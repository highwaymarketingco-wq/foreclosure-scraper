"""Johnston County NC's raw['johnston_delinquent_tax_crosswalk'] already carries a full per-year
unpaid-amount breakdown (delinquent_by_year) -- this module restates the shared
raw['two_year_delinquent'] contract from it, same shape as enrichment_randolph_multiyear_tax's
build_two_year_block and enrichment_ptscloud_two_year_delinquent's own precedent for this exact
key. PURE, no network call: the crosswalk's own ingest already did the one real fetch.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-21.csv: NC Johnston two_year_delinquent, 3,485
est_rows_affected, built=no). The crosswalk (scrapers/counties_nc/johnston_delinquent_tax_
crosswalk.py, landed 2026-10-20 commit 877d7726, 185 real board rows) already has everything
needed for this column; nothing had yet restated it. See also
enrichment_johnston_rollback_exposure.py's module docstring for the full live-investigation
context (same gap-list entry, different root cause and fix shape).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional

import structlog

from . import tax_calendar
from .models import Listing

log = structlog.get_logger()

SRC_KEY = "johnston_delinquent_tax_crosswalk"
RAW_KEY = "two_year_delinquent"
SOURCE_SLUG = "enrichment_johnston_two_year_delinquent"
COUNTY = "Johnston"


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(RAW_KEY), dict)


def build_two_year_block(crosswalk: dict, *, today: Optional[date] = None) -> dict:
    """Pure: the shared raw['two_year_delinquent'] contract from one row's already-fetched
    raw['johnston_delinquent_tax_crosswalk']['delinquent_by_year'] -- written unconditionally
    (a real answer either way, not gated on qualifying)."""
    today = today or date.today()
    by_year = crosswalk.get("delinquent_by_year") or {}
    years = sorted(int(y) for y in by_year if str(y).isdigit())
    matured = tax_calendar.completed_delinquent_years(years, "NC", COUNTY, today)
    return {
        "is_two_year_plus": len(matured) >= 2,
        "years": len(matured),
        "oldest_year": years[0] if years else None,
        "source": SOURCE_SLUG,
    }


def enrich_johnston_two_year_delinquent(listings: Iterable[Listing]) -> dict[str, int]:
    """Walk Johnston NC rows carrying raw['johnston_delinquent_tax_crosswalk'] and stamp
    raw['two_year_delinquent'] from it directly -- no network, no cap, every eligible row gets a
    real answer in one pass."""
    stats = {"eligible": 0, "written": 0}
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else None
        if not isinstance(raw, dict):
            continue
        crosswalk = raw.get(SRC_KEY)
        if not isinstance(crosswalk, dict):
            continue
        stats["eligible"] += 1
        if _already_done(raw):
            continue
        raw[RAW_KEY] = build_two_year_block(crosswalk)
        stats["written"] += 1
    log.info("johnston_two_year_delinquent.done", **stats)
    return stats
