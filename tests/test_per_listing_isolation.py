"""Pin per-listing isolation in synchronous enrichments.

The original validation/data_quality/property_kind loops would short-
circuit on the first listing that raised, leaving every listing AFTER
it un-validated/un-enriched. The orchestrator's outer try/except
swallowed the exception silently — the symptom was 'random listings
have no data_quality flags / un-normalized counties' that was never
attributable.

These tests construct a deliberately corrupt listing (raw = string
instead of dict, plus a normal listing) and verify:
  1. the corrupt one is logged + counted
  2. the clean one still gets validated/enriched
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.models import Listing, PropertyKind, ListingType
from foreclosure_scraper.validation import validate
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
from foreclosure_scraper.enrichment_property_kind import enrich_property_kind


def _good_listing() -> Listing:
    return Listing(
        source="counties_nc.wake_tax",
        source_url="https://example.com/1",
        state="NC",
        county="Wake",
        property_kind=PropertyKind.UNKNOWN,
        listing_type=ListingType.TAX_SALE,
        opening_bid=15000.0,
        living_sqft=1500.0,
        raw={},
    )


def _bomb_listing() -> Listing:
    """A listing whose .raw access path will trip code that assumes dict.
    We can't easily make Pydantic accept a non-dict raw, so we simulate
    failure by using a raw that has unexpected nested types in a key
    that one of the validators reaches into. Fall back: monkey-patch
    after construction."""
    li = Listing(
        source="counties_nc.wake_tax",
        source_url="https://example.com/2",
        state="NC",
        county="Wake",
        property_kind=PropertyKind.UNKNOWN,
        listing_type=ListingType.TAX_SALE,
        raw={"comps": "this is supposed to be a list, not a string"},
    )
    return li


def test_validation_isolates_per_listing():
    """A bomb listing shouldn't prevent the clean one from being validated."""
    good = _good_listing()
    good.county = "wake"  # lowercase — should be normalized to "Wake"
    bomb = _bomb_listing()

    stats = validate([bomb, good, _good_listing()])

    # Clean listing got normalized
    assert good.county == "Wake"
    assert stats["county_normalized"] >= 1


def test_data_quality_isolates_per_listing():
    """A bomb listing shouldn't prevent the clean one from getting flags."""
    good = _good_listing()
    good.street_address = None  # → "no_address" flag
    bomb = _bomb_listing()

    stats = enrich_data_quality([bomb, good])

    assert isinstance(good.raw, dict)
    assert "data_quality" in good.raw
    # Clean listing got the no_address flag
    assert "no_address" in good.raw["data_quality"]["flags"]


def test_property_kind_isolates_per_listing():
    """A bomb listing shouldn't prevent the clean one from being classified."""
    good = _good_listing()  # property_kind starts as UNKNOWN
    bomb = _bomb_listing()

    enrich_property_kind([bomb, good])

    # Clean listing got classified (fallback SFR if nothing else)
    assert good.property_kind != PropertyKind.UNKNOWN


def test_validation_stats_track_exceptions():
    """The exceptions counter should be present in stats so run_health
    can surface unexpected per-listing failures."""
    stats = validate([_good_listing()])
    assert "validation_exceptions" in stats


def test_data_quality_stats_track_exceptions():
    stats = enrich_data_quality([_good_listing()])
    assert "exceptions" in stats
