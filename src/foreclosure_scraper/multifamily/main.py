"""Multifamily orchestrator. Runs on the 15th of each month.

Pipeline (lighter than the foreclosure run because the data already comes
heavily structured from LoopNet / Crexi / Zillow / Realtor):
  1. Run all multifamily scrapers in parallel (budget-gated by apify_helper)
  2. Filter to scope (counties + ZIP prefixes)
  3. Dedupe by address / parcel
  4. Validate links
  5. ArcGIS GIS enrichment (parcel/owner/zoning)
  6. Census ACS location enrichment (neighborhood signals)
  7. RentCast cross-check (top-N by price/unit; tiny - ~10 calls)
  8. Multifamily-specific calc + grade (cap rate, GRM, $/unit, $/sqft)
  9. Write a separate `multifamily.json` artifact + Sheet tab + email digest
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

import structlog

from ..config import RuntimeConfig, in_scope, SCOPE_ZIP_PREFIXES
from ..dedupe import dedupe
from ..email_sender import send_digest
from ..enrichment_arcgis import enrich as enrich_gis
from ..enrichment_geocode import enrich as enrich_geocode
from ..link_validator import validate
from ..models import Listing
from ..valuation import location as valuation_location
from ..web_artifact import _to_dict
from .calc_mf import compute_multifamily, grade_multifamily, to_dict_mf
from .crexi import CrexiMultifamily
from .loopnet import LoopNetMultifamily
from .realtor_mf import RealtorMultifamily
from .zillow_mf import ZillowMultifamily


def _setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="%(message)s", stream=sys.stdout)
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


SCRAPERS = (LoopNetMultifamily(), CrexiMultifamily(), ZillowMultifamily(), RealtorMultifamily())


async def _write_artifact(listings: list[Listing], summary: dict) -> Path:
    docs = Path("docs")
    docs.mkdir(parents=True, exist_ok=True)
    out = docs / "multifamily.json"
    payload = {
        "run_time": datetime.utcnow().isoformat() + "Z",
        "total": len(listings),
        "by_source": summary.get("by_source", {}),
        "by_state": summary.get("by_state", {}),
        "by_county_top": summary.get("by_county_top", []),
        "listings": [_to_dict(li) for li in listings],
    }
    import json
    out.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    log.info("multifamily.artifact.written", path=str(out), total=len(listings))
    return out


async def run() -> int:
    _setup_logging()
    cfg = RuntimeConfig.from_env()

    log.info("multifamily.start", scrapers=len(SCRAPERS))

    sem = asyncio.Semaphore(cfg.parallel_scrapers)

    async def bounded(s):
        async with sem:
            return s.slug, await s.safe_run()

    results = await asyncio.gather(*(bounded(s) for s in SCRAPERS))

    raw: list[Listing] = []
    by_source: Counter = Counter()
    errors: list[str] = []
    for slug, listings in results:
        by_source[slug] = len(listings)
        if not listings:
            errors.append(slug)
        for li in listings:
            if not li.source:
                li.source = slug
            raw.append(li)

    in_area = [li for li in raw if _in_scope(li)]
    log.info("multifamily.in_scope", count=len(in_area), pruned=len(raw) - len(in_area))

    deduped = dedupe(in_area)
    log.info("multifamily.deduped", count=len(deduped))

    valid = await validate(deduped, workers=cfg.link_check_workers)
    log.info("multifamily.valid_links", count=len(valid))

    enriched = await enrich_gis(valid)
    log.info("multifamily.gis_enriched", count=len(enriched))

    try:
        await enrich_geocode(enriched)
    except Exception:
        log.error("geocode.failed", traceback=traceback.format_exc())

    try:
        await valuation_location.enrich(enriched)
    except Exception:
        log.error("location.failed", traceback=traceback.format_exc())

    # Multifamily-specific scoring
    for li in enriched:
        try:
            c = compute_multifamily(li)
            g = grade_multifamily(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = to_dict_mf(c)
            li.raw["grade"] = g
        except Exception:
            log.warning("multifamily.score.failed", source_url=li.source_url)

    by_state = Counter(li.state for li in enriched if li.state)
    by_county = Counter(f"{li.county}, {li.state}" for li in enriched if li.county and li.state)
    summary = {
        "total": len(enriched),
        "by_state": dict(by_state),
        "by_county_top": by_county.most_common(15),
        "by_source": dict(by_source),
        "errors": errors,
        "notes": f"multifamily monthly run, scrapers={len(SCRAPERS)}",
    }

    try:
        await _write_artifact(enriched, summary)
    except Exception:
        log.error("multifamily.artifact.failed", traceback=traceback.format_exc())

    # Email a separate multifamily digest if creds are present
    if cfg.gmail_app_password and cfg.gmail_sender:
        try:
            send_digest(
                sender=cfg.gmail_sender,
                app_password=cfg.gmail_app_password,
                recipients=cfg.email_recipients,
                sheet_url="",
                run_summary={**summary, "subject_override": "Multifamily Monthly Digest"},
            )
        except Exception:
            log.error("multifamily.email.failed", traceback=traceback.format_exc())

    log.info("multifamily.done", total=len(enriched))
    return 0


def cli() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    cli()
