"""Craven County NC gis.cravencountync.gov mMaps/Property MapServer (layers 17 TaxTable, 6
Parcels in Use Value Program) -> raw['two_year_delinquent']/raw['multi_year_delinquent_tax']/
raw['tax_aging_surfaced']/raw['rollback_exposure'].

The field names and values in these pure-function tests match REAL rows read live 2026-11-17
(e.g. PID "6-064   -091"/2017, owner "NOONAN, ROBERT C - EXECUTOR OF THE", $3,311.43 still
owed; PARCEL_ID "2-018   -013", owner "NORMAN, CATHY WHITFORD", DEFERRED_VALUE $65,290 of
$98,320 MARKET_VALUE) -- not invented.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_nc.craven_tax_table import (
    CHECKED_KEY, SLUG, _compact_pid, _is_craven_nc, build_aging_block, build_multiyear_block,
    build_rollback_block, build_two_year_block, enrich_craven_tax, _matured_cutoff_year,
)


def _li(parcel_id, owner_name="OWNER", county="Craven", state="NC", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state=state, owner_name=owner_name, parcel_id=parcel_id,
                   first_seen=now, last_seen=now, raw=kw.pop("raw", {}), **kw)


# ---------------------------------------------------------------------------
# _compact_pid: the real board<->GIS parcel join transform
# ---------------------------------------------------------------------------

def test_compact_pid_strips_dashes_and_spaces_like_the_real_board_join():
    assert _compact_pid("6-213-L -213") == "6213L213"
    assert _compact_pid("7-104-A -038") == "7104A038"
    assert _compact_pid("6-064   -091") == "6064091"
    assert _compact_pid(None) == ""


# ---------------------------------------------------------------------------
# _matured_cutoff_year: NC's Jan 6-of-year+1 rule, never the current not-yet-due year
# ---------------------------------------------------------------------------

def test_matured_cutoff_year_excludes_the_current_not_yet_due_levy():
    # 2026-11-17: the 2026 levy isn't delinquent until 2027-01-06, so 2025 is the newest
    # matured year.
    assert _matured_cutoff_year(date(2026, 11, 17)) == 2025


def test_matured_cutoff_year_rolls_back_in_early_january():
    # 2027-01-02: even 2025's delinquency date (2026-01-06) has passed, but 2026's own
    # (2027-01-06) has not yet -- the newest matured year is still 2025.
    assert _matured_cutoff_year(date(2027, 1, 2)) == 2025


# ---------------------------------------------------------------------------
# build_* : never invents a record off an empty/zero input
# ---------------------------------------------------------------------------

def test_two_year_block_always_carries_the_real_count():
    assert build_two_year_block([2017])["is_two_year_plus"] is False
    got = build_two_year_block([2017, 2018, 2019])
    assert got["is_two_year_plus"] is True
    assert got["years_delinquent"] == 3
    assert got["source"] == SLUG


def test_multiyear_block_needs_two_real_matured_years():
    assert build_multiyear_block([2017], 100.0) is None
    got = build_multiyear_block([2017, 2018], 3411.51)
    assert got["years_delinquent"] == 2
    assert got["total_due"] == 3411.51


def test_aging_block_fires_on_a_single_matured_year():
    assert build_aging_block([], 0) is None
    got = build_aging_block([2017], 3311.43)
    assert got["status"] == "delinquent"
    assert got["years_delinquent"] == 1
    assert got["latest_delinquent_year"] == 2017
    assert got["total_due"] == 3311.43


def test_rollback_block_never_invents_a_zero_or_missing_deferral():
    assert build_rollback_block({"deferred_value": 0}) is None
    assert build_rollback_block({"deferred_value": None}) is None
    got = build_rollback_block({"deferred_value": 65290.0, "market_value": 98320,
                                "approval_year": 1999})
    assert got["deferred_value"] == 65290.0
    assert got["county"] == "Craven" and got["state"] == "NC"
    assert got["rollback_years"] == 4
    assert got["match_method"] == "parcel_id"
    assert got["market_value"] == 98320
    assert got["puv_approval_year"] == 1999


# ---------------------------------------------------------------------------
# _is_craven_nc / eligibility
# ---------------------------------------------------------------------------

def test_is_craven_nc_requires_the_right_county_and_state():
    assert _is_craven_nc(_li("6213L213"))
    assert not _is_craven_nc(_li("6213L213", county="Durham"))
    assert not _is_craven_nc(_li("6213L213", state="SC"))


# ---------------------------------------------------------------------------
# enrich_craven_tax: the join logic, against a stubbed registry (no live network)
# ---------------------------------------------------------------------------

async def _stub_registries(monkeypatch, delinquent_by_pid, rollback_by_pid):
    import foreclosure_scraper.scrapers.counties_nc.craven_tax_table as mod

    async def _fake_delinquent(c, cutoff_year=None):
        return delinquent_by_pid

    async def _fake_rollback(c):
        return rollback_by_pid

    monkeypatch.setattr(mod, "fetch_delinquent_by_pid", _fake_delinquent)
    monkeypatch.setattr(mod, "fetch_rollback_by_pid", _fake_rollback)


@pytest.mark.asyncio
async def test_a_matched_parcel_gets_all_four_columns_when_eligible(monkeypatch):
    await _stub_registries(
        monkeypatch,
        delinquent_by_pid={"6064091": {"years": [2017, 2018], "total_due": 500.0,
                                       "source": SLUG}},
        rollback_by_pid={"6064091": {"deferred_value": 1000.0, "market_value": 5000.0,
                                     "approval_year": 2001}},
    )
    li = _li("6-064   -091")
    stats = await enrich_craven_tax([li])
    assert stats["matched_delinquent"] == 1
    assert stats["matched_multiyear"] == 1
    assert stats["matched_rollback"] == 1
    assert li.raw["two_year_delinquent"]["is_two_year_plus"] is True
    assert li.raw["multi_year_delinquent_tax"]["years_delinquent"] == 2
    assert li.raw["tax_aging_surfaced"]["status"] == "delinquent"
    assert li.raw["rollback_exposure"]["deferred_value"] == 1000.0
    assert li.raw[SLUG]["checked_at"]


@pytest.mark.asyncio
async def test_a_one_year_only_parcel_gets_the_checked_shadow_key_not_multiyear(monkeypatch):
    await _stub_registries(
        monkeypatch,
        delinquent_by_pid={"6064091": {"years": [2017], "total_due": 50.0, "source": SLUG}},
        rollback_by_pid={},
    )
    li = _li("6-064   -091")
    await enrich_craven_tax([li])
    assert "multi_year_delinquent_tax" not in li.raw
    assert li.raw[CHECKED_KEY] is True
    assert li.raw["tax_aging_surfaced"]["years_delinquent"] == 1  # still a real one-year hit


@pytest.mark.asyncio
async def test_a_parcel_with_no_hit_gets_no_fabricated_record(monkeypatch):
    await _stub_registries(monkeypatch, delinquent_by_pid={}, rollback_by_pid={})
    li = _li("6-064   -091")
    await enrich_craven_tax([li])
    assert "two_year_delinquent" not in li.raw
    assert "multi_year_delinquent_tax" not in li.raw
    assert "tax_aging_surfaced" not in li.raw
    assert "rollback_exposure" not in li.raw
    assert li.raw[SLUG]["checked_at"]  # still marked as having been looked at


@pytest.mark.asyncio
async def test_a_non_craven_row_is_never_targeted(monkeypatch):
    await _stub_registries(monkeypatch, delinquent_by_pid={}, rollback_by_pid={})
    li = _li("6064091", county="Durham")
    stats = await enrich_craven_tax([li])
    assert stats["eligible"] == 0
    assert SLUG not in li.raw


@pytest.mark.asyncio
async def test_an_already_checked_row_is_never_re_targeted(monkeypatch):
    await _stub_registries(monkeypatch, delinquent_by_pid={}, rollback_by_pid={})
    li = _li("6064091", raw={SLUG: {"checked_at": "2026-01-01"}})
    stats = await enrich_craven_tax([li])
    assert stats["eligible"] == 0
