"""counties_sc.sc_qpublic: 2026-10-14 source-completeness audit follow-up.

The audit flagged this file as "worth confirming the search form even works at
all -- the code never submits a query." Live-reverified (not assumed): the old
``_COUNTY_PAGES`` URL scheme (``Application.aspx?App={County}SC&Page=search``)
is itself invalid -- it 500s with a generic Schneider backend error for every
county tried (Berkeley, Beaufort, Colleton), unrelated to Cloudflare. Correcting
the alias to ``App={County}CountySC`` (confirmed against the sibling
``kershaw_flc`` docstring + the already-known-good Oconee app in
``assessor_cards/qpublic_render.py``) does resolve real per-county landing pages
for Kershaw/Oconee/Colleton, but NOT for Berkeley/Beaufort (still the same
error) -- so even the URL bug isn't a uniform one-line fix across the dict.

More fundamentally: on the apps that DO resolve, both real query mechanisms
(owner/address/parcel Search, Sales Search) are stateful ASP.NET WebForms POST
pages (``__VIEWSTATE``/``__EVENTTARGET`` + a postback search button) with a
JS-rendered results grid -- confirmed live via raw HTML capture of Kershaw's
Search (PageTypeID=2/PageID=15084) and Sales Search (PageID=15087) pages. A
plain GET -- all ``http_client.get_text(wall_bypass=True)`` and every
``wall_bypass.py`` tier can do -- cannot submit this form; a GET
``KeyValue=`` shortcut to the Results route (PageTypeID=3/PageID=15085) loads
the real page/route but the results grid stays empty (zero ``<table>`` rows,
zero occurrences of the search term anywhere in the body).

Disabled via disabled=True/disabled_reason (same pattern as
counties_sc.oconee_flc / counties_sc.clarendon_tax_auction /
counties_sc.kershaw_flc) so safe_run() never attempts the dead network call
and reports DORMANT, not an ambiguous zero.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_DORMANT
from foreclosure_scraper.scrapers.counties_sc import sc_qpublic as m


def test_disabled_and_dormant():
    assert m.ScQpublicScraper.disabled is True
    assert m.ScQpublicScraper.disabled_reason
    assert "VIEWSTATE" in m.ScQpublicScraper.disabled_reason

    scraper = m.ScQpublicScraper()
    out = asyncio.run(scraper.safe_run())

    assert out == []
    assert scraper.last_outcome == OUTCOME_DORMANT
    assert "disabled" in scraper.last_reason.lower()


def test_fetch_itself_also_returns_empty():
    """fetch() is never called by a disabled scraper's safe_run(), but it must
    still behave safely (no stale regex scrape against a dead URL scheme) if
    ever invoked directly -- e.g. by a test or a manual probe script."""
    scraper = m.ScQpublicScraper()
    out = asyncio.run(scraper.fetch())
    assert list(out) == []


def test_registered_in_the_registry():
    from foreclosure_scraper.scrapers._registry import discover

    slugs = [s.slug for s in discover()]
    assert "counties_sc.sc_qpublic" in slugs
