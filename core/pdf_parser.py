from __future__ import annotations

import re

import pandas as pd
from pypdf import PdfReader


SUMMARY_COLUMNS = [
    "sr_no", "deductor_name", "tan", "total_amount_paid", "tax_deducted", "tds_deposited", "source_page"
]


def _number(value: object) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def parse_annual_tax_statement(uploaded) -> pd.DataFrame:
    """Extract deductor summary rows from a TRACES Annual Tax Statement PDF."""
    uploaded.seek(0)
    records: list[dict[str, object]] = []
    # Layout mode retains enough horizontal spacing to distinguish summary rows from
    # transaction rows. It is significantly quicker and more dependable than PDF table grids.
    pattern = re.compile(
        r"^\s*(\d+)\s+(.+?)\s+([A-Z]{4}\d{5}[A-Z])\s+(-?[\d,.]+)\s+(-?[\d,.]+)\s+(-?[\d,.]+)\s*$"
    )
    reader = PdfReader(uploaded)
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text(extraction_mode="layout") or ""
        for line in text.splitlines():
            match = pattern.match(line)
            if not match:
                continue
            sr_no, deductor, tan, total_paid, tax_deducted, deposited = match.groups()
            records.append({
                "sr_no": int(sr_no),
                "deductor_name": deductor.strip(),
                "tan": tan,
                "total_amount_paid": _number(total_paid),
                "tax_deducted": _number(tax_deducted),
                "tds_deposited": _number(deposited),
                "source_page": page_number,
            })
    frame = pd.DataFrame.from_records(records, columns=SUMMARY_COLUMNS)
    if frame.empty:
        raise ValueError("No Annual Tax Statement deductor summaries were found in this PDF.")
    return frame.drop_duplicates(subset=["sr_no", "tan", "source_page"]).reset_index(drop=True)
