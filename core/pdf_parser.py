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
    pages_with_text = 0
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text(extraction_mode="layout") or ""
        if text.strip():
            pages_with_text += 1
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        # Some statement PDFs wrap a long deductor name over two physical lines.
        # Check each line plus its immediate neighbours, but still require TAN and
        # all three summary amounts to avoid collecting transaction rows.
        candidates = [" ".join(lines[index : index + width]) for index in range(len(lines)) for width in (1, 2, 3) if index + width <= len(lines)]
        for line in candidates:
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
        if not pages_with_text:
            raise ValueError("This PDF appears scanned or image-only. Upload the 26AS Excel/CSV export instead; OCR is not used because it can misread TAN and amounts.")
        raise ValueError("No Annual Tax Statement deductor summaries were found. The PDF layout may differ; use the 26AS Excel/CSV export for a reliable extraction.")
    return frame.drop_duplicates(subset=["sr_no", "tan", "source_page"]).reset_index(drop=True)
