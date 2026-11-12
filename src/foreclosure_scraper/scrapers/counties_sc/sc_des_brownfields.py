"""SC DES (formerly DHEC) Brownfields / Voluntary Cleanup Program sites.

SC DES publishes a list of brownfield sites and voluntary cleanup
properties at des.sc.gov.  These are properties with known environmental
contamination or cleanup agreements — a distress signal for property
intelligence (stigmatized property, cleanup costs, motivated seller).

Data shape: the main brownfields page links to individual environmental
site pages under des.sc.gov/community/community-engagement/
environmental-sites-projects/. We scrape the listing page for site names
and links, then follow through to EACH site's own detail page (2026-10-01
per-source audit) to pull two real fields the listing page never carries:
a "Tags" taxonomy block (sometimes a county name, sometimes a company name
or topic keyword) and the page's own narrative body text.

SITE_LIST_URL FIX (2026-10-01): the old path
"des.sc.gov/community/environmental-sites-projects" now 404s — the site
was restructured under "community-engagement" sometime after this scraper
was written. Verified live: the old URL is a dead 404, the new path
(below) answers 200 with 79 site links versus the 58 reachable only
through the brownfields program page's own embedded links. This was a
silent undetected-site-change drop: the try/except around each URL
swallowed the 404 as a quiet warning instead of failing loudly, so the
missing ~20+ sites were never noticed.

COUNTY EXTRACTION DISCIPLINE: a site's detail page is narrative prose
(DHEC incident write-ups), not structured address data, and this
codebase has already found and disabled a scraper
(city_websites/cities.py) for fabricating leads by loosely matching
keywords/dates anywhere on a page. To avoid repeating that mistake, county
is set ONLY when the page's own "Tags" taxonomy block (a real, structured
Drupal field, not inferred from prose) contains EXACTLY ONE value that is
a real SC county name — verified live this carries real county tags
("Jasper" on able-contracting-fire) but also non-county tags (company
names like "New Indy", topic words like "Pollution") and sometimes two
counties at once (new-indy-catawba: "Lancaster" + "York", a real
cross-county case) — ambiguous or absent cases fall back to "Statewide"
rather than guessing.

Free, public, no login.
Slug: counties_sc.sc_des_brownfields
Category: environmental
ListingType: DISTRESSED
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urljoin

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...document_links import harvest_document_links, stamp_documents
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind
from ...validation import SC_COUNTIES

log = structlog.get_logger()

PAGE_URL = (
    "https://des.sc.gov/programs/bureau-land-waste-management/"
    "brownfields-voluntary-cleanup-program"
)
# Fixed 2026-10-01 — old path (.../community/environmental-sites-projects,
# no "community-engagement" segment) confirmed live 404. See module docstring.
SITE_LIST_URL = "https://des.sc.gov/community/community-engagement/environmental-sites-projects"

_SITE_PATH_RE = re.compile(r"environmental-sites-projects/[a-z0-9][a-z0-9-]+", re.I)
_DETAIL_CONCURRENCY = 6


def _extract_site_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return (full_url, site_name) pairs for real site detail pages.

    Filters out nav/menu/section-label links the same way the original
    2026-09-15 fix did: real site links all share the structural signal
    ".../environmental-sites-projects/<real-slug>"; loose keyword matching
    on the URL or link text caught "Skip to main content" and section
    headers like "Brownfields Success Stories" instead.

    Uses a real HTML parser, not a regex over the tag soup. A prior regex
    version (r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>') silently dropped 21 of
    79 real site links on the live SITE_LIST_URL page: somewhere earlier in
    the 420KB document an overlapping/malformed anchor let the non-greedy
    `.*?</a>` match jump past several real `<a href=".../able-contracting-
    fire" title="...">...</a>` tags without ever matching them as their own
    group -- confirmed live by isolating the exact same snippet (which
    matched fine alone) versus running the regex over the full page (which
    missed it). selectolax parses the real DOM instead of guessing at tag
    boundaries, so it cannot be fooled by unbalanced markup elsewhere on
    the page the way a regex scan can.
    """
    tree = HTMLParser(html)
    out: list[tuple[str, str]] = []
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        full_url = urljoin(base_url, href)
        if "des.sc.gov" not in full_url:
            continue
        if not _SITE_PATH_RE.search(full_url):
            continue
        site_name = a.text(deep=True).strip()
        if not site_name or len(site_name) < 3:
            continue
        out.append((full_url, site_name))
    return out


def _parse_detail_page(html: str, base_url: str = "") -> tuple[Optional[str], Optional[str], list[str]]:
    """Return (county, description_snippet, document_urls) from a site's own detail page.

    county is set ONLY when the page's structured "Tags" field contains
    exactly one value matching a real SC county name — see the module
    docstring for why prose-based inference is deliberately avoided.
    description_snippet is the page's own first substantial paragraph of
    real body text (never fabricated/guessed).

    document_urls (2026-10-04 extraction-completeness audit): these DHEC site
    pages link real case documents — Emergency Orders, Corrective Action
    Plans, quarterly monitoring/progress reports, site maps, public notices —
    that were fetched (the page is already in hand for the description above)
    and then thrown away. Live-verified on 3 real sites: able-contracting-fire
    (4 docs incl. its Emergency Order), circle-k-stores-inc-petroleum-leak-
    ravenel (16 docs), csxt-bramlett-road-site (~100 docs spanning a decade of
    remediation reports).

    harvest_document_links() is run ONLY over body_el's own HTML, never the
    full page. Every DES site page shares the same ~9 global-nav boilerplate
    PDF links (generic "guidance-documents"/"public-notice-requirements"
    pages that appear on literally every page on des.sc.gov) that live
    OUTSIDE the article body and would otherwise win stamp_documents()'s
    8-link cap on every single one of the ~96 sites before a single real
    per-site document got a slot — confirmed live: scoping to the full page
    returned the same ~9 boilerplate links first on both a 4-document site
    and a 100-document site. Scoping to body_el alone reproduces exactly the
    real per-site documents with zero boilerplate.
    """
    tree = HTMLParser(html)
    county = None
    tags_el = tree.css_first(".field--name-field-categories")
    if tags_el:
        tags = [t.text().strip() for t in tags_el.css(".field__item")]
        county_matches = {t for t in tags if t in SC_COUNTIES}
        if len(county_matches) == 1:
            county = next(iter(county_matches))

    body_el = (tree.css_first(".node__content") or tree.css_first("article")
               or tree.css_first("main"))
    desc = None
    doc_urls: list[str] = []
    if body_el:
        text = body_el.text(separator="\n")
        for para in text.split("\n"):
            para = para.strip()
            if len(para) > 40:
                desc = para
                break
        doc_urls = harvest_document_links(body_el.html or "", base_url=base_url)
    return county, desc, doc_urls


class SCDESBrownfields(BaseScraper):
    slug = "counties_sc.sc_des_brownfields"
    name = "SC DES Brownfields & Voluntary Cleanup Sites"
    category = "environmental"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        sites: dict[str, str] = {}  # full_url -> site_name

        for url in (PAGE_URL, SITE_LIST_URL):
            try:
                html = await get_text(url, impersonate=True, timeout=40.0)
            except Exception as exc:
                log.warning("sc_des_brownfields.fetch_fail", url=url, error=str(exc)[:160])
                continue
            if not html:
                continue
            for full_url, site_name in _extract_site_links(html, url):
                sites.setdefault(full_url, site_name)

        if not sites:
            log.info("sc_des_brownfields.done", count=0)
            return []

        sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)
        now = datetime.utcnow()

        async def _one(full_url: str, site_name: str) -> Optional[Listing]:
            county, desc, doc_urls = None, None, []
            async with sem:
                try:
                    detail_html = await get_text(full_url, impersonate=True, timeout=30.0)
                except Exception as exc:
                    log.warning("sc_des_brownfields.detail_fail", url=full_url, error=str(exc)[:160])
                    detail_html = None
            if detail_html:
                county, desc, doc_urls = _parse_detail_page(detail_html, base_url=full_url)

            description = f"{site_name}: {desc}"[:400] if desc else site_name
            li = Listing(
                source="counties_sc.sc_des_brownfields",
                source_url=full_url,
                listing_type=ListingType.DISTRESSED,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county=county or "Statewide",
                description=description,
                first_seen=now,
                last_seen=now,
                raw={"sc_des_brownfield": {
                    "site_name": site_name,
                    "url": full_url,
                    "county_from_tags": county,
                    "description_full": desc,
                }},
            )
            stamp_documents(li, doc_urls)
            return li

        results = await asyncio.gather(*(_one(u, n) for u, n in sites.items()))
        out = [li for li in results if li is not None]
        log.info("sc_des_brownfields.done", count=len(out),
                 with_county=sum(1 for li in out if li.county != "Statewide"))
        return out
