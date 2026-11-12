"""counties_sc.greenville_mie_adverts.GreenvilleMIEAdverts.fetch(): a transient transport/
timeout error on either of this file's two real network calls gets retried, not treated as
"that scrape failed."

Found 2026-11-07 (gap-sweep): this module builds its own raw httpx.AsyncClient (not the
shared http_client.client() helper, which itself only works because ITS callers wrap their
own AsyncRetrying -- this file never did -- no tenacity import, no AsyncRetrying, no manual
backoff loop anywhere), so neither of its two httpx.get() calls had any retry cushioning.
Same bug shape already fixed the same night in the Column legal-notice API scraper,
spartan_weekly_legals.py, and the shared arcgis_webmap.query_features().

Two real call sites:

  (1) fetch()'s own sitemap GET -- `r = await c.get(SITEMAP)`, guarded only by a bare
      try/except Exception that logs and `return []`s. This is the HEADLINE, highest-
      severity finding: the sitemap is the ONLY source of every advert URL this scraper
      ever sees, so one transient blip zeroes the whole scrape's output for the run.
      Greenville is registered in main.DATELESS_OK_SOURCES (no fallback date window), so a
      zeroed run reports a clean, healthy empty result forever until someone notices by
      hand. The sitemap's own response status is deliberately NEVER checked (it legitimately
      answers HTTP 404 while serving valid XML -- see the module's "DO NOT check
      r.status_code" comment), so the except branch here is reached only by genuine
      transport/timeout failures -- exactly what AsyncRetrying is for, never a real bad
      status.

  (2) The nested `one(u)` helper inside fetch(), fanned out across every sitemap URL via
      asyncio.gather() and bounded by asyncio.Semaphore(_CONCURRENCY). Lower blast radius --
      one URL's failure only drops that single advert, the rest of the batch continues --
      but still a real unprotected call, wrapped identically for consistency. Its own
      raise_for_status() call sits OUTSIDE the AsyncRetrying block (inside the same
      try/except): a real bad HTTP status doesn't match
      retry_if_exception_type((TransportError, TimeoutException, TimeoutError)), so it
      reraises immediately on attempt 1 and is swallowed by the same
      `except Exception: stats["errors"] += 1; return` as before this fix -- one advert
      skipped, the rest of the gather unaffected.

Each site is covered for: (a) a transient transport/timeout error is retried and then
succeeds; (b) a transient error that never clears still gives up after stop_after_attempt(3)
-- bounded, not an infinite hang; (c) a real non-transport error is not retried (fails on
attempt 1).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import greenville_mie_adverts as m

SITEMAP_PATH = "/wp-sitemap-posts-advert-1.xml"


def _advert_html(tms: str, street_line: str) -> str:
    """A minimal, real advert page body -- TMS + STREET ADDRESS IS -- that
    parse_advert() genuinely parses into a non-None Listing. Exercises the full
    fetch() -> parse_advert() pipeline unmocked past the retry wrap under test,
    the same way test_calhoun_overage_claims_retry.py's _minimal_pdf() does."""
    return (
        "<html><body>"
        f"<p>TMS: {tms}</p>"
        f"<p>STREET ADDRESS IS:\n{street_line}</p>"
        "</body></html>"
    )


def _sitemap_xml(*advert_paths: str) -> str:
    locs = "".join(
        f"<url><loc>https://mie.greenvillejournal.com{p}</loc></url>" for p in advert_paths
    )
    return f'<?xml version="1.0"?><urlset>{locs}</urlset>'


_ADVERT_1 = "/advert/2022-cp-23-03386"
_ADVERT_2 = "/advert/2023-cp-23-04026"
_ADVERT_BODY = _advert_html("0577040104000", "4002 Fork Shoals Rd Simpsonville, SC 29680")
_ADVERT_BODY_2 = _advert_html("0611010100700", "118 Pine St Greenville, SC 29601")


class _Transport:
    """Serves fetch()'s real HTTP shape: the one sitemap GET plus one GET per
    advert URL the sitemap lists. Exactly one path (`flaky_path`) is made flaky
    -- raising `exc` for its first `fail_times` hits, or, with `bad_status` set,
    always answering a fixed real HTTP status instead of raising. Every other
    path answers normally on its first and only hit, so a test on one call site
    can't be confused with a coincidental failure elsewhere."""

    def __init__(self, sitemap_xml: str, advert_bodies: dict[str, str],
                 flaky_path: str | None = None, fail_times: int = 0,
                 exc: Exception | None = None, bad_status: int | None = None):
        self.sitemap_xml = sitemap_xml
        self.advert_bodies = advert_bodies
        self.flaky_path = flaky_path
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.bad_status = bad_status
        self.calls: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls[path] = self.calls.get(path, 0) + 1

        if self.flaky_path and path == self.flaky_path:
            if self.bad_status is not None:
                return httpx.Response(self.bad_status, text="server error")
            if self.calls[path] <= self.fail_times:
                raise self.exc
            # cleared -- fall through to the real terminal response below.

        if path == SITEMAP_PATH:
            # Real production shape: this endpoint answers 404 while serving valid
            # XML, and fetch() deliberately never checks the status (see "DO NOT
            # check r.status_code" in the module). A 404 terminal response here
            # proves the fix didn't accidentally start gating on status.
            return httpx.Response(404, text=self.sitemap_xml)
        if path in self.advert_bodies:
            return httpx.Response(200, text=self.advert_bodies[path])
        return httpx.Response(404, text="")


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """The real backoff is 1-8s per attempt; make the retry tests instant."""
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _run_fetch(monkeypatch, transport):
    """fetch() builds its own httpx.AsyncClient internally -- route it through
    `transport` the same way test_calhoun_overage_claims_retry.py does."""
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return asyncio.run(m.GreenvilleMIEAdverts().fetch())


def _tms_set(out):
    return {li.parcel_id for li in out}


# --------------------------------------------------------------------------------------
# (1) fetch()'s own sitemap GET -- the headline, highest-severity call site: every
# advert URL the scrape ever sees comes from this one request.

def test_sitemap_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    transport = _Transport(
        sitemap_xml=_sitemap_xml(_ADVERT_1),
        advert_bodies={_ADVERT_1: _ADVERT_BODY},
        flaky_path=SITEMAP_PATH, fail_times=2,
    )
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls[SITEMAP_PATH] == 3   # 2 failures + the success
    assert _tms_set(out) == {"0577040104000"}   # the scrape completed normally after the retry


def test_sitemap_read_timeout_is_also_retried(monkeypatch):
    transport = _Transport(
        sitemap_xml=_sitemap_xml(_ADVERT_1),
        advert_bodies={_ADVERT_1: _ADVERT_BODY},
        flaky_path=SITEMAP_PATH, fail_times=1, exc=httpx.ReadTimeout("slow"),
    )
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls[SITEMAP_PATH] == 2
    assert _tms_set(out) == {"0577040104000"}


def test_sitemap_connect_timeout_that_never_clears_gives_up_not_hangs(monkeypatch):
    """A persistently-failing connection must cost exactly stop_after_attempt(3) raw
    HTTP attempts and then give up -- never retry forever. The exhausted-retry
    exception raises out of the AsyncRetrying block exactly as a real dead host
    would, and is caught by the pre-existing, unmodified
    `except Exception as exc: log.warning(...); return []` -- fetch() returns
    cleanly empty rather than hanging or raising out to the caller."""
    transport = _Transport(
        sitemap_xml=_sitemap_xml(_ADVERT_1),
        advert_bodies={_ADVERT_1: _ADVERT_BODY},
        flaky_path=SITEMAP_PATH, fail_times=99,
    )
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls[SITEMAP_PATH] == 3   # bounded -- not 4, not 99
    assert out == []


def test_sitemap_real_non_transport_error_is_not_retried_fails_on_attempt_1(monkeypatch):
    """c.get(SITEMAP) itself raising a real, non-transport RequestError (here:
    DecodingError, which httpx itself raises for an undecodable response body --
    NOT a TransportError/TimeoutException/TimeoutError) must not be retried at
    all -- attempt 1 is the only attempt, exactly like the pre-existing behavior
    for any non-transient failure. (There is no "bad status" variant of this test
    for this call site: fetch() never calls raise_for_status()/checks status on
    the sitemap response -- see the module's "DO NOT check r.status_code"
    comment -- so a bad status is simply not an exception here at all.)"""
    class _DecodeFailTransport:
        def __init__(self):
            self.calls = 0

        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.calls += 1
            raise httpx.DecodingError("bad encoding")

    transport = _DecodeFailTransport()
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    out = asyncio.run(m.GreenvilleMIEAdverts().fetch())
    assert transport.calls == 1
    assert out == []


# --------------------------------------------------------------------------------------
# (2) the nested one(u) helper -- one GET per advert URL. Lower blast radius: a
# failure here costs only that single advert, never the whole batch.

def test_advert_fetch_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    transport = _Transport(
        sitemap_xml=_sitemap_xml(_ADVERT_1, _ADVERT_2),
        advert_bodies={_ADVERT_1: _ADVERT_BODY, _ADVERT_2: _ADVERT_BODY_2},
        flaky_path=_ADVERT_1, fail_times=2,
    )
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls[_ADVERT_1] == 3    # 2 failures + the success
    assert transport.calls[_ADVERT_2] == 1    # unaffected sibling, hit once
    assert _tms_set(out) == {"0577040104000", "0611010100700"}   # both adverts landed


def test_advert_fetch_read_timeout_is_also_retried(monkeypatch):
    transport = _Transport(
        sitemap_xml=_sitemap_xml(_ADVERT_1),
        advert_bodies={_ADVERT_1: _ADVERT_BODY},
        flaky_path=_ADVERT_1, fail_times=1, exc=httpx.ReadTimeout("slow"),
    )
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls[_ADVERT_1] == 2
    assert _tms_set(out) == {"0577040104000"}


def test_advert_fetch_connect_timeout_that_never_clears_gives_up_not_hangs(monkeypatch):
    """Bounded at stop_after_attempt(3), then caught by one()'s own pre-existing
    `except Exception: stats["errors"] += 1; return` -- only THIS advert is
    dropped; the sibling advert (an independent request under the same
    asyncio.gather()) still lands, proving the per-item isolation the bug report
    called out still holds after the fix."""
    transport = _Transport(
        sitemap_xml=_sitemap_xml(_ADVERT_1, _ADVERT_2),
        advert_bodies={_ADVERT_1: _ADVERT_BODY, _ADVERT_2: _ADVERT_BODY_2},
        flaky_path=_ADVERT_1, fail_times=99,
    )
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls[_ADVERT_1] == 3    # bounded -- not 4, not 99
    tms = _tms_set(out)
    assert "0577040104000" not in tms          # the permanently-failing advert is lost
    assert tms == {"0611010100700"}            # the sibling advert is unaffected


def test_advert_fetch_real_bad_http_status_is_not_retried_fails_on_attempt_1(monkeypatch):
    """raise_for_status()'s HTTPStatusError does not match
    retry_if_exception_type((TransportError, TimeoutException, TimeoutError)),
    so a real bad status must not be retried at all -- attempt 1 is the only
    attempt, exactly like the pre-existing behavior for a bad status. Only this
    one advert is skipped; the sibling is unaffected."""
    transport = _Transport(
        sitemap_xml=_sitemap_xml(_ADVERT_1, _ADVERT_2),
        advert_bodies={_ADVERT_1: _ADVERT_BODY, _ADVERT_2: _ADVERT_BODY_2},
        flaky_path=_ADVERT_1, bad_status=500,
    )
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls[_ADVERT_1] == 1
    tms = _tms_set(out)
    assert "0577040104000" not in tms
    assert tms == {"0611010100700"}
