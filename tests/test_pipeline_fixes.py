"""Pin pipeline-ordering invariants for image enrichment & scope bypass.

Two specific bugs surfaced after Run #13:

1. Vision saw only 1 photo per listing because `enrich_with_vision` ran
   BEFORE `enrich_with_address_photos` populated the full gallery into
   raw.images.real. Result: Marietta St case had Vision tier='gut' /
   $161k rehab when (with all 6 photos) it should've been 'major' / $63k.
   The fix moves photos+images BEFORE vision in main.run().

2. CourtListener bankruptcy listings have state set but no county/zip at
   scrape time, so they fail _in_scope and never reach the bk_property
   enrichment that would fill in their county. Result: 600 listings
   silently dropped. The fix adds SCOPE_BYPASS_SOURCES.
"""
from __future__ import annotations

import inspect
from datetime import datetime

from foreclosure_scraper import main as orchestrator
from foreclosure_scraper.main import SCOPE_BYPASS_SOURCES, _in_scope
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


# ---- Fix A: photos+images BEFORE vision ----

def test_photos_runs_before_vision():
    src = inspect.getsource(orchestrator.run)
    photos_idx = src.find("enrich_with_address_photos(enriched)")
    vision_idx = src.find("enrich_with_vision(enriched)")
    assert photos_idx > 0, "enrich_with_address_photos no longer called"
    assert vision_idx > 0, "enrich_with_vision no longer called"
    assert photos_idx < vision_idx, (
        "Pipeline ordering broken: photos enrichment must run BEFORE vision so "
        "Vision sees the full Realtor gallery (not just the primary photo). "
        f"Found photos at offset {photos_idx}, vision at {vision_idx}."
    )


def test_images_runs_before_vision():
    src = inspect.getsource(orchestrator.run)
    images_idx = src.find("enrich_with_images(enriched")
    vision_idx = src.find("enrich_with_vision(enriched)")
    assert images_idx > 0
    assert vision_idx > 0
    assert images_idx < vision_idx, (
        "enrich_with_images must run BEFORE vision so raw.images.real is "
        "populated when Vision reads from it."
    )


# ---- Fix B: SCOPE_BYPASS_SOURCES ----

def _li(**kw) -> Listing:
    base = dict(
        source="x", source_url="http://x",
        listing_type=ListingType.LIS_PENDENS, property_kind=PropertyKind.UNKNOWN,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(), raw={},
    )
    base.update(kw)
    return Listing(**base)


def test_courtlistener_bankruptcy_bypasses_scope():
    """A CL bankruptcy listing with state=NC but no county and no zip should
    pass the scope filter (the bk_property enrichment fills county later)."""
    li = _li(
        source="national.courtlistener_bankruptcy",
        state="NC", county=None, zip_code=None,
        case_number="26-30621", defendant="Smith John",
    )
    assert _in_scope(li) is True


def test_courtlistener_civil_bypasses_scope():
    li = _li(
        source="national.courtlistener_civil",
        state="SC", county=None, zip_code=None,
    )
    assert _in_scope(li) is True


def test_courtlistener_adversary_bypasses_scope():
    li = _li(
        source="national.courtlistener_adversary",
        state="NC", county=None, zip_code=None,
    )
    assert _in_scope(li) is True


def test_non_cl_listing_with_no_county_still_filtered():
    """The bypass must NOT leak to other sources — a HomeHarvest listing
    with state but no county is genuinely out of scope and should be
    filtered as before."""
    li = _li(
        source="national.homeharvest",
        state="NC", county=None, zip_code=None,
    )
    assert _in_scope(li) is False


def test_in_scope_county_still_passes_for_normal_sources():
    """Sanity: a normal listing in a tracked county still passes."""
    li = _li(
        source="counties_sc.spartanburg_master_in_equity",
        state="SC", county="Spartanburg",
    )
    assert _in_scope(li) is True


def test_zip_prefix_fallback_still_works():
    """A listing with zip but no county should still pass via the zip
    prefix path (not via the scope-bypass)."""
    li = _li(
        source="national.distressed",
        state="NC", county=None, zip_code="28792",  # Henderson NC zip
    )
    assert _in_scope(li) is True


def test_scope_bypass_set_only_contains_courtlistener():
    """The bypass must be tightly scoped — only CL sources. Adding other
    sources here without thought would let cross-state listings leak in."""
    assert SCOPE_BYPASS_SOURCES == {
        "national.courtlistener_bankruptcy",
        "national.courtlistener_civil",
        "national.courtlistener_adversary",
    }
