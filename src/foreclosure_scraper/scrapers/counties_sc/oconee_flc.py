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

`fetch()` was disabled (returned []) pending a real FLC inventory source.
AUDITED 2026-10-01: that real source already exists as sibling scrapers in
this same package -- counties_sc.oconee_forfeited_land and counties_sc.
oconee_flc_assignment both read Oconee's actual FLC inventory off the
county's own ArcGIS layer (services1.arcgis.com/UOvRn2Rvzysthh3i), not free
text. Converted to the standard disabled=True/disabled_reason so this reads
correctly in run reports (DORMANT, not an ambiguous silent zero) instead of
the ad hoc `return []` the 2026-09-15 fix used.

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
    disabled = True
    disabled_reason = ("free-text address/parcel scraping of a contact page can't tell the "
                       "courthouse's own address from a real listing - superseded by sibling "
                       "counties_sc.oconee_forfeited_land / oconee_flc_assignment (ArcGIS) - confirmed 2026-10-01")
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        return []
