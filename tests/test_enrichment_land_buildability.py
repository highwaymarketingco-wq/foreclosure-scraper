"""Land buildability layer (Dirty Deeds Tier B #35) -- pure geometry math plus
the two live sub-signals (landlocked candidate flag, cemetery proximity).

Every fixture geometry below was pulled LIVE from the real ArcGIS endpoints
this module queries (NC OneMap NC1Map_Parcels + NC1Map_Transportation, the
Buncombe and Gaston county cemetery layers) on 2026-09-29, against a real
Lincoln County NC land lead already on the board (parcel_id "4605830808",
"7440 Edgestone Ln") and real cemetery records ("New Morgan Hill Baptist
Church Cemetery" / Buncombe, "Dallas Presbyterian Church Cemetery" / Gaston).
Network calls are not exercised in CI -- the mocked client below replays
those exact captured payloads.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

import foreclosure_scraper.enrichment_land_buildability as M
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

# ---------------------------------------------------------------------------
# Real geometry captured live 2026-09-29.
# ---------------------------------------------------------------------------

# Lincoln County NC parcel 4605830808, "7440 Edgestone Ln" -- board's own
# parcel_id matches NC OneMap's parno exactly for this county/parcel.
EDGESTONE_LAT, EDGESTONE_LON = 35.53032605540521, -80.98989419041725
EDGESTONE_RINGS = [[
    [-80.98974156768823, 35.530522877043204], [-80.98917085086715, 35.530349310641576],
    [-80.98987699975363, 35.530082343459966], [-80.99028304807109, 35.53008702419034],
    [-80.99038856846406, 35.530140256361406], [-80.99018426081602, 35.53063378883166],
    [-80.9901787622039, 35.530632332728956], [-80.99014699287386, 35.53062203345327],
    [-80.99011482764001, 35.53061277027373], [-80.99008266773804, 35.53060367920205],
    [-80.99005010043346, 35.530595110508315], [-80.99001754573523, 35.530587055505585],
    [-80.98974156768823, 35.530522877043204],
]]
EDGESTONE_ROAD_PATHS = [[
    [-80.99189761799235, 35.53130483769901], [-80.99168155911119, 35.5312668392399],
    [-80.99161049539352, 35.53124791110812], [-80.99137540325326, 35.53117190040627],
    [-80.99077288019699, 35.530915942025246], [-80.99024667842683, 35.53069240593934],
    [-80.99012441738768, 35.53065052585385], [-80.98999817283911, 35.53061746807372],
    [-80.98971457891412, 35.53055126767868],
]]

# Gaston County NC cemetery polygon, "Dallas Presbyterian Church Cemetery".
DALLAS_CEMETERY_RINGS = [[
    [-81.1751617371632, 35.3141926008372], [-81.17467327187839, 35.3141739423467],
    [-81.17471656295437, 35.313261341431215], [-81.17531813468136, 35.31328407078395],
    [-81.17530180648001, 35.313530993738105], [-81.17520573240729, 35.313527362123985],
    [-81.1751617371632, 35.3141926008372],
]]
DALLAS_CENTROID_LON = sum(p[0] for p in DALLAS_CEMETERY_RINGS[0][:-1]) / 6
DALLAS_CENTROID_LAT = sum(p[1] for p in DALLAS_CEMETERY_RINGS[0][:-1]) / 6

# Buncombe County NC cemetery point, "New Morgan Hill Baptist Church Cemetery".
MORGAN_HILL_LON, MORGAN_HILL_LAT = -82.65521761182839, 35.529946621315524


def _resp(body):
    r = MagicMock()
    r.status_code = 200
    r.json = MagicMock(return_value=body)
    return r


def _client(handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = handler
        yield stub
    return _cm


def _stub(handler):
    """A bare object exposing only .get, for the functions that take an
    already-open client directly (_check_landlocked / _check_cemetery)."""
    stub = MagicMock()
    stub.get = handler
    return stub


def _listing(**kw) -> Listing:
    base = dict(
        source="test", source_url="https://example.test/1",
        listing_type=ListingType.TAX_SALE, property_kind=PropertyKind.LAND,
        state="NC", county="Lincoln",
        latitude=EDGESTONE_LAT, longitude=EDGESTONE_LON,
        parcel_id="4605830808",
    )
    base.update(kw)
    return Listing(**base)


# ===========================================================================
# Pure geometry helpers.
# ===========================================================================

def test_point_seg_dist_zero_on_segment():
    assert M._point_seg_dist_m(5, 0, 0, 0, 10, 0) == pytest.approx(0.0, abs=1e-9)


def test_point_seg_dist_perpendicular():
    assert M._point_seg_dist_m(5, 3, 0, 0, 10, 0) == pytest.approx(3.0)


def test_point_in_ring_xy_square():
    square = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    assert M._point_in_ring_xy(5, 5, square) is True
    assert M._point_in_ring_xy(50, 50, square) is False


def test_edgestone_parcel_to_road_distance_matches_live_measurement():
    """Real parcel ring + real road path (Lincoln Co. parcel 4605830808,
    "7440 Edgestone Ln") -- live-measured min distance was 3.7 m, and this
    parcel genuinely fronts the road (confirmed by street_address matching
    the nearest road name), so the pure math must reproduce that."""
    lon0, lat0 = EDGESTONE_LON, EDGESTONE_LAT
    dist = M._min_ring_to_polylines_m(EDGESTONE_RINGS, EDGESTONE_ROAD_PATHS, lon0, lat0)
    assert dist == pytest.approx(3.7, abs=0.5)
    assert dist < M._FRONTAGE_THRESHOLD_M


def test_point_to_ring_min_dist_detects_inside():
    d, inside = M._point_to_ring_min_dist_m(DALLAS_CENTROID_LAT, DALLAS_CENTROID_LON, DALLAS_CEMETERY_RINGS)
    assert inside is True
    assert d == 0.0


def test_point_to_ring_min_dist_detects_outside():
    # ~1 km east of the real cemetery polygon -- clearly outside.
    d, inside = M._point_to_ring_min_dist_m(DALLAS_CENTROID_LAT, DALLAS_CENTROID_LON + 0.012, DALLAS_CEMETERY_RINGS)
    assert inside is False
    assert d > 500


# ===========================================================================
# _check_landlocked -- mocked ArcGIS responses replaying real captures.
# ===========================================================================

@pytest.mark.asyncio
async def test_check_landlocked_frontage_parcel_is_not_a_candidate():
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        if url == M.NC1MAP_PARCELS_URL:
            return _resp({"features": [{
                "attributes": {"parno": "4605830808", "cntyname": "Lincoln"},
                "geometry": {"rings": EDGESTONE_RINGS},
            }]})
        assert url == M.NC1MAP_ROADS_URL
        return _resp({"features": [{
            "attributes": {"st_name": "EDGESTONE"},
            "geometry": {"paths": EDGESTONE_ROAD_PATHS},
        }]})

    out = await M._check_landlocked(_stub(get), _listing())
    assert out["candidate"] is False
    assert out["min_distance_m"] == pytest.approx(3.7, abs=0.5)
    assert out["nearest_road"] == "EDGESTONE"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_check_landlocked_no_roads_in_envelope_is_a_candidate():
    async def get(url, **kw):
        if url == M.NC1MAP_PARCELS_URL:
            return _resp({"features": [{
                "attributes": {"parno": "4605830808", "cntyname": "Lincoln"},
                "geometry": {"rings": EDGESTONE_RINGS},
            }]})
        return _resp({"features": []})

    out = await M._check_landlocked(_stub(get), _listing())
    assert out["candidate"] is True
    assert out["roads_in_envelope"] == 0


@pytest.mark.asyncio
async def test_check_landlocked_far_road_is_a_candidate():
    """A road real but ~200m away (the whole road shifted well off the parcel)
    must clear the 30 m frontage threshold as a candidate."""
    shifted_road = [[[x + 0.002, y + 0.002] for x, y in EDGESTONE_ROAD_PATHS[0]]]

    async def get(url, **kw):
        if url == M.NC1MAP_PARCELS_URL:
            return _resp({"features": [{
                "attributes": {"parno": "4605830808", "cntyname": "Lincoln"},
                "geometry": {"rings": EDGESTONE_RINGS},
            }]})
        return _resp({"features": [{
            "attributes": {"st_name": "FAR ROAD"},
            "geometry": {"paths": shifted_road},
        }]})

    out = await M._check_landlocked(_stub(get), _listing())
    assert out["candidate"] is True
    assert out["min_distance_m"] > M._FRONTAGE_THRESHOLD_M


@pytest.mark.asyncio
async def test_check_landlocked_ambiguous_envelope_is_skipped():
    """2+ parcels in the tiny envelope -- same guard as
    enrichment_parcel_from_geo._point_query. Must not guess."""
    async def get(url, **kw):
        return _resp({"features": [
            {"attributes": {"parno": "1"}, "geometry": {"rings": EDGESTONE_RINGS}},
            {"attributes": {"parno": "2"}, "geometry": {"rings": EDGESTONE_RINGS}},
        ]})

    assert await M._check_landlocked(_stub(get), _listing()) is None


@pytest.mark.asyncio
async def test_check_landlocked_sc_state_is_skipped_no_network():
    """SC has no confirmed statewide road layer -- see module docstring. Must
    not even attempt a query."""
    async def get(url, **kw):
        raise AssertionError("SC should never reach the network")

    li = _listing(state="SC", county="Pickens")
    assert await M._check_landlocked(_stub(get), li) is None


@pytest.mark.asyncio
async def test_check_landlocked_arcgis_error_does_not_raise():
    async def get(url, **kw):
        return _resp({"error": {"code": 499, "message": "Token Required"}})

    assert await M._check_landlocked(_stub(get), _listing()) is None


# ===========================================================================
# _check_cemetery -- mocked ArcGIS responses replaying real captures.
# ===========================================================================

@pytest.mark.asyncio
async def test_check_cemetery_gaston_point_inside_polygon_hits():
    li = _listing(county="Gaston", latitude=DALLAS_CENTROID_LAT, longitude=DALLAS_CENTROID_LON)

    async def get(url, **kw):
        assert url == M._CEMETERY_LAYER_BY_COUNTY[("NC", "Gaston")].url
        return _resp({"features": [{
            "attributes": {"NAME": "Dallas Presbyterian Church Cemetery"},
            "geometry": {"rings": DALLAS_CEMETERY_RINGS},
        }]})

    out = await M._check_cemetery(_stub(get), li)
    assert out["relation"] == "on_parcel"
    assert out["distance_m"] == 0.0
    assert out["cemetery_name"] == "Dallas Presbyterian Church Cemetery"


@pytest.mark.asyncio
async def test_check_cemetery_buncombe_point_layer_nearby_hits():
    """Real Buncombe schema quirk: this layer is a JOIN, so the attribute key
    ArcGIS returns is the FULLY QUALIFIED field name
    ('Bun.DBO.CemeteryData.Cemetery_Name'), not a bare alias -- confirmed
    live (outFields='Owner' 400s: 'Failed to execute query'). The registry
    entry and this test both use the qualified name."""
    li = _listing(county="Buncombe", latitude=MORGAN_HILL_LAT + 0.0003, longitude=MORGAN_HILL_LON)
    layer = M._CEMETERY_LAYER_BY_COUNTY[("NC", "Buncombe")]
    assert layer.name_field == "Bun.DBO.CemeteryData.Cemetery_Name"

    async def get(url, **kw):
        assert kw["params"]["outFields"] == layer.name_field
        return _resp({"features": [{
            "attributes": {layer.name_field: "New Morgan Hill Baptist Church Cemetery"},
            "geometry": {"x": MORGAN_HILL_LON, "y": MORGAN_HILL_LAT},
        }]})

    out = await M._check_cemetery(_stub(get), li)
    assert out["relation"] == "nearby"
    assert out["cemetery_name"] == "New Morgan Hill Baptist Church Cemetery"
    assert out["distance_m"] < layer.proximity_m


@pytest.mark.asyncio
async def test_check_cemetery_unregistered_county_is_skipped_no_network():
    async def get(url, **kw):
        raise AssertionError("unregistered county should never reach the network")

    li = _listing(county="Rutherford")
    assert await M._check_cemetery(_stub(get), li) is None


@pytest.mark.asyncio
async def test_check_cemetery_far_hit_is_dropped():
    li = _listing(county="Gaston", latitude=DALLAS_CENTROID_LAT, longitude=DALLAS_CENTROID_LON + 0.02)

    async def get(url, **kw):
        return _resp({"features": [{
            "attributes": {"NAME": "Dallas Presbyterian Church Cemetery"},
            "geometry": {"rings": DALLAS_CEMETERY_RINGS},
        }]})

    assert await M._check_cemetery(_stub(get), li) is None


# ===========================================================================
# enrich_land_buildability -- top-level gating + idempotency.
# ===========================================================================

@pytest.mark.asyncio
async def test_enrich_land_buildability_skips_non_land(monkeypatch):
    li = _listing(property_kind=PropertyKind.SINGLE_FAMILY)

    async def get(url, **kw):
        raise AssertionError("non-LAND row should never reach the network")

    monkeypatch.setattr(M, "client", _client(get))
    stats = await M.enrich_land_buildability([li])
    assert stats["targets"] == 0
    assert "_land_buildability_checked" not in li.raw


@pytest.mark.asyncio
async def test_enrich_land_buildability_writes_raw_and_marks_checked(monkeypatch):
    li = _listing(county="Gaston", latitude=DALLAS_CENTROID_LAT, longitude=DALLAS_CENTROID_LON)

    async def get(url, **kw):
        if url == M._CEMETERY_LAYER_BY_COUNTY[("NC", "Gaston")].url:
            return _resp({"features": [{
                "attributes": {"NAME": "Dallas Presbyterian Church Cemetery"},
                "geometry": {"rings": DALLAS_CEMETERY_RINGS},
            }]})
        if url == M.NC1MAP_PARCELS_URL:
            return _resp({"features": []})  # unresolved parcel -- landlocked stays silent
        return _resp({"features": []})

    monkeypatch.setattr(M, "client", _client(get))
    stats = await M.enrich_land_buildability([li])
    assert stats["targets"] == 1
    assert stats["cemetery_hit"] == 1
    assert li.raw["cemetery_proximity"]["cemetery_name"] == "Dallas Presbyterian Church Cemetery"
    assert "landlocked" not in li.raw
    assert li.raw["_land_buildability_checked"] is True


@pytest.mark.asyncio
async def test_enrich_land_buildability_is_idempotent(monkeypatch):
    li = _listing(county="Rutherford")  # no cemetery registry, no network needed once marked
    li.raw["_land_buildability_checked"] = True

    async def get(url, **kw):
        raise AssertionError("an already-checked lead must not be re-queried")

    monkeypatch.setattr(M, "client", _client(get))
    stats = await M.enrich_land_buildability([li])
    assert stats["targets"] == 0
