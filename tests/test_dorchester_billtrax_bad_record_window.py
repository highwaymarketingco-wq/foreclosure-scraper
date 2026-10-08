"""Dorchester BillTrax: one bad record costs that record, not the 250 around it.

The API fails a whole search window when one record in it carries a malformed id
("... is not a valid 24 digit hex string"). The old recovery halved 2000 -> 1000 -> 500
-> 250 and skipped the 250 window (2026-10-08 VM run: offset 17,000). Windows can be split
by any factor that divides them, so the new recovery goes down to the one record.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_sc import dorchester_billtrax_delinquent_tax as mod

BAD = 1234
TOTAL = 3000


def _install(monkeypatch, bad=(BAD,)):
    calls: list[tuple[int, int]] = []
    sleeps: list[float] = []

    async def fake_fetch_page(client, template, page, page_size=mod.PAGE_SIZE):
        lo = page * page_size
        calls.append((lo, page_size))
        hi = min(lo + page_size, TOTAL)
        if any(lo <= b < hi for b in bad):
            raise ValueError("API HasErrors=true for /crm/api/payment/Search: "
                             "'0bad' is not a valid 24 digit hex string.")
        return [{"_i": i} for i in range(lo, hi)], TOTAL

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(mod, "_fetch_page", fake_fetch_page)
    monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)
    return calls, sleeps


def test_only_the_bad_record_is_skipped(monkeypatch):
    calls, sleeps = _install(monkeypatch)
    bills, total, skipped = asyncio.run(mod._fetch_range_with_recovery(None, {}, 0, 2000))
    got = {b["_i"] for b in bills}
    assert skipped == [(BAD, 1)]
    assert len(got) == 1999 and BAD not in got and got == set(range(2000)) - {BAD}
    assert total == TOTAL
    # every request is a window aligned to its own size (what PageNumberToFetch can express)
    assert all(lo % size == 0 for lo, size in calls)
    # the API's record-data error is deterministic: split at once, no backoff sleeps
    assert sleeps == []
    assert len(calls) < 40


def test_two_bad_records_in_one_window_each_cost_one(monkeypatch):
    _install(monkeypatch, bad=(17, 1990))
    bills, _total, skipped = asyncio.run(mod._fetch_range_with_recovery(None, {}, 0, 2000))
    assert sorted(skipped) == [(17, 1), (1990, 1)]
    assert len(bills) == 1998


def test_a_transient_error_is_still_retried_once(monkeypatch):
    attempts = {"n": 0}

    async def flaky(client, template, page, page_size=mod.PAGE_SIZE):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("connection reset")
        lo = page * page_size
        return [{"_i": i} for i in range(lo, lo + page_size)], TOTAL

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(mod, "_fetch_page", flaky)
    monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)
    bills, _t, skipped = asyncio.run(mod._fetch_range_with_recovery(None, {}, 2000, 2000))
    assert skipped == [] and len(bills) == 2000 and attempts["n"] == 2


def test_smallest_factor():
    assert [mod._smallest_factor(n) for n in (2000, 250, 125, 25, 5, 7, 49)] == [2, 2, 5, 5, 5, 7, 7]
