"""Marlboro County SC - Delinquent Tax Sale properties.

Marlboro County publishes delinquent tax sale properties on its county
website. Annual tax sale lists with owner names, TMS numbers, addresses.

DISABLED 2026-09-15, NOT JUST DORMANT -- found by a background triage
agent (this codebase's zero-row-scraper audit) and confirmed live by
hand: `PAGE_URL` is a generic "meeting_publications.php" page, not a
dedicated tax-sale page, and it currently carries the county's FY2026-27
BUDGET/MILLAGE table -- no tax-sale content at all right now. The old
`<tr>` parser has no way to tell a budget table from a real delinquent-
tax table (both are just `<table>` rows with numbers in them), so it
was emitting fake TAX_SALE listings from budget-line-item text (e.g.
`defendant: "PROPOSED Total Revenue Operating Budget"`), with one row
even attributing the county COURTHOUSE's own address to a fake lead.
Accidentally not reaching the board only because this source was never
in `main.py`'s DATELESS_OK_SOURCES and its `active_months=(10,11,12,1)`
gate happens to currently exclude September -- neither is a real
protection, and "fix" attempts that just widen the gate or add the
whitelist entry would ship this garbage straight onto the board.

`fetch()` is disabled (returns []) until this is rewritten against a
real, dedicated tax-sale page/document (none has been located yet;
Marlboro's site does not appear to publish one anywhere reachable) or
gets a genuine per-row validator that can tell a tax-sale row from a
budget row.

Free, public, no login.
Slug: counties_sc.marlboro_delinquent_tax
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()

PAGE_URL = "https://www.marlborocounty.sc.gov/government_/meeting_publications.php"


class MarlboroDelinquentTax(BaseScraper):
    slug = "counties_sc.marlboro_delinquent_tax"
    name = "Marlboro County SC Delinquent Tax Sale"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        # Disabled -- see the module docstring. PAGE_URL is a generic
        # meetings/publications page that currently carries a BUDGET table,
        # not a tax-sale list, and the old parser could not tell them apart.
        log.info("marlboro_tax.disabled", note="awaiting a real dedicated tax-sale source or a row validator")
        return []
