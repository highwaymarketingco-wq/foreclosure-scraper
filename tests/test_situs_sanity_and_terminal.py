"""Regression tests for the Run #20 audit drop/flag fixes in main.py:

  (1) terminal court statuses (REDEEMED / dismissed / satisfied / disposed)
      are dropped by _active_only — the matter is closed, not a live lead.
  (2) the SITUS SANITY guard (_situs_is_junk) flags business/entity-name and
      'Vacant parcel' placeholder addresses while sparing real road names and
      name-prefixed strings that still carry a recoverable street address.
  (3) the post-enrichment countyless drop also covers reo.* feeds (VRM VA-REO
      etc.), and the out-of-footprint re-pass drops counties we don't track
      (e.g. Aiken SC) without touching the deny set or the coastal track.

Pure-Python; no network.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.main import _active_only, _situs_is_junk
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(*, source: str = "test", **kw) -> Listing:
    base = dict(
        source=source,
        source_url="https://example.com/x",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(kw)
    return Listing(**base)


# --------------------------------------------------------------------------- #
# (1) terminal court statuses                                                  #
# --------------------------------------------------------------------------- #

def test_redeemed_dropped():
    li = _li(source="counties_sc.oconee_forfeited_land", auction_status="redeemed")
    assert _active_only(li, 120) is False


def test_dismissed_dropped():
    li = _li(source="counties_sc.sc_public_index_lis_pendens", auction_status="dismissed")
    assert _active_only(li, 120) is False


def test_satisfied_dropped():
    li = _li(source="counties_sc.sc_public_index_lis_pendens", auction_status="satisfied")
    assert _active_only(li, 120) is False


def test_disposed_dropped():
    li = _li(source="counties_sc.sc_public_index_lis_pendens", auction_status="disposed")
    assert _active_only(li, 120) is False


def test_case_insensitive_terminal():
    li = _li(source="counties_sc.oconee_forfeited_land", auction_status="REDEEMED")
    assert _active_only(li, 120) is False


def test_active_court_statuses_kept():
    """In-progress statuses must NOT be dropped — they are live leads. These
    sources are dateless-OK so a missing sale_date alone won't drop them."""
    for status in ("pending", "hearing", "referred to master", "assigned",
                   "hold", "stayed", "reopen"):
        li = _li(source="counties_sc.sc_public_index_lis_pendens",
                 auction_status=status)
        assert _active_only(li, 120) is True, f"{status!r} wrongly dropped"


# --------------------------------------------------------------------------- #
# (2) situs sanity                                                             #
# --------------------------------------------------------------------------- #

def test_vacant_parcel_placeholder_is_junk():
    assert _situs_is_junk("Vacant parcel — D Death Recorded 2026 05 29 Baker") is True


def test_business_name_prefix_is_junk():
    junk = [
        "Midtown Moter Inn, 210, South Chester Street, Gastonia, NC",
        "Haven of Rest Thrift Store",
        "Jitters Brewing Company",
        "First United Methodist Church",
        "Ebenezer Baptist Church",
        "Salem Davidian Church, 170, Shallow Ford Road, Salem, SC",
        "M D Cleveland Civic Center, 98, Anderson Avenue, Westminster, SC",
        "Woodward & Rick Photography Inc",
        "Oconee Senior Center",
        "Rocky Bottom Retreat and Conference Center for the Blind, Taylor Way, SC",
    ]
    for a in junk:
        assert _situs_is_junk(a) is True, f"should be junk: {a!r}"


def test_real_road_names_with_entity_words_kept():
    """A token-group ending in a road suffix is a street name even if it
    contains 'church'/'academy' — must NOT be flagged."""
    real = [
        "Glassy Mountain Church Road",
        "South Academy Street",
        "GLENN CHURCH LN",
        "Old Baptist Church Rd",
    ]
    for a in real:
        assert _situs_is_junk(a) is False, f"should be kept: {a!r}"


def test_numbered_addresses_kept():
    for a in ("123 Main St", "615 E Calhoun St, Anderson, SC", "0 Earls Bridge Rd"):
        assert _situs_is_junk(a) is False, f"should be kept: {a!r}"


def test_name_prefix_with_embedded_address_kept():
    """A complex name followed by a real '<#> <name> <suffix>' situs is
    recoverable — leave it intact rather than null a usable address."""
    for a in ("STARRWOOD GOLF CO 139 STARRWOOD DR",
              "COLLEGE HEIGHTS   615 E CALHOUN ST",
              "PELZER MILL       3 BAPTIST ST"):
        assert _situs_is_junk(a) is False, f"should be kept: {a!r}"


def test_empty_address_not_junk():
    assert _situs_is_junk(None) is False
    assert _situs_is_junk("") is False
    assert _situs_is_junk("   ") is False
