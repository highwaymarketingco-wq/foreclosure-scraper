"""enrichment_greenville_rollback_exposure: a pure, no-network restatement of Greenville SC's
own parcel-CAMA ROLLBK field (already bulk-pulled by parcel_cache.py's existing weekly
Greenville refresh, since this session added "rollback_tax": "ROLLBK" to its field map) into
the shared raw['rollback_exposure'] contract.

The dollar figures below are read straight off the LIVE county layer
(arcgis3/.../GreenvilleNJ/QueryLayers/MapServer/0, 2026-10-20), not invented -- see this
module's own docstring for the full live-verification record, including the independent
confirmation against the county's own per-parcel bill page ("Total Rollback:").
"""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_greenville_rollback_exposure as mod

#: live-pulled 2026-10-20, PIN 0238020101000 (AGRICULTURAL, 49 acres).
_REAL_CACHED_GAP = {
    "owner": "TEST OWNER", "market_value": 449820.0, "tax_value": 133720.0,
    "rollback_tax": 7866.83, "acreage": 49.0,
}
#: live-pulled 2026-10-20, PIN 0132000100300 -- ROLLBK is nonzero even though the parcel is
#: ALREADY taxed at its full market value this cycle (market_value == tax_value): proves the
#: gate must be rollback_tax>0 itself, not the value gap.
_REAL_CACHED_NO_GAP = {
    "owner": "LAS CRUCES INVESTMENT LLC", "market_value": 806400.0, "tax_value": 806400.0,
    "rollback_tax": 5384.0, "acreage": 12.6,
}


def _lead(**kw) -> Listing:
    now = datetime.utcnow()
    base = dict(source="test", source_url="https://example.test",
               listing_type=ListingType.DISTRESSED, property_kind=PropertyKind.SINGLE_FAMILY,
               first_seen=now, last_seen=now)
    base.update(kw)
    return Listing(**base)


def test_build_block_reproduces_the_real_rollback_and_the_value_gap():
    rec = mod.build_block(_REAL_CACHED_GAP)
    assert rec["estimated_rollback"] == 7866.83
    assert rec["deferred_value"] == 316100.0
    assert rec["basis"] == "present_use_deferral"
    assert rec["county"] == "Greenville" and rec["state"] == "SC"
    assert rec["rollback_years"] == 3
    assert rec["match_method"] == "parcel"
    assert rec["estimate_is_floor"] is False


def test_build_block_keeps_the_rollback_without_a_deferred_value_when_there_is_no_gap():
    # The real Greenville signature: ROLLBK can be nonzero even when market_value == tax_value
    # this cycle. deferred_value must never be invented as 0 or a negative number.
    rec = mod.build_block(_REAL_CACHED_NO_GAP)
    assert rec["estimated_rollback"] == 5384.0
    assert "deferred_value" not in rec


def test_build_block_never_invents_a_rollback_when_the_field_is_blank_or_zero():
    assert mod.build_block({"rollback_tax": 0, "market_value": 100000.0, "tax_value": 1.0}) is None
    assert mod.build_block({"rollback_tax": None}) is None
    assert mod.build_block({}) is None


def test_enrich_stamps_a_matched_row_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(mod.parcel_cache, "lookup",
                        lambda county, pid, state=None: dict(_REAL_CACHED_GAP))
    li = _lead(county="Greenville", state="SC", parcel_id="0238020101000", raw={})
    stats = mod.enrich_greenville_rollback_exposure([li])
    assert stats["targets"] == 1 and stats["matched"] == 1
    rec = li.raw["rollback_exposure"]
    assert rec["estimated_rollback"] == 7866.83 and rec["match_method"] == "parcel"

    # Idempotent: a second pass must not re-run (already_done gate) or change the stamp.
    stats2 = mod.enrich_greenville_rollback_exposure([li])
    assert stats2["targets"] == 0
    assert li.raw["rollback_exposure"] == rec


def test_a_cache_miss_is_left_untouched(monkeypatch):
    monkeypatch.setattr(mod.parcel_cache, "lookup", lambda county, pid, state=None: None)
    li = _lead(county="Greenville", state="SC", parcel_id="9999999999999", raw={})
    stats = mod.enrich_greenville_rollback_exposure([li])
    assert stats["targets"] == 1 and stats["matched"] == 0 and stats["cache_miss"] == 1
    assert "rollback_exposure" not in li.raw


def test_a_zero_rollback_cache_hit_is_left_untouched(monkeypatch):
    monkeypatch.setattr(mod.parcel_cache, "lookup",
                        lambda county, pid, state=None: {"market_value": 1.0, "tax_value": 1.0,
                                                          "rollback_tax": 0.0})
    li = _lead(county="Greenville", state="SC", parcel_id="0001000100100", raw={})
    stats = mod.enrich_greenville_rollback_exposure([li])
    assert stats["targets"] == 1 and stats["matched"] == 0 and stats["no_rollback"] == 1
    assert "rollback_exposure" not in li.raw


def test_a_row_with_no_parcel_id_is_never_queried(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("must not query the cache without a parcel id")
    monkeypatch.setattr(mod.parcel_cache, "lookup", _boom)
    li = _lead(county="Greenville", state="SC", parcel_id="", raw={})
    stats = mod.enrich_greenville_rollback_exposure([li])
    assert stats["targets"] == 0 and stats["no_parcel"] == 1


def test_a_non_greenville_row_is_never_touched(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("must not query the cache for another county")
    monkeypatch.setattr(mod.parcel_cache, "lookup", _boom)
    li = _lead(county="Spartanburg", state="SC", parcel_id="123-45-67-890", raw={})
    stats = mod.enrich_greenville_rollback_exposure([li])
    assert stats["targets"] == 0


def test_a_row_that_already_carries_rollback_exposure_from_another_source_is_left_alone(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("must not query the cache when already_done")
    monkeypatch.setattr(mod.parcel_cache, "lookup", _boom)
    existing = {"estimated_rollback": 1.0, "county": "Buncombe"}
    li = _lead(county="Greenville", state="SC", parcel_id="0238020101000",
              raw={"rollback_exposure": existing})
    stats = mod.enrich_greenville_rollback_exposure([li])
    assert stats["targets"] == 0
    assert li.raw["rollback_exposure"] == existing


def test_disabled_by_env_is_a_pure_noop(monkeypatch):
    monkeypatch.setattr(mod, "ENABLED", False)
    def _boom(*a, **kw):
        raise AssertionError("must not query the cache when disabled")
    monkeypatch.setattr(mod.parcel_cache, "lookup", _boom)
    li = _lead(county="Greenville", state="SC", parcel_id="0238020101000", raw={})
    stats = mod.enrich_greenville_rollback_exposure([li])
    assert stats["targets"] == 0
    assert "rollback_exposure" not in li.raw
