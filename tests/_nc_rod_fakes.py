"""Offline stand-in for the requests.Session the NC register adapters (rod/nc_*.py) use.

Routes on (method, URL substring); a route's answer is a FakeResp, a list served in order (the
last one repeats), or a callable(method, url, params, data) -> FakeResp. Every call is recorded as
(method, url, params, data) so a test can assert what went out, and that nothing went out after a
wall. install() also turns off the 1.6 s pacing sleep and resets the process-wide budgets, walls,
sessions and caches.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Callable, Optional, Union


class FakeResp:
    def __init__(self, text: str = "", status_code: int = 200, url: str = ""):
        self.text = text
        self.status_code = status_code
        self.url = url
        self.content = text.encode("utf-8")


Answer = Union[FakeResp, list, Callable[..., FakeResp]]


class FakeSession:
    def __init__(self, routes: list[tuple[str, str, Answer]]):
        self.routes = routes
        self.calls: list[tuple[str, str, Any, Any]] = []
        self.headers: dict = {}
        self._served: dict[int, int] = {}

    def request(self, method, url, params=None, data=None, headers=None, timeout=None, allow_redirects=True):
        self.calls.append((method, url, params, data))
        for i, (m, sub, ans) in enumerate(self.routes):
            if m == method and sub in url:
                if callable(ans) and not isinstance(ans, FakeResp):
                    r = ans(method, url, params, data)
                elif isinstance(ans, list):
                    n = self._served.get(i, 0)
                    self._served[i] = n + 1
                    r = ans[min(n, len(ans) - 1)]
                else:
                    r = ans
                if not r.url:
                    r = FakeResp(r.text, r.status_code, url)
                return r
        return FakeResp("<html>no route</html>", 404, url)


def install(monkeypatch, routes: list[tuple[str, str, Answer]], *adapters) -> FakeSession:
    """Point every NC adapter at one FakeSession and reset process state. Returns the session."""
    from foreclosure_scraper.rod import nc_polite
    sess = FakeSession(routes)
    monkeypatch.setattr(nc_polite, "session_factory", lambda: sess)
    monkeypatch.setattr(nc_polite, "sleep", lambda s: None)
    nc_polite.reset_state()
    for a in adapters:
        a.drop_sessions()
    return sess


# -- shared canned bodies (made-up, shaped like the real pages) --------------------------------

CLOUDFLARE_403 = FakeResp("<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>"
                          "<div id='cf-chl-widget'></div><script src='/cdn-cgi/challenge-platform/h/b/orchestrate'>"
                          "</script></body></html>", 403)

CAPTCHA_PAGE = FakeResp("<html><head><title>Records</title></head><body><h2>Please Verify You are Not a Robot</h2>"
                        "<div class='g-recaptcha' data-sitekey='x'></div></body></html>", 200)

SERVER_ERROR = FakeResp("<html><head><title>Runtime Error</title></head><body><h1>Server Error in '/' "
                        "Application.</h1></body></html>", 500)


# -- a scripted stand-in for a Playwright page, driven through the real rod.nc_render.RenderPage ------

class _Resp:
    def __init__(self, status: int):
        self.status = status


class _Keyboard:
    def __init__(self, page: "FakePWPage"):
        self.page = page

    def press(self, key: str) -> None:
        if key in ("Control+A", "Delete"):
            self.page.typed[self.page.focus] = ""

    def type(self, text: str, delay: int = 0) -> None:
        self.page.typed[self.page.focus] = self.page.typed.get(self.page.focus, "") + text


class FakePWPage:
    """goto(url) answers from `pages` (URL substring -> html or (status, html)); click(selector)
    on a selector in `clicks` loads the next scripted page (a list is served in order); any other
    click is local. A selector 'exists' when its id / text is in the current html. Every action is
    recorded in `log`; typed text per selector in `typed`."""

    def __init__(self, pages: dict, clicks: Optional[dict] = None, start_url: str = "about:blank"):
        self.pages, self.clicks = pages, dict(clicks or {})
        self.url, self.html = start_url, ""
        self.log: list[tuple[str, str]] = []
        self.typed: dict[str, str] = {}
        self.focus = ""
        self._pending = None
        self._served: dict[str, int] = {}
        self.keyboard = _Keyboard(self)

    def _answer(self, ans, url):
        status, html = ans if isinstance(ans, tuple) else (200, ans)
        self.url, self.html = url, html
        return _Resp(status)

    def goto(self, url, wait_until=None, timeout=None):
        self.log.append(("goto", url))
        for sub, ans in self.pages.items():
            if sub in url:
                return self._answer(ans, url)
        return self._answer((404, "<html>not found</html>"), url)

    def content(self) -> str:
        return self.html

    def query_selector(self, sel: str):
        if sel.startswith("text="):
            return object() if sel[5:] in self.html else None
        m = re.match(r"#([\w\-]+)", sel)
        if not m:
            return object() if sel in self.html else None
        tag = re.search(r"""<[^>]*id=["']""" + re.escape(m.group(1)) + r"""["'][^>]*>""", self.html)
        if tag is None:
            return None
        if ":not([disabled])" in sel and re.search(r"\sdisabled[\s>=/]", tag.group(0)):
            return None
        return object()

    def wait_for_selector(self, sel, timeout=None):
        if self.query_selector(sel) is None:
            raise TimeoutError(sel)

    def click(self, sel, **kw):
        self.log.append(("click", sel))
        self.focus = sel
        if sel in self.clicks:
            ans = self.clicks[sel]
            if isinstance(ans, list):
                n = self._served.get(sel, 0)
                self._served[sel] = n + 1
                ans = ans[min(n, len(ans) - 1)]
            if callable(ans):
                ans = ans(self)
            self._pending = ans

    def _apply(self):
        if self._pending is not None:
            url, html = self._pending
            self._pending = None
            self.url, self.html = url, html

    @contextmanager
    def expect_navigation(self, timeout=None):
        yield
        self._apply()

    def wait_for_load_state(self, state=None):
        self._apply()

    def wait_for_timeout(self, ms):
        self._apply()


def install_render(monkeypatch, fake_page_factory):
    """Point rod.nc_render.launcher at a factory returning a FakePWPage per lookup."""
    from foreclosure_scraper.rod import nc_render

    @contextmanager
    def launcher(platform, state, county, **kw):
        yield nc_render.RenderPage(platform, state, county, fake_page_factory())

    monkeypatch.setattr(nc_render, "launcher", launcher)
