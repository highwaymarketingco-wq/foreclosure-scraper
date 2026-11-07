"""albemarle_observer_tax_lists.AlbemarleObserverTaxLists.fetch(): a transient transport/timeout
error on either of its two httpx calls gets retried, not treated as "the whole run failed."

Found via the proven-bug-shape sweep (2026-11-07): this scraper rolls its own bare
``httpx.AsyncClient`` -- it never goes through the shared ``http_client.client()`` /
``get_text()`` helpers, which DO wrap their calls in ``AsyncRetrying`` (``client()``'s own
``AsyncHTTPTransport(retries=0)`` says so explicitly: "callers already wrap their own
AsyncRetrying"). Both of its network calls were wrapped only in a bare
``except Exception: ... return/continue``, with zero retry of any kind, at any layer:

* line ~494 -- the WordPress REST API index search (``search=delinquent``). This runs ONCE,
  before the loop over all 9 ``Target`` entries (Tyrrell, Washington, Plymouth, Gates, Bertie,
  Chowan, Hyde, Perquimans, Pasquotank). A single transient blip here used to zero the ENTIRE
  run's output, not just one county -- the textbook single-point-of-failure shape.
* line ~508 -- the per-target post fetch, inside that loop. A transient blip here only used to
  drop that one target's county, lower severity but equally unprotected.

Because this scraper is listed in ``main.DATELESS_OK_SOURCES``, a zeroed run has no fallback
date window to recover via a later run noticing a gap -- it just silently reports an
empty/healthy result. Same root-cause shape already fixed elsewhere in this sweep (a Column
legal-notice API scraper, spartan_weekly_legals.py, arcgis_webmap.query_features).

Each test drives the real ``fetch()`` through an ``httpx.MockTransport``, the same pattern the
module's own ``test_albemarle_observer_tax_lists.py`` already uses for its network-path tests
(this scraper builds its own ``httpx.AsyncClient`` rather than taking an injectable client, so
there is no narrower retry-only entry point to call directly).
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
import pytest
from tenacity import wait_exponential_jitter

import foreclosure_scraper.scrapers.counties_nc.albemarle_observer_tax_lists as m

TODAY = datetime(2026, 9, 21)

TYRRELL_CONTENT = "<ul><li>AGUILAR, HILDA C00415005 485.94</li></ul>"
BERTIE_CONTENT = ("<table><tbody><tr><td>ALSTON ANNETTE</td><td>25A5869412801</td>"
                   "<td>$66.87</td></tr></tbody></table>")

TYRRELL_POST = {"id": 7, "date": "2026-04-27T10:00:00", "link": "u7",
                "title": {"rendered": "Public Record: Tyrrell County 2025 Unpaid Taxes List"}}
BERTIE_POST = {"id": 6, "date": "2026-06-05T10:00:00", "link": "u6",
               "title": {"rendered": "Bertie County 2025 delinquent personal property tax list"}}


def _single_target_index():
    """Only Tyrrell matches -- a run touches exactly 2 URLs (index, then Tyrrell's post),
    which keeps the index-level call-count assertions isolated from the per-post call site."""
    return [dict(TYRRELL_POST)]


def _two_target_index():
    """Tyrrell + Bertie both match -- lets a post-fetch failure on ONE target be checked
    against the OTHER target's county still coming through, proving the per-item-loop call
    site only drops the one target, not the whole run."""
    return [dict(TYRRELL_POST), dict(BERTIE_POST)]


def _index_response(index):
    return httpx.Response(200, json=index)


def _post_response(pid, content):
    return httpx.Response(200, json={"id": pid, "content": {"rendered": content}})


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same trick as test_arcgis_webmap_query_features_retry.py: swap the module's own
    `wait_exponential_jitter` for a near-instant version so the retry tests don't sit through
    real backoff delays."""
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _patch_client(monkeypatch, transport):
    """Same pattern as test_albemarle_observer_tax_lists.py's own `_patch`: force the
    scraper's self-built httpx.AsyncClient onto our MockTransport, kill the inter-target
    pacing sleep, and pin "today" so pick_post's 400-day-age window is deterministic."""
    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    monkeypatch.setattr(m, "PACE_S", 0.0)
    monkeypatch.setattr(m, "datetime", type("D", (datetime,), {"utcnow": staticmethod(lambda: TODAY)}))


# --------------------------------------------------------------------------- index call site


def test_a_transient_index_error_is_retried_and_then_succeeds(monkeypatch):
    calls = {"index": 0}

    def handler(req: httpx.Request):
        if "search=delinquent" in str(req.url):
            calls["index"] += 1
            if calls["index"] <= 2:
                raise httpx.ConnectTimeout("boom")
            return _index_response(_single_target_index())
        pid = int(req.url.path.rsplit("/", 1)[1])
        return _post_response(pid, TYRRELL_CONTENT)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    out = asyncio.run(m.AlbemarleObserverTaxLists().fetch())
    assert calls["index"] == 3                      # 2 failures + 1 success, within stop_after_attempt(3)
    assert [l.county for l in out] == ["Tyrrell"]    # retried through to a real result, not a zeroed run


def test_a_transient_index_error_that_never_clears_still_fails_after_the_retry_budget_not_a_hang(monkeypatch):
    calls = {"index": 0}

    def handler(req: httpx.Request):
        if "search=delinquent" in str(req.url):
            calls["index"] += 1
            raise httpx.ConnectTimeout("boom")
        pid = int(req.url.path.rsplit("/", 1)[1])
        return _post_response(pid, TYRRELL_CONTENT)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    out = asyncio.run(m.AlbemarleObserverTaxLists().fetch())
    assert calls["index"] == 3     # stop_after_attempt(3), then gives up -- not an infinite hang
    assert out == []               # a persistent failure still zeros the run (log-and-bail), same as before


def test_a_real_bad_status_on_the_index_is_not_retried(monkeypatch):
    calls = {"index": 0}

    def handler(req: httpx.Request):
        if "search=delinquent" in str(req.url):
            calls["index"] += 1
            return httpx.Response(503)
        pid = int(req.url.path.rsplit("/", 1)[1])
        return _post_response(pid, TYRRELL_CONTENT)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    out = asyncio.run(m.AlbemarleObserverTaxLists().fetch())
    assert calls["index"] == 1     # a real bad status is not a transport/timeout error -- no retry at all
    assert out == []


# ------------------------------------------------------------------ per-target post call site


def test_a_transient_post_fetch_error_is_retried_and_then_succeeds(monkeypatch):
    calls = {"post_7": 0}

    def handler(req: httpx.Request):
        if "search=delinquent" in str(req.url):
            return _index_response(_two_target_index())
        pid = int(req.url.path.rsplit("/", 1)[1])
        if pid == 7:
            calls["post_7"] += 1
            if calls["post_7"] <= 2:
                raise httpx.ReadTimeout("slow")
            return _post_response(pid, TYRRELL_CONTENT)
        return _post_response(pid, BERTIE_CONTENT)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    out = asyncio.run(m.AlbemarleObserverTaxLists().fetch())
    assert calls["post_7"] == 3
    assert sorted({l.county for l in out}) == ["Bertie", "Tyrrell"]   # Tyrrell retried through, not dropped


def test_a_transient_post_fetch_error_that_never_clears_drops_only_that_target_not_the_whole_run(monkeypatch):
    calls = {"post_7": 0}

    def handler(req: httpx.Request):
        if "search=delinquent" in str(req.url):
            return _index_response(_two_target_index())
        pid = int(req.url.path.rsplit("/", 1)[1])
        if pid == 7:
            calls["post_7"] += 1
            raise httpx.ReadTimeout("slow")
        return _post_response(pid, BERTIE_CONTENT)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    out = asyncio.run(m.AlbemarleObserverTaxLists().fetch())
    assert calls["post_7"] == 3                           # stop_after_attempt(3), then gives up -- no hang
    assert sorted({l.county for l in out}) == ["Bertie"]   # only Tyrrell is dropped; Bertie still comes through


def test_a_real_bad_status_on_a_post_fetch_is_not_retried(monkeypatch):
    calls = {"post_7": 0}

    def handler(req: httpx.Request):
        if "search=delinquent" in str(req.url):
            return _index_response(_two_target_index())
        pid = int(req.url.path.rsplit("/", 1)[1])
        if pid == 7:
            calls["post_7"] += 1
            return httpx.Response(500)
        return _post_response(pid, BERTIE_CONTENT)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    out = asyncio.run(m.AlbemarleObserverTaxLists().fetch())
    assert calls["post_7"] == 1    # a real bad status is not a transport/timeout error -- no retry at all
    assert sorted({l.county for l in out}) == ["Bertie"]
