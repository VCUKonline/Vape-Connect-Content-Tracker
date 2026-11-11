# Vape Connect Content Auditor

## GitHub upload (flat-file version)
Upload every file in this folder directly into the repository root. Do not create folders. Keep all filenames unchanged.

## Streamlit Community Cloud
- Main file path: `app.py`
- Python: 3.13 compatible
- No AI or OpenAI API key is required.

## Files
- `app.py`: Streamlit dashboard
- `run_stage2.py`: rule-based audit runner
- `eligible_products.csv`, `eligible_variants.csv`: Stage 1 input exports
- `stage2_*.csv` and `stage2_summary.json`: generated audit outputs
- `requirements.txt`: Python dependencies

All CSV/JSON files are stored in the repository root in this flat deployment. The app and audit runner have been updated to read and write those root-level files.

## Run locally
```bash
py -3.13 -m pip install -r requirements.txt
py -3.13 run_stage2.py --all
py -3.13 -m streamlit run app.py
```

Review statuses and product-specific not-applicable decisions are saved as root-level CSV files. Streamlit Community Cloud's local filesystem is not durable across restarts or redeployments; export/back up review data if it must be retained. Historical audit reports are not retained. Findings are rule-based prompts for human review, not confirmed errors or legal/regulatory assessments.
