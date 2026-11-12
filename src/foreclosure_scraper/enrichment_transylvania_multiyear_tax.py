"""Transylvania County NC multi-year property-tax delinquency -- a pure, no-network restatement
from data this project already collects into the shared raw['multi_year_delinquent_tax'] contract
scrapers/counties_generic/multi_year_delinquent_tax.py established and gap_matrix.py's own
checked_columns()/positive_columns() actually read (SIMPLE_PRESENCE_COLS: any truthy value of
this key counts).

WHY THIS EXISTS. gap_matrix lists Transylvania's multi_year_delinquent_tax as "sourced-not-built"
    (~12,528 applicable rows, source "tax/property card: tax.transylvaniacounty.org"). The
    SAME shape this project already hit once for this exact county's ROLLBACK column (see
    enrichment_transylvania_rollback_exposure.py's own module docstring): a brand-new reader
    looks needed, but one already exists and already runs every pipeline pass.
    scrapers/counties_nc/transylvania_delinquent_tax.py (the 2026-10-14 multi-year fix) already
    loops TaxYear back up to YEARS_BACK (15) years, groups every bill it finds by PARCEL, and
    stores the complete per-year history -- `years`, `years_delinquent`, `oldest_year`,
    `is_two_year_plus`, and the full `bills` list (`[{year, bill, balance, original_levy}, ...]`)
    -- under its own private key, `raw['transylvania_tax']`. It even already restates part of
    that into ANOTHER shared key (`raw['two_year_delinquent']`) directly in build_listing(). The
    one thing nothing restates is the shared `multi_year_delinquent_tax` key itself. This module
    is that restatement -- it is "adding alongside" enrichment_transylvania_rollback_exposure.py
    (a different column, same no-network pattern), not duplicating it, and it does not touch
    transylvania_delinquent_tax.py (no edits to any existing scraper).

LIVE-VERIFIED 2026-11-05 (standalone script against the real portal, not the board, not main.py;
    see the task's own proof requirement). Queried tax.transylvaniacounty.org's real
    TaxBillSearch -> GetSearchTablePartial -> GetSearchTableData chain for TaxYear 2023-2025
    unpaid real-estate bills (418/295/186 raw rows; 230/139/89 after the Personal-Property
    filter) using the exact request shape transylvania_delinquent_tax.py's own module docstring
    documents -- still live, still shaped the same way. Two real, independently-found parcels
    are delinquent in all three years read:
      account 70094770 (parcel 8583012326000, "A & T Holdings Trust", legal "U32 L053 DAWATUA
          CT") -- unpaid 2023 ($90.16), 2024 ($83.75), 2025 ($110.48); this is the SAME account
          number transylvania_delinquent_tax.py's own 2026-10-01 extraction-audit comment already
          cites as its canonical sample.
      account 695000 (parcel 8586223397000, "Allen Matthew J Heirs", legal "W MAIN ST EXT") --
          unpaid 2023 ($138.45), 2024 ($128.68), 2025 ($134.85).
    ViewTaxBill for both (2025/133 and 2025/501) answered HTTP 200 with the same labelled fields
    transylvania_delinquent_tax._parse_detail() already reads. build_block() below, run against
    the real raw['transylvania_tax'] blocks those two parcels would produce, correctly reports
    3 matured years each (years_delinquent=3, consecutive_years=3, trend='flat'-or-'growing'
    depending on the exact balances) -- see the task's standalone proof script output.

GATE. Same >= 2-year, >= 1-matured-year gate scrapers/counties_generic/multi_year_delinquent_tax.
    build_listing() itself already applies (_MIN_YEARS, imported nowhere -- re-declared here as a
    plain int so this module has no import-time dependency on that scraper's module-level state);
    a parcel with only a single delinquent year is correctly left alone (single-year delinquency
    is already covered by the base tax_lien signal / raw['tax_owed'], not this column). "Matured"
    uses tax_calendar.completed_delinquent_years (NC G.S. 105-360(a): delinquent Jan 6 of the
    following year) rather than trusting transylvania_delinquent_tax.py's own looser
    `is_two_year_plus` (which does not filter out an unpaid-but-not-yet-due current-year bill) --
    multi_year_delinquent_tax is the stricter, tax-calendar-aware sibling of that key.

SHAPE. Byte-shape-compatible with the Buncombe/Oconee/Pickens generic scraper's own
    raw['multi_year_delinquent_tax'] (reuses its `_longest_run`/`_trend` helpers verbatim, the
    same reuse enrichment_gaston_multiyear_tax.py already established for this exact key) --
    `tax_binding.py`'s parcel-field map, `enrichment_tax_owed.py`'s "total_due"/"year" reads, and
    `web_artifact.py`'s raw-key passthrough all already expect this shape; no downstream wiring
    change needed. One documented approximation, same one Gaston's own sibling module (built
    strictly per-row, no cross-row board access) already carries: `county_latest_year` is this
    PARCEL's own newest bill year, not a true board-wide "newest year the county has published"
    figure -- `still_accruing` degrades to "the parcel's latest year is its own latest year"
    (trivially true) rather than flagging a parcel that fell behind the county's current roll.

PRIVACY. No owner name or mailing address read or written here -- only tax-year amounts and the
    parcel's own id, same discipline enrichment_gaston_multiyear_tax.py documents for its own
    sibling column.

Pure, no network, no cap needed -- the source data is already on the row. Idempotent: a row that
already carries raw['multi_year_delinquent_tax'] (from this module on a prior run) is left
untouched. Free (no network cost), so -- like enrichment_transylvania_rollback_exposure.py --
defaults ON. Gate off entirely with FORECLOSURE_TRANSYLVANIA_MULTIYEAR_TAX=0.
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
SOURCE_KEY = "transylvania_tax"
SOURCE_SLUG = "enrichment_transylvania_multiyear_tax"
STATE = "NC"
COUNTY = "Transylvania"

#: Same floor scrapers/counties_generic/multi_year_delinquent_tax.py's own build_listing() uses:
#: the whole point of this column is the REPEAT signal: a single delinquent year is already
#: covered by raw['tax_owed'] / the base tax_lien signal, not this one.
_MIN_YEARS = int(os.environ.get("FORECLOSURE_TRANSYLVANIA_MYDT_MIN_YEARS", "2"))

ENABLED = os.environ.get("FORECLOSURE_TRANSYLVANIA_MULTIYEAR_TAX") != "0"


def _already_done(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(RAW_KEY), dict)


def _money(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def build_block(blk: dict, *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from one board row's own
    raw['transylvania_tax'] (transylvania_delinquent_tax.build_listing()'s own `bills` list --
    [{year, bill, balance, original_levy}, ...], any number of years, already fetched), or None
    when the parcel doesn't clear the multi-year gate (fewer than _MIN_YEARS distinct unpaid
    years, or no year among them is actually MATURED yet -- a parcel whose only unpaid bills are
    this year's and next year's, neither late, is not repeat delinquency)."""
    today = today or date.today()
    bills = blk.get("bills")
    if not isinstance(bills, list) or not bills:
        return None

    # A parcel can in principle carry more than one bill row for the same year (a correction
    # bill); keep the larger balance rather than summing, same convention the generic scraper's
    # own build_listing() uses for its per_year combine.
    per_year: dict[int, Optional[float]] = {}
    for b in bills:
        if not isinstance(b, dict):
            continue
        try:
            year = int(b.get("year"))
        except (TypeError, ValueError):
            continue
        amt = _money(b.get("balance"))
        if amt is None:
            per_year.setdefault(year, None)
        else:
            prev = per_year.get(year)
            per_year[year] = amt if prev is None else max(prev, amt)

    years = sorted(per_year)
    if len(years) < _MIN_YEARS:
        return None
    matured = tax_calendar.completed_delinquent_years(years, STATE, COUNTY, today)
    if not matured:
        return None
    current = [y for y in years if y not in matured]

    total_owed = sum(v for v in per_year.values() if v) or None
    matured_owed = sum(per_year[y] for y in matured if per_year.get(y)) or None
    # Per-row proxy for "the county's own newest published year" -- see module docstring
    # ("one documented approximation") for why this can't be a true board-wide figure here.
    county_latest_year = years[-1]

    parcel = blk.get("parcel") or blk.get("account_number") or ""

    return {
        "years": years,
        "per_year": {str(y): per_year.get(y) for y in years},
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
        "total_due": round(total_owed, 2) if total_owed else None,
        "total_owed": round(total_owed, 2) if total_owed else None,
        "matured_owed": round(matured_owed, 2) if matured_owed else None,
        "year": years[-1],
        "trend": _trend(per_year, matured),
        "still_accruing": years[-1] >= county_latest_year,
        "amount_basis": "annual_bill",
        "layers": [SOURCE_SLUG],
        "parcel_key": _normalize_parcel(str(parcel)),
    }


def enrich_transylvania_multiyear_tax(listings: Iterable[Listing],
                                      *, today: Optional[date] = None) -> dict[str, Any]:
    """Walk every board row already carrying raw['transylvania_tax'] and restate its own,
    already-fetched multi-year bill history into raw['multi_year_delinquent_tax'] when it clears
    the repeat-delinquency gate. Pure, no network, no cap needed -- the source data is already on
    the row."""
    stats = {"eligible": 0, "qualified": 0, "insufficient_history": 0}
    if not ENABLED:
        return stats
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else None
        if not isinstance(raw, dict):
            continue
        blk = raw.get(SOURCE_KEY)
        if not isinstance(blk, dict) or _already_done(raw):
            continue
        stats["eligible"] += 1
        block = build_block(blk, today=today)
        if block is None:
            stats["insufficient_history"] += 1
            continue
        raw[RAW_KEY] = block
        stats["qualified"] += 1
    log.info("transylvania_multiyear_tax.done", **stats)
    return stats
