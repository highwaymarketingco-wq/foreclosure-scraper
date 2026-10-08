"""Western NC multi-county — Tax foreclosure / delinquent tax pages.

Several small Western NC counties publish tax foreclosure and delinquent
tax sale information on their county websites but don't warrant individual
scraper modules due to low volume.  This scraper covers them all:

- Watauga County (wataugacounty.org)
- Avery County (averycountync.gov)
- Yancey County (yanceycountync.gov)
- Cherokee NC County (cherokeecounty-nc.gov)
- Madison County (madisoncountync.gov)

Each county page is checked for property listings, PDF links to tax sale
lists, and delinquent tax information.

FIXED 2026-10-03 (HERMES sec 8 per-source audit, batch 7). ``COUNTIES["Avery"]``
pointed at ``averycounty.com`` -- live-fetched and confirmed that domain is the
AVERY COUNTY CHAMBER OF COMMERCE (title: "Avery County Chamber of Commerce --
Home of the Annual Woolly Worm Festival...", 6 unrelated "tax" hits all from a
WordPress Directorist plugin's internal field names, zero county-government
content). This guaranteed 0 real rows for Avery FOREVER, for the wrong reason
(wrong site entirely, not "no data published"). The real county government
site is ``averycountync.gov`` (confirmed via its own title "Welcome to Avery
County"); its Tax Assessor's page (`/departments/tax_assessors_office.php`)
links a real "Property For Sale" page (sealed-bid sale of county-held parcels,
authorized by the Board of Commissioners) -- live-verified real content
("Currently there are no properties for sale" today, a genuine 0, not a
parse failure).

ALSO VERIFIED LIVE (no fix needed, two other counties' real foreclosure path
runs through sources this project already built elsewhere, same-day):
Watauga's own Tax Collections page states real-property tax foreclosure "is
handled by a Law firm located in Boone, NC" with NO firm name and NO link
anywhere on the page or site -- a genuine wall (nothing to follow, not a code
gap). Yancey's own "2025 TAX FORECLOSURE PROCESS" PDF names its foreclosure
attorney as kanialawfirm.com -- the SAME statewide Kania Ninja-Tables feed
``law_firms.kania`` already reads and (as of today's separate scope-bug fix)
now emits EVERY real NC county the feed carries, Yancey included when the
feed has a Yancey row (0 right now, matching the PDF's "sales do not occur on
a regular schedule"). Cherokee's tax-sale table is likewise already read by
the dedicated ``nc_civicplus_tax_sale`` module. Nothing for THIS generic
multi-county module to add for either -- it cannot see Kania's JSON-via-
WordPress-nonce feed or civicplus's own parser through a generic
`<table>`-on-the-county's-own-site heuristic, and it does not need to: the
real data already lands on the board via those dedicated sources.

FOUND 2026-09-15 (background triage agent, this codebase's zero-row-
scraper audit; confirmed by hand): Madison County's own homepage links
to `lrcpwa.ncptscloud.com`, which reliably ConnectTimeouts -- and despite
every individual `get_text()` call already sitting inside its own
try/except, a single dead host was observed stalling the ENTIRE 5-county
sweep for 170+ seconds straight before this fix, meaning `get_text()`'s
own internal retry/impersonation-escalation chain can run well past its
nominal `timeout=` kwarg on a host that is truly unreachable (as opposed
to one that answers slowly). Watauga/Avery/Yancey/Cherokee's homepages
all fetch fine in a couple of seconds each -- one bad link was starving
four working counties. Every fetch in this module is now wrapped in
`asyncio.wait_for()` with a SHORT outer deadline, so a truly dead host
costs this scraper a bounded ~20s instead of an unbounded multiple of
get_text's own internal timeout.

Free, public, no login.
Slug: counties_nc.wnc_tax_foreclosures
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

#: Outer per-fetch deadline. Deliberately shorter than get_text's own
#: `timeout=` kwarg -- that timeout governs ONE internal attempt, not the
#: full retry/impersonation-escalation chain, which is what actually
#: stalled on a truly dead host (see module docstring).
_FETCH_DEADLINE_S = 20.0


async def _bounded_text(url: str, **kwargs) -> str | None:
    try:
        return await asyncio.wait_for(get_text(url, **kwargs), timeout=_FETCH_DEADLINE_S)
    except Exception as exc:  # noqa: BLE001 - one dead host must not kill the whole sweep
        log.warning("wnc_tax.fetch_timeout_or_fail", url=url, error=str(exc)[:160])
        return None


COUNTIES: dict[str, str] = {
    "Watauga": "https://www.wataugacounty.org/",
    # NOT averycounty.com -- that domain is the Avery County CHAMBER OF
    # COMMERCE (Woolly Worm Festival site), not the county government.
    # Live-confirmed 2026-10-03; see module docstring.
    "Avery": "https://www.averycountync.gov/",
    "Yancey": "https://www.yanceycountync.gov/",
    "Cherokee": "https://www.cherokeecounty-nc.gov/",
    "Madison": "https://www.madisoncountync.gov/",
}

#: A county's own tax-foreclosure page, read directly every run (2026-10-08 source-completeness
#: audit). Madison's homepage carries no foreclosure link: its first three "tax" links are a
#: room-occupancy PDF, the ArcGIS tax map and "Property Tax Search" = lrcpwa.ncptscloud.com/Madison
#: (a JavaScript app with no HTML table, which also timed out on the VM: wnc_tax.fetch_timeout_or_fail
#: on 2026-10-08). The real page is Tax Administration -> "Tax Foreclosure Sales" (live 2026-10-08:
#: process text only, no sale list posted, a genuine 0; the county says sales are advertised in
#: the newspaper and "may be posted to the County's website").
COUNTY_TAX_PAGES: dict[str, list[str]] = {
    "Madison": ["https://www.madisoncountync.gov/tax-foreclosure-sale.html"],
}

#: Link targets that never hold an HTML sale table: vendor tax apps (JavaScript SPAs), payment
#: portals, map viewers. Following one costs a fetch (lrcpwa: a 20 s timeout) and yields nothing.
#: PDFs are skipped too: PDF-following was removed on purpose (see the note in fetch()).
_SKIP_LINK_RE = re.compile(
    r"ncptscloud\.com|govpayments\.com|experience\.arcgis\.com|arcgis\.com/apps|\.pdf(?:$|[?#])",
    re.I)


class WNCTaxForeclosures(BaseScraper):
    slug = "counties_nc.wnc_tax_foreclosures"
    name = "Western NC Multi-County Tax Foreclosures"
    category = "county_tax"
    timeout_s = 180.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []

        for county, base_url in COUNTIES.items():
            direct = [(u, "county tax-foreclosure page") for u in COUNTY_TAX_PAGES.get(county, [])]
            html = await _bounded_text(base_url, impersonate=True, timeout=40.0)
            if not html or len(html) < 200:
                html = ""

            # Find tax/foreclosure/sale related links
            links = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.I | re.S)
            tax_links: list[tuple[str, str]] = []
            for href, text in links:
                low = (href + " " + re.sub(r"<[^>]+>", "", text)).lower()
                if any(kw in low for kw in ("tax", "foreclos", "delinquent", "sale", "auction", "sheriff", "bid", "treasurer", "collector")):
                    tax_links.append((urljoin(base_url, href), re.sub(r"<[^>]+>", "", text).strip()))
            # The same first three links as before, minus the ones that can never hold a table
            # (never a different, later link: a tax-rates table would parse as sale rows).
            known = {u for u, _ in direct}
            tax_links = direct + [t for t in tax_links[:3]
                                  if t[0] not in known and not _SKIP_LINK_RE.search(t[0])]

            # Follow tax-related links and parse
            for tax_url, link_text in tax_links:
                if tax_url == base_url:
                    continue
                sub_html = await _bounded_text(tax_url, impersonate=True, timeout=40.0)
                if not sub_html:
                    continue

                # Parse table rows
                rows = re.findall(r"<tr[^>]*>(.*?)</tr>", sub_html, re.I | re.S)
                for row in rows:
                    cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
                    if len(cells) < 2:
                        continue
                    clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                    if any(h in c.lower() for c in clean[:2] for h in ("owner", "name", "parcel", "pin", "address", "#")):
                        continue

                    parcel = None
                    for c in clean:
                        # A dashed NC PIN ("9700-12-3456[-000]") first: the general pattern
                        # stopped at its second group ("9700-12").
                        m = re.search(r"\b(\d{4}-\d{2}-\d{4}(?:-\d{1,6})?|\d{4,}[-\s]?[\d.]+)\b", c)
                        if m:
                            parcel = m.group(1)
                            break

                    owner = clean[0] if clean else None
                    addr = None
                    for c in clean[1:]:
                        if re.search(r"\d+\s+\w+", c):
                            addr = c
                            break

                    amount = None
                    for c in clean:
                        m = re.search(r"\$[\d,]+", c)
                        if m:
                            try:
                                amount = float(m.group().replace("$", "").replace(",", ""))
                            except ValueError:
                                pass

                    # A row with neither a parcel-shaped id nor a dollar amount is page layout,
                    # not a property (Madison's Weebly pages lay their footer nav out as a
                    # one-row <table> of "Home | Departments | ..."), 2026-10-08.
                    if not parcel and amount is None:
                        continue

                    out.append(Listing(
                        source="counties_nc.wnc_tax_foreclosures",
                        source_url=tax_url,
                        listing_type=ListingType.TAX_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        state="NC",
                        county=county,
                        parcel_id=parcel,
                        defendant=owner,
                        street_address=addr,
                        judgment_amount=amount,
                        description=" | ".join(clean[:8]) if clean else None,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"wnc_tax_foreclosures": {"county": county, "cells": clean[:10], "source_link": link_text}},
                    ))

                # PDF-following DELIBERATELY REMOVED 2026-09-15. Verified live after
                # fixing this module's timeout-hang bug (see module docstring): with
                # the hang fixed, the sweep completed in 47.5s and returned 282 rows
                # -- every single one GARBAGE. The "any .pdf link near a tax-ish
                # keyword" heuristic grabbed Watauga's USPS delivery-standards manual
                # (linked from an unrelated planning/permits page that happened to
                # also mention "tax" somewhere), and its table of contents ("Finding
                # Your Growth Manager and USPS Online Resources", "Appeal Process for
                # Builders and Developers") got emitted as fake tax-foreclosure
                # listings with parcel/address pulled from chapter numbers and street
                # names in unrelated boilerplate. Same class of harm as nc_deq_dsca's
                # nav-menu garbage, found the same day. Rather than tighten the
                # per-line heuristic under time pressure and risk a subtler version
                # of the same failure, the PDF-following pass is removed entirely --
                # this module now only emits rows from an ACTUAL HTML table it finds
                # on a tax-labeled page, which is a structurally safer signal (a real
                # <table> with real cells, not "any text near a scary-looking PDF").
                # Currently 0 real rows across all 5 counties either way (none of
                # their tax pages carry a live HTML table right now) -- re-add PDF
                # support only with real per-document validation (e.g. require the
                # PDF's OWN filename/title to match a tax-foreclosure pattern, not
                # just nearby link text), not a blanket "parse every linked PDF".

        log.info("wnc_tax.done", count=len(out))
        return out
