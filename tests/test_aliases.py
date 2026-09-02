from core.aliases import load_saved_aliases


def test_saved_aliases_include_user_confirmed_deepak_pair():
    aliases = load_saved_aliases()
    assert aliases["DEEPAK NOVOCHEM TECHNOLOGIES LIMITED"] == "Deepak Novachem / Tds 2024-25"


def test_saved_aliases_include_user_confirmed_dar_pair():
    aliases = load_saved_aliases()
    assert "DAR AL HANDASAH CONSULTANTS (SHAIR & PARTNERS) INDIA PRIVATE LIMITED" in aliases


def test_saved_aliases_include_latest_confirmed_pairs():
    aliases = load_saved_aliases()
    assert aliases["P N GADGIL"] == "PNG"
    assert aliases["MSME-DEVELOPMENT AND FACILITATION OFFICE"] == "MSME DFO / TDS 2024-25"
