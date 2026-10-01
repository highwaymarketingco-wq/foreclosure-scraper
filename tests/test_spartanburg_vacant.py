"""Spartanburg City vacant-property registry.

Audited 2026-10-01. Found and fixed two real field-population gaps (network
mocked here — one page of fake ArcGIS features, no live requests):

1. `owner_name` was never set (only `defendant`), even though the owner name
   is known and already used in `description`/`owner_mailing`. owner_name is
   the field dozens of enrichers across this codebase read (the resolver,
   skip-trace, GIS backfill, ...) — defendant alone is not a universal
   substitute. Live-verified before the fix: 0/4,659 rows had owner_name;
   after: 4,659/4,659.

2. CAMA specs (living_sqft/year_built/bedrooms/bathrooms) were computed into
   raw['cama_specs'] but never promoted to the matching top-level Listing
   fields — traced that nothing in valuation/calc.py reads raw['cama_specs']
   at all (only web_artifact.py's RAW_KEEP retains it for display), so this
   data was fetched, stored, published, and never actually used for ARV.
   Mirrors the sibling spartanburg_condemned.py scraper's existing convention
   of promoting living_sqft/year_built onto the Listing itself.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_sc import spartanburg_vacant as mod


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _feature(**attrs):
    return {"attributes": attrs, "geometry": {"x": -81.93, "y": 34.92}}


_PAGE_1 = {
    "features": [
        _feature(
            TAXPIN="711264855413", OwnerName="YARBOROUGH LOIS", TaxpayerNa=None,
            StreetAddr=None, City=None, State=None, Zip=None,
            PropertyLo="305 WIMBERLY DR", SaleDate=None, SaleAmount=None,
            YearBuilt=1965, ConditionF="FA", LivingArea=1240, BedRooms=3,
            FullBaths=1, HalfBaths=1, LandUse="SFR", PropertyTy="RES",
        ),
        _feature(
            TAXPIN="712244588319", OwnerName="CITY OF SPARTANBURG", TaxpayerNa=None,
            StreetAddr=None, City=None, State=None, Zip=None,
            PropertyLo="0 HIGH ST", SaleDate=None, SaleAmount=None,
            YearBuilt=None, ConditionF=None, LivingArea=None, BedRooms=None,
            FullBaths=None, HalfBaths=None, LandUse=None, PropertyTy=None,
        ),
        _feature(
            TAXPIN="712204145906", OwnerName="SHELL RICKY", TaxpayerNa=None,
            StreetAddr=None, City=None, State=None, Zip=None,
            PropertyLo="202 NORTH ST", SaleDate=None, SaleAmount=None,
            YearBuilt=None, ConditionF="PR", LivingArea=None, BedRooms=None,
            FullBaths=None, HalfBaths=None, LandUse=None, PropertyTy=None,
        ),
    ]
}
_PAGE_EMPTY = {"features": []}


def _run_fetch(monkeypatch):
    calls = {"n": 0}

    def fake_client(**kw):
        class _FakeHTTPClient:
            async def get(self, url, params=None):
                calls["n"] += 1
                if calls["n"] == 1:
                    return _FakeResponse(_PAGE_1)
                return _FakeResponse(_PAGE_EMPTY)

        class _CM:
            async def __aenter__(self):
                return _FakeHTTPClient()

            async def __aexit__(self, *a):
                return False

        return _CM()

    monkeypatch.setattr(mod, "client", fake_client)
    return list(asyncio.run(mod.SpartanburgVacant().fetch()))


def test_owner_name_is_populated_alongside_defendant(monkeypatch):
    out = _run_fetch(monkeypatch)
    assert len(out) == 2  # the CITY OF SPARTANBURG gov row is dropped
    for li in out:
        assert li.owner_name
        assert li.owner_name == li.defendant


def test_cama_specs_promoted_to_top_level_listing_fields(monkeypatch):
    out = _run_fetch(monkeypatch)
    row = next(li for li in out if li.parcel_id == "711264855413")
    assert row.living_sqft == 1240.0
    assert row.year_built == 1965
    assert row.bedrooms == 3.0
    assert row.bathrooms == 1.5  # 1 full + 1 half


def test_cama_specs_still_present_in_raw_for_backward_compat(monkeypatch):
    out = _run_fetch(monkeypatch)
    row = next(li for li in out if li.parcel_id == "711264855413")
    assert row.raw["cama_specs"]["living_sqft"] == 1240


def test_row_with_no_cama_data_leaves_fields_none_not_zero(monkeypatch):
    out = _run_fetch(monkeypatch)
    row = next(li for li in out if li.parcel_id == "712204145906")
    assert row.living_sqft is None
    assert row.year_built is None
    assert row.bedrooms is None
    assert row.bathrooms is None


def test_government_owner_still_excluded(monkeypatch):
    out = _run_fetch(monkeypatch)
    assert all("CITY OF" not in (li.owner_name or "") for li in out)


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties_sc.spartanburg_vacant" in {s.slug for s in all_scrapers()}
