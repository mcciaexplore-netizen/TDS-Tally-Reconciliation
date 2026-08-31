from __future__ import annotations

import pandas as pd
import streamlit as st

from core.ingestion import preview_raw, read_tabular, read_tally_report, suggest_header_row, workbook_sheets
from core.mapping import FIELDS, options, suggest_columns
from core.naming import detect_financial_year, report_filename
from core.pdf_parser import parse_annual_tax_statement
from core.reconcile import reconcile
from core.reporting import audit_view, excel_report


st.set_page_config(page_title="TDS / Tally Reconciliation", page_icon="✓", layout="wide")
st.title("TDS / Tally Reconciliation")
st.caption("Runs locally in this browser session. No API key, cloud upload, or permanent file storage.")


def file_kind(upload) -> str:
    return upload.name.lower().rsplit(".", 1)[-1]


def preview_for_display(frame: pd.DataFrame) -> pd.DataFrame:
    """Avoid Arrow conversion errors from report previews with mixed cell types."""
    return frame.astype(object).where(frame.notna(), "").astype(str)


def parse_aliases(text: str) -> dict[str, str]:
    """Parse reviewer-approved aliases: Portal company = Tally ledger name."""
    aliases = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Each alias must use: Portal company name = Tally ledger name")
        portal_name, tally_name = (part.strip() for part in line.split("=", 1))
        if not portal_name or not tally_name:
            raise ValueError("Both sides of every alias must contain a company name")
        aliases[portal_name] = tally_name
    return aliases


def load_source(upload, label: str):
    kind = file_kind(upload)
    if kind == "pdf":
        if label != "TDS":
            raise ValueError("Tally upload must be Excel or CSV.")
        return parse_annual_tax_statement(upload), None, 0
    sheets = [None] if kind == "csv" else workbook_sheets(upload)
    selected_sheet = sheets[0]
    raw = preview_raw(upload, selected_sheet)
    return None, (selected_sheet, raw), suggest_header_row(raw)


tds_upload, tally_upload = st.columns(2)
with tds_upload:
    tds_file = st.file_uploader("1. Upload TDS statement", type=["pdf", "xlsx", "xls", "csv"], key="tds")
with tally_upload:
    tally_file = st.file_uploader("2. Upload Tally export", type=["xlsx", "xls", "csv"], key="tally")

if not (tds_file and tally_file):
    st.info("Upload both files to start. TDS can be the Annual Tax Statement PDF; Tally must be Excel or CSV.")
    st.stop()

# Tally filenames commonly carry the financial year; use it first, then TDS.
financial_year = detect_financial_year(tally_file.name, tds_file.name)

try:
    tds_initial, tds_book, tds_header = load_source(tds_file, "TDS")
    _, tally_book, tally_header = load_source(tally_file, "Tally")
except Exception as exc:
    st.error(f"Could not read the uploaded file: {exc}")
    st.stop()

st.subheader("Preview and header detection")
left, right = st.columns(2)
with left:
    st.markdown("#### TDS source")
    if tds_initial is not None:
        tds = tds_initial
        st.success("Annual Tax Statement PDF recognized. Deductor summary rows extracted.")
        st.dataframe(tds.head(20), width="stretch")
    else:
        tds_sheet, tds_raw = tds_book
        if file_kind(tds_file) != "csv":
            tds_sheet = st.selectbox("TDS worksheet", workbook_sheets(tds_file), key="tds_sheet")
            tds_raw = preview_raw(tds_file, tds_sheet)
        tds_header = st.number_input("TDS header row (zero-based)", 0, max(0, len(tds_raw) - 1), tds_header, key="tds_header")
        st.dataframe(preview_for_display(tds_raw), width="stretch")
        tds = read_tabular(tds_file, tds_sheet, tds_header)
with right:
    st.markdown("#### Tally source")
    tally_sheet, tally_raw = tally_book
    if file_kind(tally_file) != "csv":
        tally_sheet = st.selectbox("Tally worksheet", workbook_sheets(tally_file), key="tally_sheet")
        tally_raw = preview_raw(tally_file, tally_sheet)
    tally_header = st.number_input("Tally header row (zero-based)", 0, max(0, len(tally_raw) - 1), tally_header, key="tally_header")
    st.dataframe(preview_for_display(tally_raw), width="stretch")
    tally = read_tally_report(tally_file, tally_sheet, tally_header)
    st.caption("When a Tally Cost Centre Summary split header is detected, the app automatically combines its `Particulars` and `Debit/Credit/Balance` header rows.")

st.subheader("Automatic column mapping - verify before continuing")
st.write("Suggested mappings are generated from headers and data shape. Confirm them here; no reconciliation runs until you approve.")
tds_suggestions, tally_suggestions = suggest_columns(tds), suggest_columns(tally)


def mapping_picker(title: str, frame: pd.DataFrame, suggestions):
    st.markdown(f"#### {title}")
    chosen = {}
    choices = options(frame)
    for field in FIELDS:
        suggestion = suggestions[field]
        default = suggestion.column if suggestion.column in choices else "-- Not mapped --"
        position = choices.index(default)
        chosen[field] = st.selectbox(
            f"{field.replace('_', ' ').title()} ({suggestion.confidence} confidence)",
            choices, index=position, key=f"{title}_{field}",
        )
    return chosen

map_left, map_right = st.columns(2)
with map_left:
    tds_mapping = mapping_picker("TDS", tds, tds_suggestions)
with map_right:
    tally_mapping = mapping_picker("Tally", tally, tally_suggestions)

st.subheader("Reconcile")
tolerance = st.number_input("Allowed amount difference", min_value=0.0, value=1.0, step=1.0)
threshold = st.slider("Partial-match name confidence threshold", 60, 100, 78)
alias_text = st.text_area(
    "Approved company aliases (optional)",
    placeholder="Portal company name = Tally ledger name\n3D ENGINEERING AUTOMATION LLP = 3D ENGINEERING / TDS 2024-25",
    help="Use one confirmed mapping per line. These remain auditable as ‘Approved alias’ matches.",
)
required = [tds_mapping["party_name"], tds_mapping["tax_amount"], tally_mapping["party_name"], tally_mapping["tax_amount"]]
if any(value == "-- Not mapped --" for value in required):
    st.warning("Map Party Name and Tax Amount on both sides to enable reconciliation.")
    st.stop()

if st.button("Approve mapping and reconcile", type="primary"):
    try:
        approved_aliases = parse_aliases(alias_text)
    except ValueError as exc:
        st.error(f"Could not read aliases: {exc}")
        st.stop()
    results = reconcile(
        tds, tally,
        tds_mapping["party_name"], tds_mapping["tax_amount"],
        tally_mapping["party_name"], tally_mapping["tax_amount"],
        tds_tan_col=None if tds_mapping["tan"] == "-- Not mapped --" else tds_mapping["tan"],
        approved_aliases=approved_aliases,
        amount_tolerance=tolerance, partial_threshold=float(threshold),
    )
    st.session_state["results"] = results
    st.session_state["mapping_rows"] = [
        {"canonical_field": field, "tds_column": tds_mapping[field], "tally_column": tally_mapping[field]}
        for field in FIELDS
    ]

if "results" in st.session_state:
    results = st.session_state["results"]
    st.subheader("Tally vs Portal Match")
    metrics = results["status"].value_counts()
    cards = st.columns(6)
    for card, status in zip(cards, ["Total match", "Approved alias", "Partial match", "Needs review", "No match", "No match in TDS"]):
        card.metric(status, int(metrics.get(status, 0)))
    selected_statuses = st.multiselect("Filter statuses", sorted(results["status"].unique()), default=sorted(results["status"].unique()))
    display = audit_view(results[results["status"].isin(selected_statuses)])
    st.dataframe(display, width="stretch", height=420, column_config={
        "Total TDS Deposited Rs. (Portal)": st.column_config.NumberColumn(format="₹ %0.2f"),
        "Debit Amount Rs. (Tally)": st.column_config.NumberColumn(format="₹ %0.2f"),
    })
    report = excel_report(results, st.session_state["mapping_rows"])
    excel_name = report_filename("xlsx", tally_file.name, tds_file.name)
    csv_name = report_filename("csv", tally_file.name, tds_file.name)
    st.download_button("Download Excel audit report", report, excel_name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.download_button("Download all results CSV", results.to_csv(index=False).encode("utf-8"), csv_name, "text/csv")
