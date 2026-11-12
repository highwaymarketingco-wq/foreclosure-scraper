"""Restates multi_year_delinquent_tax + two_year_delinquent from data
enrichment_ustaxdata_tax_search.py ALREADY fetched -- pure compute, no network call, same
shape as enrichment_johnston_two_year_delinquent.py's restatement pattern.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-28.csv). NC Robeson/Alexander/Rockingham all
show "multi_year_delinquent_tax" and "two_year_delinquent" sourced-not-built, source
"tax/property card: www.ustaxdata.com". enrichment_ustaxdata_tax_search.py's own 2026-10-20
correction already explains why: it writes raw['ustaxdata_delinquent_tax'] (bills, years_unpaid)
and, through enrichment_tax_owed.py's generic Pass B, raw['tax_owed']/raw['tax_aging_surfaced']
-- but NOTHING in that chain ever writes the two literal raw keys multi_year_delinquent_tax/
two_year_delinquent gap_matrix.py reads as an exact presence check. The per-year bill history is
already sitting on the row; this module just reads it a second way.

STATUS-BASED, NOT AMOUNT-BASED -- the one real nuance here. Gaston's sibling module (and
Nash's) treat a year "unpaid" when its dollar amount is positive. That rule would silently MISS
Rockingham: that tenant's taxbill.cfm detail page never resolves a dollar amount for many
confirmed-unpaid bills (enrichment_ustaxdata_tax_search.py's own 2026-10-20 docstring section,
"balance stayed None" on a live-verified Rockingham parcel with 5 real 2026 unpaid bills).
bills[]'s own `status` field ("paid"/"unpaid"/"partial"/"unknown", set from the vendor's own
bill_paid/bill_open/bill_partial icon -- never inferred from a dollar amount) is the one signal
present on every tenant regardless of whether the second-hop dollar-amount fetch succeeded, so
delinquency here is read from `status in {"unpaid", "partial"}`, matching the vendor's own
stated bill status rather than re-deriving it from an amount that can be legitimately absent.

Covers all three tenants enrichment_ustaxdata_tax_search.py already reaches (TENANTS: Robeson;
NAME_SEARCH_TENANTS: Alexander, Rockingham) -- the eligibility check reads those same registries
rather than hand-listing counties again.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional

import structlog

from . import tax_calendar
from .enrichment_ustaxdata_tax_search import NAME_SEARCH_TENANTS, TENANTS
from .models import Listing
from .scrapers.counties_generic.multi_year_delinquent_tax import _longest_run, _trend

log = structlog.get_logger()

SRC_KEY = "ustaxdata_delinquent_tax"
RAW_KEY = "multi_year_delinquent_tax"
TWO_YEAR_KEY = "two_year_delinquent"
SOURCE_SLUG = "enrichment_ustaxdata_multiyear_tax"
_DELINQUENT_STATUSES = frozenset({"unpaid", "partial"})
MIN_YEARS = 2

_TENANT_COUNTIES = {c.lower() for c in TENANTS} | {c.lower() for c in NAME_SEARCH_TENANTS}


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(RAW_KEY), dict)


def _eligible(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else None
    if not isinstance(raw, dict):
        return False
    return bool(
        (li.state or "").strip().upper() == "NC"
        and (li.county or "").replace(" County", "").strip().lower() in _TENANT_COUNTIES
        and isinstance(raw.get(SRC_KEY), dict)
        and isinstance(raw[SRC_KEY].get("bills"), list)
        and not _already_done(raw)
    )


def _delinquent_per_year(bills: list[dict]) -> dict[int, Optional[float]]:
    """One entry per delinquent bill-year (status unpaid/partial), newest status wins if a year
    somehow repeats. Amount is whatever total_due the second-hop fetch resolved, or None --
    never coerced to 0, so a real-but-unknown balance isn't mistaken for a cleared one."""
    per_year: dict[int, Optional[float]] = {}
    for b in bills or ():
        if not isinstance(b, dict):
            continue
        year = b.get("year")
        if not isinstance(year, int):
            continue
        if b.get("status") in _DELINQUENT_STATUSES:
            per_year[year] = b.get("total_due")
    return per_year


def build_block(bills: list[dict], county: str, *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block, or None when fewer than MIN_YEARS
    delinquent years or none of them has matured yet (same gate shape as Gaston's sibling)."""
    today = today or date.today()
    per_year = _delinquent_per_year(bills)
    years = sorted(per_year)
    if len(years) < MIN_YEARS:
        return None
    matured = [y for y in years if tax_calendar.levy_year_is_delinquent(y, "NC", county, today)]
    if not matured:
        return None
    current = [y for y in years if y not in matured]
    known_amounts = [per_year[y] for y in years if per_year[y]]
    total_owed = round(sum(known_amounts), 2) if known_amounts else None
    matured_amounts = [per_year[y] for y in matured if per_year[y]]
    matured_owed = round(sum(matured_amounts), 2) if matured_amounts else None
    county_latest_year = max((b["year"] for b in bills if isinstance(b, dict) and "year" in b),
                             default=years[-1])
    return {
        "years": years,
        "per_year": {str(y): per_year[y] for y in years},
        "years_delinquent": len(matured),
        "unpaid_bill_years": len(years),
        "matured_years": matured,
        "matured_years_delinquent": len(matured),
        "consecutive_years": _longest_run(years),
        "first_year": years[0],
        "latest_year": years[-1],
        "latest_matured_year": max(matured),
        "county_latest_year": county_latest_year,
        "current_levy_year": (current[-1] if current else None),
        "in_current_levy": bool(current),
        "total_due": total_owed,
        "total_owed": total_owed,
        "matured_owed": matured_owed,
        "amount_known": bool(known_amounts),
        "year": years[-1],
        "trend": _trend(per_year, matured),
        "still_accruing": years[-1] >= county_latest_year,
        "amount_basis": "annual_bill",
        "layers": ["ustaxdata_bill_status"],
        "source": SOURCE_SLUG,
    }


def build_two_year_block(bills: list[dict], county: str, *, today: Optional[date] = None) -> dict:
    """Pure: the raw['two_year_delinquent'] wrapper, written unconditionally once a row has a
    real ustaxdata answer either way -- same convention as
    enrichment_johnston_two_year_delinquent.build_two_year_block / Nash's/Gaston's siblings."""
    today = today or date.today()
    per_year = _delinquent_per_year(bills)
    matured = tax_calendar.completed_delinquent_years(sorted(per_year), "NC", county, today)
    return {
        "is_two_year_plus": len(matured) >= 2,
        "years": len(matured),
        "oldest_year": min(matured) if matured else None,
        "source": SOURCE_SLUG,
    }


def enrich_ustaxdata_multiyear_tax(listings: Iterable[Listing]) -> dict[str, int]:
    """Walk NC Robeson/Alexander/Rockingham rows carrying raw['ustaxdata_delinquent_tax'] and
    restate raw['multi_year_delinquent_tax'] + raw['two_year_delinquent'] from its own bills --
    no network, no cap, every eligible row gets a real answer in one pass."""
    stats = {"eligible": 0, "qualified": 0, "two_year_written": 0}
    for li in listings:
        if not _eligible(li):
            continue
        stats["eligible"] += 1
        raw = li.raw
        county = (li.county or "").replace(" County", "").strip()
        bills = raw[SRC_KEY]["bills"]
        block = build_block(bills, county)
        if block:
            raw[RAW_KEY] = block
            stats["qualified"] += 1
        raw[TWO_YEAR_KEY] = build_two_year_block(bills, county)
        stats["two_year_written"] += 1
    log.info("ustaxdata_multiyear_tax.done", **stats)
    return stats
