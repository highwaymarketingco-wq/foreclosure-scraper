"""qpaybill_delinquent_roll: the page-2+ pagination POST inside _walk_prefix, and the
per-parcel detail GETs in fetch_details_paced/fetch_details, get the same
transport/timeout retry cushioning the prefix's own first-page search already has.

Found 2026-11-07 (gap-sweep). _walk_prefix retries a prefix's FIRST search up to 3x
with backoff (the `for attempt in range(3)` loop near the top of the function), but
the SAME prefix's page-2+ continuation -- a request or two later, inside the
`while len(rows) >= PAGE_CAP:` pagination loop -- had a bare try/except with ZERO
retry: `except Exception: stats["errors"] += 1; log.warning(...); break`. A single
transient transport blip there permanently stopped that prefix's pagination,
discarding every row still on its unread later pages -- rows the prefix's own first
page just proved the portal can serve. Per the module's own comments a busy letter
can need several pages (Barnwell's busiest needed 3), so this was a live,
non-hypothetical loss path, not a hypothetical one.

fetch_details_paced (wired into fetch()'s staged detail pass) and its dead-but-
identical-shape twin fetch_details share the same bare-GET-with-zero-retry shape on
their own per-parcel detail fetch. Fixed alongside the primary bug for robustness,
since both are the exact same unprotected-network-call shape in this one file.

Same root-cause shape already fixed tonight for the Column legal-notice API
scrapers, spartan_weekly_legals.py and arcgis_webmap.query_features() -- modeled on
test_arcgis_webmap_query_features_retry.py's fixture/fake-client style.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import qpaybill_delinquent_roll as qpr

PAGE_CAP = qpr.PAGE_CAP


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(qpr, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


class _FakeResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.content = text.encode()


# ---------------------------------------------------------------------------
# _walk_prefix: the page-2+ pagination POST (the primary, confirmed bug: line 749
# in the original file, `rows, vs = await _post(client, sub, vs, prefix, page)`
# inside the pagination while-loop).
# ---------------------------------------------------------------------------

#: A page carries its own fresh VIEWSTATE tokens (so _fresh_vs/the prefix's own
#: first-search retry loop -- unrelated to this fix -- is satisfied on attempt 1)
#: plus a results grid. Owners all start with "A" so _all_match accepts every page.
_VS_HTML = ('<input type="hidden" id="__VIEWSTATE" value="vs1"/>'
            '<input type="hidden" id="__VIEWSTATEGENERATOR" value="g1"/>'
            '<input type="hidden" id="__EVENTVALIDATION" value="ev1"/>')


def _grid_row(ident: str) -> str:
    return (f"<tr><td>N{ident}</td><td>ASMITH<br/>1 MAIN ST</td><td>2025</td>"
            f"<td>PROP OF X</td><td>{ident}</td><td>RealEstate</td>"
            f"<td>Unpaid</td><td></td><td>$100.00</td></tr>")


def _grid_html(idents: list[str]) -> str:
    return "<table>" + "".join(_grid_row(i) for i in idents) + "</table>"


#: Page 1 of prefix "A": a FULL page (== PAGE_CAP rows), so _walk_prefix's pagination
#: while-loop is entered exactly like a real busy letter would be.
_PAGE1_HTML = _VS_HTML + _grid_html([f"045-00-00-{n:03d}" for n in range(PAGE_CAP)])
#: Page 2, once it finally succeeds: fewer than PAGE_CAP rows, so pagination ends.
_PAGE2_OK_HTML = _VS_HTML + _grid_html(["045-00-00-999"])


class _FakePrefixClient:
    """Mimics httpx.AsyncClient for _walk_prefix. .get always serves a fresh
    viewstate page (the prefix's OWN first-search retry loop, unrelated to and
    unchanged by this fix, must succeed on its first attempt). .post serves a full
    page on the first search (page=None, __EVENTARGUMENT empty) so the pagination
    while-loop is entered, then behaves per the page2_* knobs for every page=2+
    request -- the call this fix protects.
    """

    def __init__(self, page2_fail_times: int = 0, page2_exc: Exception | None = None,
                page2_bad_status: int | None = None):
        self.page2_calls = 0
        self.page2_fail_times = page2_fail_times
        self.page2_exc = page2_exc or httpx.ConnectTimeout("boom")
        self.page2_bad_status = page2_bad_status

    async def get(self, url, **kw):
        return _FakeResp(_VS_HTML)

    async def post(self, url, data=None, **kw):
        if not (data or {}).get("__EVENTARGUMENT"):
            return _FakeResp(_PAGE1_HTML)           # the prefix's first search
        self.page2_calls += 1
        if self.page2_bad_status is not None:
            return _FakeResp("<html></html>", status_code=self.page2_bad_status)
        if self.page2_calls <= self.page2_fail_times:
            raise self.page2_exc
        return _FakeResp(_PAGE2_OK_HTML)


def _fresh_stats() -> dict:
    return {"queries": 0, "errors": 0, "page_capped_prefixes": 0,
            "pager_stalled": 0, "drifted": 0}


def test_a_transient_timeout_on_page_2_is_retried_and_then_succeeds():
    client = _FakePrefixClient(page2_fail_times=2)
    sink: dict = {}
    stats = _fresh_stats()
    asyncio.run(qpr._walk_prefix(client, "testsub", "A", qpr._Budget(10), sink, stats))
    assert client.page2_calls == 3
    assert stats["errors"] == 0
    # The retried page's own row actually landed in the sink, not just "didn't raise".
    assert ("045-00-00-999", "2025", "N045-00-00-999") in sink
    assert len(sink) == PAGE_CAP + 1


def test_a_connect_timeout_that_never_clears_still_gives_up_not_hangs():
    client = _FakePrefixClient(page2_fail_times=99)
    sink: dict = {}
    stats = _fresh_stats()
    asyncio.run(qpr._walk_prefix(client, "testsub", "A", qpr._Budget(10), sink, stats))
    assert client.page2_calls == 3   # stop_after_attempt(3), then gives up -- not an infinite loop
    assert stats["errors"] == 1
    # Page 1's own 25 rows are kept (this prefix's already-absorbed pages are never
    # discarded); only the still-failing page 2 is missing.
    assert len(sink) == PAGE_CAP
    assert ("045-00-00-999", "2025", "N045-00-00-999") not in sink


def test_a_read_timeout_on_page_2_is_also_retried():
    client = _FakePrefixClient(page2_fail_times=1, page2_exc=httpx.ReadTimeout("slow"))
    sink: dict = {}
    stats = _fresh_stats()
    asyncio.run(qpr._walk_prefix(client, "testsub", "A", qpr._Budget(10), sink, stats))
    assert client.page2_calls == 2
    assert stats["errors"] == 0
    assert len(sink) == PAGE_CAP + 1


def test_a_real_bad_status_on_page_2_is_not_retried():
    """A real portal outage (QPayBillUnavailable, raised by _require_ok from inside
    _post()) is not a transport/timeout blip and must fail on attempt 1, exactly
    like the already-shipped arcgis_webmap/spartan_weekly_legals fixes."""
    client = _FakePrefixClient(page2_bad_status=503)
    sink: dict = {}
    stats = _fresh_stats()
    asyncio.run(qpr._walk_prefix(client, "testsub", "A", qpr._Budget(10), sink, stats))
    assert client.page2_calls == 1   # a real bad status is not a transport/timeout error
    assert stats["errors"] == 1
    assert len(sink) == PAGE_CAP


# ---------------------------------------------------------------------------
# fetch_details_paced: the staged detail pass's own per-parcel GET (wired into
# production via fetch()'s detail_county()).
# ---------------------------------------------------------------------------

#: Enough of a real detail page for parse_detail() to return a non-empty dict, so a
#: successful fetch is provably PARSED, not just "didn't raise".
_DETAIL_BODY = ("<div>Notice #: 000207255</div><div>Status: Unpaid</div>"
                "<div>Balance Due:$130.55</div>")


class _FakeDetailClient:
    def __init__(self, fail_times: int = 0, exc: Exception | None = None):
        self.calls = 0
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")

    async def get(self, url, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(_DETAIL_BODY)


_HREF = "TaxesDetailsType4.aspx?receiptNo=R1"


def test_fetch_details_paced_retries_a_transient_timeout_then_succeeds():
    client = _FakeDetailClient(fail_times=2)
    stats: dict = {}
    got = asyncio.run(qpr.fetch_details_paced(client, "testsub", [_HREF], stats, pace_s=0))
    assert client.calls == 3
    assert stats.get("detail_errors", 0) == 0
    assert got["R1"]["balance_due"] == 130.55


def test_fetch_details_paced_gives_up_not_hangs_when_the_timeout_never_clears():
    client = _FakeDetailClient(fail_times=99)
    stats: dict = {}
    got = asyncio.run(qpr.fetch_details_paced(client, "testsub", [_HREF], stats, pace_s=0))
    assert client.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite loop
    assert stats.get("detail_errors", 0) == 1
    assert got == {}   # the pre-existing per-href except swallows it; no row, no hang


def test_fetch_details_paced_does_not_retry_a_non_transport_exception():
    """fetch_details_paced never checks HTTP status (no _require_ok call on this
    path), so the real-error analogue here is any exception that is not a
    transport/timeout blip -- it must still fail on attempt 1, unretried."""
    class _BadDetailClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, **kw):
            self.calls += 1
            raise ValueError("not a transport/timeout error")

    client = _BadDetailClient()
    stats: dict = {}
    got = asyncio.run(qpr.fetch_details_paced(client, "testsub", [_HREF], stats, pace_s=0))
    assert client.calls == 1
    assert stats.get("detail_errors", 0) == 1
    assert got == {}


# ---------------------------------------------------------------------------
# fetch_details: the dead-but-identical-shape twin (never called from fetch(), but
# fixed alongside fetch_details_paced since it is the exact same unprotected call).
# ---------------------------------------------------------------------------

def test_fetch_details_retries_a_transient_timeout_then_succeeds():
    client = _FakeDetailClient(fail_times=2)
    stats: dict = {}
    got = asyncio.run(qpr.fetch_details(client, "testsub", [_HREF], qpr._Budget(10), stats))
    assert client.calls == 3
    assert got["R1"]["balance_due"] == 130.55


def test_fetch_details_gives_up_not_hangs_when_the_timeout_never_clears():
    client = _FakeDetailClient(fail_times=99)
    stats: dict = {}
    got = asyncio.run(qpr.fetch_details(client, "testsub", [_HREF], qpr._Budget(10), stats))
    assert client.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite loop
    assert stats.get("detail_errors", 0) == 1
    assert got == {}
