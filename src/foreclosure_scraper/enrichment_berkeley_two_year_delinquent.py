"""Berkeley County SC paystar.io delinquent roll — a pure, no-network restatement of the
multi-invoice history counties_sc.berkeley_paystar_tax already aggregates into its own raw key,
into the shared raw['two_year_delinquent'] contract gap_matrix.py's checked_columns()/
positive_columns() actually read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-19.csv, filtered column==two_year_delinquent AND
    gap_class==sourced-not-built, read before writing a line here). SC Berkeley shows 3,012
    applicable, source "tax/property card: berkeleycountysc.paystar.io", built=no. That host is
    not an unbuilt gap at all: counties_sc.berkeley_paystar_tax already reads it live every run,
    and its own `_merge_invoices()` (2026-10-09 source audit, module docstring) already collapses a
    parcel's unpaid prior-year invoices onto one row and computes `years_unpaid` and
    `years_delinquent` (LATE levy years, tax_calendar.completed_delinquent_years) on
    raw['berkeley_paystar_tax'] -- the exact fields `two_year_delinquent` needs, just never
    restated under the shared key. Live-verified directly against the board (board_stream,
    docs/listings.json.gz), 2026-10-19: raw['berkeley_paystar_tax'] is present on 2,211 of
    Berkeley's 3,012 applicable rows (73%), every one of them already carrying `years_delinquent`
    and `oldest_year` from `_merge_invoices()`; raw['two_year_delinquent'] is present on ZERO.

    Same pattern, same shared key, as this project's two existing siblings for different vendors:
    enrichment_qpaybill_multiyear_tax.py's `build_two_year_block()` (SC qPayBill) and
    sc_catalis_delinquent_roll.py's own unconditional write -- "years" is a COUNT of matured/late
    years, not a list, written for EVERY row carrying the source block regardless of whether it
    clears any multi-year gate.

GATE. `_merge_invoices()` already applies SC's own statutory late-date rule
    (tax_calendar.completed_delinquent_years) when it computes `years_delinquent`, so this module
    trusts that field directly rather than re-deriving it from `years_unpaid` a second time --
    same "read what the source already computed, don't re-derive" discipline
    enrichment_dorchester_two_year_delinquent.py uses for Dorchester's own `is_two_year_plus`.
    Written unconditionally once raw['berkeley_paystar_tax'] is a dict, even a single-invoice
    parcel (`is_two_year_plus` states the truth either way).

Pure, no network, no cap needed -- the source data is already on the row. Idempotent: a row that
already carries raw['two_year_delinquent'] is left untouched.
Gate off entirely with FORECLOSURE_BERKELEY_TYD=0.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

import structlog

from .models import Listing

log = structlog.get_logger()

RAW_KEY = "two_year_delinquent"
SOURCE_KEY = "berkeley_paystar_tax"
SOURCE_SLUG = "counties_sc.berkeley_paystar_tax"

ENABLED = os.environ.get("FORECLOSURE_BERKELEY_TYD") != "0"


def _already_done(raw: dict) -> bool:
    return isinstance(raw.get(RAW_KEY), dict)


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build_two_year_block(blk: dict) -> dict:
    """Pure: the raw['two_year_delinquent'] wrapper from one board row's own
    raw['berkeley_paystar_tax'] -- trusts `years_delinquent`/`oldest_year` as
    `_merge_invoices()` already computed them (late-year-only, tax_calendar-gated), the same
    "years is a count" shape sc_catalis_delinquent_roll.py's own unconditional write uses."""
    years_delinquent = _int_or_none(blk.get("years_delinquent")) or 0
    oldest = _int_or_none(blk.get("oldest_year"))
    return {
        "is_two_year_plus": years_delinquent >= 2,
        "years": years_delinquent,
        "oldest_year": oldest,
        "source": SOURCE_SLUG,
    }


def enrich_berkeley_two_year_delinquent(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every board row already carrying raw['berkeley_paystar_tax'] and restate its
    already-computed years_delinquent/oldest_year into raw['two_year_delinquent']. Pure, no
    network, no cap needed -- the source data is already on the row.

    Gated on county=='Berkeley' (not just the source key's presence): a 2026-10-19 gap-matrix
    backfill dry-run found 2 pre-existing board rows (Spartanburg SC, Sumter SC, both
    qpaybill_delinquent_roll-sourced) already carrying a stray raw['berkeley_paystar_tax'] block
    with a junk parent_tms ("0000000000") -- a pre-existing cross-contamination bug in a different
    module, out of this file's scope to fix. The source key's presence alone is not a safe signal
    of which county actually owns the row."""
    stats = {"eligible": 0, "written": 0, "skipped_wrong_county": 0}
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
        raw[RAW_KEY] = build_two_year_block(blk)
        stats["written"] += 1
    log.info("berkeley_tyd.done", **stats)
    return stats
