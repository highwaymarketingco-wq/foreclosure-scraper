"""reo.usda_rd: a transient transport error on any of this module's bare
network calls gets retried, not treated as "this county/state+kind/row has
nothing."

Found 2026-10-17 (gap-sweep): _active_counties() opened http_client.client()
directly and issued raw c.get() calls with no retry wrapper. The client's
transport is built with retries=0 ("callers already wrap their own
AsyncRetrying" per http_client.py's own comment), so a bare call here had zero
retry cushioning -- the same root cause already fixed tonight for the Column
legal-notice API scraper, spartan_weekly_legals.py, mecklenburg_delinquent_tax,
and the shared arcgis_webmap.query_features(). This call runs once per
state+kind (6 total: NC/SC x SFH/MFH/FSA) and both GETs are sequential and
dependent (the 2nd needs the session the 1st established), so a single
transient blip here used to permanently zero that whole state+kind's county
list, which cascades through _fetch_state into zero listings for the whole
combination. Because expected_min_count=0 and real volume is typically 0-10
rows per state, a transient-failure zero is visually indistinguishable from a
genuine "no active listings" result, and this slug (main.DATELESS_OK_SOURCES)
has no fallback date window to self-heal on a later run.

Found again 2026-11-07 (second pass over this same file): the same bare-call
gap was still open on the other two network sites this module makes --
_search_county()'s per-county results POST and _enrich_from_detail()'s
per-row PropertyDetail GET. Both are narrower blast radius than
_active_counties above (one county's listings / one row's optional
enrichment fields, not a whole state+kind), but structurally identical and
fixed the same way. Covered below alongside the original _active_counties
tests rather than in a second file, since both sites live in this one module.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.reo import usda_rd as mod

# URL fragments that distinguish the two sequential GETs _active_counties makes.
REF_FRAG = "/searchSFH"  # step 1: session-establishing GET to the kind's search page
JSON_FRAG = "/getCountiesOfStateWithActiveProperties"  # step 2: active-counties JSON

COUNTIES_JSON = [
    {"countyCode": "063", "countyName": "Lexington (1)"},
    {"countyCode": "079", "countyName": "Richland (1)"},
]


class _Resp:
    def __init__(self, status_code=200, content_type="application/json", payload=None):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload


class _FlakyClient:
    """Serves a fixed real-shaped response by URL fragment, except one fragment
    (`flaky_frag`) raises `exc` for the first `fail_times` calls to it before
    serving its real response -- models a connection that blips and then
    clears (or never clears, for fail_times >= stop_after_attempt's budget).
    """

    def __init__(self, flaky_frag=None, fail_times=0, exc=None,
                 json_status=200, json_content_type="application/json"):
        self.flaky_frag = flaky_frag
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls: list[str] = []
        self._flaky_calls = 0
        self.json_status = json_status
        self.json_content_type = json_content_type

    async def get(self, url, headers=None):
        self.calls.append(url)
        if self.flaky_frag and self.flaky_frag in url:
            self._flaky_calls += 1
            if self._flaky_calls <= self.fail_times:
                raise self.exc
        if JSON_FRAG in url:
            return _Resp(status_code=self.json_status,
                         content_type=self.json_content_type,
                         payload=COUNTIES_JSON)
        return _Resp()  # the session-establishing GET -- return value is never read


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same trick as the other retry tests in this repo: swap in a near-zero
    backoff so the retried tests don't actually sleep for the real 1-8s
    exponential jitter."""
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                         lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _json_calls(c):
    return len([u for u in c.calls if JSON_FRAG in u])


def _ref_calls(c):
    return len([u for u in c.calls if REF_FRAG in u])


def test_transient_error_on_session_get_is_retried_and_then_succeeds():
    c = _FlakyClient(flaky_frag=REF_FRAG, fail_times=2)
    codes = asyncio.run(mod._active_counties(c, "SC", "SFH"))
    assert _ref_calls(c) == 3  # 2 failures + 1 success, stop_after_attempt(3)
    assert codes == ["063", "079"]


def test_transient_error_on_counties_json_get_is_retried_and_then_succeeds():
    c = _FlakyClient(flaky_frag=JSON_FRAG, fail_times=2)
    codes = asyncio.run(mod._active_counties(c, "SC", "SFH"))
    assert _json_calls(c) == 3
    assert codes == ["063", "079"]


def test_a_read_timeout_is_also_retried():
    c = _FlakyClient(flaky_frag=JSON_FRAG, fail_times=1, exc=httpx.ReadTimeout("slow"))
    codes = asyncio.run(mod._active_counties(c, "SC", "SFH"))
    assert _json_calls(c) == 2
    assert codes == ["063", "079"]


def test_transient_error_that_never_clears_gives_up_after_the_retry_budget_not_an_infinite_hang():
    # fail_times far exceeds the retry budget: the AsyncRetrying block itself raises
    # once stop_after_attempt(3) is exhausted (reraise=True); the surrounding
    # try/except (Exception, asyncio.TimeoutError) in _active_counties then logs a
    # warning and returns [] -- this function's own documented contract ("never
    # raises"). This proves the retry loop is BOUNDED -- exactly 3 attempts, no
    # hang -- even though the state+kind is still (correctly) lost for this one
    # call, same as it would be for a genuinely dead host before or after this fix.
    c = _FlakyClient(flaky_frag=JSON_FRAG, fail_times=99)
    codes = asyncio.run(mod._active_counties(c, "SC", "SFH"))
    assert _json_calls(c) == 3  # stop_after_attempt(3), then gives up -- not more, not fewer
    assert codes == []


def test_a_real_bad_http_status_is_not_retried():
    c = _FlakyClient(json_status=503, json_content_type="text/html")
    codes = asyncio.run(mod._active_counties(c, "SC", "SFH"))
    assert _json_calls(c) == 1  # a real bad status is not a transport/timeout error
    assert codes == []


def test_a_200_html_no_active_inventory_page_is_not_retried():
    # Per the module's own docstring: when a state has 0 active properties for a
    # kind, the endpoint returns a real HTML 200 (not JSON) -- documented as 0
    # active counties, and must not be mistaken for a transport failure worth
    # retrying.
    c = _FlakyClient(json_status=200, json_content_type="text/html")
    codes = asyncio.run(mod._active_counties(c, "SC", "SFH"))
    assert _json_calls(c) == 1
    assert codes == []


# --- _search_county: per-county search-results POST --------------------------

class _SearchResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FlakySearchClient:
    """Raises `exc` on the first `fail_times` POSTs, then serves a fixed
    `text`/`status_code` -- same flip-then-clear (or never-clear) model as
    `_FlakyClient` above, for the per-county results POST."""

    def __init__(self, fail_times=0, exc=None, status_code=200, text=""):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.status_code = status_code
        self.text = text
        self.calls = 0

    async def post(self, url, data=None, headers=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _SearchResp(status_code=self.status_code, text=self.text)


def test_search_county_transient_connect_timeout_is_retried_and_then_succeeds():
    from tests.test_usda_rd_photo import _REAL_TABLE_HTML

    c = _FlakySearchClient(fail_times=2, text=_REAL_TABLE_HTML)
    out = asyncio.run(mod._search_county(c, "SC", "SFH", "063"))
    assert c.calls == 3  # 2 failures + 1 success, stop_after_attempt(3)
    assert len(out) == 1
    assert out[0].street_address == "341 Crestwood Arch"


def test_search_county_a_read_timeout_is_also_retried():
    from tests.test_usda_rd_photo import _REAL_TABLE_HTML

    c = _FlakySearchClient(fail_times=1, exc=httpx.ReadTimeout("slow"), text=_REAL_TABLE_HTML)
    out = asyncio.run(mod._search_county(c, "SC", "SFH", "063"))
    assert c.calls == 2
    assert len(out) == 1


def test_search_county_transient_error_that_never_clears_gives_up_after_the_retry_budget_not_an_infinite_hang():
    # fail_times far exceeds the retry budget: the AsyncRetrying block itself
    # raises once stop_after_attempt(3) is exhausted (reraise=True); the
    # surrounding try/except (Exception, asyncio.TimeoutError) in
    # _search_county then logs a warning and returns [] -- this function's own
    # existing contract (never raises out to _fetch_state's per-county loop).
    # Proves the retry loop is BOUNDED -- exactly 3 attempts, no hang -- even
    # though this one county is still (correctly) lost for this run, same as
    # it would be for a genuinely dead host before or after this fix.
    c = _FlakySearchClient(fail_times=99)
    out = asyncio.run(mod._search_county(c, "SC", "SFH", "063"))
    assert c.calls == 3  # stop_after_attempt(3), then gives up -- not more, not fewer
    assert out == []


def test_search_county_a_real_bad_http_status_is_not_retried():
    c = _FlakySearchClient(status_code=503, text="")
    out = asyncio.run(mod._search_county(c, "SC", "SFH", "063"))
    assert c.calls == 1  # a real bad status is not a transport/timeout error
    assert out == []


# --- _enrich_from_detail: per-row PropertyDetail-page GET ---------------------
# Narrowest blast radius of the three fixed in this file: the caller appends
# `li` to its output regardless of this call's outcome, so an unretried blip
# here never drops a row/county/run -- it only silently loses this one row's
# optional enrichment fields (sale_date above all; see module docstring).

class _DetailResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FlakyDetailClient:
    """Raises `exc` on the first `fail_times` GETs, then serves a fixed
    `text`/`status_code`, for the per-row PropertyDetail GET."""

    def __init__(self, fail_times=0, exc=None, status_code=200, text=""):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.status_code = status_code
        self.text = text
        self.calls = 0

    async def get(self, url, headers=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _DetailResp(status_code=self.status_code, text=self.text)


def test_enrich_from_detail_transient_connect_timeout_is_retried_and_then_succeeds():
    from tests.test_usda_rd_detail_page import REAL_DETAIL_HTML, _make_listing

    c = _FlakyDetailClient(fail_times=2, text=REAL_DETAIL_HTML)
    li = _make_listing()
    asyncio.run(mod._enrich_from_detail(c, li, "https://x/SFHPropertyDetail?id=7619"))
    assert c.calls == 3  # 2 failures + 1 success, stop_after_attempt(3)
    assert li.sale_date == datetime(2025, 5, 5)  # the headline field this fetch recovers


def test_enrich_from_detail_transient_error_that_never_clears_gives_up_after_the_retry_budget_not_an_infinite_hang():
    # Same bounded-retry proof as _search_county above: the AsyncRetrying block
    # exhausts stop_after_attempt(3) and reraises, but _enrich_from_detail's OWN
    # outer try/except (its documented best-effort "never raises" contract --
    # see its docstring, and the pre-existing
    # test_enrich_from_detail_never_raises_on_fetch_failure in
    # test_usda_rd_detail_page.py) swallows that and simply returns without
    # mutating `li`. No hang, no exception reaches _search_county's per-row loop.
    from tests.test_usda_rd_detail_page import _make_listing

    c = _FlakyDetailClient(fail_times=99)
    li = _make_listing()
    asyncio.run(mod._enrich_from_detail(c, li, "https://x/SFHPropertyDetail?id=7619"))
    assert c.calls == 3  # stop_after_attempt(3), then gives up -- not more, not fewer
    assert li.sale_date is None  # untouched, not crashed


def test_enrich_from_detail_a_real_bad_http_status_is_not_retried():
    from tests.test_usda_rd_detail_page import _make_listing

    c = _FlakyDetailClient(status_code=500, text="")
    li = _make_listing()
    asyncio.run(mod._enrich_from_detail(c, li, "https://x/SFHPropertyDetail?id=7619"))
    assert c.calls == 1  # a real bad status is not a transport/timeout error
    assert li.sale_date is None
