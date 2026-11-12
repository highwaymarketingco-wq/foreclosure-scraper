"""NC PTS Cloud (Farragut BillPWA) multi-year delinquent-tax HISTORY — restate data this
project already collects into the one shared contract key the gap matrix actually credits.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-18.csv, read before writing a line here).
    "multi_year_delinquent_tax" shows sourced-not-built, hits=0, built=no for several of the
    counties `counties_nc.nc_ptscloud_delinquent_tax` already scrapes live every run:
    NC Forsyth 10,688 applicable, NC Pitt 5,182, NC Beaufort 4,281 (also two_year_delinquent
    4,281 — out of scope here, a different column), NC Henderson 3,976. The column's own
    next_action guesses "add a tax-roll reader for ... bcpwa.ncptscloud.com" — but that reader
    already exists and is already wired into main.py (slug counties_nc.nc_ptscloud_delinquent_tax,
    line ~987). The real gap is identical in shape to the Gaston precedent from last night
    (project_tax_roll_reader_workflow_2026-10-18.md / enrichment_gaston_multiyear_tax.py):
    an UPSTREAM source already reads the full per-year bill history, but nothing ever restates
    it under the one raw key gap_matrix.checked_columns() actually reads for this column.

    scripts/gap_matrix.py (2026-10-16 audit, same file, line ~1150) narrowed
    multi_year_delinquent_tax's check to `raw.get("multi_year_delinquent_tax") not in _EMPTY`
    specifically because the old broad "any tax-ish key" predicate false-credited 150,198 rows
    against its real 3-county-only producer, scrapers/counties_generic/multi_year_delinquent_tax.py
    (Buncombe/Oconee/Pickens — a wholly different data shape: per-year ArcGIS "unpaid bills"
    layers, one hosted service per calendar year). That producer has NO path to Forsyth et al.;
    they are not on that platform at all. This module is a second, independent producer of the
    SAME shared raw key, for a different source family — same pattern Gaston's enrichment
    already established (DevNetWedge instead of ArcGIS-per-year; here, BillPWA CSV instead of
    either).

WHERE THE DATA ALREADY LIVES. `nc_ptscloud_delinquent_tax._parse_csv` aggregates every tenant's
    exported CSV by parcel and, per parcel, appends one `_bill_entry()` dict per distinct
    tax-year row it sees (`a["by_year"]`) before folding everything down into
    `raw['nc_ptscloud_delinquent_tax']['by_year']` via `_year_summary()` — the full multi-year
    depth is read and kept, just under that source's OWN raw key, not the shared one. No new
    network call, no new vendor integration: this module is a pure, no-network transform that
    walks already-collected board rows and restates `by_year` into `raw['multi_year_delinquent_tax']`
    in the exact byte-shape Gaston's enrichment and the Buncombe/Oconee/Pickens scraper both
    already produce (`tax_binding.BLOCK_PARCEL_FIELDS["multi_year_delinquent_tax"] = ("parcel_key",)`,
    `enrichment_tax_owed._SOURCES`'s exact-key read of `"total_due"`, `web_artifact.RAW_KEEP`'s
    "*" wildcard — all already expect this shape, so nothing downstream needs to change).

LIVE-VERIFIED 2026-10-18 directly against the real board (`board_stream.iter_board_rows`,
    `docs/listings.json.gz`), not assumed: 20,399 rows currently carry
    `raw['nc_ptscloud_delinquent_tax']` across 9 tenants (Forsyth 5,326, Guilford 3,535,
    Beaufort 3,443, Pitt 1,933, Henderson 1,601, Madison 1,358, Hyde 1,840, Orange 1,357,
    Cleveland 6). Of those, 8,618 already carry >=2 distinct `years_unpaid` AND at least one
    matured (`years_delinquent`>=1) year on their EXISTING `nc_ptscloud_delinquent_tax` block —
    i.e. would qualify for this module's gate the moment it runs, with zero new fetches.
    (Guilford is excluded from this session's target list — another concurrent agent's county —
    but is not excluded from this module's logic: it is the same source, same shape, and
    skipping it would mean re-deriving the same block differently later for no reason. Noted
    here rather than silently included.)

GATE (matches Gaston's enrichment and the generic scraper's own MIN_YEARS/matured-year rule
    exactly, so a downstream consumer sees one consistent contract regardless of producer):
    at least MIN_YEARS (2) distinct unpaid tax years, AND at least one of them past its
    statutory delinquent date (`tax_calendar.completed_delinquent_years`) — a parcel whose only
    "unpaid years" are this year's not-yet-due current bill plus nothing else does not qualify.

PER-YEAR AMOUNT. Each `by_year` entry's `total_due` is that one tax year's own unpaid amount
    (principal + interest for that year's bill, per `_bill_entry`) — the same "one row per levy
    year, each row its own bill" shape Buncombe's layers have, so `amount_basis` here is
    "annual_bill" (not Oconee/Pickens' "advertised_balance"). A parcel occasionally carries two
    distinct CSV rows for the same tax year (a corrected/supplemental bill); per_year keeps the
    LARGER of the two rather than summing, mirroring `scrapers.counties_generic.
    multi_year_delinquent_tax.build_listing`'s own documented reasoning for the identical case.

NOT A NEW SOURCE, NOT COUNTY-RESTRICTED. Runs over every row carrying
    `raw['nc_ptscloud_delinquent_tax']`, whichever tenant produced it — the gate above is what
    decides eligibility, not a county allowlist, so a 10th tenant `nc_ptscloud_delinquent_tax.py`
    picks up later needs no change here. Idempotent: a row that already carries
    `raw['multi_year_delinquent_tax']` (from this module on a prior run, or in principle from a
    different county-specific producer) is left untouched rather than overwritten.

PRIVACY. Reads only fields `nc_ptscloud_delinquent_tax` already carries on the row (parcel id,
    tax years, dollar amounts); no new field, no name or mailing address touched.

Gate off entirely with FORECLOSURE_PTSCLOUD_MYDT=0.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Iterable, Optional

import structlog

from . import tax_calendar
from .models import Listing, _normalize_parcel
from .scrapers.counties_generic.multi_year_delinquent_tax import _longest_run, _trend

log = structlog.get_logger()

RAW_KEY = "multi_year_delinquent_tax"
SOURCE_KEY = "nc_ptscloud_delinquent_tax"

ENABLED = os.environ.get("FORECLOSURE_PTSCLOUD_MYDT") != "0"
MIN_YEARS = int(os.environ.get("PTSCLOUD_MYDT_MIN_YEARS", "2"))

BASE_URL = "https://bcpwa.ncptscloud.com"


def _already_done(li: Listing) -> bool:
    return isinstance(li.raw, dict) and isinstance(li.raw.get(RAW_KEY), dict)


def build_block(parcel_id: Optional[str], state: Optional[str], county: Optional[str],
                by_year: list[dict], tenant: Optional[str], *,
                today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from one board row's own
    raw['nc_ptscloud_delinquent_tax']['by_year'] list, or None when the parcel doesn't clear the
    multi-year gate (fewer than MIN_YEARS distinct unpaid tax years, or no MATURED one)."""
    today = today or date.today()
    per_year: dict[int, float] = {}
    for entry in by_year or ():
        year = tax_calendar.levy_year(entry.get("tax_year"))
        amount = entry.get("total_due")
        if year is None or not isinstance(amount, (int, float)) or amount <= 0:
            continue
        prev = per_year.get(year)
        per_year[year] = amount if prev is None else max(prev, amount)
    years = sorted(per_year)
    if len(years) < MIN_YEARS:
        return None
    matured = tax_calendar.completed_delinquent_years(years, state, county, today)
    if not matured:
        return None
    current = [y for y in years if y not in matured]
    total_owed = round(sum(per_year.values()), 2) or None
    matured_owed = round(sum(per_year[y] for y in matured), 2) or None
    county_latest_year = years[-1]
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
        "year": years[-1],
        "trend": _trend(per_year, matured),
        "still_accruing": years[-1] >= county_latest_year,
        "amount_basis": "annual_bill",
        "layers": ["nc_ptscloud_billpwa_payment_history"],
        "parcel_key": _normalize_parcel(parcel_id),
        "tenant": tenant,
        "source_url": f"{BASE_URL}/{tenant}/bill-search" if tenant else BASE_URL,
    }


def enrich_ptscloud_multiyear_tax(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every board row already carrying raw['nc_ptscloud_delinquent_tax'] and restate its
    per-year history into raw['multi_year_delinquent_tax'] when it clears the multi-year gate.
    Pure, no network, no cap needed — the source data is already on the row."""
    stats = {"eligible": 0, "qualified": 0, "insufficient_history": 0}
    if not ENABLED:
        return stats
    today = date.today()
    for li in listings:
        if not isinstance(li.raw, dict):
            continue
        src = li.raw.get(SOURCE_KEY)
        if not isinstance(src, dict) or _already_done(li):
            continue
        stats["eligible"] += 1
        block = build_block(li.parcel_id, li.state, li.county,
                            src.get("by_year") or [], src.get("tenant"), today=today)
        if block is None:
            stats["insufficient_history"] += 1
            continue
        li.raw[RAW_KEY] = block
        stats["qualified"] += 1
    log.info("ptscloud_mydt.done", **stats)
    return stats
