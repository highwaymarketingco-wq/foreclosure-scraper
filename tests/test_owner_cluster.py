"""Tests for enrichment_owner_cluster -- same-owner parcel clustering.

Dirty Deeds Tier A #2: one death/owner touching many parcels is worth more
than the same parcels scored independently.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_owner_cluster import enrich_owner_cluster
from foreclosure_scraper.models import Listing, ListingType


def _mk(owner_name, county="Buncombe", state="NC", parcel_id=None, street_address=None,
        source="s", source_url=None, market_value=None):
    return Listing(
        source=source, source_url=source_url or f"https://example.com/{owner_name}-{parcel_id}-{street_address}",
        listing_type=ListingType.TAX_LIEN, state=state, county=county,
        owner_name=owner_name, parcel_id=parcel_id, street_address=street_address,
        market_value=market_value,
    )


def test_two_distinct_parcels_same_owner_same_county_cluster():
    a = _mk("SMITH JOHN ROBERT", parcel_id="P1", market_value=100_000)
    b = _mk("SMITH JOHN ROBERT", parcel_id="P2", market_value=200_000)
    stats = enrich_owner_cluster([a, b])
    assert stats["clusters"] == 1
    assert stats["tagged_rows"] == 2
    assert a.raw["owner_cluster"]["cluster_size"] == 2
    assert b.raw["owner_cluster"]["cluster_size"] == 2
    assert a.raw["owner_cluster"]["cluster_id"] == b.raw["owner_cluster"]["cluster_id"]
    assert a.raw["owner_cluster"]["total_value"] == 300_000.0


def test_single_property_is_not_a_cluster():
    a = _mk("SMITH JOHN ROBERT", parcel_id="P1")
    stats = enrich_owner_cluster([a])
    assert stats["clusters"] == 0
    assert "owner_cluster" not in (a.raw or {})


def test_duplicate_source_rows_for_same_property_do_not_inflate_cluster_size():
    """liensnc vs counties_generic.liensnc double-tagging the same parcel must
    not look like a two-property cluster."""
    a = _mk("SMITH JOHN ROBERT", parcel_id="P1", source="liensnc")
    b = _mk("SMITH JOHN ROBERT", parcel_id="P1", source="counties_generic.liensnc")
    stats = enrich_owner_cluster([a, b])
    assert stats["clusters"] == 0


def test_different_counties_do_not_cluster():
    a = _mk("SMITH JOHN ROBERT", county="Buncombe", parcel_id="P1")
    b = _mk("SMITH JOHN ROBERT", county="Spartanburg", state="SC", parcel_id="P2")
    stats = enrich_owner_cluster([a, b])
    assert stats["clusters"] == 0


def test_entities_are_excluded_from_clustering():
    a = _mk("SMITH RENTALS LLC", parcel_id="P1")
    b = _mk("SMITH RENTALS LLC", parcel_id="P2")
    stats = enrich_owner_cluster([a, b])
    assert stats["clusters"] == 0


def test_conflicting_middle_names_lower_confidence():
    """Same surname+first name, but spelled-out middle names disagree across
    the two properties -- likely two different people, flag it."""
    a = _mk("SMITH JOHN ROBERT", parcel_id="P1")
    b = _mk("SMITH JOHN MICHAEL", parcel_id="P2")
    stats = enrich_owner_cluster([a, b])
    assert stats["clusters"] == 1
    assert a.raw["owner_cluster"]["confidence"] == "low"


def test_agreeing_or_absent_middles_stay_high_confidence():
    a = _mk("SMITH JOHN ROBERT", parcel_id="P1")
    b = _mk("SMITH JOHN", parcel_id="P2")  # no middle name -- no conflict
    stats = enrich_owner_cluster([a, b])
    assert a.raw["owner_cluster"]["confidence"] == "high"


def test_three_way_cluster_reports_full_size():
    a = _mk("BYRD SANDRA LEE", parcel_id="P1", market_value=50_000)
    b = _mk("BYRD SANDRA LEE", parcel_id="P2", market_value=75_000)
    c = _mk("BYRD SANDRA LEE", parcel_id="P3", market_value=25_000)
    stats = enrich_owner_cluster([a, b, c])
    assert stats["clusters"] == 1
    assert stats["max_cluster_size"] == 3
    assert a.raw["owner_cluster"]["total_value"] == 150_000.0
    assert len(a.raw["owner_cluster"]["parcel_ids"]) == 3


def test_no_owner_name_never_crashes_and_is_never_tagged():
    a = _mk(None, parcel_id="P1")
    b = _mk("", parcel_id="P2")
    stats = enrich_owner_cluster([a, b])
    assert stats["clusters"] == 0
    assert "owner_cluster" not in (a.raw or {})


def test_national_homebuilder_names_excluded():
    """Live dry-run on the real board 2026-09-16 found MERITAGE HOMES (264
    parcels) and LENNAR HOMES (189 parcels) clustered as individual people --
    neither contains a name_normalize.is_entity() marker. Must be excluded."""
    a = _mk("MERITAGE HOMES", parcel_id="P1")
    b = _mk("MERITAGE HOMES", parcel_id="P2")
    stats = enrich_owner_cluster([a, b])
    assert stats["clusters"] == 0

    c = _mk("LENNAR HOMES", parcel_id="P3")
    d = _mk("LENNAR HOMES", parcel_id="P4")
    stats2 = enrich_owner_cluster([c, d])
    assert stats2["clusters"] == 0


def test_government_entity_excluded():
    """Live dry-run found 'LINCOLN COUNTY' clustered as a person (130 county-
    owned parcels). is_entity() has no government check at all."""
    a = _mk("LINCOLN COUNTY", parcel_id="P1")
    b = _mk("LINCOLN COUNTY", parcel_id="P2")
    stats = enrich_owner_cluster([a, b])
    assert stats["clusters"] == 0


def test_hoa_or_community_style_name_excluded():
    """Live dry-run found 'CONNESTEE FALLS' (a real Transylvania County NC
    gated community) parsed as PersonName(surname='FALLS', given=
    ('CONNESTEE',))."""
    a = _mk("CONNESTEE FALLS", parcel_id="P1")
    b = _mk("CONNESTEE FALLS", parcel_id="P2")
    stats = enrich_owner_cluster([a, b])
    assert stats["clusters"] == 0


def test_oversized_cluster_is_flagged_low_confidence_not_dropped():
    """A implausibly large same-name cluster (more properties than any real
    individual multi-parcel owner in the source corpus) must still be
    reported -- never silently dropped -- but marked low confidence so a
    human knows to sanity-check it rather than trust it at face value."""
    listings = [_mk("VERYCOMMON NAME", parcel_id=f"P{i}") for i in range(20)]
    stats = enrich_owner_cluster(listings)
    assert stats["clusters"] == 1
    assert stats["tagged_rows"] == 20
    assert listings[0].raw["owner_cluster"]["cluster_size"] == 20
    assert listings[0].raw["owner_cluster"]["confidence"] == "low"
    assert listings[0].raw["owner_cluster"]["low_confidence_reason"] == "oversized"


def test_plausible_sized_cluster_stays_high_confidence():
    """Six properties under one owner (the corpus's own headline example --
    'first deal in ep 038 was six houses under one dead owner') must NOT
    trip the oversized flag."""
    listings = [_mk("JONES MARY ELLEN", parcel_id=f"P{i}") for i in range(6)]
    stats = enrich_owner_cluster(listings)
    assert listings[0].raw["owner_cluster"]["confidence"] == "high"
    assert listings[0].raw["owner_cluster"]["low_confidence_reason"] is None


def test_never_drops_a_lead():
    listings = [_mk("SMITH JOHN ROBERT", parcel_id="P1"), _mk(None, parcel_id="P2")]
    before = len(listings)
    enrich_owner_cluster(listings)
    assert len(listings) == before
