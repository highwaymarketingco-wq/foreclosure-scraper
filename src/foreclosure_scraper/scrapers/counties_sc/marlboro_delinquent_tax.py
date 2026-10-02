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

`fetch()` was disabled (returned []) pending a real, dedicated tax-sale
page/document. AUDITED 2026-10-01: that real source turned out to already
exist elsewhere in this codebase rather than on Marlboro's own site --
counties_sc.qpaybill_delinquent_roll.py covers Marlboro's actual delinquent
roll (QPAYBILL_SUBS["Marlboro"] = "marlborocountytax") with owner, situs,
balance and years-delinquent, something this budget/meetings page was never
going to produce safely. Converted to the standard disabled=True/
disabled_reason so this reads correctly in run reports (DORMANT, not an
ambiguous silent zero) instead of the ad hoc `return []` the 2026-09-15 fix
used.

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
    disabled = True
    disabled_reason = ("PAGE_URL is a generic meetings/publications page (budget tables, not "
                       "tax-sale data) - superseded by counties_sc.qpaybill_delinquent_roll "
                       "(Marlboro) - confirmed 2026-10-01")
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        return []
