# Vape Connect Content Auditor

A read-only, rule-based Shopify catalogue content audit dashboard. No OpenAI API key, AI service, Shopify credentials, or write access is required.

## Deploy to Streamlit Community Cloud

1. Download and extract this ZIP.
2. Create a new GitHub repository.
3. Upload the **contents** of the extracted `vape_connect_content_auditor_stage2_rules` folder to the repository root (so `app.py` is at the root).
4. In Streamlit Community Cloud, choose **New app** and connect the repository.
5. Set **Main file path** to `app.py`, then deploy.

The ZIP includes the Stage 1 input CSVs and a pre-generated audit of all 317 eligible products. The dashboard should therefore load without needing a separate first-run command.

## Run locally

Use Python 3.13:

```bat
py -3.13 -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
streamlit run app.py
```

To regenerate the audit from the included Stage 1 CSVs:

```bat
python run_stage2.py --all
```

## Dashboard features

- KPI summary and issue-category chart
- Brand, issue category, severity and review-status filters
- Product dropdown navigation to detailed findings
- Original Shopify description and SEO fields shown as source evidence
- Review states: Open, Reviewed - valid, Resolved
- Reviewer notes and product-specific not-applicable categories
- CSV downloads for findings and product summaries

## Punctuation normalization

Whitespace immediately before `. , ! ? ; :` is normalized only in the temporary analysis text. It is not reported as a grammar issue. The source HTML and Shopify content are never edited.

## Important limitations

- Findings are deterministic review prompts, not confirmed errors or legal/regulatory assessments.
- Variant option checks use literal matching and are informational.
- The dashboard is read-only and does not connect to Shopify.
- Review-state CSVs are written under `data/output/`. Streamlit Community Cloud's local filesystem is not a durable database; export or back up review data if it must be retained across redeployments.
- This project does not retain historical audit reports.
