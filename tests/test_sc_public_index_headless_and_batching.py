"""national.sc_public_index: the 2026-09-27 investigation into repeated,
confirmed ZERO-row runs (timeout_s=180 exceeded, no rows, twice in one week).

TWO separate, stacked bugs were found -- fixing only one would not have
restored real output:

BUG #1 -- headless nodriver is silently WAF-blocked, MEASURED live 2026-09-27:
``uc.start(headless=True)`` never raises for publicindex.sccourts.org, so the
old ``except Exception: browser = await uc.start(headless=False)`` fallback
never fired. What actually happens: headless Chrome's first navigation gets
HTTP 406 from the WAF, which Chrome renders as its own
chrome-error://chromewebdata interstitial (confirmed via location.href and
the body text "This page isn't working ... HTTP ERROR 406"). That "succeeds"
(no exception) at loading a WAF block page, so the disclaimer-accept click
grabbed Chrome's own "Reload" button instead, and every run found no search
form and returned 0 rows -- for EVERY county, regardless of the 26-prefix
timing arithmetic. Headed (headless=False) navigation to the SAME URL got the
real disclaimer page every time tested live -- matching
enrichment_case_detail.py's own docstring for this exact site: "nodriver
(headless=False) — the ONLY method that works for SC Public Index." The fix
detects the block from PAGE CONTENT (chrome-error:// on the current URL)
rather than an exception handler nothing ever throws into.

BUG #2 -- even with #1 fixed, one WORKING county's full 26-prefix sweep is
~353s wall-clock (Spartanburg, MEASURED live 2026-09-27: 1,233 deduped real
CP cases) -- confirming the task's own arithmetic (26 x 12.5s + disclaimer
overhead ~= 345s) was right all along. 44 non-Charleston counties x ~353s is
~4.3 HOURS; no realistic timeout_s covers all of them in one invocation. The
fix batches a bounded, day-rotating slice of counties per run (BATCH_SIZE,
COUNTY_TIMEOUT_S, _select_county_batch) -- same "reduce scope per run, land
real progress every run instead of none" direction as this same week's
counties_sc.qpaybill_delinquent_roll county-launch-gating fix -- and salvages
per-county into self.partial so base_scraper.safe_run()'s timeout-salvage
path has something to ship if timeout_s fires mid-batch anyway.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
from unittest.mock import AsyncMock, MagicMock

import nodriver
import pytest

from foreclosure_scraper.base_scraper import OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.national import sc_public_index as m


def _case(case_number: str, name: str = "Doe John", role: str = "Defendant") -> dict:
    """A minimal but realistic case record, same shape _parse_search_results produces."""
    return {"name": name, "role": role, "case_number": case_number,
            "date_filed": "01/01/2026", "status": "Active", "date_disposed": ""}


# ---------------------------------------------------------------------------
# BUG #1 -- headless-mode WAF block must be detected by CONTENT, not exception
# ---------------------------------------------------------------------------

_FORM_HTML = (
    "<html><body>"
    "<input type='text' id='ContentPlaceHolder1_TextBoxlastName'>"
    "</body></html>"
)

_RESULTS_HTML = """
<table>
  <tr><th>Name</th><th>Role</th><th>Case</th></tr>
  <tr><td>x</td><td>x</td><td>x</td></tr>
  <tr><td>Doe John</td><td>Defendant</td><td>2026CP4200001</td></tr>
</table>
"""


def _fake_evaluate(location_href=None):
    async def _ev(js, *_a, **_kw):
        if js == "location.href":
            return location_href
        return None
    return AsyncMock(side_effect=_ev)


def _fake_page(*, location_href=None):
    """A page whose get_content() answers the disclaimer-form-check first,
    then the search-results check on every call after -- matching the two
    real get_content() call sites in _nodriver_search_county."""
    page = MagicMock()
    btn = MagicMock()
    btn.click = AsyncMock(return_value=None)
    page.find = AsyncMock(return_value=btn)
    page.evaluate = _fake_evaluate(location_href)

    calls = {"n": 0}

    async def _get_content():
        calls["n"] += 1
        return _FORM_HTML if calls["n"] == 1 else _RESULTS_HTML

    page.get_content = AsyncMock(side_effect=_get_content)
    return page


def _fake_browser(page) -> MagicMock:
    browser = MagicMock()
    browser.get = AsyncMock(return_value=page)
    browser.stop = MagicMock()
    return browser


@pytest.fixture
def _single_prefix_and_fast_sleep(monkeypatch):
    """Same rationale as test_sc_public_index_browser_cleanup.py: only the
    control flow (headless-vs-headed, cleanup) is under test here, not a
    real 26-letter x 12.5s sweep. NOT autouse -- the fetch()-level batching
    tests below need a REAL asyncio.sleep to simulate a genuinely slow
    county against a tiny timeout, so this is opted into explicitly by only
    the low-level _nodriver_search_county tests that need it."""
    monkeypatch.setattr(m, "SEARCH_PREFIXES", ["A"])

    async def _fast_sleep(*_a, **_kw):
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)


@pytest.mark.asyncio
async def test_headless_waf_block_is_detected_and_headed_retry_is_used(
        monkeypatch, _single_prefix_and_fast_sleep):
    """The exact 2026-09-27 finding: uc.start(headless=True) never raises, so
    the old exception-based fallback never fired. The fix must detect the
    block from location.href and restart headed -- proven here by using TWO
    distinct fake browsers and asserting nodriver.start was called with
    headless=True THEN headless=False, and that real rows come back (from
    the headed browser only)."""
    headless_page = _fake_page(location_href="chrome-error://chromewebdata/")
    headless_browser = _fake_browser(headless_page)
    headed_page = _fake_page(location_href="https://publicindex.sccourts.org/x")
    headed_browser = _fake_browser(headed_page)

    starts: list[bool] = []

    async def fake_start(headless=True, **_kw):
        starts.append(headless)
        return headless_browser if headless else headed_browser

    monkeypatch.setattr(nodriver, "start", fake_start)

    result = await m._nodriver_search_county("spartanburg")

    assert starts == [True, False], (
        "must try headless first, detect the WAF block, then start headed -- "
        f"got {starts!r}")
    headless_browser.stop.assert_called_once()  # blocked browser closed before retry
    headed_browser.stop.assert_called_once()    # final cleanup (outer finally)
    assert [r["case_number"] for r in result] == ["2026CP4200001"], (
        "the headed browser's real page content must be what gets parsed")


@pytest.mark.asyncio
async def test_headless_success_never_triggers_a_headed_restart(
        monkeypatch, _single_prefix_and_fast_sleep):
    """The detection must not false-positive on a normal, working headless
    page -- only chrome-error:// on location.href should trigger a restart."""
    page = _fake_page(location_href="https://publicindex.sccourts.org/x")
    browser = _fake_browser(page)

    starts: list[bool] = []

    async def fake_start(headless=True, **_kw):
        starts.append(headless)
        return browser

    monkeypatch.setattr(nodriver, "start", fake_start)

    result = await m._nodriver_search_county("spartanburg")

    assert starts == [True], f"headed fallback must not fire when headless works, got {starts!r}"
    browser.stop.assert_called_once()
    assert len(result) == 1


@pytest.mark.asyncio
async def test_headless_block_with_non_string_location_href_does_not_crash(
        monkeypatch, _single_prefix_and_fast_sleep):
    """page.evaluate("location.href") returning None/non-string (e.g. a stub
    or a real edge case) must be treated as NOT blocked, not raise."""
    page = _fake_page(location_href=None)
    browser = _fake_browser(page)
    monkeypatch.setattr(nodriver, "start", AsyncMock(return_value=browser))

    result = await m._nodriver_search_county("spartanburg")

    assert len(result) == 1
    browser.stop.assert_called_once()


# ---------------------------------------------------------------------------
# BUG #2 -- county batching / rotation / per-county timeout / partial salvage
# ---------------------------------------------------------------------------

class _FixedDatetime:
    """Stand-in for the `datetime` class in sc_public_index's namespace,
    exposing only what _select_county_batch calls (.utcnow())."""

    def __init__(self, value):
        self._value = value

    def utcnow(self):
        return self._value


def _freeze_day(monkeypatch, year, month, day):
    monkeypatch.setattr(m, "datetime", _FixedDatetime(_dt.datetime(year, month, day)))


def test_select_county_batch_never_exceeds_batch_size():
    counties = [f"county{i}" for i in range(44)]
    batch = m._select_county_batch(counties, 2)
    assert 0 < len(batch) <= 2
    assert len(set(batch)) == len(batch)  # no duplicates
    assert set(batch) <= set(counties)


def test_select_county_batch_empty_inputs():
    assert m._select_county_batch([], 2) == []
    assert m._select_county_batch(["a", "b"], 0) == []
    assert m._select_county_batch(["a", "b"], -1) == []


def test_select_county_batch_same_day_is_stable(monkeypatch):
    """Re-running on the same UTC day (e.g. a retried scoped-scraper dry run)
    must hit the SAME batch -- no hidden randomness."""
    counties = ["a", "b", "c", "d", "e"]
    _freeze_day(monkeypatch, 2026, 5, 10)
    first = m._select_county_batch(counties, 2)
    second = m._select_county_batch(counties, 2)
    assert first == second


def test_select_county_batch_rotates_to_cover_every_county_within_a_cycle(monkeypatch):
    """Over one full rotation cycle (ceil(N/batch_size) distinct days), every
    county must be reached at least once -- the whole point of batching
    instead of permanently narrowing scope."""
    counties = [f"county{i}" for i in range(m.BATCH_SIZE * 5 + 1)]  # not an exact multiple
    n_batches = -(-len(counties) // m.BATCH_SIZE)

    seen: set[str] = set()
    base = _dt.datetime(2026, 1, 1)
    for day_offset in range(n_batches):
        _freeze_day(monkeypatch, base.year, base.month, base.day)
        base = base + _dt.timedelta(days=1)
        seen.update(m._select_county_batch(counties, m.BATCH_SIZE))

    assert seen == set(counties), (
        f"missing counties after a full {n_batches}-day rotation: "
        f"{set(counties) - seen}")


def test_real_module_constants_are_sized_with_margin_over_the_measurement():
    """Regression guard against silently drifting back toward the original
    failure: BaseScraper's default timeout_s=180 was never enough (one
    working county sweep alone measures ~353s), and this scraper's own
    values must leave real margin over the measured per-county time and over
    each other, not merely be non-default."""
    MEASURED_SINGLE_COUNTY_S = 353.0
    assert m.COUNTY_TIMEOUT_S > MEASURED_SINGLE_COUNTY_S, (
        "COUNTY_TIMEOUT_S must clear the measured real county time with margin")
    assert m.SCPublicIndexScraper.timeout_s >= m.BATCH_SIZE * m.COUNTY_TIMEOUT_S, (
        "timeout_s must cover the whole batch's worst case (every batched "
        "county using its full COUNTY_TIMEOUT_S), not just the happy path")


def test_fetch_runs_charleston_every_time_and_batches_the_rest(monkeypatch):
    """Charleston (fast curl path) is not part of the slow-batch budget and
    must run every invocation regardless of the day-based rotation; the
    other counties are limited to whatever _select_county_batch returns."""
    monkeypatch.setattr(m, "_curl_search_county", AsyncMock(
        return_value=[_case("2026CP1000001")]))

    async def fake_nodriver(county):
        return [_case(f"2026CP99{abs(hash(county)) % 9000 + 1000}")]

    monkeypatch.setattr(m, "_nodriver_search_county", fake_nodriver)
    monkeypatch.setattr(m, "_select_county_batch",
                         lambda counties, n: counties[:2])

    scraper = m.SCPublicIndexScraper()
    scraper._counties = ["charleston", "spartanburg", "greenville", "pickens", "oconee"]

    listings = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    # charleston + 2 batched counties = 3 real rows, NOT all 5 counties
    assert len(listings) == 3


def test_fetch_populates_partial_incrementally_for_salvage(monkeypatch):
    """self.partial is base_scraper.safe_run()'s timeout-salvage mechanism.
    fetch() used to only ever build its result at the very end, so a
    scraper-level timeout mid-run discarded every county already collected.
    This proves partial mirrors the final output on a clean run."""
    monkeypatch.setattr(m, "_curl_search_county", AsyncMock(
        return_value=[_case("2026CP1000001")]))

    async def fake_nodriver(county):
        return [_case("2026CP1000002")] if county == "spartanburg" else [_case("2026CP1000003")]

    monkeypatch.setattr(m, "_nodriver_search_county", fake_nodriver)
    monkeypatch.setattr(m, "_select_county_batch",
                         lambda counties, n: counties[:2])

    scraper = m.SCPublicIndexScraper()
    scraper._counties = ["charleston", "spartanburg", "greenville"]

    listings = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert len(listings) == 3
    assert {li.case_number for li in scraper.partial} == {li.case_number for li in listings}
    assert len(scraper.partial) == 3


def test_one_hung_county_does_not_zero_out_the_batch(monkeypatch):
    """Mirrors counties_sc.qpaybill_delinquent_roll's exact fix shape: a
    per-county asyncio.wait_for(COUNTY_TIMEOUT_S) must abandon a hung county
    WITHOUT blocking the other batched county's already-collected rows."""
    monkeypatch.setattr(m, "COUNTY_TIMEOUT_S", 0.05)
    monkeypatch.setattr(m, "_curl_search_county", AsyncMock(return_value=[]))
    monkeypatch.setattr(m, "_select_county_batch",
                         lambda counties, n: ["stuck", "fine"])

    async def fake_nodriver(county):
        if county == "stuck":
            await asyncio.Event().wait()  # never completes
        return [_case("2026CP1000099")]

    monkeypatch.setattr(m, "_nodriver_search_county", fake_nodriver)

    scraper = m.SCPublicIndexScraper()
    scraper._counties = ["charleston", "stuck", "fine"]

    listings = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert len(listings) == 1
    assert listings[0].case_number == "2026CP1000099"


def test_safe_run_salvages_charleston_when_the_scraper_timeout_fires_mid_batch(monkeypatch):
    """End-to-end through base_scraper.safe_run(), matching the exact live
    failure shape (scraper-level soft timeout firing with real rows already
    collected but never shipped): Charleston finishes fast and is salvaged
    even though a batched county is still running when timeout_s fires."""
    monkeypatch.setattr(m, "COUNTY_TIMEOUT_S", 30.0)  # far above timeout_s below
    monkeypatch.setattr(m.SCPublicIndexScraper, "timeout_s", 0.15)
    monkeypatch.setattr(m, "_curl_search_county", AsyncMock(
        return_value=[_case("2026CP1000001")]))
    monkeypatch.setattr(m, "_select_county_batch",
                         lambda counties, n: ["slow"])

    async def fake_nodriver(county):
        await asyncio.sleep(5.0)
        return [_case("2026CP1000002")]

    monkeypatch.setattr(m, "_nodriver_search_county", fake_nodriver)

    scraper = m.SCPublicIndexScraper()
    scraper._counties = ["charleston", "slow"]

    out = asyncio.run(scraper.safe_run())

    assert scraper.last_outcome == OUTCOME_PARTIAL, (
        f"expected Charleston's row to be salvaged as PARTIAL, got "
        f"{scraper.last_outcome!r} ({scraper.last_reason!r})")
    assert len(out) == 1
    assert out[0].case_number == "2026CP1000001"
