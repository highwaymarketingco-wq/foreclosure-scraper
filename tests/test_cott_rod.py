"""Cott Systems / cotthosting.com (Polk + Rutherford NC) — rod/cott.py.

2026-10-02 REWRITTEN: this module used to carry its own POST flow (real
__VIEWSTATE/__EVENTVALIDATION tokens, `ctl00$cphMain$txtLastName` field
names) built against a generic ASP.NET WebForms template that does not match
this vendor — live-probed, __VIEWSTATE is empty/absent here exactly like
Buncombe/Gaston, so every POST just re-rendered the blank search form and
every public function silently returned [] for both counties. It now
delegates entirely to rod/aumentum.py's live-verified `*_at()` entry points
(see that module's docstring). These tests pin the delegation wiring: the
right base URL for each county, the right underlying aumentum function, and
that an unmapped county still short-circuits to [] without calling network
code. CI never hits the network — aumentum's own `*_at()` functions are
monkeypatched out.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.rod import aumentum, cott


def test_cott_counties():
    assert set(cott.COTT_COUNTIES) == {("NC", "Polk"), ("NC", "Rutherford")}
    assert cott.COTT_COUNTIES[("NC", "Polk")] == \
        "https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4"
    assert cott.COTT_COUNTIES[("NC", "Rutherford")] == \
        "https://cotthosting.com/NCRUTHERFORDEXTERNAL/LandRecords/protected/v4"


def test_search_by_name_delegates_to_aumentum_with_the_right_base(monkeypatch):
    seen = {}

    async def fake(base, county, state, name, max_docs):
        seen.update(base=base, county=county, state=state, name=name, max_docs=max_docs)
        return ["sentinel"]

    monkeypatch.setattr(aumentum, "_search_by_name_at", fake)
    out = asyncio.run(cott.search_by_name("NC", "Rutherford", "SMITH", max_docs=25))

    assert out == ["sentinel"]
    assert seen == {
        "base": "https://cotthosting.com/NCRUTHERFORDEXTERNAL/LandRecords/protected/v4",
        "county": "Rutherford", "state": "NC", "name": "SMITH", "max_docs": 25,
    }


def test_discover_recent_nods_delegates_to_aumentum_with_the_right_base(monkeypatch):
    seen = {}

    async def fake(base, county, state, days_back, max_docs):
        seen.update(base=base, county=county, state=state,
                    days_back=days_back, max_docs=max_docs)
        return ["sentinel"]

    monkeypatch.setattr(aumentum, "discover_recent_nods_at", fake)
    out = asyncio.run(cott.discover_recent_nods("NC", "Polk", days_back=45, max_docs=10))

    assert out == ["sentinel"]
    assert seen == {
        "base": "https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4",
        "county": "Polk", "state": "NC", "days_back": 45, "max_docs": 10,
    }


def test_discover_recent_sold_recordings_delegates_to_aumentum_with_the_right_base(monkeypatch):
    seen = {}

    async def fake(base, county, state, days_back, max_docs):
        seen.update(base=base, county=county, state=state,
                    days_back=days_back, max_docs=max_docs)
        return ["sentinel"]

    monkeypatch.setattr(aumentum, "discover_recent_sold_recordings_at", fake)
    out = asyncio.run(cott.discover_recent_sold_recordings("NC", "Rutherford"))

    assert out == ["sentinel"]
    assert seen["base"] == "https://cotthosting.com/NCRUTHERFORDEXTERNAL/LandRecords/protected/v4"
    assert seen["county"] == "Rutherford" and seen["state"] == "NC"


def test_unmapped_county_short_circuits_without_touching_aumentum(monkeypatch):
    """An unmapped (state, county) must return [] WITHOUT calling into
    aumentum at all — if any of these fire, the guard is broken."""
    def boom(*a, **kw):
        raise AssertionError("should not be called for an unmapped county")

    monkeypatch.setattr(aumentum, "_search_by_name_at", boom)
    monkeypatch.setattr(aumentum, "discover_recent_nods_at", boom)
    monkeypatch.setattr(aumentum, "discover_recent_sold_recordings_at", boom)

    assert asyncio.run(cott.search_by_name("NC", "Wake", "SMITH")) == []
    assert asyncio.run(cott.discover_recent_nods("NC", "Wake")) == []
    assert asyncio.run(cott.discover_recent_sold_recordings("NC", "Wake")) == []
