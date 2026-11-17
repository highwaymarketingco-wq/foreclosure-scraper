"""Haywood County NC maps.haywoodcountync.gov Land_Records/Public_Access MapServer
"Defer_Value" field -> raw['rollback_exposure']. Values below match a real row read live
2026-11-17 (PIN "8609-42-0939", owner "ROSS, HOBERT DEAN/TR", Defer_Value $512,639 of $944,600
Mkt_Value) -- not invented."""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.enrichment_haywood_rollback_exposure import (
    _compact_pid, _is_haywood_nc, build_rollback_block, enrich_haywood_rollback_exposure,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(parcel_id, county="Haywood", state="NC", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state=state, owner_name="OWNER", parcel_id=parcel_id,
                   first_seen=now, last_seen=now, raw=kw.pop("raw", {}), **kw)


def test_compact_pid_strips_the_dashed_pin_format():
    assert _compact_pid("8609-42-0939") == "8609420939"
    assert _compact_pid("8605-90-3984") == "8605903984"


def test_rollback_block_never_invents_a_zero_or_missing_deferral():
    assert build_rollback_block({"deferred_value": 0}) is None
    got = build_rollback_block({"deferred_value": 512639.0, "market_value": 944600.0})
    assert got["deferred_value"] == 512639.0
    assert got["county"] == "Haywood" and got["state"] == "NC"
    assert got["rollback_years"] == 4
    assert got["market_value"] == 944600.0


def test_is_haywood_nc_requires_the_right_county_and_state():
    assert _is_haywood_nc(_li("8609-42-0939"))
    assert not _is_haywood_nc(_li("8609-42-0939", county="Macon"))
    assert not _is_haywood_nc(_li("8609-42-0939", state="SC"))


@pytest.mark.asyncio
async def test_a_matched_parcel_gets_rollback_exposure(monkeypatch):
    import foreclosure_scraper.enrichment_haywood_rollback_exposure as mod

    async def _fake_fetch(c):
        return {"8609420939": {"deferred_value": 512639.0, "market_value": 944600.0}}

    monkeypatch.setattr(mod, "fetch_deferred_by_pid", _fake_fetch)
    li = _li("8609-42-0939")
    stats = await enrich_haywood_rollback_exposure([li])
    assert stats["matched"] == 1
    assert li.raw["rollback_exposure"]["deferred_value"] == 512639.0


@pytest.mark.asyncio
async def test_a_board_pin_without_dashes_still_matches(monkeypatch):
    import foreclosure_scraper.enrichment_haywood_rollback_exposure as mod

    async def _fake_fetch(c):
        return {"8609420939": {"deferred_value": 512639.0}}

    monkeypatch.setattr(mod, "fetch_deferred_by_pid", _fake_fetch)
    li = _li("8609420939")  # board's own bare form
    stats = await enrich_haywood_rollback_exposure([li])
    assert stats["matched"] == 1


@pytest.mark.asyncio
async def test_a_parcel_with_no_hit_gets_no_fabricated_record(monkeypatch):
    import foreclosure_scraper.enrichment_haywood_rollback_exposure as mod

    async def _fake_fetch(c):
        return {}

    monkeypatch.setattr(mod, "fetch_deferred_by_pid", _fake_fetch)
    li = _li("8609-42-0939")
    await enrich_haywood_rollback_exposure([li])
    assert "rollback_exposure" not in li.raw
