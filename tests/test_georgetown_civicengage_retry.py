"""georgetown_civicengage: transient transport errors on the file's bare network
calls get retried, not treated as "the whole branch failed."

Gap-sweep 2026-10-17: this file makes 5 distinct `c.get()` calls via the shared
http_client.client() wrapper (which does not retry internally -- its own
docstring says callers must wrap their own AsyncRetrying). The FLC landing-page
fetch (line 488) already had a crude manual 2-try loop from a documented 10/8
incident (see test_georgetown_flc_retry.py) and is untouched here. The other
four -- the Tax-Sale landing fetch, the MIE landing fetch, and the two
DocumentCenter doc fetchers `_get_pdf`/`_get_doc` -- had zero retry cushioning
at all. `_get_pdf` is the most severe: the FLC and Tax branches each call it
once and `break` on success, so one transient blip there used to silently lose
the entire FLC list or entire Tax-Sale list for the run, with no fallback date
window (Georgetown is in main.DATELESS_OK_SOURCES) to self-heal later.
`_get_doc` sits in the per-item MIE roster loop, so a failure there only used
to drop one month's rows. Same root-cause shape, same fix, as already shipped
tonight for the Column legal-notice API scraper, spartan_weekly_legals.py, and
arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.counties_sc import georgetown_civicengage as mod


class _Resp:
    def __init__(self, status_code: int = 200, content: bytes = b"%PDF-1.4", text: str = ""):
        self.status_code = status_code
        self.content = content
        self.text = text


class _FlakyClient:
    """Raises on the first `fail_times` calls to .get(), then serves `resp`."""

    def __init__(self, fail_times: int, exc=None, resp: _Resp | None = None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.resp = resp if resp is not None else _Resp()
        self.calls = 0

    async def get(self, url, *a, **k):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.resp


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Same technique as test_arcgis_webmap_query_features_retry.py: make the
    # exponential-jitter backoff effectively instant so the retry tests run fast.
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


DOC_URL = "https://www.gtcountysc.gov/DocumentCenter/View/1/2026-FLC-LIST"


# ---------------------------------------------------------------------------
# _get_pdf -- the call site named in the fix (line 586), a true single-point-
# of-failure per branch (FLC / Tax-Sale each call it once and break on success).
# ---------------------------------------------------------------------------

def test_get_pdf_transient_timeout_is_retried_and_then_succeeds():
    c = _FlakyClient(fail_times=2)
    data = asyncio.run(mod.GeorgetownCivicEngage()._get_pdf(c, DOC_URL))
    assert c.calls == 3
    assert data == b"%PDF-1.4"


def test_get_pdf_timeout_that_never_clears_still_returns_none_not_hangs():
    c = _FlakyClient(fail_times=99)
    data = asyncio.run(mod.GeorgetownCivicEngage()._get_pdf(c, DOC_URL))
    assert c.calls == 3   # stop_after_attempt(3), then the bare except swallows the reraise
    assert data is None


def test_get_pdf_real_bad_status_is_not_retried():
    c = _FlakyClient(fail_times=0, resp=_Resp(status_code=503, content=b""))
    data = asyncio.run(mod.GeorgetownCivicEngage()._get_pdf(c, DOC_URL))
    assert c.calls == 1   # a real bad status is not a transport/timeout error
    assert data is None


def test_get_pdf_non_pdf_magic_is_not_retried():
    # Same shape as the real bad-status case: a well-formed 200 response that
    # just isn't a PDF must not trigger a retry either.
    c = _FlakyClient(fail_times=0, resp=_Resp(status_code=200, content=b"<html>not a pdf"))
    data = asyncio.run(mod.GeorgetownCivicEngage()._get_pdf(c, DOC_URL))
    assert c.calls == 1
    assert data is None


# ---------------------------------------------------------------------------
# _get_doc -- same pattern, the per-item MIE monthly-roster call site (line 602).
# ---------------------------------------------------------------------------

def test_get_doc_transient_timeout_is_retried_and_then_succeeds():
    ole_bytes = b"\xd0\xcf\x11\xe0fake-ole-payload"
    c = _FlakyClient(fail_times=2, resp=_Resp(content=ole_bytes))
    data = asyncio.run(mod.GeorgetownCivicEngage()._get_doc(c, DOC_URL))
    assert c.calls == 3
    assert data == ole_bytes


def test_get_doc_timeout_that_never_clears_still_returns_none_not_hangs():
    c = _FlakyClient(fail_times=99)
    data = asyncio.run(mod.GeorgetownCivicEngage()._get_doc(c, DOC_URL))
    assert c.calls == 3
    assert data is None


def test_get_doc_real_bad_status_is_not_retried():
    c = _FlakyClient(fail_times=0, resp=_Resp(status_code=404, content=b""))
    data = asyncio.run(mod.GeorgetownCivicEngage()._get_doc(c, DOC_URL))
    assert c.calls == 1
    assert data is None


def test_get_doc_unknown_magic_is_not_retried():
    c = _FlakyClient(fail_times=0, resp=_Resp(status_code=200, content=b"garbage"))
    data = asyncio.run(mod.GeorgetownCivicEngage()._get_doc(c, DOC_URL))
    assert c.calls == 1
    assert data is None


# ---------------------------------------------------------------------------
# Landing-page fetches (Tax-Sale line 509, MIE line 530) -- confirms the fix
# saves the WHOLE branch from a single transient blip, end-to-end via fetch().
# ---------------------------------------------------------------------------

class _LandingClient:
    """Fakes `async with client(...) as c:`. One nominated landing-page URL is
    flaky (fails `fail_times` times then serves `ok_html`); every other URL
    (the other two landing pages) returns an empty-but-200 page so those
    branches are no-ops."""

    def __init__(self, flaky_url: str, fail_times: int, ok_html: str):
        self.flaky_url = flaky_url
        self.fail_times = fail_times
        self.ok_html = ok_html
        self.calls: dict[str, int] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, *a, **k):
        self.calls[url] = self.calls.get(url, 0) + 1
        if url == self.flaky_url:
            if self.calls[url] <= self.fail_times:
                raise httpx.ConnectTimeout("boom")
            return _Resp(status_code=200, text=self.ok_html)
        return _Resp(status_code=200, text="")


def test_tax_page_landing_fetch_transient_timeout_is_retried_not_branch_zeroed(monkeypatch):
    cli = _LandingClient(
        mod.TAX_PAGE, fail_times=2,
        ok_html='<a href="/DocumentCenter/View/9/2025-Tax-Sale-List">2025 Tax Sale List</a>',
    )
    monkeypatch.setattr(mod, "client", lambda *a, **k: cli)

    async def fake_pdf(self, c, url):
        return b"%PDF-1.4"

    monkeypatch.setattr(mod.GeorgetownCivicEngage, "_get_pdf", fake_pdf)
    monkeypatch.setattr(mod, "_pdf_text", lambda data: "text")
    tax_row = Listing(source=mod.GeorgetownCivicEngage.slug, source_url="https://example.invalid/tax",
                      listing_type=ListingType.TAX_SALE, state="SC", county="Georgetown",
                      parcel_id="05-0017-114-00-00")
    monkeypatch.setattr(mod, "parse_tax", lambda text, url: [tax_row])

    rows = list(asyncio.run(mod.GeorgetownCivicEngage().fetch()))
    assert cli.calls[mod.TAX_PAGE] == 3
    assert [r.parcel_id for r in rows] == ["05-0017-114-00-00"]


def test_mie_page_landing_fetch_transient_timeout_is_retried_not_branch_zeroed(monkeypatch):
    cli = _LandingClient(
        mod.MIE_PAGE, fail_times=2,
        ok_html='<a href="/DocumentCenter/View/3/May-2026-foreclosure-sale.pdf">May 2026</a>',
    )
    monkeypatch.setattr(mod, "client", lambda *a, **k: cli)

    async def fake_doc(self, c, url):
        return b"%PDF-1.4"

    monkeypatch.setattr(mod.GeorgetownCivicEngage, "_get_doc", fake_doc)
    monkeypatch.setattr(mod, "_pdf_text", lambda data: "text")
    mie_row = Listing(source=mod.GeorgetownCivicEngage.slug, source_url="https://example.invalid/mie",
                      listing_type=ListingType.FORECLOSURE_SALE, state="SC", county="Georgetown",
                      parcel_id="04-0133-037-00-00")
    monkeypatch.setattr(mod, "parse_mie", lambda text, url, label="": [mie_row])

    rows = list(asyncio.run(mod.GeorgetownCivicEngage().fetch()))
    assert cli.calls[mod.MIE_PAGE] == 3
    assert [r.parcel_id for r in rows] == ["04-0133-037-00-00"]


def test_tax_page_real_bad_status_is_not_retried(monkeypatch):
    cli = _LandingClient(mod.TAX_PAGE, fail_times=0, ok_html="")
    # Force a real non-transport failure path: status 500 (not an exception).
    orig_get = cli.get

    async def get_500(url, *a, **k):
        cli.calls[url] = cli.calls.get(url, 0) + 1
        if url == mod.TAX_PAGE:
            return _Resp(status_code=500, text="")
        return _Resp(status_code=200, text="")

    cli.get = get_500
    monkeypatch.setattr(mod, "client", lambda *a, **k: cli)

    rows = list(asyncio.run(mod.GeorgetownCivicEngage().fetch()))
    assert cli.calls[mod.TAX_PAGE] == 1   # a real bad status is not a transport/timeout error
    assert rows == []
