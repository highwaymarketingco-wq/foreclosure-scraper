"""richland_flc.RichlandFLC.fetch(): a transient curl_cffi transport/timeout
error on the .xlsx download gets retried, not treated as "the whole scrape
failed."

Found 2026-11-07 (no-retry audit): this file's fetch() downloads the single
.xlsx document that holds 100% of its output by rolling its own
curl_cffi.requests.AsyncSession directly (per the module docstring,
deliberately bypassing http_client's get_bytes/get_bytes_impersonate, which
already have tenacity AsyncRetrying built in, because this WAF-fronted host
needs Chrome impersonation those helpers didn't give it). That means the
download never got http_client's retry coverage -- the only guard was a bare
try/except Exception that logs and returns [] on ANY failure, transient or
not. There is exactly one document fetch and it gates the entire scrape's
output; counties_sc.richland_flc is also listed in main.DATELESS_OK_SOURCES
(no fallback date window), so a run zeroed by one transient blip could not
self-heal later -- it would silently report an empty/healthy result until
someone noticed by hand. Same bug shape already fixed tonight in
arcgis_webmap.query_features, the Column legal-notice API scraper,
spartan_weekly_legals.py, and (also curl_cffi-based) bid4assets.py.

Nuance: like bid4assets.py, this call site uses curl_cffi.requests.AsyncSession,
not httpx -- curl_cffi raises its OWN exception hierarchy under
curl_cffi.requests.exceptions (ConnectionError, ConnectTimeout, ReadTimeout,
Timeout, DNSError, ...), confirmed in this project's venv (curl_cffi 0.13.0),
so these tests use REAL curl_cffi exception instances, not httpx ones. Mirrors
the fakes/structure of test_bid4assets_retry.py and
test_arcgis_webmap_query_features_retry.py.
"""
from __future__ import annotations

import asyncio
import zipfile
from io import BytesIO

import curl_cffi.requests as cc_requests
import pytest
from curl_cffi.requests.exceptions import ConnectTimeout, HTTPError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from foreclosure_scraper.scrapers.counties_sc import richland_flc as rflc

FAKE_HTML = (
    '<html><body><a href="/documents/copy-of-flc-owned-property-8-5-2026.xlsx">'
    "Download</a></body></html>"
)

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _make_minimal_xlsx() -> bytes:
    """One valid header row + one valid data row -- just enough for
    parse_flc_xlsx to yield exactly one real record, so a "download
    succeeded" test can assert on real output, not just a bare byte count.
    Same xl/sharedStrings.xml shape as test_richland_flc.py's own helper."""
    rows = [
        ["TAX MAP#", "OWNER NAME", "LOCATION", "OPENING BID"],
        ["01000-03-38-", "RICHLAND CO FORFEITED LAND COMM", "N/S HUBERT SIMPSON RD", "1300"],
    ]
    shared: list[str] = []

    def _sst_idx(s: str) -> int:
        if s not in shared:
            shared.append(s)
        return shared.index(s)

    sheet_rows = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, val in enumerate(row):
            col = chr(65 + c_idx)
            try:
                float(val)
                cells.append(f'<c r="{col}{r_idx}"><v>{val}</v></c>')
            except (TypeError, ValueError):
                idx = _sst_idx(val)
                cells.append(f'<c r="{col}{r_idx}" t="s"><v>{idx}</v></c>')
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    sheet_xml = (f'<?xml version="1.0"?><worksheet xmlns="{_NS}">'
                 f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    sst_xml = (f'<?xml version="1.0"?><sst xmlns="{_NS}" count="{len(shared)}" '
               f'uniqueCount="{len(shared)}">'
               + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        zf.writestr("xl/sharedStrings.xml", sst_xml)
    return buf.getvalue()


VALID_XLSX = _make_minimal_xlsx()


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(rflc, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _fake_page_fetch(monkeypatch):
    """fetch() first calls get_text() to find the .xlsx link -- give it a
    deterministic hit every time so every test reaches the download call
    site under test without touching the network."""
    async def _fake_get_text(url, **kwargs):
        return FAKE_HTML
    monkeypatch.setattr(rflc, "get_text", _fake_get_text)


class _FakeResp:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if not (200 <= self.status_code < 400):
            raise HTTPError(f"HTTP Error {self.status_code}")


class _FlakySession:
    """Simulates curl_cffi.requests.AsyncSession used as `async with
    AsyncSession() as s:` -- raises on the first `fail_times` calls to
    get(), then serves a real (terminal) response. Mirrors `_FlakySession` in
    test_bid4assets_retry.py and `_FlakyHttp` in
    test_arcgis_webmap_query_features_retry.py."""

    def __init__(self, fail_times: int, exc=None, resp: _FakeResp | None = None):
        self.fail_times = fail_times
        self.exc = exc or ConnectTimeout("boom")
        self.resp = resp if resp is not None else _FakeResp(content=VALID_XLSX)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, impersonate=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.resp


def _patch_async_session(monkeypatch, fake_session):
    """richland_flc.fetch() does `from curl_cffi.requests import AsyncSession`
    freshly inside its try block on every call, so patching the attribute on
    curl_cffi.requests itself (not on the richland_flc module) is what the
    local import actually resolves against -- same technique as
    test_bid4assets_retry.py's _patch_async_session."""
    monkeypatch.setattr(cc_requests, "AsyncSession", lambda *a, **kw: fake_session)


# --- the shared retry primitive itself, in isolation -----------------------
# (fetch()'s own outer try/except already catches-and-degrades on exhaustion,
# so this proves (b) directly against the real predicate the call site uses,
# independent of that pre-existing catch-all.)

def test_transient_exc_tuple_retries_then_raises_when_budget_exhausted():
    """(b): the predicate fetch()'s download call site uses really does raise
    once stop_after_attempt(3) is exhausted against a persistently transient
    curl_cffi error -- not an infinite retry loop/hang."""
    calls = {"n": 0}

    async def _drive():
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.001, max=0.002),
            retry=retry_if_exception_type(rflc._TRANSIENT_EXC),
            reraise=True,
        ):
            with attempt:
                calls["n"] += 1
                raise ConnectTimeout("boom")

    with pytest.raises(ConnectTimeout):
        asyncio.run(_drive())
    assert calls["n"] == 3


def test_transient_exc_tuple_does_not_match_http_error():
    """(c), predicate-level: curl_cffi's HTTPError (what r.raise_for_status()
    raises on a real bad status) must never be treated as transient."""
    assert not issubclass(HTTPError, rflc._TRANSIENT_EXC)


# --- RichlandFLC.fetch(): the one call site that gates 100% of the output --

def test_fetch_retries_a_transient_timeout_and_then_succeeds(monkeypatch):
    """(a): a transient transport/timeout error on the .xlsx download is
    retried, and the retried request's real data comes through -- not
    silently dropped."""
    fake = _FlakySession(fail_times=2)
    _patch_async_session(monkeypatch, fake)

    out = asyncio.run(rflc.RichlandFLC().fetch())

    assert fake.calls == 3
    assert len(out) == 1
    assert out[0].parcel_id == "01000-03-38-"
    assert out[0].owner_name == "RICHLAND CO FORFEITED LAND COMM"
    assert out[0].opening_bid == 1300.0


def test_fetch_transient_timeout_that_never_clears_degrades_not_hangs(monkeypatch):
    """(b), integrated: a transient error that never clears must still fall
    through to fetch()'s own pre-existing except-and-return-[] quickly, not
    hang or retry forever."""
    fake = _FlakySession(fail_times=99)
    _patch_async_session(monkeypatch, fake)

    out = asyncio.run(rflc.RichlandFLC().fetch())

    assert fake.calls == 3   # stop_after_attempt(3), then the outer except catches it
    assert out == []


def test_fetch_real_http_error_status_is_not_retried(monkeypatch):
    """(c), integrated: a real non-transport HTTP error status must fail
    immediately on attempt 1 -- the response comes back without raising from
    get(), so the retry predicate (which only fires on an exception) is
    never even consulted."""
    fake = _FlakySession(fail_times=0, resp=_FakeResp(status_code=503))
    _patch_async_session(monkeypatch, fake)

    out = asyncio.run(rflc.RichlandFLC().fetch())

    assert fake.calls == 1   # a real bad status is not a transport/timeout error
    assert out == []


def test_fetch_a_read_timeout_is_also_retried(monkeypatch):
    """A sibling transient type (ReadTimeout, not just ConnectTimeout) is
    retried too -- the predicate isn't accidentally narrowed to one class."""
    from curl_cffi.requests.exceptions import ReadTimeout
    fake = _FlakySession(fail_times=1, exc=ReadTimeout("slow"))
    _patch_async_session(monkeypatch, fake)

    out = asyncio.run(rflc.RichlandFLC().fetch())

    assert fake.calls == 2
    assert len(out) == 1
