"""Durham County NC webgis2.durhamnc.gov PublicServices/Property Parcels layer
"TOTAL_DEFERRED_VALUE" field -> raw['rollback_exposure']. Values below match real rows read
live 2026-11-19 (PIN "0830318548": land $1,658,596 - present-use land $5,166 = USE_VALUE_DEFERRED
$1,653,430; PIN "0822527500": HISTORIC_VALUE_DEFERRED $663,375 of TOTAL_PROP_VALUE $1,327,263) --
not invented."""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.enrichment_durham_rollback_exposure import (
    _compact_pid, _is_durham_nc, build_rollback_block, enrich_durham_rollback_exposure,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(parcel_id, county="Durham", state="NC", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state=state, owner_name="OWNER", parcel_id=parcel_id,
                   first_seen=now, last_seen=now, raw=kw.pop("raw", {}), **kw)


def test_compact_pid_is_a_no_op_on_an_already_bare_pin():
    assert _compact_pid("0830318548") == "0830318548"
    assert _compact_pid(None) == ""


def test_rollback_block_never_invents_a_zero_or_missing_deferral():
    assert build_rollback_block({"deferred_value": 0, "full_value": 100.0}) is None
    assert build_rollback_block({"deferred_value": None, "full_value": 100.0}) is None
    assert build_rollback_block({"deferred_value": 50.0, "full_value": 0}) is None


def test_rollback_block_derives_taxable_value_exactly_from_the_two_literal_fields():
    # real sampled row: land $1,658,596 + bldg $324,050 = full $1,982,646;
    # USE_VALUE_DEFERRED $1,653,430, no historic component.
    got = build_rollback_block({
        "deferred_value": 1653430.0, "full_value": 1982646.0,
        "use_value_deferred": 1653430.0, "historic_value_deferred": 0.0,
        "land_class": "PRESENT-USE/HORTICUL",
    })
    assert got["deferred_value"] == 1653430.0
    assert got["full_value"] == 1982646.0
    assert got["taxable_value"] == 1982646.0 - 1653430.0
    assert got["basis"] == "present_use_deferral"
    assert got["land_class"] == "PRESENT-USE/HORTICUL"
    assert got["county"] == "Durham" and got["state"] == "NC"
    assert got["rollback_years"] == 4


def test_rollback_block_basis_is_historic_when_only_the_historic_component_is_set():
    got = build_rollback_block({
        "deferred_value": 663375.0, "full_value": 1327263.0,
        "use_value_deferred": None, "historic_value_deferred": 663375.0,
    })
    assert got["basis"] == "historic_deferral"


def test_rollback_block_basis_is_combined_when_both_components_are_set():
    got = build_rollback_block({
        "deferred_value": 100.0, "full_value": 500.0,
        "use_value_deferred": 60.0, "historic_value_deferred": 40.0,
    })
    assert got["basis"] == "present_use+historic_deferral"


def test_rollback_block_never_yields_a_negative_taxable_value():
    # defensive: a corrupt/stale read where deferred > full must not be trusted blindly.
    assert build_rollback_block({"deferred_value": 600.0, "full_value": 500.0}) is None


def test_is_durham_nc_requires_the_right_county_and_state():
    assert _is_durham_nc(_li("0830318548"))
    assert not _is_durham_nc(_li("0830318548", county="Wake"))
    assert not _is_durham_nc(_li("0830318548", state="SC"))


@pytest.mark.asyncio
async def test_a_matched_parcel_gets_rollback_exposure(monkeypatch):
    import foreclosure_scraper.enrichment_durham_rollback_exposure as mod

    async def _fake_fetch(client):
        return {"0830318548": {"deferred_value": 1653430.0, "full_value": 1982646.0,
                                "use_value_deferred": 1653430.0, "historic_value_deferred": 0.0,
                                "land_class": "PRESENT-USE/HORTICUL"}}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("0830318548")
    stats = await enrich_durham_rollback_exposure([li])
    assert stats["matched"] == 1
    assert li.raw["rollback_exposure"]["deferred_value"] == 1653430.0


@pytest.mark.asyncio
async def test_a_parcel_with_no_hit_gets_no_fabricated_record(monkeypatch):
    import foreclosure_scraper.enrichment_durham_rollback_exposure as mod

    async def _fake_fetch(client):
        return {}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("0830318548")
    await enrich_durham_rollback_exposure([li])
    assert "rollback_exposure" not in li.raw


@pytest.mark.asyncio
async def test_an_existing_rollback_record_is_never_re_targeted(monkeypatch):
    import foreclosure_scraper.enrichment_durham_rollback_exposure as mod
    called = {"n": 0}

    async def _fake_fetch(client):
        called["n"] += 1
        return {}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("0830318548", raw={"rollback_exposure": {"deferred_value": 1.0}})
    stats = await enrich_durham_rollback_exposure([li])
    assert stats["eligible"] == 0
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_disabled_via_env_short_circuits(monkeypatch):
    import foreclosure_scraper.enrichment_durham_rollback_exposure as mod

    monkeypatch.setattr(mod, "ENABLED", False)
    li = _li("0830318548")
    stats = await enrich_durham_rollback_exposure([li])
    assert stats == {"eligible": 0, "deferred_pins": 0, "matched": 0, "fetch_errors": 0}
