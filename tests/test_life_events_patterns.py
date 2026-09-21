"""A company name containing the word ESTATE is not a death (audit 2026-09-21, F13)."""
from __future__ import annotations

from foreclosure_scraper.enrichment_life_events import enrich_life_events
from foreclosure_scraper.models import Listing, ListingType


def _tag(owner):
    li = Listing(source="x", source_url="u", listing_type=ListingType.TAX_LIEN, state="NC", county="Gaston",
                 owner_name=owner, raw={})
    enrich_life_events([li])
    return li.raw.get("life_events") or []


def test_real_estate_company_is_not_probate():
    assert "estate_probate" not in _tag("ACME REAL ESTATE HOLDINGS LLC")
    assert "estate_probate" not in _tag("Smith Estate Planning Inc")


def test_death_shaped_names_still_tag_probate():
    assert "estate_probate" in _tag("ESTATE OF JOHN Q SMITH")
    assert "estate_probate" in _tag("EST OF MARY JONES")
    assert "estate_probate" in _tag("SMITH HEIRS")
    assert "estate_probate" in _tag("JONES, HEIR")


def test_does_not_touch_the_distress_stack():
    li = Listing(source="x", source_url="u", listing_type=ListingType.TAX_LIEN, state="NC", county="Gaston",
                 owner_name="ESTATE OF A B", raw={"distress_stack": {"categories": ["FINANCIAL"]}})
    enrich_life_events([li])
    assert li.raw["distress_stack"]["categories"] == ["FINANCIAL"]
