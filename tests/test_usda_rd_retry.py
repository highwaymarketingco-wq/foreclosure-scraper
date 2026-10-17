"""reo.usda_rd._active_counties: a transient transport error on either of its
two sequential, dependent GETs gets retried, not treated as "this state+kind
has zero active counties."

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
"""
from __future__ import annotations

import asyncio

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
