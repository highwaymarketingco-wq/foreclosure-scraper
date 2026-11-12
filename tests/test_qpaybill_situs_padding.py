"""THE BUG THIS PINS. Several qPayBill portals render an absent city and ZIP as
literal zero columns, so the situs cell reads "128 PHOENIX LN 00000 0000" or
"9523 HWY 260 0 0000". Stored as-is that is not an address: it fails geocoding, it
defeats dedupe (two rows for the same house differ only by padding), and it prints
on a call sheet as something nobody can drive to.

4,327 rows were already on the board this way — Spartanburg 3,060, Clarendon 928,
Abbeville 214, McCormick 98 — before this was caught on 2026-09-13, while
smoke-testing the newly-found Lexington portal.
"""
from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import _clean_situs


def test_trailing_zero_columns_are_removed():
    assert _clean_situs("128 PHOENIX LN 00000 0000") == "128 PHOENIX LN"
    assert _clean_situs("9523 HWY 260 0 0000") == "9523 HWY 260"
    assert _clean_situs("KIMBETH LN 0 0000") == "KIMBETH LN"


def test_a_line_that_is_only_padding_becomes_none():
    # Reduces to a lone "00000" if you only strip whitespace-prefixed tokens.
    # "no address" is the truth; a blank-looking string is not.
    for junk in ("00000 0000", "0", "0 0000", "  "):
        assert _clean_situs(junk) is None, junk


def test_real_zero_house_numbers_survive():
    # Vacant parcels are genuinely numbered 0. Stripping LEADING zeros would
    # destroy a real address.
    assert _clean_situs("0 MAIN ST") == "0 MAIN ST"


def test_roads_carrying_digits_are_untouched():
    for good in ("123 COUNTY ROAD 40", "S-40-0 RD", "100 HIGHWAY 601"):
        assert _clean_situs(good) == good


def test_none_and_empty():
    assert _clean_situs(None) is None
    assert _clean_situs("") is None
