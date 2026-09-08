from __future__ import annotations

from io import BytesIO
from typing import BinaryIO
import re

import pandas as pd


MAX_PROCESSING_ROWS = 100_000


def _source_bytes(uploaded: BinaryIO) -> BytesIO:
    """Copy an uploaded file only to in-memory storage for the active session."""
    uploaded.seek(0)
    return BytesIO(uploaded.read())


def workbook_sheets(uploaded: BinaryIO) -> list[str]:
    raw = _source_bytes(uploaded)
    return pd.ExcelFile(raw).sheet_names


def read_tabular(uploaded: BinaryIO, sheet_name: str | None = None, header_row: int = 0) -> pd.DataFrame:
    raw = _source_bytes(uploaded)
    filename = getattr(uploaded, "name", "").lower()
    if filename.endswith(".csv"):
        frame = pd.read_csv(raw, header=header_row)
    else:
        frame = pd.read_excel(raw, sheet_name=sheet_name, header=header_row)
    if len(frame) > MAX_PROCESSING_ROWS:
        raise ValueError(f"This sheet contains {len(frame):,} rows. Split it before processing; the safe limit is {MAX_PROCESSING_ROWS:,} rows.")
    return frame


def tally_header_rows(raw: pd.DataFrame) -> tuple[int, int] | None:
    """Detect Tally's three-line Cost Centre Summary header layout."""
    for index in range(max(0, len(raw) - 3)):
        current = " ".join(str(value).lower() for value in raw.iloc[index].dropna())
        following = " ".join(str(value).lower() for value in raw.iloc[index + 1 : index + 4].fillna("").to_numpy().flatten())
        if "particulars" in current and {"debit", "credit", "balance"}.issubset(following.split()):
            for detail_row in range(index + 1, min(index + 4, len(raw))):
                values = {str(value).strip().lower() for value in raw.iloc[detail_row].dropna()}
                if {"debit", "credit", "balance"}.issubset(values):
                    return index, detail_row
    return None


def read_tally_report(uploaded: BinaryIO, sheet_name: str | None = None, header_row: int = 0) -> pd.DataFrame:
    """Read normal tables and join split Tally report headings when recognised."""
    # Read the complete report for reconciliation. Previews remain short, but
    # processing must never silently drop records after an arbitrary row cap.
    raw = read_raw(uploaded, sheet_name)
    split = tally_header_rows(raw)
    # A reviewer-selected header row is authoritative. Only use the special
    # split Tally layout when they retain its detected primary header row.
    if not split or header_row != split[0]:
        return read_tabular(uploaded, sheet_name, header_row)
    primary_row, detail_row = split
    primary = raw.iloc[primary_row].fillna("").astype(str).str.strip().tolist()
    detail = raw.iloc[detail_row].fillna("").astype(str).str.strip().tolist()
    columns = [detail_value or primary_value or f"Column {index + 1}" for index, (primary_value, detail_value) in enumerate(zip(primary, detail))]
    data = raw.iloc[detail_row + 1 :].copy()
    data.columns = columns
    data = data.dropna(how="all").reset_index(drop=True)
    if len(data) > MAX_PROCESSING_ROWS:
        raise ValueError(f"This sheet contains {len(data):,} rows. Split it before processing; the safe limit is {MAX_PROCESSING_ROWS:,} rows.")
    return data


def _header_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _summary_columns(row: pd.Series) -> dict[str, int] | None:
    """Find the six fields in one repeated 26AS deductor-summary header."""
    found: dict[str, int] = {}
    for index, value in enumerate(row):
        text = _header_text(value)
        if text == "srno":
            found["sr_no"] = index
        elif "nameofdeductor" in text:
            found["deductor_name"] = index
        elif "tanofdeductor" in text:
            found["tan"] = index
        elif "totalamountpaidcredited" in text:
            found["total_amount_paid"] = index
        elif "totaltaxdeducted" in text:
            found["tax_deducted"] = index
        elif "totaltdsdeposited" in text:
            found["tds_deposited"] = index
    required = {"sr_no", "deductor_name", "tan", "total_amount_paid", "tax_deducted", "tds_deposited"}
    return found if required.issubset(found) else None


def extract_26as_deductor_summaries(raw: pd.DataFrame) -> pd.DataFrame | None:
    """Extract one top-level total row per deductor from a detailed 26AS export.

    A downloaded detailed 26AS workbook repeats a six-field deductor header,
    then one total row, followed by transaction-level Section/Date rows.  Only
    that first total row is useful for TDS-to-Tally reconciliation.
    """
    records: list[dict[str, object]] = []
    columns: dict[str, int] | None = None
    for row_number, row in raw.iterrows():
        detected = _summary_columns(row)
        if detected:
            columns = detected
            continue
        if not columns:
            continue
        tan = row.iloc[columns["tan"]]
        # Transaction rows do not contain a TAN. Requiring it avoids extracting
        # their Sr. No. 1..n records even if the same row has numeric values.
        tan_text = str(tan or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{4}\d{5}[A-Z]", tan_text):
            continue
        deductor = row.iloc[columns["deductor_name"]]
        if pd.isna(deductor) or not str(deductor).strip():
            continue
        records.append({
            "sr_no": row.iloc[columns["sr_no"]],
            "deductor_name": str(deductor).strip(),
            "tan": tan_text,
            "total_amount_paid": row.iloc[columns["total_amount_paid"]],
            "tax_deducted": row.iloc[columns["tax_deducted"]],
            "tds_deposited": row.iloc[columns["tds_deposited"]],
            "source_row": row_number + 1,
        })
    if not records:
        return None
    return pd.DataFrame.from_records(records).drop_duplicates(subset=["sr_no", "tan"], keep="first").reset_index(drop=True)


def is_detailed_26as_export(raw: pd.DataFrame) -> bool:
    """Distinguish a transaction-level 26AS export from a clean summary file.

    Reconciliation must not re-extract a summary downloaded from step 1. A
    detailed export repeats the deductor header for multiple parties, or
    contains the Section-level transaction heading beneath a deductor header.
    """
    summary_headers = sum(_summary_columns(row) is not None for _, row in raw.iterrows())
    has_detail_heading = any("section" in _header_text(value) for _, row in raw.iterrows() for value in row)
    return summary_headers > 1 or (summary_headers == 1 and has_detail_heading)


def preview_raw(uploaded: BinaryIO, sheet_name: str | None = None, rows: int = 35) -> pd.DataFrame:
    raw = _source_bytes(uploaded)
    filename = getattr(uploaded, "name", "").lower()
    if filename.endswith(".csv"):
        return pd.read_csv(raw, header=None, nrows=rows)
    return pd.read_excel(raw, sheet_name=sheet_name, header=None, nrows=rows)


def read_raw(uploaded: BinaryIO, sheet_name: str | None = None) -> pd.DataFrame:
    """Read a whole source sheet with an explicit safe limit, never truncate."""
    raw = _source_bytes(uploaded)
    filename = getattr(uploaded, "name", "").lower()
    if filename.endswith(".csv"):
        frame = pd.read_csv(raw, header=None)
    else:
        frame = pd.read_excel(raw, sheet_name=sheet_name, header=None)
    if len(frame) > MAX_PROCESSING_ROWS:
        raise ValueError(f"This sheet contains {len(frame):,} rows. Split it before processing; the safe limit is {MAX_PROCESSING_ROWS:,} rows.")
    return frame


def suggest_header_row(raw: pd.DataFrame, scan_rows: int = 30) -> int:
    """Select the row most likely to be a header, including Tally report headers."""
    split = tally_header_rows(raw)
    if split:
        return split[0]
    aliases = {"particulars", "name", "deductor", "party", "ledger", "amount", "debit", "credit", "balance", "date", "tan", "tds"}
    best_row, best_score = 0, -1
    for index in range(min(scan_rows, len(raw))):
        values = [str(value).strip().lower() for value in raw.iloc[index].dropna().tolist()]
        unique_count = len(set(values))
        keyword_count = sum(any(alias in value for alias in aliases) for value in values)
        score = (keyword_count * 8) + min(unique_count, 8)
        if score > best_score:
            best_row, best_score = index, score
    return best_row
