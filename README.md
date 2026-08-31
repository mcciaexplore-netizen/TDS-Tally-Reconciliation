# Offline TDS / Tally Reconciliation

Local-first Streamlit application for reconciling an Annual Tax Statement (PDF, Excel, or CSV) with a Tally export (Excel or CSV).

## What it does

- Reads files only in the running browser session; it does not upload them to a cloud service.
- Detects spreadsheet headers and proposes column mappings automatically.
- Requires a human to verify or amend every suggested mapping before reconciliation.
- Normalizes party names, ledger suffixes, whitespace, punctuation, and numeric values.
- Classifies results as `Total match`, `Partial match`, `Needs review`, or `No match`; similar-name candidates always require human approval.
- Exports a traceable Excel workbook and CSV result files.

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL shown by Streamlit. No API keys are needed.

## Current scope

The supplied Tally `Cost Centre Summary` is an aggregate-by-party report. It is reconciled against PDF deductor totals by party and TDS amount. For voucher-level reconciliation, upload a Tally voucher/register export containing party, voucher number, date, and TDS amount.
