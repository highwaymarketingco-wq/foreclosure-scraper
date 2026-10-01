"""`get_bytes(impersonate=True)` — the byte-fetch twin of `get_text`'s plain ->
curl-cffi escalation tier.

Added 2026-10-01 after `law_firms.finkel` was found silently returning 0 rows:
its PDF host (Cloudflare-fronted) 403s plain httpx, but `get_bytes()` had no
escalation path at all (unlike `get_text(impersonate=True)`), so the scraper's
`except Exception: continue` swallowed every fetch forever. Confirmed live
that a real Chrome TLS fingerprint (curl-cffi `impersonate="chrome"`) gets a
real 200 from the same URL. This test covers the new escalation logic in
isolation (no live network).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from foreclosure_scraper import http_client as hc


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code = status_code
        self.content = content
        self.request = httpx.Request("GET", "https://example.test/x.pdf")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class _FakeClient:
    def __init__(self, status_code: int, content: bytes = b""):
        self._status_code = status_code
        self._content = content

    async def get(self, url, **kw):
        return _FakeResponse(self._status_code, self._content)


def _fake_client_cm(status_code: int, content: bytes = b""):
    class _CM:
        async def __aenter__(self):
            return _FakeClient(status_code, content)

        async def __aexit__(self, *a):
            return False

    def _factory(**kw):
        return _CM()

    return _factory


@pytest.fixture(autouse=True)
def _clear_impersonate_hosts():
    hc._impersonate_hosts.clear()
    yield
    hc._impersonate_hosts.clear()


def test_plain_200_returns_bytes_without_escalation(monkeypatch):
    monkeypatch.setattr(hc, "client", _fake_client_cm(200, b"hello"))

    async def boom(*a, **k):
        raise AssertionError("should not escalate on a clean 200")

    monkeypatch.setattr(hc, "get_bytes_impersonate", boom)
    out = asyncio.run(hc.get_bytes("https://example.test/x.pdf"))
    assert out == b"hello"


def test_403_without_impersonate_flag_raises(monkeypatch):
    monkeypatch.setattr(hc, "client", _fake_client_cm(403, b"blocked"))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(hc.get_bytes("https://example.test/x.pdf"))


def test_403_with_impersonate_true_escalates_and_returns_real_bytes(monkeypatch):
    monkeypatch.setattr(hc, "client", _fake_client_cm(403, b"<html>cloudflare block</html>"))

    calls = []

    async def fake_impersonate(url, *, timeout=60.0):
        calls.append(url)
        return b"%PDF-1.4 real pdf bytes"

    monkeypatch.setattr(hc, "get_bytes_impersonate", fake_impersonate)
    out = asyncio.run(hc.get_bytes("https://example.test/x.pdf", impersonate=True))
    assert out == b"%PDF-1.4 real pdf bytes"
    assert calls == ["https://example.test/x.pdf"]
    assert "example.test" in hc._impersonate_hosts


def test_known_blocked_host_skips_the_doomed_plain_attempt(monkeypatch):
    hc._impersonate_hosts.add("example.test")

    async def boom(**kw):
        raise AssertionError("should not attempt the plain tier for a known-blocked host")

    monkeypatch.setattr(hc, "client", boom)

    async def fake_impersonate(url, *, timeout=60.0):
        return b"cached-tier bytes"

    monkeypatch.setattr(hc, "get_bytes_impersonate", fake_impersonate)
    out = asyncio.run(hc.get_bytes("https://example.test/x.pdf", impersonate=True))
    assert out == b"cached-tier bytes"


def test_404_is_never_retried_via_impersonation(monkeypatch):
    """A generic not-found isn't a fingerprint block — escalating would waste
    a fetch on a URL that will never come back."""
    monkeypatch.setattr(hc, "client", _fake_client_cm(404, b"not found"))

    async def boom(*a, **k):
        raise AssertionError("404 is not a block code; must not escalate")

    monkeypatch.setattr(hc, "get_bytes_impersonate", boom)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(hc.get_bytes("https://example.test/x.pdf", impersonate=True))
