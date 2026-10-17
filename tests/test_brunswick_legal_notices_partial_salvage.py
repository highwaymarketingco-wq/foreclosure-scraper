"""brunswick_legal_notices.fetch(): self.partial (base_scraper's own documented timeout-salvage
mechanism) is now populated as each notice is parsed, before the slow sequential NC OneMap
geo-resolution pass runs.

Found 2026-10-17 (gap-sweep wave 6, source-county-floor): docs/run_meta.json's own
source_status for this slug was '[ALARM] TIMEOUT: exceeded soft timeout 240s' with 0 rows on a
run where the HTML list parse had already succeeded (a handful of notices, always a small
number -- tax-sale notices are episodic). fetch() built each Listing into a local `out` list and
never touched self.partial anywhere; base_scraper.safe_run() only ships self.partial on a
TimeoutError, returning [] when it is empty. A slow/degraded NC OneMap during _geo_enrich's
sequential per-parcel resolution could blow the remaining budget and discard every already-parsed
notice. Same bug class and same fix shape already applied to gannett_obituaries.py and
funeral_home_rss.py in this repo.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.counties_nc import brunswick_legal_notices as bln


def _rows(n: int):
    return [(f"12345-{i}", f"https://x.test/notice-{i}.pdf", "2026-10-01") for i in range(n)]


def test_self_partial_mirrors_the_returned_listings_on_a_clean_run(monkeypatch):
    """On a run that completes normally (no timeout), self.partial must hold exactly what
    fetch() returned -- proving the incremental population doesn't drop or duplicate anything
    even when nothing goes wrong."""
    monkeypatch.setattr(bln, "get_text", _async_return("<html>fake list page</html>"))
    monkeypatch.setattr(bln, "parse_legal_notices", lambda html: _rows(3))
    monkeypatch.setattr(bln, "_fetch_pdf_fields", _async_return({}))
    monkeypatch.setattr(bln, "_geo_enrich", _async_return(0))
    monkeypatch.setattr(bln, "stamp_documents", lambda *a, **k: None)

    scraper = bln.BrunswickLegalNotices()
    out = asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))

    assert len(out) == 3
    assert {li.parcel_id for li in scraper.partial} == {li.parcel_id for li in out}
    assert len(scraper.partial) == 3


def test_safe_run_salvages_already_parsed_notices_when_geo_enrich_times_out(monkeypatch):
    """The actual bug, reproduced end-to-end through base_scraper.safe_run(): the HTML list
    parse succeeds (a handful of real notices), then the slow sequential NC OneMap
    geo-resolution pass hangs past the scraper's soft timeout. Before the fix, safe_run()'s
    TimeoutError handler found self.partial empty and reported 0 rows -- the exact shape of
    the live '[ALARM] TIMEOUT ... 0 rows' run."""
    monkeypatch.setattr(bln, "get_text", _async_return("<html>fake list page</html>"))
    monkeypatch.setattr(bln, "parse_legal_notices", lambda html: _rows(5))
    monkeypatch.setattr(bln, "_fetch_pdf_fields", _async_return({}))
    monkeypatch.setattr(bln, "stamp_documents", lambda *a, **k: None)

    async def _hangs(listings):
        await asyncio.sleep(3600.0)
        return 0

    monkeypatch.setattr(bln, "_geo_enrich", _hangs)

    scraper = bln.BrunswickLegalNotices()
    scraper.timeout_s = 0.15
    out = asyncio.run(scraper.safe_run())

    assert scraper.last_outcome == OUTCOME_PARTIAL, (
        f"expected the 5 already-parsed notices to be salvaged as PARTIAL, got "
        f"{scraper.last_outcome!r} ({scraper.last_reason!r})")
    assert len(out) == 5


def _async_return(value):
    async def _fn(*_a, **_k):
        return value
    return _fn
