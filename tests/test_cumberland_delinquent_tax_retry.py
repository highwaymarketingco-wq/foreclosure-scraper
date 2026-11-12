"""cumberland_delinquent_tax: a transient transport error on the PDF fetch gets retried, not
treated as "the whole scrape failed."

The file's only network call is a bare `client(timeout=120.0)` + `c.get(url)` fetch of one
county PDF, immediately followed by a manual status/content-type check that raises
RuntimeError on failure -- no retry loop around it. Same root cause, same fix, as the Column
legal-notice API scraper, spartan_weekly_legals.py and arcgis_webmap.query_features() fixed
earlier the same night: http_client.client()'s own docstring says every caller is expected to
wrap its own AsyncRetrying, and this file didn't. Blast radius is single-point-of-failure: one
request's result is the entire scrape's output, and per the file's own docstring this slug is
in main.DATELESS_OK_SOURCES with no fallback date window, so a transient-blip-caused zero
cannot self-heal later.
"""
from __future__ import annotations

import asyncio
import io
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from pypdf import PdfWriter
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import cumberland_delinquent_tax as M


def _minimal_pdf_bytes() -> bytes:
    """A real, minimal, parseable (blank, textless) PDF -- starts with b"%PDF" like the
    content check requires, and pypdf.PdfReader can open it for real (no PdfReader mocking)."""
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


PDF_BYTES = _minimal_pdf_bytes()


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _env_on(monkeypatch):
    # Make sure the dormant gate never fires regardless of the host's own env.
    monkeypatch.delenv(M.ENV_OFF, raising=False)
    monkeypatch.setenv("FORECLOSURE_CUMBERLAND_TAX_YEAR", "2025")


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return MagicMock(status_code=200, content=PDF_BYTES)

    monkeypatch.setattr(M, "client", _fake_client(get))
    out = asyncio.run(M.CumberlandDelinquentTax().fetch())
    assert calls["n"] == 3
    assert list(out) == []   # blank page -> no records, but a clean (non-raising) result


def test_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return MagicMock(status_code=200, content=PDF_BYTES)

    monkeypatch.setattr(M, "client", _fake_client(get))
    out = asyncio.run(M.CumberlandDelinquentTax().fetch())
    assert calls["n"] == 2
    assert list(out) == []


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(M.CumberlandDelinquentTax().fetch())
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up -- not an infinite hang


def test_a_real_bad_http_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        return MagicMock(status_code=503, content=b"")

    monkeypatch.setattr(M, "client", _fake_client(get))
    with pytest.raises(RuntimeError, match="HTTP 503"):
        asyncio.run(M.CumberlandDelinquentTax().fetch())
    assert calls["n"] == 1   # a real bad status is not a transport/timeout error


def test_a_200_with_a_non_pdf_body_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        return MagicMock(status_code=200, content=b"<html>not a pdf</html>")

    monkeypatch.setattr(M, "client", _fake_client(get))
    with pytest.raises(RuntimeError, match="HTTP 200"):
        asyncio.run(M.CumberlandDelinquentTax().fetch())
    assert calls["n"] == 1   # HTTP-200-with-wrong-body is not a transport/timeout error either
