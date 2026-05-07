"""NC eCourts (Tyler Odyssey) Lis Pendens / Foreclosure-relevant judgment scraper.

Source
------
NC AOC's public **Judgment Search** at https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/

This is an AngularJS SPA backed by an OData-like JSON service:
  POST https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search

Flow:
  1. Empty POST returns the initial `searchObject` template (with default sorts/facets).
  2. Modify the template: set `parameters.fromDate`/`toDate`, set `facets[Location]`
     buckets to our 14 target counties (each {District,Superior} Court).
  3. POST it back. Server returns `searchResult.hits[]` of judgments matching.
  4. Filter hits by `causeOfActionDesc` to foreclosure-relevant types
     (CV - Lis Pendens, CV - Claim of Lien, CV - Lien, CV - Possession, etc.).
  5. Page through `from`/`size` until exhausted.

Note on coverage
----------------
Tyler's full SmartSearch (which includes raw SP filings) is gated behind a Tyler
Identity Provider login — public Judgment Search is the only unauthenticated
view. SP cases aren't indexed here as judgments because SP foreclosures
typically resolve via trustee deed, not entered judgment. What IS indexed:

  * `CV - Lis Pendens` rows — actual lis pendens judgments (BK trustees, IRS, lenders)
  * `CV - Claim of Lien` rows — HOA + mechanic's liens (precursors to foreclosure)
  * `CV - Lien` / `CV - Possession` / `CV - Federal Tax Lien` — adjacent

This means we capture **judgment-entered** foreclosure-precursor signals across
the 14 target counties, not raw SP intakes. Works well as a downstream filter
for property addresses appearing in the County Tax / Newspaper / RoD scrapers.

If the public endpoint adds auth or breaks, we fall back to Scrapling
StealthyFetcher driving the SPA directly.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SERVICE_URL = "https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search"
APP_BASE = "https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/"

# Target counties for the eCourts judgment search. Must mirror
# config.NC_COUNTIES — Tyler indexes them as "<County> District Court" /
# "<County> Superior Court". Iteration history:
#   2026-05-07a — pruned 11 eastern-NC counties (Wake/Forsyth/etc).
#   2026-05-07b — pruned 3 more (Mecklenburg/Madison/Yancey) per user
#     scope rollback. Mecklenburg = Charlotte; user out of that market.
TARGET_COUNTIES = [
    # WNC mountains + foothills
    "Rutherford", "Cleveland", "Henderson", "Polk", "Gaston",
    "Buncombe", "Transylvania", "McDowell", "Lincoln",
    "Mitchell", "Burke",
    # User-key coastal NC counties
    "New Hanover", "Brunswick", "Onslow",
]


# NC Upset Bid window: NCGS §45-21.27 gives 10 days from filing of the
# report of sale (§45-21.26 requires the report to be filed within 5 days
# after the sale), so the practical window measured from sale_date is up
# to 15 calendar days; investors typically use 14 as the operational
# threshold. Note this scraper queries Tyler Odyssey's judgment search
# whose orderedDate is the JUDGMENT date, not the sale date — recent
# orderedDate doesn't reliably mean a recent sale, which is why
# enrichment_upset_bid.py is the authoritative tagger (it works off
# sale_date, not orderedDate). This constant is preserved here for any
# legacy callers but the actual upset-bid logic now lives in
# enrich_upset_bid.
UPSET_BID_WINDOW_DAYS = 14

# Causes of action we consider foreclosure-relevant. CV - Lis Pendens is a
# direct hit; the lien types are precursors / adjacent (HOA liens routinely
# escalate to foreclosure, federal tax liens encumber the property).
#
# Deliberately EXCLUDED:
#   * CV - Possession              -> landlord/tenant evictions (most are
#                                     summary ejectments with no plaintiff)
#   * CV - Possession of Personal Property -> vehicle / chattel repossessions
#   * CV - Summary Ejectment       -> rental evictions, not real-property fc
FORECLOSURE_CAUSES = {
    "CV - Lis Pendens",
    "CV - Claim of Lien",
    "CV - Lien",
    "CV - Federal Tax Lien",
    "CV - Tax Delinquency",
}

# AngularJS app expects a Tyler-style header set. Use Title-case keys to
# OVERRIDE http_client.DEFAULT_HEADERS — IIS rejects requests that contain
# both `Accept` and `accept` (which happens if you mix cases in the merge).
SERVICE_HEADERS = {
    "Origin": "https://portal-nc.tylertech.cloud",
    "Referer": APP_BASE,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
}


def _strip_court_suffix(loc: str) -> str:
    """'Henderson District Court' -> 'Henderson'."""
    if not loc:
        return ""
    return re.sub(r"\s+(District|Superior)\s+Court\b.*$", "", loc).strip()


def _build_search_object(
    template: dict,
    *,
    counties: list[str],
    from_date: datetime,
    to_date: datetime,
    page_from: int = 0,
    page_size: int = 200,
) -> dict:
    """Configure the searchObject template with our filters."""
    so = json.loads(json.dumps(template))  # deep copy
    so["queryString"] = ""
    so["from"] = page_from
    so["size"] = page_size
    so["parameters"] = {
        "fromDate": from_date.strftime("%Y-%m-%dT%H:%M:%S"),
        "toDate": to_date.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    # Location facet: select both District and Superior Court for each target county
    location_buckets = []
    for cnty in counties:
        for ct in ("District Court", "Superior Court"):
            location_buckets.append({
                "name": f"{cnty} {ct}",
                "count": 0,
                "selected": True,
                "rangeFrom": None,
                "rangeTo": None,
                "displayOrder": 0,
            })
    so["facets"] = [
        {"name": "Judgment Type", "type": "MultiSelect",
         "indexFieldName": "judgmentType.sort", "displayOrder": 1, "buckets": []},
        {"name": "Sentence Type", "type": "MultiSelect",
         "indexFieldName": "sentenceType.sort", "displayOrder": 2, "buckets": []},
        {"name": "Location", "type": "MultiSelect",
         "indexFieldName": "countyNodes.countyNode.sort",
         "displayOrder": 3, "buckets": location_buckets},
    ]
    return so


def _hit_to_listing(hit: dict, slug: str) -> Listing | None:
    """Convert a Tyler search hit to our Listing schema."""
    cause = hit.get("causeOfActionDesc") or ""
    if cause not in FORECLOSURE_CAUSES:
        return None

    case_number = (hit.get("caseNumber") or "").strip()
    location = hit.get("location") or ""
    county = _strip_court_suffix(location)
    if not county:
        return None

    # Parties: in this index, debtors are typically property owners (defendants)
    # and creditors are plaintiffs (lenders/HOAs/trustees). Some rows have empty
    # creditors — Tyler hides them on lien-only intakes.
    debtors = hit.get("debtors") or []
    creditors = hit.get("creditors") or []
    defendant = "; ".join(d.get("name", "") for d in debtors if d.get("name"))[:300] or None
    plaintiff = "; ".join(c.get("name", "") for c in creditors if c.get("name"))[:300] or None

    ordered_date = None
    od = hit.get("orderedDate")
    if od:
        try:
            ordered_date = datetime.fromisoformat(od.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ordered_date = None

    # Upset-bid window detection (NCGS §45-21.27 — 10 calendar days from
    # the date of sale). When ordered_date is recent we tag the listing
    # so the investor can prioritize cases still actionable.
    in_upset_bid_window = False
    if ordered_date is not None:
        # Normalize to naive UTC for comparison with utcnow()
        od_naive = ordered_date.replace(tzinfo=None) if ordered_date.tzinfo else ordered_date
        days_since = (datetime.utcnow() - od_naive).days
        if 0 <= days_since <= UPSET_BID_WINDOW_DAYS:
            in_upset_bid_window = True
            # Compute the upset-bid deadline date for the investor.
            # No need to handle weekends per statute — the window runs
            # in calendar days and only the deadline-day filing time
            # matters (handled by the clerk of court).

    # Pick listing type: explicit lis pendens vs lien
    if "Lis Pendens" in cause:
        listing_type = ListingType.LIS_PENDENS
    elif "Lien" in cause:
        listing_type = ListingType.TAX_LIEN if "Tax" in cause else ListingType.LIS_PENDENS
    else:
        listing_type = ListingType.LIS_PENDENS

    # Source URL: SPA detail view is state-driven, so link to the search app —
    # users can paste case# into the search box. Encoding the case# as fragment
    # is a best-effort breadcrumb.
    source_url = f"{APP_BASE}#/search?caseNumber={case_number}"

    raw_blob: dict = {}
    if in_upset_bid_window:
        # Compute deadline (orderedDate + 10 days). Floor to day for clarity.
        deadline = od_naive + timedelta(days=UPSET_BID_WINDOW_DAYS)

    # Critical: orderedDate is the JUDGMENT date (when the lis pendens or
    # lien was entered), NOT a future sale date. Setting it as sale_date
    # caused every NC eCourts listing to fail _active_only's 120-day-
    # forward horizon — Run #16 produced 571 listings here, all silently
    # dropped before reaching docs/listings.json. The fix: leave sale_date
    # None (DATELESS_OK_SOURCES already handles this for nc_ecourts) and
    # store the judgment date in raw.nc_ecourts.orderedDate where the
    # dashboard / enrichment can find it without it gating the active
    # filter. For upset-bid-window listings the actual sale happened ON
    # orderedDate (we keep upset_bid_deadline + raw.upset_bid for that).
    return Listing(
        source=slug,
        source_url=source_url,
        listing_type=listing_type,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        case_number=case_number,
        plaintiff=plaintiff,
        defendant=defendant,
        sale_date=None,
        upset_bid_deadline=(deadline if in_upset_bid_window else None),
        description=f"{cause} judgment in {location}: {case_number}",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "nc_ecourts": {
                "cause": cause,
                "judgmentType": hit.get("judgmentType"),
                "civilJudgmentStatus": hit.get("civilJudgmentStatus"),
                "caseCategoryKey": hit.get("caseCategoryKey"),
                "caseID": hit.get("caseID"),
                "judgmentId": hit.get("judgmentId"),
                "orderedDate": od,
                "ordered_date_iso": ordered_date.isoformat() if ordered_date else None,
                "location": location,
            },
            **({"upset_bid": {
                "in_window": True,
                "window_days": UPSET_BID_WINDOW_DAYS,
                "deadline_iso": deadline.isoformat(),
                "days_remaining": max(0, UPSET_BID_WINDOW_DAYS - (
                    datetime.utcnow() - od_naive).days),
                "statute": "NCGS §45-21.27",
                "sale_occurred_on_iso": ordered_date.isoformat() if ordered_date else None,
            }} if in_upset_bid_window else {}),
        },
    )


class NCECourtsLisPendens(BaseScraper):
    slug = "counties_nc.nc_ecourts_lis_pendens"
    name = "NC eCourts Lis Pendens (Tyler Odyssey Judgment Search)"
    category = "county_court"
    expected_min_count = 3
    timeout_s = 600.0
    requires_apify = False
    optional = True

    # Days back to search (matches user spec: last 60 days)
    # 90-day window — NC trustee sales typically have a 30-day notice
    # period plus a 10-day upset bid window; 60 days missed sales that
    # were filed 60-90 days ago and are still in their upset bid period.
    LOOKBACK_DAYS = 90
    # Page size on each request
    PAGE_SIZE = 200
    # Cap total pages we'll pull across a run (safety against runaway pagination)
    MAX_PAGES = 25

    async def fetch(self) -> Iterable[Listing]:
        end = datetime.now()
        start = end - timedelta(days=self.LOOKBACK_DAYS)

        async with client(timeout=45.0, headers=SERVICE_HEADERS) as c:
            # Step 1: empty POST -> initial searchObject template
            try:
                r = await c.post(SERVICE_URL, content=b"")
            except Exception as exc:  # noqa: BLE001
                log.warning("nc_ecourts.template_fetch_failed", error=str(exc))
                return []
            if r.status_code not in (200, 201):
                log.warning("nc_ecourts.template_status", status=r.status_code,
                            body=r.text[:300])
                return []
            try:
                template = r.json()
            except (ValueError, json.JSONDecodeError) as exc:
                log.warning("nc_ecourts.template_json_failed", error=str(exc))
                return []

            # Step 2: paginate through all hits across the 14 target counties
            all_hits: list[dict] = []
            page_from = 0
            for _ in range(self.MAX_PAGES):
                so = _build_search_object(
                    template,
                    counties=TARGET_COUNTIES,
                    from_date=start,
                    to_date=end,
                    page_from=page_from,
                    page_size=self.PAGE_SIZE,
                )
                try:
                    r2 = await c.post(SERVICE_URL, json=so)
                except Exception as exc:  # noqa: BLE001
                    log.warning("nc_ecourts.search_request_failed", error=str(exc),
                                page_from=page_from)
                    break
                if r2.status_code not in (200, 201):
                    log.warning("nc_ecourts.search_status", status=r2.status_code,
                                page_from=page_from, body=r2.text[:300])
                    break
                try:
                    data = r2.json()
                except (ValueError, json.JSONDecodeError):
                    log.warning("nc_ecourts.search_json_failed", page_from=page_from)
                    break
                hits = (data.get("searchResult") or {}).get("hits") or []
                if not hits:
                    break
                all_hits.extend(hits)
                total = (data.get("searchResult") or {}).get("totalHits") or 0
                if len(all_hits) >= total:
                    break
                page_from += len(hits)

            log.info("nc_ecourts.fetched", total_hits=len(all_hits))

        # Diagnostic: count cause-of-action types BEFORE filtering. Helps
        # identify when NCAOC adds new foreclosure-relevant cause codes
        # that we're silently dropping. Surfaces in logs each weekly run.
        from collections import Counter
        cause_counts = Counter(
            (h.get("causeOfActionDesc") or "(blank)") for h in all_hits
        )
        log.info(
            "nc_ecourts.cause_distribution",
            unique_causes=len(cause_counts),
            top=dict(cause_counts.most_common(15)),
            covered=sorted(c for c in cause_counts if c in FORECLOSURE_CAUSES),
            uncovered_top=[c for c, _ in cause_counts.most_common(20)
                           if c not in FORECLOSURE_CAUSES][:10],
        )

        # Step 3: convert hits to listings, filtering to foreclosure-relevant causes
        listings: list[Listing] = []
        seen_keys: set[str] = set()
        for h in all_hits:
            listing = _hit_to_listing(h, self.slug)
            if listing is None:
                continue
            # Dedupe on (case_number, county, cause)
            key = (
                listing.case_number or "",
                listing.county or "",
                (listing.raw.get("nc_ecourts") or {}).get("cause", ""),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            listings.append(listing)

        log.info("nc_ecourts.parsed", listings=len(listings),
                 raw_hits=len(all_hits), lookback_days=self.LOOKBACK_DAYS)
        return listings


# Allow running this module directly for quick iteration:
#   uv run python -m foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens
if __name__ == "__main__":
    async def _main() -> None:
        scraper = NCECourtsLisPendens()
        results = await scraper.safe_run()
        print(f"parsed: {len(results)}")
        # By county
        by_county: dict[str, int] = {}
        for x in results:
            by_county[x.county or "?"] = by_county.get(x.county or "?", 0) + 1
        for c, n in sorted(by_county.items(), key=lambda kv: -kv[1]):
            print(f"  {c}: {n}")
        for x in results[:8]:
            print(f"  {x.county}: case={x.case_number} {x.plaintiff} vs {x.defendant}")

    asyncio.run(_main())
