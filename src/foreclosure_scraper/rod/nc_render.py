"""Headless-browser lookups for NC registers whose name search runs in the page's own JavaScript
(Harris 'ROD Web Access' Infragistics forms, Logan's Blazor and Visual WebGui apps). Same approach
as rod/logan_render.py (the Spartanburg precedent): a fresh guest session in headless Chromium per
lookup, doing only what a person does on the page (accept the disclaimer, type the name, press
Search), no login, no CAPTCHA, no stealth settings.

RULES, shared with the plain-HTTP adapters (rod/nc_polite.py)
  * an ordinary desktop Chrome User-Agent (the quiet-title intake's), no TLS or fingerprint tricks;
    images, fonts and media are not downloaded;
  * every navigation or server action waits for the same per-host 1.6 s clock the plain client uses;
    one browser in the process at a time (an 8 GB machine), one lookup at a time per county;
  * after every navigation the page is checked by the shared wall detector: a CAPTCHA, a login page,
    a challenge or a block status walls the county for the run and nothing is retried;
  * the per-run cap is the platform's own env var (NcRenderPlatform.cap_env, default 30 lookups per
    county), in the style of FORECLOSURE_SPARTANBURG_ROD_MAX.

The adapters talk to the page only through RenderPage, so their flows are tested offline with a
scripted fake page (tests/_nc_rod_fakes.py FakeRenderPage).
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional
from urllib.parse import urlsplit

from ..quiet_title.fetch import UA
from . import nc_polite
from .nc_chain import OwnerName, SearchResult
from .nc_platform import NcRodPlatform
from .nc_polite import PoliteClient, RodWalled

_BROWSER_LOCK = threading.Lock()
_HEAVY = ("image", "font", "media")


class RenderPage:
    """The few page actions an adapter needs, each paced and wall-checked."""

    def __init__(self, platform: str, state: str, county: str, page: Any) -> None:
        self.platform, self.state, self.county = platform, state, county
        self.page = page

    def _host(self, url: Optional[str] = None) -> str:
        return (urlsplit(url or self.page.url).hostname or "").lower()

    def check(self, status: int = 200) -> str:
        html = self.page.content()
        why = nc_polite.wall_reason(status, self.page.url, html)
        if why:
            nc_polite.mark_walled(self.platform, self.state, self.county, why)
            raise RodWalled(self.page.url, why)
        return html

    def goto(self, url: str) -> str:
        nc_polite.pace(self._host(url))
        resp = self.page.goto(url, wait_until="networkidle")
        nc_polite.mark_done(self._host(url))
        return self.check(resp.status if resp is not None else 200)

    def click_nav(self, selector: str, timeout_ms: int = 90000) -> str:
        """Click something that loads a new page (a postback, a submit)."""
        nc_polite.pace(self._host())
        with self.page.expect_navigation(timeout=timeout_ms):
            self.page.click(selector)
        self.page.wait_for_load_state("networkidle")
        nc_polite.mark_done(self._host())
        return self.check()

    def click_wait(self, selector: str, settle_ms: int = 1500) -> str:
        """Click something that updates the page in place (an AJAX postback, a websocket UI)."""
        nc_polite.pace(self._host())
        self.page.click(selector)
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(settle_ms)
        nc_polite.mark_done(self._host())
        return self.check()

    def type_into(self, selector: str, text: str) -> None:
        """Type as a person does (key events, so the page's own controls record the value)."""
        self.page.click(selector)
        self.page.keyboard.press("Control+A")
        self.page.keyboard.press("Delete")
        if text:
            self.page.keyboard.type(text, delay=25)

    def click_local(self, selector: str) -> None:
        """A click that only changes the page (a radio button, a tab): no server request."""
        self.page.click(selector)

    def has(self, selector: str) -> bool:
        return self.page.query_selector(selector) is not None

    def html(self) -> str:
        return self.check()

    def wait_for(self, selector: str, timeout_ms: int = 30000) -> bool:
        try:
            self.page.wait_for_selector(selector, timeout=timeout_ms)
            return True
        except Exception:  # noqa: BLE001 - a missing element is the caller's to report
            return False


def _route(route) -> None:
    if route.request.resource_type in _HEAVY:
        route.abort()
    else:
        route.continue_()


@contextmanager
def browser_page(platform: str, state: str, county: str, *, timeout_ms: int = 60000) -> Iterator[RenderPage]:
    """A fresh headless Chromium guest session (closed afterwards); one at a time in the process."""
    from playwright.sync_api import sync_playwright
    with _BROWSER_LOCK:
        with sync_playwright() as p:
            br = p.chromium.launch(headless=True)
            try:
                ctx = br.new_context(user_agent=UA)
                ctx.route("**/*", _route)
                pg = ctx.new_page()
                pg.set_default_timeout(timeout_ms)
                yield RenderPage(platform, state, county, pg)
            finally:
                br.close()


#: test seam: tests replace this with a factory yielding a scripted fake page
launcher: Callable[..., Any] = browser_page


class NcRenderPlatform(NcRodPlatform):
    """An NcRodPlatform whose lookups run in a headless browser. Subclasses set cap_env and
    implement _render_search(rp, cfg, who, side, date_thru)."""

    default_cap = 30

    def _search(self, client: PoliteClient, cfg: Any, ctx, who: OwnerName, side: str,
                date_thru: Optional[str]) -> SearchResult:
        with launcher(self.platform, self.state, client.county) as rp:
            return self._render_search(rp, cfg, who, side, date_thru)

    def _render_search(self, rp: RenderPage, cfg: Any, who: OwnerName, side: str,
                       date_thru: Optional[str], date_from: Optional[str] = None) -> SearchResult:
        raise NotImplementedError
