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
from .models import Listing
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
    if in_scope(li.county, li.state):
        return True
    if li.zip_code and any(li.zip_code.startswith(p) for p in SCOPE_ZIP_PREFIXES):
        return True
    return False


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
}


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
    cutoff_past = datetime.utcnow() - timedelta(days=2)  # tiny grace for same-day sales
    cutoff_future = datetime.utcnow() + timedelta(days=horizon_days)
    return cutoff_past <= li.sale_date <= cutoff_future


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

    log.info("orchestrator.collected", raw=len(raw))

    # Filter to scope (counties we care about)
    in_area = [li for li in raw if _in_scope(li)]
    log.info("orchestrator.in_scope", count=len(in_area), pruned=len(raw) - len(in_area))

    # Active only
    active = [li for li in in_area if _active_only(li, cfg.sale_horizon_days)]
    log.info("orchestrator.active", count=len(active), pruned=len(in_area) - len(active))

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
    enriched = await enrich(enriched)
    log.info("orchestrator.zillow_enriched", count=len(enriched))

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
    # Build per-source status: working / empty (verified) / regressed / Apify-blocked
    apify_required = {s.slug for s in scrapers if getattr(s, "requires_apify", False)}
    source_status = {}
    for slug in expected:
        n = by_source.get(slug, 0)
        if n > 0:
            source_status[slug] = f"OK ({n})"
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
