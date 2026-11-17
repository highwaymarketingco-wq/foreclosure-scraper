"""Macon County NC gis.maconnc.org TaxParcels MapServer "DEFERMENT" field ->
raw['rollback_exposure']. Values below match a real row read live 2026-11-17 (PIN
"6468452250", owner "THE COPE FAMILY LIMITED PATNERSHIP I", DEFERMENT $328,040 of $352,350
LAND_VALUE) -- not invented."""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.enrichment_macon_rollback_exposure import (
    _compact_pid, _is_macon_nc, build_rollback_block, enrich_macon_rollback_exposure,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(parcel_id, county="Macon", state="NC", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state=state, owner_name="OWNER", parcel_id=parcel_id,
                   first_seen=now, last_seen=now, raw=kw.pop("raw", {}), **kw)


def test_compact_pid_is_a_no_op_on_an_already_bare_pin():
    assert _compact_pid("6468452250") == "6468452250"
    assert _compact_pid(None) == ""


def test_rollback_block_never_invents_a_zero_or_missing_deferral():
    assert build_rollback_block({"deferred_value": 0}) is None
    assert build_rollback_block({"deferred_value": None}) is None
    got = build_rollback_block({"deferred_value": 328040.0, "land_value": 352350.0})
    assert got["deferred_value"] == 328040.0
    assert got["county"] == "Macon" and got["state"] == "NC"
    assert got["rollback_years"] == 4
    assert got["land_value"] == 352350.0


def test_is_macon_nc_requires_the_right_county_and_state():
    assert _is_macon_nc(_li("6468452250"))
    assert not _is_macon_nc(_li("6468452250", county="Craven"))
    assert not _is_macon_nc(_li("6468452250", state="SC"))


@pytest.mark.asyncio
async def test_a_matched_parcel_gets_rollback_exposure(monkeypatch):
    import foreclosure_scraper.enrichment_macon_rollback_exposure as mod

    async def _fake_fetch(c):
        return {"6468452250": {"deferred_value": 328040.0, "land_value": 352350.0}}

    monkeypatch.setattr(mod, "fetch_deferred_by_pid", _fake_fetch)
    li = _li("6468452250")
    stats = await enrich_macon_rollback_exposure([li])
    assert stats["matched"] == 1
    assert li.raw["rollback_exposure"]["deferred_value"] == 328040.0


@pytest.mark.asyncio
async def test_a_parcel_with_no_hit_gets_no_fabricated_record(monkeypatch):
    import foreclosure_scraper.enrichment_macon_rollback_exposure as mod

    async def _fake_fetch(c):
        return {}

    monkeypatch.setattr(mod, "fetch_deferred_by_pid", _fake_fetch)
    li = _li("6468452250")
    await enrich_macon_rollback_exposure([li])
    assert "rollback_exposure" not in li.raw


@pytest.mark.asyncio
async def test_an_existing_rollback_record_is_never_re_targeted(monkeypatch):
    import foreclosure_scraper.enrichment_macon_rollback_exposure as mod
    called = {"n": 0}

    async def _fake_fetch(c):
        called["n"] += 1
        return {}

    monkeypatch.setattr(mod, "fetch_deferred_by_pid", _fake_fetch)
    li = _li("6468452250", raw={"rollback_exposure": {"deferred_value": 1.0}})
    stats = await enrich_macon_rollback_exposure([li])
    assert stats["eligible"] == 0
