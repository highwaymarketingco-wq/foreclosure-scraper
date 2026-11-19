"""Yancey County NC HCCOG-hosted YanceyCountyBaseData Parcels layer "AG_LAND_VA" field ->
raw['rollback_exposure']. Values below match real rows read live 2026-11-19 (PIN
"080400683856000": CURRENT_LA $146,600 + CURRENT_BL $276,400 = full $423,000; AG_LAND_VA
$90,024, CURRENT_TO $366,424 == AG_LAND_VA + CURRENT_BL exactly) -- not invented."""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.enrichment_yancey_rollback_exposure import (
    _already_done, _compact_pid, _is_yancey_nc, build_rollback_block,
    enrich_yancey_rollback_exposure,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(parcel_id, county="Yancey", state="NC", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state=state, owner_name="OWNER", parcel_id=parcel_id,
                   first_seen=now, last_seen=now, raw=kw.pop("raw", {}), **kw)


def test_compact_pid_is_a_no_op_on_an_already_bare_pin():
    assert _compact_pid("081002651917000") == "081002651917000"
    assert _compact_pid(None) == ""


def test_compact_pid_strips_dashes_on_the_one_known_outlier_board_row():
    assert _compact_pid("0800-0147-8924-000") == "080001478924000"


def test_rollback_block_never_invents_a_zero_or_missing_deferral():
    assert build_rollback_block({"deferred_value": 0, "full_value": 100.0}) is None
    assert build_rollback_block({"deferred_value": None, "full_value": 100.0}) is None
    assert build_rollback_block({"deferred_value": 50.0, "full_value": 0}) is None


def test_rollback_block_derives_taxable_value_exactly_from_the_two_literal_fields():
    # real sampled row: CURRENT_LA $146,600 + CURRENT_BL $276,400 = full $423,000;
    # AG_LAND_VA $90,024 -> deferred = land - ag = $56,576; taxable = full - deferred = $366,424
    # == the layer's own CURRENT_TO on this row (AG_LAND_VA + CURRENT_BL), confirming the fetch
    # function computed deferred/full the same way build_rollback_block expects.
    got = build_rollback_block({
        "deferred_value": 146600.0 - 90024.0, "full_value": 146600.0 + 276400.0,
        "land_class": "A",
    })
    assert got["deferred_value"] == 56576.0
    assert got["full_value"] == 423000.0
    assert got["taxable_value"] == 423000.0 - 56576.0
    assert got["taxable_value"] == 366424.0  # == real CURRENT_TO read live on this PIN
    assert got["basis"] == "present_use_deferral"
    assert got["land_class"] == "A"
    assert got["county"] == "Yancey" and got["state"] == "NC"
    assert got["rollback_years"] == 4
    assert got["source_key"] == "enrichment_yancey_rollback_exposure"


def test_rollback_block_never_yields_a_negative_taxable_value():
    # defensive: a corrupt/stale read where deferred > full must not be trusted blindly.
    assert build_rollback_block({"deferred_value": 600.0, "full_value": 500.0}) is None


def test_rollback_block_is_flag_only_safe():
    """A flag-only rollback_exposure block (e.g. a statewide presentval-style sweep's Y marker,
    deferred_value=None) must NOT block this producer's own real-dollar join -- _already_done
    only trusts a real deferred_value, same convention every sibling in this family uses."""
    assert not _already_done({"rollback_exposure": {"presentval": "Y", "deferred_value": None}})


def test_is_yancey_nc_requires_the_right_county_and_state():
    assert _is_yancey_nc(_li("081002651917000"))
    assert not _is_yancey_nc(_li("081002651917000", county="Mitchell"))
    assert not _is_yancey_nc(_li("081002651917000", state="SC"))


@pytest.mark.asyncio
async def test_a_matched_parcel_gets_rollback_exposure(monkeypatch):
    import foreclosure_scraper.enrichment_yancey_rollback_exposure as mod

    async def _fake_fetch(client):
        return {"081002651917000": {"deferred_value": 56576.0, "full_value": 423000.0,
                                     "land_class": "A"}}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("081002651917000")
    stats = await enrich_yancey_rollback_exposure([li])
    assert stats["matched"] == 1
    assert li.raw["rollback_exposure"]["deferred_value"] == 56576.0


@pytest.mark.asyncio
async def test_a_parcel_with_no_hit_gets_no_fabricated_record(monkeypatch):
    import foreclosure_scraper.enrichment_yancey_rollback_exposure as mod

    async def _fake_fetch(client):
        return {}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("081002651917000")
    await enrich_yancey_rollback_exposure([li])
    assert "rollback_exposure" not in li.raw


@pytest.mark.asyncio
async def test_an_existing_rollback_record_is_never_re_targeted(monkeypatch):
    import foreclosure_scraper.enrichment_yancey_rollback_exposure as mod
    called = {"n": 0}

    async def _fake_fetch(client):
        called["n"] += 1
        return {}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("081002651917000", raw={"rollback_exposure": {"deferred_value": 1.0}})
    stats = await enrich_yancey_rollback_exposure([li])
    assert stats["eligible"] == 0
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_disabled_via_env_short_circuits(monkeypatch):
    import foreclosure_scraper.enrichment_yancey_rollback_exposure as mod

    monkeypatch.setattr(mod, "ENABLED", False)
    li = _li("081002651917000")
    stats = await enrich_yancey_rollback_exposure([li])
    assert stats == {"eligible": 0, "deferred_pins": 0, "matched": 0, "fetch_errors": 0}
