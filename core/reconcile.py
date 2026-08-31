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


def _company_tokens(value: object) -> set[str]:
    """Retain meaningful words for safer company-name comparison."""
    text = str(value or "").upper()
    text = re.sub(r"\bTDS\s*\d{2,4}\s*[-/]?\s*\d{2,4}\b", " ", text)
    text = re.sub(r"\bTD\s*\d{2,4}\s*[-/]?\s*\d{2,4}\b", " ", text)
    ignored = {
        "THE", "M", "S", "PRIVATE", "PVT", "LIMITED", "LTD", "LLP", "FY", "TDS", "TD",
        "TECHNOLOGY", "TECHNOLOGIES", "SYSTEM", "SYSTEMS", "SERVICE", "SERVICES", "SOLUTION", "SOLUTIONS",
        "COMPANY", "CORPORATION", "INDIA", "AND", "OF", "FOR", "TO",
    }
    return {token for token in re.findall(r"[A-Z0-9]+", text) if token not in ignored and not re.fullmatch(r"20\d{2}|\d{2}", token)}


def as_amount(value: object) -> float | None:
    if pd.isna(value):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _score(left: str, right: str, left_tokens: set[str], right_tokens: set[str]) -> float:
    """Score legal-name variations without treating them as automatic matches."""
    base = SequenceMatcher(None, left, right).ratio() * 100
    common_tokens = left_tokens & right_tokens
    smaller_tokens = min(left_tokens, right_tokens, key=len) if left_tokens and right_tokens else set()
    # Tally ledger names often abbreviate a longer legal company name. A meaningful
    # normalized prefix/substring is a strong review candidate (for example,
    # `3DENGINEERING` inside `3DENGINEERINGAUTOMATION`), but remains non-exact.
    if min(len(left), len(right)) >= 8 and (left in right or right in left):
        base = max(base, 92.0)
    elif len(smaller_tokens) >= 2 and smaller_tokens.issubset(left_tokens | right_tokens) and smaller_tokens.issubset(common_tokens):
        base = max(base, 90.0)
    elif len(smaller_tokens) == 1 and len(next(iter(smaller_tokens), "")) >= 3 and smaller_tokens.issubset(common_tokens):
        # Short branded ledger names such as GIZ, BPMBC, or 4FIN need an amount
        # check below before becoming a review candidate.
        base = max(base, 82.0)
    elif len(common_tokens) < 2 and base < 90:
        # Prevent generic tails (for example, only "Technologies" in common) from
        # claiming another company's ledger.
        base = min(base, 75.0)
    return round(base, 1)


def reconcile(
    tds: pd.DataFrame,
    tally: pd.DataFrame,
    tds_party_col: str,
    tds_tax_col: str,
    tally_party_col: str,
    tally_tax_col: str,
    tds_tan_col: str | None = None,
    approved_aliases: dict[str, str] | None = None,
    amount_tolerance: float = 1.0,
    partial_threshold: float = 78.0,
) -> pd.DataFrame:
    """One-to-one party matching; never silently accepts an ambiguous fuzzy candidate."""
    left = tds.copy().reset_index(names="tds_row")
    right = tally.copy().reset_index(names="tally_row")
    left["_display_party"] = left[tds_party_col]
    right["_display_party"] = right[tally_party_col]
    left["_tokens"] = left[tds_party_col].map(_company_tokens)
    right["_tokens"] = right[tally_party_col].map(_company_tokens)
    left["_tan"] = left[tds_tan_col] if tds_tan_col else None
    left["_party"] = left[tds_party_col].map(normalize_party)
    right["_party"] = right[tally_party_col].map(normalize_party)
    left["_amount"] = left[tds_tax_col].map(as_amount)
    right["_amount"] = right[tally_tax_col].map(as_amount)
    available = set(right.index)
    assigned: dict[int, tuple[int, str, float, float | None]] = {}
    aliases = {normalize_party(portal): normalize_party(tally_name) for portal, tally_name in (approved_aliases or {}).items()}

    # Phase 0: apply aliases explicitly approved by the reviewer. These are the
    # safe way to reconcile business-name changes that text comparison cannot prove.
    for left_index, lrow in left.iterrows():
        alias_target = aliases.get(lrow["_party"])
        if not alias_target:
            continue
        candidates = [index for index in available if right.at[index, "_party"] == alias_target]
        if not candidates:
            continue
        best_index = min(candidates, key=lambda index: _amount_distance(lrow["_amount"], right.at[index, "_amount"]))
        rrow = right.loc[best_index]
        delta = _amount_delta(lrow["_amount"], rrow["_amount"])
        status = "Approved alias" if delta is not None and abs(delta) <= amount_tolerance else "Partial match"
        assigned[left_index] = (best_index, status, 100.0, delta)
        available.remove(best_index)

    # Phase 1: match exact normalized names first. This protects a true ledger
    # from being consumed by an earlier, weaker fuzzy candidate.
    for left_index, lrow in left.loc[~left.index.isin(assigned)].iterrows():
        exact = [index for index in available if right.at[index, "_party"] == lrow["_party"] and lrow["_party"]]
        if not exact:
            continue
        best_index = min(exact, key=lambda index: _amount_distance(lrow["_amount"], right.at[index, "_amount"]))
        rrow = right.loc[best_index]
        delta = _amount_delta(lrow["_amount"], rrow["_amount"])
        status = "Total match" if delta is not None and abs(delta) <= amount_tolerance else "Partial match"
        assigned[left_index] = (best_index, status, 100.0, delta)
        available.remove(best_index)

    # Phase 2: create all valid fuzzy edges and assign the strongest candidates
    # globally, rather than greedily in portal-row order.
    edges: list[tuple[float, float, int, int, float | None]] = []
    for left_index, lrow in left.loc[~left.index.isin(assigned)].iterrows():
        for right_index in available:
            rrow = right.loc[right_index]
            score = _score(lrow["_party"], rrow["_party"], lrow["_tokens"], rrow["_tokens"])
            delta = _amount_delta(lrow["_amount"], rrow["_amount"])
            if delta is not None and abs(delta) <= amount_tolerance:
                score = min(99.0, score + 5.0)
            if score >= partial_threshold:
                edges.append((score, _amount_distance(lrow["_amount"], rrow["_amount"]), left_index, right_index, delta))
    for score, distance, left_index, right_index, delta in sorted(edges, key=lambda edge: (-edge[0], edge[1], edge[2], edge[3])):
        if left_index not in assigned and right_index in available:
            assigned[left_index] = (right_index, "Needs review", score, delta)
            available.remove(right_index)

    result: list[dict[str, object]] = []
    for left_index, lrow in left.iterrows():
        if left_index in assigned:
            right_index, status, confidence, delta = assigned[left_index]
            rrow = right.loc[right_index]
            result.append(_result_row(lrow, rrow, status, confidence, rrow[tally_party_col], delta))
        else:
            best_confidence = max((_score(lrow["_party"], right.at[index, "_party"], lrow["_tokens"], right.at[index, "_tokens"]) for index in available), default=0.0)
            result.append(_result_row(lrow, None, "No match", best_confidence, None, None))

    for index in sorted(available):
        rrow = right.loc[index]
        result.append({
            "status": "No match in TDS", "match_confidence": None, "tds_party": None, "tds_tax_amount": None,
            "tds_tan": None, "tally_party": rrow[tally_party_col], "tally_tax_amount": rrow["_amount"], "amount_difference": None,
        })
    return pd.DataFrame(result)


def _amount_delta(left: float | None, right: float | None) -> float | None:
    return None if pd.isna(left) or pd.isna(right) else right - left


def _amount_distance(left: float | None, right: float | None) -> float:
    delta = _amount_delta(left, right)
    return float("inf") if delta is None else abs(delta)


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
