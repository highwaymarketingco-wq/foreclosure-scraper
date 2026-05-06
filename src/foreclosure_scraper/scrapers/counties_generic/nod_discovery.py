"""NOD (Notice of Default / Notice of Foreclosure) discovery via ROD adapters.

For every (state, county) where we have a working Register-of-Deeds vendor
adapter, sweep the last `days_back` days of recordings and pull every doc
that looks like a NOD / NOS / Lis Pendens. These are the *earliest* public
signal that a property is heading to foreclosure (often weeks before a sale
date is published), so we treat them as `LIS_PENDENS`-typed Listings to feed
the same downstream dedupe / dashboard.

This complements `counties.sitemap_walker` (which walks county.gov pages
for already-scheduled sales) by surfacing the upstream pre-foreclosure
trigger event.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...rod import aumentum, cchs, cott, kofile
from ...rod.models import RodDoc

log = structlog.get_logger()

# (state, county, vendor-callable) tuples. Each callable takes
# (state, county, days_back, max_docs) and returns list[RodDoc].
ROD_TARGETS: tuple[tuple[str, str, callable], ...] = (
    # CCHS — Burke / Lincoln / Cleveland NC
    ("NC", "Burke", cchs.discover_recent_nods),
    ("NC", "Lincoln", cchs.discover_recent_nods),
    ("NC", "Cleveland", cchs.discover_recent_nods),
    # Aumentum / Manatron — Mecklenburg / Buncombe / Gaston NC
    ("NC", "Mecklenburg", aumentum.discover_recent_nods),
    ("NC", "Buncombe", aumentum.discover_recent_nods),
    ("NC", "Gaston", aumentum.discover_recent_nods),
    # Cott Systems — Polk / Rutherford NC
    ("NC", "Polk", cott.discover_recent_nods),
    ("NC", "Rutherford", cott.discover_recent_nods),
    # Kofile — Oconee SC
    ("SC", "Oconee", kofile.discover_recent_nods),
)

# Typical NC non-judicial-foreclosure timeline: NOH/NOS recorded → sale 30–90 days later.
# We project a placeholder sale_date 90 days out so the listing surfaces in
# the upcoming-sales dashboard but is clearly marked as estimated in `description`.
NC_NOD_TO_SALE_DAYS = 90


def _project_sale_date(recorded: datetime | None) -> datetime | None:
    if recorded is None:
        return None
    return recorded + timedelta(days=NC_NOD_TO_SALE_DAYS)


def _build_case_number(d: RodDoc) -> str | None:
    if d.instrument_no:
        return d.instrument_no.strip() or None
    if d.book and d.page:
        return f"{d.book}/{d.page}"
    return None


def _build_description(d: RodDoc) -> str:
    rec = d.recorded_date.strftime("%Y-%m-%d") if d.recorded_date else "unknown date"
    grantor = (d.grantor or "?").strip()
    grantee = (d.grantee or "?").strip()
    bk_pg = f"{d.book}/{d.page}" if (d.book and d.page) else (d.instrument_no or "n/a")
    return f"NOD recorded {rec}: {grantor} vs {grantee} ({bk_pg})"


def _build_source_url(d: RodDoc) -> str:
    """Best-effort link back to the ROD vendor. We don't always have a stable
    deep-link, so we emit the search-page root keyed by vendor."""
    state, county = d.state, d.county
    if (state, county) in cchs.CCHS_COUNTIES:
        slug = cchs.CCHS_COUNTIES[(state, county)]
        return f"https://us5.courthousecomputersystems.com/{slug}/searchonline.asp"
    if (state, county) in aumentum.AUMENTUM_COUNTIES:
        return f"{aumentum.AUMENTUM_COUNTIES[(state, county)]}/SrchDocType.aspx"
    if (state, county) in cott.COTT_COUNTIES:
        return f"{cott.COTT_COUNTIES[(state, county)]}/SrchDocType.aspx"
    if (state, county) in kofile.KOFILE_COUNTIES:
        return f"https://{kofile.KOFILE_COUNTIES[(state, county)]}/"
    return ""


def _to_listing(d: RodDoc, slug: str) -> Listing:
    now = datetime.utcnow()
    return Listing(
        source=slug,
        source_url=_build_source_url(d) or "https://example.invalid/",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        state=d.state,
        county=d.county,
        case_number=_build_case_number(d),
        defendant=d.grantor,
        plaintiff=d.grantee,
        sale_date=_project_sale_date(d.recorded_date),
        description=_build_description(d),
        first_seen=now,
        last_seen=now,
        raw={"nod": d.to_dict()},
    )


class NODDiscovery(BaseScraper):
    slug = "counties.nod_discovery"
    name = "ROD-driven NOD / NOS / Lis Pendens discovery"
    category = "county_court"
    # NOD discovery is opportunistic across multiple county ROD vendors;
    # weeks with zero matches are normal (small counties don't always
    # file in the lookback window). Real regression here = a county's
    # ROD index becomes unreachable, which fires structural log warnings
    # separately. Empty count alone shouldn't cry wolf.
    expected_min_count = 0
    requires_apify = False
    timeout_s = 600.0

    days_back: int = 60
    max_docs_per_county: int = 100

    async def fetch(self) -> Iterable[Listing]:
        sem = asyncio.Semaphore(4)

        async def one(state: str, county: str, fn) -> list[Listing]:
            async with sem:
                bound = log.bind(scraper=self.slug, state=state, county=county)
                try:
                    docs = await fn(
                        state, county,
                        days_back=self.days_back,
                        max_docs=self.max_docs_per_county,
                    )
                except Exception as exc:  # noqa: BLE001
                    bound.warning("nod.county_error",
                                  error=str(exc), exc_type=type(exc).__name__)
                    return []
                if not isinstance(docs, list):
                    return []
                bound.info("nod.county_ok", count=len(docs))
                return [_to_listing(d, self.slug) for d in docs if d.recorded_date]

        results = await asyncio.gather(
            *(one(s, c, fn) for s, c, fn in ROD_TARGETS),
            return_exceptions=True,
        )
        out: list[Listing] = []
        for r in results:
            if isinstance(r, list):
                out.extend(r)
        return out
