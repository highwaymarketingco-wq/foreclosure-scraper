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
from ...validation import NC_COUNTIES as _ALL_NC_COUNTIES

log = structlog.get_logger()

SERVICE_URL = "https://portal-nc.tylertech.cloud/app/NCJudgmentSearchService/search"
APP_BASE = "https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/"

# Target counties for the eCourts judgment search. Tyler indexes them as
# "<County> District Court" / "<County> Superior Court" — one batched query
# with a facet bucket pair per county, not a per-county round trip.
#
# Iteration history (pre-2026-09-23, narrow WNC/coastal footprint):
#   2026-05-07a — pruned 11 eastern-NC counties (Wake/Forsyth/etc).
#   2026-05-07b — pruned 3 more (Mecklenburg/Madison/Yancey) per user
#     scope rollback. Mecklenburg = Charlotte; user out of that market.
#   2026-06-16 — dropped New Hanover/Brunswick/Onslow: they were pruned
#     2026-05-15 ("anything east of Charlotte") and are in
#     SCOPE_DENY_COUNTIES, so querying them just scraped rows that the
#     scope filter then discarded.
#   2026-06-25 through 2026-08-19 — 11 coastal counties added piecemeal
#     (Brunswick/Pender/Onslow/Carteret/Dare/Currituck/Hyde/New Hanover/
#     Beaufort/Craven/Pamlico), re-admitted via the OCEANFRONT_COASTAL_
#     COUNTIES gate in main._in_scope rather than the (then-only) narrow
#     footprint allow-list.
#
# 2026-09-23 — WIDENED FROM 22 TO ALL 100 NC COUNTIES. This was a historical
# footprint artifact, not a technical ceiling: the 22-county cap mirrored
# config.NC_COUNTIES (the narrow 11-county WNC "flip" footprint) plus the
# 11 coastal add-ons, but this scraper's listing types (LIS_PENDENS,
# TAX_LIEN, and now DIVORCE_NOTICE below) are NOT in main._FLIP_LISTING_TYPES
# — they route through config.in_scope_distressed(), which admits ANY real
# NC county with no deny list (confirmed by reading main._county_in_scope
# and config.in_scope_distressed's docstring: "if its a distressed property
# its anywhere in nc and sc"). SCOPE_DENY_COUNTIES (Mecklenburg/Wake/Forsyth/
# etc.) only gates FLIP-type leads, so it never applied to this source.
#
# Live-verified 2026-09-23 before widening (see
# tests/test_nc_ecourts_statewide_widen.py for the MEASURED assertions):
#   - Queried all 10 of Wake/Mecklenburg/Forsyth/Guilford/Durham/Cumberland/
#     New Hanover/Alamance/Chatham/Person individually: every one returned
#     real, non-zero totalHits (230-11,949) under BOTH "<County> District
#     Court" and "<County> Superior Court" facet names.
#   - Queried 20 small/rural counties flagged as at-risk for the "shares a
#     Clerk of Court office with a neighbor" caveat (Tyrrell, Camden, Gates,
#     Hyde, Jones, Bertie, Warren, Hertford, Alleghany, Avery, Graham, Clay,
#     Pamlico, Washington, Perquimans, Chowan, Swain, Yancey, Madison,
#     Mecklenburg): every one returned real, non-zero totalHits (46-11,949)
#     under its own county name — no shared/consolidated-clerk naming
#     collisions found.
#   - Queried all 100 NC counties in ONE batched request (as production
#     runs it): totalHits=78,663 in a 90-day window. The response's
#     "facets" display list truncates to a subset of buckets (an artifact
#     of Tyler's facet-aggregation size cap, not a real limit — confirmed by
#     re-querying with ONLY the "missing" 26 counties, which returned
#     totalHits=2,814, and by paging the actual hits[] of the full-100
#     query and finding real rows from 22 of those 26 counties in the
#     first 3,000 hits sampled). The scraper below reads hits[]/location
#     per-row, never the facets display list, so this display artifact
#     does not affect what gets scraped.
# Sourced from validation.NC_COUNTIES (the canonical 100-county set already
# used by the scope gate) rather than a fourth hand-maintained county list.
TARGET_COUNTIES = sorted(_ALL_NC_COUNTIES)


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
    # 2026-07-03 Task #52: expanded per per-county case-type-code map.
    # These causes attach a lien to real property or signal a forced sale.
    "CV - Transcript of Judgment",          # judgment lien on real property (NCGS 1-234)
    "CV - NC Certificate of Tax Liability",  # NC DOR state tax lien (NCGS 105-242)
    "CV - Condemnation",                      # government taking; forced seller
}

# 2026-09-23 — divorce judgments, spiked per docs/gap_ledger.md (line ~119)
# and docs/coverage_gap_build_plan_2026-09-23.md item 2. Live-verified this
# same day (tests/test_nc_ecourts_statewide_widen.py): querying Buncombe/
# Henderson/Rutherford/Wake/Mecklenburg over a 90-day window returned 281
# "FAM - Divorce" / caseCategoryKey=="FAM" hits (5th most common cause of
# the 3,000 sampled) with both spouses structured as debtors[]/creditors[]
# the same way lien debtors/creditors are — the gap ledger's finding holds
# up live, unchanged. This is a GRANTED divorce judgment (further down the
# NCGS 50-20 equitable-distribution timeline than a raw CVD filing — the
# raw filings live only in the WAF-walled Smart Search nc_ecourts_divorce.py
# already drives), not a duplicate of that source.
DIVORCE_CAUSES = {
    "FAM - Divorce",
}

# Hard safety exclusion mirroring enrichment_nc_divorce.py's _DV50B_RE: a 50B
# domestic-violence protective order is a safety matter, never a lead, and
# must never surface even if it somehow carried a divorce-adjacent cause or
# party-name text. causeOfActionDesc alone already can't produce this (a 50B
# case has its own distinct cause label, not "FAM - Divorce" — confirmed
# live: a 100-county, 90-day, 4,000-row sample of this exact endpoint turned
# up FAM - Arrears/Child Support/Divorce/Equitable Distribution/Other Filing/
# Qualified Domestic Relations Order/Registration of a Foreign Order, and
# zero DV/50B/protective-order-named causes), but this regex is a defense-
# in-depth second layer against the free-text fields (case description /
# party names) in case a future taxonomy change ever blurs that line. Kept
# as a local copy rather than an import: enrichment_nc_divorce.py pulls in
# the Playwright/stealth-render stack (`.render.fetch_rendered`) for its own
# WAF-bypass path, which this pure-JSON scraper has no other reason to load.
_DV50B_RE = re.compile(r"\b50\s?-?\s?B\b|domestic\s+violence|\bDVPO\b|protective\s+order", re.I)

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
    is_divorce = cause in DIVORCE_CAUSES
    if cause not in FORECLOSURE_CAUSES and not is_divorce:
        return None

    # Skip terminal/dead dispositions — a Canceled/Satisfied/Dismissed/Vacated lien
    # or judgment is no longer an actionable lead (e.g. an HOA Claim of Lien marked
    # 'Canceled' once paid). civilJudgmentStatus carries the disposition; without
    # this we pull dead liens (e.g. 24M001384-100 Avery Park v. Perone, Canceled).
    status = (hit.get("civilJudgmentStatus") or "").strip().lower()
    if any(t in status for t in ("cancel", "satisf", "dismiss", "vacat",
                                 "withdraw", "expired", "released")):
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

    # Defense-in-depth safety exclusion (see _DV50B_RE docstring above): drop
    # anything DV/50B-adjacent regardless of which allowlisted cause it
    # otherwise matched. causeOfActionDesc alone already can't produce a 50B
    # hit here (live-verified — see DIVORCE_CAUSES comment), but this also
    # scans judgmentType and both parties' names as a second layer.
    _dv_check_blob = " ".join(filter(None, [
        cause, hit.get("judgmentType") or "", defendant or "", plaintiff or "",
    ]))
    if _DV50B_RE.search(_dv_check_blob):
        return None

    ordered_date = None
    od = hit.get("orderedDate")
    if od:
        try:
            ordered_date = datetime.fromisoformat(od.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            ordered_date = None

    # Upset-bid window detection (NCGS §45-21.27 — 10 calendar days from
    # the date of sale). When ordered_date is recent we tag the listing
    # so the investor can prioritize cases still actionable. Meaningless for
    # a divorce judgment (no foreclosure sale involved), so skipped there.
    in_upset_bid_window = False
    if ordered_date is not None and not is_divorce:
        # Normalize to naive UTC for comparison with utcnow()
        od_naive = ordered_date.replace(tzinfo=None) if ordered_date.tzinfo else ordered_date
        days_since = (datetime.utcnow() - od_naive).days
        if 0 <= days_since <= UPSET_BID_WINDOW_DAYS:
            in_upset_bid_window = True
            # Compute the upset-bid deadline date for the investor.
            # No need to handle weekends per statute — the window runs
            # in calendar days and only the deadline-day filing time
            # matters (handled by the clerk of court).

    # Pick listing type based on the cause.
    if is_divorce:
        listing_type = ListingType.DIVORCE_NOTICE
    elif "Lis Pendens" in cause:
        listing_type = ListingType.LIS_PENDENS
    elif "Tax" in cause or "Tax Liability" in cause:
        listing_type = ListingType.TAX_LIEN
    elif "Lien" in cause:
        listing_type = ListingType.TAX_LIEN if "Tax" in cause else ListingType.LIS_PENDENS
    elif "Condemnation" in cause:
        listing_type = ListingType.LIS_PENDENS
    elif "Transcript of Judgment" in cause:
        listing_type = ListingType.LIS_PENDENS
    else:
        listing_type = ListingType.LIS_PENDENS

    # For a divorce judgment, the plaintiff/petitioner is the filing spouse —
    # set owner_name from them so downstream GIS/name-to-property resolution
    # can find the marital home, same convention as nc_ecourts_divorce.py
    # ("owner_name=plaintiff # filing spouse -> GIS resolves marital home").
    # Not set for other cause types: FORECLOSURE_CAUSES rows already resolve
    # by defendant/property, not by a filing-party name.
    owner_name = plaintiff if is_divorce else None

    description = (
        f"NC divorce judgment ({location}): {case_number} — "
        f"{plaintiff or '?'} v. {defendant or '?'}"
        if is_divorce else
        f"{cause} judgment in {location}: {case_number}"
    )

    # Source URL: SPA detail view is state-driven, so link to the search app —
    # users can paste case# into the search box. Encoding the case# as fragment
    # is a best-effort breadcrumb.
    source_url = f"{APP_BASE}#/search?caseNumber={case_number}"

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
        owner_name=owner_name,
        plaintiff=plaintiff,
        defendant=defendant,
        sale_date=None,
        upset_bid_deadline=(deadline if in_upset_bid_window else None),
        description=description,
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
    # 2026-09-23: bumped 600 -> 900 alongside the MAX_PAGES increase below.
    # Widening TARGET_COUNTIES to all 100 NC counties raised the 90-day
    # corpus from a 22-county subset to totalHits=78,663 (live-measured
    # 2026-09-23). MEASURED: 5 sequential live page fetches against the
    # full-100-county query averaged 1.15s/page; 900s leaves headroom over
    # the ~453s a full 394-page pull takes at that rate, plus the template
    # fetch + per-hit processing. See tests/test_nc_ecourts_statewide_widen.py.
    timeout_s = 900.0
    requires_apify = False
    optional = True

    # Days back to search (matches user spec: last 60 days)
    # 90-day window — NC trustee sales typically have a 30-day notice
    # period plus a 10-day upset bid window; 60 days missed sales that
    # were filed 60-90 days ago and are still in their upset bid period.
    LOOKBACK_DAYS = 90
    # Page size on each request
    PAGE_SIZE = 200
    # Cap total pages we'll pull across a run (safety against runaway pagination).
    # 2026-09-23: bumped 25 -> 450. At 25 pages (5,000 hits) the old cap covered
    # only ~6% of the live-measured 78,663-hit, 100-county, 90-day corpus —
    # widening TARGET_COUNTIES without also raising this would have silently
    # capped the county-breadth win this change exists to deliver. 450 pages
    # (90,000 hits) covers today's corpus with room for growth; at the
    # measured ~1.15s/page it's a ~450-517s pull, inside the 900s timeout_s
    # above with margin for the template fetch and per-hit processing.
    MAX_PAGES = 450

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
