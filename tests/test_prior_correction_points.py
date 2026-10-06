"""enrichment_prior_correction, the map pin of a row whose owner-mailing street is corrected
(docs/HANDOFF.md item 71, pins), and the geocoder's handling of the rows it leaves without one.

Row shapes are real board rows of 2026-10-06 (sources, raw tags, provenance stamps, which fields
are set), pseudonymized: owners, streets, parcel ids and coordinates are replaced. The measured
provenance behind each case is in the item: 'census_geocode' points sat on the mailing's own
geocode, 'parcel_polygon_centroid' points inside the row's parcel, untagged ones either way.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from foreclosure_scraper import enrichment_geocode as geo
from foreclosure_scraper import enrichment_parcel_from_geo as pfg
from foreclosure_scraper import enrichment_prior_correction as pc
from foreclosure_scraper.enrichment_geocode import COUNTY_SEAT_CENTROIDS
from foreclosure_scraper.models import Listing

MAILING_PT = (35.61234, -82.47321)      # where the owner's mailing street geocodes
PARCEL_PT = (35.55871, -82.61942)       # inside the parcel (its polygon centroid)
BUNCOMBE_SEAT = COUNTY_SEAT_CENTROIDS[("NC", "Buncombe")]


def _li(**kw) -> Listing:
    base = {"source": "counties_generic.arcgis_distress.buncombe_unpaid_bills",
            "source_url": "https://example.test/x", "state": "NC", "county": "Buncombe"}
    base.update(kw)
    return Listing(**base)


class FakeCache(pc.CacheReader):
    def __init__(self, rows: dict, have=("Buncombe", "Transylvania", "Spartanburg")):
        self.rows = rows
        super().__init__(lookup=self._fake_lookup, available=lambda c, s: c in have)

    def _fake_lookup(self, county, pid, state):
        hit = self.rows.get((county, str(pid)))
        return (dict(hit), "exact") if hit else (None, None)


CACHE = {("Buncombe", "9686540826"): {"owner": "DOE JOHN", "address": "40 SAMPLE RIDGE RD",
                                      "owner_mailing": "18 SAMPLE RIDGE RD FAIRVIEW NC 28730"},
         ("Buncombe", "9634700001"): {"owner": "ROE MARY", "address": "7 EXAMPLE CV",
                                      "owner_mailing": "1200 OTHER PL APT 4 SAMPLE BEACH FL 33000"},
         ("Transylvania", "8597705450"): {"owner": "ROE RICHARD", "address": "U32 L053 SAMPLE CT",
                                          "owner_mailing": "17 Example Ct Sampleton NV 89000"},
         ("Spartanburg", "612000010001"): {"owner": "DOE JANE", "address": "12 SAMPLE ST",
                                           "owner_mailing": "77 HARBOR VIEW CT MOORE SC 29369"}}


def _unpaid(**kw) -> Listing:
    """buncombe_unpaid_bills, the shape item 69 found: the mailing street on the same road as the
    situs, the mailing's city/ZIP, and the point resolver_backfill_geocode put on that street."""
    base = dict(parcel_id="9686540826", street_address="18 SAMPLE RIDGE RD", city="FAIRVIEW", zip_code="28730",
                latitude=MAILING_PT[0], longitude=MAILING_PT[1],
                raw={"geo_imprecise": "census_geocode",
                     "comps_geo_warning": "comps are county-wide (no same-zip/city/nearby match)"})
    base.update(kw)
    return _li(**base)


# --------------------------------------------------------------------------- the plan
def test_point_geocoded_from_the_mailing_street_is_cleared_with_its_tag():
    li = _unpaid()
    a = pc.restore_situs(li, FakeCache(CACHE))
    assert li.street_address == "40 SAMPLE RIDGE RD"
    assert (li.latitude, li.longitude) == (None, None)
    assert "geo_imprecise" not in li.raw                       # it described the old point
    assert li.raw["comps_geo_warning"]                         # not a point tag: left
    assert a["point"] == {"action": "cleared", "old": list(MAILING_PT), "tags": {"geo_imprecise": "census_geocode"}}
    assert li.raw[pc.MAILING_KEY]["point"]["old"] == list(MAILING_PT)
    assert pc.awaiting_parcel_point(li.raw)


def test_untagged_point_of_the_run_geocoder_is_cleared_too():
    # buncombe_elderly: enrichment_geocode tags nothing; measured, half such points sat on the
    # mailing's geocode, so an untagged point on a corrected row is not trusted
    li = _unpaid(source="counties_nc.buncombe_elderly", raw={})
    a = pc.restore_situs(li, FakeCache(CACHE))
    assert a["point"]["action"] == "cleared" and "tags" not in a["point"]
    assert li.latitude is None and pc.awaiting_parcel_point(li.raw)


def test_parcel_polygon_centroid_of_the_scraper_is_kept():
    # spartanburg_vacant: the scraper's own parcel centroid (and board_quality's centroid_snap,
    # several rows of one parcel stand on it); the street was the mailing, the point never was
    li = _li(source="counties_sc.spartanburg_vacant", state="SC", county="Spartanburg", parcel_id="612000010001",
             street_address="77 HARBOR VIEW CT", city="Spartanburg", zip_code="29306",
             latitude=34.95102, longitude=-81.93377,
             raw={"geo_source": "parcel_polygon_centroid", "geo_imprecise": "centroid_snap",
                  "situs_address_source": "gis_parcel_situs"})
    a = pc.restore_situs(li, FakeCache(CACHE))
    assert a["class"] == "definite" and li.street_address == "12 SAMPLE ST"
    assert a["point"] == {"action": "kept", "old": [34.95102, -81.93377], "why": "parcel_polygon_centroid"}
    assert (li.latitude, li.longitude) == (34.95102, -81.93377)
    assert li.raw["geo_source"] == "parcel_polygon_centroid" and li.raw["geo_imprecise"] == "centroid_snap"
    assert not pc.awaiting_parcel_point(li.raw)


def test_no_point_and_a_stale_out_of_bbox_tag():
    # transylvania_delinquent_tax, out-of-state mailing: board_quality had nulled the point it
    # geocoded in Nevada; the street is nulled (the situs has no house number)
    li = _li(source="counties_nc.transylvania_delinquent_tax", county="Transylvania", parcel_id="8597705450",
             street_address="17 Example Ct", city="Sampleton", zip_code="89000", raw={"geo_imprecise": "out_of_bbox"})
    a = pc.restore_situs(li, FakeCache(CACHE))
    assert a["nulled"] == "situs_without_house_number"
    assert a["point"] == {"action": "absent", "old": None, "tags": {"geo_imprecise": "out_of_bbox"}}
    assert "geo_imprecise" not in li.raw and pc.awaiting_parcel_point(li.raw)


def test_replaced_by_the_parcel_centroid_another_row_of_the_parcel_holds():
    sibling = _li(source="counties_sc.spartanburg_vacant", parcel_id="9686540826", street_address="40 SAMPLE RIDGE RD",
                  latitude=PARCEL_PT[0], longitude=PARCEL_PT[1], raw={"geo_source": "parcel_polygon_centroid"})
    li = _unpaid()
    stats = pc.correct_prior_rows([li, sibling], cache=FakeCache(CACHE))
    p = li.raw[pc.MAILING_KEY]["point"]
    assert p["action"] == "replaced" and p["from"] == "sibling_parcel_centroid" and p["old"] == list(MAILING_PT)
    assert (li.latitude, li.longitude) == PARCEL_PT
    assert li.raw["geo_source"] == "parcel_polygon_centroid" and "geo_imprecise" not in li.raw
    assert not pc.awaiting_parcel_point(li.raw)
    assert stats["mailing_point"] == {"replaced": 1, "from_sibling_parcel_centroid": 1}
    assert (sibling.latitude, sibling.longitude) == PARCEL_PT                  # the sibling is untouched


def test_precise_resolver_point_of_the_parcel_is_used_a_fallback_one_is_not():
    precise = _li(source="counties_nc.nc_ust_incidents", parcel_id="9686540826", street_address="40 SAMPLE RIDGE RD",
                  latitude=35.55902, longitude=-82.61988,
                  raw={"parcel_from_geo": {"source": "nc_onemap_point", "lat": 35.55902, "lng": -82.61988}})
    li = _unpaid()
    pc.correct_prior_rows([li, precise], cache=FakeCache(CACHE))
    assert li.raw[pc.MAILING_KEY]["point"]["from"] == "sibling_resolver_point"
    assert (li.latitude, li.longitude) == (35.55902, -82.61988)
    assert li.raw["geo_source"] == "parcel_resolver_point"
    # the same parcel resolved at the county seat (item 70) says nothing about where it is
    seat = _li(source="counties_nc.nc_ptscloud_delinquent_tax", parcel_id="9686540826",
               latitude=BUNCOMBE_SEAT[0], longitude=BUNCOMBE_SEAT[1],
               raw={"parcel_from_geo": {"source": "nc_onemap_point", "lat": BUNCOMBE_SEAT[0], "lng": BUNCOMBE_SEAT[1]}})
    li2 = _unpaid()
    assert pc.parcel_points([li2, seat], pc.Counter(), 8) == {}


def test_disagreeing_parcel_points_are_not_used():
    a = _li(parcel_id="9686540826", latitude=PARCEL_PT[0], longitude=PARCEL_PT[1],
            raw={"geo_source": "parcel_polygon_centroid"})
    b = _li(parcel_id="9686540826", latitude=PARCEL_PT[0] + 0.01, longitude=PARCEL_PT[1],
            raw={"geo_source": "parcel_polygon_centroid"})
    assert pc.parcel_points([a, b], pc.Counter(), 8) == {}


def test_the_rows_own_bag_centroid_of_the_parcel():
    li = _unpaid(raw={"gis_attrs_full": {"PIN": "9686540826", "_centroid": list(PARCEL_PT)}})
    a = pc.restore_situs(li, FakeCache(CACHE))
    assert a["point"]["from"] == "row_parcel_bag" and (li.latitude, li.longitude) == PARCEL_PT


def test_rows_not_corrected_keep_their_point():
    occupied = _li(source="counties_nc.buncombe_elderly", parcel_id="9686540826", street_address="40 SAMPLE RIDGE RD",
                   latitude=MAILING_PT[0], longitude=MAILING_PT[1], raw={"geo_imprecise": "census_geocode"})
    before = occupied.model_dump()
    stats = pc.correct_prior_rows([occupied], cache=FakeCache(CACHE))
    assert occupied.model_dump() == before and stats["mailing_point"] == {}


def test_aged_copy_dropped_beside_its_live_row_whatever_its_point():
    prior = _unpaid(first_seen=datetime(2026, 8, 2), raw={"pulled_sale": {"consecutive_misses": 1},
                                                          "geo_imprecise": "census_geocode"})
    fresh = _li(parcel_id="9686540826", street_address="40 SAMPLE RIDGE RD", first_seen=datetime(2026, 10, 6))
    rows = [prior, fresh]
    stats = pc.correct_prior_rows(rows, cache=FakeCache(CACHE))
    assert rows == [fresh] and stats["superseded_dropped"] == 1 and stats["mailing_point"] == {"cleared": 1}


# ------------------------------------------------------------ the parcel layer (run time)
def test_layer_id_forms():
    assert pc.layer_id_forms("711285545746", "Spartanburg", "SC")[-1] == "7112-85-5457.46"
    forms = pc.layer_id_forms("9686-54-0826-00000", "Buncombe", "NC")
    assert forms[0] == "9686-54-0826-00000" and "9686540826" in forms
    assert all(len(f) <= 18 for f in forms) and len(forms) <= 4      # no zero-padded guesses


def test_concave_lot_pin_stays_inside_it():
    # a U-shaped lot: its area centroid falls in the open middle, outside the lot
    ring = [[-82.6200, 35.5580], [-82.6170, 35.5580], [-82.6170, 35.5600], [-82.6176, 35.5600],
            [-82.6176, 35.5586], [-82.6194, 35.5586], [-82.6194, 35.5600], [-82.6200, 35.5600]]
    lat, lng = pc.polygon_centroid({"rings": [ring]})
    assert pc._inside(lng, lat, [tuple(p) for p in ring])


def test_largest_ring_is_chosen_by_area_not_by_vertex_count():
    big = [[-82.6200, 35.5580], [-82.6100, 35.5580], [-82.6100, 35.5680], [-82.6200, 35.5680]]
    small_detailed = [[-82.5000 + 0.00001 * i, 35.5000 + (0.00002 if i % 2 else 0)] for i in range(40)]
    lat, lng = pc.polygon_centroid({"rings": [small_detailed + [[-82.5, 35.5]], big]})
    assert abs(lat - 35.5630) < 1e-4 and abs(lng - -82.6150) < 1e-4


def test_polygon_centroid():
    # an L-shaped lot: its area centroid (35.55851, -82.61930) is in the notch, so the pin moves
    # along that latitude to the middle of the lot's own stretch there (the L's upright)
    ring = [[-82.6200, 35.5580], [-82.6180, 35.5580], [-82.6180, 35.5584], [-82.6196, 35.5584],
            [-82.6196, 35.5596], [-82.6200, 35.5596], [-82.6200, 35.5580]]
    lat, lng = pc.polygon_centroid({"rings": [ring]})
    assert abs(lat - 35.55851) < 1e-5 and abs(lng - -82.6198) < 1e-6
    # a plain rectangle: its centre
    assert pc.polygon_centroid(_square(35.5, -82.6)) == (35.5, -82.6)
    assert pc.polygon_centroid({"x": -82.6, "y": 35.5}) == (35.5, -82.6)
    assert pc.polygon_centroid({"rings": [[[-112.0, 40.0], [-111.0, 40.0], [-111.0, 41.0]]]}) is None


def _square(lat, lng, d=0.0002):
    return {"rings": [[[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d], [lng - d, lat - d]]]}


def _fake_layer(monkeypatch, features_by_id):
    """_arc_query stand-in: answers `<field> IN ('a','b',...)` with the features of the ids it
    lists, each carrying that id under the queried field, as an ArcGIS layer does."""
    import re
    calls = []

    async def fake(c, url, params, **kw):
        calls.append(params["where"])
        m = re.search(r"(\w+) IN \((.*)\)$", params["where"])
        field, ids = m.group(1), re.findall(r"'([^']*)'", m.group(2))
        return [dict(f, attributes={field: i}) for i in ids for f in features_by_id.get(i, [])]
    monkeypatch.setattr(pfg, "_arc_query", fake)
    return calls


def test_parcel_layer_point_onemap_is_restricted_to_the_county(monkeypatch):
    calls = _fake_layer(monkeypatch, {"9686540826": [{"geometry": _square(*PARCEL_PT)}]})
    p, outcome = asyncio.run(pc.parcel_layer_point(None, "Buncombe", "NC", "9686-54-0826-00000"))
    assert outcome == "placed" and abs(p[0] - PARCEL_PT[0]) < 1e-6 and abs(p[1] - PARCEL_PT[1]) < 1e-6
    assert calls == ["(cntyname='Buncombe') AND parno IN ('9686-54-0826-00000','968654082600000','9686540826')"]


def test_one_query_per_county_batch_and_the_dashed_transylvania_pin(monkeypatch):
    calls = _fake_layer(monkeypatch, {"8597-70-5450-000": [{"geometry": _square(35.2, -82.7)}],
                                      "8597-70-0001-000": [{"geometry": _square(35.21, -82.71)}]})
    res = asyncio.run(pc.parcel_layer_points(None, "Transylvania", "NC",
                                             ["8597705450000", "8597700001000", "8597700002000"]))
    assert res["8597705450000"][1] == res["8597700001000"][1] == "placed"
    assert res["8597700002000"] == (None, "not_found")
    assert len(calls) == 2                                   # one IN query per id field, not per row


def test_budget_spent_leaves_rows_for_the_next_run(monkeypatch):
    calls = _fake_layer(monkeypatch, {"9686540826": [{"geometry": _square(*PARCEL_PT)}]})
    res = asyncio.run(pc.parcel_layer_points(None, "Buncombe", "NC", ["9686540826"], deadline=0.0))
    assert res == {"9686540826": (None, "budget_skip")} and calls == []


def test_parcel_layer_point_outcomes(monkeypatch):
    _fake_layer(monkeypatch, {"1": [{"attributes": {}}],                                    # a table: no geometry
                              "2": [{"geometry": _square(*PARCEL_PT)}, {"geometry": _square(35.7, -82.4)}]})
    assert asyncio.run(pc.parcel_layer_point(None, "Buncombe", "NC", "1")) == (None, "no_geometry")
    assert asyncio.run(pc.parcel_layer_point(None, "Buncombe", "NC", "2")) == (None, "ambiguous")
    assert asyncio.run(pc.parcel_layer_point(None, "Buncombe", "NC", "3")) == (None, "not_found")
    assert asyncio.run(pc.parcel_layer_point(None, "Union", "SC", "3"))[1] == "no_layer"   # dual-state, no state tag


# ------------------------------------------------------------------- the geocode phase
@asynccontextmanager
async def _no_network(**kw):
    class C:
        async def get(self, *a, **k):
            raise AssertionError("no network expected")

        async def post(self, *a, **k):
            raise AssertionError("no network expected")
    yield C()


def test_geocode_phase_places_awaiting_rows_on_their_parcel_and_never_on_the_county_seat(monkeypatch):
    _fake_layer(monkeypatch, {"9686540826": [{"geometry": _square(*PARCEL_PT)}]})
    monkeypatch.setattr(geo, "client", _no_network)
    placed, missing = _unpaid(), _unpaid(parcel_id="9634700001", street_address="1200 OTHER PL APT 4",
                                         city="SAMPLE BEACH", zip_code="33000")
    cache = FakeCache(CACHE)
    pc.restore_situs(placed, cache)
    pc.restore_situs(missing, cache)              # the cache situs '7 EXAMPLE CV' has no city/ZIP
    assert placed.latitude is None and missing.latitude is None and missing.street_address == "7 EXAMPLE CV"
    # an address-less row nobody corrected: still the county seat, as before
    plain = _li(source="counties_nc.nc_notices_counties", parcel_id=None, street_address=None, raw={})
    asyncio.run(geo.enrich([placed, missing, plain]))
    assert abs(placed.latitude - PARCEL_PT[0]) < 1e-5 and placed.raw["geo_source"] == "parcel_polygon_centroid"
    assert placed.raw[pc.MAILING_KEY]["point"]["placed"]["by"] == "parcel_layer"
    assert not pc.awaiting_parcel_point(placed.raw)
    assert (missing.latitude, missing.longitude) == (None, None)             # not the county seat
    assert pc.awaiting_parcel_point(missing.raw)                             # retried next run
    assert (plain.latitude, plain.longitude) == BUNCOMBE_SEAT


def test_awaiting_row_with_a_city_is_geocoded_from_its_corrected_street_only(monkeypatch):
    li = _unpaid()
    pc.restore_situs(li, FakeCache(CACHE))
    li.city = "Fairview"                         # e.g. a later enricher filled the situs city
    asked = []

    async def census(c, q):
        asked.append(q)
        return (35.5588, -82.6195) if q.startswith("40 SAMPLE RIDGE RD") else None

    async def nominatim(c, q):
        asked.append("nominatim:" + q)
        return None
    monkeypatch.setattr(geo, "_census_geocode", census)
    monkeypatch.setattr(geo, "_nominatim_geocode", nominatim)
    geo._CACHE.clear()
    assert asyncio.run(geo._resolve(None, li, 0.0)) == (35.5588, -82.6195)
    assert asked == ["40 SAMPLE RIDGE RD, Fairview, NC"]          # no city-centroid candidate
    li.street_address = "41 SAMPLE RIDGE RD"                       # nothing matches now
    asked.clear()
    geo._CACHE.clear()
    assert asyncio.run(geo._resolve(None, li, 0.0)) is None        # no Tier 3 / Tier 4
    assert asked == ["41 SAMPLE RIDGE RD, Fairview, NC", "nominatim:41 SAMPLE RIDGE RD, Fairview, NC"]


def test_resolver_guard_still_covers_a_withdrawn_parcel_back_on_the_county_seat():
    """Correction 1's rows: the fallback parcel is withdrawn and the row keeps its point. Should
    something clear that point, the geocoder puts an address-less row back on the county seat,
    the point recorded in the audit, and enrichment_parcel_from_geo refuses it again."""
    seat = COUNTY_SEAT_CENTROIDS[("NC", "Rutherford")]
    li = Listing(source="counties_nc.rutherford_tax", source_url="https://example.test/x", state="NC",
                 county="Rutherford", parcel_id="5550001111", latitude=seat[0], longitude=seat[1],
                 raw={"parcel_from_geo": {"source": "nc_onemap_point", "lat": seat[0], "lng": seat[1]},
                      "rutherford_tax": {"parcel": "400001"}})
    pc.withdraw_fallback_parcel(li, pc.Counter(), 8, FakeCache({}))
    li.latitude = li.longitude = None
    assert not pc.awaiting_parcel_point(li.raw)                     # not a mailing row: Tier 4 applies
    assert asyncio.run(geo._resolve(None, li, 0.0, fast_only=True)) == seat
    li.latitude, li.longitude = seat
    assert pfg._withdrawn(li)


def test_a_row_an_earlier_phase_placed_is_recorded_and_not_queried(monkeypatch):
    calls = _fake_layer(monkeypatch, {})
    monkeypatch.setattr(geo, "client", _no_network)
    li = _unpaid()
    pc.restore_situs(li, FakeCache(CACHE))
    li.latitude, li.longitude = PARCEL_PT          # e.g. the GIS phase's parcel centroid by situs
    asyncio.run(geo.enrich([li]))
    assert li.raw[pc.MAILING_KEY]["point"]["placed"] == {"by": "before_geocode", "at": list(PARCEL_PT)}
    assert calls == [] and not pc.awaiting_parcel_point(li.raw)
