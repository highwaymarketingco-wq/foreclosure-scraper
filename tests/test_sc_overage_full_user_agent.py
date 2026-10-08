"""The SC overage-claim scrapers send a complete browser User-Agent.

2026-10-08: yorkcountysc.gov and orangeburgcounty.org (CivicPlus DocumentCenter behind
Cloudflare) answer the bare "Mozilla/5.0" these modules used to send with HTTP 403, and a
complete browser User-Agent with 200 (same host, same minute, no challenge page). York
went from 107 rows to 0 and Orangeburg from 446 to 0 on that alone.

The fake transport below behaves like that front: 403 for a bare or missing UA, the real
document otherwise. On the old code every module fetched nothing.
"""
from __future__ import annotations

import asyncio
import importlib

import httpx
import pytest

MODULES = [
    "york_overage_claims",
    "orangeburg_overage_claims",
    "calhoun_overage_claims",
    "fairfield_overage_claims",
    "laurens_overage_claims",
]

_PKG = "foreclosure_scraper.scrapers.counties_sc."


def _is_full_browser_ua(ua: str | None) -> bool:
    ua = (ua or "").strip()
    return ua != "Mozilla/5.0" and "AppleWebKit" in ua and "Chrome/" in ua


def _patch_client(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.parametrize("name", MODULES)
def test_every_request_carries_a_complete_browser_user_agent(monkeypatch, name):
    mod = importlib.import_module(_PKG + name)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        if not _is_full_browser_ua(request.headers.get("user-agent")):
            return httpx.Response(403, text="Forbidden")
        return httpx.Response(200, html="<html><body>nothing posted</body></html>")

    _patch_client(monkeypatch, handler)
    scraper_cls = next(v for v in vars(mod).values()
                       if isinstance(v, type) and v.__module__ == mod.__name__
                       and hasattr(v, "fetch") and hasattr(v, "slug"))
    s = scraper_cls()
    asyncio.run(s.safe_run())
    assert seen, f"{name} made no request"
    assert all(_is_full_browser_ua(ua) for ua in seen), f"{name} sent {set(seen)}"


YORK_TEXT = """Tax Sale 10/28/2024
NAME
 MAP#
 OVERAGE AMT
SAMPLEMAN ALPHA Q
 111-22-33-444
 $1,234.56
EXAMPLETON BETA R ETAL
 222-33-44-555
 $7,890.12
**UPDATED 9/30/26**
"""


def test_york_ships_rows_when_the_front_refuses_a_bare_user_agent(monkeypatch):
    mod = importlib.import_module(_PKG + "york_overage_claims")

    def handler(request: httpx.Request) -> httpx.Response:
        if not _is_full_browser_ua(request.headers.get("user-agent")):
            return httpx.Response(403, text="Forbidden")
        return httpx.Response(200, content=b"%PDF-1.7 fake",
                              headers={"content-type": "application/pdf"})

    class _Page:
        def extract_text(self):
            return YORK_TEXT

    class _Reader:
        def __init__(self, *_a, **_k):
            self.pages = [_Page()]

    import pypdf
    monkeypatch.setattr(pypdf, "PdfReader", _Reader)
    monkeypatch.setattr(mod, "_situs_for", lambda _m: None)
    _patch_client(monkeypatch, handler)

    rows = asyncio.run(mod.YorkOverageClaims().safe_run())
    assert sorted(r.parcel_id for r in rows) == ["111-22-33-444", "222-33-44-555"]
    assert {r.raw["tax_sale_overage"]["amount"] for r in rows} == {1234.56, 7890.12}
