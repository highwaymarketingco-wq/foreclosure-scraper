"""NC DEQ DSCA — Dry-Cleaning Solvent Cleanup Act site list.

The NC Department of Environmental Quality (DEQ) maintains a list of
properties contaminated by dry-cleaning solvents under the DSCA program.
These properties have environmental contamination that can affect
property value and marketability — a distress signal for property
intelligence.

DISABLED, NOT JUST DORMANT — found 2026-09-15 (background triage agent,
this codebase's zero-row-scraper audit; confirmed live by hand before
touching this file). This module was WORSE than a silent zero: run live,
it returned `count=4` and `outcome=OK`, but all 4 "listings" were GARBAGE
-- the program-description page this used to target
(`.../dry-cleaning-solvent-cleanup-act-program`, itself a 301 redirect to
`.../superfund-section/dry-cleaning-solvent-cleanup-act-program`) has no
site-list table at all, just prose and a SIDEBAR NAVIGATION table. The
`<tr>` regex matched that nav table instead, and nothing in the header-
skip check caught it, so "Public Notices", "Contacts", "Statutes/Rules"
and "Stakeholder Work Group" (the nav labels) landed on the board as fake
"DSCA contamination site" listings with every structured field null.

The REAL, current DSCA site data lives on a DIFFERENT DEQ page
(`.../science-data-and-reports/dsca-site-listsfacility-inventories`) as
downloadable Excel files ("active-and-inactive-drycleaner-facilities-
excel-...", "closed-dry-cleaner-facilities-excel-..."), not an HTML table
at all -- a genuinely different, bigger build (download + parse .xlsx,
same stdlib zip+XML approach as richland_flc.py) that was out of scope to
rush alongside the immediate safety fix. `fetch()` is disabled to return
nothing rather than resurrect the risk of emitting garbage again from a
page shape it was never built to parse. Re-enable only once rewritten
against the real Excel source.

Free, public, no login.
Slug: counties_nc.nc_deq_dsca
Category: environmental
ListingType: DISTRESSED
"""
from __future__ import annotations

from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()

#: The real site list -- see the module docstring. Not yet fetched/parsed
#: (downloadable Excel, not an HTML table); kept here as the documented
#: next target rather than the old page, which has no real data at all.
REAL_DATA_PAGE_URL = "https://www.deq.nc.gov/about/divisions/waste-management/science-data-and-reports/dsca-site-listsfacility-inventories"


class NCDEQDSCA(BaseScraper):
    slug = "counties_nc.nc_deq_dsca"
    name = "NC DEQ DSCA Contamination Sites"
    category = "environmental"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        # Disabled -- see the module docstring. The page this used to parse
        # has no site-list table; its <tr> regex was matching the page's
        # SIDEBAR NAVIGATION table instead and emitting nav-menu labels as
        # fake contamination-site listings. Returning nothing is strictly
        # better than that until this is rewritten against the real
        # downloadable-Excel source at REAL_DATA_PAGE_URL.
        log.info("nc_deq_dsca.disabled", note="awaiting rewrite against REAL_DATA_PAGE_URL's Excel files")
        return []
