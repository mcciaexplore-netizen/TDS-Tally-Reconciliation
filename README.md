# Offline TDS / Tally Reconciliation

Local-first Streamlit application for reconciling an Annual Tax Statement (PDF, Excel, or CSV) with a Tally export (Excel or CSV).

## What it does

- No API key is required. Files are processed by the Streamlit server: run it on your own computer for confidential TDS/TAN data. Do not upload confidential files to a public deployment.
- Detects spreadsheet headers and proposes column mappings automatically.
- Requires a human to verify or amend every suggested mapping before reconciliation.
- Normalizes party names, ledger suffixes, whitespace, punctuation, and numeric values.
- Classifies results as `Total match`, `Partial match`, `Needs review`, or `No match`; similar-name candidates always require human approval.
- Exports a traceable Excel workbook and CSV result files.

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL shown by Streamlit. No API keys are needed.

## Current scope

The supplied Tally `Cost Centre Summary` is reconciled against deductor totals by party and TDS amount. When the same party has several Tally lines, the app can aggregate up to eight same-name lines to the portal total and records the source rows in the audit report. Fuzzy name matches are always marked for human review.
