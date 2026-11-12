"""Per-host rate limiter + UA rotation (IP-ban hardening)."""
from __future__ import annotations

import asyncio
import time

from foreclosure_scraper import http_client as hc


def test_same_host_requests_are_spaced(monkeypatch):
    monkeypatch.setattr(hc, "_MIN_INTERVAL_S", 0.2)
    monkeypatch.setattr(hc, "_JITTER_S", 0.0)

    async def run():
        t0 = time.monotonic()
        for _ in range(3):
            await hc._throttle("spaced-host.example")  # fresh host
        return time.monotonic() - t0

    elapsed = asyncio.run(run())
    assert elapsed >= 0.4 - 0.05  # 3 calls -> 2 enforced gaps of 0.2s


def test_different_hosts_run_in_parallel(monkeypatch):
    monkeypatch.setattr(hc, "_MIN_INTERVAL_S", 0.5)
    monkeypatch.setattr(hc, "_JITTER_S", 0.0)

    async def run():
        t0 = time.monotonic()
        await asyncio.gather(
            hc._throttle("hostA.example"), hc._throttle("hostB.example"),
            hc._throttle("hostC.example"),
        )
        return time.monotonic() - t0

    # first hit to each fresh host doesn't wait; parallel across hosts
    assert asyncio.run(run()) < 0.3


def test_throttle_noop_on_empty_host():
    asyncio.run(hc._throttle(None))  # must not raise


def test_default_ua_is_from_pool_and_present():
    assert hc.DEFAULT_HEADERS["User-Agent"] in hc._UA_POOL
    assert "Mozilla/5.0" in hc.DEFAULT_HEADERS["User-Agent"]
