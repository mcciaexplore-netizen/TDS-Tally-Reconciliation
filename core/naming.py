from __future__ import annotations

import re


def detect_financial_year(*filenames: str) -> str | None:
    """Return a financial-year token such as 2024-25 found in an uploaded filename."""
    for filename in filenames:
        match = re.search(r"(?<!\d)(20\d{2})[\s_.-]*(?:20)?(\d{2})(?!\d)", filename or "", flags=re.IGNORECASE)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
    return None


def report_filename(extension: str, *filenames: str) -> str:
    year = detect_financial_year(*filenames)
    suffix = f"_{year}" if year else ""
    return f"TDS_Tally_Reconciliation{suffix}.{extension.lstrip('.')}"
