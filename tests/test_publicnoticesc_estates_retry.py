"""publicnoticesc_estates.fetch: a transient transport error on the pagination "next page"
postback gets retried, not treated as "pagination for this preset just ended."

Found 2026-11-07: of the file's 4 PoliteFetcher calls, 3 (pf.get_with_url + the 2 postbacks
inside _open_preset()) already run under fetch()'s own manual 2-attempt retry loop -- but the
4th, the pagination while-loop's own "next page" postback (`html = await pf.post(session_url,
form)`), had zero retry cushioning. Because each page's POST depends on the prior page's
rendered hidden-field/button state, pages cannot be fetched out of order or skipped, so a single
transient blip there used to end pagination for the REST of that preset's run -- losing whatever
pages were still unread -- with no retry attempted, while rows already collected kept shipping
silently under-reported. Same root cause already fixed tonight for arcgis_webmap.query_features()
and others: PoliteFetcher.get()/.post() carry zero retry logic of their own (one raw httpx call,
then only a wall check and a status>=400 check) -- any retry cushioning must come from the caller.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.public_notices import publicnoticesc_estates as est


def _row(nid: str, text: str, county: str = "Jasper") -> str:
    return (f'<table class="nested"><tr><td><input onclick="location.href=\'Details.aspx?SID=abc&ID={nid}\'"></td>'
            f'<td><div class="left"><strong>Test Gazette</strong><br>Thursday, October 1, 2026</div>'
            f'<div class="right" style="display:none">City: Ridgeland<br>County: {county}</div></td></tr>'
            f'<tr><td colspan="3">{text}... click \'view\' to open the full text.</td></tr></table>')


HEAD = "<html><input type='hidden' name='__VIEWSTATE' value='v'/>"

# Page 1: one named estate, plus an ENABLED next-button so fetch()'s pagination while-loop goes
# on to POST for page 2 -- that POST is the call site under test. No lblTotalPages label, so the
# cur>=tot check never short-circuits the loop on its own.
PAGE_1 = (HEAD
          + _row("1", "STATE OF SOUTH CAROLINA COUNTY OF: JASPER IN THE MATTER OF: ORVEL QUIMBY TANDRY "
                      "(DECEASED) NOTICE TO CREDITORS CASE NUMBER: 2026-ES-27-00206")
          + f'<a id="{est._NEXT_BTN_RENDERED_ID}" href="#">Next</a>'
          + '<span id="lblCurrentPage">1</span>'
          + "</html>")

# Page 2: a different estate, no next-button -- the loop stops here (last page).
PAGE_2 = (HEAD
          + _row("2", "STATE OF SOUTH CAROLINA COUNTY OF: AIKEN IN THE MATTER OF: PELL ASTER WINTHROPE "
                      "(DECEASED) PROBATE NOTICE CASE NUMBER: 2026-ES-02-00999", county="Aiken")
          + '<span id="lblCurrentPage">2</span>'
          + "</html>")

_BTN_NEXT_KEY = f"{est.GRID}$ctl01$btnNext.x"


class _FlakyPoliteFetcher:
    """A PoliteFetcher stand-in whose session-open postbacks (inside _open_preset -- already
    retry-protected by fetch()'s own 2-attempt loop, not what this test targets) always succeed.
    Only the pagination "next page" postback can be made to flake, N times before serving page 2.
    """

    def __init__(self, fail_times: int = 0, exc: Exception | None = None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.page_posts = 0

    async def __aenter__(self) -> "_FlakyPoliteFetcher":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get_with_url(self, url):
        return PAGE_1, "https://www.scpublicnotices.com/(S(x))/Search.aspx"

    async def post(self, url, data):
        if _BTN_NEXT_KEY not in data:
            return PAGE_1
        self.page_posts += 1
        if self.page_posts <= self.fail_times:
            raise self.exc
        return PAGE_2


@pytest.fixture(autouse=True)
def _one_preset_fast_backoff(monkeypatch):
    # One preset only -- PRESETS has 2 entries and fetch() loops over both, which would double
    # every call count below for no reason relevant to this test (the call site under test is
    # the same code regardless of which preset is running).
    monkeypatch.setattr(est, "PRESETS", {"30": "Notice to Creditors"})
    monkeypatch.setattr(est, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))
    monkeypatch.setattr(est, "_RETRY_PAUSE_S", 0.0, raising=False)


def _run(monkeypatch, fake):
    monkeypatch.setattr(est, "PoliteFetcher", lambda: fake)
    s = est.PublicNoticeSCEstates()
    rows = asyncio.run(s.fetch())
    return s, rows


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyPoliteFetcher(fail_times=2)
    s, rows = _run(monkeypatch, fake)
    assert fake.page_posts == 3  # 2 failures + 1 success, inside stop_after_attempt(3)
    assert sorted(r.county for r in rows) == ["Aiken", "Jasper"]
    assert "error" not in s.last_stats["Notice to Creditors"]


def test_a_connect_timeout_that_never_clears_still_exhausts_the_retry_budget(monkeypatch):
    fake = _FlakyPoliteFetcher(fail_times=99)
    s, rows = _run(monkeypatch, fake)
    assert fake.page_posts == 3  # stop_after_attempt(3), then gives up -- not an infinite retry/hang
    # The exhausted error reaches fetch()'s own except-block (proof it really raised, rather than
    # hanging inside AsyncRetrying) and page 1's already-collected row still ships instead of the
    # whole preset's result being thrown away.
    assert "error" in s.last_stats["Notice to Creditors"]
    assert [r.county for r in rows] == ["Jasper"]


def test_a_read_timeout_is_also_retried(monkeypatch):
    fake = _FlakyPoliteFetcher(fail_times=1, exc=httpx.ReadTimeout("slow"))
    s, rows = _run(monkeypatch, fake)
    assert fake.page_posts == 2
    assert sorted(r.county for r in rows) == ["Aiken", "Jasper"]


def test_a_real_http_error_status_is_not_retried(monkeypatch):
    class _BadStatusFetcher(_FlakyPoliteFetcher):
        async def post(self, url, data):
            if _BTN_NEXT_KEY not in data:
                return PAGE_1
            self.page_posts += 1
            raise httpx.HTTPStatusError("HTTP 503", request=None, response=None)

    fake = _BadStatusFetcher()
    s, rows = _run(monkeypatch, fake)
    assert fake.page_posts == 1   # a real bad status is not a transport/timeout error -- no retry
    assert [r.county for r in rows] == ["Jasper"]  # page 1's row still shipped


def test_walled_on_the_page_postback_is_also_not_retried(monkeypatch):
    """Walled (a detected CAPTCHA/login/block wall) must stay terminal, exactly like it already
    is for the _open_preset() call sites -- a wall is never something a retry fixes."""
    from foreclosure_scraper.quiet_title.fetch import Walled

    class _WalledFetcher(_FlakyPoliteFetcher):
        async def post(self, url, data):
            if _BTN_NEXT_KEY not in data:
                return PAGE_1
            self.page_posts += 1
            raise Walled(url, "captcha")

    fake = _WalledFetcher()
    s, rows = _run(monkeypatch, fake)
    assert fake.page_posts == 1  # not retried
    assert s.last_stats["Notice to Creditors"]["walled"] == "captcha"
    assert [r.county for r in rows] == ["Jasper"]
