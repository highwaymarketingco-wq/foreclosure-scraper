"""CchsClassicReader's two SearchService.asp calls escalate to curl-cffi impersonation on a
block status, the same fix rod/cchs.py's _get_search_text already applies to the identical
endpoint on the identical vendor-hosted courthousecomputersystems.com tenants.

2026-10-16: confirmed live via the VM's own log that all 17 HOSTED_CCHS counties' sweep got
HTTP 403 every run because CchsClassicReader used PoliteClient (plain requests.Session, no
TLS impersonation by design -- it serves 3 OTHER NC ROD platforms that don't need it) for
this endpoint instead of the impersonation tier rod/cchs.py already proved clears it.
"""
from __future__ import annotations

import httpx
import pytest

from foreclosure_scraper import http_client as HC
from foreclosure_scraper.rod import county_sweeps as CS
from foreclosure_scraper.rod import nc_polite


@pytest.fixture(autouse=True)
def _reset_wall_registry():
    nc_polite.reset_state()
    yield
    nc_polite.reset_state()

_SEARCH_XML = "<recordcount>2</recordcount><doccount>1</doccount>"
_GETALL_XML = (
    "<r><da>10/01/2026</da><ki>FCL</ki><bk>300</bk><pg>12</pg><dn>2026000123</dn>"
    "<or>DOE JOHN</or><ee>BANK LLC</ee></r>"
    "<r><da>10/01/2026</da><ki>FCL</ki><bk>300</bk><pg>12</pg><dn>2026000123</dn>"
    "<or>DOE JANE</or><ee>BANK LLC</ee></r>"
)


def _reader() -> CS.CchsClassicReader:
    from types import SimpleNamespace
    fake_client = SimpleNamespace(platform="cchs_classic_hosted_sweep", state="NC", county="Duplin")
    r = CS.CchsClassicReader("Duplin", client=fake_client)  # unused once open() is skipped
    r.kinds = ["FCL"]
    r.types = 1
    return r


def test_a_403_on_plain_httpx_escalates_and_the_sweep_succeeds(monkeypatch):
    calls = {"n": 0}

    async def fake_get_text(url, **kw):
        calls["n"] += 1
        assert kw.get("impersonate") is True
        if "cmd=getall" in url:
            return _GETALL_XML
        return _SEARCH_XML

    monkeypatch.setattr(HC, "get_text", fake_get_text)
    from datetime import date
    docs, overflowed = _reader().read(date(2026, 10, 1), date(2026, 10, 7))

    assert calls["n"] == 2
    assert overflowed is False
    assert len(docs) == 1   # two party rows collapse into one document


def test_a_block_even_impersonation_cannot_clear_walls_the_county(monkeypatch):
    """A block code that survives BOTH tiers (plain httpx AND curl-cffi impersonation --
    get_text(impersonate=True) already tries both internally) is a much stronger wall
    signal than the single plain-httpx 403 this used to wall on. Must still mark_walled
    and raise RodWalled, exactly like PoliteClient.request() does for every other call,
    not a generic RuntimeError that bypasses the existing wall-tracking contract."""
    from foreclosure_scraper.rod.nc_polite import RodWalled, walled_reason

    async def fake_get_text(url, **kw):
        raise RuntimeError("impersonate got 403 for " + url)

    monkeypatch.setattr(HC, "get_text", fake_get_text)
    from datetime import date
    reader = _reader()
    with pytest.raises(RodWalled):
        reader.read(date(2026, 10, 1), date(2026, 10, 7))
    assert walled_reason("cchs_classic_hosted_sweep", "NC", "Duplin") == "HTTP 403"


def test_a_real_non_block_http_error_surfaces_as_the_existing_runtimeerror_not_a_wall(monkeypatch):
    async def fake_get_text(url, **kw):
        req = httpx.Request("GET", url)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("not found", request=req, response=resp)

    monkeypatch.setattr(HC, "get_text", fake_get_text)
    from datetime import date
    from foreclosure_scraper.rod.nc_polite import walled_reason
    with pytest.raises(RuntimeError, match="without a record count"):
        _reader().read(date(2026, 10, 1), date(2026, 10, 7))
    assert walled_reason("cchs_classic_hosted_sweep", "NC", "Duplin") is None   # a real 404 is not a wall


def test_impersonated_classic_get_returns_a_200_page_on_success(monkeypatch):
    async def fake_get_text(url, **kw):
        return "<recordcount>0</recordcount>"

    monkeypatch.setattr(HC, "get_text", fake_get_text)
    page = CS._impersonated_classic_get("https://x.example/SearchService.asp", headers={})
    assert page.status == 200 and "recordcount" in page.text


def test_impersonated_classic_get_never_raises_on_any_failure(monkeypatch):
    async def fake_get_text(url, **kw):
        raise ConnectionError("dns failure")

    monkeypatch.setattr(HC, "get_text", fake_get_text)
    page = CS._impersonated_classic_get("https://x.example/SearchService.asp", headers={})
    assert page.status >= 400   # degraded to a Page, did not raise
