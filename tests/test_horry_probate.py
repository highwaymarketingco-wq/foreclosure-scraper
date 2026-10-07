"""Horry County SC probate estates via the Spartan portal (hand-written rows).

Row keys and value shapes match the live grid answer read on 2026-10-07; every
name and case number below is made up.
"""
from __future__ import annotations

import asyncio
import json

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_sc import horry_probate as mod

NOW = mod.datetime(2026, 10, 7)


def _row(case="2026ES2699001", name="TESTPERSON, ALEXANDRA Q", ptype="Deceased Person                         ",
         filed="09/15/2026"):
    return {"APPCODE": "26500", "CMSCASE": 999001.0, "WARANTNO": case, "CASENBR": "", "PROSCODE": "ZZZ",
            "CseFilDt": filed, "CseTypIn": "E", "PPTYSEQ": 1.0, "PPTYNAME": name,
            "PPTYLNAME": "TESTPERSON", "PPTYFNAME": "ALEXANDRA", "PROSNAME": "PLACEHOLDER, CLERK",
            "PPTYTYPE": ptype}


def _payload(rows, total):
    return {"d": json.dumps({"Error": None, "sEcho": 1, "recordsFiltered": total,
                             "recordsTotal": total, "aaData": rows})}


def test_row_becomes_a_probate_lead_for_the_decedent():
    li = mod.build_listing(_row(), now=NOW)
    assert li.listing_type == ListingType.PROBATE_NOTICE
    assert (li.state, li.county, li.case_number) == ("SC", "Horry", "2026ES2699001")
    assert li.owner_name == "TESTPERSON, ALEXANDRA Q"
    p = li.raw["probate"]
    assert p["filing_date"] == "2026-09-15" and p["party_type"] == "Deceased Person"
    assert "PROSNAME" not in repr(li.raw) and "PLACEHOLDER, CLERK" not in repr(li.raw)


def test_non_decedent_and_unnamed_rows_are_dropped():
    assert mod.build_listing(_row(ptype="Petitioner"), now=NOW) is None
    assert mod.build_listing(_row(name=""), now=NOW) is None


def test_search_params_match_the_grid_request():
    p = mod.search_params(2026, 500)
    assert p["CaseNumber"] == "2026ES26" and p["AgencyId"] == "26500"
    assert (p["iDisplayStart"], p["iDisplayLength"]) == ("500", "500")


def test_decode_handles_the_asmx_wrapper_and_junk():
    assert mod.decode(_payload([_row()], 1))["recordsTotal"] == 1
    assert mod.decode({"d": "not json"}) == {} and mod.decode([]) == {}


class _Resp:
    def __init__(self, payload, status_code=200):
        self._p, self.status_code = payload, status_code

    def json(self):
        return self._p


class _Http:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        if url == mod.PAGE_URL:
            return _Resp({})
        return self.pages.pop(0) if self.pages else _Resp(_payload([], 0))


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_fetch_pages_by_offset_dedupes_and_applies_the_lookback(monkeypatch):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    monkeypatch.setattr(mod, "_PAUSE_S", 0)
    this_year = [_Resp(_payload([_row("2026ES2699001"), _row("2026ES2699002")], 3)),
                 _Resp(_payload([_row("2026ES2699002"), _row("2026ES2699003", filed="01/02/2024")], 3))]
    last_year = [_Resp(_payload([_row("2025ES2699004", filed="12/01/2025")], 1))]
    http = _Http(this_year + last_year)
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    s = mod.HorryProbate()
    rows = asyncio.run(s.fetch())
    assert sorted(li.case_number for li in rows) == ["2025ES2699004", "2026ES2699001", "2026ES2699002"]
    data_calls = [c for c in http.calls if c[0] == mod.DATA_URL]
    assert [c[1]["CaseNumber"] for c in data_calls] == ["2026ES26", "2026ES26", "2025ES26"]


def test_future_filing_date_typo_is_blanked():
    li = mod.build_listing(_row(filed="06/01/3025"), now=NOW)
    assert li.raw["probate"]["filing_date"] is None
