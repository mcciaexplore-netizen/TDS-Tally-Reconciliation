from __future__ import annotations

from difflib import SequenceMatcher
from itertools import combinations
import re

import pandas as pd


def normalize_party(value: object) -> str:
    """Normalize names for comparison only; retain the original in reports."""
    text = str(value or "").upper()
    text = re.sub(r"\bENGG\b", "ENGINEERING", text)
    text = re.sub(r"TDS\s*\d{2,4}\s*[-/]?\s*\d{2,4}\b", " ", text)
    text = re.sub(r"\bTD\s*\d{2,4}\s*[-/]?\s*\d{2,4}\b", " ", text)
    # Tally reports also use bare financial-year suffixes such as `/22-23`.
    text = re.sub(r"\b(?:FY\s*)?(?:20)?\d{2}\s*[-/]\s*(?:20)?\d{2}\b", " ", text)
    text = re.sub(r"\bP(?:\s*\.?\s*L(?:\s*\.?\s*T\s*\.?\s*D)?|\s+LTD)\.?(?=\W|$)", " ", text)
    text = re.sub(r"\b(THE|M/S|PRIVATE|PVT|LIMITED|LTD|LLP|OPC|CORPORATION|CORP|COMPANY)\b", " ", text)
    return re.sub(r"[^A-Z0-9]", "", text)


def _company_tokens(value: object) -> set[str]:
    text = str(value or "").upper()
    text = re.sub(r"\bENGG\b", "ENGINEERING", text)
    text = re.sub(r"\bTDS?\s*\d{2,4}\s*[-/]?\s*\d{2,4}\b", " ", text)
    text = re.sub(r"\b(?:FY\s*)?(?:20)?\d{2}\s*[-/]\s*(?:20)?\d{2}\b", " ", text)
    ignored = {"THE", "M", "S", "P", "L", "PL", "PRIVATE", "PVT", "LIMITED", "LTD", "LLP", "OPC", "FY", "TDS", "TD", "TECHNOLOGY", "TECHNOLOGIES", "SYSTEM", "SYSTEMS", "SERVICE", "SERVICES", "SOLUTION", "SOLUTIONS", "COMPANY", "CORPORATION", "CORP", "INDIA", "AND", "OF", "FOR", "TO"}
    return {token for token in re.findall(r"[A-Z0-9]+", text) if token not in ignored and not re.fullmatch(r"20\d{2}|\d{2}", token)}


def as_amount(value: object) -> float | None:
    if pd.isna(value):
        return None
    raw = str(value).strip().replace(",", "")
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", raw)
    try:
        result = float(cleaned) if cleaned else None
        return -abs(result) if negative and result is not None else result
    except ValueError:
        return None


def is_summary_party(value: object) -> bool:
    label = re.sub(r"[^A-Z ]", " ", str(value or "").upper())
    label = re.sub(r"\s+", " ", label).strip()
    return bool(re.fullmatch(r"(?:GRAND |NET )?TOTAL(?: FOR .*|S)?", label))


def _token_similarity(left_tokens: set[str], right_tokens: set[str]) -> float:
    if not left_tokens or not right_tokens:
        return 0.0
    smaller, larger = (left_tokens, right_tokens) if len(left_tokens) <= len(right_tokens) else (right_tokens, left_tokens)
    scores = [max(SequenceMatcher(None, token, other).ratio() for other in larger) for token in smaller]
    return round(sum(scores) * 100 / len(scores), 1)


def _score(left: str, right: str, left_tokens: set[str], right_tokens: set[str]) -> float:
    base = SequenceMatcher(None, left, right).ratio() * 100
    common = left_tokens & right_tokens
    smaller = min(left_tokens, right_tokens, key=len) if left_tokens and right_tokens else set()
    token_similarity = _token_similarity(left_tokens, right_tokens)
    if min(len(left), len(right)) >= 8 and (left in right or right in left):
        base = max(base, 92.0)
    elif len(smaller) >= 2 and smaller.issubset(common):
        base = max(base, 90.0)
    elif len(smaller) == 1 and len(next(iter(smaller), "")) >= 3 and smaller.issubset(common):
        base = max(base, 82.0)
    elif len(common) >= 2 and token_similarity >= 80.0:
        base = max(base, token_similarity)
    elif len(common) >= 1 and min(len(left_tokens), len(right_tokens)) >= 2 and token_similarity >= 90.0:
        # One exact distinctive word plus a near-spelling of the second word,
        # e.g. DEEPAK NOVOCHEM vs DEEPAK NOVACHEM.
        base = max(base, token_similarity)
    elif len(smaller) == 1 and token_similarity >= 88.0:
        base = max(base, token_similarity)
    elif len(common) < 2 and base < 90:
        base = min(base, 75.0)
    return round(base, 1)


def _amount_delta(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None or pd.isna(left) or pd.isna(right) else right - left


def _amount_distance(left: float | None, right: float | None) -> float:
    delta = _amount_delta(left, right)
    return float("inf") if delta is None else abs(delta)


def _best_subset(indices: list[int], right: pd.DataFrame, target: float | None, max_rows: int = 8) -> list[int]:
    """Find a small exact/closest subset for split Tally ledger entries."""
    if target is None or not indices:
        return indices[:1]
    candidates = indices[:max_rows]
    best = [candidates[0]]
    best_distance = _amount_distance(target, right.at[candidates[0], "_amount"])
    for size in range(2, len(candidates) + 1):
        for subset in combinations(candidates, size):
            total = sum((right.at[index, "_amount"] or 0.0) for index in subset)
            distance = abs(total - target)
            if distance < best_distance - 1e-9 or (distance == best_distance and len(subset) < len(best)):
                best, best_distance = list(subset), distance
    return best


def _may_be_name_candidate(left: pd.Series, right: pd.Series) -> bool:
    """Cheap safe pre-filter before expensive fuzzy scoring."""
    if left["_party"] == right["_party"]:
        return True
    if left["_tokens"] & right["_tokens"]:
        return True
    left_name, right_name = left["_party"], right["_party"]
    return len(left_name) >= 3 and len(right_name) >= 3 and left_name[:3] == right_name[:3]


def _candidate_groups(lrow: pd.Series, right: pd.DataFrame, available: set[int], score_for, threshold: float, exact_only: bool = False, max_aggregate_rows: int = 8) -> list[tuple[float, list[int]]]:
    """Return candidate party groups, never an arbitrary duplicate ledger row."""
    grouped: dict[str, list[int]] = {}
    for index in available:
        rrow = right.loc[index]
        if not exact_only and not _may_be_name_candidate(lrow, rrow):
            continue
        score = score_for(lrow, rrow)
        if exact_only:
            if lrow["_party"] and lrow["_party"] == rrow["_party"]:
                grouped.setdefault(rrow["_party"], []).append(index)
        elif score >= threshold:
            grouped.setdefault(rrow["_party"], []).append(index)
    output = []
    for indices in grouped.values():
        subset = _best_subset(indices, right, lrow["_amount"], max_aggregate_rows)
        output.append((max(score_for(lrow, right.loc[index]) for index in subset), subset))
    return output


def reconcile(
    tds: pd.DataFrame, tally: pd.DataFrame, tds_party_col: str, tds_tax_col: str,
    tally_party_col: str, tally_tax_col: str, tds_tan_col: str | None = None,
    approved_aliases: dict[str, str] | None = None, amount_tolerance: float = 1.0,
    partial_threshold: float = 78.0, relative_tolerance_pct: float = 0.0,
    max_aggregate_rows: int = 8,
) -> pd.DataFrame:
    """Reconcile names with controlled aggregate Tally-row matching.

    Fuzzy relationships remain review-only. Every result retains source IDs and
    a matching method so an accountant can audit it.
    """
    left = tds.copy().reset_index(names="tds_row")
    right = tally.copy().reset_index(names="tally_row")
    left = left.loc[~left[tds_party_col].map(is_summary_party)].copy()
    right = right.loc[~right[tally_party_col].map(is_summary_party)].copy()
    for frame, party_col, amount_col in ((left, tds_party_col, tds_tax_col), (right, tally_party_col, tally_tax_col)):
        frame["_display_party"] = frame[party_col]
        frame["_tokens"] = frame[party_col].map(_company_tokens)
        frame["_party"] = frame[party_col].map(normalize_party)
        frame["_amount"] = frame[amount_col].map(as_amount)
    left["_tan"] = left[tds_tan_col] if tds_tan_col else None
    # A portal export can occasionally contain several summary lines for the
    # same deductor. Combine only identical normalized parties so they can be
    # compared against one Tally total, while retaining every original row ID.
    combined_left: list[pd.Series] = []
    for party, group in left.groupby("_party", sort=False, dropna=False):
        if party and len(group) > 1:
            row = group.iloc[0].copy()
            row["_amount"] = group["_amount"].sum(min_count=1)
            row["tds_row"] = ", ".join(str(value) for value in group["tds_row"])
            row["_display_party"] = " | ".join(dict.fromkeys(str(value) for value in group["_display_party"]))
            row["_tan"] = " | ".join(dict.fromkeys(str(value) for value in group["_tan"].dropna()))
            row["_portal_aggregated"] = True
            combined_left.append(row)
        else:
            for _, row in group.iterrows():
                row = row.copy()
                row["_portal_aggregated"] = False
                combined_left.append(row)
    left = pd.DataFrame(combined_left).reset_index(drop=True)
    available = set(right.index)
    assigned: dict[int, tuple[list[int], str, float, str]] = {}
    score_cache: dict[tuple[str, str], float] = {}

    def score_for(lrow: pd.Series, rrow: pd.Series) -> float:
        key = (lrow["_party"], rrow["_party"])
        if key not in score_cache:
            score_cache[key] = _score(lrow["_party"], rrow["_party"], lrow["_tokens"], rrow["_tokens"])
        return score_cache[key]

    aliases = {normalize_party(portal): normalize_party(tally_name) for portal, tally_name in (approved_aliases or {}).items()}
    for li, lrow in left.iterrows():
        target = aliases.get(lrow["_party"])
        choices = [index for index in available if right.at[index, "_party"] == target] if target else []
        if choices:
            subset = _best_subset(choices, right, lrow["_amount"], max_aggregate_rows)
            assigned[li] = (subset, "Approved alias", 100.0, "reviewer-approved alias")
            available.difference_update(subset)
    for li, lrow in left.loc[~left.index.isin(assigned)].iterrows():
        groups = _candidate_groups(lrow, right, available, score_for, partial_threshold, exact_only=True, max_aggregate_rows=max_aggregate_rows)
        if groups:
            _, subset = min(groups, key=lambda item: _amount_distance(lrow["_amount"], sum((right.at[i, "_amount"] or 0.0) for i in item[1])))
            method = "exact normalized name" if len(subset) == 1 else "exact normalized name; aggregated Tally rows"
            if lrow["_portal_aggregated"]:
                method += "; aggregated Portal rows"
            assigned[li] = (subset, "Total match", 100.0, method)
            available.difference_update(subset)
    edges: list[tuple[float, float, int, list[int], str]] = []
    for li, lrow in left.loc[~left.index.isin(assigned)].iterrows():
        for score, subset in _candidate_groups(lrow, right, available, score_for, partial_threshold, max_aggregate_rows=max_aggregate_rows):
            total = sum((right.at[i, "_amount"] or 0.0) for i in subset)
            if _within_tolerance(lrow["_amount"], total, amount_tolerance, relative_tolerance_pct):
                score = min(99.0, score + 5.0)
            edges.append((score, _amount_distance(lrow["_amount"], total), li, subset, "fuzzy name; human verification required"))
    for score, distance, li, subset, method in sorted(edges, key=lambda e: (-e[0], e[1], e[2], e[3])):
        if li not in assigned and all(index in available for index in subset):
            competing = [edge for edge in edges if edge[2] == li and all(index in available for index in edge[3])]
            if len(competing) > 1 and abs(competing[0][0] - competing[1][0]) <= 2.0:
                method += "; ambiguous alternatives"
            assigned[li] = (subset, "Needs review", score, method)
            available.difference_update(subset)

    result: list[dict[str, object]] = []
    for li, lrow in left.iterrows():
        if li in assigned:
            subset, status, confidence, method = assigned[li]
            rows = right.loc[subset]
            total = rows["_amount"].sum(min_count=1)
            delta = _amount_delta(lrow["_amount"], total)
            if status in {"Approved alias", "Total match"} and not _within_tolerance(lrow["_amount"], total, amount_tolerance, relative_tolerance_pct):
                status = "Partial match"
            result.append(_result_row(lrow, rows, status, confidence, method, delta))
        else:
            candidates = _candidate_groups(lrow, right, available, score_for, partial_threshold, max_aggregate_rows=max_aggregate_rows)
            top = sorted(((score, "; ".join(str(right.at[i, "_display_party"]) for i in subset)) for score, subset in candidates), reverse=True)[:3]
            result.append(_result_row(lrow, None, "No match", max((x[0] for x in top), default=0.0), "no candidate met the confidence threshold", None, top))
    for index in sorted(available):
        rrow = right.loc[index]
        result.append({"status": "No match in TDS", "match_confidence": None, "match_method": "no TDS candidate", "candidate_matches": None, "tds_row": None, "tally_rows": str(rrow["tally_row"]), "tds_tan": None, "tds_party": None, "tds_tax_amount": None, "tally_party": rrow["_display_party"], "tally_tax_amount": rrow["_amount"], "amount_difference": None})
    output = pd.DataFrame(result)
    output["_sort_name"] = output["tds_party"].fillna(output["tally_party"]).fillna("").astype(str).str.casefold()
    return output.sort_values("_sort_name", kind="stable").drop(columns="_sort_name").reset_index(drop=True)


def _result_row(lrow: pd.Series, tally_rows: pd.DataFrame | None, status: str, confidence: float, method: str, delta: float | None, candidates: list[tuple[float, str]] | None = None) -> dict[str, object]:
    if tally_rows is None:
        tally_party, tally_amount, tally_indices = None, None, None
    else:
        tally_party = " | ".join(dict.fromkeys(str(value) for value in tally_rows["_display_party"]))
        tally_amount = tally_rows["_amount"].sum(min_count=1)
        tally_indices = ", ".join(str(value) for value in tally_rows["tally_row"])
    candidate_text = None if not candidates else " | ".join(f"{name} ({score:.1f}%)" for score, name in candidates)
    return {"status": status, "match_confidence": confidence, "match_method": method, "candidate_matches": candidate_text, "tds_row": lrow["tds_row"], "tally_rows": tally_indices, "tds_tan": lrow["_tan"], "tds_party": lrow["_display_party"], "tds_tax_amount": lrow["_amount"], "tally_party": tally_party, "tally_tax_amount": tally_amount, "amount_difference": delta}


def _within_tolerance(left: float | None, right: float | None, absolute: float, relative_pct: float) -> bool:
    delta = _amount_delta(left, right)
    if delta is None:
        return False
    allowed = max(absolute, abs(left or 0.0) * relative_pct / 100)
    return abs(delta) <= allowed
