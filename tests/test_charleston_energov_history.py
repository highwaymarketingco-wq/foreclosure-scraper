"""Charleston County SC EnerGov history (building-code cases + demolition permits).

Date-coverage audit fix, 2026-10-14 (docs/date_coverage_audit_2026-10-14.md, target #3):
`FORECLOSURE_CHARLESTON_ENERGOV_DAYS` defaulted to 730 and was baked into both slices' WHERE
clause as a hard floor, even though the layer is a full, date-agnostic 16-year, 386k+ row
history updated daily. Live-verified 2026-10-14: 125 of 1,873 all-time code cases (93%
excluded) and 944 of 3,228 all-time demolition permits (71% excluded) fell inside the old
730-day window; a full live fetch went from 469 leads (730-day window) to 2,778 leads
(no floor). The fix drops the date floor by default (`since=None`); the env var still
narrows it for an explicit sample run. The fixture cases below are schema-accurate to a
real `ENERGOV HISTORY POINTS` row (read live 2026-10-14), not invented.
"""
from __future__ import annotations

import json as _json
from datetime import datetime, timezone

import httpx
import pytest

import foreclosure_scraper.scrapers.counties_sc.charleston_energov_history as m

HISTORY_URL = m.HISTORY
ADDRESSES_URL = m.ADDRESSES


def _ms(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


# --------------------------------------------------------------------------- where_clauses

def test_where_clauses_drop_the_date_floor_by_default():
    where = m.where_clauses(None)
    assert where["code"] == "MODULENAME='CodeManagement' AND CASETYPE IN ('Building Services')"
    assert where["demolition"] == "MODULENAME='PermitManagement' AND WORKCLASS LIKE 'Demolition%'"
    assert "APPLICATIONDATE" not in where["code"] and "APPLICATIONDATE" not in where["demolition"]


def test_where_clauses_add_the_floor_only_when_since_is_given():
    since = datetime(2024, 10, 14, tzinfo=timezone.utc)
    where = m.where_clauses(since)
    assert where["code"].endswith("AND APPLICATIONDATE >= DATE '2024-10-14'")
    assert where["demolition"].endswith("AND APPLICATIONDATE >= DATE '2024-10-14'")


# --------------------------------------------------------------------------- real-shaped fixture rows
#
# Real attribute shapes (trimmed), live 2026-10-14: a 2010 code case is the measured oldest
# on the layer; a 2026 one is current. Points are made up (real coordinates are SC state
# plane, not needed here) but internally consistent with the address-match fixtures below.

CODE_OLD_FEATURE = {
    "attributes": {"OBJECTID": 1, "MODULENAME": "CodeManagement", "CASENUMBER": "CE10-00321",
                   "CASETYPE": "Building Services", "WORKCLASS": None,
                   "APPLICATIONDATE": _ms("2010-11-04")},
    "geometry": {"x": 1.0, "y": 1.0},
}
CODE_NEW_FEATURE = {
    "attributes": {"OBJECTID": 2, "MODULENAME": "CodeManagement", "CASENUMBER": "CE26-04455",
                   "CASETYPE": "Building Services", "WORKCLASS": None,
                   "APPLICATIONDATE": _ms("2026-09-01")},
    "geometry": {"x": 2.0, "y": 2.0},
}
DEMO_OLD_FEATURE = {
    "attributes": {"OBJECTID": 3, "MODULENAME": "PermitManagement", "CASENUMBER": "PR16-00099",
                   "CASETYPE": "Building (R)", "WORKCLASS": "Demolition",
                   "APPLICATIONDATE": _ms("2016-04-11")},
    "geometry": {"x": 3.0, "y": 3.0},
}
DEMO_NEW_FEATURE = {
    "attributes": {"OBJECTID": 4, "MODULENAME": "PermitManagement", "CASENUMBER": "PR26-00777",
                   "CASETYPE": "Building (R)", "WORKCLASS": "Demolition",
                   "APPLICATIONDATE": _ms("2026-10-01")},
    "geometry": {"x": 4.0, "y": 4.0},
}


def test_unique_cases_and_group_by_property_carry_a_2010_case_through_with_no_date_logic():
    """unique_cases/group_by_property apply no date filtering of their own -- whatever the
    fetch hands them becomes a lead. Proves the ONLY thing standing between a 2010 case and
    the board was the WHERE clause, which the fix now leaves open by default."""
    cases = m.unique_cases([CODE_OLD_FEATURE], "code")
    assert len(cases) == 1 and cases[0]["date"].year == 2010
    addr = {"PID": "1234", "WHOLE_ADDRESS": "100 OLD ST", "POSTAL_TOWN": "CHARLESTON",
            "POSTAL_CODE": "29401"}
    [g] = m.group_by_property(cases, [addr])
    li = m.to_listing(g)
    assert li.raw["code_enforcement"]["violations"][0]["date"] == "2010-11-04"
    assert li.parcel_id == "1234"


# --------------------------------------------------------------------------- full fetch() integration

def _cutoff_date(where: str) -> str | None:
    import re
    mo = re.search(r"DATE '(\d{4}-\d{2}-\d{2})'", where)
    return mo.group(1) if mo else None


def _history_handler(features: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        where = request.url.params.get("where", "")
        cutoff = _cutoff_date(where)
        kept = features
        if cutoff is not None:
            floor = _ms(cutoff)
            kept = [f for f in features if (f["attributes"].get("APPLICATIONDATE") or 0) >= floor]
        return httpx.Response(200, json={"objectIdFieldName": "OBJECTID", "features": kept,
                                         "exceededTransferLimit": False})
    return handler


# Every fixture point maps 1:1 to an address, matched by exact coordinates (distance 0).
_POINT_TO_ADDR = {
    (1.0, 1.0): {"PID": "P-OLD-CODE", "WHOLE_ADDRESS": "1 OLD CODE ST", "POSTAL_TOWN": "CHARLESTON",
                "POSTAL_CODE": "29401"},
    (2.0, 2.0): {"PID": "P-NEW-CODE", "WHOLE_ADDRESS": "2 NEW CODE ST", "POSTAL_TOWN": "CHARLESTON",
                "POSTAL_CODE": "29401"},
    (3.0, 3.0): {"PID": "P-OLD-DEMO", "WHOLE_ADDRESS": "3 OLD DEMO ST", "POSTAL_TOWN": "CHARLESTON",
                "POSTAL_CODE": "29401"},
    (4.0, 4.0): {"PID": "P-NEW-DEMO", "WHOLE_ADDRESS": "4 NEW DEMO ST", "POSTAL_TOWN": "CHARLESTON",
                "POSTAL_CODE": "29401"},
}


def _addresses_handler(request: httpx.Request) -> httpx.Response:
    import urllib.parse
    body = dict(urllib.parse.parse_qsl(request.content.decode()))
    geom = _json.loads(body["geometry"])
    feats = []
    for x, y in geom["points"]:
        addr = _POINT_TO_ADDR.get((x, y))
        if addr:
            feats.append({"attributes": addr, "geometry": {"x": x, "y": y}})
    return httpx.Response(200, json={"features": feats})


def _combined_transport(history_features: list[dict]):
    hist = _history_handler(history_features)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(HISTORY_URL):
            return hist(request)
        if url.startswith(ADDRESSES_URL):
            return _addresses_handler(request)
        return httpx.Response(404, json={"error": f"no route for {url}"})
    return httpx.MockTransport(handler)


@pytest.fixture
def _patched_client(monkeypatch):
    features = [CODE_OLD_FEATURE, CODE_NEW_FEATURE, DEMO_OLD_FEATURE, DEMO_NEW_FEATURE]
    transport = _combined_transport(features)
    monkeypatch.setattr(m, "client", lambda timeout=90.0: httpx.AsyncClient(transport=transport))


def test_fetch_with_no_date_floor_includes_a_2010_code_case_and_a_2016_demolition(_patched_client, monkeypatch):
    import asyncio
    monkeypatch.delenv("FORECLOSURE_CHARLESTON_ENERGOV_DAYS", raising=False)
    out = asyncio.run(m.CharlestonEnergovHistory().fetch())
    pids = {li.parcel_id for li in out}
    assert {"P-OLD-CODE", "P-NEW-CODE", "P-OLD-DEMO", "P-NEW-DEMO"} <= pids
    old_code = next(li for li in out if li.parcel_id == "P-OLD-CODE")
    assert old_code.raw["code_enforcement"]["violations"][0]["date"] == "2010-11-04"
    old_demo = next(li for li in out if li.parcel_id == "P-OLD-DEMO")
    assert old_demo.raw["demolition_permit"]["latest_date"] == "2016-04-11"


def test_fetch_with_an_explicit_days_window_drops_the_old_cases(_patched_client, monkeypatch):
    import asyncio
    monkeypatch.setenv("FORECLOSURE_CHARLESTON_ENERGOV_DAYS", "730")
    out = asyncio.run(m.CharlestonEnergovHistory().fetch())
    pids = {li.parcel_id for li in out}
    assert "P-OLD-CODE" not in pids and "P-OLD-DEMO" not in pids
    assert "P-NEW-CODE" in pids and "P-NEW-DEMO" in pids
