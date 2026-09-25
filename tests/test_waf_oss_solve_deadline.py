"""enrichment_waf_oss.solve_waf_via_browser must not run unboundedly long.

MEASURED (2026-09-25 live incident): a patchright-launched "Chrome for
Testing" renderer (Scrapling's StealthyFetcher, which reaches this
module's solve_waf_via_browser via its page_action hook -- see
scrapers/counties_nc/nc_ecourts_estates.py and
enrichment_nc_case_status_tyler.py) was found pegged at 100% CPU for 2.7
hours straight, a direct child of the still-running scraper process;
killing it immediately unstuck the whole pipeline.

Every individual wait inside solve_waf_via_browser (canvas selector,
canvas-render poll, one Gemini HTTP call, Confirm click, networkidle) was
already bounded -- but they compound: MAX_PUZZLES (20) puzzles x up to 11
rotated Gemini keys x GEMINI_TIMEOUT_S (30s) is ~110 minutes worst case,
which dwarfs every caller's own outer timeout_s (base_scraper.safe_run,
180-600s) and even Scrapling's own `timeout=240000`ms fetch param (which
only bounds page ops IT drives, not the total runtime of a page_action
callback like this one). In practice the only thing that ever stopped a
run this long was the caller's outer asyncio.wait_for cancelling deep
inside this coroutine mid-await on the browser/HTTP call -- an unsafe
cancellation point for Playwright/patchright's async bindings and the
likely leak vector.

The fix adds MAX_TOTAL_SOLVE_SECONDS: a self-imposed wall-clock budget
checked at the top of the puzzle loop and threaded into _identify_tiles's
key-rotation loop, so the function returns False on its own -- well
inside every caller's timeout -- instead of needing to be force-cancelled
mid-browser-op. These tests mock the Playwright `page` object and the
Gemini HTTP call -- no real browser or network call is made.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from foreclosure_scraper import enrichment_waf_oss as waf


def _fake_locator_result(*, exists: bool) -> MagicMock:
    """The real code does `page.locator(sel).first` -- `.first` must be an
    explicit attribute carrying our async count()/click(), not a MagicMock
    auto-attribute (those return plain (non-awaitable) Mocks)."""
    wrapper = MagicMock()
    first = MagicMock()
    first.count = AsyncMock(return_value=1 if exists else 0)
    first.click = AsyncMock(return_value=None)
    wrapper.first = first
    return wrapper


class _FakeMouse:
    def __init__(self):
        self.click = AsyncMock(return_value=None)


class FakePage:
    """Stands in for a Playwright/patchright `page`. `solved_after` controls
    how many Confirm clicks it takes before the WAF marker disappears from
    page.content() -- None means it NEVER clears (the pathological /
    unresolvable-retry-loop case the incident describes)."""

    def __init__(self, solved_after: int | None = 1):
        self.solved_after = solved_after
        self.puzzle_attempts = 0
        self.confirms = 0
        self.mouse = _FakeMouse()

    def locator(self, selector: str):
        if "Confirm" in selector:
            return _fake_locator_result(exists=True)
        return _fake_locator_result(exists=False)  # no "Begin" button, no Submit/Verify

    async def wait_for_selector(self, *_a, **_kw):
        self.puzzle_attempts += 1
        return None

    async def wait_for_function(self, *_a, **_kw):
        return None

    async def wait_for_load_state(self, *_a, **_kw):
        return None

    async def evaluate(self, script: str, *_a, **_kw):
        if "Choose all" in script:
            return "traffic lights"
        if "toDataURL" in script:
            return {"rect": {"x": 0, "y": 0, "w": 300, "h": 300}, "b64": "ZmFrZQ=="}
        return None

    async def content(self) -> str:
        self.confirms += 1
        if self.solved_after is not None and self.confirms >= self.solved_after:
            return "<html>past the challenge now</html>"
        return "<html>awswaf gokuProps still here</html>"


@pytest.mark.asyncio
async def test_normal_solve_succeeds_on_first_puzzle_no_behavior_change(monkeypatch):
    """(a) Happy path: solves in one puzzle, well within budget, unaffected
    by the new deadline logic."""
    monkeypatch.setattr(waf, "_identify_tiles", AsyncMock(return_value=[1, 5]))
    page = FakePage(solved_after=1)

    result = await waf.solve_waf_via_browser(page)

    assert result is True
    assert page.puzzle_attempts == 1


@pytest.mark.asyncio
async def test_unresolvable_retry_loop_times_out_via_deadline_not_max_puzzles(monkeypatch):
    """(c) The pathological case from the incident: the WAF challenge never
    actually clears (solved_after=None), so without a wall-clock budget the
    old code would grind through all MAX_PUZZLES=20 attempts (each with its
    own real ~2.7s of bounded sleeps -- canvas settle + tile click + post-
    confirm -- so ~53s here, and far longer/effectively unbounded once
    Gemini key-rotation is added on top in a real run). With
    MAX_TOTAL_SOLVE_SECONDS tightened for this test, it must give up after
    exactly one puzzle attempt (the deadline check runs at the TOP of each
    loop iteration, so the in-flight attempt still pays its own real
    bounded sleeps, ~2.7s, before the SECOND iteration's deadline check
    catches it) -- nowhere near the ~53s that 20 full iterations would
    take, let alone the ~110min pathological case with real Gemini
    key-rotation on top.
    """
    monkeypatch.setattr(waf, "MAX_TOTAL_SOLVE_SECONDS", 0.05)
    monkeypatch.setattr(waf, "_identify_tiles", AsyncMock(return_value=[1]))
    page = FakePage(solved_after=None)  # WAF marker never clears

    started = time.monotonic()
    result = await waf.solve_waf_via_browser(page)
    elapsed = time.monotonic() - started

    assert result is False
    # Proves the DEADLINE ended the loop, not MAX_PUZZLES=20.
    assert page.puzzle_attempts < 20, (
        f"ran {page.puzzle_attempts} puzzle attempts -- the deadline check "
        "didn't short-circuit the loop"
    )
    # "Reasonable time": nowhere near the ~53s (let alone the ~110min with
    # real Gemini key-rotation) the unbounded loop would take.
    assert elapsed < 5.0, f"took {elapsed:.2f}s -- deadline budget was not enforced"


@pytest.mark.asyncio
async def test_identify_tiles_stops_rotating_keys_past_deadline(monkeypatch):
    """(c), isolated: _identify_tiles's own Gemini-key-rotation loop must
    stop consulting further keys once the shared deadline has already
    passed, rather than burning a full GEMINI_TIMEOUT_S per remaining key."""
    monkeypatch.setenv("GEMINI_API_KEY", "k1,k2,k3")

    post_calls = {"n": 0}

    async def _slow_post(*_a, **_kw):
        post_calls["n"] += 1
        raise AssertionError("no HTTP call should be made once the deadline has passed")

    fake_client = MagicMock()
    fake_client.post = _slow_post
    fake_client_cm = MagicMock()
    fake_client_cm.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client_cm.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(waf.httpx, "AsyncClient", MagicMock(return_value=fake_client_cm))

    already_expired = time.monotonic() - 1.0
    result = await waf._identify_tiles("ZmFrZQ==", "cars", deadline=already_expired)

    assert result is None
    assert post_calls["n"] == 0
