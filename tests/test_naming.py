from core.naming import detect_financial_year, report_filename


def test_detects_short_second_year_from_tally_filename():
    assert detect_financial_year("TALLY TDS 2024-25.xls") == "2024-25"


def test_prefers_first_filename_when_both_have_years():
    assert detect_financial_year("TALLY 2024-25.xls", "TDS 2023-24.pdf") == "2024-25"


def test_report_filename_contains_detected_year():
    assert report_filename("xlsx", "TALLY TDS 2024-25.xls") == "TDS_Tally_Reconciliation_2024-25.xlsx"
