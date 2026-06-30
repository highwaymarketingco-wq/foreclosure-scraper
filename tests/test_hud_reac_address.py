"""HUD REAC address backfill — REMS-id join fills a real street address + geo."""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_hud_reac_address as mod


def _reac_lead(name: str, rems: str, county: str = "Gaston", state: str = "NC") -> Listing:
    now = datetime.utcnow()
    return Listing(
        source="national.hud_reac_inspection",
        source_url="https://www.hud.gov/stat/mfh/inspection-scores",
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.MULTI_FAMILY,
        street_address=name,  # placeholder == name
        owner_name=name,
        county=county,
        state=state,
        first_seen=now,
        last_seen=now,
        raw={"reac": {"rems_property_id": rems, "property_name": name}},
    )


_FAKE_INDEX = {
    "800012450": {"addr": "2900 Union Rd", "city": "Gastonia", "st": "NC",
                  "zip": "28054", "lat": 35.2203, "lng": -81.1685},
}


def test_join_fills_real_address_and_geo(monkeypatch):
    async def fake_index():
        return _FAKE_INDEX
    monkeypatch.setattr(mod, "_build_index", fake_index)

    li = _reac_lead("A.R.P. MANOR", "800012450")
    stats = asyncio.run(mod.enrich_hud_reac_address([li]))

    assert stats["matched"] == 1
    assert li.street_address == "2900 Union Rd"
    assert li.street_address != li.owner_name  # no longer the placeholder
    assert li.city == "Gastonia"
    assert li.zip_code == "28054"
    assert li.latitude == pytest.approx(35.2203)
    assert li.longitude == pytest.approx(-81.1685)
    assert li.raw["reac"]["hud_address_source"] == "Multifamily_Properties_Assisted"


def test_no_rems_match_left_untouched(monkeypatch):
    async def fake_index():
        return _FAKE_INDEX
    monkeypatch.setattr(mod, "_build_index", fake_index)

    li = _reac_lead("UNKNOWN COMPLEX", "999999999")
    stats = asyncio.run(mod.enrich_hud_reac_address([li]))
    assert stats["matched"] == 0
    assert li.street_address == "UNKNOWN COMPLEX"  # untouched placeholder


def test_lead_with_real_address_is_not_a_target(monkeypatch):
    called = {"n": 0}
    async def fake_index():
        called["n"] += 1
        return _FAKE_INDEX
    monkeypatch.setattr(mod, "_build_index", fake_index)

    li = _reac_lead("A.R.P. MANOR", "800012450")
    li.street_address = "2900 Union Rd"  # already real (differs from name)
    stats = asyncio.run(mod.enrich_hud_reac_address([li]))
    assert stats["matched"] == 0
    assert called["n"] == 0  # no targets -> never even fetched the index


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_HUD_REAC_ADDR", "0")
    li = _reac_lead("A.R.P. MANOR", "800012450")
    stats = asyncio.run(mod.enrich_hud_reac_address([li]))
    assert stats["matched"] == 0
