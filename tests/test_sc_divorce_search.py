"""SC divorce enricher: a failed search must never read as "no divorce".

Found 2026-09-18 while diagnosing a slow backfill. _search_one used to
`continue` on timeout / non-200 / bad JSON, so an unsearched owner came back
as an empty case list and enrich_sc_divorce stamped raw['divorce'] with
case_count 0 (30-day refresh window). errors always read 0.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper import enrichment_sc_divorce as m
from foreclosure_scraper.models import Listing, ListingType


class _Resp:
    def __init__(self, status=200, payload=None, bad_json=False):
        self.status_code = status
        self._payload = [] if payload is None else payload
        self._bad = bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload


class _FakeSession:
    """Async context manager whose post() is scripted per call."""
    def __init__(self, script):
        self.script = script          # callable(payload) -> _Resp or Exception
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return _Resp()

    async def post(self, url, json=None, **k):
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            out = self.script(json)
            if isinstance(out, Exception):
                raise out
            return out
        finally:
            self.in_flight -= 1


def _lead(i, owner="SMITH JOHN"):
    return Listing(source="x", source_url=f"u{i}", listing_type=ListingType.TAX_LIEN,
                   state="SC", county="Spartanburg", owner_name=owner, parcel_id=f"P{i}")


def _case_row():
    return {"CaseId": "2020DR4200001", "CaseDescription": "JOHN SMITH vs. MARY SMITH",
            "CaseInitialFilingDate": "2020-01-02T00:00:00", "CaseCategory": "110 - Divorce",
            "LocationName": "Spartanburg", "ParticipantRole": "Petitioner"}


def test_search_one_raises_on_timeout_non200_and_bad_json():
    for bad in (asyncio.TimeoutError(), _Resp(status=503), _Resp(bad_json=True), _Resp(payload={"err": 1})):
        s = _FakeSession(lambda p, bad=bad: bad)
        with pytest.raises(m._IncompleteSearch):
            asyncio.run(m._search_one(s, {}, "SMITH", "JOHN", 1046))


def test_search_one_empty_list_is_a_definitive_no_not_an_error():
    s = _FakeSession(lambda p: _Resp(payload=[]))
    assert asyncio.run(m._search_one(s, {}, "SMITH", "JOHN", 1046)) == []


def _run(monkeypatch, listings, script, concurrency=4):
    fake = _FakeSession(script)
    monkeypatch.setattr(m, "AsyncSession", lambda **k: fake)

    async def _hs(session):
        return "tok"
    monkeypatch.setattr(m, "_handshake", _hs)
    monkeypatch.setattr(m, "_CONCURRENCY", concurrency)
    stats = asyncio.run(m.enrich_sc_divorce(listings, max_lookups=len(listings)))
    return stats, fake


def test_failed_search_leaves_lead_unstamped_and_counts_an_error(monkeypatch):
    leads = [_lead(1), _lead(2)]
    stats, _ = _run(monkeypatch, leads, lambda p: _Resp(status=503))
    assert stats["searched"] == 0
    assert stats["errors"] == 2
    assert all("divorce" not in (li.raw or {}) for li in leads), \
        "an unsearched lead was stamped as checked"


def test_good_empty_answer_stamps_zero_cases(monkeypatch):
    leads = [_lead(1)]
    stats, _ = _run(monkeypatch, leads, lambda p: _Resp(payload=[]))
    assert stats["searched"] == 1 and stats["errors"] == 0
    assert leads[0].raw["divorce"]["case_count"] == 0


def test_worker_pool_covers_every_target_once_and_stays_bounded(monkeypatch):
    leads = [_lead(i) for i in range(25)]
    stats, fake = _run(monkeypatch, leads, lambda p: _Resp(payload=[]), concurrency=4)
    assert stats["searched"] == 25
    assert sum(1 for li in leads if "divorce" in li.raw) == 25
    assert fake.calls == 25 * len(m._DIVORCE_CATEGORIES)   # each lead searched exactly once
    assert 1 < fake.max_in_flight <= 4


def test_hit_is_recorded(monkeypatch):
    leads = [_lead(1)]
    stats, _ = _run(monkeypatch, leads,
                    lambda p: _Resp(payload=[_case_row()]) if p and any(
                        d.get("PACaseCategoryId") == 1062 for d in p if isinstance(d, dict)) else _Resp(payload=[]))
    assert stats["with_divorce"] == 1
    assert leads[0].raw["divorce"]["case_count"] >= 1


def test_consecutive_failures_abort_the_run(monkeypatch):
    leads = [_lead(i) for i in range(40)]
    stats, _ = _run(monkeypatch, leads, lambda p: _Resp(status=500), concurrency=1)
    assert stats.get("aborted_throttled") is True
    assert stats["errors"] == 12          # stops at the 12-failure guard, not all 40
