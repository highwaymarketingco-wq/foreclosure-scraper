"""CourtListener bankruptcy: the wall-clock budget is shared between the courts.

The gated run of 2026-10-08 stopped at exactly the 600 s budget with 3,386 of
4,579 dockets; the courts ran in order with one shared deadline, so the whole
cut fell on the last court (scb, South Carolina). Each court now gets a fair
share of what is left, and unused time rolls forward.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

from foreclosure_scraper.scrapers.national import courtlistener_bankruptcy as cb


def test_each_court_gets_a_fair_share_of_the_remaining_budget():
    seen: list[tuple[str, float, float]] = []

    async def fake_fetch_court(c, court, token, deadline=None):
        seen.append((court, time.monotonic(), deadline))
        return []

    async def _run():
        with patch.object(cb, "_fetch_court", new=fake_fetch_court), \
                patch.object(cb, "_load_token", return_value=None):
            return await cb.CourtListenerBankruptcy().fetch()

    start = time.monotonic()
    asyncio.run(_run())
    assert [s[0] for s in seen] == list(cb.COURTS)
    overall = start + cb.FETCH_BUDGET_S
    first_court, first_now, first_deadline = seen[0]
    # The first court may not spend the whole budget: a quarter of it (+ slack).
    assert first_deadline <= first_now + cb.FETCH_BUDGET_S / len(cb.COURTS) + 1.0
    assert first_deadline < overall - 1.0
    # The last court gets everything that is left.
    last_now, last_deadline = seen[-1][1], seen[-1][2]
    assert abs(last_deadline - overall) < 2.0
    assert last_deadline > last_now


def test_budget_covers_the_measured_corpus():
    # 229 pages measured 2026-10-08 at ~2.2 s/page is ~505 s; the old 600 s
    # left no room for the chapter fallback and a shared host throttle.
    assert cb.FETCH_BUDGET_S >= 780
    assert cb.CourtListenerBankruptcy.timeout_s > cb.FETCH_BUDGET_S + 120
