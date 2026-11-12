"""2026-11-06: us4.courthousecomputersystems.com started rejecting GET on
SearchService.asp with a plain HTTP 405 ("HTTP verb used to access this page is not
allowed") while POST with the identical query string answers 200 -- confirmed live for
every us4 HOSTED_CCHS tenant (rod/county_sweeps.py) and every us4 rod/cchs.py tenant
(Lincoln, Madison, Henderson, Duplin); us3/us5 tenants (Burke, Cleveland, Caswell,
Gates, Dare, Caldwell, Currituck) were re-confirmed unaffected on GET and ALSO fine on
POST. Both readers now retry a 405 via http_client.post_text at the same url instead of
hard-coding which tenant needs it -- these tests cover that retry-on-405 branch with no
network (http_client.get_text/post_text are faked).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from foreclosure_scraper import http_client as HC
from foreclosure_scraper.rod import cchs
from foreclosure_scraper.rod import county_sweeps as CS
from foreclosure_scraper.rod import nc_polite


def _http_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://x.example/SearchService.asp")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"got {code}", request=req, response=resp)


# --------------------------------------------------------------------------- #
# rod/cchs.py: _search_or_post                                               #
# --------------------------------------------------------------------------- #

def test_search_or_post_retries_a_405_via_post_and_returns_its_text(monkeypatch):
    calls = {"get": 0, "post": 0}

    async def fake_get_text(url, **kw):
        calls["get"] += 1
        raise _http_error(405)

    async def fake_post_text(url, **kw):
        calls["post"] += 1
        return "<SearchResponse><recordcount>1</recordcount></SearchResponse>"

    monkeypatch.setattr(cchs, "get_text", fake_get_text)
    monkeypatch.setattr(cchs, "post_text", fake_post_text)
    text = asyncio.run(cchs._search_or_post("https://x.example/SearchService.asp?cmd=search", {}))
    assert calls == {"get": 1, "post": 1}
    assert "<recordcount>1</recordcount>" in text


def test_search_or_post_never_calls_post_when_get_already_works(monkeypatch):
    calls = {"get": 0, "post": 0}

    async def fake_get_text(url, **kw):
        calls["get"] += 1
        return "<SearchResponse><recordcount>0</recordcount></SearchResponse>"

    async def fake_post_text(url, **kw):
        calls["post"] += 1
        raise AssertionError("post_text must not be called when GET already succeeds")

    monkeypatch.setattr(cchs, "get_text", fake_get_text)
    monkeypatch.setattr(cchs, "post_text", fake_post_text)
    text = asyncio.run(cchs._search_or_post("https://x.example/SearchService.asp?cmd=search", {}))
    assert calls == {"get": 1, "post": 0}
    assert "<recordcount>0</recordcount>" in text


def test_search_or_post_does_not_retry_a_non_405_status(monkeypatch):
    async def fake_get_text(url, **kw):
        raise _http_error(403)

    async def fake_post_text(url, **kw):
        raise AssertionError("post_text must not be called for a non-405 status")

    monkeypatch.setattr(cchs, "get_text", fake_get_text)
    monkeypatch.setattr(cchs, "post_text", fake_post_text)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        asyncio.run(cchs._search_or_post("https://x.example/SearchService.asp?cmd=search", {}))
    assert exc_info.value.response.status_code == 403


def test_get_search_text_still_walls_when_the_post_fallback_also_fails(monkeypatch):
    async def fake_get_text(url, **kw):
        raise _http_error(405)

    async def fake_post_text(url, **kw):
        raise _http_error(503)

    monkeypatch.setattr(cchs, "get_text", fake_get_text)
    monkeypatch.setattr(cchs, "post_text", fake_post_text)
    with pytest.raises(cchs.CchsWall):
        asyncio.run(cchs._get_search_text("us4.example", "https://x.example/SearchService.asp?cmd=search",
                                          {}, "search county=Lincoln"))


def test_search_by_name_recovers_a_us4_405_via_search_or_post(monkeypatch):
    """End-to-end through search_by_name (the function enrichment_cchs_rod.py calls):
    a 405 on GET no longer silently swallows to [] -- it recovers the real rows via
    POST, exactly as live-confirmed for Lincoln/Madison/Henderson/Duplin."""
    calls = {"get": 0, "post": 0}

    async def fake_get_text(url, **kw):
        calls["get"] += 1
        raise _http_error(405)

    async def fake_post_text(url, **kw):
        calls["post"] += 1
        if "cmd=getall" in url:
            return ("<Records><r><da>11/01/2026</da><ki>LIEN</ki><bk>400</bk><pg>12</pg>"
                    "<dn>2026000777</dn><or>DOE JOHN</or><ee>CREDITOR LLC</ee></r></Records>")
        return "<SearchResponse><recordcount>1</recordcount><doccount>1</doccount></SearchResponse>"

    import contextlib

    class _BootstrapClient:
        async def get(self, *a, **kw):
            return None

    @contextlib.asynccontextmanager
    async def fake_bootstrap_client(**kw):
        yield _BootstrapClient()

    monkeypatch.setattr(cchs, "get_text", fake_get_text)
    monkeypatch.setattr(cchs, "post_text", fake_post_text)
    monkeypatch.setattr(cchs, "client", fake_bootstrap_client)

    docs = asyncio.run(cchs.search_by_name("NC", "Lincoln", "DOE JOHN"))
    assert calls == {"get": 2, "post": 2}          # search + getall, each 405-then-POST
    assert len(docs) == 1 and docs[0].grantor == "DOE JOHN"


# --------------------------------------------------------------------------- #
# rod/county_sweeps.py: _impersonated_classic_get                           #
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _reset_wall_registry():
    nc_polite.reset_state()
    yield
    nc_polite.reset_state()


def test_impersonated_classic_get_retries_a_405_via_post(monkeypatch):
    calls = {"get": 0, "post": 0}

    async def fake_get_text(url, **kw):
        calls["get"] += 1
        raise _http_error(405)

    async def fake_post_text(url, **kw):
        calls["post"] += 1
        return "<SearchResponse><recordcount>2</recordcount></SearchResponse>"

    monkeypatch.setattr(HC, "get_text", fake_get_text)
    monkeypatch.setattr(HC, "post_text", fake_post_text)
    page = CS._impersonated_classic_get("https://x.example/SearchService.asp?cmd=search", headers={})
    assert calls == {"get": 1, "post": 1}
    assert page.status == 200 and "<recordcount>2</recordcount>" in page.text


def test_impersonated_classic_get_never_calls_post_when_get_already_works(monkeypatch):
    calls = {"get": 0, "post": 0}

    async def fake_get_text(url, **kw):
        calls["get"] += 1
        return "<SearchResponse><recordcount>0</recordcount></SearchResponse>"

    async def fake_post_text(url, **kw):
        calls["post"] += 1
        raise AssertionError("post_text must not be called when GET already succeeds")

    monkeypatch.setattr(HC, "get_text", fake_get_text)
    monkeypatch.setattr(HC, "post_text", fake_post_text)
    page = CS._impersonated_classic_get("https://x.example/SearchService.asp?cmd=search", headers={})
    assert calls == {"get": 1, "post": 0}
    assert page.status == 200


def test_impersonated_classic_get_degrades_cleanly_when_the_post_fallback_also_fails(monkeypatch):
    async def fake_get_text(url, **kw):
        raise _http_error(405)

    async def fake_post_text(url, **kw):
        raise RuntimeError("impersonate got 503 for " + url)

    monkeypatch.setattr(HC, "get_text", fake_get_text)
    monkeypatch.setattr(HC, "post_text", fake_post_text)
    page = CS._impersonated_classic_get("https://x.example/SearchService.asp?cmd=search", headers={})
    assert page.status == 503          # degraded to a Page, did not raise


def test_impersonated_classic_get_does_not_retry_a_non_405_status(monkeypatch):
    async def fake_get_text(url, **kw):
        raise _http_error(403)

    async def fake_post_text(url, **kw):
        raise AssertionError("post_text must not be called for a non-405 status")

    monkeypatch.setattr(HC, "get_text", fake_get_text)
    monkeypatch.setattr(HC, "post_text", fake_post_text)
    page = CS._impersonated_classic_get("https://x.example/SearchService.asp?cmd=search", headers={})
    assert page.status == 403


# --------------------------------------------------------------------------- #
# http_client.post_text itself                                              #
# --------------------------------------------------------------------------- #

def test_post_text_returns_body_on_a_clean_200(monkeypatch):
    import contextlib

    class _FakeHttpxClient:
        async def post(self, url, headers=None, data=None):
            req = httpx.Request("POST", url)
            return httpx.Response(200, text="<ok/>", request=req)

    @contextlib.asynccontextmanager
    async def fake_client(**kw):
        yield _FakeHttpxClient()

    monkeypatch.setattr(HC, "client", fake_client)
    text = asyncio.run(HC.post_text("https://x.example/SearchService.asp?cmd=search"))
    assert text == "<ok/>"


def test_post_text_retries_a_502_then_succeeds(monkeypatch):
    import contextlib
    import tenacity

    class _FakeHttpxClient:
        def __init__(self):
            self.n = 0

        async def post(self, url, headers=None, data=None):
            self.n += 1
            req = httpx.Request("POST", url)
            if self.n == 1:
                return httpx.Response(502, text="bad gateway", request=req)
            return httpx.Response(200, text="<ok/>", request=req)

    fake = _FakeHttpxClient()

    @contextlib.asynccontextmanager
    async def fake_client(**kw):
        yield fake

    monkeypatch.setattr(HC, "client", fake_client)
    monkeypatch.setattr(HC, "wait_exponential_jitter", lambda **kw: tenacity.wait_none())
    text = asyncio.run(HC.post_text("https://x.example/SearchService.asp?cmd=search"))
    assert text == "<ok/>" and fake.n == 2


def test_post_text_does_not_retry_a_404(monkeypatch):
    import contextlib

    class _FakeHttpxClient:
        def __init__(self):
            self.n = 0

        async def post(self, url, headers=None, data=None):
            self.n += 1
            req = httpx.Request("POST", url)
            return httpx.Response(404, text="not found", request=req)

    fake = _FakeHttpxClient()

    @contextlib.asynccontextmanager
    async def fake_client(**kw):
        yield fake

    monkeypatch.setattr(HC, "client", fake_client)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(HC.post_text("https://x.example/SearchService.asp?cmd=search"))
    assert fake.n == 1
