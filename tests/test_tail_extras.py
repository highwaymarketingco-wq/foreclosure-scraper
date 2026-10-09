"""enrichment_tail_extras: the unwired enrichers wired into the tail (audit 2026-10-09,
unwired_enrichers). Made-up rows; the septic layer is the saved slice tests/test_septic_status.py
uses; no test opens a connection (the network steps get a fake query or a fake card reader)."""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

import foreclosure_scraper.enrichment_tail_extras as TE
from foreclosure_scraper.models import Listing

REPO = pathlib.Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
SEPTIC = json.loads((REPO / "tests" / "fixtures" / "buncombe_septic_cases.json").read_text())["features"]
P_ADVERSE, P_CLEAN = "9676765715", "0628228822"
_spec = importlib.util.spec_from_file_location("reconcile_board", REPO / "scripts" / "reconcile_board.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def _li(state="NC", county="Polk", raw=None, **kw) -> Listing:
    return Listing(source=kw.pop("source", "test"), source_url=kw.pop("url", "https://example.com/x"),
                   state=state, county=county, raw=raw if raw is not None else {}, **kw)


def _tier(t):
    return {"distress_stack": {"tier": t}}


# --------------------------------------------------------------------------- flood_zone mirror
def test_flood_zone_mirrors_raw_flood_and_replaces_a_stored_failure():
    a = _li(raw={"flood": {"zone": "AE", "in_sfha": True, "subtype": "FLOODWAY"},
                 "flood_zone": {"in_sfha": False, "zone": None, "flood_risk": "unknown"}})
    b = _li(raw={"flood": {"zone": "X", "in_sfha": False, "subtype": "0.2 PCT ANNUAL CHANCE FLOOD HAZARD"}})
    c = _li(raw={"flood_zone": {"zone": "X", "flood_risk": "low", "in_sfha": False}})   # no raw['flood']
    s = TE.mirror_flood_zone([a, b, c])
    assert a.raw["flood_zone"]["zone"] == "AE" and a.raw["flood_zone"]["flood_risk"] == "high"
    assert b.raw["flood_zone"]["flood_risk"] == "moderate" and b.raw["flood_zone"]["in_sfha"] is False
    assert c.raw["flood_zone"]["zone"] == "X"                       # an older reading is kept
    assert s == {"mirrored": 2, "changed": 2, "flood_zone_only": 1}
    assert TE.mirror_flood_zone([a, b, c])["changed"] == 0


# --------------------------------------------------------------------------- HUD FMR
TABLE = {"county_rent": {"3714999999": {"efficiency": 700, "1br": 800, "2br": 900, "3br": 1200, "4br": 1400,
                                        "year": "2026", "area_name": "Polk County, NC"}},
         "metro_rent": {"METRO1": {"efficiency": 900, "1br": 1000, "2br": 1100, "3br": 1500, "4br": 1700,
                                   "year": "2026", "area_name": "Asheville, NC HUD Metro FMR Area"}},
         "county_fips": {"NC": {"polk": "3714999999", "buncombe": "METRO1"}}, "cached_at": "2026-10-01"}


def test_hud_fmr_from_the_cached_table_every_covered_row_and_no_census_rent():
    a = _li(county="Polk", bedrooms=2)
    b = _li(county="Buncombe", raw={"census_rent": {"monthly_rent": 1, "source": "acs_2023_5yr"}})
    c = _li(county="Nowhere")
    s = TE.apply_hud_fmr([a, b, c], table=TABLE)
    assert a.raw["hud_fmr"]["fmr_monthly"] == 900 and a.raw["hud_fmr"]["fmr_br_tier"] == "2br"
    assert b.raw["hud_fmr"]["fmr_monthly"] == 1500                  # a census_rent no longer blocks it
    assert b.raw["census_rent"]["source"] == "acs_2023_5yr" and "census_rent" not in a.raw
    assert "hud_fmr" not in c.raw and s["matched"] == 2 and s["no_match"] == 1
    a.bedrooms = 3                                                  # a corrected bedroom count reaches the row
    TE.apply_hud_fmr([a], table=TABLE)
    assert a.raw["hud_fmr"]["fmr_monthly"] == 1200
    assert TE.apply_hud_fmr([a, b, c], table=TABLE)["changed"] == 0


def test_hud_fmr_without_a_table_is_a_noop(tmp_path):
    li = _li()
    assert "skipped" in TE.apply_hud_fmr([li], table={})
    assert TE.load_fmr_table(tmp_path / "none.json") is None and li.raw == {}


# --------------------------------------------------------------------------- septic
def _bun(pid, raw=None):
    return _li(county="Buncombe", parcel_id=pid, raw=raw)


def test_septic_applied_from_the_layer_and_cleared_when_the_parcel_has_no_case():
    adverse = _bun(P_ADVERSE)
    gone = _bun("0000000001", raw={"septic": {"latest_status": "old"}, "land_distress": True})
    other = _li(county="Polk", parcel_id=P_ADVERSE)
    s = TE.apply_septic([adverse, gone, other], SEPTIC, NOW.isoformat(), now=NOW)
    assert adverse.raw["septic"]["septic_adverse"] is True and adverse.raw["land_distress"] is True
    assert adverse.raw["septic"]["checked_at"] == NOW.isoformat()
    assert "septic" not in gone.raw and "land_distress" not in gone.raw
    assert other.raw == {} and s["targets"] == 2 and s["cleared"] == 1
    snap = copy.deepcopy(adverse.raw)
    TE.apply_septic([adverse], SEPTIC, NOW.isoformat(), now=NOW)
    assert adverse.raw == snap


def test_septic_cache_round_trip_and_weekly_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(TE, "SEPTIC_CACHE", tmp_path / "septic.json.gz")
    assert TE.read_septic_cache() == (None, None)
    TE.write_septic_cache(SEPTIC, (NOW - timedelta(days=2)).isoformat())
    feats, at = TE.read_septic_cache()
    assert len(feats) == len(SEPTIC) and at.startswith("2026-10-07")
    out = asyncio.run(TE.refresh_septic_cache(10, now=NOW))      # 2 days old: no fetch
    assert out.get("fresh") is True


# --------------------------------------------------------------------------- BT appraisal cards
def test_bt_targets_unchecked_or_30_days_hot_first():
    fresh = _li(county="McDowell", parcel_id="0668-00-82-0841",
                raw={"bt_appraisal_card": {"status": "no_card", "checked_at": (NOW - timedelta(days=3)).isoformat()}})
    old = _li(county="McDowell", parcel_id="0668-00-82-0842",
              raw={"bt_appraisal_card": {"status": "no_card", "checked_at": (NOW - timedelta(days=40)).isoformat()}})
    cold = _li(county="McDowell", parcel_id="0668-00-82-0843", raw=_tier("COLD"))
    hot = _li(county="McDowell", parcel_id="0668-00-82-0844", raw=_tier("HOT"))
    has_sqft = _li(county="McDowell", parcel_id="0668-00-82-0845", living_sqft=1500)
    other = _li(county="Polk", parcel_id="0668-00-82-0846")
    got = TE.bt_targets([fresh, old, cold, hot, has_sqft, other], NOW)
    assert got[0] is hot and set(map(id, got)) == {id(old), id(cold), id(hot)}


def test_bt_cards_stamp_what_was_read_and_what_had_no_card(monkeypatch):
    import foreclosure_scraper.enrichment_bt_appraisal_card as BT

    async def fake(rows):
        rows = list(rows)
        rows[0].raw["bt_appraisal_card"] = {"heated_sqft": 1800, "card_url": "https://example.com/c"}
        rows[0].living_sqft = 1800
        rows[1].raw["bt_appraisal_card"] = {"status": "no_card"}
        return {"fetched": 2}                                       # rows[2]: a fetch error, no block
    monkeypatch.setattr(BT, "enrich_bt_appraisal_card", fake)
    rows = [_li(county="McDowell", parcel_id=f"0668-00-82-08{i}0") for i in range(3)]
    s = asyncio.run(TE.run_bt_cards(rows, 5, now=NOW))
    assert s["selected"] == 3
    assert rows[0].raw["bt_appraisal_card"]["checked_at"] == NOW.isoformat()
    assert rows[1].raw["bt_appraisal_card"] == {"status": "no_card", "checked_at": NOW.isoformat()}
    assert "bt_appraisal_card" not in rows[2].raw                  # retried next run
    assert [li for li in TE.bt_targets(rows, NOW + timedelta(days=1))] == [rows[2]]


# --------------------------------------------------------------------------- wetlands
def test_wetlands_targets_and_shape_and_a_shared_point(monkeypatch):
    calls = []

    async def fake(c, lat, lon, radius_m):
        calls.append((lat, lon))
        return [{"type": "Freshwater Forested/Shrub Wetland", "code": "PFO1C", "acres": 90.37}] if lat > 34 else []
    land = _li(latitude=35.1, longitude=-82.1, property_kind="land")
    twin = _li(latitude=35.10001, longitude=-82.10001, raw=_tier("WARM"))
    dry = _li(latitude=33.1, longitude=-81.1, raw=_tier("HOT"))
    cold_house = _li(latitude=35.2, longitude=-82.2, raw=_tier("COLD"))
    done = _li(latitude=35.3, longitude=-82.3, property_kind="land",
               raw={"wetlands": {"has_wetlands": False, "checked_at": (NOW - timedelta(days=10)).isoformat()}})
    s = asyncio.run(TE.run_wetlands([land, twin, dry, cold_house, done], 30, now=NOW, query=fake))
    assert len(calls) == 2 and s["rows_set"] == 3                   # one query for the shared point
    assert land.raw["wetlands"]["has_wetlands"] is True and land.raw["wetlands"]["features"][0]["code"] == "PFO1C"
    assert dry.raw["wetlands"] == {"has_wetlands": False, "features": [], "within_m": TE.WETLANDS_RADIUS_M,
                                   "source": "usfws_nwi", "checked_at": NOW.isoformat()}
    assert "wetlands" not in cold_house.raw and done.raw["wetlands"]["has_wetlands"] is False


def test_wetlands_stops_on_a_wall_and_stamps_nothing_unanswered():
    async def walled(c, lat, lon, radius_m):
        raise PermissionError("wetlands service answered 403")
    rows = [_li(latitude=35 + i / 10, longitude=-82.0, property_kind="land") for i in range(3)]
    s = asyncio.run(TE.run_wetlands(rows, 30, now=NOW, query=walled))
    assert s["stopped"].endswith("403") and all("wetlands" not in li.raw for li in rows)


# --------------------------------------------------------------------------- the local steps
def test_local_steps_are_offline_idempotent_and_budget_free(tmp_path, monkeypatch):
    monkeypatch.setattr(TE, "SEPTIC_CACHE", tmp_path / "septic.json.gz")
    TE.write_septic_cache(SEPTIC, NOW.isoformat())
    monkeypatch.setattr(TE, "load_fmr_table", lambda path=None: TABLE)
    rows = [
        _bun(P_ADVERSE, raw={"flood": {"zone": "X", "in_sfha": False}}),
        _li(county="Polk", bedrooms=3, listing_type="tax_lien",
            url="https://example.com/100-test-st-shelby-nc-1000001", city="Cleveland", street_address="100 Test St"),
        _li(county="Polk", raw={"qa_flags": ["arv_below_asis"]}),
    ]
    with R.network_blocked():
        a = TE.enrich_local_pre_gate(rows, now=NOW)
        b = TE.enrich_local_after_qa(rows)
        snap = [copy.deepcopy(li.raw) for li in rows]
        TE.enrich_local_pre_gate(rows, now=NOW)
        TE.enrich_local_after_qa(rows)
    assert [li.raw for li in rows] == snap
    assert not any("failed" in v for v in {**a, **b}.values() if isinstance(v, dict))
    assert rows[0].raw["flood_zone"]["zone"] == "X" and rows[0].raw["septic"]["septic_adverse"] is True
    assert rows[1].raw["hud_fmr"]["fmr_monthly"] == 1200
    assert all("property_category" in li.raw for li in rows)
    assert "arv_below_asis" in rows[2].raw["qa_flags"]             # board_qa's flags are kept


def test_a_step_failure_is_contained(monkeypatch):
    def boom(rows):
        raise RuntimeError("x")
    monkeypatch.setattr(TE, "mirror_flood_zone", boom)
    monkeypatch.setattr(TE, "load_fmr_table", lambda path=None: TABLE)
    li = _li(county="Polk")
    out = TE.enrich_local_pre_gate([li], now=NOW)
    assert "failed" in out["flood_zone"] and li.raw["hud_fmr"]["fmr_monthly"] == 1200


def test_network_steps_never_raise(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(TE, "run_bt_cards", boom)
    monkeypatch.setattr(TE, "refresh_septic_cache", boom)
    monkeypatch.setattr(TE, "run_wetlands", boom)
    assert "failed" in asyncio.run(TE.enrich_network_pre_value([_li()], budget_s=1))["bt_appraisal_card"]
    g = asyncio.run(TE.enrich_network_geo([_li()], budget_s=1))
    assert "failed" in g["septic_refresh"] and "failed" in g["wetlands"]


def test_wetlands_query_point_reads_the_service_answer():
    from foreclosure_scraper import enrichment_usfws_wetlands as W

    class Resp:
        def __init__(self, code, data):
            self.status_code, self._d = code, data

        def json(self):
            return self._d

    class C:
        def __init__(self, resp):
            self.resp, self.params = resp, None

        async def get(self, url, params=None):
            assert url == W.WETLANDS_URL and "fwspublicservices" in url
            self.params = params
            return self.resp
    c = C(Resp(200, {"features": [{"attributes": {"WETLAND_TYPE": "Riverine", "ATTRIBUTE": "R5UBH",
                                                  "ACRES": 1.234}}]}))
    assert asyncio.run(W.query_point(c, 35.0, -82.0, 60)) == [{"type": "Riverine", "code": "R5UBH", "acres": 1.23}]
    assert c.params["distance"] == "60" and c.params["units"] == "esriSRUnit_Meter"
    assert asyncio.run(W.query_point(C(Resp(500, {})), 35.0, -82.0)) is None
    assert asyncio.run(W.query_point(C(Resp(200, {"error": {"code": 400}})), 35.0, -82.0)) is None
    with pytest.raises(PermissionError):
        asyncio.run(W.query_point(C(Resp(403, {})), 35.0, -82.0))


def test_refdata_check_reads_the_fmr_table(tmp_path):
    spec = importlib.util.spec_from_file_location("refdata_check", REPO / "deploy" / "oracle" / "refdata_check.py")
    RC = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(RC)
    rel = "data/fmr_cache/fmr_by_county.json"
    assert RC.RECOMMENDED[rel] == ("json", "county_rent")
    f = tmp_path / rel
    assert RC._check(tmp_path, rel, "json", "county_rent") == "missing"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"county_rent": {}}))
    assert "county_rent" in RC._check(tmp_path, rel, "json", "county_rent")
    f.write_text(json.dumps(TABLE))
    assert RC._check(tmp_path, rel, "json", "county_rent") is None
    f.write_text("{not json")
    assert "unreadable" in RC._check(tmp_path, rel, "json", "county_rent")
