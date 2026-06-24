"""Orchestrator: run all scrapers, dedupe, validate, enrich, write Sheet, email."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import structlog

from .config import (
    RuntimeConfig,
    SCOPE_DENY_COUNTIES_NORMALIZED,
    SCOPE_ZIP_PREFIXES,
    in_scope,
)
from .oceanfront import is_oceanfront
from .dedupe import dedupe
from .email_sender import send_digest
from .enrichment import enrich
from .enrichment_arcgis import enrich as enrich_gis
from .enrichment_owner_mailing import enrich_owner_mailing
from .enrichment_courts import discover_lis_pendens, enrich_with_court_records
from .enrichment_geocode import enrich as enrich_geocode
from .flags import compute_flags
from .link_validator import validate
from .models import Listing, PropertyKind
from .scrapers._registry import all_scrapers
from .sheets import write_listings
from .valuation import calc as valuation_calc
from .valuation import grading as valuation_grading
from .valuation import location as valuation_location
from .valuation import rentcast as valuation_rentcast
from .web_artifact import write_artifact


def _setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level, logging.INFO)),
    )


log = structlog.get_logger()


# NC + SC ocean-facing counties. Listings in these counties are denied by
# default (they're east of Charlotte / outside the upstate footprint), but
# get re-admitted through the OCEANFRONT_OVERRIDE in _in_scope when the
# listing's data passes the 2-of-3 oceanfront signal check.
OCEANFRONT_COASTAL_COUNTIES: frozenset[tuple[str, str]] = frozenset({
    ("Currituck", "NC"), ("Dare", "NC"), ("Hyde", "NC"), ("Carteret", "NC"),
    ("Onslow", "NC"), ("Pender", "NC"), ("New Hanover", "NC"), ("Brunswick", "NC"),
    ("Horry", "SC"), ("Georgetown", "SC"), ("Charleston", "SC"),
    ("Beaufort", "SC"), ("Colleton", "SC"),
})

# TRUE downtown Charleston peninsula (owner direction 2026-06-22 — keep these
# even though they're harbor-side, not oceanfront; rare but valuable). The
# historic peninsula south of the Crosstown/Hampton Park, between the Ashley
# (W) and Cooper (E) rivers. This bbox EXCLUDES North Charleston (lat >32.81),
# Summerville (~33.0/-80.18), West Ashley (lon <-79.975) and James Island
# (lat <32.76) — exactly the "not Summerville, not North Charleston" ask.
DOWNTOWN_CHARLESTON_BBOX = (32.760, 32.808, -79.975, -79.915)  # lat_min,lat_max,lon_min,lon_max
_DOWNTOWN_CHS_DENY_CITY = {"north charleston", "summerville", "hanahan",
                           "goose creek", "west ashley", "james island", "ladson"}


def _is_downtown_charleston(li: Listing) -> bool:
    """True for a Charleston-peninsula (true downtown) listing — admitted
    alongside the oceanfront path, but never North Charleston / Summerville."""
    if (li.state or "").upper() != "SC":
        return False
    if li.county and li.county.replace(" County", "").strip().title() != "Charleston":
        return False
    if (li.city or "").strip().lower() in _DOWNTOWN_CHS_DENY_CITY:
        return False
    if li.latitude is None or li.longitude is None:
        return False
    try:
        lat, lon = float(li.latitude), float(li.longitude)
    except (TypeError, ValueError):
        return False
    a0, a1, o0, o1 = DOWNTOWN_CHARLESTON_BBOX
    if a0 <= lat <= a1 and o0 <= lon <= o1:
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["downtown_charleston"] = True
        return True
    return False


def _check_oceanfront(li: Listing) -> bool:
    """Run is_oceanfront against the listing's data and, on a pass, tag
    raw.oceanfront=True with the contributing signals for transparency."""
    ok, signals = is_oceanfront(
        description=li.description,
        street_address=li.street_address,
        city=li.city,
        latitude=li.latitude,
        longitude=li.longitude,
    )
    if ok:
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["oceanfront"] = True
        li.raw["oceanfront_signals"] = signals
    return ok


def _in_scope(li: Listing) -> bool:
    # Oceanfront override — runs BEFORE the deny check so the otherwise-
    # denied coastal counties (New Hanover/Brunswick/Onslow + the SC
    # coast) can re-enter when a listing passes the strict 2-of-3
    # oceanfront filter. Listings keep tag raw.oceanfront=True so the
    # dashboard can sort/filter them.
    if li.county and li.state:
        cs = (li.county.replace(" County", "").strip().title(),
              li.state.upper())
        if cs in OCEANFRONT_COASTAL_COUNTIES and _check_oceanfront(li):
            return True
    # True downtown Charleston peninsula — harbor-side, so it won't pass the
    # oceanfront distance gate, but the owner wants it kept (not N. Charleston /
    # Summerville). Also runs before the deny check.
    if _is_downtown_charleston(li):
        return True
    # Deny set takes precedence over EVERY other scope path. Without this,
    # a listing tagged with a denied county still gets through via the zip-
    # prefix fallback (288/287/296 cover Haywood NC, Mecklenburg NC,
    # Abbeville SC etc.) or via SCOPE_BYPASS_SOURCES (CourtListener
    # bankruptcy/civil/adversary). Explicit deny wins.
    if li.county and li.state:
        if (li.county.replace(" County", "").strip().title(),
                li.state.upper()) in SCOPE_DENY_COUNTIES_NORMALIZED:
            return False
    if li.source in SCOPE_BYPASS_SOURCES:
        # State-level signal (typically CourtListener BK with no county yet).
        # Tag it so dashboard can group / filter the 'state-only' bucket.
        if not (li.county and li.county.strip()):
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["geo_attribution"] = "state-only"
        return True
    if in_scope(li.county, li.state):
        return True
    # ZIP-prefix fallback is a LAST resort for listings with NO county only.
    # 2026-06-19: previously this rescued rows that already carried an
    # out-of-scope county (e.g. Fannie in Macon/Jackson/Graham, 287xx) that
    # in_scope() had just rejected. Guarding on empty-county stops that.
    if (not (li.county and li.county.strip())) and li.zip_code \
            and any(li.zip_code.startswith(p) for p in SCOPE_ZIP_PREFIXES):
        return True
    return False


#: Sources where the listing's `state` is reliable but `county` and `zip` are
# typically unset at scrape time (CourtListener bankruptcy / civil / adversary
# only get county after enrichment). Without bypass, ~600 NC + SC bankruptcy
# listings get filtered before the bk_property enrichment can fill in their
# county. Investors want full state-wide coverage of distressed-debt signals,
# not just the 21 in-scope-county footprint.
SCOPE_BYPASS_SOURCES = {
    "national.courtlistener_bankruptcy",
    "national.courtlistener_civil",
    "national.courtlistener_adversary",
}


#: Sources where blank sale_date is acceptable — these list ACTIVELY-FOR-SALE
# inventory, not historical events. For everything else (court rosters, law-firm
# trustee calendars, tax-sale lists, public notices) we require a parseable date.
DATELESS_OK_SOURCES = {
    "national.hud_homestore",
    "national.fannie_homepath",
    "national.freddie_homesteps",
    "national.auction_dot_com",
    "national.hubzu",
    "national.xome",
    "national.foreclosure_dot_com",
    "national.zillow_foreclosures",
    "national.zillow_bulk",
    "national.bid4assets",
    "national.propwire",       # preforeclosure leads: NOD filed but sale not yet scheduled
    "national.trulia",
    "national.realtor_foreclosures",
    "national.probate_foreclosure_leads",
    "national.homeharvest",    # actively-listed-with-agent foreclosures (no sale date until auction)
    "national.distressed",     # motivated-seller / cash-only / estate-sale / as-is hits
    "counties_sc.sc_public_index_lis_pendens",  # filed but no sale date yet
    "counties_nc.nc_ecourts_lis_pendens",       # NC Tyler portal civil-side filings
    "counties.nod_discovery",                   # ROD-discovered NOD recordings
    "national.courtlistener_bankruptcy",        # Ch 7/11/13 federal bankruptcy filings
    "counties_sc.sc_tax_delinquent",            # delinquent property tax / pre-tax-sale
    # 2026-05 expansion — new sources added in this PR. Without these
    # entries, _active_only would drop their listings whenever sale_date
    # is missing (which is most of the time for monthly/annual cadence).
    "counties_sc.sc_courtrosters",                # SC MIE rosters (monthly)
    "counties_nc.nc_rod_substitute_trustee",      # ROD substitute-trustee deed filings
    "reo.usda_rd",                                # USDA Rural Development resale REO
    "reo.treasury_seized",                        # Treasury seized real property
    "reo.vrm_va_reo",                             # VRM Properties (VA REO)
    "national.courtlistener_civil",               # federal civil real-property cases
    "national.courtlistener_adversary",           # CL bankruptcy lift-stay / 363 sale
    # ncnotices.com — legal notices in NC newspapers (foreclosure +
    # divorce + probate categories). Service-by-publication divorces
    # and Notice-to-Creditors probate notices typically have no sale_date.
    "public_notices.ncnotices",
    # Relationship-deeds enrichment — derives PROBATE_NOTICE / DIVORCE_NOTICE
    # listings from ROD recordings (executor's deeds, quitclaim + $0
    # divorce transfers). These are leads, not auctions — no sale_date.
    "derived.probate_deed",
    "derived.divorce_deed",
}


def _flip_candidate(li: Listing) -> bool:
    """Filter out listings that aren't realistic flip candidates for upstate
    SC + WNC investors. Drops:
      - SFR / condo / townhouse priced > $750k UNLESS lot is >2 acres
      - Anything priced > $1.5M (excluded outright; super-luxury isn't our scope)

    KEEPS regardless of price:
      - Multi-family (apartment complexes have their own value calc)
      - Land (priced by acreage, not size)
      - Properties without an opening_bid (unknown, don't drop blindly)
    """
    bid = li.opening_bid
    if not bid or bid <= 0:
        return True  # unknown price; keep

    # Hard cap — nothing > $1.5M
    if bid > 1_500_000:
        return False

    # Multi-family + land bypass
    if li.property_kind in (PropertyKind.MULTI_FAMILY, PropertyKind.LAND):
        return True

    # SFR/condo/townhouse > $750k requires acreage justification
    if bid > 750_000:
        lot = li.lot_size_sqft
        if lot and lot >= 2 * 43_560:  # 2+ acres
            return True
        return False

    # H2 FIX (2026-05-08): default to KEEP for the most common branch
    # — bid in [1, 750_000] for SFR/condo/townhouse. Previously this
    # function fell off the end with no return, implicitly returning
    # None (falsy) → the orchestrator silently dropped every priced-SFR
    # ≤ $750k listing. The bread-and-butter flip pool. Massive silent
    # data loss until this fix.
    return True


# Common SC MIE address abbreviations — kept here so the city-splitter
# resolves them to canonical city names that match Realtor.com.
_SOLD_POOL_CITY_ALIASES = {
    "Sptbg.": "Spartanburg", "Sptbg": "Spartanburg", "Sbg.": "Spartanburg",
    "Greenwd.": "Greenwood", "Greenwd": "Greenwood",
    "Henderson.": "Hendersonville", "Hendsv.": "Hendersonville",
    "WS": "Winston-Salem",
}


def _split_embedded_city(listings: list[Listing]) -> None:
    """Split city out of street_address for sold-pool listings whose
    city is embedded in the address string ('248 Sweetie Way, Sptbg., SC').

    Mutates listings in place. The MIE PDF parsers carry the full address
    line from the PDF unsplit; this helper unblocks the downstream
    HomeHarvest-by-address lookup which requires li.city set.
    """
    for li in listings:
        if li.city or not li.street_address or "," not in li.street_address:
            continue
        parts = [p.strip() for p in li.street_address.split(",")]
        if len(parts) < 2:
            continue
        # parts[0] = street, parts[1] = city candidate, parts[2:] = state/zip noise
        candidate = parts[1]
        # Skip if it's a 2-letter state code (e.g. "123 Main St, SC")
        if len(candidate) == 2 and candidate.isupper():
            continue
        city = _SOLD_POOL_CITY_ALIASES.get(candidate, candidate)
        if 2 <= len(city) <= 30:
            li.street_address = parts[0]
            li.city = city

    return True


def _active_only(li: Listing, horizon_days: int) -> bool:
    """Drop listings whose sale is too far past or > horizon_days out, and any auction marked withdrawn/cancelled."""
    if li.auction_status and li.auction_status.lower() in {
        "withdrawn",
        "cancelled",
        "canceled",
        "rescinded",
        "sold",
        "completed",
    }:
        return False
    if li.sale_date is None:
        # For court / law-firm / tax / public-notice sources a missing date almost
        # always means we scraped a historic roster; drop it.
        return li.source in DATELESS_OK_SOURCES
    # Normalize sale_date to naive UTC (some scrapers return offset-aware
    # datetimes from dateutil parsing; we compare against utcnow() which is naive).
    sale = li.sale_date
    if sale.tzinfo is not None:
        sale = sale.replace(tzinfo=None)
    # State-aware past cutoff: NC's upset-bid period (NCGS §45-21.27) is
    # 10 days from the trustee's filing of the report of sale, and §45-21.26
    # gives 5 days from sale to file the report — so the practical window
    # from sale_date is up to 15 days. We use 14 as the operational threshold.
    # Without this grace, we strand the strongest actionable signal an
    # investor can chase. Default 2-day grace for other states; SC also
    # gets 14 (its §29-3-680 confirmation window is even longer).
    past_grace_days = 14 if li.state in ("NC", "SC") else 2
    cutoff_past = datetime.utcnow() - timedelta(days=past_grace_days)
    cutoff_future = datetime.utcnow() + timedelta(days=horizon_days)
    return cutoff_past <= sale <= cutoff_future


async def run() -> int:
    _setup_logging()
    cfg = RuntimeConfig.from_env()

    scrapers = all_scrapers()
    log.info("orchestrator.start", scrapers=len(scrapers))

    sem = asyncio.Semaphore(cfg.parallel_scrapers)

    async def bounded(s):
        async with sem:
            return s.slug, await s.safe_run()

    results = await asyncio.gather(*(bounded(s) for s in scrapers))

    raw: list[Listing] = []
    by_source: Counter = Counter()
    errors: list[str] = []
    regressions: list[str] = []
    expected = {s.slug: s.expected_min_count for s in scrapers}
    # Per-run outcome+reason from base_scraper.safe_run — so a 0-count source is
    # never ambiguous (code error vs blocked vs timeout vs legit empty).
    source_outcomes = {s.slug: (getattr(s, "last_outcome", "OK"),
                                getattr(s, "last_reason", "")) for s in scrapers}
    for slug, listings in results:
        n = len(listings)
        by_source[slug] = n
        if n == 0:
            errors.append(slug)
            continue
        # Regression detection: source's expected_min_count not met
        if n < expected.get(slug, 0):
            regressions.append(f"{slug}: got {n}, expected ≥ {expected[slug]}")
        for li in listings:
            if not li.source:
                li.source = slug
            raw.append(li)

    if regressions:
        log.warning("orchestrator.regressions", count=len(regressions), regressions=regressions)

    # Lis pendens discovery — independent search of NC eCourts + SC Public Index
    # for new foreclosure filings per county (catches early-warning cases that
    # haven't hit the law-firm trustee calendars yet)
    try:
        lp = await discover_lis_pendens()
        for li in lp:
            raw.append(li)
        by_source["courts.lis_pendens_discovery"] = len(lp)
        log.info("orchestrator.lis_pendens_discovered", count=len(lp))
    except Exception as exc:  # noqa: BLE001
        log.warning("orchestrator.lis_pendens_failed", error=str(exc))

    # Last-known-good carryover — for any source that produced ≥3 listings
    # last week but 0 this week (anti-bot escalation, scheduled maintenance,
    # transient 5xx), replay the prior listings tagged stale=True so the
    # dashboard never goes blank. Carryover listings flow through filter +
    # dedupe normally; if a fresh scrape supersedes them next run, dedupe
    # picks the fresher record. Carryover skipped for sources whose zero
    # is acknowledged (paywall/apify/render-blocked).
    try:
        from .carryover import carryover_for_zeroed_sources
        skip_for_carryover = {
            *(s.slug for s in scrapers if getattr(s, "requires_apify", False)),
            *(s.slug for s in scrapers if getattr(s, "requires_paywall", False)),
            *(s.slug for s in scrapers if getattr(s, "requires_render", False)),
        }
        carried, carry_stats = carryover_for_zeroed_sources(
            by_source_now=dict(by_source),
            expected_min=expected,
            skip_slugs=skip_for_carryover,
        )
        if carried:
            log.warning(
                "orchestrator.carryover_applied",
                listings=len(carried),
                sources=carry_stats,
            )
            for li in carried:
                raw.append(li)
                # Track in by_source under a synthetic slug suffix so
                # source_status can mark them visibly stale in run_health.
                by_source[li.source or "carryover"] += 1
    except Exception:
        log.error("carryover.failed", traceback=traceback.format_exc())
        carry_stats = {}

    log.info("orchestrator.collected", raw=len(raw))

    # Partition: recently-finished foreclosure sales (180-day past window
    # from real foreclosure-sale sources — law-firm trustees, county MIE,
    # county tax, auction.com) are routed to a SEPARATE pool used as
    # max-bid comp signal. These never appear as listings on the dashboard
    # main grid; they only surface as nested data on per-listing card
    # popouts via raw.foreclosure_sold_comps. The active pipeline stays
    # focused on actionable inventory.
    from .enrichment_foreclosure_sold_comps import is_sold_pool_candidate
    sold_pool_raw = [li for li in raw if is_sold_pool_candidate(li)]
    active_raw = [li for li in raw if li not in set(id(x) for x in sold_pool_raw)
                  ] if False else [li for li in raw if not is_sold_pool_candidate(li)]
    log.info("orchestrator.partitioned",
             active=len(active_raw), sold_pool=len(sold_pool_raw))

    # Filter to scope (counties we care about) — applies to both partitions
    in_area = [li for li in active_raw if _in_scope(li)]
    log.info("orchestrator.in_scope", count=len(in_area),
             pruned=len(active_raw) - len(in_area))
    sold_pool = [li for li in sold_pool_raw if _in_scope(li)]
    log.info("orchestrator.sold_pool_in_scope",
             count=len(sold_pool), pruned=len(sold_pool_raw) - len(sold_pool))

    # Active only
    active = [li for li in in_area if _active_only(li, cfg.sale_horizon_days)]
    log.info("orchestrator.active", count=len(active), pruned=len(in_area) - len(active))

    # Flip-candidate filter — drop super-luxury SFR (>$750k without 2+ acres,
    # and anything >$1.5M outright). Multi-family + land bypass.
    flip_able = [li for li in active if _flip_candidate(li)]
    log.info("orchestrator.flip_filtered", count=len(flip_able),
             pruned=len(active) - len(flip_able))
    active = flip_able

    # Dedupe across sources
    deduped = dedupe(active)
    log.info("orchestrator.deduped", count=len(deduped), pruned=len(active) - len(deduped))

    # Pulled-sale detection (dad's #6): listings that existed last week
    # but didn't show up this run get tagged raw['pulled_sale'] with
    # presumed_withdrawn=True and kept on the dashboard for up to 4
    # consecutive misses before being dropped. NC + SC trustees PULL
    # ~half of all scheduled foreclosure sales before they auction
    # (BK, settlement, refinance, postponement). Without this, those
    # silently disappear from the dashboard.
    try:
        from .enrichment_pulled_sales import enrich_with_pulled_sales
        deduped, pulled_stats = enrich_with_pulled_sales(deduped)
        log.info("orchestrator.pulled_sales", **pulled_stats)
    except Exception:
        log.error("pulled_sales.failed", traceback=traceback.format_exc())

    # Link reachability — drop any listing whose URL is dead
    valid = await validate(deduped, workers=cfg.link_check_workers)
    log.info("orchestrator.valid_links", count=len(valid))

    # County GIS enrichment (free, pure HTTP) — fills parcel ID, owner, zoning,
    # year built, beds/baths, sqft, tax value, last-sale book/page from county
    # ArcGIS REST. Covers 23 of 25 counties.
    enriched = await enrich_gis(valid)
    log.info("orchestrator.gis_enriched", count=len(enriched))

    # Court-records enrichment — RETIRED by default (2026-06-24). Verified dead-end:
    #  • NC: Tyler's NCJudgmentSearchService is search-only (per-case query returns
    #    0 hits) and the WorkspaceMode page is 202-async/unparseable. Tested live.
    #    NC court data already comes from the nc_ecourts scraper + nc_case_status.
    #  • SC: it scraped publicindex.sccourts.org — the SC Public Index, which our
    #    compliance policy PROHIBITS (admin order + ACLU suit). SC court coverage
    #    comes compliantly from MIE rosters + scpublicnotices.
    # It produced 0 fields while costing ~4h + 17k failed renders. Off by default;
    # set COURT_RECORDS_ENRICH=1 to force-run (not recommended — broken + SC non-compliant).
    if os.environ.get("COURT_RECORDS_ENRICH") == "1":
        try:
            await enrich_with_court_records(enriched)
            log.info("orchestrator.courts_enriched", count=len(enriched))
        except Exception as exc:  # noqa: BLE001
            log.warning("orchestrator.courts_failed", error=str(exc))

    # Zillow per-address detail enrichment (Apify) — fills photos, zestimate,
    # description, plus anything county GIS missed.
    # Wrap in try/except so a Zillow enrichment crash doesn't lose the listings
    # we already collected + GIS-enriched (the artifact write is downstream).
    try:
        enriched = await enrich(enriched)
        log.info("orchestrator.zillow_enriched", count=len(enriched))
    except Exception:
        log.error("zillow_enrich.failed", traceback=traceback.format_exc())

    # Computed flags from enriched data: absentee_owner, high_equity, vacant,
    # negative_equity, plus keyword flags from descriptions
    compute_flags(enriched)
    log.info("orchestrator.flagged", count=len(enriched))

    # Geocoding fallback — fills lat/lng for any listing the county GIS didn't
    # return geometry for. Rate-limited per Nominatim's policy.
    try:
        await enrich_geocode(enriched)
    except Exception:
        log.error("geocode.failed", traceback=traceback.format_exc())

    # Census ACS location enrichment (free, dedup'd by ZIP) — fills neighborhood
    # signals for the location grade (median HH income, home value, owner pct).
    try:
        await valuation_location.enrich(enriched)
    except Exception:
        log.error("location.failed", traceback=traceback.format_exc())

    # Per-county Register of Deeds enrichment — recorded mortgage history,
    # lis pendens, satisfactions, lien-position computation. Free, pure-HTTP
    # for the 4 vendors I've adapted (CCHS / Aumentum / Cott / Kofile).
    # ROD deed enrichment: the CCHS/Aumentum/Cott/Kofile vendor portals
    # migrated to iframe apps and currently match 0 (verified: 27 min for
    # 0 hits on the 2026-06-16 run). Gated off by default so it doesn't
    # burn wall-clock; set ROD_ENRICH_ON=1 to re-enable after adapters are
    # rebuilt.
    if os.environ.get("ROD_ENRICH_ON") == "1":
        try:
            from .rod import enrich as rod_enrich
            await rod_enrich.enrich_all(enriched)
        except Exception:
            log.error("rod.failed", traceback=traceback.format_exc())
    else:
        log.info("rod.skipped", reason="adapters_broken_set_ROD_ENRICH_ON=1")

    # Address backfill — for listings that have defendant + county but no
    # street_address (SC Public Index lis pendens, NC eCourts, courthouse
    # rolls without address columns), look the property up by owner name
    # in the same county GIS we use for address-based enrichment. Free,
    # pure-HTTP. Only writes when the match is confident (single result
    # OR a unique multi-token match).
    try:
        from .enrichment_address_backfill import enrich_addresses_from_owner
        await enrich_addresses_from_owner(enriched)
    except Exception:
        log.error("address_backfill.failed", traceback=traceback.format_exc())

    # Bankruptcy property lookup — for every CourtListener bankruptcy listing,
    # search the county GIS by debtor name across all counties in the BK
    # court's footprint to recover address + property specs. Without this,
    # bankruptcy listings have only a debtor name + court + chapter and
    # nothing flows downstream (no photos, no comps, no ARV).
    try:
        from .enrichment_bankruptcy_property import enrich_bankruptcy_property
        await enrich_bankruptcy_property(enriched)
    except Exception:
        log.error("bk_property.failed", traceback=traceback.format_exc())

    # Parcel-id / PIN / REID lookup — for tax foreclosures that publish parcel
    # numbers but not street addresses. Queries the same county GIS we already
    # use, but matches by parcel field. Falls back to subdivision+lot synthesis
    # when the GIS has "0 NO ADDRESS ASSIGNED" (undeveloped lots).
    try:
        from .enrichment_parcel_lookup import enrich_with_parcel_lookup
        await enrich_with_parcel_lookup(enriched)
    except Exception:
        log.error("parcel_lookup.failed", traceback=traceback.format_exc())

    # Aggressive cross-county owner-name search — last resort for listings
    # still without an address. Tries every county GIS in the state + a
    # fuzzy partial-token match in the stated county.
    try:
        from .enrichment_aggressive_address import enrich_with_aggressive_address
        await enrich_with_aggressive_address(enriched)
    except Exception:
        log.error("aggressive_address.failed", traceback=traceback.format_exc())

    # Capture per-enrichment stats for the per-run health artifact.
    enrichment_stats: dict[str, dict] = {}

    # SC lis-pendens GIS resolver — for any SC lis-pendens still on a
    # placeholder address, decode the authoritative venue county from the
    # case-number prefix (SC Code §15-11-10 venue rule) and confidently
    # match against SCDOT GIS by defendant name. Also re-tags county
    # whenever case# disagrees with current tag (defense-in-depth against
    # any source that mistags SC lis pendens). Free, pure-HTTP, idempotent.
    try:
        from .enrichment_lis_pendens_resolver import enrich_lis_pendens_addresses
        s = await enrich_lis_pendens_addresses(enriched)
        if s: enrichment_stats["lis_pendens_resolver"] = s
    except Exception:
        log.error("lis_pendens_resolver.failed", traceback=traceback.format_exc())

    # Parcel-centroid reverse-geocode — for listings that confidently
    # matched a parcel via owner-name search but the county GIS has no
    # situs field (Cleveland NC, Cherokee SC, etc.), reverse-geocode the
    # centroid via Nominatim and annotate raw.parcel_resolution. Result is
    # APPROXIMATE (nearest-road snap) — never written to street_address,
    # only to raw blob for human review.
    try:
        from .enrichment_parcel_reverse_geo import enrich_parcel_reverse_geo
        s = await enrich_parcel_reverse_geo(enriched)
        if s: enrichment_stats["parcel_reverse_geo"] = s
    except Exception:
        log.error("parcel_reverse_geo.failed", traceback=traceback.format_exc())

    # SC/NC case-detail scrape — for lis pendens listings whose address is
    # still a synthesized "Lis Pendens" placeholder, render the case detail
    # page on the public court portal and extract the real property address.
    # Scrapling stealth, ~20-40s per case. Disable via CASE_DETAIL_OFF=1.
    if not os.environ.get("CASE_DETAIL_OFF"):
        try:
            from .enrichment_case_detail import enrich_case_detail_addresses
            await enrich_case_detail_addresses(enriched)
        except Exception:
            log.error("case_detail.failed", traceback=traceback.format_exc())

    # FINAL synthesis pass — for listings still without an address, build
    # the best-available identifier from case#/defendant/description. The
    # dashboard never shows "(address pending)" for a real listing.
    try:
        from .enrichment_address_final import enrich_with_address_synthesis
        enrich_with_address_synthesis(enriched)
    except Exception:
        log.error("address_synth.failed", traceback=traceback.format_exc())

    # Enforce case-pinned county AFTER all address-finding enrichments.
    # NC + SC venue rules require foreclosure cases to be filed in the
    # county where the property is located (NCGS §45-21.2, SC Code §15-11-10),
    # so the case# encodes the authoritative county. Cross-county defendant-
    # name GIS matches earlier in the chain can overwrite county AND fill
    # a wrong-county street_address — Run #16 forensics found 15 NC eCourts
    # listings tagged with the wrong county. This module re-tags county and
    # nulls a real-looking but wrong-county street_address so investors don't
    # drive to the wrong property.
    try:
        from .enrichment_county_pin import enforce_case_pinned_county
        s = enforce_case_pinned_county(enriched)
        if s:
            enrichment_stats["county_pin"] = s
    except Exception:
        log.error("county_pin.failed", traceback=traceback.format_exc())

    # Final county normalization: late enrichments (reverse-geo, parcel-pin,
    # aggressive-address) assign li.county AFTER validate() ran, and some use
    # str.title() which mangles 'MCDOWELL' -> 'Mcdowell'. Canonicalize here so
    # the board doesn't split one county across casings and dedupe sees a
    # consistent county in its signatures.
    from .validation import normalize_county as _norm_county
    _county_fixed = 0
    for _li in enriched:
        if _li.county:
            _canon = _norm_county(_li.county)
            if _canon != _li.county:
                _li.county = _canon
                _county_fixed += 1
    if _county_fixed:
        log.info("orchestrator.county_normalized", fixed=_county_fixed)

    # H1 FIX (post-enrich dedupe): the initial dedupe() at line 369 ran
    # before parcel_id / zip_code / street_address / county were filled
    # by the enrichment chain above. Cross-source duplicates (same
    # property scraped by nc_ecourts + brock_scott + ROD) all missed
    # their merge because dedupe_key() fell through to the 'url:' branch.
    # Re-running dedupe now — after county_pin nailed the county, after
    # parcel_lookup filled parcel_id, after lis_pendens_resolver filled
    # street_address — gives the key the data it needs to actually merge.
    pre_dedupe2_count = len(enriched)
    enriched = dedupe(enriched)
    log.info(
        "orchestrator.dedupe2",
        before=pre_dedupe2_count,
        after=len(enriched),
        collapsed=pre_dedupe2_count - len(enriched),
    )

    # 2026-06-19 QA fix — POST-ENRICHMENT SCOPE RE-PASS. _in_scope() runs once
    # at ingest, BEFORE the enrichment chain fills county on 'state-only'
    # bankruptcy rows (and others). A row admitted with an empty county can be
    # enriched to a DENIED county (e.g. Mecklenburg) and then ship, because the
    # deny-check never re-runs. Re-apply the deny-list on the now-final county so
    # denied counties can never appear regardless of how they were admitted.
    def _denied_now(li: Listing) -> bool:
        if li.county and li.state:
            key = (li.county.replace(" County", "").strip().title(), li.state.upper())
            return key in SCOPE_DENY_COUNTIES_NORMALIZED
        return False
    _pre_scope = len(enriched)
    enriched = [li for li in enriched if not _denied_now(li)]
    if _pre_scope != len(enriched):
        log.info("orchestrator.scope_repass", dropped=_pre_scope - len(enriched))

    # Drop national court records (bankruptcy/civil) that never resolved to an
    # in-scope county — without a county they can't be routed or actioned for the
    # 18-county focus, so they're noise in the export. County-resolved national
    # records (e.g. bankruptcy debtors geocoded via OneMap) are kept.
    def _countyless_national(li) -> bool:
        return (li.source or "").startswith("national.") and not (li.county or "").strip()
    _pre_natl = len(enriched)
    enriched = [li for li in enriched if not _countyless_national(li)]
    if _pre_natl != len(enriched):
        log.info("orchestrator.drop_countyless_national", dropped=_pre_natl - len(enriched))

    # #0 contactability spine: owner name + MAILING address + absentee/
    # out-of-state flags from county GIS (free ArcGIS REST). Runs on every
    # crawl so contactability is automatic — no manual backfill needed.
    if not os.environ.get("OWNER_MAILING_OFF"):
        try:
            om = await enrich_owner_mailing(enriched)
            enrichment_stats["owner_mailing"] = om
        except Exception:
            log.error("owner_mailing.failed", traceback=traceback.format_exc())

    # Incarceration distress (NC DAC name-match against owners from #0). Low-
    # confidence name-only stack signal; runs after owner_mailing fills names.
    if not os.environ.get("INCARCERATION_OFF"):
        try:
            from .enrichment_incarceration import enrich_incarceration
            enrichment_stats["incarceration"] = await enrich_incarceration(enriched)
        except Exception:
            log.error("incarceration.failed", traceback=traceback.format_exc())

    # NC case-status: two-stage dispatch.
    #   Stage 1 (when NC_ECOURTS_USERNAME/PASSWORD set): authenticated
    #     Tyler portal scrape via WS-Fed login. Up to NC_ECOURTS_AUTH_CAP
    #     cases (default 50). Tags raw.nc_case_status with full docket
    #     detail (status, last_event, sold_price, in_upset_bid_window).
    #   Stage 2 (always runs): heuristic sale-date math + Trustee's Deed
    #     cross-ref. Fills any listings Tyler didn't tag. Pure compute.
    # Disable both with NC_CASE_STATUS_OFF=1.
    if not os.environ.get("NC_CASE_STATUS_OFF"):
        try:
            from .enrichment_nc_case_status import (
                enrich_with_nc_case_status_dispatched,
            )
            # No time limit: the authenticated Tyler path is already count-capped
            # (NC_ECOURTS_AUTH_CAP) and the no-creds path is pure compute. The
            # per-case court lookups that actually stalled live in
            # enrichment_courts, which now has its own stall-breaker (no timer).
            await enrich_with_nc_case_status_dispatched(enriched, sold_pool=sold_pool)
        except Exception:
            log.error("nc_case_status.failed", traceback=traceback.format_exc())

    # Bankruptcy cross-reference — for every existing listing whose defendant
    # matches a recent NC/SC bankruptcy filing, tag raw.bankruptcy with the
    # chapter/court/date/docket. Free with CourtListener token. Strong pre-
    # foreclosure signal: Ch.13 = trying to stop the sale, Ch.7 = liquidation.
    try:
        from .enrichment_bankruptcy import enrich_with_bankruptcy
        await enrich_with_bankruptcy(enriched)
    except Exception:
        log.error("bankruptcy.failed", traceback=traceback.format_exc())

    # Relationship-deed detection — scan ROD pool (active + sold) for
    # executor's-deed / quitclaim-divorce patterns. Emits new
    # PROBATE_NOTICE / DIVORCE_NOTICE listings into the active pool.
    # Free derivation from existing ROD scrapes.
    try:
        from .enrichment_relationship_deeds import enrich_with_relationship_deeds
        derived_leads = enrich_with_relationship_deeds(
            enriched, sold_pool=sold_pool,
        )
        if derived_leads:
            enriched = enriched + derived_leads
            log.info("relationship_deeds.added_to_active",
                     count=len(derived_leads))
    except Exception:
        log.error("relationship_deeds.failed",
                  traceback=traceback.format_exc())

    # Skip-trace (dad's #7): homeowner contact info for short-sale outreach.
    # Provider-pluggable via SKIP_TRACE_PROVIDER env:
    #   - "none" (default): disabled, no API calls
    #   - "tax_records_only": FREE, reads GIS mailing address (absentee detector)
    #   - "batchskiptracing" / etc.: PAID, $0.05-0.20/lead
    # Cap via SKIP_TRACE_MAX_PER_RUN (default 100), prioritized by sale_date
    # proximity so the imminent-sale leads always get traced first.
    try:
        from .enrichment_skip_trace import enrich_with_skip_trace
        await enrich_with_skip_trace(enriched)
    except Exception:
        log.error("skip_trace.failed", traceback=traceback.format_exc())

    # RECORDED-SALES comps (Tier 0) — query each county GIS for REAL nearby
    # arms-length recorded sales (distance-matched to the subject's coordinates)
    # and attach a median $/sqft. This is the comp-accuracy fix: real recorded
    # transactions outrank scraped listings in valuation/calc.py. Free, polite
    # (shared rate-limited client). Runs before the listing-comp fallback so the
    # valuation tier order is recorded > scraped > zestimate > tax.
    try:
        from .enrichment_recorded_comps import enrich as enrich_recorded_comps
        await enrich_recorded_comps(enriched)
    except Exception:
        log.error("recorded_comps.failed", traceback=traceback.format_exc())

    # Comp finder + property-spec backfill — pulls 180-day sold pool per county
    # from HomeHarvest (free), backfills missing sqft/beds/baths/year, attaches
    # 3 comparable sales per listing matched by zip + sqft + beds.
    try:
        from .enrichment_comps import enrich_with_comps
        await enrich_with_comps(enriched)
    except Exception:
        log.error("comps.failed", traceback=traceback.format_exc())

    # Per-address photo gallery enrichment — for listings that came from
    # courthouse / law-firm / sitemap sources WITHOUT photos, look up the
    # same address on HomeHarvest's for_sale/pending/sold endpoints to pull
    # rich Realtor.com galleries (primary + up to 5 alts). Free.
    # MUST run before Vision so the condition assessment sees all photos —
    # otherwise Vision sees only the primary, returns more pessimistic tiers
    # (Marietta St case: 1-photo Vision = 'gut' / $161k rehab vs 6-photo
    #  Vision = 'major' / $63k rehab).
    try:
        from .enrichment_photos import enrich_with_address_photos
        await enrich_with_address_photos(enriched)
    except Exception:
        log.error("photos.failed", traceback=traceback.format_exc())

    # Image fallback — ensure 100% have at least an OSM static-map of the address
    # (free, no API key). Real Zillow/Realtor photos win when present.
    # Runs before Vision so raw.images.real (the list Vision reads from) is
    # populated with the full Realtor gallery, not just the primary.
    try:
        from .enrichment_images import enrich_with_images
        await enrich_with_images(enriched, use_mapillary=False)
    except Exception:
        log.error("images.failed", traceback=traceback.format_exc())

    # Claude Vision condition assessment — overrides regex/age tier with
    # actual photo evidence when ANTHROPIC_API_KEY is set. Costs ~$0.01-0.03
    # per listing depending on photo count. Skipped silently when no key.
    # Runs AFTER photos+images so it sees the full 5-6 photo gallery.
    #
    # Budget guard: VISION_MAX_LISTINGS env caps the number of API calls.
    # Default 600 ≈ $12-18 max per run (Sonnet 4.5 pricing). Without this
    # cap, an unexpected listing-count spike could blow past the Anthropic
    # spend budget for the week before anyone notices.
    # HARD wall-clock cap: a rate-limited (429) API key can otherwise stall
    # Vision for hours and hang the whole run before it ever writes the Sheet
    # (observed 2026-06-17: 47/250 scored in 18h on a throttled key). Vision
    # is best-effort condition scoring — listings it doesn't reach fall back
    # to the regex/age condition tier. So we time-box it and ALWAYS proceed.
    try:
        from .enrichment_vision import enrich_with_vision
        vision_cap = int(os.environ.get("VISION_MAX_LISTINGS", "600"))
        vision_budget_s = float(os.environ.get("VISION_MAX_SECONDS", "900"))  # 15 min
        try:
            await asyncio.wait_for(
                enrich_with_vision(enriched, max_listings=vision_cap),
                timeout=vision_budget_s,
            )
        except asyncio.TimeoutError:
            log.warning("vision.time_capped", budget_s=vision_budget_s,
                        note="proceeding; unscored listings use regex/age condition")
    except Exception:
        log.error("vision.failed", traceback=traceback.format_exc())

    # ---- Sold-comp pool enrichment (parallel mini-pipeline) ----
    # The sold pool runs through a STRIPPED pipeline: address-backfill
    # so we know the property, photos+images so Vision has something to
    # see, Vision (capped) so each comp shows current condition. We
    # skip flood/EPA/permits/RentCast/HomeHarvest-comps-of-comps —
    # diminishing returns for a comp signal.
    if sold_pool:
        try:
            log.info("sold_pool.enrich_start", count=len(sold_pool))
            # Address backfill so we know which property each sold comp is.
            try:
                from .enrichment_address_backfill import (
                    enrich_addresses_from_owner,
                )
                await enrich_addresses_from_owner(sold_pool)
            except Exception:
                log.error("sold_pool.addr_backfill_failed",
                          traceback=traceback.format_exc())
            # County GIS — fills sqft/beds/baths/year/parcel by parcel or
            # address. Free (no API key). Without this, comp_dict's
            # beds/baths/sqft fields stay empty for many SC results-PDF
            # listings since SC MIE PDFs don't carry property specs.
            try:
                await enrich_gis(sold_pool)
            except Exception:
                log.error("sold_pool.gis_failed",
                          traceback=traceback.format_exc())
            # SC MIE PDFs put city inside street_address ("248 Sweetie Way,
            # Sptbg., SC") with li.city=None — that blocks HomeHarvest's
            # by-address lookup which requires city + state. Split it out
            # before photos.
            try:
                _split_embedded_city(sold_pool)
            except Exception:
                log.error("sold_pool.city_split_failed",
                          traceback=traceback.format_exc())
            # Pull a Realtor.com gallery for each sold comp's address.
            try:
                from .enrichment_photos import enrich_with_address_photos
                await enrich_with_address_photos(sold_pool)
            except Exception:
                log.error("sold_pool.photos_failed",
                          traceback=traceback.format_exc())
            # OSM map fallback.
            try:
                from .enrichment_images import enrich_with_images
                await enrich_with_images(sold_pool, use_mapillary=False)
            except Exception:
                log.error("sold_pool.images_failed",
                          traceback=traceback.format_exc())
            # Vision condition assessment — separate (smaller) cap from
            # the active pipeline so sold-comp Vision can't cannibalize
            # active-listing Vision budget.
            try:
                from .enrichment_vision import enrich_with_vision as _ev
                sold_vision_cap = int(os.environ.get(
                    "SOLD_POOL_VISION_MAX_LISTINGS", "100"
                ))
                await _ev(sold_pool, max_listings=sold_vision_cap)
            except Exception:
                log.error("sold_pool.vision_failed",
                          traceback=traceback.format_exc())
            # Validate (county/parcel hygiene), county_pin (case# auth),
            # property_kind (so kind-group matching works downstream).
            try:
                from .validation import validate as _vl
                _vl(sold_pool)
            except Exception:
                pass
            try:
                from .enrichment_county_pin import enforce_case_pinned_county
                enforce_case_pinned_county(sold_pool)
            except Exception:
                pass
            try:
                from .enrichment_property_kind import enrich_property_kind
                enrich_property_kind(sold_pool)
            except Exception:
                pass
            log.info("sold_pool.enrich_done", count=len(sold_pool))
        except Exception:
            log.error("sold_pool.enrich_outer_failed",
                      traceback=traceback.format_exc())

    # Match active listings to sold-pool comps (per-county, like-for-like
    # by property_kind / beds / sqft). Each matched listing gets
    # raw.foreclosure_sold_comps + raw.foreclosure_sold_comp_summary.
    # Promote-to-sold-pool pass: any active listing whose enrichment
    # surfaced raw.actual_sold_price (e.g. NC eCourts case-status detected
    # an Order Confirming Sale with hammer price) should move from the
    # active pipeline into the sold-comp pool BEFORE the matcher runs.
    # Without this pass, those listings would carry an actual_sold_price
    # that nothing else uses since they're still in `enriched`.
    try:
        promoted = []
        kept_enriched = []
        for li in enriched:
            raw = li.raw if isinstance(li.raw, dict) else {}
            if isinstance(raw.get("actual_sold_price"), (int, float)) \
                    and raw.get("nc_case_status", {}).get("promoted_to_sold_comp"):
                promoted.append(li)
            else:
                kept_enriched.append(li)
        if promoted:
            log.info("orchestrator.promoted_to_sold_pool",
                     count=len(promoted),
                     reason="nc_case_status surfaced hammer price on Order Confirming Sale")
            enriched = kept_enriched
            sold_pool = sold_pool + promoted
    except Exception:
        log.error("promote_to_sold_pool.failed",
                  traceback=traceback.format_exc())

    try:
        from .enrichment_foreclosure_sold_comps import (
            enrich_foreclosure_sold_comps,
        )
        s = enrich_foreclosure_sold_comps(enriched, sold_pool)
        if s:
            enrichment_stats["foreclosure_sold_comps"] = s
    except Exception:
        log.error("foreclosure_sold_comps.failed",
                  traceback=traceback.format_exc())

    # FEMA flood-zone tag — free public NFHL API, marks SFHA (high-risk) zones
    # so grade can dock points and the calculator can include flood insurance.
    try:
        from .enrichment_flood import enrich_with_flood
        await enrich_with_flood(enriched)
    except Exception:
        log.error("flood.failed", traceback=traceback.format_exc())

    # EPA ECHO + (optional) FBI crime data — environmental hazards within 1 mi
    # and county-level crime stats. Both free; FBI requires a free api.data.gov key.
    try:
        from .enrichment_environmental import enrich_with_environmental
        await enrich_with_environmental(enriched)
    except Exception:
        log.error("environmental.failed", traceback=traceback.format_exc())

    # FEMA repetitive flood loss — beyond basic flood zone, this catches
    # structures with multiple historical claims (much stronger distress
    # signal). Free OpenFEMA API.
    try:
        from .enrichment_fema_repetitive_loss import enrich_with_fema_repetitive_loss
        await enrich_with_fema_repetitive_loss(enriched)
    except Exception:
        log.error("fema_repetitive_loss.failed", traceback=traceback.format_exc())

    # Code enforcement violations — Charlotte 311 + other city open-data
    # portals. Active open violations are direct distress signal. Free
    # ArcGIS REST endpoints.
    try:
        from .enrichment_code_enforcement import enrich_with_code_enforcement
        await enrich_with_code_enforcement(enriched)
    except Exception:
        log.error("code_enforcement.failed", traceback=traceback.format_exc())

    # Building permits — recent permits = active investment, stale 3+ year
    # open permits = abandoned project. Free ArcGIS REST per city.
    try:
        from .enrichment_building_permits import enrich_with_building_permits
        await enrich_with_building_permits(enriched)
    except Exception:
        log.error("building_permits.failed", traceback=traceback.format_exc())

    # NC SOS LLC dissolution check — for listings with LLC/Inc defendants,
    # check NC Secretary of State for dissolved/suspended status. Capped
    # at 50 unique names/run; each Scrapling render is ~15-30s. Disable
    # via SOS_DISSOLUTION_OFF=1.
    if not os.environ.get("SOS_DISSOLUTION_OFF"):
        try:
            from .enrichment_sos_dissolution import enrich_with_sos_dissolution
            await enrich_with_sos_dissolution(enriched)
        except Exception:
            log.error("sos_dissolution.failed", traceback=traceback.format_exc())

    # Expanded rent comps — for listings without strict like-for-like comps,
    # broaden to zip-level for-rent pool. Free via HomeHarvest.
    try:
        from .enrichment_rent_comps_extra import enrich_with_extra_rent_comps
        await enrich_with_extra_rent_comps(enriched)
    except Exception:
        log.error("rent_comps_extra.failed", traceback=traceback.format_exc())

    # Property kind backfill — guarantee 100% non-UNKNOWN coverage. Runs
    # LAST so it can use every other signal (description, structure data,
    # GIS, etc.). Cascade: description → structure → listing_type → source.
    try:
        from .enrichment_property_kind import enrich_property_kind
        enrich_property_kind(enriched)
    except Exception:
        log.error("property_kind.failed", traceback=traceback.format_exc())

    # RECAP document body fetch — pull the actual motion PDFs (plain text)
    # from CourtListener for adversary-proceeding listings (lift-stay,
    # §363 sale). Adds raw.recap.plain_text which the judgment_amount
    # enrichment text-mines for property address + lender balance.
    try:
        from .enrichment_recap_document import enrich_recap_documents
        s = await enrich_recap_documents(enriched)
        if s: enrichment_stats["recap_documents"] = s
    except Exception:
        log.error("recap_documents.failed", traceback=traceback.format_exc())

    # Judgment-amount text mining — extract the lender's judgment dollar
    # figure from notice text we already scraped. Investor uses this as
    # a "mortgage balance remaining" proxy. Pure-Python, no I/O.
    try:
        from .enrichment_judgment_amount import enrich_judgment_amount
        s = enrich_judgment_amount(enriched)
        if s: enrichment_stats["judgment_amount"] = s
    except Exception:
        log.error("judgment_amount.failed", traceback=traceback.format_exc())

    # Detail-page fetcher for judgment_amount (dad's #5, follow-up to
    # patch run #11 diagnostic showing text_no_match=717/717). Pure
    # text-mining can't find the judgment amount because law-firm
    # scrapers only capture table-cell summaries, not the full Notice
    # of Sale text. This step fetches the detail page (URL already
    # in source_url) for listings still missing judgment_amount and
    # re-runs the extractor on the fetched text. Capped at 200
    # fetches/run, prioritized by imminent sale_date.
    try:
        from .enrichment_judgment_detail import (
            enrich_judgment_amount_via_detail_pages,
        )
        s = await enrich_judgment_amount_via_detail_pages(enriched)
        if s: enrichment_stats["judgment_amount_detail"] = s
    except Exception:
        log.error("judgment_detail.failed", traceback=traceback.format_exc())

    # Cross-source "amount owed" waterfall — fills a single, honestly-labeled
    # debt figure (judgment → opening-bid proxy → assessed value) so the
    # dashboard always shows something with clear provenance. Runs AFTER
    # judgment enrichment so explicit judgments win.
    try:
        from .enrichment_amount_owed import enrich_amount_owed
        s = enrich_amount_owed(enriched)
        if s: enrichment_stats["amount_owed"] = s
    except Exception:
        log.error("amount_owed.failed", traceback=traceback.format_exc())

    # Pre-write data validation gate — runs BEFORE valuation so the
    # calculator sees validated inputs. Catches recurring data-quality
    # bugs at a single chokepoint: state/county mismatch, casing fixes
    # (Mcdowell → McDowell), invalid parcel_id formats, opening_bid=0,
    # tax_value < $5k for non-land, sqft / year / beds / baths out of
    # range, and comps with bad sold_price or wrong property_kind.
    try:
        from .validation import validate as validate_listings
        validation_stats = validate_listings(enriched)
        if validation_stats:
            enrichment_stats["validation"] = validation_stats
        log.info("orchestrator.validated", **validation_stats)
    except Exception:
        log.error("validation.failed", traceback=traceback.format_exc())

    # Data-quality flag enrichment — runs after validation so the flags
    # reflect post-validation state (e.g. cross-state county nulled).
    # Surfaces investor-facing caveats in raw.data_quality.
    try:
        from .enrichment_data_quality import enrich_data_quality
        s = enrich_data_quality(enriched)
        if s: enrichment_stats["data_quality"] = s
    except Exception:
        log.error("data_quality.failed", traceback=traceback.format_exc())

    # Upset-bid window tagging (NCGS §45-21.27) — for every NC listing
    # whose sale_date is in the past 0-10 calendar days, attach
    # raw.upset_bid + upset_bid_deadline. Pure-Python, idempotent.
    # Runs AFTER validation/data_quality so it sees the cleaned-up
    # sale_date, BEFORE calc/grade so the valuation pass can read the
    # upset-bid signal (e.g. higher confidence on recent comp matching).
    try:
        from .enrichment_upset_bid import enrich_upset_bid
        s = enrich_upset_bid(enriched)
        if s:
            enrichment_stats["upset_bid"] = s
    except Exception:
        log.error("upset_bid.failed", traceback=traceback.format_exc())

    # Foreclosure-process + redemption-clock labels (NC power-of-sale vs SC
    # judicial vs tax; SC tax = ~12-mo redemption). Pure-Python; runs before
    # calc/grade so the risk model can read the process timing.
    try:
        from .enrichment_process_timing import enrich_process_timing
        s = enrich_process_timing(enriched)
        if s:
            enrichment_stats["process_timing"] = s
    except Exception:
        log.error("process_timing.failed", traceback=traceback.format_exc())

    # Lien-stack join — attach an owner's OTHER recorded debts (SC state tax
    # liens = super-priority) to the subject so calc + equity subtract them.
    # MUST run before the calc loop so max_bid reflects the senior debt.
    try:
        from .enrichment_lien_stack import enrich_lien_stack
        s = enrich_lien_stack(enriched)
        if s:
            enrichment_stats["lien_stack"] = s
    except Exception:
        log.error("lien_stack.failed", traceback=traceback.format_exc())

    # SC CAMA backfill — clean appraised value + specs + condition from the county
    # Assessor CSV (Spartanburg's live SCDOT value is corrupt). Runs before calc so
    # the value/specs feed ARV + grade. Fills only missing fields.
    try:
        from .enrichment_sc_cama import enrich_sc_cama
        s = enrich_sc_cama(enriched)
        if s:
            enrichment_stats["sc_cama"] = s
    except Exception:
        log.error("sc_cama.failed", traceback=traceback.format_exc())

    # Footprint-based sqft ESTIMATE for SC leads with no true sqft (Spartanburg
    # assessor blanks LivingArea). Needs sc_cama's story_height; runs before calc
    # so the $/sqft ARV path can fire (capped to MEDIUM, flagged estimated).
    try:
        from .enrichment_footprint_sqft import enrich_footprint_sqft
        s = enrich_footprint_sqft(enriched)
        if s:
            enrichment_stats["footprint_sqft"] = s
    except Exception:
        log.error("footprint_sqft.failed", traceback=traceback.format_exc())

    # Investor calculator + A-F grades per listing.
    valuation_failures = 0
    for li in enriched:
        try:
            c = valuation_calc.compute(li)
            g = valuation_grading.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = valuation_calc.to_dict(c)
            li.raw["grade"] = valuation_grading.to_dict(g)
        except Exception:
            valuation_failures += 1
            log.warning("valuation.failed", source_url=li.source_url,
                        traceback=traceback.format_exc())
    log.info("orchestrator.graded", count=len(enriched), failures=valuation_failures)
    # A blanket calc/grade break (refactor that throws on every listing) would
    # otherwise pass as a green run with empty calc/grade — surface it as an alarm.
    if enriched and valuation_failures >= max(5, len(enriched) // 4):
        enrichment_stats["valuation_failures"] = valuation_failures

    # Owner-equity engine — ARV − mortgage payoff − junior liens. Runs after
    # calc (needs arv_expected) + amount_owed, before distress scoring (which
    # now gates HOT on real equity, not flip ROI). Pure-Python, free.
    try:
        from .enrichment_equity import enrich_equity
        s = enrich_equity(enriched)
        if s:
            enrichment_stats["equity"] = s
    except Exception:
        log.error("equity.failed", traceback=traceback.format_exc())

    # Stacked-distress score (HOT/WARM/COLD operator board) — runs last so it
    # can stack every signal + equity + contactability gathered above.
    try:
        from .distress_score import score_board
        enrichment_stats["distress_stack"] = score_board(enriched)
        log.info("orchestrator.distress_scored", tiers=enrichment_stats["distress_stack"])
    except Exception:
        log.error("distress_score.failed", traceback=traceback.format_exc())

    # RentCast AVM cross-check on top-N listings (authoritative AVM + comparables).
    # Only fires when RENTCAST_API_KEY is set.
    # Free tier (50 calls/mo) → 25 listings × 2 calls each.
    # Foundation tier ($74/mo, 1000 calls) → 100 listings × ~10 calls each.
    try:
        rc_top_n = int(os.environ.get("RENTCAST_TOP_N", "25"))
        rc_summary = await valuation_rentcast.enrich_top_n(enriched, top_n=rc_top_n)
        if rc_summary.get("matched", 0) > 0:
            for li in enriched:
                valuation_rentcast.update_grade_with_rentcast(li)
            log.info("orchestrator.rentcast_blended", **rc_summary)
    except Exception:
        log.error("rentcast.failed", traceback=traceback.format_exc())

    # Run summary for Sheet log + email body
    by_state = Counter(li.state for li in enriched if li.state)
    by_county = Counter(f"{li.county}, {li.state}" for li in enriched if li.county and li.state)
    # Build per-source status: working / empty (verified) / regressed /
    # paywall-blocked / render-required. The blocked / render-required
    # statuses are acknowledged failure modes (no alert) versus
    # REGRESSED (alert).
    paywall_required = {s.slug for s in scrapers if getattr(s, "requires_paywall", False)}
    render_required = {s.slug for s in scrapers if getattr(s, "requires_render", False)}

    # Per-source SILENT-FAILURE alarm: rolling baselines + consecutive-zero +
    # sustained-bleed across runs. Catches a source that breaks and STAYS
    # broken, or quietly bleeds (was ~50/run, now 5/run) — failure modes the
    # single-run REGRESSED check below cannot see. Surfaced loudly in the email.
    docs_dir = Path(__file__).resolve().parent.parent.parent / "docs"
    source_alarms: dict = {}
    try:
        from .source_health_tracker import update_source_health
        source_alarms = update_source_health(by_source, expected, docs_dir)
    except Exception:
        log.error("source_health.call_failed", traceback=traceback.format_exc())

    # A hard per-run failure (0 rows WITH a real cause: blocked / errored /
    # timed out) is an alarm on the FIRST occurrence — the owner wants immediate
    # notice + the exact reason, not a 2-run-consecutive DEAD detection delay.
    for slug, (outcome, reason) in source_outcomes.items():
        if (by_source.get(slug, 0) == 0
                and outcome in ("BLOCKED", "ERROR", "TIMEOUT")
                and slug not in source_alarms):
            source_alarms[slug] = {"reason": f"{outcome}: {reason}", "severity": outcome}

    source_status = {}
    for slug in expected:
        n = by_source.get(slug, 0)
        carried_n = (carry_stats or {}).get(slug, 0)
        outcome, reason = source_outcomes.get(slug, ("OK", ""))
        if slug in source_alarms:
            # Alarm supersedes the normal status so it can't be missed.
            source_status[slug] = f"🔴 ALARM — {source_alarms[slug]['reason']}"
        elif carried_n > 0 and n == carried_n:
            # All "listings" for this slug came from the prior run — fresh
            # scrape returned zero. Surface it visibly so on-call knows the
            # data is stale, not real-world dry.
            source_status[slug] = f"CARRYOVER ({carried_n} stale from prior run)"
        elif n > 0:
            source_status[slug] = f"OK ({n})"
        # n == 0 below — say EXACTLY what happened this run, not a static guess.
        elif outcome == "BLOCKED":
            source_status[slug] = f"🔴 BLOCKED — {reason}"
        elif outcome == "TIMEOUT":
            source_status[slug] = f"🔴 TIMEOUT — {reason}"
        elif outcome == "ERROR":
            source_status[slug] = f"🔴 ERROR — {reason}"
        elif outcome == "DORMANT":
            source_status[slug] = f"DORMANT — {reason}"
        elif slug in paywall_required:
            source_status[slug] = "PAYWALL-BLOCKED"
        elif slug in render_required:
            source_status[slug] = "RENDER-REQUIRED (stealth fetch returned nothing)"
        elif expected[slug] == 0:
            source_status[slug] = "EMPTY (verified)"
        else:
            source_status[slug] = f"REGRESSED (expected ≥ {expected[slug]})"

    # New-this-run detection (early-access / geo-alert capability). Must run
    # BEFORE web_artifact overwrites the prior listings.json. Tags raw.is_new.
    new_stats = {"new": 0}
    try:
        from .new_listings import mark_new_listings
        new_stats = mark_new_listings(enriched)
    except Exception:
        log.error("new_listings.failed", traceback=traceback.format_exc())

    # Outreach stack — owner contact actions (letter/email/SMS), a postcard
    # mail-merge CSV, and persistent CRM status. Runs after skip-trace +
    # valuation so it has owner contact + deal numbers to work with.
    outreach_stats = {}
    try:
        from .outreach import generate_outreach
        outreach_stats = generate_outreach(enriched)
    except Exception:
        log.error("outreach.failed", traceback=traceback.format_exc())

    summary = {
        "total": len(enriched),
        "new_this_week": new_stats.get("new", 0),
        "new_lis_pendens": new_stats.get("new_lis_pendens", 0),
        "outreach": outreach_stats,
        "by_state": dict(by_state),
        "by_county_top": by_county.most_common(15),
        "by_source": dict(by_source),
        "errors": errors,
        "regressions": regressions,
        "source_status": source_status,
        "source_alarms": source_alarms,
        "notes": f"horizon={cfg.sale_horizon_days}d, scrapers={len(scrapers)}, regressions={len(regressions)}",
    }

    # ---- Fail-loud guard: catastrophic week-over-week count drop ----------
    # A silent drop in total listings is the failure mode that hid for a
    # month (the pipeline reported "success" while shipping far less data).
    # Compare against the prior committed listings.json BEFORE we overwrite
    # it; surface a sharp drop as a regression in the health report + log so
    # it can never pass unnoticed again. We do NOT abort — a genuinely quiet
    # week should still publish — but the drop is made impossible to miss.
    try:
        import json as _json
        prev_path = Path(__file__).resolve().parent.parent.parent / "docs" / "listings.json"
        if prev_path.exists():
            prev = _json.loads(prev_path.read_text())
            prev_total = len(prev) if isinstance(prev, list) else 0
            curr_total = len(enriched)
            if prev_total >= 100 and curr_total < prev_total * 0.75:
                pct = round(100 * (1 - curr_total / prev_total))
                msg = (f"COUNT DROP {pct}%: {prev_total} -> {curr_total} "
                       f"listings vs last run — investigate before trusting this run")
                summary.setdefault("regressions", []).append(msg)
                summary["count_drop_alert"] = {
                    "prev_total": prev_total, "curr_total": curr_total, "drop_pct": pct,
                }
                log.error("orchestrator.count_drop_alert",
                          prev=prev_total, curr=curr_total, drop_pct=pct)
    except Exception:
        log.error("count_drop_guard.failed", traceback=traceback.format_exc())

    # Web artifact — always write, even when Sheets/Email secrets are missing.
    # GitHub Actions then commits docs/ back to the repo, GitHub Pages serves it.
    try:
        write_artifact(enriched, summary)
    except Exception:
        log.error("web_artifact.failed", traceback=traceback.format_exc())

    # Sold-comp pool — separate file so the dashboard's main grid never
    # shows past-sale "listings". The card popout still reads
    # raw.foreclosure_sold_comps which travels with the active listing.
    # This separate file is for power-users / future analytics.
    try:
        import json as _json
        from .web_artifact import _to_dict as _slim
        sold_path = Path(__file__).resolve().parent.parent.parent / \
            "docs" / "foreclosure_sold_pool.json"
        sold_payload = [_slim(li) for li in sold_pool]
        sold_path.write_text(
            _json.dumps(sold_payload, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        log.info("orchestrator.sold_pool_written",
                 path=str(sold_path), count=len(sold_payload))
    except Exception:
        log.error("sold_pool_write.failed",
                  traceback=traceback.format_exc())

    # Per-source health JSON — committed alongside listings.json each run
    # so an investor (or alerting hook) can see at a glance which sources
    # are OK, which are blocked, and which actually regressed.
    try:
        from .run_health import write_health_artifact
        health_path = Path(__file__).resolve().parent.parent.parent / "docs" / "run_health.json"
        write_health_artifact(
            out_path=health_path,
            summary=summary,
            enrichment_stats=enrichment_stats,
        )
        log.info("orchestrator.health_artifact", path=str(health_path))
    except Exception:
        log.error("run_health.failed", traceback=traceback.format_exc())

    # Sheets + Email — guarded so a missing secret doesn't kill the rest of the run
    sheet_url = ""
    if cfg.sheet_id and cfg.google_service_account_json:
        try:
            sheet_url = write_listings(
                sheet_id=cfg.sheet_id,
                service_account_json=cfg.google_service_account_json,
                listings=enriched,
                run_summary=summary,
            )
        except Exception:
            log.error("sheets.failed", traceback=traceback.format_exc())
    else:
        log.warning("sheets.skipped_no_secret")

    # Send the digest whenever Gmail creds exist — do NOT gate on sheet_url.
    # Gating on the sheet meant a missing/failed Sheets export silently
    # suppressed the ENTIRE email, including the source-alarm/failure banner the
    # owner relies on to learn a source broke. The template already guards the
    # sheet link with `if sheet_url`, so an empty sheet_url is fine.
    if cfg.gmail_app_password and cfg.gmail_sender:
        try:
            send_digest(
                sender=cfg.gmail_sender,
                app_password=cfg.gmail_app_password,
                recipients=cfg.email_recipients,
                sheet_url=sheet_url,
                run_summary=summary,
            )
        except Exception:
            log.error("email.failed", traceback=traceback.format_exc())
    elif summary.get("source_alarms"):
        # No Gmail creds but sources failed — make sure it can't pass silently.
        log.error("email.skipped_but_alarms_present", alarms=list(summary["source_alarms"]))
    else:
        log.warning("email.skipped_no_secret")

    log.info("orchestrator.done")
    return 0


def cli() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    cli()
