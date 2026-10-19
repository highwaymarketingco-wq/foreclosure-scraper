"""enrichment_rollback_deferral's Wake NC path: a present-use (AGR/FOR) candidate list from NC
OneMap, confirmed to a real dollar deferred value by one live Account.asp fetch per matched
board lead (no bulk layer carries the value itself for Wake -- module docstring).

Offline: `_fetch_wake_candidates` and `_wake_live_topup` are monkeypatched, same convention
test_rollback_deferral.py already uses for Buncombe/Anderson/Mecklenburg. The dollar figures in
`_REAL_167151_RECORD` are read straight off the live Account.asp page for PIN 1797953869 / REID
0167151 (tax_lien_wake module docstring; captured live 2026-10-18), not invented.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_rollback_deferral as mod

PIN = "1797953869"
REID = "0167151"

#: the real Account.asp + bill-history figures for this parcel (module docstring): market
#: $1,801,100, present-use $29,987, deferred (the difference) $1,771,113, current ordinary bill
#: $197.79 -- rate 197.79 / 29987 = 0.0065966..., inside the sane band.
_REAL_167151_RECORD = {
    "deferred_value": 1771113.0, "use_value": 29987.0, "real_value": 1801100.0,
    "rollback_years": 4, "estimate_is_floor": True, "basis": "present_use_deferral",
    "county": "Wake", "state": "NC",
    "source": "Wake County Real Estate Data, Account.asp Tax-Relief section (Total Deferred Value)",
    "source_key": "wake_account_detail", "reid": REID,
    "effective_tax_rate": round(197.79 / 29987.0, 6), "tax_rate_source": "parcel_bill",
    "annual_deferred_tax": round(1771113.0 * (197.79 / 29987.0), 2),
    "tax_year": 2026,
    "estimated_rollback": round(round(1771113.0 * (197.79 / 29987.0), 2) * 4, 2),
}


def _lead(**kw) -> Listing:
    now = datetime.utcnow()
    base = dict(source="test", source_url="https://example.test",
               listing_type=ListingType.DISTRESSED, property_kind=PropertyKind.SINGLE_FAMILY,
               first_seen=now, last_seen=now)
    base.update(kw)
    return Listing(**base)


def _run(listings):
    return asyncio.run(mod.enrich_with_rollback_exposure(listings))


def _patch(monkeypatch, candidates=None, topup=None):
    async def fake_candidates(c):
        return candidates or []

    async def fake_topup(c, reid):
        return (topup or {}).get(reid)

    monkeypatch.setattr(mod, "_fetch_buncombe", lambda c: _empty())
    monkeypatch.setattr(mod, "_fetch_anderson", lambda c: _empty())
    monkeypatch.setattr(mod, "_fetch_mecklenburg_candidates", lambda c: _empty_list())
    monkeypatch.setattr(mod, "_fetch_wake_candidates", fake_candidates)
    monkeypatch.setattr(mod, "_wake_live_topup", fake_topup)


async def _empty():
    return {}


async def _empty_list():
    return []


def _candidate(pin=PIN, reid=REID, code="AGR"):
    return {"parno": pin, "altparno": reid, "parusecode": code}


def test_wake_index_bridges_pin_to_reid_from_the_candidate_list():
    idx = mod._wake_index([_candidate()])
    assert idx[PIN] == {"reid": REID, "parusecode": "AGR"}


def test_a_matched_lead_gets_the_live_confirmed_record(monkeypatch):
    _patch(monkeypatch, candidates=[_candidate()], topup={REID: dict(_REAL_167151_RECORD)})
    li = _lead(county="Wake", state="NC", parcel_id=PIN)
    stats = _run([li])
    assert stats["matched_wake"] == 1 and stats["wake_live_confirmed"] == 1
    rec = li.raw["rollback_exposure"]
    assert rec["deferred_value"] == 1771113.0 and rec["match_method"] == "parcel"
    assert rec["estimated_rollback"] == _REAL_167151_RECORD["estimated_rollback"]
    assert stats["with_estimate"] == 1


def test_a_false_positive_agr_candidate_with_no_real_deferral_stamps_nothing(monkeypatch):
    """Account.asp answered but showed no Total Deferred Value -- _wake_live_topup itself
    returns None for this (tax_lien_wake module docstring: 'never guess a deferred parcel into
    existence'); the enrichment must not stamp a placeholder either."""
    _patch(monkeypatch, candidates=[_candidate()], topup={})  # topup returns None for REID
    li = _lead(county="Wake", state="NC", parcel_id=PIN)
    stats = _run([li])
    assert stats["matched_wake"] == 0 and "rollback_exposure" not in li.raw


def test_a_lead_outside_the_candidate_list_is_untouched(monkeypatch):
    _patch(monkeypatch, candidates=[_candidate()], topup={REID: dict(_REAL_167151_RECORD)})
    li = _lead(county="Wake", state="NC", parcel_id="9999999999")
    stats = _run([li])
    assert stats["matched_wake"] == 0 and "rollback_exposure" not in li.raw


def test_two_board_leads_on_the_same_reid_each_get_stamped_from_one_fetch(monkeypatch):
    calls = []

    async def counting_topup(c, reid):
        calls.append(reid)
        return dict(_REAL_167151_RECORD)

    _patch(monkeypatch, candidates=[_candidate()])
    monkeypatch.setattr(mod, "_wake_live_topup", counting_topup)
    a = _lead(county="Wake", state="NC", parcel_id=PIN)
    b = _lead(county="Wake", state="NC", parcel_id=PIN)
    stats = _run([a, b])
    assert stats["matched_wake"] == 2
    assert calls == [REID]            # fetched once, stamped onto both leads
    assert a.raw["rollback_exposure"]["deferred_value"] == 1771113.0
    assert b.raw["rollback_exposure"]["deferred_value"] == 1771113.0


def test_non_wake_counties_never_trigger_the_wake_fetch_at_all(monkeypatch):
    called = []

    async def tracking_candidates(c):
        called.append(True)
        return []

    _patch(monkeypatch)
    monkeypatch.setattr(mod, "_fetch_wake_candidates", tracking_candidates)
    li = _lead(county="Mecklenburg", state="NC", parcel_id="00716203")
    _run([li])
    assert called == []
