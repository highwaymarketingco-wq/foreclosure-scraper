"""nc_its_public_tax: a transient transport/timeout error on any of this module's three bare
httpx.AsyncClient call sites gets retried, not treated as "the whole county's result is gone."

Found 2026-11-07 (gap-sweep continuation, same root cause already fixed tonight for the Column
legal-notice API scraper, spartan_weekly_legals.py, and the shared arcgis_webmap.query_features()):
this file builds its own raw httpx.AsyncClient (no transport= retry config) and never imported
tenacity -- zero retry cushioning on any of its three network calls:

  1. fetch_year()'s once-per-(county, year) search-init POST to GetSearchTablePartial
     (full_model vs legacy branch).
  2. fetch_year()'s per-page POST to GetSearchTableData inside the paging loop -- the
     highest-volume site, up to MAX_PAGES_PER_YEAR calls per year, for up to YEARS_BACK years.
  3. NcItsPublicTax.fetch()'s once-per-county session-cookie GET to TaxBillSearch.

fetch_year() has no try/except of its own, so a blip on any page -- even deep into a year's
pagination -- loses every page already parsed for that call, not just the one page in flight;
the exception then propagates into fetch()'s per-county try/except, which zeroes that county's
WHOLE result for the run (every year, every bill) and marks it failed/incomplete. Because this
source is registered in main.py's dateless-sources set (no sale date, no fallback date window),
a county zeroed this way cannot self-heal later -- it silently reports failed until a human
notices. A real bad HTTP status, or an HTTP-200-with-corrupted-body, must still fail immediately
and unretried (raise_for_status() / the JSON-shape RuntimeErrors are deliberate hard-fails).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

import foreclosure_scraper.scrapers.counties_nc.nc_its_public_tax as m

ONSLOW = m.PORTALS["Onslow"]          # legacy (non full_model) portal
PERSON = m.PORTALS["Person"]          # full_model (newer-build) portal

COLS_DESC = ["TaxYear", "BillNumber", "AccountNumber", "AccountName1", "Description",
             "OriginalBillAmount", "TotalDue"]
_EMPTY_PAGE = {"total": 1, "numRecords": 0, "rows": []}


@pytest.fixture
def _fast(monkeypatch):
    monkeypatch.setattr(m, "PACE_S", 0.0)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same trick the proven reference test (test_arcgis_webmap_query_features_retry.py)
    uses: keep the real exponential-jitter curve but shrink it to microseconds so the
    (b) exhausted-retry-budget tests don't actually sleep ~1s + ~2s between attempts."""
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _flaky_transport(fail_path_suffix: str, fail_times: int, exc: Exception | None = None):
    """A MockTransport where every GET succeeds, every POST whose path does NOT end in
    `fail_path_suffix` succeeds normally (whichever of the two real endpoints that is), and
    a POST to `fail_path_suffix` raises `exc` the first `fail_times` calls then serves a
    real (terminal, empty) page. Returns (transport, calls) where calls['n'] counts only the
    calls to the path under test."""
    exc = exc or httpx.ConnectTimeout("boom")
    calls = {"n": 0}

    def _ok(path: str) -> httpx.Response:
        if path.endswith("GetSearchTablePartial"):
            return httpx.Response(200, text="<div>fragment</div>")
        return httpx.Response(200, json=_EMPTY_PAGE)

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "GET":
            return httpx.Response(200, text="<html>search</html>")
        if not path.endswith(fail_path_suffix):
            return _ok(path)
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise exc
        return _ok(path)

    return httpx.MockTransport(handler), calls


# =================================================================================================
# Site 2 -- fetch_year()'s per-page GetSearchTableData POST (legacy branch). The highest-volume
# call site in the file: up to MAX_PAGES_PER_YEAR pages/year, PACE_S apart, up to YEARS_BACK years.
# =================================================================================================

def test_table_data_page_retries_a_transient_connect_timeout_then_succeeds(_fast):
    transport, calls = _flaky_transport("GetSearchTableData", fail_times=2)

    async def go():
        async with httpx.AsyncClient(transport=transport) as c:
            return await m.fetch_year(c, ONSLOW, 2025)

    bills, stats = asyncio.run(go())
    assert calls["n"] == 3             # 2 failed attempts + 1 that finally got through
    assert bills == [] and stats["pages"] == 1


def test_table_data_page_read_timeout_is_also_retried(_fast):
    transport, calls = _flaky_transport("GetSearchTableData", fail_times=1, exc=httpx.ReadTimeout("slow"))

    async def go():
        async with httpx.AsyncClient(transport=transport) as c:
            return await m.fetch_year(c, ONSLOW, 2025)

    bills, stats = asyncio.run(go())
    assert calls["n"] == 2
    assert bills == []


def test_table_data_page_gives_up_after_the_retry_budget_not_an_infinite_hang(_fast):
    transport, calls = _flaky_transport("GetSearchTableData", fail_times=99)

    async def go():
        async with httpx.AsyncClient(transport=transport) as c:
            return await m.fetch_year(c, ONSLOW, 2025)

    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(go())
    assert calls["n"] == 3             # stop_after_attempt(3), then it really gives up


def test_table_data_page_a_real_bad_status_is_not_retried(_fast):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, text="<html>search</html>")
        if req.url.path.endswith("GetSearchTablePartial"):
            return httpx.Response(200, text="<div>fragment</div>")
        calls["n"] += 1
        return httpx.Response(503)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await m.fetch_year(c, ONSLOW, 2025)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(go())
    assert calls["n"] == 1             # a real bad status is not a transport/timeout error


def test_table_data_page_a_corrupted_200_body_is_not_retried(_fast):
    """The 'HTTP-200-with-error-body' silent-death shape (session lost) is a deliberate hard
    fail, same as the reference fix -- never wrapped in the retry."""
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, text="<html>search</html>")
        if req.url.path.endswith("GetSearchTablePartial"):
            return httpx.Response(200, text="<div>fragment</div>")
        calls["n"] += 1
        return httpx.Response(200, text="<html>Session expired</html>")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await m.fetch_year(c, ONSLOW, 2025)

    with pytest.raises(RuntimeError, match="not JSON"):
        asyncio.run(go())
    assert calls["n"] == 1


def test_full_model_table_data_page_also_retries_a_transient_timeout(_fast):
    """The full_model branch (form-encoded `data=`, not `json=`) of the same per-page call
    site must carry the identical retry cushioning."""
    m._FORM_FIELDS[PERSON.base] = ["TaxYear", "UnpaidBillsOnly"]
    cols_html = "".join(f'<th id="{c}">x</th>' for c in COLS_DESC)
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, text="x")
        if req.url.path.endswith("GetSearchTablePartial/"):
            return httpx.Response(200, text=cols_html
                                   + '<script>PopulateTable("PayTaxBills", x)</script>')
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx.ConnectTimeout("boom")
        return httpx.Response(200, json=_EMPTY_PAGE)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await m.fetch_year(c, PERSON, 2025)

    bills, stats = asyncio.run(go())
    assert calls["n"] == 3
    assert bills == []


# =================================================================================================
# Site 1 -- fetch_year()'s once-per-year search-init POST to GetSearchTablePartial (legacy branch).
# =================================================================================================

def test_search_init_partial_retries_a_transient_timeout_then_succeeds(_fast):
    transport, calls = _flaky_transport("GetSearchTablePartial", fail_times=2)

    async def go():
        async with httpx.AsyncClient(transport=transport) as c:
            return await m.fetch_year(c, ONSLOW, 2025)

    bills, stats = asyncio.run(go())
    assert calls["n"] == 3
    assert bills == []


def test_search_init_partial_gives_up_after_the_retry_budget_not_an_infinite_hang(_fast):
    transport, calls = _flaky_transport("GetSearchTablePartial", fail_times=99)

    async def go():
        async with httpx.AsyncClient(transport=transport) as c:
            return await m.fetch_year(c, ONSLOW, 2025)

    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(go())
    assert calls["n"] == 3


def test_search_init_partial_a_real_bad_status_is_not_retried(_fast):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, text="<html>search</html>")
        calls["n"] += 1
        return httpx.Response(500)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await m.fetch_year(c, ONSLOW, 2025)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(go())
    assert calls["n"] == 1


def test_full_model_search_init_partial_also_retries_a_transient_timeout(_fast):
    """The full_model branch of the same search-init call site must carry the identical
    retry cushioning."""
    m._FORM_FIELDS[PERSON.base] = ["TaxYear", "UnpaidBillsOnly"]
    cols_html = "".join(f'<th id="{c}">x</th>' for c in COLS_DESC)
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, text="x")
        if not req.url.path.endswith("GetSearchTablePartial/"):
            return httpx.Response(200, json=_EMPTY_PAGE)       # the per-page call, unaffected
        calls["n"] += 1
        if calls["n"] <= 1:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, text=cols_html
                               + '<script>PopulateTable("PayTaxBills", x)</script>')

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await m.fetch_year(c, PERSON, 2025)

    bills, stats = asyncio.run(go())
    assert calls["n"] == 2
    assert bills == []


# =================================================================================================
# Site 3 -- NcItsPublicTax.fetch()'s once-per-county session-cookie GET to TaxBillSearch. Exercised
# at the class level (not fetch_year) because the real code opens its own httpx.AsyncClient inside
# fetch() -- same monkeypatch.setattr(httpx, "AsyncClient", Fake) pattern the module's own existing
# test file (test_nc_its_public_tax.py) already uses for this exact reason.
# =================================================================================================

def test_session_get_retries_a_transient_timeout_then_succeeds(monkeypatch, _fast):
    monkeypatch.setenv("ITS_TAX_COUNTIES", "Onslow")
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            calls["n"] += 1
            if calls["n"] <= 2:
                raise httpx.ConnectTimeout("boom")
            return httpx.Response(200, text="<html>search</html>")
        if req.url.path.endswith("GetSearchTablePartial"):
            return httpx.Response(200, text="<div>fragment</div>")
        return httpx.Response(200, json=_EMPTY_PAGE)

    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    s = m.NcItsPublicTax()
    s.limit = 5
    out = asyncio.run(s.fetch())
    assert calls["n"] == 3
    assert "failed" not in s.county_stats["Onslow"]      # the county's run was NOT zeroed
    assert out == []                                     # (empty rows, but a clean, complete read)


def test_session_get_gives_up_after_the_retry_budget_and_only_that_county_is_marked_failed(
        monkeypatch, _fast):
    """Proves (b) at the class level: the retry budget really is bounded (no infinite hang
    on fetch()), AND that the existing per-county blast-radius containment still works
    exactly as documented -- the exhausted retry is caught by fetch()'s own try/except and
    marks just this county failed, it does not propagate out of fetch() itself."""
    monkeypatch.setenv("ITS_TAX_COUNTIES", "Onslow")
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            calls["n"] += 1
            raise httpx.ConnectTimeout("boom")
        return httpx.Response(200, text="unused")       # never reached

    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    s = m.NcItsPublicTax()
    s.limit = 5
    out = asyncio.run(s.fetch())                         # must return, never hang or raise out
    assert out == []
    assert calls["n"] == 3                               # stop_after_attempt(3), then gave up
    assert "failed" in s.county_stats["Onslow"]


def test_session_get_a_real_bad_status_is_not_retried(monkeypatch, _fast):
    monkeypatch.setenv("ITS_TAX_COUNTIES", "Onslow")
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            calls["n"] += 1
            return httpx.Response(500)
        return httpx.Response(200, text="unused")        # never reached

    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    s = m.NcItsPublicTax()
    s.limit = 5
    out = asyncio.run(s.fetch())
    assert out == []
    assert calls["n"] == 1                                # a real bad status is not retried
    assert "failed" in s.county_stats["Onslow"]
