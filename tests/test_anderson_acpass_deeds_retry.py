"""anderson_acpass_deeds._fetch_type_code: the two POSTs (the initial
type+date search and the 'More' pagination follow-up) get retry cushioning
on transport/timeout errors, not treated as "the whole code failed."

Found 2026-10-17 (gap-sweep): this function had zero retry cushioning on
either POST -- the same http_client-style gap already fixed tonight for the
Column legal-notice API scrapers, spartan_weekly_legals.py, and
arcgis_webmap.query_features(). http_client.client() builds its transport
with retries=0 and its own docstring says callers must wrap their own
AsyncRetrying. Unwrapped, a single transient blip on either POST propagates
out of _fetch_type_code and is only caught at the call site in fetch() as
catch-and-skip-the-whole-code (`except Exception: log.warning(...); continue`)
-- with only two instrument-type codes total (195 COURT ORDER, 020 POA),
losing one zeroes up to half this dateless source's output for the run, and
since the slug is in main.DATELESS_OK_SOURCES (no fallback date window) a
zeroed code can't self-heal on a later run.

Modeled on tests/test_arcgis_webmap_query_features_retry.py (same fixture
and fast-backoff style).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import anderson_acpass_deeds as _mod

# Trimmed excerpts of REAL markup (same fixtures used in
# test_anderson_acpass_deeds.py) -- one finite COURT ORDER page (2 rows, no
# "More" form) and one POA page carrying the real paging cursor.
COURT_ORDER_PAGE = """
<table width="100%" border="1" cellpadding="0" cellspacing="0" bordercolor="#003300">
  <tr>
    <td><div align="center"><font face="Arial, Helvetica">
        <input type="checkbox" name="instryearnbr" value="L2023239990001">
        </font></div></td>
    <td><font size="2" face="Arial, Helvetica"><a href="deddetail1.cgi?instryearnbr=L2023239990001">239990001</a></font></td>
    <td><div align="center">COURT ORDER</div></td>
    <td colspan="2"><div align="center"><font size="2" face="Arial, Helvetica">3/21/2023</font></div></td>
    <td><div align="center"><font size="2" face="Arial, Helvetica">19991&nbsp;&nbsp;00011
        </font></div></td>
    <td colspan="2"><div align="center"><font color="#000000" size="2" face="Arial, Helvetica">&nbsp;<strong>ORDER ESTABLISHING HEIRS
        </strong> </font> </div>
      <div align="center"></div></td>
  </tr>
  <tr>
    <td><div align="center"><font face="Arial, Helvetica">
        <input type="checkbox" name="instryearnbr" value="L2023230007259">
        </font></div></td>
    <td><font size="2" face="Arial, Helvetica"><a href="deddetail1.cgi?instryearnbr=L2023230007259">230007259</a></font></td>
    <td><div align="center">COURT ORDER</div></td>
    <td colspan="2"><div align="center"><font size="2" face="Arial, Helvetica">3/29/2023</font></div></td>
    <td><div align="center"><font size="2" face="Arial, Helvetica">16686&nbsp;&nbsp;00078
        </font></div></td>
    <td colspan="2"><div align="center"><font color="#000000" size="2" face="Arial, Helvetica">&nbsp;<strong>ORDER
        </strong> </font> </div>
      <div align="center"></div></td>
  </tr>
</table>
"""

POA_PAGE_WITH_CURSOR = """
<table width="100%" border="1" cellpadding="0" cellspacing="0" bordercolor="#003300">
  <tr>
    <td><div align="center"><font face="Arial, Helvetica">
        <input type="checkbox" name="instryearnbr" value="L2024249990002">
        </font></div></td>
    <td><font size="2" face="Arial, Helvetica"><a href="deddetail1.cgi?instryearnbr=L2024249990002">249990002</a></font></td>
    <td><div align="center">POA</div></td>
    <td colspan="2"><div align="center"><font size="2" face="Arial, Helvetica">1/02/2024</font></div></td>
    <td><div align="center"><font size="2" face="Arial, Helvetica">19992&nbsp;&nbsp;00022
        </font></div></td>
    <td colspan="2"><div align="center"><font color="#000000" size="2" face="Arial, Helvetica">&nbsp;<strong>DURABLE POWER OF ATTORNEY
        </strong> </font> </div>
      <div align="center"></div></td>
  </tr>
  <tr>
    <td height="32" colspan="8"><div align="center">
        <INPUT name="image" TYPE="image" SRC="/images/show.gif" onClick="submitFunction(2)">
        <INPUT name="image" type="image" SRC="/images/more.gif" value="LAST&gt;&gt;" onClick="submitFunction(3)">
        <input name="searchtype" type="hidden" value="L">
        <input name="searchinstr" type="hidden" value="020">
        <input name="searchbegdate" type="hidden" value="20240101">
        <input name="searchenddate" type="hidden" value="20261001">
        <input name="daten" type="hidden" value="20240109">
        <input name="instrnon" type="hidden" value=240000520">
    </div></td>
  </tr>
</table>
"""


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(_mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


class _FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FlakySearchClient:
    """The initial _SEARCH_CGI POST raises on the first N-1 calls, then
    serves a real (finite, no-cursor) result page."""

    def __init__(self, fail_times: int, exc=None, success_text: str = ""):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0
        self.success_text = success_text

    async def post(self, url, data=None, headers=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(200, self.success_text)


def test_search_post_transient_connect_timeout_is_retried_and_then_succeeds():
    c = _FlakySearchClient(fail_times=2, success_text=COURT_ORDER_PAGE)
    rows = asyncio.run(_mod._fetch_type_code(c, "195", "01/01/2024", "01/01/2026"))
    assert c.calls == 3
    assert len(rows) == 2


def test_search_post_read_timeout_is_also_retried():
    c = _FlakySearchClient(fail_times=1, exc=httpx.ReadTimeout("slow"), success_text=COURT_ORDER_PAGE)
    rows = asyncio.run(_mod._fetch_type_code(c, "195", "01/01/2024", "01/01/2026"))
    assert c.calls == 2
    assert len(rows) == 2


def test_search_post_transient_error_that_never_clears_raises_not_hangs():
    c = _FlakySearchClient(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(_mod._fetch_type_code(c, "195", "01/01/2024", "01/01/2026"))
    assert c.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite retry/hang


class _BadStatusSearchClient:
    """A real non-transport HTTP error (a server-side 503) comes back as an
    ordinary response, not an exception -- must NOT be retried."""

    def __init__(self):
        self.calls = 0

    async def post(self, url, data=None, headers=None):
        self.calls += 1
        return _FakeResp(503, "")


def test_search_post_bad_status_is_not_retried():
    c = _BadStatusSearchClient()
    rows = asyncio.run(_mod._fetch_type_code(c, "195", "01/01/2024", "01/01/2026"))
    assert c.calls == 1   # a real bad status is not a transport/timeout error
    assert rows == []


class _FlakyNextClient:
    """The initial search POST always succeeds immediately with a page that
    carries a pagination cursor; the 'More' follow-up POST to _NEXT_CGI is
    the flaky one."""

    def __init__(self, fail_times: int, exc=None, next_success_text: str = COURT_ORDER_PAGE):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.next_success_text = next_success_text
        self.search_calls = 0
        self.next_calls = 0

    async def post(self, url, data=None, headers=None):
        if url == _mod._SEARCH_CGI:
            self.search_calls += 1
            return _FakeResp(200, POA_PAGE_WITH_CURSOR)
        self.next_calls += 1
        if self.next_calls <= self.fail_times:
            raise self.exc
        return _FakeResp(200, self.next_success_text)


def test_next_post_transient_error_is_retried_and_then_succeeds():
    c = _FlakyNextClient(fail_times=2)
    rows = asyncio.run(_mod._fetch_type_code(c, "020", "01/01/2024", "01/01/2026"))
    assert c.search_calls == 1
    assert c.next_calls == 3
    # 1 POA row off page 1 + 2 COURT_ORDER rows off the (finite) page 2.
    assert len(rows) == 3


def test_next_post_error_that_never_clears_raises_not_hangs():
    c = _FlakyNextClient(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(_mod._fetch_type_code(c, "020", "01/01/2024", "01/01/2026"))
    assert c.search_calls == 1
    assert c.next_calls == 3


def test_next_post_bad_status_is_not_retried():
    class _BadStatusNextClient:
        def __init__(self):
            self.search_calls = 0
            self.next_calls = 0

        async def post(self, url, data=None, headers=None):
            if url == _mod._SEARCH_CGI:
                self.search_calls += 1
                return _FakeResp(200, POA_PAGE_WITH_CURSOR)
            self.next_calls += 1
            return _FakeResp(503, "")

    c = _BadStatusNextClient()
    rows = asyncio.run(_mod._fetch_type_code(c, "020", "01/01/2024", "01/01/2026"))
    assert c.next_calls == 1   # a real bad status on the 'More' POST is not retried
    assert len(rows) == 1      # the loop breaks, but page 1's row already collected is kept
