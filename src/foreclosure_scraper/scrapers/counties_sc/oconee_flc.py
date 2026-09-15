"""Oconee County SC - Forfeited Land Commission (FLC) properties.

Oconee County's FLC page lists available forfeited land commission
properties - properties the county acquired through tax delinquency.

DISABLED 2026-09-15, NOT JUST DORMANT. First found by a background
triage agent (this codebase's zero-row-scraper audit): the original
`(?:TMS|PIN|Parcel)` regex had no word boundary, so "PIN" matched as a
bare substring inside page CSS like ".spin-button{...}", producing a
fake parcel_id. Patched that (word boundary + require the capture to
start with a digit) and re-verified live -- which surfaced a SECOND,
deeper problem the first fix didn't touch: the `addresses` regex
(a digit-run followed by street-suffix words like St/Ave/Rd/...) matches ANY address-shaped
text ANYWHERE on the page, with no way to tell "the county TREASURER
OFFICE's own street address" (which is printed on essentially every
county contact page) from a real delinquent property. Confirmed live
post-fix: still 4 fake rows, all four with street_address literally
"415 S. Pine St. Walhalla, SC 29691" -- the county office's own address,
repeated once per contact block on the page (address / hours / phone /
fax), not four different properties.

`fetch()` is disabled (returns []) until this has a real way to
distinguish an FLC property listing from the page's own contact
boilerplate -- e.g. a dedicated FLC inventory page/document, if Oconee
publishes one, rather than scraping oconeesc.com/treasurer-home's
free text for address-shaped substrings.

Free, public, no login.
Slug: counties_sc.oconee_flc
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()

PAGE_URL = "https://oconeesc.com/treasurer-home"


class OconeeFLC(BaseScraper):
    slug = "counties_sc.oconee_flc"
    name = "Oconee County SC Forfeited Land Commission"
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        # Disabled -- see the module docstring. The free-text address/parcel
        # regex approach cannot tell the county office's own contact address
        # from a real FLC property listing.
        log.info("oconee_flc.disabled", note="awaiting a real FLC inventory source, not free-text address scraping")
        return []
