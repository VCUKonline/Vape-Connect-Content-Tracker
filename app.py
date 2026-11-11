from pathlib import Path
import json
import re
import subprocess
import sys
import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent
INPUT = BASE / "data" / "input"
OUTPUT = BASE / "data" / "output"
STATUS_FILE = OUTPUT / "issue_review_status.csv"
NA_FILE = OUTPUT / "not_applicable_issues.csv"

st.set_page_config(page_title="Vape Connect Content Auditor", page_icon="🔎", layout="wide")
st.markdown("""
<style>
.stApp {background:#0d0d0f;color:#f5f5f5}
.vc-title {font-size:2.35rem;font-weight:850;line-height:1.08;margin-bottom:0.2rem}
.vc-title .white{color:#f7f7f7}.vc-title .red{color:#ef4444}
div[data-testid="stMetric"]{background:#19191d;border:1px solid #38383f;padding:13px 16px;border-radius:12px}
section[data-testid="stSidebar"]{background:#151519}
</style>
<div class="vc-title"><span class="white">VAPE CONNECT</span><br><span class="red">Content Auditor</span></div>
<p style="color:#aaa">Stage 2 · Basic rule-based checks · No AI or OpenAI API required · Read-only</p>
""", unsafe_allow_html=True)

@st.cache_data
def load_csv(path):
    return pd.read_csv(path,dtype=str,keep_default_na=False) if path.exists() else pd.DataFrame()

# Streamlit Cloud starts the dashboard directly, so generate the first audit
# automatically when the output files are not yet present.
OUTPUT.mkdir(parents=True, exist_ok=True)
required_outputs = [
    OUTPUT / "stage2_product_audit.csv",
    OUTPUT / "stage2_content_issues.csv",
    OUTPUT / "stage2_variant_checks.csv",
]
if not all(path.exists() for path in required_outputs):
    with st.spinner("First launch: running the rule-based audit for all eligible products..."):
        run = subprocess.run(
            [sys.executable, str(BASE / "run_stage2.py"), "--all"],
            cwd=BASE, capture_output=True, text=True
        )
    if run.returncode != 0:
        st.error("The initial audit could not be completed.")
        st.code(run.stderr or run.stdout)
        st.stop()

products=load_csv(OUTPUT/"stage2_product_audit.csv")
issues=load_csv(OUTPUT/"stage2_content_issues.csv")
variants=load_csv(OUTPUT/"stage2_variant_checks.csv")
source_products=load_csv(INPUT/"eligible_products.csv")
source_variants=load_csv(INPUT/"eligible_variants.csv")
if products.empty:
    st.warning("No audit results were produced. Check the Stage 1 input CSV files.")
    st.stop()

for frame,col in [(issues,"product_id"),(variants,"product_id"),(products,"product_id")]:
    if col in frame.columns: frame[col]=frame[col].astype(str)

# Stable issue keys allow statuses to persist between app sessions.
def make_key(row, kind):
    parts=[kind,str(row.get('product_id','')),str(row.get('category',row.get('option_name',''))),str(row.get('issue',row.get('finding',''))),str(row.get('evidence',row.get('option_value','')))]
    return "|".join(parts)

if not issues.empty:
    issues=issues.copy(); issues['kind']='Content'; issues['issue_key']=issues.apply(lambda r:make_key(r,'Content'),axis=1)
if not variants.empty:
    v=variants.copy(); v['category']='Variant review'; v['issue']=v.get('finding',''); v['evidence']=v.get('option_name','').astype(str)+': '+v.get('option_value','').astype(str); v['recommendation']=v.get('note',''); v['kind']='Variant'; v['issue_key']=v.apply(lambda r:make_key(r,'Variant'),axis=1)
    all_issues=pd.concat([issues,v],ignore_index=True,sort=False)
else: all_issues=issues.copy()

# Load and persist review state; this is an operational review log, not audit history.
def read_state(path, cols):
    return pd.read_csv(path,dtype=str,keep_default_na=False) if path.exists() else pd.DataFrame(columns=cols)
state=read_state(STATUS_FILE,['issue_key','status','review_note'])
na=read_state(NA_FILE,['product_id','category'])
if not all_issues.empty:
    all_issues=all_issues.merge(state[['issue_key','status','review_note']] if not state.empty else pd.DataFrame(columns=['issue_key','status','review_note']),on='issue_key',how='left')
    all_issues['status']=all_issues['status'].fillna('Open').replace('','Open')
    all_issues['review_note']=all_issues['review_note'].fillna('')
    if not na.empty:
        na_keys=set(zip(na.product_id.astype(str),na.category.astype(str)))
        all_issues=all_issues[~all_issues.apply(lambda r:(str(r.product_id),str(r.category)) in na_keys,axis=1)]

st.sidebar.header("Filters")
brands=sorted(products.get('brand',pd.Series(dtype=str)).replace('', 'Unspecified').unique().tolist())
selected_brands=st.sidebar.multiselect('Brand',brands,default=brands)
category_options=sorted(all_issues.get('category',pd.Series(dtype=str)).dropna().unique().tolist())
selected_categories=st.sidebar.multiselect('Issue category',category_options,default=category_options)
severity_options=sorted(all_issues.get('severity',pd.Series(dtype=str)).dropna().unique().tolist())
selected_severity=st.sidebar.multiselect('Severity',severity_options,default=severity_options)
status_options=['Open','Reviewed - valid','Resolved']
selected_status=st.sidebar.multiselect('Review status',status_options,default=status_options)

filtered_products=products.copy()
if selected_brands: filtered_products=filtered_products[filtered_products['brand'].replace('', 'Unspecified').isin(selected_brands)]
else: filtered_products=filtered_products.iloc[0:0]
filtered_ids=set(filtered_products.product_id.astype(str))
filtered_issues=all_issues[all_issues.product_id.astype(str).isin(filtered_ids)].copy() if not all_issues.empty else all_issues.copy()
if selected_categories: filtered_issues=filtered_issues[filtered_issues.category.isin(selected_categories)]
else: filtered_issues=filtered_issues.iloc[0:0]
if selected_severity and 'severity' in filtered_issues: filtered_issues=filtered_issues[filtered_issues.severity.isin(selected_severity)]
if selected_status: filtered_issues=filtered_issues[filtered_issues.status.isin(selected_status)]
else: filtered_issues=filtered_issues.iloc[0:0]

products_with_issues=filtered_issues.product_id.nunique() if not filtered_issues.empty else 0
c1,c2,c3,c4=st.columns(4)
c1.metric('Products audited',f"{len(filtered_products):,}")
c2.metric('Products with open/review findings',f"{products_with_issues:,}")
c3.metric('Visible findings',f"{len(filtered_issues):,}")
c4.metric('Products without findings',f"{max(0,len(filtered_products)-products_with_issues):,}")

st.subheader('Issue overview')
if filtered_issues.empty: st.info('No findings match the current filters.')
else:
    cat_counts=filtered_issues.groupby('category').size().sort_values(ascending=False).rename('Findings').reset_index()
    st.bar_chart(cat_counts.set_index('category'))

st.subheader('Products with issues')
if filtered_issues.empty:
    st.caption('No products to display for the selected filters.')
else:
    counts=filtered_issues.groupby(['product_id','product_name']).agg(Findings=('issue_key','count'),Open=('status',lambda x:int((x=='Open').sum()))).reset_index()
    product_lookup=filtered_products.set_index('product_id')
    counts['Brand']=counts.product_id.map(product_lookup.brand.to_dict()).fillna('')
    counts=counts[['product_name','Brand','Findings','Open','product_id']].rename(columns={'product_name':'Product'})
    st.dataframe(counts.drop(columns=['product_id']),use_container_width=True,hide_index=True)
    choices={f"{r['product_name']}  |  {r['Brand']}  |  {r['Findings']} findings":str(r['product_id']) for _,r in counts.iterrows()}
    selected_label=st.selectbox('Select a product to inspect',list(choices.keys()))
    selected_id=choices[selected_label]
    detail=filtered_products[filtered_products.product_id.astype(str)==selected_id].iloc[0]
    detail_issues=all_issues[all_issues.product_id.astype(str)==selected_id].copy()
    st.divider(); st.subheader(str(detail.get('product_name','Product details')))
    st.caption(f"Brand: {detail.get('brand','')}  ·  Variants: {detail.get('variant_count','')}  ·  Completeness indicator: {detail.get('description_score','')}/100")
    url=str(detail.get('product_url','')).strip()
    if url: st.markdown(f"[Open product page]({url})")
    if not source_products.empty and 'product_id' in source_products:
        src=source_products[source_products.product_id.astype(str)==selected_id]
        if not src.empty:
            raw_html=str(src.iloc[0].get('description_html',''))
            with st.expander('Original Shopify description (unchanged source)'):
                st.code(raw_html if raw_html else '(Empty description)',language='html')
            with st.expander('SEO fields'):
                st.write('SEO title:',src.iloc[0].get('seo_title',''))
                st.write('SEO description:',src.iloc[0].get('seo_description',''))
    st.markdown('**Detailed findings and review controls**')
    if detail_issues.empty: st.success('No active findings remain for this product.')
    else:
        for ix,row in detail_issues.iterrows():
            with st.container(border=True):
                st.markdown(f"**{row.get('category','')}** · {row.get('severity','Info')} · {row.get('status','Open')}")
                st.write(str(row.get('issue','')))
                st.caption('Evidence: '+str(row.get('evidence','')))
                st.caption('Suggested review: '+str(row.get('recommendation','')))
                k=str(row['issue_key'])
                current=str(row.get('status','Open'))
                status=st.selectbox('Review status',status_options,index=status_options.index(current) if current in status_options else 0,key='status_'+str(ix))
                note=st.text_input('Reviewer note (optional)',value=str(row.get('review_note','')),key='note_'+str(ix))
                if st.button('Save review',key='save_'+str(ix)):
                    state=state[state.issue_key!=k] if not state.empty else state
                    state=pd.concat([state,pd.DataFrame([{'issue_key':k,'status':status,'review_note':note}])],ignore_index=True)
                    state.to_csv(STATUS_FILE,index=False,encoding='utf-8-sig')
                    st.cache_data.clear(); st.success('Review status saved.'); st.rerun()
    st.markdown('**Mark a finding category as not applicable for this product**')
    product_categories=sorted(detail_issues.category.dropna().astype(str).unique().tolist()) if not detail_issues.empty else category_options
    if product_categories:
        na_category=st.selectbox('Not-applicable category',product_categories,key='na_cat')
        if st.button('Mark category not applicable for this product'):
            na=na[~((na.product_id.astype(str)==selected_id)&(na.category.astype(str)==na_category))] if not na.empty else na
            na=pd.concat([na,pd.DataFrame([{'product_id':selected_id,'category':na_category}])],ignore_index=True)
            na.to_csv(NA_FILE,index=False,encoding='utf-8-sig')
            st.cache_data.clear(); st.success('Category excluded for this product.'); st.rerun()

st.subheader('Download')
if not filtered_issues.empty:
    st.download_button('Download filtered findings CSV',filtered_issues.drop(columns=['issue_key'],errors='ignore').to_csv(index=False).encode('utf-8-sig'),'content_audit_findings.csv','text/csv')
if not filtered_products.empty:
    st.download_button('Download product summary CSV',filtered_products.to_csv(index=False).encode('utf-8-sig'),'content_audit_products.csv','text/csv')
st.caption('Review statuses and product-specific not-applicable decisions are saved locally in data/output/. Historical audit reports are not retained. Findings are rule-based prompts for human review, not confirmed errors.')
