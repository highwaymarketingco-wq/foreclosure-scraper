"""A county with no live GIS layer (and no full parcel_cache hit) is a structural dead end,
not a transient failure -- it must be stamped queried=True so it stops being re-selected by
every future backfill_gis_attrs_boardwide.py batch forever (found live 2026-11-11: this was
previously an unstamped `return`, so NC counties outside its 18-county live-layer list -- the
large majority of NC's ~100 counties -- never converged across repeated board-wide batches)."""
import asyncio
from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_gis_attrs as g


def _li(parcel=None, lat=None, lng=None, county="Wake", state="NC"):
    now = datetime.utcnow()
    return Listing(source="s", source_url="https://x/1", listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN, state=state, county=county,
                   parcel_id=parcel, latitude=lat, longitude=lng,
                   first_seen=now, last_seen=now, raw={})


def test_wake_county_has_no_live_layer():
    # Sanity check on the test's own premise, not the fix -- Wake must genuinely be outside
    # NC_GIS or this test proves nothing.
    assert "Wake" not in g.NC_GIS


def test_no_live_layer_county_is_stamped_queried_not_left_forever_unmarked():
    li = _li(lat=35.78, lng=-78.64)
    stats = asyncio.run(g.enrich_gis_attrs([li]))
    assert stats.get("no_live_layer") == 1
    assert (li.raw.get("gis") or {}).get("queried") is True
    assert (li.raw.get("gis") or {}).get("source") == "no_live_layer"


def test_no_live_layer_stamp_is_idempotent_second_call_is_skipped():
    li = _li(lat=35.78, lng=-78.64)
    asyncio.run(g.enrich_gis_attrs([li]))
    stats2 = asyncio.run(g.enrich_gis_attrs([li]))
    assert stats2["skipped_done"] == 1
    assert stats2.get("no_live_layer", 0) == 0


def test_does_not_overwrite_an_existing_gis_block_from_another_source():
    li = _li(lat=35.78, lng=-78.64)
    li.raw["gis"] = {"owner": "ALREADY HERE"}
    asyncio.run(g.enrich_gis_attrs([li]))
    assert li.raw["gis"]["queried"] is True
    assert li.raw["gis"]["source"] == "no_live_layer"
    assert li.raw["gis"]["owner"] == "ALREADY HERE"
