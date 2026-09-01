import pandas as pd

from core.mapping import suggest_columns


def test_name_of_deductor_beats_tan_for_party_mapping():
    frame = pd.DataFrame(columns=["Sr. No.", "Name of Deductor", "TAN of Deductor", "Total TDS Deposited"])
    suggestions = suggest_columns(frame)
    assert suggestions["party_name"].column == "Name of Deductor"
    assert suggestions["tax_amount"].column == "Total TDS Deposited"


def test_balance_is_selected_as_tally_tax_amount():
    frame = pd.DataFrame(columns=["Particulars", "Debit", "Credit", "Balance"])
    assert suggest_columns(frame)["tax_amount"].column == "Balance"
