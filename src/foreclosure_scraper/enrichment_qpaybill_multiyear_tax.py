"""SC qPayBill (29-county treasurer payment portal) multi-year delinquent-tax HISTORY — a pure,
no-network restatement of data this project already collects into the two shared contract keys
the gap matrix actually credits: raw['multi_year_delinquent_tax'] and raw['two_year_delinquent'].

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-18.csv, read before writing a line here).
    "multi_year_delinquent_tax", "two_year_delinquent" and "rollback_exposure" all show
    sourced-not-built (or built-but-low-yield from a false-positive text match — see below) for
    SC Orangeburg (3,968 applicable), Horry (6,543), Sumter (4,274), Williamsburg (2,921) — the
    next_action column guesses "add a tax-roll reader for tax/property card:
    <county>treasurer.qpaybill.com". That reader already exists
    (scrapers/counties_sc/qpaybill_delinquent_roll.py, wired into main.py, 29 SC counties) and
    already runs on every one of these rows (confirmed live against docs/listings.json.gz,
    2026-10-18: Horry 1,548/6,543 rows carry raw['qpaybill_roll'], Williamsburg 2,637/2,921,
    Orangeburg 3,470/3,968, Sumter 3,697/4,274). The real gap is identical in SHAPE to last
    night's Gaston precedent (project_tax_roll_reader_workflow_2026-10-18.md /
    enrichment_gaston_multiyear_tax.py) and to this session's sibling fix for a different vendor
    (enrichment_ptscloud_multiyear_tax.py, NC PTS Cloud/BillPWA): an UPSTREAM source already
    reads the full multi-year bill history per row, but nothing ever restates it under the one
    raw key gap_matrix.checked_columns()/positive_columns() actually read for these two columns.

    _to_listings() in qpaybill_delinquent_roll.py (the portal returns one grid row per UNPAID
    YEAR) already aggregates every unpaid year onto raw['qpaybill_roll']: `years_unpaid` (the
    matured/late years only — `_delinquent_years()` already applies SC's Jan-15-of-next-year
    statutory rule, the exact same "late" filter `tax_calendar.completed_delinquent_years` /
    sc_catalis_delinquent_roll.py's own `completed_delinquent_years` call apply), `all_unpaid_years`
    (including a not-yet-due current-year bill), `years_delinquent` (len of the former) and
    `is_two_year_plus` (len(years_unpaid) >= 2) — the EXACT fields and EXACT boolean
    `two_year_delinquent` needs, just nested under qpaybill_roll instead of the shared key. This
    module restates them; it adds no new fetch, no new vendor integration, and does not touch
    qpaybill_delinquent_roll.py (whose own 13 test files this avoids putting at any risk).

    SEPARATE FALSE-POSITIVE FOUND, NOT RELIED ON OR FIXED HERE (reported, not touched):
    scripts/gap_matrix.py's built_in_code() textually greps each column's producer files for a
    quoted/slug county name. enrichment_tax_owed.py's FIELD_PRIORITY dict happens to carry the
    quoted keys "horry_delinquent_xlsx" and "sumter_delinquent_tax" (an unrelated field-priority
    table for the plain `tax_owed` amount, not this column) — their SLUGS contain "horry" and
    "sumter" immediately after a quote, which is exactly what the regex in _county_patterns()
    matches. That makes Horry/Sumter show built="code" -> gap_class "built-but-low-yield" for
    multi_year_delinquent_tax while Orangeburg/Williamsburg (not textually matched) show
    built="no" -> "sourced-not-built", even though NONE of the four had a real producer before
    this module — a cosmetic difference in gap_matrix's own heuristic, not a real difference in
    coverage. Left to whoever owns gap_matrix.py's text-matching heuristic; not in scope here.

GATE (matches Gaston's and ptscloud's enrichment exactly, so a downstream consumer sees one
    contract regardless of producer): raw['two_year_delinquent'] is written for EVERY row that
    carries raw['qpaybill_roll'] (even a single delinquent year — the wrapper's own
    `is_two_year_plus` states the truth either way, matching sc_catalis_delinquent_roll.py's
    unconditional write). raw['multi_year_delinquent_tax'] is written only when
    years_delinquent >= MIN_YEARS (2) — a single year's bill is not a "multi-year" claim.

PER-YEAR AMOUNT, HONESTLY SCOPED. qpaybill_roll's own raw key keeps only the TOTAL balance
    across a parcel's delinquent years (`balance_owed`), not a per-year split — the portal's grid
    returns one row per unpaid year with its own amount, but `_to_listings()` only persists the
    aggregate (module docstring there: "one Listing per PARCEL, with the unpaid years aggregated
    onto it"). Rebuilding a true per-year breakdown would mean changing that function's own raw
    shape, a file 13 test suites already pin — correctly out of scope for this module (the
    "reuse, don't duplicate" / "don't force a half-build" rule this session is run under). So,
    unlike Gaston/ptscloud's blocks, this one has no `per_year` dict and no `trend` field: naming
    a field this source cannot honestly state would be worse than leaving it out.
    `amount_basis` is therefore "aggregate_across_years", not "annual_bill" or
    "advertised_balance" — a distinct, honest label, not a copy of either sibling's.

ACCOUNT-ID COUNTIES: NO parcel_key, ON PURPOSE. Orangeburg's `identification_no` is an ACCOUNT
    number, not a parcel id (qpaybill_delinquent_roll.ACCOUNT_ID_ONLY = {"Orangeburg"}; its own
    rows already carry parcel_id=None for exactly this reason). tax_binding.py's own comment on
    BLOCK_PARCEL_FIELDS["qpaybill_roll"] already flags this and bind_block() already special-cases
    it for that one block name — but a NEW block name ("multi_year_delinquent_tax") gets no such
    special case for free, and tax_binding.BLOCK_PARCEL_FIELDS["multi_year_delinquent_tax"] =
    ("parcel_key",) would otherwise try to bind Orangeburg's account number as if it were a
    parcel id (the exact bug class project_tax_binding_bug_2026-10-08.md's "20,185 rows had
    another parcel's tax debt" finding was about). Fixed here at the source instead of touching
    tax_binding.py: this module never writes `parcel_key` when the source block is
    `is_account_id_not_parcel`, matching what qpaybill_delinquent_roll.py itself already does for
    `parcel_id`.

ROLLBACK_EXPOSURE: INVESTIGATED, CORRECTLY NOT BUILT (no file touched for it). Same question the
    Spartanburg agent answered live last night for this identical vendor family
    (project_tax_roll_reader_workflow_2026-10-18.md) — re-verified live here, 2026-10-18, against
    REAL Horry and Orangeburg parcels (qPayBill search -> detail-page fetch, same code path
    QPAYBILL_ROLL_DETAIL=1 already uses): the detail page's label set is
    (`Total Appraisal:`, `Total Assessed:`, `Assessment Ratio:`, `Land`/`Building Appraisal`,
    `Residential Exemption:`, `Homestead Exemption:`, tax breakdown lines) — parse_detail()'s own
    field list, confirmed exhaustive against the live markup for both counties. There is no
    separate present-use/market-value field anywhere on it: "Total Appraisal" IS the
    already-current, already-(if applicable)-use-reduced appraisal the bill is based on, the same
    finding Spartanburg's agent made. Because parse_detail() is one function shared verbatim by
    all 29 qpaybill counties (no per-county branching in its label set), this generalizes
    structurally to Sumter and Williamsburg too without a separate live check for each: the
    payment portal cannot expose the market-vs-use split rollback_exposure needs, full stop. SAME
    conclusion, SAME file-touched-count (zero) as the Spartanburg decision; not re-attempted here.

HEIR_ESTATE / VACANT_LOT: investigated, correctly not attempted here (reported, not built).
    heir_estate's only producers (scrapers/counties_nc/nc_heir_estate_parcels.py,
    .../henderson_foreclosure_parcels.py) are NC-only; there is no SC heir_estate producer at all
    to extend — building one would be a new scraper project, not an extension, and a different
    task than this one. vacant_lot's generic producer (enrichment_vacant_landuse.py) already
    reads parcel_cache for ANY county with a cached layer and DOES already resolve real rows for
    all three target SC counties here (parcel_cache.lookup confirmed live: Horry's board parcel
    id joins and returns land_use="311" — a raw numeric DOR use-code the vacant-text matcher
    (`_is_vacant_land_use`, which matches "VAC" abbreviation forms) can never recognize regardless
    of the parcel's real use; Sumter and Orangeburg's cached records carry no land_use field at
    all). Decoding Horry's numeric use-code legend, or checking whether Sumter/Orangeburg's own
    ArcGIS services even expose a land_use/use-code field, is real, separately scoped follow-up
    work — not attempted here given this column was this task's explicitly secondary target.

Gate off entirely with FORECLOSURE_QPAYBILL_MYDT=0.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional

import structlog

from .models import Listing, _normalize_parcel
from .scrapers.counties_generic.multi_year_delinquent_tax import _longest_run

log = structlog.get_logger()

MYDT_KEY = "multi_year_delinquent_tax"
TYD_KEY = "two_year_delinquent"
SOURCE_KEY = "qpaybill_roll"
SOURCE_SLUG = "counties_sc.qpaybill_delinquent_roll"

ENABLED = os.environ.get("FORECLOSURE_QPAYBILL_MYDT") != "0"
MIN_YEARS = int(os.environ.get("QPAYBILL_MYDT_MIN_YEARS", "2"))


def _already_done(raw: dict) -> bool:
    return isinstance(raw.get(MYDT_KEY), dict) and isinstance(raw.get(TYD_KEY), dict)


def build_two_year_block(qr: dict) -> dict:
    """Pure: the raw['two_year_delinquent'] wrapper, same shape sc_catalis_delinquent_roll.py's
    own unconditional write uses ('years' = a COUNT of late years, not a list)."""
    years_unpaid = qr.get("years_unpaid") or []
    oldest = None
    try:
        ints = sorted(int(y) for y in years_unpaid)
        oldest = ints[0] if ints else None
    except (TypeError, ValueError):
        oldest = None
    return {
        "is_two_year_plus": bool(qr.get("is_two_year_plus")),
        "years": int(qr.get("years_delinquent") or len(years_unpaid)),
        "oldest_year": oldest,
        "source": SOURCE_SLUG,
    }


def build_multiyear_block(qr: dict) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from one row's own
    raw['qpaybill_roll'], or None when it doesn't clear the multi-year gate (fewer than
    MIN_YEARS matured/late unpaid years). No `per_year`/`trend` (module docstring: the source
    keeps only the aggregate balance, not a per-year split) and no `parcel_key` when the
    identification_no is an account number, not a parcel id."""
    years_unpaid = qr.get("years_unpaid") or []
    try:
        years = sorted(int(y) for y in years_unpaid)
    except (TypeError, ValueError):
        return None
    if len(years) < MIN_YEARS:
        return None
    all_years = qr.get("all_unpaid_years") or years_unpaid
    total_due = qr.get("balance_owed")
    if not isinstance(total_due, (int, float)):
        total_due = None
    block: dict[str, Any] = {
        "years": years,
        "years_delinquent": int(qr.get("years_delinquent") or len(years)),
        "unpaid_bill_years": len(all_years),
        "consecutive_years": _longest_run(years),
        "first_year": years[0],
        "latest_year": years[-1],
        "year": years[-1],
        "total_due": total_due,
        "total_owed": total_due,
        "amount_basis": "aggregate_across_years",
        "layers": ["qpaybill_delinquent_roll"],
        "source": SOURCE_SLUG,
    }
    ident = qr.get("identification_no")
    if ident and not qr.get("is_account_id_not_parcel"):
        key = _normalize_parcel(str(ident))
        if len(key) >= 4 and len(set(key)) > 1:
            block["parcel_key"] = key
    return block


def enrich_qpaybill_multiyear_tax(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every board row already carrying raw['qpaybill_roll'] and restate its multi-year
    shape into raw['multi_year_delinquent_tax'] / raw['two_year_delinquent']. Pure, no network,
    no cap needed -- the source data is already on the row. Idempotent: a row that already
    carries both canonical keys (from a prior run of this module) is left untouched."""
    stats = {"eligible": 0, "two_year_written": 0, "multiyear_qualified": 0,
              "multiyear_insufficient_years": 0}
    if not ENABLED:
        return stats
    for li in listings:
        raw = li.raw
        if not isinstance(raw, dict):
            continue
        qr = raw.get(SOURCE_KEY)
        if not isinstance(qr, dict) or _already_done(raw):
            continue
        stats["eligible"] += 1
        if not isinstance(raw.get(TYD_KEY), dict):
            raw[TYD_KEY] = build_two_year_block(qr)
            stats["two_year_written"] += 1
        if not isinstance(raw.get(MYDT_KEY), dict):
            block = build_multiyear_block(qr)
            if block is None:
                stats["multiyear_insufficient_years"] += 1
            else:
                raw[MYDT_KEY] = block
                stats["multiyear_qualified"] += 1
    log.info("qpaybill_mydt.done", **stats)
    return stats
