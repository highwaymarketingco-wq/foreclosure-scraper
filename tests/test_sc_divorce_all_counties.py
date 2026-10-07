"""SC divorce enricher: all 46 counties (2026-10-07). Made-up names only."""
from __future__ import annotations

import asyncio

from foreclosure_scraper import enrichment_sc_divorce as m
from foreclosure_scraper.models import Listing, ListingType


def test_county_map_has_all_46_counties_and_keeps_the_original_8():
    assert len(m._COUNTY_CODE) == 46
    assert sorted(m._COUNTY_CODE.values()) == list(range(1005, 1051))
    assert list(m._COUNTY_CODE) == sorted(m._COUNTY_CODE, key=str.lower)  # alphabetical = code order
    original = {"Spartanburg": 1046, "Anderson": 1008, "Pickens": 1043, "Oconee": 1041,
                "Cherokee": 1015, "Union": 1048, "Laurens": 1034, "Greenville": 1027}
    assert all(m._COUNTY_CODE[k] == v for k, v in original.items())


def test_county_code_lookup_is_forgiving_and_sc_only():
    assert m._county_code("York") == 1050
    assert m._county_code("York County") == 1050
    assert m._county_code("Mccormick") == m._county_code("McCormick") == 1039
    assert m._county_code(" charleston ") == 1014
    assert m._county_code("Wake") is None
    assert m._county_code(None) is None


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _lead(i, county, state="SC", owner="SAMPLEMAN SAM"):
    return Listing(source="x", source_url=f"u{i}", listing_type=ListingType.TAX_LIEN,
                   state=state, county=county, owner_name=owner, parcel_id=f"P{i}")


def test_new_counties_are_searched_with_their_own_code(monkeypatch):
    seen = []

    async def fake_search(session, headers, last, first, county_code):
        seen.append(county_code)
        return []

    async def _hs(session):
        return "tok"

    monkeypatch.setattr(m, "AsyncSession", lambda **k: _Session())
    monkeypatch.setattr(m, "_handshake", _hs)
    monkeypatch.setattr(m, "_search_one", fake_search)
    monkeypatch.setattr(m, "_CONCURRENCY", 1)
    leads = [_lead(1, "York"), _lead(2, "Horry County"), _lead(3, "Mccormick"),
             _lead(4, "Spartanburg"), _lead(5, "Wake", state="NC"), _lead(6, "Nowhere")]
    stats = asyncio.run(m.enrich_sc_divorce(leads, max_lookups=10))
    assert stats["targets"] == 4 and stats["searched"] == 4
    assert sorted(seen) == [1030, 1039, 1046, 1050]
    assert "divorce" in leads[0].raw and "divorce" not in leads[4].raw


def test_per_run_cap_still_applies_across_more_counties(monkeypatch):
    async def fake_search(session, headers, last, first, county_code):
        return []

    async def _hs(session):
        return "tok"

    monkeypatch.setattr(m, "AsyncSession", lambda **k: _Session())
    monkeypatch.setattr(m, "_handshake", _hs)
    monkeypatch.setattr(m, "_search_one", fake_search)
    monkeypatch.setattr(m, "_CONCURRENCY", 1)
    leads = [_lead(i, c) for i, c in enumerate(list(m._COUNTY_CODE) * 2)]
    stats = asyncio.run(m.enrich_sc_divorce(leads, max_lookups=5))
    assert stats["pending"] == 92 and stats["targets"] == 5 and stats["searched"] == 5
