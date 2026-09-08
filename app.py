from __future__ import annotations

from io import BytesIO
import hashlib
import json

import pandas as pd
import streamlit as st

from core.ingestion import extract_26as_deductor_summaries, is_detailed_26as_export, preview_raw, read_raw, read_tabular, read_tally_report, suggest_header_row, workbook_sheets
from core.aliases import load_saved_aliases
from core.mapping import FIELDS, options, suggest_columns
from core.naming import detect_financial_year, report_filename
from core.pdf_parser import parse_annual_tax_statement
from core.reconcile import reconcile
from core.reporting import audit_view, excel_report
from core.quality import quality_report
from core.review_store import export_aliases, load_local_aliases, save_alias


RECONCILIATION_STATE_VERSION = "2026-09-08-reliability-pass"

st.set_page_config(page_title="TDS / Tally Reconciliation", page_icon="✓", layout="wide")


def file_kind(upload) -> str:
    return upload.name.lower().rsplit(".", 1)[-1]


def file_signature(upload) -> tuple[str, int, str]:
    """Invalidate results when contents change, even if name and size do not."""
    upload.seek(0)
    digest = hashlib.sha256(upload.read()).hexdigest()
    upload.seek(0)
    return upload.name, upload.size, digest


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


def parse_alias_profile(upload) -> dict[str, str]:
    """Read a portable reviewer-approved alias profile without server storage."""
    if upload is None:
        return {}
    try:
        payload = json.loads(upload.getvalue().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Alias profile must be a UTF-8 JSON file of company-name pairs.") from exc
    if not isinstance(payload, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in payload.items()):
        raise ValueError("Alias profile must be a JSON object of Portal company names mapped to Tally company names.")
    return payload


SUMMARY_EXPORT_COLUMNS = {
    "sr_no": "Sr. No.",
    "deductor_name": "Name of Deductor",
    "tan": "TAN of Deductor",
    "total_amount_paid": "Total Amount Paid / Credited",
    "tax_deducted": "Total Tax Deducted",
    "tds_deposited": "Total TDS Deposited",
}


def extraction_view(summary: pd.DataFrame) -> pd.DataFrame:
    """Use the clean, human-readable 26AS Summary column layout for export."""
    return summary.loc[:, list(SUMMARY_EXPORT_COLUMNS)].rename(columns=SUMMARY_EXPORT_COLUMNS)


def summary_excel(summary: pd.DataFrame) -> bytes:
    """Create a portable extracted 26AS workbook for the next workflow step."""
    output = BytesIO()
    display = extraction_view(summary)
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        display.to_excel(writer, sheet_name="26AS Summary", index=False)
        sheet = writer.sheets["26AS Summary"]
        workbook = writer.book
        header = workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78", "align": "center", "text_wrap": True, "border": 1})
        amount = workbook.add_format({"num_format": "#,##0.00"})
        for index, column in enumerate(display.columns):
            sheet.write(0, index, column, header)
        sheet.set_column("A:A", 10)
        sheet.set_column("B:B", 50)
        sheet.set_column("C:C", 16)
        sheet.set_column("D:F", 28, amount)
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, len(display), len(display.columns) - 1)
    return output.getvalue()


def extraction_filename(extension: str, source_name: str) -> str:
    year = detect_financial_year(source_name) or "Extracted"
    return f"26AS_Deductor_Summary_{year}.{extension}"


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


workflow = st.sidebar.radio(
    "Workflow",
    ["1. Extract 26AS totals", "2. Reconcile TDS with Tally"],
)
st.sidebar.caption("Step 1 creates a clean one-row-per-deductor file. Step 2 reconciles that file with Tally.")

if workflow == "1. Extract 26AS totals":
    st.title("Extract 26AS deductor totals")
    st.caption("Upload a detailed 26AS Excel/CSV file or Annual Tax Statement PDF. Transaction rows under each deductor are ignored.")
    source_file = st.file_uploader("Upload detailed 26AS statement", type=["pdf", "xlsx", "xls", "csv"], key="extract_source")
    if source_file is None:
        st.info("Upload the 26AS source file to create a clean reconciliation-ready summary.")
        st.stop()
    try:
        if file_kind(source_file) == "pdf":
            extracted = parse_annual_tax_statement(source_file)
        else:
            sheets = [None] if file_kind(source_file) == "csv" else workbook_sheets(source_file)
            selected_sheet = sheets[0]
            if len(sheets) > 1:
                selected_sheet = st.selectbox("26AS worksheet", sheets, key="extract_sheet")
            raw = read_raw(source_file, selected_sheet)
            extracted = extract_26as_deductor_summaries(raw)
            if extracted is None:
                raise ValueError("No repeated 26AS deductor-summary headers were found. Select the worksheet containing Name of Deductor, TAN of Deductor, and Total TDS Deposited.")
    except Exception as exc:
        st.error(f"Could not extract the 26AS summary: {exc}")
        st.stop()
    clean_summary = extraction_view(extracted)
    st.success(f"Extracted {len(clean_summary)} deductor total rows. The Sr. No. 1, 2, 3 transaction rows below each deductor were ignored.")
    st.dataframe(clean_summary, width="stretch", height=460, column_config={
        "Total Amount Paid / Credited": st.column_config.NumberColumn(format="₹ %0.2f"),
        "Total Tax Deducted": st.column_config.NumberColumn(format="₹ %0.2f"),
        "Total TDS Deposited": st.column_config.NumberColumn(format="₹ %0.2f"),
    })
    st.download_button("Download extracted 26AS summary (Excel)", summary_excel(extracted), extraction_filename("xlsx", source_file.name), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.download_button("Download extracted 26AS summary (CSV)", clean_summary.to_csv(index=False).encode("utf-8"), extraction_filename("csv", source_file.name), "text/csv")
    st.info("Next: choose ‘2. Reconcile TDS with Tally’ in the sidebar, then upload this downloaded summary together with the Tally export.")
    st.stop()

st.title("TDS / Tally Reconciliation")
st.caption("No API key is required. Files are processed by this Streamlit server; keep the app local when handling confidential TDS/TAN data.")


tds_upload, tally_upload = st.columns(2)
with tds_upload:
    tds_file = st.file_uploader("1. Upload TDS statement", type=["pdf", "xlsx", "xls", "csv"], key="tds")
with tally_upload:
    tally_file = st.file_uploader("2. Upload Tally export", type=["xlsx", "xls", "csv"], key="tally")

if not (tds_file and tally_file):
    st.info("Upload both files to start. TDS can be the Annual Tax Statement PDF; Tally must be Excel or CSV.")
    st.stop()

# A Streamlit selectbox keeps its value between reruns.  A selection made for
# an earlier upload can be invalid for a newly uploaded statement, so reset
# the mapping and old results whenever either source changes.
source_fingerprint = (RECONCILIATION_STATE_VERSION, file_signature(tds_file), file_signature(tally_file))
if st.session_state.get("_reconciliation_source_fingerprint") != source_fingerprint:
    for key in [
        "tds_sheet", "tds_header", "tally_sheet", "tally_header", "results", "mapping_rows", "reconciliation_input_counts",
        *[f"TDS_{field}" for field in FIELDS],
        *[f"Tally_{field}" for field in FIELDS],
    ]:
        st.session_state.pop(key, None)
    st.session_state["_reconciliation_source_fingerprint"] = source_fingerprint

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
        # Extraction must inspect the complete worksheet.  The default preview
        # is intentionally short, but using it here previously limited a
        # 318-row uploaded summary to the first 34 deductors.
        tds_raw = read_raw(tds_file, tds_sheet)
        if is_detailed_26as_export(tds_raw):
            extracted_summary = extract_26as_deductor_summaries(tds_raw)
            if extracted_summary is None:
                st.error("The detailed 26AS export could not be converted into deductor totals.")
                st.stop()
            tds = extracted_summary
            st.success(f"Detailed 26AS export recognized. Extracted {len(tds)} deductor total rows; transaction rows were ignored.")
            st.dataframe(tds.head(20), width="stretch")
        else:
            tds_header = st.number_input("TDS header row (zero-based)", 0, max(0, len(tds_raw) - 1), tds_header, key="tds_header")
            st.dataframe(preview_for_display(tds_raw), width="stretch")
            tds = read_tabular(tds_file, tds_sheet, tds_header)
            st.success("Reconciliation-ready 26AS summary recognized. It is used directly without re-extraction.")
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

st.info(f"Loaded {len(tds):,} TDS deductor records and {len(tally):,} Tally ledger records. Verify these counts before approving the mapping.")
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

source_quality_has_error = False
if all(value != "-- Not mapped --" for value in [tds_mapping["party_name"], tds_mapping["tax_amount"], tally_mapping["party_name"], tally_mapping["tax_amount"]]):
    with st.expander("Source quality checks", expanded=False):
        tds_checks = pd.DataFrame(quality_report(tds, tds_mapping["party_name"], tds_mapping["tax_amount"], None if tds_mapping["tan"] == "-- Not mapped --" else tds_mapping["tan"]))
        tally_checks = pd.DataFrame(quality_report(tally, tally_mapping["party_name"], tally_mapping["tax_amount"]))
        check_left, check_right = st.columns(2)
        with check_left:
            st.markdown("**TDS checks**")
            st.dataframe(tds_checks, width="stretch", hide_index=True)
        with check_right:
            st.markdown("**Tally checks**")
            st.dataframe(tally_checks, width="stretch", hide_index=True)
        source_quality_has_error = bool((tds_checks.loc[tds_checks["severity"] == "Error", "count"] > 0).any() or (tally_checks.loc[tally_checks["severity"] == "Error", "count"] > 0).any())
        if source_quality_has_error:
            st.warning("Blank party-name rows were found. They will be ignored during reconciliation; review the source checks if this was not expected.")

st.subheader("Reconcile")
tolerance = st.number_input("Allowed amount difference", min_value=0.0, value=1.0, step=1.0)
relative_tolerance = st.number_input("Allowed percentage difference", min_value=0.0, value=0.0, step=0.1, help="A match is accepted when it is within either the absolute or percentage allowance.")
threshold = st.slider("Partial-match name confidence threshold", 60, 100, 78)
max_aggregate_rows = st.slider("Maximum same-party Tally rows to aggregate", 1, 16, 8, help="Use a higher value only when a single deductor is commonly split across many ledger rows.")
alias_text = st.text_area(
    "Approved company aliases (optional)",
    placeholder="Portal company name = Tally ledger name\n3D ENGINEERING AUTOMATION LLP = 3D ENGINEERING / TDS 2024-25",
    help="Use one confirmed mapping per line. These remain auditable as ‘Approved alias’ matches.",
)
alias_profile_file = st.file_uploader("Load approved aliases profile (optional)", type=["json"], help="Use the downloaded profile to reuse confirmed aliases on another computer or after a restart.")
try:
    saved_aliases = load_saved_aliases()
except ValueError as exc:
    st.error(f"Could not read saved company aliases: {exc}")
    st.stop()
if saved_aliases:
    st.caption(f"{len(saved_aliases)} locally saved, reviewer-approved company aliases will be applied automatically.")
local_aliases = load_local_aliases(financial_year)
if local_aliases:
    st.caption(f"{len(local_aliases)} reviewer-approved aliases from this computer will be applied for {financial_year or 'all years'}.")
try:
    uploaded_aliases = parse_alias_profile(alias_profile_file)
    typed_aliases_preview = parse_aliases(alias_text)
except ValueError as exc:
    st.error(f"Could not read approved aliases: {exc}")
    st.stop()
if uploaded_aliases:
    st.caption(f"{len(uploaded_aliases)} approved aliases loaded from the selected profile.")
profile_for_download = {**saved_aliases, **local_aliases, **uploaded_aliases, **typed_aliases_preview}
st.download_button("Download approved aliases profile", json.dumps(profile_for_download, indent=2, sort_keys=True).encode("utf-8"), "tds_tally_approved_aliases.json", "application/json")
required = [tds_mapping["party_name"], tds_mapping["tax_amount"], tally_mapping["party_name"], tally_mapping["tax_amount"]]
if any(value == "-- Not mapped --" for value in required):
    st.warning("Map Party Name and Tax Amount on both sides to enable reconciliation.")
    st.stop()
if tds_mapping["party_name"] == tds_mapping["tax_amount"] or tally_mapping["party_name"] == tally_mapping["tax_amount"]:
    st.error("Party Name and Tax Amount must be two different columns on each side.")
    st.stop()
st.caption("Party Name and Tax Amount drive matching. TAN is retained for audit; Date, Section and Total Amount are optional reference mappings.")

run_signature = json.dumps({
    "source": source_fingerprint,
    "tds": tds_mapping,
    "tally": tally_mapping,
    "tolerance": tolerance,
    "relative_tolerance": relative_tolerance,
    "threshold": threshold,
    "max_aggregate_rows": max_aggregate_rows,
    "aliases": [alias_text, uploaded_aliases],
}, sort_keys=True, default=str)

if st.button("Approve mapping and reconcile", type="primary"):
    try:
        approved_aliases = {**saved_aliases, **local_aliases, **uploaded_aliases, **typed_aliases_preview}
    except ValueError as exc:
        st.error(f"Could not read aliases: {exc}")
        st.stop()
    try:
        results = reconcile(
            tds, tally,
            tds_mapping["party_name"], tds_mapping["tax_amount"],
            tally_mapping["party_name"], tally_mapping["tax_amount"],
            tds_tan_col=None if tds_mapping["tan"] == "-- Not mapped --" else tds_mapping["tan"],
            approved_aliases=approved_aliases,
            amount_tolerance=tolerance, partial_threshold=float(threshold), relative_tolerance_pct=relative_tolerance,
            max_aggregate_rows=max_aggregate_rows,
        )
    except Exception as exc:
        st.error(f"Reconciliation could not run: {exc}")
        st.stop()
    st.session_state["results"] = results
    st.session_state["mapping_rows"] = [
        {"canonical_field": field, "tds_column": tds_mapping[field], "tally_column": tally_mapping[field]}
        for field in FIELDS
    ]
    st.session_state["reconciliation_input_counts"] = {"tds": len(tds), "tally": len(tally)}
    st.session_state["reconciliation_metadata"] = {
        "financial_year": financial_year or "Not detected", "absolute_tolerance": tolerance,
        "relative_tolerance_pct": relative_tolerance, "partial_threshold": threshold,
        "max_aggregate_rows": max_aggregate_rows, "tds_file": tds_file.name, "tally_file": tally_file.name,
    }
    st.session_state["reconciliation_run_signature"] = run_signature

if "results" in st.session_state and st.session_state.get("reconciliation_run_signature") == run_signature:
    results = st.session_state["results"]
    st.subheader("Tally vs Portal Match")
    input_counts = st.session_state.get("reconciliation_input_counts", {})
    tds_count = input_counts.get("tds")
    tally_count = input_counts.get("tally")
    if isinstance(tds_count, int) and isinstance(tally_count, int):
        st.caption(f"This result was generated from {tds_count:,} TDS records and {tally_count:,} Tally records.")
    else:
        st.caption("This result was generated before input-count tracking. Approve the mapping again to refresh it.")
    metrics = results["status"].value_counts()
    cards = st.columns(6)
    for card, status in zip(cards, ["Total match", "Approved alias", "Partial match", "Needs review", "No match", "No match in TDS"]):
        card.metric(status, int(metrics.get(status, 0)))
    matched_value = results.loc[results["status"].isin(["Total match", "Approved alias"]), "tds_tax_amount"].sum()
    portal_value = results["tds_tax_amount"].sum()
    dashboard_left, dashboard_mid, dashboard_right = st.columns(3)
    dashboard_left.metric("Portal value reconciled", f"₹ {matched_value:,.2f}")
    dashboard_mid.metric("Portal value in scope", f"₹ {portal_value:,.2f}")
    dashboard_right.metric("Exact/approved rate", f"{(100 * metrics.get('Total match', 0) + 100 * metrics.get('Approved alias', 0)) / max(1, len(results[results['tds_party'].notna()])):.1f}%")
    selected_statuses = st.multiselect("Filter statuses", sorted(results["status"].unique()), default=sorted(results["status"].unique()))
    tally_amount_label = f"{tally_mapping['tax_amount']} Amount Rs. (Tally)"
    display = audit_view(results[results["status"].isin(selected_statuses)], tally_amount_label)
    st.dataframe(display, width="stretch", height=420, column_config={
        "Total TDS Deposited Rs. (Portal)": st.column_config.NumberColumn(format="₹ %0.2f"),
        tally_amount_label: st.column_config.NumberColumn(format="₹ %0.2f"),
    })
    report = excel_report(results, st.session_state["mapping_rows"], tally_amount_label, st.session_state.get("reconciliation_metadata"))
    excel_name = report_filename("xlsx", tally_file.name, tds_file.name)
    csv_name = report_filename("csv", tally_file.name, tds_file.name)
    st.download_button("Download Excel audit report", report, excel_name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.download_button("Download all results CSV", results.to_csv(index=False).encode("utf-8"), csv_name, "text/csv")

    reviewable = results.loc[results["tds_party"].notna() & results["status"].isin(["Needs review", "Partial match", "No match"])].copy()
    if not reviewable.empty:
        st.subheader("Reviewer decision queue")
        st.caption("Confirm a Portal-to-Tally relationship here to store a local, year-aware alias. The app will then require a fresh reconciliation run.")
        review_labels = {f"Row {index + 1}: {row.tds_party} — {row.status}": row.tds_party for index, row in reviewable.iterrows()}
        with st.form("review_decision"):
            selected_review = st.selectbox("Portal company requiring review", list(review_labels))
            selected_tally = st.selectbox("Verified Tally company", sorted(tally[tally_mapping["party_name"]].dropna().astype(str).unique()))
            reviewer_name = st.text_input("Reviewer name (optional)")
            decision_reason = st.text_input("Decision note", value="Verified against source records")
            save_decision = st.form_submit_button("Save approved alias")
        if save_decision:
            save_alias(review_labels[selected_review], selected_tally, financial_year, reviewer_name, decision_reason)
            st.session_state.pop("results", None)
            st.success("Approved alias saved locally. Reconcile again to apply it.")
            st.rerun()
    local_decisions = export_aliases()
    if local_decisions:
        with st.expander("Local reviewer decision audit", expanded=False):
            st.dataframe(pd.DataFrame(local_decisions), width="stretch", hide_index=True)
elif "results" in st.session_state:
    st.info("Settings changed after the last run. Approve mapping and reconcile again before viewing or downloading a result.")
