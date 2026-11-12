"""THE BUG THIS PINS. York SC's parcel layer returns DateSold as an ArcGIS
esriFieldTypeDate — epoch MILLISECONDS. `sale_date` is not in _NUMERIC, so the
value passed straight through and would have been stored as the literal string
'1747267200000': a date column holding a 13-digit number.

Two fabrication traps came out of fixing it, both pinned below:
  - a magnitude floor rejected 1969-12-31 (a real pre-1970 sale reads as a SMALL
    negative epoch, and long-held property makes those ordinary);
  - 0 is ArcGIS's null-date placeholder, and naive conversion turns it — and any
    small junk value — into a confident, wrong 1970-01-01.

Found 2026-09-13 wiring York SC.
"""
from foreclosure_scraper.parcel_cache import _map_val


def _sd(v):
    return _map_val({"D": v}, "sale_date", "D")


def test_epoch_millis_becomes_an_iso_date():
    assert _sd(1747267200000) == "2025-05-15"


def test_pre_1970_sales_survive():
    # Small NEGATIVE epoch-ms. A magnitude floor silently dropped these.
    assert _sd(-500000000000) == "1954-02-26"


def test_null_date_placeholder_never_fabricates_1970():
    for junk in (0, 12345, -1):
        assert _sd(junk) is None, f"{junk!r} fabricated a date"


def test_bare_year_is_refused_not_turned_into_jan_1():
    assert _sd(2024) is None


def test_text_dates_pass_through_trimmed():
    # Anderson maps a TEXT field (saledatetx) — it must not be mangled.
    assert _sd(" 2024-03-11 ") == "2024-03-11"


def test_absurd_values_are_refused():
    assert _sd(99999999999999999) is None


def test_other_columns_are_untouched():
    assert _map_val({"D": 1747267200000}, "owner", "D") == 1747267200000
