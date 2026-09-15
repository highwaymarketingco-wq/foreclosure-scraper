"""SC DES (formerly DHEC) Brownfields / Voluntary Cleanup Program sites.

SC DES publishes a list of brownfield sites and voluntary cleanup
properties at des.sc.gov.  These are properties with known environmental
contamination or cleanup agreements — a distress signal for property
intelligence (stigmatized property, cleanup costs, motivated seller).

Data shape: the main brownfields page links to individual environmental
site pages under des.sc.gov/community/environmental-sites-projects/.
We scrape the listing page for site names and links, then yield each as
a DISTRESSED listing.  Individual site pages may have address details
which we could follow in a future enrichment pass.

Free, public, no login.
Slug: counties_sc.sc_des_brownfields
Category: environmental
ListingType: DISTRESSED
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = (
    "https://des.sc.gov/programs/bureau-land-waste-management/"
    "brownfields-voluntary-cleanup-program"
)
SITE_LIST_URL = "https://des.sc.gov/community/environmental-sites-projects"


class SCDESBrownfields(BaseScraper):
    slug = "counties_sc.sc_des_brownfields"
    name = "SC DES Brownfields & Voluntary Cleanup Sites"
    category = "environmental"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_urls: set[str] = set()

        for url in (PAGE_URL, SITE_LIST_URL):
            try:
                html = await get_text(url, impersonate=True, timeout=40.0)
            except Exception as exc:
                log.warning("sc_des_brownfields.fetch_fail", url=url, error=str(exc)[:160])
                continue

            if not html:
                continue

            # Find all links to environmental site pages
            links = re.findall(
                r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                html,
                re.I | re.S,
            )
            for href, link_text in links:
                full_url = urljoin(url, href)
                # Only follow links to site pages on des.sc.gov
                if "des.sc.gov" not in full_url:
                    continue
                # FOUND 2026-09-15 (background triage agent, this codebase's
                # zero-row-scraper audit): the original filter matched on
                # keywords in EITHER the resolved URL or the link TEXT, and
                # both leaked garbage. (1) Text match: section/nav labels
                # like "Brownfields Funding & Incentives" and "Brownfields
                # Success Stories" contain "brownfield" without being a real
                # site page. (2) URL match: PAGE_URL's own path contains
                # "cleanup-program", so a plain in-page anchor link like
                # href="#main-content" resolved (via urljoin) to a URL that
                # STILL contained "cleanup" -- "Skip to main content" and
                # "Menu" landed on the board as fake sites this way.
                # Confirmed live: real site links (verified via
                # "Congaree River Sediment Cleanup", a genuine cleanup site)
                # all share ONE real structural signal instead --
                # /environmental-sites-projects/<real-slug>, e.g.
                # ".../community/environmental-sites-projects/congaree-river-
                # sediment-cleanup" or ".../community-engagement/
                # environmental-sites-projects/college-charleston-project-
                # 205". Match on THAT specific path shape only, not on
                # loose keywords in the URL or the link text.
                if not re.search(r"environmental-sites-projects/[a-z0-9][a-z0-9-]+", full_url, re.I):
                    continue
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                site_name = re.sub(r"<[^>]+>", "", link_text).strip()
                if not site_name or len(site_name) < 3:
                    continue

                out.append(Listing(
                    source="counties_sc.sc_des_brownfields",
                    source_url=full_url,
                    listing_type=ListingType.DISTRESSED,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Statewide",
                    description=site_name,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"sc_des_brownfield": {
                        "site_name": site_name,
                        "url": full_url,
                        "source_page": url,
                    }},
                ))

        log.info("sc_des_brownfields.done", count=len(out))
        return out
