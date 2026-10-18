"""wall_bypass._pydoll_fetch: pydoll's own Browser.close() (chromium/base.py) only closes the
WebSocket connection -- Browser.stop() is the one that calls _browser_process_manager.
stop_process() (SIGTERM, then SIGKILL after 15s) on the real OS Chrome subprocess. The cleanup
finally-block must call stop(), not close(), on every path (success, error, timeout), or every
pydoll fetch leaks a Chrome process. 2026-10-17: close()-only left 365 orphaned Chrome processes
running from one run_stealth_sources.py session, making the Mac unresponsive. No real browser is
launched here -- pydoll's Chrome class is monkeypatched with a fake."""
from __future__ import annotations

import asyncio

from foreclosure_scraper import wall_bypass as W


class _FakeTab:
    def __init__(self, page_html: str = "<html><body>ok</body></html>", fail_go_to: bool = False):
        self._page_html = page_html
        self._fail_go_to = fail_go_to

    async def enable_auto_solve_cloudflare_captcha(self, **kw):
        pass

    async def go_to(self, url, timeout=None):
        if self._fail_go_to:
            raise RuntimeError("simulated navigation failure")

    @property
    async def page_source(self):
        return self._page_html


class _FakeChrome:
    instances: list["_FakeChrome"] = []
    fail_go_to = False

    def __init__(self, options=None):
        self.stopped = False
        self.closed = False
        type(self).instances.append(self)

    async def start(self):
        return _FakeTab(fail_go_to=type(self).fail_go_to)

    async def stop(self):
        self.stopped = True

    async def close(self):
        self.closed = True


def _patch_chrome(monkeypatch, fail_go_to: bool = False):
    import pydoll.browser.chromium as chromium_mod
    _FakeChrome.instances = []
    _FakeChrome.fail_go_to = fail_go_to
    monkeypatch.setattr(chromium_mod, "Chrome", _FakeChrome)
    monkeypatch.setattr(W, "_find_chrome_binary", lambda: None)


def test_a_successful_fetch_stops_not_just_closes_the_browser(monkeypatch):
    _patch_chrome(monkeypatch)
    out = asyncio.run(W._pydoll_fetch("https://example.com", 5, None))
    assert "ok" in out
    assert len(_FakeChrome.instances) == 1
    assert _FakeChrome.instances[0].stopped is True
    assert _FakeChrome.instances[0].closed is False


def test_a_failed_fetch_still_stops_the_browser(monkeypatch):
    _patch_chrome(monkeypatch, fail_go_to=True)
    out = asyncio.run(W._pydoll_fetch("https://example.com", 5, None))
    assert out == ""
    assert _FakeChrome.instances[0].stopped is True


def test_a_cancelled_fetch_still_stops_the_browser(monkeypatch):
    """The exact hazard the surrounding comment calls out: asyncio.CancelledError is a
    BaseException, not an Exception -- an `except Exception` cleanup would let it skip stop()
    entirely and leak the process."""
    _patch_chrome(monkeypatch)

    class _HangingTab(_FakeTab):
        async def go_to(self, url, timeout=None):
            await asyncio.sleep(10)

    class _HangingChrome(_FakeChrome):
        async def start(self):
            return _HangingTab()

    import pydoll.browser.chromium as chromium_mod
    monkeypatch.setattr(chromium_mod, "Chrome", _HangingChrome)

    async def _run():
        task = asyncio.ensure_future(W._pydoll_fetch("https://example.com", 5, None))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert _HangingChrome.instances[0].stopped is True
