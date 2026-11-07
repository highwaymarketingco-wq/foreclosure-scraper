"""counties_nc.transylvania_delinquent_tax.TransylvaniaDelinquentTax.fetch: a transient
transport/timeout error on any of its three real network calls -- the one-time session-
cookie seed GET, the per-year search-criteria/data POST pair, or the per-parcel ViewTaxBill
detail POST -- gets retried, not treated as "that part of the scrape failed."

Found 2026-11-07 (gap-sweep): all three calls go through a raw httpx.AsyncClient this file
constructs itself (not the shared, already-must-wrap-its-own-retries http_client.client()
helper -- deliberate per this module's own docstring, since client() would serialize ~450
parallel detail calls into many minutes), each guarded only by a bare try/except with zero
retry. The seed GET (1) is the worst of the three: a true single point of failure -- fetch()
swallows the exception into `return []` itself, so a transient blip there used to zero the
WHOLE run (no years, no bills, no enrichment), with no fallback date window to self-heal
(this slug is registered in main.DATELESS_OK_SOURCES). The per-year POST pair (2) only loses
that one year's rows, but a transient blip there used to count as a genuinely-empty year
toward _CONSECUTIVE_EMPTY_STOP and could truncate the multi-year back-read early. The
per-parcel ViewTaxBill POST (3) only drops that one parcel's owner-mailing/parcel/value
enrichment -- the bill-grid lead itself still ships, just thinner. Same bug shape already
fixed tonight in the Column legal-notice API scraper, spartan_weekly_legals.py and the
shared arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio
import json as _json

import httpx
import pytest
from tenacity import wait_exponential_jitter

import foreclosure_scraper.scrapers.counties_nc.transylvania_delinquent_tax as m

# Real-shaped description cell, same fixture value test_transylvania_delinquent_tax.py uses:
# "PARCEL<br/>MAP MS<br/><br/>ACREAGE LT".
REAL_ESTATE_DESC = "8586223397000<br/>T001A00001  01 MS.01<br /><br />1.270 AC"
PARCEL = "8586223397000"


def _grid_row(year, bill, account, owner, desc, orig, bal):
    return {"id": f"{year}/{bill}",
            "cell": [str(year), str(bill), account, owner, desc, orig, bal]}


# One real-estate bill for tax year 2025 -- the only year asked for once
# FORECLOSURE_TRANSYLVANIA_TAX_YEAR pins the loop to a single iteration (see _single_year
# below), so every test's call counts map 1:1 onto one AsyncRetrying cycle per call site.
ONE_ROW = {"2025": [_grid_row(2025, 101, "70000001", "ROE JANE", REAL_ESTATE_DESC,
                              "100.00", "50.00")]}


class _FlakyTransport(httpx.AsyncBaseTransport):
    """Serves the real 3-step chain (seed GET -> GetSearchTablePartial -> GetSearchTableData
    -> ViewTaxBill) from `rows_by_year`/`detail_html`, except requests whose path ends with
    `flaky_path` raise `exc` for the first `fail_times` calls to that path before serving
    their real response -- models a connection that blips and then clears (or never clears,
    for fail_times >= stop_after_attempt's budget). `bad_status`, independently, makes ONE
    path answer with a fixed real (non-transport) HTTP status instead of raising -- proves
    that kind of failure is never mistaken for a transport/timeout error."""

    def __init__(self, rows_by_year, detail_html="<html></html>",
                 flaky_path=None, fail_times=0, exc=None, bad_status=None):
        self.rows_by_year = rows_by_year
        self.detail_html = detail_html
        self.flaky_path = flaky_path
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.bad_status = bad_status  # (path_suffix, status_code)
        self.calls: dict[str, int] = {}
        self._flaky_calls = 0
        self._year: str | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls[path] = self.calls.get(path, 0) + 1

        if self.flaky_path and path.endswith(self.flaky_path):
            self._flaky_calls += 1
            if self._flaky_calls <= self.fail_times:
                raise self.exc

        if self.bad_status and path.endswith(self.bad_status[0]):
            return httpx.Response(self.bad_status[1], json={})

        if path == "/TaxBillSearch":
            return httpx.Response(200, text="<html>search</html>")
        if path.endswith("GetSearchTablePartial/"):
            body = _json.loads(request.content or b"{}")
            self._year = body["TaxYear"]
            return httpx.Response(200, text="<div>fragment</div>")
        if path.endswith("GetSearchTableData"):
            rows = self.rows_by_year.get(self._year, [])
            return httpx.Response(200, json={"total": 1, "numRecords": len(rows), "rows": rows})
        if path.endswith("ViewTaxBill"):
            return httpx.Response(200, text=self.detail_html)
        return httpx.Response(404)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """The real backoff is 1-8s per attempt; make the retry tests instant."""
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _single_year(monkeypatch):
    """Pin the scrape to exactly one tax year so each call site's retry attempts can be
    counted exactly. The multi-year widening and the consecutive-empty-years stop are
    already covered separately by test_transylvania_delinquent_tax.py -- not under test
    here."""
    monkeypatch.setenv("FORECLOSURE_TRANSYLVANIA_TAX_YEAR", "2025")
    monkeypatch.setenv("FORECLOSURE_TRANSYLVANIA_TAX_CONCURRENCY", "2")


def _run(monkeypatch, transport):
    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    return asyncio.run(m.TransylvaniaDelinquentTax().fetch())


# --------------------------------------------------------- (1) the seed GET (/TaxBillSearch)
# The single point of failure: fetch() swallows this call's own exception into `return []`,
# so before this fix a transient blip here zeroed the WHOLE run.

def test_seed_cookie_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    transport = _FlakyTransport(ONE_ROW, flaky_path="/TaxBillSearch", fail_times=2)
    out = _run(monkeypatch, transport)
    assert transport.calls["/TaxBillSearch"] == 3     # 2 failures + the attempt that succeeded
    assert len(out) == 1
    assert out[0].parcel_id == PARCEL


def test_seed_cookie_connect_timeout_that_never_clears_still_gives_up_not_hangs(monkeypatch):
    transport = _FlakyTransport(ONE_ROW, flaky_path="/TaxBillSearch", fail_times=99)
    out = _run(monkeypatch, transport)
    assert transport.calls["/TaxBillSearch"] == 3      # stop_after_attempt(3), then gives up
    assert out == []     # fetch()'s own contract -- the outer try/except still returns [] cleanly


def test_seed_cookie_real_bad_http_status_is_not_retried(monkeypatch):
    # The seed call's own code never inspects the response at all (no status check, no body
    # read) -- it only cares whether the call RAISED. A real bad status does not raise, so
    # it is not a transport/timeout error, so attempt 1 is the only attempt and the rest of
    # fetch() proceeds exactly as if the seed GET had returned 200.
    transport = _FlakyTransport(ONE_ROW, bad_status=("/TaxBillSearch", 503))
    out = _run(monkeypatch, transport)
    assert transport.calls["/TaxBillSearch"] == 1
    assert len(out) == 1


# ------------------------------------------------- (2) the per-year search/data POST pair
# A transient blip here used to count as a genuinely-empty year toward
# _CONSECUTIVE_EMPTY_STOP, risking an early, silent truncation of the multi-year back-read.

def test_per_year_search_post_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    transport = _FlakyTransport(ONE_ROW, flaky_path="GetSearchTablePartial/", fail_times=2)
    out = _run(monkeypatch, transport)
    assert transport.calls["/TaxBillSearch/GetSearchTablePartial/"] == 3
    assert len(out) == 1


def test_per_year_data_post_read_timeout_is_also_retried(monkeypatch):
    transport = _FlakyTransport(ONE_ROW, flaky_path="GetSearchTableData", fail_times=1,
                                exc=httpx.ReadTimeout("slow"))
    out = _run(monkeypatch, transport)
    assert transport.calls["/TaxBillSearch/GetSearchTableData"] == 2
    assert len(out) == 1


def test_per_year_timeout_that_never_clears_still_raises_bounded_zeroing_only_that_year(monkeypatch):
    transport = _FlakyTransport(ONE_ROW, flaky_path="GetSearchTablePartial/", fail_times=99)
    out = _run(monkeypatch, transport)
    assert transport.calls["/TaxBillSearch/GetSearchTablePartial/"] == 3  # bounded, no hang
    assert out == []    # the only year read is lost, same as a genuinely dead host would do


def test_per_year_real_bad_http_status_is_not_retried(monkeypatch):
    transport = _FlakyTransport(ONE_ROW, bad_status=("GetSearchTableData", 500))
    out = _run(monkeypatch, transport)
    assert transport.calls["/TaxBillSearch/GetSearchTableData"] == 1
    assert out == []     # a non-200 response is treated as "no rows" (existing behavior), unretried


# ------------------------------------------------- (3) the per-parcel ViewTaxBill POST
# Lowest severity of the three: a failure here only drops ONE parcel's detail enrichment --
# build_listing() tolerates a missing/empty detail dict and the bill-grid lead still ships.

def test_enrich_detail_post_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    transport = _FlakyTransport(
        ONE_ROW, detail_html=f"<html>Parcel Number :<br/>{PARCEL}</html>",
        flaky_path="ViewTaxBill", fail_times=2)
    out = _run(monkeypatch, transport)
    assert transport.calls["/TaxBillSearch/ViewTaxBill"] == 3
    assert len(out) == 1
    assert out[0].parcel_id == PARCEL     # the detail fetch actually landed and was parsed


def test_enrich_detail_timeout_that_never_clears_still_ships_a_thinner_listing(monkeypatch):
    transport = _FlakyTransport(ONE_ROW, flaky_path="ViewTaxBill", fail_times=99)
    out = _run(monkeypatch, transport)
    assert transport.calls["/TaxBillSearch/ViewTaxBill"] == 3   # stop_after_attempt(3), no hang
    assert len(out) == 1                  # the bill-grid lead still ships (build_listing's det={})
    assert out[0].parcel_id == PARCEL     # falls back to the grid parcel, not the detail page


def test_enrich_detail_real_bad_http_status_is_not_retried(monkeypatch):
    transport = _FlakyTransport(ONE_ROW, bad_status=("ViewTaxBill", 503))
    out = _run(monkeypatch, transport)
    assert transport.calls["/TaxBillSearch/ViewTaxBill"] == 1
    assert len(out) == 1
