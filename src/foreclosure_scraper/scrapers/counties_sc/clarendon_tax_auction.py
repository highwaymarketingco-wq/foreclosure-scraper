"""Clarendon County SC — Treasurer Auction properties.

Clarendon County treasurer posts properties for auction at
clarendoncountysc.gov.  The county website features an auction hammer
icon linking to delinquent tax sale properties.

DISABLED 2026-09-15, NOT JUST DORMANT -- found by a background triage
agent (this codebase's zero-row-scraper audit) and confirmed live by
hand: the keyword-link-follower ("auction", "tax sale", "delinquent",
"foreclos", "sheriff", "treasurer", "bid" anywhere in a link's href or
text) is far too broad for this county's homepage. Live run produced 23
fake TAX_SALE rows: 20 were rows from the county's UNRELATED procurement/
RFP portal (clarendoncountyprocurement.sc.gov/solicitations -- e.g.
`defendant: "ITB 2025-012"`, a road-paving-contract bid notice), and 3
were random county-council MEETING-AGENDA PDFs mislabeled
`"Tax auction PDF: ...january-12-2026.pdf"`. Every fake row had
parcel_id=None. Accidentally not reaching the board only because this
source was never in `main.py`'s DATELESS_OK_SOURCES and its
`active_months=(9,10,11,12,1)` gate happens to not yet have started for
2026 -- neither is a real protection, and a "fix" that just widens the
gate or adds the whitelist entry would ship this straight onto the
board the moment September ends.

`fetch()` was disabled (returned []) pending a real per-link/per-document
validator. AUDITED 2026-10-01: that real source turned out to already exist
elsewhere in this codebase -- counties_sc.qpaybill_delinquent_roll.py covers
Clarendon's actual delinquent roll (QPAYBILL_SUBS["Clarendon"] =
"clarendoncountysc") with owner, situs, balance and years-delinquent, so a
rewritten per-document validator here would only reproduce the same data
less reliably. Converted to the standard disabled=True/disabled_reason so
this reads correctly in run reports (DORMANT, not an ambiguous silent zero)
instead of the ad hoc `return []` the 2026-09-15 fix used.

Free, public, no login.
Slug: counties_sc.clarendon_tax_auction
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()

PAGE_URL = "https://www.clarendoncountysc.gov/"


class ClarendonTaxAuction(BaseScraper):
    slug = "counties_sc.clarendon_tax_auction"
    name = "Clarendon County SC Tax Auction Properties"
    disabled = True
    disabled_reason = ("keyword-link-follower grabbed the county's unrelated procurement/RFP "
                       "portal and meeting-agenda PDFs as fake tax listings - superseded by "
                       "counties_sc.qpaybill_delinquent_roll (Clarendon) - confirmed 2026-10-01")
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        return []
