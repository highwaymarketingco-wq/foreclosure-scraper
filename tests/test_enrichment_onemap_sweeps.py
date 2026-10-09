"""NC OneMap statewide sweeps (heir_estate, rollback_exposure; top-80 2026-10-09).

All fixtures are made up: parcel ids, owner names and counts are invented; the ArcGIS answers are
hand-built in the shape the layer returns.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest

import foreclosure_scraper.enrichment_onemap_sweeps as M
from foreclosure_scraper import screen_ledger as SL


def li(county="Alamance", parcel="1234-56-7890", state="NC", raw=None):
    return SimpleNamespace(county=county, parcel_id=parcel, state=state, raw=raw)


# --------------------------------------------------------------------------- the flag is trusted only where it is a flag

def test_reliable_flag_counties_drops_flag_on_everything_and_counties_without_a_flag():
    flagged = {"Alamance": 2341, "Johnston": 124034, "Rowan": 82366, "Dare": 3, "Nowhere": 0}
    totals = {"Alamance": 79495, "Johnston": 125000, "Rowan": 83000, "Dare": 40000, "Nowhere": 9}
    assert M.reliable_flag_counties(flagged, totals) == ["Alamance", "Dare"]
    assert M.reliable_flag_counties({"X": 26}, {"X": 100}) == []          # 26% is over the line
    assert M.reliable_flag_counties({"X": 25}, {"X": 100}) == ["X"]
    assert M.reliable_flag_counties({"X": 5}, {}) == []                    # no total, no trust


# --------------------------------------------------------------------------- classification of the owner of record

@pytest.mark.parametrize("attrs,match", [
    ({"ownname": "DOE JANE HEIRS"}, "heirs"),
    ({"ownname": "ROE JOHN ESTATE"}, "estate"),
    ({"ownname": "ESTATE OF ROE MARY"}, "estate"),
    ({"ownname": "DOE SAM", "ownname2": "ROE ANN ESTATE"}, "estate"),
])
def test_decedent_titled_parcels_are_matched(attrs, match):
    hit = M.classify_heir_row(attrs)
    assert hit and hit["match"] == match and hit["owner"]


@pytest.mark.parametrize("name", ["EXAMPLE REAL ESTATE LLC", "ROE FARM ESTATES LLC", "DOE JANE LIFE ESTATE",
                                  "DOE JANE", "", None])
def test_other_owners_are_not_matched(name):
    assert M.classify_heir_row({"ownname": name}) is None


def test_the_index_is_keyed_by_county_and_normalized_parcel_and_altparcel():
    rows = [{"cntyname": "Alamance", "parno": "1234-56-7890", "altparno": "ALT 9", "ownname": "DOE JANE HEIRS"},
            {"cntyname": "Wake", "parno": "55", "altparno": "", "ownname": "DOE JANE"}]
    idx = M.build_heir_index(rows)
    assert set(idx) == {"Alamance"}
    assert set(idx["Alamance"]) == {"1234567890", "alt9"}
    assert idx["Alamance"]["1234567890"]["m"] == "heirs"


# --------------------------------------------------------------------------- stamping never overwrites a richer stamp

def test_apply_indexes_flags_nc_rows_and_keeps_existing_stamps():
    heir = {"swept_on": "2026-10-09", "index": {"Alamance": {"1234567890": {"o": "DOE JANE HEIRS", "m": "heirs", "h": []}}}}
    puv = {"swept_on": "2026-10-09", "counties_swept": ["Alamance"],
           "index": {"Alamance": {"1234567890": 1, "1111111111": 1}}}
    a = li(parcel="1234-56-7890")
    b = li(parcel="1111-11-1111")
    rich = {"rollback_exposure": {"deferred_value": 285500.0, "source": "county layer"}}
    c = li(parcel="1111-11-1111", raw=json.loads(json.dumps(rich)))
    d = li(county="Wake", parcel="1234-56-7890")             # a county that was not swept
    e = li(state="SC", parcel="1234-56-7890")                # not NC at all
    f = li(parcel=None)
    st = M.apply_indexes([a, b, c, d, e, f], heir, puv)
    assert a.raw["heir_estate"]["owner_of_record"] == "DOE JANE HEIRS" and a.raw["heir_estate"]["source"] == M.SOURCE_HEIR
    assert a.raw["rollback_exposure"]["basis"] == "present_use_flag"
    assert a.raw["rollback_exposure"]["deferred_value"] is None          # a flag, not a dollar figure
    assert a.raw["rollback_exposure"]["rollback_years"] == 4
    assert b.raw["rollback_exposure"]["source_key"] == M.SOURCE_PUV and "heir_estate" not in b.raw
    assert c.raw["rollback_exposure"] == rich["rollback_exposure"]       # never overwritten
    assert d.raw is None and e.raw is None and f.raw is None
    assert st["nc_rows_with_parcel"] == 4
    assert (st["rollback_stamped"], st["rollback_already"], st["heir_estate_stamped"]) == (2, 1, 1)


def test_a_county_not_in_the_swept_set_gets_no_rollback_flag():
    puv = {"swept_on": "x", "counties_swept": ["Alamance"], "index": {"Surry": {"1": 1}}}
    row = li(county="Surry", parcel="1")
    M.apply_indexes([row], None, puv)
    assert row.raw is None


def test_mcdowell_style_county_names_resolve_to_the_layer_spelling():
    puv = {"swept_on": "x", "counties_swept": ["McDowell"], "index": {"McDowell": {"7777": 1}}}
    row = li(county="Mcdowell County", parcel="7777")
    M.apply_indexes([row], None, puv)
    assert row.raw["rollback_exposure"]["county"] == "McDowell"


# --------------------------------------------------------------------------- screens

def test_screened_counties_only_for_complete_sweeps():
    heir = {"complete": True, "counties_swept": ["Alamance", "Wake"]}
    puv = {"complete": False, "counties_swept": ["Alamance"]}
    got = M.screened_counties(heir, puv)
    assert got == {"heir_estate": ["NC|Alamance", "NC|Wake"]}
    assert M.screened_counties(None, None) == {}


def test_the_screen_ledger_turns_the_stats_into_cube_screens():
    health = {"generated_at": "2026-10-09T00:00:00Z", "sources": [], "enrichments": {
        "onemap_sweeps": {"screened": {"heir_estate": ["NC|Alamance", "NC|Nowhere"],
                                       "rollback_exposure": ["NC|Alamance"]}}}}
    led = SL.build(health)
    assert SL.screened(led, "heir_estate", "NC", "Alamance") and SL.screened(led, "rollback_exposure", "NC", "Alamance")
    assert not SL.screened(led, "heir_estate", "NC", "Wake")
    assert "NC|Nowhere" not in led["screens"]["heir_estate"]          # not a county of the state


def test_the_its_portals_screen_the_tax_columns_only_when_the_run_is_ok():
    ok = SL.build({"sources": [{"source": "counties_nc.nc_its_public_tax", "status": "OK (1200)"}]})
    for county in ("Onslow", "Graham", "Anson", "Yadkin", "Scotland"):
        for col in SL.TAX_COLUMNS:
            assert SL.screened(ok, col, "NC", county), (county, col)
    partial = SL.build({"sources": [{"source": "counties_nc.nc_its_public_tax", "status": "PARTIAL: counties not read in full: Anson"}]})
    assert not SL.screened(partial, "two_year_delinquent", "NC", "Anson")


# --------------------------------------------------------------------------- the cache

def test_cache_round_trip_and_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "CACHE_DIR", tmp_path)
    doc = {"swept_on": "2026-10-01", "complete": True, "index": {}}
    M.save_cache("heir_estate", doc)
    assert M.load_cache("heir_estate", date(2026, 10, 4)) == doc
    assert M.load_cache("heir_estate", date(2026, 10, 1) + timedelta(days=M.CACHE_TTL_DAYS + 1)) is None
    (tmp_path / "heir_estate.json").write_text("not json")
    assert M.load_cache("heir_estate", date(2026, 10, 2)) is None
    M.save_cache("incomplete", {"swept_on": "2026-10-01", "complete": False})
    assert M.load_cache("incomplete", date(2026, 10, 2)) is None


# --------------------------------------------------------------------------- paging

def _layer(pages, calls):
    """pages: lists of attribute dicts; the keyset query asks for objectid > last."""
    def handler(req: httpx.Request):
        q = dict(req.url.params)
        calls.append(q)
        if "groupByFieldsForStatistics" in q:
            return httpx.Response(200, json={"features": [
                {"attributes": {"cntyname": "Alamance", "n": 3}}, {"attributes": {"cntyname": "Wake", "n": 9}}]})
        last = int(re.search(r"objectid > (-?\d+)", q["where"]).group(1))
        for i, pg in enumerate(pages):
            if max(a["objectid"] for a in pg) > last:
                return httpx.Response(200, json={"features": [{"attributes": a} for a in pg if a["objectid"] > last],
                                                 "exceededTransferLimit": i < len(pages) - 1})
        return httpx.Response(200, json={"features": []})
    return handler


def test_sweep_pages_by_keyset_until_the_layer_stops_exceeding_the_limit(monkeypatch):
    monkeypatch.setattr(M, "PAGE", 2)
    monkeypatch.setattr(M, "PACE_S", 0.0)
    pages = [[{"parno": "1", "objectid": 1}, {"parno": "2", "objectid": 2}],
             [{"parno": "3", "objectid": 5}, {"parno": "4", "objectid": 9}], [{"parno": "5", "objectid": 12}]]
    calls: list = []

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_layer(pages, calls))) as http:
            return await M._sweep(http, "x = 1", "parno")

    rows = asyncio.run(go())
    assert [r["parno"] for r in rows] == ["1", "2", "3", "4", "5"]
    assert [c["where"] for c in calls] == ["(x = 1) AND objectid > -1", "(x = 1) AND objectid > 2",
                                           "(x = 1) AND objectid > 9"]
    assert all(c["orderByFields"] == "objectid" and "resultOffset" not in c for c in calls)


@pytest.mark.parametrize("handler", [
    lambda req: httpx.Response(500),
    lambda req: httpx.Response(200, json={"error": {"code": 400, "message": "Unable to complete operation."}}),
    lambda req: httpx.Response(200, text="<html>not json</html>"),
])
def test_a_failed_page_raises_instead_of_ending_the_sweep_early(handler, monkeypatch):
    monkeypatch.setattr(M, "PACE_S", 0.0)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await M._sweep(http, "1=1", "parno")

    with pytest.raises(M.SweepError):
        asyncio.run(go())


def test_stats_groups_by_county():
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_layer([], []))) as http:
            return await M._stats(http, "presentval = 'Y'")

    assert asyncio.run(go()) == {"Alamance": 3, "Wake": 9}


def test_enrich_never_raises_and_reports_the_failed_sweep(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(M, "PACE_S", 0.0)
    real = httpx.AsyncClient

    class Boom(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(lambda req: httpx.Response(500))
            super().__init__(*a, **kw)

    import contextlib

    @contextlib.asynccontextmanager
    async def fake_client(**kw):
        async with Boom() as c:
            yield c

    monkeypatch.setattr(M, "client", fake_client)
    row = li()
    st = asyncio.run(M.enrich_onemap_sweeps([row]))
    assert set(st["errors"]) == {"heir_estate", "present_use"}
    assert st["screened"] == {} and row.raw is None            # nothing is claimed on a failed sweep


def test_kill_switch(monkeypatch):
    monkeypatch.setenv(M.ENV_OFF, "1")
    assert "skipped" in asyncio.run(M.enrich_onemap_sweeps([li()]))
