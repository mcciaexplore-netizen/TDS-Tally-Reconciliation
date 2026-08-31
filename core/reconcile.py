from __future__ import annotations

from difflib import SequenceMatcher
import re

import pandas as pd


def normalize_party(value: object) -> str:
    text = str(value or "").upper()
    text = re.sub(r"\bTDS\s*\d{2,4}\s*[-/]?\s*\d{2,4}\b", " ", text)
    text = re.sub(r"\bTD\s*\d{2,4}\s*[-/]?\s*\d{2,4}\b", " ", text)
    text = re.sub(r"\b(THE|M/S|PRIVATE|PVT|LIMITED|LTD|LLP)\b", " ", text)
    return re.sub(r"[^A-Z0-9]", "", text)


def as_amount(value: object) -> float | None:
    if pd.isna(value):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _score(left: str, right: str) -> float:
    return round(SequenceMatcher(None, left, right).ratio() * 100, 1)


def reconcile(
    tds: pd.DataFrame,
    tally: pd.DataFrame,
    tds_party_col: str,
    tds_tax_col: str,
    tally_party_col: str,
    tally_tax_col: str,
    tds_tan_col: str | None = None,
    amount_tolerance: float = 1.0,
    partial_threshold: float = 78.0,
) -> pd.DataFrame:
    """One-to-one party matching; never silently accepts an ambiguous fuzzy candidate."""
    left = tds.copy().reset_index(names="tds_row")
    right = tally.copy().reset_index(names="tally_row")
    left["_display_party"] = left[tds_party_col]
    right["_display_party"] = right[tally_party_col]
    left["_tan"] = left[tds_tan_col] if tds_tan_col else None
    left["_party"] = left[tds_party_col].map(normalize_party)
    right["_party"] = right[tally_party_col].map(normalize_party)
    left["_amount"] = left[tds_tax_col].map(as_amount)
    right["_amount"] = right[tally_tax_col].map(as_amount)
    available = set(right.index)
    result: list[dict[str, object]] = []

    for _, lrow in left.iterrows():
        exact = [index for index in available if right.at[index, "_party"] == lrow["_party"] and lrow["_party"]]
        candidates = exact or list(available)
        ranked = sorted(((index, _score(lrow["_party"], right.at[index, "_party"])) for index in candidates), key=lambda item: item[1], reverse=True)
        if not ranked:
            result.append(_result_row(lrow, None, "No match", 0, None, None))
            continue
        best_index, confidence = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else -1
        rrow = right.loc[best_index]
        delta = None if pd.isna(lrow["_amount"]) or pd.isna(rrow["_amount"]) else rrow["_amount"] - lrow["_amount"]
        if exact and delta is not None and abs(delta) <= amount_tolerance:
            status = "Total match"
        elif exact:
            # Identity is confirmed but the value differs or is incomplete.
            status = "Partial match"
        elif confidence >= partial_threshold:
            # A similar name is a candidate only. It must never become an accepted
            # match without the reviewer explicitly verifying it.
            status = "Needs review"
        else:
            result.append(_result_row(lrow, None, "No match", confidence, None, None))
            continue
        available.remove(best_index)
        result.append(_result_row(lrow, rrow, status, confidence, rrow[tally_party_col], delta))

    for index in sorted(available):
        rrow = right.loc[index]
        result.append({
            "status": "No match in TDS", "match_confidence": None, "tds_party": None, "tds_tax_amount": None,
            "tds_tan": None, "tally_party": rrow[tally_party_col], "tally_tax_amount": rrow["_amount"], "amount_difference": None,
        })
    return pd.DataFrame(result)


def _result_row(lrow, rrow, status, confidence, tally_party, delta):
    return {
        "status": status,
        "match_confidence": confidence,
        "tds_tan": lrow["_tan"],
        "tds_party": lrow["_display_party"],
        "tds_tax_amount": lrow["_amount"],
        "tally_party": tally_party,
        "tally_tax_amount": None if rrow is None else rrow["_amount"],
        "amount_difference": delta,
    }
