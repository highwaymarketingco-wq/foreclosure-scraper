"""gis.last_sale.amount must always be a number.

2026-09-20: 588 board rows held it as display text ("330,000") and 6 as "DOD",
because parcel-cache sale prices were copied in unparsed. `str > int` in
enrich_gis_derived crashed scripts/recompute_valuation.py before it wrote anything.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_gis_derived import enrich_gis_derived
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.parcel_cache import sale_amount


@pytest.mark.parametrize("raw,expected", [
    ("330,000", 330000.0), ("$1,200", 1200.0), ("12,345.50", 12345.5),
    (250000, 250000.0), (250000.0, 250000.0), ("  99,999 ", 99999.0),
])
def test_sale_amount_parses_display_text(raw, expected):
    assert sale_amount(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "DOD", "N/A", 0, "0", -5, True, float("nan")])
def test_sale_amount_rejects_non_prices(raw):
    assert sale_amount(raw) is None


def _li(amount):
    return Listing(source="counties_sc.qpaybill_delinquent_roll", source_url="u",
                   listing_type=ListingType.TAX_LIEN, state="SC", county="Cherokee",
                   raw={"gis": {"last_sale": {"amount": amount, "date": "2020-01-01"}}})


def test_string_amount_no_longer_crashes_and_is_normalized_to_a_number():
    li = _li("330,000")
    enrich_gis_derived([li])                      # used to raise TypeError (str > int)
    assert li.raw["gis"]["last_sale"]["amount"] == 330000.0


def test_non_numeric_amount_is_dropped_not_kept():
    li = _li("DOD")
    enrich_gis_derived([li])
    assert "amount" not in li.raw["gis"]["last_sale"]


def test_implausible_string_amount_is_still_capped():
    li = _li("1,200,000,000")                     # the uninitialized-double class of bad value
    enrich_gis_derived([li])
    assert "amount" not in li.raw["gis"]["last_sale"]


def test_numeric_amount_is_untouched():
    li = _li(275000.0)
    enrich_gis_derived([li])
    assert li.raw["gis"]["last_sale"]["amount"] == 275000.0
