from __future__ import annotations

from io import BytesIO
from typing import BinaryIO

import pandas as pd


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
        return pd.read_csv(raw, header=header_row)
    return pd.read_excel(raw, sheet_name=sheet_name, header=header_row)


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
    raw = preview_raw(uploaded, sheet_name, rows=10000)
    split = tally_header_rows(raw)
    if not split:
        return read_tabular(uploaded, sheet_name, header_row)
    primary_row, detail_row = split
    primary = raw.iloc[primary_row].fillna("").astype(str).str.strip().tolist()
    detail = raw.iloc[detail_row].fillna("").astype(str).str.strip().tolist()
    columns = [detail_value or primary_value or f"Column {index + 1}" for index, (primary_value, detail_value) in enumerate(zip(primary, detail))]
    data = raw.iloc[detail_row + 1 :].copy()
    data.columns = columns
    return data.dropna(how="all").reset_index(drop=True)


def preview_raw(uploaded: BinaryIO, sheet_name: str | None = None, rows: int = 35) -> pd.DataFrame:
    raw = _source_bytes(uploaded)
    filename = getattr(uploaded, "name", "").lower()
    if filename.endswith(".csv"):
        return pd.read_csv(raw, header=None, nrows=rows)
    return pd.read_excel(raw, sheet_name=sheet_name, header=None, nrows=rows)


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
