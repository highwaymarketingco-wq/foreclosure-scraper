"""NC Register of Deeds — Substitute Trustee Deed + Trustee's Deed
Upon Sale indexer scraper, Buncombe-only after the 2026-05-07 scope
rollback.

Two distinct value sources from the same portal:

  PRE-SALE  Substitute Trustee Deed + Notice of Sale recordings —
             precede the SP foreclosure docket by 2-6 weeks. Earliest
             publicly-available indicator that a foreclosure is
             imminent (lead source).

  POST-SALE Trustee's Deed Upon Sale recordings — these are the
             documents that transfer the property to the winning
             bidder. They include the deed-tax stamp which encodes the
             sold price (NC charges $1 per $500 of consideration, so
             stamp_amount × 500 = sold_price). Feeds the
             foreclosure_sold_comps pool.

The Buncombe portal (https://buncombe-recordings.permitium.com/) is a
Permitium hosted recording-search SaaS. Behind a JS app shell + likely
Cloudflare bot mitigation — needs Scrapling stealth to render.

This scraper currently runs in DIAGNOSTIC mode: it tries the stealth
flow, logs what it sees (page title, form selectors found, table row
counts), and falls back to skeleton if the structure doesn't match
the documented Permitium pattern. Production parsing will be added
once we have CI logs from the live portal showing the actual element
structure.

Set NC_ROD_DEBUG=1 to log raw HTML excerpt for inspection.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


# Per-county configuration. Document-type values are the actual filter
# strings each portal accepts — verified from the indexer dropdown
# options as of May 2026. 2026-05-07 scope rollback: dropped Mecklenburg
# / Wake / Durham portals; only Buncombe (in user's WNC core scope)
# remains. Portal configs for the dropped counties are preserved here
# in code comments below for future re-activation if scope changes.
#
# DEACTIVATED PORTALS (kept as comments for fast re-activation):
#   Mecklenburg: https://meckrod.manatron.com/RealEstate/SearchEntry.aspx (manatron)
#     doc_types: SUBSTITUTE TRUSTEE DEED, NOTICE OF SALE, CLAIM OF LIEN, TRUSTEES DEED
#   Wake: https://services.wakegov.com/booksweb/PublicFreeMonitorSearch.aspx (aumentum)
#     doc_types: SUBSTITUTE TRUSTEE DEED, NOTICE OF SALE, CLAIM OF LIEN
#   Durham: https://rod-public.dconc.gov/Search.aspx (aumentum)
#     doc_types: SUBSTITUTE TRUSTEE DEED, NOTICE OF SALE, CLAIM OF LIEN
COUNTY_PORTALS: dict[str, dict] = {
    "Buncombe": {
        "url": "https://buncombe-recordings.permitium.com/",
        "search_path": "/searches/new",
        "doc_types": [
            "SUBSTITUTE TRUSTEE DEED",
            "NOTICE OF SALE",
        ],
        "vendor": "permitium",
    },
}


# ---- Permitium parsing patterns (best-effort, refined as CI logs land) ----

# NC deed-tax stamp: $1 per $500 of consideration. So a "EXCISE TAX:
# $50.00" stamp implies a $25,000 sale price.
EXCISE_TAX_RE = re.compile(
    r"(?:excise\s+tax|stamp(?:ed)?\s+tax|consideration\s+stamp)\s*[:=]?\s*"
    r"\$\s*([\d,]+(?:\.\d{2})?)",
    re.I,
)
# Direct consideration line ("CONSIDERATION: $123,456.00")
CONSIDERATION_RE = re.compile(
    r"consideration\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I,
)
# Recording date / instrument date
DATE_RE = re.compile(
    r"\b(?:recorded|instrument|filed)\s*(?:on|date)?\s*[:=]?\s*"
    r"((?:\d{1,2}/\d{1,2}/\d{2,4})|(?:\w+\s+\d{1,2},?\s+\d{4}))",
    re.I,
)


def _sold_price_from_stamp(text: str) -> Optional[float]:
    """NC deed tax: $1 per $500 of consideration. Stamp_amount × 500 =
    sold price. Prefer explicit CONSIDERATION line if present."""
    m = CONSIDERATION_RE.search(text)
    if m:
        try:
            v = float(m.group(1).replace(",", ""))
            if 100 <= v <= 10_000_000:
                return v
        except ValueError:
            pass
    m = EXCISE_TAX_RE.search(text)
    if m:
        try:
            stamp = float(m.group(1).replace(",", ""))
            v = stamp * 500
            if 100 <= v <= 10_000_000:
                return v
        except ValueError:
            pass
    return None


async def _scrapling_search_permitium(
    portal_url: str, doc_type: str, days_back: int = 60,
) -> tuple[str, list[Listing]]:
    """Drive a Permitium recording-search portal and return (raw_html,
    listings). Returns ("", []) when Scrapling not available or portal
    unreachable. Logs diagnostic info on every path so the first CI run
    surfaces the actual page structure."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("nc_rod.scrapling_missing", portal=portal_url)
        return "", []
    try:
        # Attempt 1: load search-form page with network-idle wait.
        result = await StealthyFetcher.async_fetch(
            portal_url,
            headless=True,
            network_idle=True,
            timeout=60000,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("nc_rod.permitium_fetch_failed",
                    portal=portal_url, error=str(exc)[:200])
        return "", []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    log.info(
        "nc_rod.permitium_landing",
        portal=portal_url, html_bytes=len(html),
        has_search_form=("<form" in html.lower() and "search" in html.lower()),
        has_results_table=("<table" in html.lower() and "<tr" in html.lower()),
        has_doc_type_filter="document_type" in html.lower() or "doc_type" in html.lower(),
    )
    if os.environ.get("NC_ROD_DEBUG"):
        log.debug("nc_rod.html_excerpt", excerpt=html[:2000])

    # Future: drive the search form with page_action — set doc_type
    # filter, set date range to past `days_back`, click Search, wait
    # for results table, parse rows. Implementation pending the first
    # CI run's diagnostic logs that reveal the actual selectors.
    return html, []


class NCRodSubstituteTrustee(BaseScraper):
    """NC Register of Deeds — substitute-trustee + notice-of-sale +
    trustee's-deed-upon-sale recordings (Buncombe only after scope
    rollback)."""

    slug = "counties_nc.nc_rod_substitute_trustee"
    name = "NC ROD Substitute Trustee + Trustee's Deed (Buncombe)"
    category = "register_of_deeds"
    expected_min_count = 0
    requires_apify = False
    # Permitium portal is JS app shell + likely Cloudflare; needs Scrapling.
    requires_render = True
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for county, cfg in COUNTY_PORTALS.items():
            portal_url = cfg["url"]
            for doc_type in cfg["doc_types"]:
                try:
                    html, listings = await _scrapling_search_permitium(
                        portal_url=portal_url,
                        doc_type=doc_type,
                        days_back=60,
                    )
                    out.extend(listings)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "nc_rod.search_failed",
                        county=county, doc_type=doc_type,
                        error=str(exc)[:200],
                    )

        if not out:
            # Diagnostic emit so the run report is honest about why no
            # data: the stealth flow ran but didn't yet know how to
            # parse the live portal structure. Next iteration uses the
            # nc_rod.permitium_landing log to refine selectors.
            log.info(
                "nc_rod.no_listings_yet",
                counties=list(COUNTY_PORTALS),
                note=("Permitium search-form selectors not yet wired. "
                      "Check nc_rod.permitium_landing log entries from "
                      "this run for actual page structure to refine."),
            )
        return out
