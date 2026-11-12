"""sc_coastal_rosters._query_layer: the county-native ArcGIS ``/query`` call made
inside its nested ``_query()`` closure had zero retry cushioning on a transport
error or timeout -- identical in shape to the already-fixed gaps in
arcgis_webmap.query_features, spartan_weekly_legals.py and the Column
legal-notice API scraper. The only error handling was
``except (httpx.HTTPError, ValueError): return None``, which silently converted
a transient connection reset/timeout into the exact same outcome as a genuine
"TMS not found" miss -- risking that one listing's lat/lng enrichment (and
therefore its admission through main._in_scope's near-beach gate) being
silently dropped over nothing worse than a one-off network blip.

Note on shape (b) below: _query_layer's own contract is ``Optional[dict]`` --
a persistent failure and a genuine miss both legitimately resolve to ``None``
for its callers (that part of the design is unchanged by this fix). What the
fix actually bounds is *how many raw HTTP attempts* a persistent transport
failure costs before giving up: exactly ``stop_after_attempt(3)`` attempts with
short backoff, never an unbounded/infinite retry loop.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import sc_coastal_rosters as scr
from foreclosure_scraper.scrapers.counties_sc.sc_coastal_rosters import _query_layer

LAYER_URL = "https://gis.example.test/arcgis/rest/services/Parcels/MapServer/1/query"

# A TMS that _tms_candidates reduces to exactly ONE candidate ("ABC" itself --
# it isn't letter+digits so the grouped-PIN branch doesn't fire, and it has no
# digits at all so the numeric variants are empty strings and never added).
# With a single id_field this means _query_layer issues exactly ONE _query()
# call (no second "unquoted numeric" attempt, no LIKE fallback), so the raw
# transport call count maps 1:1 onto one AsyncRetrying cycle -- which is what
# lets these tests pin exact attempt counts.
_TMS = "ABC"
_FIELDS = ("TMS",)


class _FlakyTransport(httpx.AsyncBaseTransport):
    """Raises a transport/timeout error on the first ``fail_times`` requests,
    then serves a real terminal ArcGIS response."""

    def __init__(self, fail_times: int, exc: Exception | None = None, hit: bool = False):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.hit = hit
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        if self.hit:
            return httpx.Response(200, json={
                "features": [{"attributes": {"TMS": _TMS}, "geometry": {"x": -79.0, "y": 33.0}}]
            })
        return httpx.Response(200, json={"features": []})


class _FixedStatusTransport(httpx.AsyncBaseTransport):
    """Always answers with the same real (non-transport) HTTP status."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(self.status_code, json={})


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Keep the exponential-jitter backoff effectively instant in tests."""
    monkeypatch.setattr(
        scr, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    transport = _FlakyTransport(fail_times=2, hit=True)

    async def run():
        async with httpx.AsyncClient(transport=transport) as c:
            return await _query_layer(c, LAYER_URL, _FIELDS, _TMS)

    attrs = asyncio.run(run())
    assert transport.calls == 3          # 2 failures + the attempt that succeeded
    assert attrs is not None
    assert attrs["_centroid"] == (33.0, -79.0)


def test_a_read_timeout_is_also_retried():
    transport = _FlakyTransport(fail_times=1, exc=httpx.ReadTimeout("slow"), hit=True)

    async def run():
        async with httpx.AsyncClient(transport=transport) as c:
            return await _query_layer(c, LAYER_URL, _FIELDS, _TMS)

    attrs = asyncio.run(run())
    assert transport.calls == 2
    assert attrs is not None


def test_a_connect_timeout_that_never_clears_still_returns_promptly_not_a_hang():
    """A persistently-failing transport must cost exactly stop_after_attempt(3)
    raw HTTP attempts, then give up -- never retry forever. Because
    _query_layer's own pre-existing broad ``except (httpx.HTTPError, ...)``
    treats ANY httpx error (including the reraised exhausted-retry exception)
    as a benign miss, the function still returns ``None`` here rather than
    raising -- that part of its contract for callers is unchanged. What this
    pins down is that the failure is bounded at 3 real attempts, not infinite."""
    transport = _FlakyTransport(fail_times=99)

    async def run():
        async with httpx.AsyncClient(transport=transport) as c:
            return await _query_layer(c, LAYER_URL, _FIELDS, _TMS)

    result = asyncio.run(run())
    assert transport.calls == 3   # stop_after_attempt(3), then gives up -- not 4, not 99
    assert result is None


def test_a_real_bad_http_status_is_not_retried_fails_on_attempt_1():
    """A real (non-transport) bad status is not a transport/timeout error, so
    it must not be retried at all -- the existing ``r.status_code != 200``
    check converts it straight to a miss on the very first attempt."""
    transport = _FixedStatusTransport(503)

    async def run():
        async with httpx.AsyncClient(transport=transport) as c:
            return await _query_layer(c, LAYER_URL, _FIELDS, _TMS)

    result = asyncio.run(run())
    assert transport.calls == 1
    assert result is None


def test_a_200_with_an_error_body_is_not_retried():
    """The classic HTTP-200-plus-error-body shape (e.g. a type mismatch on the
    where clause) is not a transport/timeout error either, and must also fail
    immediately rather than being retried."""

    class _ErrorBodyTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.calls = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return httpx.Response(200, json={"error": {"code": 400, "message": "bad where"}})

    transport = _ErrorBodyTransport()

    async def run():
        async with httpx.AsyncClient(transport=transport) as c:
            return await _query_layer(c, LAYER_URL, _FIELDS, _TMS)

    result = asyncio.run(run())
    assert transport.calls == 1
    assert result is None
