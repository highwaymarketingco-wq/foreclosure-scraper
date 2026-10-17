"""national.homepath_json: a transient transport error on a page fetch gets retried,
not treated as "the whole state's sweep failed."

Found 2026-10-17 (gap-sweep, per-source network-call audit): both real external
network call sites in this module -- ``_fetch_state``'s main paginated search
call and ``_enrich_galleries``'s per-listing detail-page call -- go through the
shared ``http_client.client()`` helper, which does NOT retry internally (its own
module comment: "callers already wrap their own AsyncRetrying"). Neither call
site wrapped its request in any retry mechanism; the only error handling was a
bare ``try/except Exception: log.warning(...); break``/``continue``, so a single
transient blip permanently zeroed (``_fetch_state``) or impoverished
(``_enrich_galleries``) that run's results -- the exact same root cause already
fixed tonight for the Column legal-notice API scraper, spartan_weekly_legals.py,
and arcgis_webmap.query_features().

``_fetch_state`` is the higher-severity finding: its pagination loop is NOT a
per-item loop -- one failed page aborts ALL remaining pages for that state, and
because this source is in ``main.DATELESS_OK_SOURCES`` (no fallback date
window), a zeroed run cannot self-heal later. ``_enrich_galleries`` is lower
severity (each listing is independent -- a failure there only costs that one
listing its extra gallery/agent contact) but gets the identical treatment for
consistency.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import homepath_json as m


def _prop(uuid: str, state: str = "NC") -> dict:
    return {
        "propertyUuid": uuid,
        "addressLine1": "1 Test St",
        "city": "Asheville",
        "state": state,
        "zipCode": "28801",
        "county": "BUNCOMBE COUNTY",
        "propertyType": "Single Family",
        "price": 100000,
        "geoPoint": {"latitude": 35.5, "longitude": -82.5},
    }


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        m, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


# ---------------------------------------------------------------------------
# _fetch_state (PRIMARY: single_point_of_failure -- one failed page used to
# abort the whole state's pagination sweep).
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyClient:
    """Mimics the async-context-manager `client()` returns: raises on the
    first `fail_times` calls to `.get`, then serves a real page."""

    def __init__(self, fail_times: int, exc=None, page_payload=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0
        self._page_payload = page_payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None, follow_redirects=True):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        if self._page_payload is not None:
            return _FakeResp(self._page_payload)
        # Default: one real row then an empty terminal page.
        return _FakeResp({"properties": []})


def test_fetch_state_transient_transport_error_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyClient(fail_times=2, page_payload={"properties": [_prop("ok-1")]})
    monkeypatch.setattr(m, "client", lambda timeout=30.0: fake)

    out = asyncio.run(m._fetch_state("NC", "national.homepath_json"))

    assert fake.calls == 3  # 2 failures + 1 success, within stop_after_attempt(3)
    assert len(out) == 1
    assert out[0].case_number == "fannie-ok-1"


def test_fetch_state_transient_error_that_never_clears_does_not_hang_and_gives_up(monkeypatch):
    fake = _FlakyClient(fail_times=99)
    monkeypatch.setattr(m, "client", lambda timeout=30.0: fake)

    # Must complete promptly (no infinite retry loop) rather than hang.
    out = asyncio.run(asyncio.wait_for(
        m._fetch_state("NC", "national.homepath_json"), timeout=5.0
    ))

    assert fake.calls == 3  # stop_after_attempt(3) exhausted, then gives up
    # _fetch_state's own existing (unchanged) contract: a page fetch that
    # ultimately fails logs + breaks the pagination loop -- it does not crash
    # the caller. With the fix, that only happens after retries are spent.
    assert out == []


def test_fetch_state_read_timeout_is_also_retried(monkeypatch):
    fake = _FlakyClient(
        fail_times=1, exc=httpx.ReadTimeout("slow"),
        page_payload={"properties": [_prop("ok-2")]},
    )
    monkeypatch.setattr(m, "client", lambda timeout=30.0: fake)

    out = asyncio.run(m._fetch_state("NC", "national.homepath_json"))

    assert fake.calls == 2
    assert len(out) == 1
    assert out[0].case_number == "fannie-ok-2"


def test_fetch_state_real_bad_status_is_not_retried(monkeypatch):
    class _BadStatusClient:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None, follow_redirects=True):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    fake = _BadStatusClient()
    monkeypatch.setattr(m, "client", lambda timeout=30.0: fake)

    out = asyncio.run(m._fetch_state("NC", "national.homepath_json"))

    assert fake.calls == 1  # a real bad status is not a transport/timeout error
    assert out == []


# ---------------------------------------------------------------------------
# _enrich_galleries (SECONDARY: per_item_loop -- same fix for consistency).
# ---------------------------------------------------------------------------


class _FlakyDetailHttp:
    def __init__(self, fail_times: int, exc=None, detail_payload=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0
        self._detail_payload = detail_payload if detail_payload is not None else {}

    async def get(self, url, headers=None, follow_redirects=True):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self._detail_payload)


def _listing_with_uuid(uuid: str):
    li = m._to_listing(_prop(uuid), m.HomePathJSON.slug)
    assert li is not None
    return li


def test_enrich_galleries_transient_transport_error_is_retried_and_then_succeeds():
    detail_payload = {
        "propertyPics": [{"imageUrl": "https://homepath.fanniemae.com/images/a.jpg"}],
        "brokerCompanies": [{"contacts": [{"fullName": "Jane Agent", "phoneNumber": "555-1111"}]}],
    }
    http = _FlakyDetailHttp(fail_times=2, detail_payload=detail_payload)
    li = _listing_with_uuid("gal-1")

    asyncio.run(m._enrich_galleries(http, [li], deadline=float("inf")))

    assert http.calls == 3
    assert li.raw["homepath_json"]["agent"]["name"] == "Jane Agent"
    assert "https://homepath.fanniemae.com/images/a.jpg" in li.raw["images"]["real"]


def test_enrich_galleries_transient_error_that_never_clears_does_not_hang():
    http = _FlakyDetailHttp(fail_times=99)
    li = _listing_with_uuid("gal-2")

    # Must complete promptly (no infinite retry loop) rather than hang, and
    # must not drop the row -- it simply keeps whatever it already had.
    asyncio.run(asyncio.wait_for(
        m._enrich_galleries(http, [li], deadline=float("inf")), timeout=5.0
    ))

    assert http.calls == 3  # stop_after_attempt(3) exhausted, then gives up
    assert "agent" not in li.raw["homepath_json"]


def test_enrich_galleries_real_bad_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, headers=None, follow_redirects=True):
            self.calls += 1
            return _FakeResp({}, status_code=500)

    http = _BadStatusHttp()
    li = _listing_with_uuid("gal-3")

    asyncio.run(m._enrich_galleries(http, [li], deadline=float("inf")))

    assert http.calls == 1  # a real bad status is not a transport/timeout error
    assert "agent" not in li.raw["homepath_json"]
