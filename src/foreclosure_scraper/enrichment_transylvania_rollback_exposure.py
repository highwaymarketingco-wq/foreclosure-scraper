"""Transylvania NC "Deferred Value" restatement — a pure, no-network bridge from data this
project already collects into the shared raw['rollback_exposure'] contract
enrichment_rollback_deferral.py established and gap_matrix.py's own checked_columns()/
positive_columns() already read.

WHY THIS EXISTS (gap_list_2026-10-19.csv, filtered column==rollback_exposure AND
    gap_class==sourced-not-built, read before writing a line here). Transylvania shows
    12,457 applicable, source "tax/property card: tax.transylvaniacounty.org", built=no — the
    second-largest cell in that filtered list. The next_action guesses a brand-new reader is
    needed, but one already exists and already runs every pipeline pass:
    scrapers/counties_nc/transylvania_delinquent_tax.py's `parse_view_tax_bill()` already reads
    a labelled "Deferred Value :" line off the county's own ViewTaxBill detail page (the SAME
    per-bill detail fetch that scraper already makes for the delinquent-tax lead itself — no new
    request) and already stores it, unrestated, as `raw['transylvania_tax']['deferred_value']`.
    That module's own 2026-10-03 extraction-audit comment names this field explicitly:
    "'Deferred Value :' (present-use-value deferral, e.g. agricultural land) ... were also
    dropped [until this audit]" — i.e. the SOURCE already identifies this as the exact present-
    use rollback signal this column exists for; it was only ever restated under the source's own
    private key, never under the shared one gap_matrix actually checks.

    LIVE-VERIFIED against the real board (board_stream, docs/listings.json.gz), 2026-10-19: 480
    rows carry `raw['transylvania_tax']`; 3 of them already have a real, positive
    `deferred_value` (461,410 / 81,500 / 241,210), none of the three with any `exemption` value
    set on the same row — i.e. the field is clean on the rows that have it, not a byproduct of a
    different (non-rollback) exemption mechanism riding along on the same bill.

    NOT THE SAME TRAP AS THE OTHER TWO ROLLBACK_EXPOSURE CANDIDATES INVESTIGATED THE SAME NIGHT
    (reported, not built, in the session's own notes): SC qPayBill's "Total Appraisal" / "Total
    Assessed" pair is one value split by a FIXED statutory ratio (4%/6%), not present use, and
    carries no separate use-value field at all (qpaybill_delinquent_roll.parse_detail()'s own
    field list, re-verified in code 2026-10-19). NC PTS Cloud's `ABSTRACT_ASSESS_VALUE` vs
    `ABSTRACT_TAXABLE_VALUE` pair (live-pulled CSV headers, 2026-10-19) DOES show a real gap on
    some rows, but with no reason/exclusion-type code anywhere in that export to tell a
    present-use ag/forestry deferral (rollback-eligible) apart from NC's elderly/disabled
    homestead EXCLUSION (permanent, $25,000-or-50%-of-value, G.S. 105-277.1 — NOT subject to
    rollback) or a disabled-veteran exclusion (G.S. 105-277.1C, also permanent) riding on the
    same two columns — several live examples showed an exact $25,000 gap, the signature of the
    elderly exclusion, mixed in with variable-percentage gaps that look like present use. Building
    a producer off that pair would misclassify a permanently-exempt row as rollback-liable, so it
    was correctly left unbuilt (see the task session's own report). Transylvania's field is
    different in kind: it is the county's OWN labelled "Deferred Value" line, not an inferred
    difference between two generically-named value columns, so there is no such ambiguity to
    disambiguate.

GATE. Only a positive `deferred_value` qualifies — `build_block()` never invents one, matching
    `transylvania_delinquent_tax.parse_view_tax_bill()`'s own "only keys actually found" rule one
    level up.

RATE, NEVER ASSUMED. Same convention enrichment_rollback_deferral.py's Buncombe and Wake sections
    already use: the effective combined tax rate is DERIVED per parcel from that parcel's own
    numbers (its newest bill's own single-year `original_levy`, divided by its own
    `net_taxable_valuation`), never a hard-coded millage, and only kept when it lands inside the
    same sane band (`_RATE_MIN`/`_RATE_MAX`, imported from enrichment_rollback_deferral.py rather
    than re-declared) those sections already validate against. `bills[0]` (not the block's own
    top-level `original_levy`, which `transylvania_delinquent_tax.build_listing()` documents as
    SUMMED across every delinquent year read) is used deliberately: it is the one bill whose year
    matches the ViewTaxBill detail page `net_taxable_valuation` was read from, so a multi-year-
    delinquent parcel's levy is never divided by a value from a different year than it belongs to.
    A parcel whose rate doesn't land in the sane band (or has no net_taxable_valuation/levy at
    all) still gets its real `deferred_value`, just without a derived annual/estimated-rollback
    figure — "no rate is ever assumed" holds even when the usual derivation is unavailable, same
    as every sibling section of enrichment_rollback_deferral.py.

Pure, no network, no cap needed — the source data is already on the row. Idempotent: a row that
already carries `raw['rollback_exposure']` (from this module on a prior run, or in principle
because it also somehow matched Buncombe/Anderson/Mecklenburg/Wake, which it cannot given county
is exclusive) is left untouched. Gate off entirely with FORECLOSURE_TRANSYLVANIA_ROLLBACK=0.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional

import structlog

from .enrichment_rollback_deferral import _RATE_MAX, _RATE_MIN
from .models import Listing

log = structlog.get_logger()

RAW_KEY = "rollback_exposure"
SOURCE_KEY = "transylvania_tax"
ROLLBACK_YEARS_NC = 4  # G.S. 105-277.4(c) — see enrichment_rollback_deferral.py's module docstring

ENABLED = os.environ.get("FORECLOSURE_TRANSYLVANIA_ROLLBACK") != "0"


def _already_done(raw: dict) -> bool:
    return isinstance(raw.get(RAW_KEY), dict)


def _positive(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def build_block(blk: dict) -> Optional[dict]:
    """Pure: the raw['rollback_exposure'] record from one board row's own
    raw['transylvania_tax'], or None when its own 'Deferred Value :' line (deferred_value) is
    blank/zero — never invented."""
    deferred = _positive(blk.get("deferred_value"))
    if deferred is None:
        return None

    rec: dict[str, Any] = {
        "deferred_value": round(deferred, 2),
        "basis": "present_use_deferral",
        "county": "Transylvania",
        "state": "NC",
        "source": 'Transylvania County Tax Bill Search, ViewTaxBill detail ("Deferred Value :")',
        "source_key": SOURCE_KEY,
        "rollback_years": ROLLBACK_YEARS_NC,
        "estimate_is_floor": True,       # statutory interest not modelled
        "match_method": "parcel",
    }
    if blk.get("tax_year"):
        rec["tax_year"] = blk["tax_year"]

    net_taxable = _positive(blk.get("net_taxable_valuation"))
    bills = blk.get("bills") or []
    head_levy = _positive(bills[0].get("original_levy")) if bills and isinstance(bills[0], dict) else None
    if net_taxable and head_levy:
        rate = head_levy / net_taxable
        if _RATE_MIN <= rate <= _RATE_MAX:
            annual = round(deferred * rate, 2)
            rec.update(
                effective_tax_rate=round(rate, 6),
                tax_rate_source="parcel_bill",
                annual_deferred_tax=annual,
                estimated_rollback=round(annual * ROLLBACK_YEARS_NC, 2),
            )
    return rec


def enrich_transylvania_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every board row already carrying raw['transylvania_tax'] and restate its own
    'Deferred Value' into raw['rollback_exposure'] when positive. Pure, no network, no cap
    needed — the source data is already on the row."""
    stats = {"eligible": 0, "matched": 0, "no_deferral": 0, "with_estimate": 0}
    if not ENABLED:
        return stats
    for li in listings:
        raw = li.raw
        if not isinstance(raw, dict):
            continue
        blk = raw.get(SOURCE_KEY)
        if not isinstance(blk, dict) or _already_done(raw):
            continue
        stats["eligible"] += 1
        rec = build_block(blk)
        if rec is None:
            stats["no_deferral"] += 1
            continue
        raw[RAW_KEY] = rec
        stats["matched"] += 1
        if rec.get("estimated_rollback"):
            stats["with_estimate"] += 1
    log.info("transylvania_rollback.done", **stats)
    return stats
