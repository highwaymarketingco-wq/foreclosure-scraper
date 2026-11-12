"""horry_probate._fetch_detail_page: a transient transport/timeout error on the
per-case CaseDetailPage.aspx fetch gets retried, not treated as "this case's
enrichment is permanently lost."

Found 2026-11-07 (follow-up gap check on a file already partially remediated):
this file's other two network call sites -- the priming ``await
http.get(PAGE_URL)`` and the paginated ``await http.get(DATA_URL, ...)``, both
in ``HorryProbate.fetch()`` -- were already wrapped in ``AsyncRetrying`` (see
tests/test_horry_probate_retry.py, landed in the same systematic sweep as the
Column legal-notice API scrapers, spartan_weekly_legals.py, and
arcgis_webmap.query_features()). This third call site, inside the
module-level ``_fetch_detail_page()`` helper, was missed: its bare
``try/except Exception`` caught everything -- including
httpx.TransportError/TimeoutException -- and returned ``{}`` on the very
first failure, with zero retry.

Lower severity than the other two (this is a per-item loop capped at
DETAIL_FETCH_CAP, not a whole-scrape single point of failure -- every
listing's core fields are already banked via ``self.partial`` before this
enrichment pass runs, per the module's own "pure enrichment, never drops the
listing" contract), but still a real, permanent loss of that one case's
decedent-address / personal-representative fields on a transient blip, with
zero chance to self-heal within the run. Same fix, same reasoning, for
consistency with the rest of the file.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import horry_probate as mod

# Synthetic CaseDetailPage.aspx body -- same shape the real parser
# (_parse_detail_html) looks for (Primary Parties / Case Parties / Scheduled
# Events markers, gridItemNrm/Alt row classes), used only to prove a
# successful retry actually returns the real parsed result, not just "no
# exception".
_DETAIL_HTML = """
<table><caption><h2>Primary Parties</h2></caption><tr class="gridHdr" align="left">
<th scope="col">Name</th><th scope="col">Type</th><th scope="col">Date of Death</th><th scope="col">Address</th>
</tr><tr class="gridItemNrm">
<td>Example, Decedent</td><td>Deceased Person                         </td><td>1/1/2026</td><td>&nbsp;</td>
</tr></table>
<table><caption><h2>Case Parties</h2></caption><tr class="gridHdr" align="left">
<th scope="col">Name</th><th scope="col">Type</th>
</tr><tr class="gridItemNrm">
<td>Example, Decedent</td><td>Deceased Person                         </td>
</tr><tr class="gridItemAlt">
<td>Example, Rep</td><td>Personal Representative                 </td>
</tr></table>
<h2>Scheduled Events</h2>
"""


class _DetailResp:
    def __init__(self, text="", status_code=200):
        self.text, self.status_code = text, status_code


class _FlakyHttp:
    """Raises on the first N-1 calls, then serves a real (200) detail page."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, headers=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _DetailResp(_DETAIL_HTML, status_code=200)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2)
    extras = asyncio.run(mod._fetch_detail_page(http, "26500", 1, 1))
    assert http.calls == 3
    assert extras["personal_representatives"] == [{"name": "Example, Rep",
                                                     "role": "Personal Representative"}]


def test_a_connect_timeout_that_never_clears_still_returns_empty_not_hangs():
    http = _FlakyHttp(fail_times=99)
    extras = asyncio.run(mod._fetch_detail_page(http, "26500", 1, 1))
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- not a hang
    # _fetch_detail_page's own outer try/except still swallows the exhausted
    # retry's re-raise and returns {} -- enrichment must never raise outward.
    assert extras == {}


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    extras = asyncio.run(mod._fetch_detail_page(http, "26500", 1, 1))
    assert http.calls == 2
    assert extras["personal_representatives"][0]["name"] == "Example, Rep"


def test_a_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, headers=None):
            self.calls += 1
            return _DetailResp("<html>forbidden</html>", status_code=403)

    http = _BadStatusHttp()
    extras = asyncio.run(mod._fetch_detail_page(http, "26500", 1, 1))
    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert extras == {}


def test_a_non_transport_exception_is_not_retried():
    class _BoomHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, headers=None):
            self.calls += 1
            raise RuntimeError("not a transport/timeout error")

    http = _BoomHttp()
    extras = asyncio.run(mod._fetch_detail_page(http, "26500", 1, 1))
    assert http.calls == 1   # a non-transport/timeout exception must not be retried
    assert extras == {}
