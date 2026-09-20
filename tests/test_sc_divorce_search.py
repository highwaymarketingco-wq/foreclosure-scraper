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


# ---- ordering: likely-a-person first, never a filter -------------------------

def _stamped(i, source, hit):
    li = _lead(i, owner="DOE JANE")
    li.source = source
    li.raw = {"divorce": {"fetched_at": "2026-09-01T00:00:00+00:00", "case_count": 1 if hit else 0}}
    return li


def _pending(i, source, owner="DOE JANE"):
    li = _lead(i, owner=owner)
    li.source = source
    return li


def test_source_hit_rates_need_a_minimum_sample():
    rows = [_stamped(i, "big_src", i % 2 == 0) for i in range(40)] + \
           [_stamped(100 + i, "tiny_src", True) for i in range(5)]
    rates = m._source_hit_rates(rows, None)
    assert rates == {"big_src": 0.5}          # tiny_src (5 < 30) is unknown, not 100%


def test_pending_leads_order_by_source_yield_and_entities_sink(monkeypatch):
    rich = [_stamped(i, "tax_roll", i % 4 == 0) for i in range(40)]      # 25% hit rate
    poor = [_stamped(500 + i, "lien_registry", False) for i in range(40)]  # 0%
    p_poor = _pending(900, "lien_registry")
    p_unseen_person = _pending(901, "brand_new_src")
    p_unseen_entity = _pending(902, "brand_new_src", owner="ACME HOLDINGS LLC")
    p_rich = _pending(903, "tax_roll")
    pending = [p_poor, p_unseen_entity, p_unseen_person, p_rich]

    order = []
    async def fake_search(session, headers, last, first, county_code):
        order.append(last)
        return []
    fake = _FakeSession(lambda p: _Resp(payload=[]))
    monkeypatch.setattr(m, "AsyncSession", lambda **k: fake)
    async def _hs(session): return "tok"
    monkeypatch.setattr(m, "_handshake", _hs)
    monkeypatch.setattr(m, "_search_one", fake_search)
    monkeypatch.setattr(m, "_CONCURRENCY", 1)
    p_poor.owner_name = "POORMAN PAT"
    p_unseen_person.owner_name = "UNSEENSON URI"
    p_unseen_entity.owner_name = "ACME HOLDINGS LLC"
    p_rich.owner_name = "RICHARDSON RAY"
    stats = asyncio.run(m.enrich_sc_divorce(rich + poor + pending, max_lookups=4))
    assert stats["searched"] == 4, "ordering must never drop a lead"
    # rich source first; an unseen source's person before its entity; the
    # 0%-yield source's person last of all (below even the entity-discounted
    # unseen prior: 0.10 * 0.2 = 0.02 > 0.0).
    assert order == ["RICHARDSON", "UNSEENSON", "ACME", "POORMAN"], order


# ---- name order: GIS SURNAME-FIRST vs court/probate FIRST-LAST ----------------

import pytest as _pytest


@_pytest.mark.parametrize("owner,expected", [
    # county-GIS / tax roll: ALL-CAPS surname-first (unchanged behavior)
    ("BYRD SANDRA D", ("BYRD", "SANDRA")),
    ("SMITH JOHN C & MELINDA P", ("SMITH", "JOHN")),
    ("LOPEZ, JOSE G. SANCHEZ & SULLY L. SANCHEZ", ("LOPEZ", "JOSE")),
    ("ABBAD MIRIAM ALALI SAMI", ("ABBAD", "MIRIAM")),
    # court-party / probate notices: Title Case FIRST [MIDDLE] LAST (the bug)
    ("Krystal  Henderson", ("HENDERSON", "KRYSTAL")),
    ("Joshua D Smith", ("SMITH", "JOSHUA")),
    ("Susan Lee Meaders", ("MEADERS", "SUSAN")),
    ("Rhonda J. Hester Cassell", ("CASSELL", "RHONDA")),
    ("Rex Allen Chappell Jr", ("CHAPPELL", "REX")),
    ("Tina Lopez & John Lopez", ("LOPEZ", "TINA")),
    # a comma always means LAST, FIRST even in mixed case
    ("Roper, John A., Jr.", ("ROPER", "JOHN")),
    # degenerate input
    ("Madonna", ("MADONNA", "")),
    ("", ("", "")),
    (None, ("", "")),
])
def test_name_parts_reads_both_board_conventions(owner, expected):
    assert m._name_parts(owner) == expected


# ---- reset script: only stamps whose search actually differs -------------------

def test_reset_targets_only_wrong_order_stamps():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from reset_divorce_wrong_order import needs_reset

    def stamped(owner, county="Spartanburg", state="SC"):
        li = _lead(1, owner=owner)
        li.county, li.state = county, state
        li.raw = {"divorce": {"fetched_at": "2026-09-01T00:00:00+00:00", "case_count": 0}}
        return li

    assert needs_reset(stamped("Joshua D Smith")) is True          # was searched as JOSHUA/D
    assert needs_reset(stamped("BYRD SANDRA D")) is False           # GIS order: unchanged
    assert needs_reset(stamped("Roper, John A., Jr.")) is False     # comma: unchanged
    assert needs_reset(stamped("Madonna")) is False                 # single token: unchanged
    assert needs_reset(stamped("Acme Holdings LLC")) is False       # entity: stamp stands
    assert needs_reset(stamped("Joshua D Smith", county="Wake", state="NC")) is False   # out of scope
    unstamped = _lead(2, owner="Joshua D Smith")
    assert needs_reset(unstamped) is False                          # never searched: nothing to clear


def test_error_kinds_are_tallied_by_cause(monkeypatch):
    leads = [_lead(i) for i in range(3)]
    seq = iter([_Resp(status=503), asyncio.TimeoutError(), _Resp(bad_json=True)] * 12)
    stats, _ = _run(monkeypatch, leads, lambda p: next(seq), concurrency=1)
    kinds = stats["error_kinds"]
    assert stats["errors"] == sum(kinds.values()) == 3
    assert set(kinds) <= {"http_503", "TimeoutError", "bad_json"}, kinds


def test_error_kinds_absent_when_nothing_failed(monkeypatch):
    stats, _ = _run(monkeypatch, [_lead(1)], lambda p: _Resp(payload=[]))
    assert "error_kinds" not in stats
