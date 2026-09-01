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


def test_shortened_tally_ledger_name_becomes_review_candidate():
    tds = pd.DataFrame({"party": ["3D ENGINEERING AUTOMATION LLP"], "tax": [200]})
    tally = pd.DataFrame({"party": ["3D ENGINEERING / TDS 2024-25"], "tax": [200]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax")
    assert result.loc[0, "status"] == "Needs review"
    assert result.loc[0, "match_confidence"] >= 90


def test_same_amount_without_company_similarity_is_not_a_match():
    tds = pd.DataFrame({"party": ["Alpha Engineering"], "tax": [200]})
    tally = pd.DataFrame({"party": ["Unrelated Services / TDS 2024-25"], "tax": [200]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax")
    assert result.loc[0, "status"] == "No match"


def test_generic_technology_word_does_not_steal_correct_ledger():
    tds = pd.DataFrame({"party": ["Clarion Technologies Private Limited", "4FIN Technologies Private Limited"], "tax": [3500, 400]})
    tally = pd.DataFrame({"party": ["4FIN Technologies / TDS 2024-25"], "tax": [400]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax")
    assert result.loc[result["tds_party"] == "Clarion Technologies Private Limited", "status"].item() == "No match"
    assert result.loc[result["tds_party"] == "4FIN Technologies Private Limited", "status"].item() == "Total match"


def test_approved_alias_reconciles_different_company_names():
    tds = pd.DataFrame({"party": ["3D Engineering Automation LLP"], "tax": [200]})
    tally = pd.DataFrame({"party": ["3D Engineering / TDS 2024-25"], "tax": [200]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax", approved_aliases={"3D Engineering Automation LLP": "3D Engineering / TDS 2024-25"})
    assert result.loc[0, "status"] == "Approved alias"


def test_spelling_variation_with_two_company_words_is_review_candidate():
    tds = pd.DataFrame({"party": ["Deepak Novochem Technologies Limited"], "tax": [7500]})
    tally = pd.DataFrame({"party": ["Deepak Novachem / TDS 2024-25"], "tax": [7500]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax")
    assert result.loc[result["tds_party"] == "Deepak Novochem Technologies Limited", "status"].item() == "Needs review"


def test_single_distinctive_word_typo_is_review_candidate():
    tds = pd.DataFrame({"party": ["Brainiac Global Consulting Private Limited"], "tax": [2500]})
    tally = pd.DataFrame({"party": ["Brainac / TDS 2024-25"], "tax": [2500]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax")
    assert result.loc[0, "status"] == "Needs review"


def test_multiword_typo_is_review_candidate():
    tds = pd.DataFrame({"party": ["Dar Al Handasah Consultants India Private Limited"], "tax": [700]})
    tally = pd.DataFrame({"party": ["Dar Ai Handasah / TDS 2024-25"], "tax": [700]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax")
    assert result.loc[0, "status"] == "Needs review"


def test_results_are_alphabetical_by_company_name():
    tds = pd.DataFrame({"party": ["Zulu Limited", "Alpha Limited"], "tax": [10, 20]})
    tally = pd.DataFrame({"party": ["Zulu / TDS 2024-25", "Alpha / TDS 2024-25"], "tax": [10, 20]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax")
    assert result["tds_party"].tolist() == ["Alpha Limited", "Zulu Limited"]


def test_confirmed_alias_handles_spelling_and_business_name_changes():
    tds = pd.DataFrame({"party": ["Emcure Pharmaceuticals Limited"], "tax": [68750]})
    tally = pd.DataFrame({"party": ["Emcure Pharma / 2024-25"], "tax": [68750]})
    result = reconcile(tds, tally, "party", "tax", "party", "tax", approved_aliases={"Emcure Pharmaceuticals Limited": "Emcure Pharma / 2024-25"})
    assert result.loc[0, "status"] == "Approved alias"
