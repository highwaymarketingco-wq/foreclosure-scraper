"""Flip leads are only in the 18 footprint counties; distress leads are anywhere in NC and SC.

The owner's rule, 2026-09-15: "if its a flip, its only in the counties we talked about. if its
a distressed property its anywhere in nc and sc." It was wired into two places in main.py while
every coastal admission path (the oceanfront override, the coastal-source bypass, downtown
Charleston, their provisional variants) ran BEFORE both and never asked whether the row was a
flip, and _denied_now then exempted the same rows again in the post-enrichment re-pass. Measured
on the 2026-09-21 board: 102 flips outside the 18 counties. docs/data_quality_fixes_2026-09-21.md
section 4.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.main import (
    OCEANFRONT_COASTAL_COUNTIES,
    _denied_now,
    _flip_outside_footprint,
    _in_scope,
)
from foreclosure_scraper.models import Listing, ListingType

FLIP_TYPES = [ListingType.FORECLOSURE_SALE, ListingType.AUCTION, ListingType.SHERIFF_SALE,
              ListingType.HOA_SALE, ListingType.REO]
DISTRESS_TYPES = [ListingType.TAX_LIEN, ListingType.TAX_SALE, ListingType.LIS_PENDENS,
                  ListingType.BANKRUPTCY, ListingType.DISTRESSED]

# a coastal source whose county is "the whole point of the lead" (COASTAL_COUNTY_BYPASS_SOURCES)
COASTAL_SOURCE = "counties_sc.charleston_mie"


def _lead(lt, county="Charleston", state="SC", source=COASTAL_SOURCE, **kw) -> Listing:
    return Listing(source=source, source_url="https://example.gov/x", listing_type=lt,
                   county=county, state=state, street_address="1 Main St", raw=kw.pop("raw", {}), **kw)


@pytest.mark.parametrize("lt", FLIP_TYPES)
def test_a_coastal_flip_through_the_coastal_source_bypass_is_rejected(lt):
    li = _lead(lt)
    assert _flip_outside_footprint(li) is True
    assert _in_scope(li) is False


@pytest.mark.parametrize("lt", DISTRESS_TYPES)
def test_a_coastal_distress_lead_through_the_same_bypass_is_admitted(lt):
    li = _lead(lt)
    assert _flip_outside_footprint(li) is False
    assert _in_scope(li) is True


def test_a_coastal_tax_lien_is_admitted_and_tagged_as_a_coastal_county_row():
    li = _lead(ListingType.TAX_LIEN, county="Georgetown", source="counties_sc.georgetown_civicengage")
    assert _in_scope(li) is True
    assert li.raw.get("coastal_county") is True


def test_the_oceanfront_override_no_longer_admits_a_flip():
    """A beach-town REO: keyword + street pass the 2-of-3 test, county is coastal."""
    kw = dict(description="True oceanfront 3br", street_address="123 N Lumina Ave",
              city="Wrightsville Beach")
    flip = Listing(source="national.fannie_homepath", source_url="https://x", listing_type=ListingType.REO,
                   county="New Hanover", state="NC", raw={}, **kw)
    assert ("New Hanover", "NC") in OCEANFRONT_COASTAL_COUNTIES
    assert _in_scope(flip) is False
    assert not flip.raw.get("oceanfront"), "a rejected flip must not be tagged as an admitted oceanfront row"
    tax = Listing(source="counties_nc.nc_coastal_tax_foreclosure", source_url="https://x",
                  listing_type=ListingType.TAX_LIEN, county="New Hanover", state="NC", raw={}, **kw)
    assert _in_scope(tax) is True


def test_downtown_charleston_no_longer_admits_a_flip():
    flip = Listing(source="national.fannie_homepath", source_url="https://x", listing_type=ListingType.REO,
                   state="SC", county="Charleston", city="Charleston", latitude=32.7765, longitude=-79.9311, raw={})
    assert _in_scope(flip) is False
    lien = Listing(source="counties_sc.charleston_delinquent_tax", source_url="https://x",
                   listing_type=ListingType.TAX_LIEN, state="SC", county="Charleston", city="Charleston",
                   latitude=32.7765, longitude=-79.9311, raw={})
    assert _in_scope(lien) is True


def test_flips_inside_the_footprint_are_still_admitted():
    for county, state in (("Gaston", "NC"), ("Spartanburg", "SC"), ("Buncombe", "NC")):
        assert _in_scope(_lead(ListingType.FORECLOSURE_SALE, county=county, state=state,
                               source="law_firms.brock_scott")) is True, county


def test_distress_leads_are_admitted_anywhere_in_nc_and_sc():
    for county, state in (("Pender", "NC"), ("Onslow", "NC"), ("Greenville", "SC"), ("Charleston", "SC")):
        assert _in_scope(_lead(ListingType.TAX_LIEN, county=county, state=state,
                               source="counties_nc.rutherford_tax")) is True, county


# ---- the post-enrichment re-pass ---------------------------------------------------------

@pytest.mark.parametrize("tag", ["oceanfront", "downtown_charleston", "coastal_county"])
def test_denied_now_no_longer_exempts_a_tagged_coastal_flip(tag):
    flip = _lead(ListingType.FORECLOSURE_SALE, raw={tag: True})
    assert _denied_now(flip) is True


def test_denied_now_still_exempts_a_tagged_coastal_distress_lead():
    for tag in ("oceanfront", "downtown_charleston", "coastal_county"):
        assert _denied_now(_lead(ListingType.TAX_LIEN, raw={tag: True})) is False


def test_denied_now_drops_a_flip_in_a_coastal_county_even_without_a_tag():
    assert _denied_now(_lead(ListingType.REO, county="Onslow", state="NC")) is True
    assert _denied_now(_lead(ListingType.TAX_LIEN, county="Onslow", state="NC")) is False


def test_denied_now_drops_a_flip_that_still_has_no_county_after_enrichment():
    flip = Listing(source="law_firms.hutchens", source_url="https://x", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county=None, raw={})
    assert _denied_now(flip) is True
    lien = Listing(source="counties_nc.rutherford_tax", source_url="https://x", listing_type=ListingType.TAX_LIEN,
                   state="NC", county=None, raw={})
    assert _denied_now(lien) is False, "a countyless DISTRESS lead keeps waiting for its county"


def test_denied_now_keeps_an_in_footprint_flip_and_a_tagged_in_footprint_row():
    assert _denied_now(_lead(ListingType.FORECLOSURE_SALE, county="Gaston", state="NC",
                             source="law_firms.brock_scott")) is False


def test_a_flip_with_no_state_or_no_county_is_not_declared_a_footprint_leak():
    assert _flip_outside_footprint(_lead(ListingType.REO, county="")) is False
    li = _lead(ListingType.REO)
    li.state = ""
    assert _flip_outside_footprint(li) is False
