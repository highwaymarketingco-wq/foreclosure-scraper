"""A coastal-county FLIP is wanted when it is no more than a 5 minute drive from the beach.

THE OWNER'S RULE (2026-10-06): "I'm happy if it's a couple of blocks back but nothing more than a
5 minute drive to the beach", confirmed as "5 minute drive". It applies to flips only (a scheduled
foreclosure / sheriff / HOA sale, an auction, an REO: main._FLIP_LISTING_TYPES). A distress lead is in
scope anywhere in NC and SC and never meets a beach distance.

WHAT THIS CHANGED, AND WHAT IT FOUND
  * The old bar was a hard 250 m. But since the 2026-09-21 flip-footprint fix no coastal flip was admitted
    at any distance (main._flip_outside_footprint ran first and no coastal county is in the 18-county
    footprint), so 250 m only ever shaped the raw.oceanfront TAG on distress leads. On the published board
    of 2026-10-05 there are 0 flip rows in the 16 coastal counties.
  * Now oceanfront.FLIP_COASTAL_MAX_M (2,500 m straight line) decides a coastal flip: 5 minutes at a 25 mph
    beach-town average is 3.35 km of road, about 2.6 km straight at the usual 1.3 road factor.
    OCEANFRONT_DISTANCE_M stays 250 m and raw.oceanfront stays "true beachfront"; a flip within the
    cutoff gets raw.near_beach_drive (the measured distances), and raw.oceanfront too only if within 250 m.
  * The OSM coastline behind distance_to_ocean_m is not only the open ocean (Charleston Harbor, the
    rivers behind the barrier islands, the sound shores are in it: the Charleston Battery is 123 m from it,
    Morehead City downtown 237 m, Manteo 1.5 km). A flip must also be near the curated OCEAN-FACING polyline.

Coordinates are public places; addresses and names are invented.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from foreclosure_scraper import coastal_geofilter, oceanfront
from foreclosure_scraper.main import (
    _denied_now,
    _flip_outside_footprint,
    _in_scope,
    _resolve_coastal_pending,
)
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.oceanfront import (
    FLIP_COASTAL_MAX_M,
    OCEANFRONT_DISTANCE_M,
    flip_near_beach,
    is_oceanfront,
)

# ---- real places, measured against the bundled shoreline (asset m / ocean-facing polyline m) ----
WRIGHTSVILLE_OCEANFRONT = (34.2085, -77.7960)   # New Hanover   48 / 112
TOPSAIL_BLOCKS_BACK = (34.384, -77.592)         # Pender       806 / 410
CAPE_CARTERET_MAINLAND = (34.620, -77.104)      # Carteret    2381 / 2398   (about 2.4 km, across Bogue Sound)
WILMINGTON_OLEANDER = (34.2020, -77.8900)       # New Hanover 4898 / 6442
WILMINGTON_INLAND = (34.2255, -77.9450)         # New Hanover 10314 / 12041
CHARLESTON_BATTERY = (32.7706, -79.9343)        # Charleston   123 / 8571   (harbor shore, not the beach)
MANTEO = (35.9080, -75.6680)                    # Dare        1486 / 6882   (Roanoke Sound shore)
MOREHEAD_CITY = (34.7237, -76.7260)             # Carteret     237 / 3699   (Newport River / Bogue Sound)
RAVENEL_INLAND = (32.785, -80.236)              # Charleston  17211 / 25248
SURFSIDE_BEACH = (33.6060, -78.9670)            # Horry         224 / 366   (Horry is excluded by the owner)

FLIPS = [ListingType.FORECLOSURE_SALE, ListingType.AUCTION, ListingType.SHERIFF_SALE,
         ListingType.HOA_SALE, ListingType.REO]
DISTRESS = [ListingType.TAX_LIEN, ListingType.TAX_SALE, ListingType.LIS_PENDENS, ListingType.BANKRUPTCY,
            ListingType.DISTRESSED, ListingType.PROBATE_NOTICE, ListingType.ESTATE_LEAD]


def _row(lt, county, state, point=None, *, raw=None, source="law_firms.example", **kw) -> Listing:
    lat, lng = point if point else (None, None)
    return Listing(source=source, source_url="https://example.invalid/x", listing_type=lt, county=county,
                   state=state, street_address=kw.pop("street_address", "10 Example St"), latitude=lat,
                   longitude=lng, raw=dict(raw or {}), **kw)


# ---- the numbers ---------------------------------------------------------------------------------

def test_the_two_bars_are_distinct_and_the_true_beachfront_bar_is_unchanged():
    assert OCEANFRONT_DISTANCE_M == 250.0 and coastal_geofilter.NEAR_BEACH_M == 250.0
    assert FLIP_COASTAL_MAX_M == 2500.0 and FLIP_COASTAL_MAX_M > OCEANFRONT_DISTANCE_M


def test_a_listing_800_m_back_is_still_not_true_oceanfront():
    ok, sig = is_oceanfront(description="True oceanfront 3br", street_address="123 N Lumina Ave",
                            city="Wrightsville Beach", latitude=TOPSAIL_BLOCKS_BACK[0],
                            longitude=TOPSAIL_BLOCKS_BACK[1])
    assert ok is False and sig["geo_precise"] is True and sig["geo_distance_m"] > OCEANFRONT_DISTANCE_M


# ---- a coastal flip at 100 m, 800 m, 2.4 km is admitted; 4+ km is not ---------------------------------

@pytest.mark.parametrize("lt", FLIPS)
@pytest.mark.parametrize("county,state,point,band", [
    ("New Hanover", "NC", WRIGHTSVILLE_OCEANFRONT, (0, 250)),
    ("Pender", "NC", TOPSAIL_BLOCKS_BACK, (600, 1000)),
    ("Carteret", "NC", CAPE_CARTERET_MAINLAND, (2200, 2500)),
])
def test_a_coastal_flip_within_the_drive_is_admitted(lt, county, state, point, band):
    ok, sig = flip_near_beach(*point)
    assert ok is True and band[0] <= sig["distance_m"] <= band[1], sig
    li = _row(lt, county, state, point)
    assert _flip_outside_footprint(li) is False
    assert _in_scope(li) is True
    assert li.raw["near_beach_drive"]["distance_m"] == sig["distance_m"]
    assert _denied_now(li) is False, "and the post-enrichment re-pass keeps it, deny list or not"


@pytest.mark.parametrize("lt", FLIPS)
@pytest.mark.parametrize("county,state,point", [
    ("New Hanover", "NC", WILMINGTON_OLEANDER),      # 4.9 km
    ("New Hanover", "NC", WILMINGTON_INLAND),        # 10 km
    ("Charleston", "SC", RAVENEL_INLAND),            # 17 km
])
def test_a_coastal_flip_4_km_or_more_back_is_not(lt, county, state, point):
    li = _row(lt, county, state, point)
    assert _in_scope(li) is False
    assert "near_beach_drive" not in li.raw and not li.raw.get("oceanfront")
    assert _denied_now(li) is True


def test_the_cutoff_is_the_constant():
    """Just inside and just outside FLIP_COASTAL_MAX_M, same point."""
    lat, lng = CAPE_CARTERET_MAINLAND
    d = flip_near_beach(lat, lng)[1]["distance_m"]
    assert flip_near_beach(lat, lng, max_m=d + 1)[0] is True
    assert flip_near_beach(lat, lng, max_m=d - 1)[0] is False


# ---- the tags keep their meaning ------------------------------------------------------------------

def test_oceanfront_tag_means_true_beachfront_and_near_beach_drive_means_admitted():
    near = _row(ListingType.REO, "New Hanover", "NC", WRIGHTSVILLE_OCEANFRONT)
    far = _row(ListingType.REO, "Pender", "NC", TOPSAIL_BLOCKS_BACK)
    assert _in_scope(near) is True and _in_scope(far) is True
    assert near.raw.get("oceanfront") is True and "near_beach_drive" in near.raw
    assert far.raw.get("oceanfront") is not True, "800 m back is admitted but is not oceanfront"
    assert far.raw["near_beach_drive"]["max_m"] == FLIP_COASTAL_MAX_M


# ---- harbor, river and sound shores are not the beach -----------------------------------------------

@pytest.mark.parametrize("name,county,state,point,shore_m", [
    ("Charleston Battery", "Charleston", "SC", CHARLESTON_BATTERY, 123),
    ("Manteo", "Dare", "NC", MANTEO, 1486),
    ("Morehead City", "Carteret", "NC", MOREHEAD_CITY, 237),
])
def test_a_harbor_river_or_sound_front_flip_is_not_near_the_beach(name, county, state, point, shore_m):
    ok, sig = flip_near_beach(*point)
    assert abs(sig["distance_m"] - shore_m) < 5, "the OSM shore really is that close: that is the trap"
    assert ok is False and sig["ocean_facing_m"] > FLIP_COASTAL_MAX_M + oceanfront.OCEAN_FACING_SLACK_M, name
    li = _row(ListingType.FORECLOSURE_SALE, county, state, point)
    assert _in_scope(li) is False


def test_downtown_charleston_is_unchanged_a_distress_lead_is_kept_and_tagged_a_flip_is_not():
    lien = _row(ListingType.TAX_LIEN, "Charleston", "SC", (32.7765, -79.9311), city="Charleston",
                source="counties_sc.sc_dew_lien_registry")
    assert _in_scope(lien) is True and lien.raw.get("downtown_charleston") is True
    for lt in FLIPS:
        flip = _row(lt, "Charleston", "SC", (32.7765, -79.9311), city="Charleston",
                    source="national.fannie_homepath")
        assert _in_scope(flip) is False
        assert not flip.raw.get("downtown_charleston") and "near_beach_drive" not in flip.raw


# ---- the keyword does not outvote a precise point -----------------------------------------------------

@pytest.mark.parametrize("lt", FLIPS)
def test_a_beachfront_keyword_flip_far_inland_fails_when_the_point_is_precise(lt):
    li = _row(lt, "New Hanover", "NC", WILMINGTON_INLAND, street_address="123 N Lumina Ave",
              city="Wrightsville Beach", description="True oceanfront 3br, beachfront, steps to the beach")
    assert _in_scope(li) is False
    assert not li.raw.get("oceanfront")


# ---- a distress lead is unchanged: admitted at any distance, statewide ----------------------------------

@pytest.mark.parametrize("lt", DISTRESS)
@pytest.mark.parametrize("county,state,point", [
    ("New Hanover", "NC", WRIGHTSVILLE_OCEANFRONT),
    ("New Hanover", "NC", WILMINGTON_OLEANDER),
    ("Charleston", "SC", RAVENEL_INLAND),
    ("Brunswick", "NC", None),
])
def test_a_distress_lead_is_admitted_at_any_distance(lt, county, state, point):
    li = _row(lt, county, state, point)
    assert _in_scope(li) is True
    assert "near_beach_drive" not in li.raw, "the beach-drive rule is for flips"
    assert _denied_now(li) is False


def test_a_distress_lead_is_tagged_oceanfront_only_within_250_m():
    near = _row(ListingType.TAX_LIEN, "New Hanover", "NC", WRIGHTSVILLE_OCEANFRONT)
    back = _row(ListingType.TAX_LIEN, "Pender", "NC", TOPSAIL_BLOCKS_BACK)
    assert _in_scope(near) and _in_scope(back)
    assert near.raw.get("oceanfront") is True
    assert back.raw.get("oceanfront") is not True, "the true-beachfront bar did not move"


# ---- no point yet: the provisional path and the post-geocode re-pass ------------------------------------

def _ingest_then_geocode(li, point):
    assert _in_scope(li) is True
    assert li.raw.get("oceanfront_pending") is True, "precondition: admitted provisionally"
    li.latitude, li.longitude = point
    return _resolve_coastal_pending(li)


@pytest.mark.parametrize("point,keep", [
    (WRIGHTSVILLE_OCEANFRONT, True),
    (TOPSAIL_BLOCKS_BACK, True),
    (CAPE_CARTERET_MAINLAND, True),
    (WILMINGTON_OLEANDER, False),
    (CHARLESTON_BATTERY, False),
])
def test_a_provisional_flip_is_kept_or_dropped_by_the_drive_once_geocoded(point, keep):
    li = _row(ListingType.FORECLOSURE_SALE, "New Hanover", "NC")
    assert _ingest_then_geocode(li, point) is keep
    assert "oceanfront_pending" not in li.raw
    assert ("near_beach_drive" in li.raw) is keep
    assert _denied_now(li) is (not keep), "the next pass in run() agrees with the re-pass"


def test_a_provisional_flip_geocoded_to_the_harbor_is_not_rescued_by_downtown_charleston():
    li = _row(ListingType.FORECLOSURE_SALE, "Charleston", "SC", city="Charleston")
    assert _ingest_then_geocode(li, (32.7765, -79.9311)) is False


def test_a_provisional_flip_that_never_gets_a_point_drops_but_a_distress_lead_is_kept():
    flip = _row(ListingType.FORECLOSURE_SALE, "Brunswick", "NC", parcel_id="2000001234", street_address=None)
    assert _in_scope(flip) is True and _resolve_coastal_pending(flip) is False
    lead = _row(ListingType.ESTATE_LEAD, "Brunswick", "NC", parcel_id="2000001234", street_address=None)
    assert _in_scope(lead) is True and _resolve_coastal_pending(lead) is True


def test_a_coastal_flip_with_neither_a_point_nor_a_locator_is_rejected():
    li = _row(ListingType.FORECLOSURE_SALE, "Brunswick", "NC", street_address=None, city="Southport")
    assert _in_scope(li) is False


# ---- a shared fallback point proves nothing --------------------------------------------------------------

@pytest.mark.parametrize("flag", ["county_centroid", "county_centroid_no_addr", "centroid_snap"])
def test_a_flip_on_a_flagged_fallback_point_is_not_admitted_even_when_it_would_measure_near(flag):
    li = _row(ListingType.FORECLOSURE_SALE, "Pender", "NC", TOPSAIL_BLOCKS_BACK, raw={"geo_imprecise": flag})
    assert flip_near_beach(*TOPSAIL_BLOCKS_BACK, raw=li.raw) == (None, {})
    assert _in_scope(li) is False
    assert _denied_now(li) is True


def test_a_real_address_geocode_is_a_trusted_point():
    li = _row(ListingType.FORECLOSURE_SALE, "Pender", "NC", TOPSAIL_BLOCKS_BACK,
              raw={"geo_imprecise": "census_geocode"})
    assert _in_scope(li) is True


def test_bad_coordinates_are_unmeasurable_not_a_crash():
    for bad in ((None, None), ("x", -77.0), (float("nan"), -77.0), (95.0, -77.0)):
        assert flip_near_beach(*bad) == (None, {})


# ---- the owner's other exclusions and the footprint are untouched ------------------------------------------

def test_horry_is_still_excluded_at_the_beach():
    li = _row(ListingType.FORECLOSURE_SALE, "Horry", "SC", SURFSIDE_BEACH)
    assert flip_near_beach(*SURFSIDE_BEACH)[0] is True, "the point itself is on the beach"
    assert _in_scope(li) is False, "Horry is excluded per the owner (2026-08-12), it is not a coastal county here"


def test_footprint_flips_and_the_coastal_source_bypass_are_unchanged():
    gaston = _row(ListingType.FORECLOSURE_SALE, "Gaston", "NC", source="law_firms.brock_scott")
    assert _in_scope(gaston) is True
    inland_bypass = _row(ListingType.FORECLOSURE_SALE, "Georgetown", "SC", (33.4, -79.233),
                         source="counties_sc.georgetown_civicengage")
    assert _in_scope(inland_bypass) is False, "a coastal-source flip is decided by the drive, not the source"
    tax = _row(ListingType.TAX_SALE, "Georgetown", "SC", (33.4, -79.233),
               source="counties_sc.georgetown_civicengage")
    assert _in_scope(tax) is True and tax.raw.get("coastal_county") is True


def test_a_tag_shelters_no_flip_only_the_point_does():
    for tag in ("oceanfront", "downtown_charleston", "coastal_county"):
        far = _row(ListingType.FORECLOSURE_SALE, "New Hanover", "NC", WILMINGTON_OLEANDER, raw={tag: True})
        assert _denied_now(far) is True, tag
    published = _row(ListingType.FORECLOSURE_SALE, "New Hanover", "NC", TOPSAIL_BLOCKS_BACK)   # no tags at all
    assert _denied_now(published) is False, "a flip published last run comes back untagged and is judged by its point"


# ---- the data-quality stamp agrees ------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import quarantine_flip_leaks as Q  # noqa: E402


def test_quarantine_does_not_stamp_a_near_beach_flip_and_clears_a_stale_stamp(monkeypatch):
    import _dq_common as C
    monkeypatch.setattr(C, "missing_raw_keep", lambda keys: [])
    lt = ListingType.FORECLOSURE_SALE
    assert Q.flip_verdict("NC", "Pender", lt, None, *TOPSAIL_BLOCKS_BACK, {}) == "near_beach"
    assert Q.flip_verdict("NC", "Pender", lt, None, *WILMINGTON_OLEANDER, {}) == "leak"
    assert Q.flip_verdict("NC", "Pender", lt) == "leak", "no point: nothing to measure"
    assert Q.flip_verdict("NC", "Pender", lt, None, *TOPSAIL_BLOCKS_BACK, {"geo_imprecise": "centroid_snap"}) == "leak"
    assert Q.flip_verdict("SC", "Horry", lt, None, *SURFSIDE_BEACH, {}) == "leak"
    rows = [_row(lt, "Pender", "NC", TOPSAIL_BLOCKS_BACK, raw={"scope": Q.STAMP}),
            _row(lt, "Pender", "NC", WILMINGTON_OLEANDER, raw={}),
            _row(ListingType.TAX_LIEN, "Pender", "NC", WILMINGTON_OLEANDER, raw={})]
    Q.apply_rows(rows)
    assert "scope" not in rows[0].raw, "near the beach: the earlier stamp is cleared"
    assert rows[1].raw["scope"] == Q.STAMP and "scope" not in rows[2].raw and len(rows) == 3
