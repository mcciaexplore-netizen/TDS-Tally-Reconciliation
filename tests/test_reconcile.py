import pandas as pd

from core.reconcile import normalize_party, reconcile


def test_normalize_removes_tally_suffix_and_company_noise():
    assert normalize_party("Acme Pvt. Ltd. / TDS 2024-25") == "ACME"


def test_exact_party_and_amount_is_total_match():
    tds = pd.DataFrame({"party": ["Acme Private Limited"], "tax": [3500]})
    tally = pd.DataFrame({"party": ["ACME / TDS 2024-25"], "tax": [3500]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax")
    assert result.loc[0, "status"] == "Total match"


def test_exact_party_with_amount_difference_is_partial():
    tds = pd.DataFrame({"party": ["Acme"], "tax": [3500]})
    tally = pd.DataFrame({"party": ["Acme/TDS 2024-25"], "tax": [3490]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax")
    assert result.loc[0, "status"] == "Partial match"


def test_similar_party_name_requires_human_review():
    tds = pd.DataFrame({"party": ["Favourite Safety Product"], "tax": [500]})
    tally = pd.DataFrame({"party": ["Favourite Safety / TDS 2024-25"], "tax": [500]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax", partial_threshold=75)
    assert result.loc[0, "status"] == "Needs review"
