"""Hertford County NC gis.hertfordcounty.org TaxParcels "TOTAL_DEFERRED_VALUE" field ->
raw['rollback_exposure']. Values below match real rows read live 2026-11-19 (REID
"6941164705000": TOTAL_LAND_ASSESSED $72,092 + TOTAL_BLDG_ASSESSED $214,881 = full $286,973;
TOTAL_PROP_VALUE (already reduced) $247,353; TOTAL_DEFERRED_VALUE $39,620 == $286,973 -
$247,353 exactly) -- not invented."""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.enrichment_hertford_rollback_exposure import (
    _already_done, _compact_pid, _is_hertford_nc, build_rollback_block,
    enrich_hertford_rollback_exposure,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(parcel_id, county="Hertford", state="NC", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state=state, owner_name="OWNER", parcel_id=parcel_id,
                   first_seen=now, last_seen=now, raw=kw.pop("raw", {}), **kw)


def test_compact_pid_is_a_no_op_on_an_already_bare_reid():
    assert _compact_pid("6941164705000") == "6941164705000"
    assert _compact_pid(None) == ""


def test_compact_pid_strips_dashes_if_ever_present():
    assert _compact_pid("6941-1647-05-000") == "6941164705000"


def test_rollback_block_never_invents_a_zero_or_missing_deferral():
    assert build_rollback_block({"deferred_value": 0, "full_value": 100.0}) is None
    assert build_rollback_block({"deferred_value": None, "full_value": 100.0}) is None
    assert build_rollback_block({"deferred_value": 50.0, "full_value": 0}) is None


def test_rollback_block_uses_the_layers_own_taxable_value_directly():
    # real sampled row: land $72,092 + bldg $214,881 = full $286,973; TOTAL_PROP_VALUE
    # (already reduced) $247,353; TOTAL_DEFERRED_VALUE $39,620 == full - taxable exactly.
    # Unlike Durham, taxable_value is NOT derived by subtraction -- it's the layer's own
    # TOTAL_PROP_VALUE field, passed straight through.
    got = build_rollback_block({
        "deferred_value": 39620.0, "full_value": 72092.0 + 214881.0,
        "taxable_value": 247353.0,
        "use_value_deferred": 39620.0, "historic_value_deferred": 0,
    })
    assert got["deferred_value"] == 39620.0
    assert got["full_value"] == 286973.0
    assert got["taxable_value"] == 247353.0
    assert got["full_value"] - got["taxable_value"] == got["deferred_value"]
    assert got["basis"] == "present_use_deferral"
    assert got["county"] == "Hertford" and got["state"] == "NC"
    assert got["rollback_years"] == 4
    assert got["source_key"] == "enrichment_hertford_rollback_exposure"
    assert got["match_method"] == "reid"


def test_rollback_block_falls_back_to_subtraction_when_taxable_value_is_absent():
    # defensive path only -- fetch_deferrals always supplies taxable_value live, but
    # build_rollback_block must not crash if a caller omits it.
    got = build_rollback_block({"deferred_value": 100.0, "full_value": 500.0})
    assert got["taxable_value"] == 400.0


def test_rollback_block_never_yields_a_negative_taxable_value():
    # defensive: a corrupt/stale read where deferred > full must not be trusted blindly.
    assert build_rollback_block({"deferred_value": 600.0, "full_value": 500.0}) is None


def test_rollback_block_is_flag_only_safe():
    """A flag-only rollback_exposure block (e.g. a statewide presentval-style sweep's Y marker,
    deferred_value=None) must NOT block this producer's own real-dollar join -- _already_done
    only trusts a real deferred_value, same convention every sibling in this family uses."""
    assert not _already_done({"rollback_exposure": {"presentval": "Y", "deferred_value": None}})


def test_is_hertford_nc_requires_the_right_county_and_state():
    assert _is_hertford_nc(_li("6941164705000"))
    assert not _is_hertford_nc(_li("6941164705000", county="Martin"))
    assert not _is_hertford_nc(_li("6941164705000", state="SC"))


@pytest.mark.asyncio
async def test_a_matched_parcel_gets_rollback_exposure(monkeypatch):
    import foreclosure_scraper.enrichment_hertford_rollback_exposure as mod

    async def _fake_fetch(client):
        return {"6941164705000": {"deferred_value": 39620.0, "full_value": 286973.0,
                                   "taxable_value": 247353.0}}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("6941164705000")
    stats = await enrich_hertford_rollback_exposure([li])
    assert stats["matched"] == 1
    assert li.raw["rollback_exposure"]["deferred_value"] == 39620.0


@pytest.mark.asyncio
async def test_a_parcel_with_no_hit_gets_no_fabricated_record(monkeypatch):
    import foreclosure_scraper.enrichment_hertford_rollback_exposure as mod

    async def _fake_fetch(client):
        return {}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("6941164705000")
    await enrich_hertford_rollback_exposure([li])
    assert "rollback_exposure" not in li.raw


@pytest.mark.asyncio
async def test_an_existing_rollback_record_is_never_re_targeted(monkeypatch):
    import foreclosure_scraper.enrichment_hertford_rollback_exposure as mod
    called = {"n": 0}

    async def _fake_fetch(client):
        called["n"] += 1
        return {}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("6941164705000", raw={"rollback_exposure": {"deferred_value": 1.0}})
    stats = await enrich_hertford_rollback_exposure([li])
    assert stats["eligible"] == 0
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_disabled_via_env_short_circuits(monkeypatch):
    import foreclosure_scraper.enrichment_hertford_rollback_exposure as mod

    monkeypatch.setattr(mod, "ENABLED", False)
    li = _li("6941164705000")
    stats = await enrich_hertford_rollback_exposure([li])
    assert stats == {"eligible": 0, "deferred_pins": 0, "matched": 0, "fetch_errors": 0}
