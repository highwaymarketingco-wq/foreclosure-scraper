"""NC "ITSPublic" tax-bill portal (BT TaxPayer Portal family) multi-year delinquent-tax
HISTORY — restate data this project already collects into the one shared contract key the gap
matrix actually credits.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-18.csv, read before writing a line here).
    "multi_year_delinquent_tax" shows sourced-not-built, hits=0, built=no for Duplin (3,519
    applicable) with next_action "add a tax-roll reader for tax/property card:
    www.bttaxpayerportal.com" — but that reader already exists and is already wired into
    main.py: scrapers.counties_nc.nc_its_public_tax.PORTALS has had a "Duplin" entry
    (ITSPublicDL, full_model=True) since 2026-10-09, and the SAME gap CSV's own rows for
    Duplin's two_year_delinquent / repeat_tax_loss / tax_aging_surfaced columns already show
    built-but-low-yield, ran=True, hits=2,902 of 3,519 (82%) against that exact producer. The
    real gap is identical in shape to last night's Gaston/PTS-Cloud precedents
    (project_tax_roll_reader_workflow_2026-10-18.md, enrichment_gaston_multiyear_tax.py,
    enrichment_ptscloud_multiyear_tax.py): an upstream source already reads the full per-year
    bill history and already restates two_year_delinquent/tax_owed from it, but nothing ever
    restates it under the ONE raw key gap_matrix.checked_columns() reads for this specific
    column (`raw.get("multi_year_delinquent_tax")`, scripts/gap_matrix.py line ~1150).

    LIVE-RECONFIRMED 2026-10-18 directly against the real portal (not assumed): GET
    https://www.bttaxpayerportal.com/ITSPublicDL/TaxBillSearch -> 200, title "Tax Bill Search";
    POST .../GetSearchTablePartial/ + .../GetSearchTableData (TaxYear=2024, UnpaidBillsOnly)
    -> a real jqGrid answer, 3,978 unpaid 2024 records / 40 pages. This is the SAME
    TaxBillSearch sub-app Onslow/Graham/Harnett/Transylvania/Catawba already read on this
    vendor — a genuinely different sub-app from the "AppraisalCard"/"BasicSearch" CAMA product
    enrichment_bt_parcel_info.py's own docstring correctly found carries no tax-payment data at
    all (that finding does not generalize to every bttaxpayerportal.com cell: the HOST is
    multi-tenant and multi-product, and Duplin's ITSPublicDL tenant happens to expose BOTH
    products under the one host).

WHERE THE DATA ALREADY LIVES. scrapers.counties_nc.nc_its_public_tax.aggregate() already walks
    every matched parcel's own multi-year bill set (`by_parcel`, one list of `{year, bill,
    balance, original_levy, status}` dicts per parcel across every year its county budget read)
    and folds it down into raw['nc_its_public_tax']['bills'] / ['years'] / ['total_due'] — the
    full multi-year depth is read and kept, just under that source's OWN raw key, not the
    shared one. This module is a pure, no-network transform that walks already-collected board
    rows and restates `bills`/`years` into raw['multi_year_delinquent_tax'] in the exact
    byte-shape Gaston's and PTS-Cloud's enrichments already produce
    (tax_binding.BLOCK_PARCEL_FIELDS["multi_year_delinquent_tax"] = ("parcel_key",),
    enrichment_tax_owed._SOURCES's exact-key read of "total_due", web_artifact.RAW_KEEP's "*"
    wildcard — all already expect this shape, so nothing downstream needs to change).

GATE (matches Gaston's and PTS-Cloud's enrichments exactly, so a downstream consumer sees one
    consistent contract regardless of producer): at least MIN_YEARS (2) distinct unpaid tax
    years, AND at least one of them past its statutory delinquent date
    (tax_calendar.completed_delinquent_years). In practice every year nc_its_public_tax.py ever
    requests is already past that date by construction (its own delinquent_years() only ever
    asks for years at or before today.year - 1, never the current not-yet-due levy) — the
    explicit matured check is kept anyway for the same reason enrichment_ptscloud_multiyear_tax
    keeps it: a future change to that scraper's year window must not silently start crediting a
    current, not-yet-late bill as "matured" here too.

NOT A NEW SOURCE, NOT COUNTY-RESTRICTED. Runs over every row carrying
    raw['nc_its_public_tax'], whichever of the 12 PORTALS counties produced it (Onslow, Graham,
    Alleghany, Anson, Caswell, Duplin, Granville, Harnett, Jones, Person, Scotland, Yadkin) —
    the gate above is what decides eligibility, not a county allowlist, matching
    enrichment_ptscloud_multiyear_tax's own "not county-restricted" convention. This session's
    task was scoped to Duplin specifically and every live check above was run against Duplin's
    own tenant; the fix is the same shape for every sibling county on this one scraper, so it is
    not special-cased to avoid re-deriving the identical block differently later for no reason.
    Idempotent: a row that already carries raw['multi_year_delinquent_tax'] (from a prior run of
    this module, or in principle from a different county-specific producer) is left untouched.

rollback_exposure is NOT addressed here and is not buildable from this source: TaxBillSearch is
    a payment/billing portal (bill number, balance, status) with no market-vs-use valuation
    field anywhere in its rows — the same structural reason last night's Spartanburg agent
    correctly declined rollback_exposure against qPayBill. See the task report for the full
    reasoning; no code was written for it.

PRIVACY. Reads only fields raw['nc_its_public_tax'] already carries on the row (parcel id, bill
    years, dollar amounts); no new field, no name or mailing address touched.

Gate off entirely with FORECLOSURE_ITS_PUBLIC_MYDT=0.
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
SOURCE_KEY = "nc_its_public_tax"

ENABLED = os.environ.get("FORECLOSURE_ITS_PUBLIC_MYDT") != "0"
MIN_YEARS = int(os.environ.get("ITS_PUBLIC_MYDT_MIN_YEARS", "2"))


def _already_done(li: Listing) -> bool:
    return isinstance(li.raw, dict) and isinstance(li.raw.get(RAW_KEY), dict)


def build_block(parcel_id: Optional[str], state: Optional[str], county: Optional[str],
                source_block: dict, *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from one board row's own
    raw['nc_its_public_tax']['bills'] list, or None when the parcel doesn't clear the
    multi-year gate (fewer than MIN_YEARS distinct unpaid tax years, or no MATURED one)."""
    today = today or date.today()
    per_year: dict[int, float] = {}
    for bill in source_block.get("bills") or ():
        year = tax_calendar.levy_year(bill.get("year"))
        amount = bill.get("balance")
        if year is None or not isinstance(amount, (int, float)) or amount <= 0:
            continue
        prev = per_year.get(year)
        # a parcel occasionally carries two bills for the same tax year (a corrected/
        # supplemental bill) -- keep the LARGER, same convention as enrichment_ptscloud_
        # multiyear_tax and scrapers.counties_generic.multi_year_delinquent_tax.build_listing.
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
        "layers": ["nc_its_public_tax_bill_search"],
        "parcel_key": _normalize_parcel(parcel_id),
        "portal": source_block.get("portal"),
        "source_url": f"{source_block['portal']}/TaxBillSearch" if source_block.get("portal") else None,
    }


def enrich_its_public_multiyear_tax(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every board row already carrying raw['nc_its_public_tax'] and restate its per-year
    history into raw['multi_year_delinquent_tax'] when it clears the multi-year gate. Pure, no
    network, no cap needed -- the source data is already on the row."""
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
        block = build_block(li.parcel_id, li.state, li.county, src, today=today)
        if block is None:
            stats["insufficient_history"] += 1
            continue
        li.raw[RAW_KEY] = block
        stats["qualified"] += 1
    log.info("its_public_mydt.done", **stats)
    return stats
