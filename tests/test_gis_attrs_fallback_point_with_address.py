"""A geocoder-fallback-bound lead with no parcel_id is not necessarily a permanent dead end --
other enrichers in this codebase (enrichment_resolve_name_to_property.py) can still backfill a
parcel_id for it LATER, so the original fix (2026-11-21) deliberately left it unstamped rather
than risk losing that future chance forever.

FIXED 2026-11-25, for exactly the subset where that risk doesn't apply: a row that ALSO carries
a street_address can never reach ANY real parcel_id-backfill path in this codebase --
enrichment_parcel_from_geo.py excludes every fallback-point row outright (same reasoning as
here), and enrichment_resolve_name_to_property.py's own _is_target() requires NO street_address
as well as no parcel_id. For that subset, permanent-skip costs nothing, proven rather than
assumed (board-wide measurement, 2026-11-25: 16,502 of 50,063 stuck rows carry an address).
A row with NO address still gets the original, unstamped skip -- confirmed below."""
import asyncio
from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_gis_attrs as g

# A real county-seat centroid this codebase already uses as its own fallback-point test
# coordinate (enrichment_geocode.COUNTY_SEAT_CENTROIDS[("SC", "Anderson")]). SC counties all
# carry a live layer, so a row here reaches the fallback-point check, not the no_live_layer one.
_ANDERSON_SEAT = (34.504, -82.650)


def _li(street_address=None, lat=_ANDERSON_SEAT[0], lng=_ANDERSON_SEAT[1]):
    now = datetime.utcnow()
    return Listing(source="s", source_url="https://x/1", listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN, state="SC", county="Anderson",
                   parcel_id=None, latitude=lat, longitude=lng, street_address=street_address,
                   first_seen=now, last_seen=now, raw={})


def test_anderson_seat_is_genuinely_a_county_seat_fallback_point():
    # Sanity check on the test's own premise, not the fix.
    from foreclosure_scraper.enrichment_geocode import is_county_seat_point
    assert is_county_seat_point(*_ANDERSON_SEAT)
    assert "Anderson" in g.SC_GIS  # SC has a live layer everywhere -- must not hit no_live_layer


def test_fallback_point_with_address_is_stamped_unreachable():
    li = _li(street_address="123 Main St")
    stats = asyncio.run(g.enrich_gis_attrs([li]))
    assert stats.get("fallback_point_with_address_stamped") == 1
    assert stats.get("skipped_fallback_point", 0) == 0
    assert (li.raw.get("gis") or {}).get("queried") is True
    assert (li.raw.get("gis") or {}).get("source") == "fallback_point_with_address_unreachable"


def test_fallback_point_with_address_stamp_is_idempotent():
    li = _li(street_address="123 Main St")
    asyncio.run(g.enrich_gis_attrs([li]))
    stats2 = asyncio.run(g.enrich_gis_attrs([li]))
    assert stats2["skipped_done"] == 1
    assert stats2.get("fallback_point_with_address_stamped", 0) == 0


def test_fallback_point_without_address_is_still_left_unstamped():
    """The original, unchanged behavior for the subset that genuinely needs it: no address means
    enrichment_resolve_name_to_property.py could still reach this row later, so it must NOT be
    permanently marked done."""
    li = _li(street_address=None)
    stats = asyncio.run(g.enrich_gis_attrs([li]))
    assert stats.get("skipped_fallback_point") == 1
    assert stats.get("fallback_point_with_address_stamped", 0) == 0
    assert (li.raw.get("gis") or {}).get("queried") is not True


def test_fallback_point_without_address_stays_reselectable_every_run():
    li = _li(street_address=None)
    asyncio.run(g.enrich_gis_attrs([li]))
    stats2 = asyncio.run(g.enrich_gis_attrs([li]))
    # unlike the stamped case, a second run re-selects it (skipped_done must NOT fire)
    assert stats2.get("skipped_done", 0) == 0
    assert stats2.get("skipped_fallback_point") == 1
