from __future__ import annotations

import pandas as pd

from core.reconcile import as_amount, is_summary_party, normalize_party


def quality_report(frame: pd.DataFrame, party_col: str, amount_col: str, tan_col: str | None = None) -> list[dict[str, object]]:
    """Return human-readable source checks before any reconciliation occurs."""
    parties = frame[party_col]
    normalized = parties.map(normalize_party)
    numeric = frame[amount_col].map(as_amount)
    checks = [
        {"check": "Records", "count": len(frame), "severity": "Info"},
        {"check": "Blank party names", "count": int(parties.isna().sum() + parties.astype(str).str.strip().eq("").sum()), "severity": "Error"},
        {"check": "Invalid / blank amounts", "count": int(numeric.isna().sum()), "severity": "Warning"},
        {"check": "Summary / total rows", "count": int(parties.map(is_summary_party).sum()), "severity": "Warning"},
        {"check": "Duplicate normalized party names", "count": int(normalized[normalized.ne("")].duplicated(keep=False).sum()), "severity": "Warning"},
    ]
    if tan_col:
        tans = frame[tan_col].astype(str).str.strip().str.upper()
        checks.append({"check": "Duplicate TANs", "count": int(tans[tans.ne("") & tans.ne("NAN")].duplicated(keep=False).sum()), "severity": "Warning"})
    return checks
