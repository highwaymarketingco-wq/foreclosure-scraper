"""Dorchester County SC billtrax.com delinquent roll — a pure, no-network restatement of the
per-parcel bill history counties_sc.dorchester_billtrax_delinquent_tax already aggregates into
its own raw key, into the shared raw['two_year_delinquent'] contract gap_matrix.py's
checked_columns()/positive_columns() actually read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-19.csv, filtered column==two_year_delinquent AND
    gap_class==sourced-not-built, read before writing a line here). SC Dorchester shows 1,817
    applicable, source "tax/property card: dorchestercountyscdelinquenttax.billtrax.com", built=no.
    That host is not an unbuilt gap: counties_sc.dorchester_billtrax_delinquent_tax already reads
    it live every run, and its own per-parcel aggregation (module code, not a docstring claim)
    ALREADY computes `years`, `years_delinquent` and `is_two_year_plus` on
    raw['billtrax_dorchester_delinquent_tax'] -- the exact field, already named `is_two_year_plus`,
    `two_year_delinquent` needs, just never copied to the shared key. Live-verified directly
    against the board (board_stream, docs/listings.json.gz), 2026-10-19:
    raw['billtrax_dorchester_delinquent_tax'] is present on 1,058 of Dorchester's 1,817 applicable
    rows (58%), every one of them already carrying `is_two_year_plus`/`years_delinquent`;
    raw['two_year_delinquent'] is present on ZERO.

    Same pattern, same shared key, as this project's siblings for different vendors
    (enrichment_qpaybill_multiyear_tax.py's `build_two_year_block()`, sc_catalis_delinquent_roll.py's
    own unconditional write, enrichment_berkeley_two_year_delinquent.py just above) -- "years" is a
    COUNT of matured/late years, not a list, written for EVERY row carrying the source block
    regardless of whether it clears any multi-year gate. This is the simplest of the three: the
    source block's own `is_two_year_plus` and `years_delinquent` are copied directly, not
    re-derived, because dorchester_billtrax_delinquent_tax.py already applies SC's own statutory
    late-date rule (tax_calendar.completed_delinquent_years) when it computes them.

GATE. Written unconditionally once raw['billtrax_dorchester_delinquent_tax'] is a dict, even a
    single-year parcel (`is_two_year_plus` states the truth either way).

Pure, no network, no cap needed -- the source data is already on the row. Idempotent: a row that
already carries raw['two_year_delinquent'] is left untouched.
Gate off entirely with FORECLOSURE_DORCHESTER_TYD=0.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

import structlog

from .models import Listing

log = structlog.get_logger()

RAW_KEY = "two_year_delinquent"
SOURCE_KEY = "billtrax_dorchester_delinquent_tax"
SOURCE_SLUG = "counties_sc.dorchester_billtrax_delinquent_tax"

ENABLED = os.environ.get("FORECLOSURE_DORCHESTER_TYD") != "0"


def _already_done(raw: dict) -> bool:
    return isinstance(raw.get(RAW_KEY), dict)


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build_two_year_block(blk: dict) -> dict:
    """Pure: the raw['two_year_delinquent'] wrapper from one board row's own
    raw['billtrax_dorchester_delinquent_tax'] -- trusts `is_two_year_plus`/`years_delinquent` as
    the scraper already computed them (late-year-only, tax_calendar-gated), copied rather than
    re-derived. `oldest_year` falls back to the block's own `years` list (the full unpaid-year
    list, not just the matured ones) when present."""
    years_list = blk.get("years")
    oldest = None
    if isinstance(years_list, list) and years_list:
        try:
            oldest = min(int(y) for y in years_list)
        except (TypeError, ValueError):
            oldest = None
    return {
        "is_two_year_plus": bool(blk.get("is_two_year_plus")),
        "years": _int_or_none(blk.get("years_delinquent")) or 0,
        "oldest_year": oldest,
        "source": SOURCE_SLUG,
    }


def enrich_dorchester_two_year_delinquent(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every board row already carrying raw['billtrax_dorchester_delinquent_tax'] and
    restate its already-computed is_two_year_plus/years_delinquent into
    raw['two_year_delinquent']. Pure, no network, no cap needed -- the source data is already on
    the row."""
    stats = {"eligible": 0, "written": 0}
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
        raw[RAW_KEY] = build_two_year_block(blk)
        stats["written"] += 1
    log.info("dorchester_tyd.done", **stats)
    return stats
