"""national.sc_public_index's nodriver browser must always be closed.

MEASURED (2026-09-25 live incident): national.sc_public_index logged
scraper.timeout at 05:05:33 UTC (base_scraper.safe_run()'s
asyncio.wait_for firing on this scraper's soft timeout_s -- a clean
~3min run), but its underlying uc_* Chrome child process (nodriver,
launched by _nodriver_search_county) kept running -- pegged at high CPU
-- for hours afterward, until it was found and killed by hand; killing
it immediately unstuck the pipeline. Root cause: the old code's cleanup
lived only inside `except Exception:` handlers (plus one call after the
search loop finished). asyncio.CancelledError -- what asyncio.wait_for
actually raises into a cancelled coroutine -- is a BaseException, not an
Exception, so it skipped every `except Exception:` handler untouched and
neither `browser.stop()` call ever ran. The fix wraps the whole browser
lifecycle in one try/finally so cleanup runs on every exit path (success,
ordinary exception, or cancellation), and re-raises CancelledError after
cleanup instead of swallowing it.

These tests mock `nodriver.start` -- no real Chrome is launched.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import nodriver
import pytest

from foreclosure_scraper.scrapers.national import sc_public_index


SEARCH_PAGE_HTML = (
    "<html><body>"
    "<input type='text' id='ContentPlaceHolder1_TextBoxlastName'>"
    "</body></html>"
)


def _make_fake_browser(page) -> MagicMock:
    browser = MagicMock()
    browser.get = AsyncMock(return_value=page)
    browser.stop = MagicMock()
    return browser


def _make_fake_page(*, get_content_html: str = SEARCH_PAGE_HTML,
                     get_content_hangs: bool = False,
                     evaluate_raises: bool = False) -> MagicMock:
    page = MagicMock()

    btn = MagicMock()
    btn.click = AsyncMock(return_value=None)
    page.find = AsyncMock(return_value=btn)

    if get_content_hangs:
        # A never-set Event gives a genuine, indefinitely-awaitable
        # suspension point for asyncio.wait_for to cancel into --
        # standing in for "the outer timeout fires mid-browser-op".
        async def _hang():
            await asyncio.Event().wait()
        page.get_content = AsyncMock(side_effect=_hang)
    else:
        page.get_content = AsyncMock(return_value=get_content_html)

    if evaluate_raises:
        page.evaluate = AsyncMock(side_effect=RuntimeError("boom: JS eval failed"))
    else:
        page.evaluate = AsyncMock(return_value=None)

    return page


@pytest.fixture(autouse=True)
def _single_prefix_and_fast_sleep(monkeypatch):
    """Keep the happy-path test from actually looping all 26 letters /
    sleeping the real (dozens of seconds of) delays -- irrelevant to what
    these tests check (cleanup), and would make the suite slow."""
    monkeypatch.setattr(sc_public_index, "SEARCH_PREFIXES", ["A"])

    async def _fast_sleep(*_a, **_kw):
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)


@pytest.mark.asyncio
async def test_normal_run_closes_browser_no_behavior_change(monkeypatch):
    """(a) A clean, successful run still calls browser.stop() exactly once."""
    page = _make_fake_page()
    browser = _make_fake_browser(page)
    monkeypatch.setattr(nodriver, "start", AsyncMock(return_value=browser))

    result = await sc_public_index._nodriver_search_county("spartanburg")

    assert result == []  # dummy HTML has no case rows -- just proving it ran clean
    browser.stop.assert_called_once()


@pytest.mark.asyncio
async def test_exception_during_flow_still_closes_browser(monkeypatch):
    """(b) An ordinary exception mid-flow must not skip cleanup."""
    page = _make_fake_page(evaluate_raises=True)
    browser = _make_fake_browser(page)
    monkeypatch.setattr(nodriver, "start", AsyncMock(return_value=browser))

    result = await sc_public_index._nodriver_search_county("spartanburg")

    assert result == []
    browser.stop.assert_called_once()


@pytest.mark.asyncio
async def test_cancellation_from_outer_timeout_still_closes_browser(monkeypatch):
    """(b)/(c) This is the exact incident: an outer asyncio.wait_for (what
    safe_run() uses for timeout_s) cancels the coroutine while it's
    suspended mid-browser-op. Cleanup must still run, AND the cancellation
    must propagate (not be swallowed) -- wait_for surfaces that as
    asyncio.TimeoutError to the caller.
    """
    page = _make_fake_page(get_content_hangs=True)
    browser = _make_fake_browser(page)
    monkeypatch.setattr(nodriver, "start", AsyncMock(return_value=browser))

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            sc_public_index._nodriver_search_county("spartanburg"), timeout=0.05
        )

    # The whole point of the fix: even though the coroutine never reached
    # its own return statement, the browser was still stopped.
    browser.stop.assert_called_once()
