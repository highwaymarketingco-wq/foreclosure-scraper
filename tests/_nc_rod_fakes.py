"""Offline stand-in for the requests.Session the NC register adapters (rod/nc_*.py) use.

Routes on (method, URL substring); a route's answer is a FakeResp, a list served in order (the
last one repeats), or a callable(method, url, params, data) -> FakeResp. Every call is recorded as
(method, url, params, data) so a test can assert what went out, and that nothing went out after a
wall. install() also turns off the 1.6 s pacing sleep and resets the process-wide budgets, walls,
sessions and caches.
"""
from __future__ import annotations

from typing import Any, Callable, Union


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
