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

from .assessment import assess_all
from .config import RuntimeConfig, in_scope, SCOPE_ZIP_PREFIXES
from .dedupe import dedupe
from .email_sender import send_digest
from .enrichment import enrich
from .link_validator import validate
from .models import Listing
from .scrapers._registry import all_scrapers
from .sheets import write_listings


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


def _active_only(li: Listing, horizon_days: int) -> bool:
    """Drop listings whose sale is in the past or > horizon_days out, and any auction marked withdrawn/cancelled."""
    if li.auction_status and li.auction_status.lower() in {"withdrawn", "cancelled", "canceled", "rescinded"}:
        return False
    if li.sale_date is None:
        return True  # keep, we don't know yet
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
    for slug, listings in results:
        if not listings:
            errors.append(slug)
            continue
        for li in listings:
            if not li.source:
                li.source = slug
            raw.append(li)
        by_source[slug] = len(listings)

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

    # Property enrichment
    enriched = await enrich(valid)
    log.info("orchestrator.enriched", count=len(enriched))

    # Property assessment (condition / ARV / rehab / max-bid)
    assessments = assess_all(enriched)
    # Pin assessment values onto each listing's raw payload so the Sheet writer
    # can render them as dedicated columns.
    for li, a in zip(enriched, assessments):
        li.raw["assessment"] = a
    log.info("orchestrator.assessed", count=len(enriched))

    # Run summary for Sheet log + email body
    by_state = Counter(li.state for li in enriched if li.state)
    by_county = Counter(f"{li.county}, {li.state}" for li in enriched if li.county and li.state)
    summary = {
        "total": len(enriched),
        "new_this_week": len(enriched),  # placeholder until we wire historical compare
        "by_state": dict(by_state),
        "by_county_top": by_county.most_common(15),
        "by_source": dict(by_source),
        "errors": errors,
        "notes": f"horizon={cfg.sale_horizon_days}d, scrapers={len(scrapers)}",
    }

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
