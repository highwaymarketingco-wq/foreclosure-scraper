"""Berkeley County SC paystar.io delinquent roll -- a REALIZED ag-use rollback tax bill,
restated into the shared raw['rollback_exposure'] contract gap_matrix.py's own
checked_columns()/positive_columns() already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-20.csv, read before writing a line here).
    rollback_exposure shows sourced-not-built for SC Berkeley (3,012 applicable), source
    "tax/property card: berkeleycountysc.paystar.io", next_action "add a tax-roll reader".

    NOT THE SAME SHAPE AS THIS FAMILY'S OTHER PRODUCERS, CHECKED LIVE, NOT ASSUMED. Every
    existing rollback_exposure producer (enrichment_rollback_deferral.py's Buncombe/Wake/
    Mecklenburg sections, enrichment_harnett_rollback_exposure.py,
    enrichment_transylvania_rollback_exposure.py) reads a PROSPECTIVE present-use VALUE still
    sitting on the parcel ("Deferred"/"Total Deferred Value") -- the dollar gap between fair-
    market and special-use value that WOULD come due if the use changes. Berkeley's paystar
    tenant has NO such field anywhere in its assetMetaJson (live-checked 2026-10-20 against
    600 real invoices' full key set: QRLandValue/OTLandValue/AgLandValue and their Building
    twins are each class's CURRENT value, never a deferred/differential figure). That is a
    genuine dead end for the prospective shape -- reported, not built around.

    What paystar DOES carry, confirmed live against real invoices (081-00-00-141 and 4 more,
    2026-10-20): RollbackCode=="R" with RollbackInformation=="ROLLBACK TAXES" and a real
    RollbackUseChangeYear (e.g. "2025") on an invoice whose RollbackDesc is a literal permit/
    construction trigger ("MH40093", "MH SETUP", "NEW SFR" -- South Carolina's rollback trigger
    IS a structure going up on previously ag-valued land, SC Code 12-43-220(d)(4)). This is not
    a forward-looking estimate -- it is the county's OWN REALIZED rollback bill, already
    assessed and (being on this UNPAID roll at all) still unpaid. Sampled 2026-10-20: 25 of 600
    real invoices (4.2%) carried RollbackCode=="R"; 0 of 20 other Rollback* field values ever
    appeared outside that one code, so "R" is read as the sole positive signal, nothing
    inferred from a blank code.

    raw['berkeley_paystar_tax'] already captures rollback_code/rollback_description
    unconditionally once non-blank (counties_sc/berkeley_paystar_tax.py's _BILL_TEXT, pre-
    existing before this session) -- a board row scraped since that field was added already
    carries them without any new network call. rollback_use_change_year and
    rollback_information are newly captured by this session's scraper fix (same file,
    2026-10-20) and are therefore ABSENT from any row scraped before today; this module still
    fires on rollback_code alone (the one confirmed positive signal) and merely enriches the
    block with the newer fields when present.

    Board state measured live 2026-10-20 (board_stream.iter_board_rows, read-only, no write):
    0 of the board's 2,211 Berkeley paystar rows currently carry rollback_code=="R" -- the
    board's cached Berkeley data predates real rollback hits reaching it (a stale-cache gap,
    not a false "it doesn't exist" reading: the live API confirms real hits today). This module
    will fire the moment those rows are re-scraped; it does nothing against the board's current
    cache (reported, not hidden).

GATE. county=='Berkeley' (not just the source key's presence -- same cross-contamination
    guard as this county's sibling enrichers). rollback_code must equal the one confirmed
    positive value "R" exactly; a row already carrying raw['rollback_exposure'] is untouched.

HONESTY OF SHAPE. basis is "realized_rollback_bill", not "present_use_deferral" (this family's
    prospective basis) -- amount_due is the bill ALREADY ISSUED and unpaid (this row's own
    raw['berkeley_paystar_tax']['total_due']/['latest_invoice_total_due']), not an estimate of
    what a FUTURE sale would trigger. No deferred_value/estimated_rollback field is invented;
    this county's source does not expose the number those fields would need.

Pure, no network, no cap needed -- the source data is already on the row.
Gate off entirely with FORECLOSURE_BERKELEY_ROLLBACK=0.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

import structlog

from .models import Listing

log = structlog.get_logger()

RAW_KEY = "rollback_exposure"
SOURCE_KEY = "berkeley_paystar_tax"
SOURCE_SLUG = "counties_sc.berkeley_paystar_tax"
_POSITIVE_CODE = "R"


def _already_done(raw: dict) -> bool:
    return isinstance(raw.get(RAW_KEY), dict)


ENABLED = os.environ.get("FORECLOSURE_BERKELEY_ROLLBACK") != "0"


def build_rollback_block(blk: dict) -> dict | None:
    """Pure: the raw['rollback_exposure'] record from one board row's own
    raw['berkeley_paystar_tax'], or None when rollback_code isn't the one confirmed positive
    value ("R")."""
    code = str(blk.get("rollback_code") or "").strip()
    if code != _POSITIVE_CODE:
        return None
    amount = blk.get("latest_invoice_total_due", blk.get("total_due"))
    try:
        amount = round(float(amount), 2) if amount is not None else None
    except (TypeError, ValueError):
        amount = None
    rec: dict[str, Any] = {
        "basis": "realized_rollback_bill",
        "rollback_code": code,
        "county": "Berkeley",
        "state": "SC",
        "source": 'berkeleycountysc.paystar.io invoice detail ("RollbackCode"/"RollbackInformation")',
        "source_key": SOURCE_KEY,
        "estimate_is_floor": False,   # this is the actual issued bill, not an estimate
    }
    if amount:
        rec["amount_due"] = amount
    trigger = blk.get("rollback_description")
    if trigger:
        rec["trigger"] = trigger
    info = blk.get("rollback_information")
    if info:
        rec["rollback_information"] = info
    use_change_year = blk.get("rollback_use_change_year")
    if use_change_year:
        rec["use_change_year"] = use_change_year
    tax_year = blk.get("tax_year")
    if tax_year:
        rec["tax_year"] = tax_year
    return rec


def enrich_berkeley_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every board row already carrying raw['berkeley_paystar_tax'] and restate a
    confirmed rollback_code=='R' reading into raw['rollback_exposure']. Pure, no network, no
    cap needed -- the source data is already on the row."""
    stats = {"eligible": 0, "written": 0, "skipped_wrong_county": 0, "no_rollback": 0}
    if not ENABLED:
        return stats
    for li in listings:
        raw = li.raw
        if not isinstance(raw, dict):
            continue
        blk = raw.get(SOURCE_KEY)
        if not isinstance(blk, dict) or _already_done(raw):
            continue
        if (li.county or "").strip().lower() != "berkeley":
            stats["skipped_wrong_county"] += 1
            continue
        stats["eligible"] += 1
        block = build_rollback_block(blk)
        if block is None:
            stats["no_rollback"] += 1
            continue
        raw[RAW_KEY] = block
        stats["written"] += 1
    log.info("berkeley_rollback.done", **stats)
    return stats
