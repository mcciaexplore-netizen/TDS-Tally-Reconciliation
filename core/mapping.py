from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd


FIELDS = {
    "party_name": ["party", "vendor", "deductor", "name", "particular", "ledger", "payee"],
    "tax_amount": ["tds deposited", "tax deducted", "tds", "tax amount", "closing balance", "balance"],
    "total_amount": ["total amount", "amount paid", "credited", "gross amount", "payment amount"],
    "transaction_date": ["transaction date", "booking date", "voucher date", "date"],
    "tan": ["tan", "tax deduction account"],
    "section": ["section", "tds section"],
}


@dataclass(frozen=True)
class Suggestion:
    column: str | None
    confidence: str
    score: int


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def suggest_columns(frame: pd.DataFrame) -> dict[str, Suggestion]:
    suggestions: dict[str, Suggestion] = {}
    for field, aliases in FIELDS.items():
        best_column, best_score = None, 0
        for column in frame.columns:
            value = _normalize(str(column))
            score = max((100 if _normalize(alias) == value else 80 if _normalize(alias) in value else 0) for alias in aliases)
            if field == "party_name":
                # A name/party/ledger is a party identifier; TAN merely belongs to
                # the same deductor and must never win the suggested party mapping.
                if any(token in value.split() for token in ("name", "party", "particular", "ledger", "vendor", "payee")):
                    score += 20
                if "tan" in value.split():
                    score -= 80
            # When two fields are equally clear, prefer the later/more specific source
            # column. In the annual statement this selects `tds_deposited` over the
            # nearby `tax_deducted` field for the final reconciliation amount.
            if score >= best_score:
                best_column, best_score = str(column), score
        confidence = "High" if best_score >= 80 else "Medium" if best_score >= 50 else "Low"
        suggestions[field] = Suggestion(best_column if best_score else None, confidence, best_score)
    return suggestions


def options(frame: pd.DataFrame) -> list[str]:
    return ["-- Not mapped --", *map(str, frame.columns)]
