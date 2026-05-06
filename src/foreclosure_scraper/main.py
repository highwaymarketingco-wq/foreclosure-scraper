"""Orchestrator: run all scrapers, dedupe, validate, enrich, write Sheet, email."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from collections import Counter
from datetime import datetime, timedelta

import structlog

from .config import RuntimeConfig, in_scope, SCOPE_ZIP_PREFIXES
from .dedupe import dedupe
from .email_sender import send_digest
from .enrichment import enrich
from .enrichment_arcgis import enrich as enrich_gis
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


def _in_scope(li: Listing) -> bool:
    if li.source in SCOPE_BYPASS_SOURCES:
        return True
    if in_scope(li.county, li.state):
        return True
    if li.zip_code and any(li.zip_code.startswith(p) for p in SCOPE_ZIP_PREFIXES):
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
    "counties_nc.wake_tax",                       # annual tax-foreclosure auctions
    "counties_nc.forsyth_tax",
    "counties_nc.guilford_tax",
    "counties_nc.new_hanover_tax",
    "counties_nc.durham_tax",
    "counties_nc.nc_rod_substitute_trustee",      # ROD substitute-trustee deed filings
    "reo.usda_rd",                                # USDA Rural Development resale REO
    "reo.treasury_seized",                        # Treasury seized real property
    "reo.vrm_va_reo",                             # VRM Properties (VA REO)
    "city_websites.charlotte_demolition",         # demolition orders (distress signal)
    "national.courtlistener_civil",               # federal civil real-property cases
    "national.courtlistener_adversary",           # CL bankruptcy lift-stay / 363 sale
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

    return True


def _active_only(li: Listing, horizon_days: int) -> bool:
    """Drop listings whose sale is in the past or > horizon_days out, and any auction marked withdrawn/cancelled."""
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
    cutoff_past = datetime.utcnow() - timedelta(days=2)  # tiny grace for same-day sales
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

    # Filter to scope (counties we care about)
    in_area = [li for li in raw if _in_scope(li)]
    log.info("orchestrator.in_scope", count=len(in_area), pruned=len(raw) - len(in_area))

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

    # Link reachability — drop any listing whose URL is dead
    valid = await validate(deduped, workers=cfg.link_check_workers)
    log.info("orchestrator.valid_links", count=len(valid))

    # County GIS enrichment (free, pure HTTP) — fills parcel ID, owner, zoning,
    # year built, beds/baths, sqft, tax value, last-sale book/page from county
    # ArcGIS REST. Covers 23 of 25 counties.
    enriched = await enrich_gis(valid)
    log.info("orchestrator.gis_enriched", count=len(enriched))

    # Court records enrichment (NC eCourts + SC Public Index) — fills plaintiff,
    # defendant, trustee, sale location for any listing that has a case number.
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
    try:
        from .rod import enrich as rod_enrich
        await rod_enrich.enrich_all(enriched)
    except Exception:
        log.error("rod.failed", traceback=traceback.format_exc())

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

    # NC eCourts case-status check via Tyler portal (Scrapling/Playwright).
    # Tags listings.raw.nc_case_status with current docket state — pending,
    # sold (recent sale), upset_bid (in 10-day window), confirmed, dismissed.
    # Heavy: each case takes a few seconds to render; capped to top 100 cases
    # prioritized by recent sale_date. Disable with NC_CASE_STATUS_OFF=1.
    if not os.environ.get("NC_CASE_STATUS_OFF"):
        try:
            from .enrichment_nc_case_status import enrich_with_nc_case_status
            await enrich_with_nc_case_status(enriched)
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
    try:
        from .enrichment_vision import enrich_with_vision
        vision_cap = int(os.environ.get("VISION_MAX_LISTINGS", "600"))
        await enrich_with_vision(enriched, max_listings=vision_cap)
    except Exception:
        log.error("vision.failed", traceback=traceback.format_exc())

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

    # Investor calculator + A-F grades per listing.
    for li in enriched:
        try:
            c = valuation_calc.compute(li)
            g = valuation_grading.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = valuation_calc.to_dict(c)
            li.raw["grade"] = valuation_grading.to_dict(g)
        except Exception:
            log.warning("valuation.failed", source_url=li.source_url)
    log.info("orchestrator.graded", count=len(enriched))

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
    # apify-blocked / paywall-blocked / render-required. The blocked /
    # render-required statuses are acknowledged failure modes (no alert)
    # versus REGRESSED (alert).
    apify_required = {s.slug for s in scrapers if getattr(s, "requires_apify", False)}
    paywall_required = {s.slug for s in scrapers if getattr(s, "requires_paywall", False)}
    render_required = {s.slug for s in scrapers if getattr(s, "requires_render", False)}
    source_status = {}
    for slug in expected:
        n = by_source.get(slug, 0)
        carried_n = (carry_stats or {}).get(slug, 0)
        if carried_n > 0 and n == carried_n:
            # All "listings" for this slug came from the prior run — fresh
            # scrape returned zero. Surface it visibly so on-call knows the
            # data is stale, not real-world dry.
            source_status[slug] = f"CARRYOVER ({carried_n} stale from prior run)"
        elif n > 0:
            source_status[slug] = f"OK ({n})"
        elif slug in paywall_required:
            source_status[slug] = "PAYWALL-BLOCKED"
        elif slug in render_required:
            source_status[slug] = "RENDER-REQUIRED (Scrapling stealth not wired)"
        elif slug in apify_required:
            source_status[slug] = "APIFY-BLOCKED"
        elif expected[slug] == 0:
            source_status[slug] = "EMPTY (verified)"
        else:
            source_status[slug] = f"REGRESSED (expected ≥ {expected[slug]})"

    summary = {
        "total": len(enriched),
        "new_this_week": len(enriched),  # placeholder until we wire historical compare
        "by_state": dict(by_state),
        "by_county_top": by_county.most_common(15),
        "by_source": dict(by_source),
        "errors": errors,
        "regressions": regressions,
        "source_status": source_status,
        "notes": f"horizon={cfg.sale_horizon_days}d, scrapers={len(scrapers)}, regressions={len(regressions)}",
    }

    # Web artifact — always write, even when Sheets/Email secrets are missing.
    # GitHub Actions then commits docs/ back to the repo, GitHub Pages serves it.
    try:
        write_artifact(enriched, summary)
    except Exception:
        log.error("web_artifact.failed", traceback=traceback.format_exc())

    # Per-source health JSON — committed alongside listings.json each run
    # so an investor (or alerting hook) can see at a glance which sources
    # are OK, which are blocked, and which actually regressed.
    try:
        from pathlib import Path
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

    if cfg.gmail_app_password and cfg.gmail_sender and sheet_url:
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
    else:
        log.warning("email.skipped_no_secret")

    log.info("orchestrator.done")
    return 0


def cli() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    cli()
