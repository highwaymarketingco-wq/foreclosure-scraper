"""counties_sc.kershaw_flc: 2026-10-02 per-source audit follow-up, item 4.

PAGE_URL (kershaw.sc.gov/treasurer/forfeited-land-commission) 404s live --
the county site reorganized onto a new URL scheme with no redirect.
Re-searched live for a replacement (new Treasurer/Delinquent-Matters page,
Auditor, Boards and Commissions, Bids and RFPs, the county's ArcGIS open-data
parcel layer -- no owner field -- and a general web search) and found no
current free FLC inventory anywhere; the one lead (qPublic owner-name
search) is gated behind a click-through Terms of Service, a compliance wall
per CLAUDE.md, not a technical gap. Disabled via disabled=True/
disabled_reason (same pattern as counties_sc.oconee_flc /
counties_sc.clarendon_tax_auction / national.loopnet) so safe_run() never
attempts the dead network call and reports DORMANT, not an ambiguous zero.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.counties_sc import kershaw_flc as m


def test_disabled_and_dormant():
    assert m.KershawFLC.disabled is True
    assert m.KershawFLC.disabled_reason
    assert "404" in m.KershawFLC.disabled_reason or "404s" in m.KershawFLC.disabled_reason

    scraper = m.KershawFLC()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()


def test_fetch_itself_also_returns_empty():
    """fetch() is never called by a disabled scraper's safe_run(), but it
    must still behave safely (no stale regex scrape) if ever invoked directly
    -- e.g. by a test or a manual probe script."""
    scraper = m.KershawFLC()
    out = asyncio.run(scraper.fetch())
    assert list(out) == []


def test_registered_in_the_registry():
    from foreclosure_scraper.scrapers._registry import discover

    slugs = [s.slug for s in discover()]
    assert "counties_sc.kershaw_flc" in slugs
