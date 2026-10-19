"""NC PTS Cloud (Farragut BillPWA) — a pure, no-network restatement of the per-year depth
counties_nc.nc_ptscloud_delinquent_tax already fetches into its own raw key, into the shared
raw['two_year_delinquent'] contract gap_matrix.py's checked_columns()/positive_columns() actually
read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-19.csv, filtered column==two_year_delinquent AND
    gap_class==sourced-not-built, read before writing a line here). NC Guilford shows 12,276
    applicable, Beaufort 4,281, Orange 3,046, Madison 1,704 — all four tenants of
    counties_nc.nc_ptscloud_delinquent_tax (bcpwa.ncptscloud.com), already wired into main.py and
    already read live every run. The next_action guesses "add a tax-roll reader for ...
    bcpwa.ncptscloud.com" — that reader already exists; the real gap is that the PUBLISHED board
    rows for these four tenants were almost all written before nc_ptscloud_delinquent_tax.py's own
    commit 7f4c2c0c (2026-10-18) added `_canonical_tax_depth()`'s unconditional two_year_delinquent
    write for FRESH rows. Live-verified directly against the board (board_stream,
    docs/listings.json.gz), 2026-10-19: raw['two_year_delinquent'] is present on ZERO of Guilford's
    3,521 / Beaufort's 3,228 / Orange's 1,358 / Madison's 1,206 rows carrying
    raw['nc_ptscloud_delinquent_tax'] — while raw['multi_year_delinquent_tax'] (restated by the
    sibling module below) already reaches 35 / 92 / 653 / 167 of them respectively, because that
    sibling module's own backfill ran and this column's never did. Of those same rows, the large
    majority (3,367 / 3,167 / 1,325 / 911 — 96%, 98%, 98%, 76%) already carry the NEWER
    `by_year`-shaped block (the rest predate that shape entirely and are correctly left alone
    below, same discipline as enrichment_ptscloud_multiyear_tax.py's own `_already_done()` gate).

    Exactly the same shape as this project's two existing siblings for different vendors on the
    SAME shared key: enrichment_qpaybill_multiyear_tax.py's `build_two_year_block()` (SC qPayBill)
    and sc_catalis_delinquent_roll.py's own unconditional write (both: "years" is a COUNT of
    matured/late years, not a list; written for EVERY row with the source block, regardless of
    whether it clears any multi-year gate). This module is the ptscloud-vendor instance of that
    same pattern, read off the EXACT by_year history
    enrichment_ptscloud_multiyear_tax.py already restates from (`raw['nc_ptscloud_delinquent_tax']
    ['by_year']`), using nc_ptscloud_delinquent_tax.py's own `_canonical_tax_depth()` logic
    (levy_year / levy_year_is_delinquent) so a freshly-scraped row and a backfilled stale row
    compute byte-identical two_year_delinquent blocks.

GATE. Only rows carrying the NEWER `by_year` list (nc_ptscloud_delinquent_tax.py's current shape)
    are restated — the older, pre-10/18 block shape (`tax_year` singular, no `by_year`) carries no
    per-year list to derive years/oldest_year/matured-count from, and is left alone rather than
    guessed at from a single field. Written unconditionally once `by_year` is present, even an
    empty list or a parcel with no matured year (matching sc_catalis/qpaybill: `is_two_year_plus`
    states the truth either way, not just the qualifying case).

Pure, no network, no cap needed — the source data is already on the row. Idempotent: a row that
already carries raw['two_year_delinquent'] (from a prior run of this module, or from a scraper run
fresh enough to have written it itself) is left untouched.
Gate off entirely with FORECLOSURE_PTSCLOUD_TYD=0.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional

import structlog

from . import tax_calendar
from .models import Listing

log = structlog.get_logger()

RAW_KEY = "two_year_delinquent"
SOURCE_KEY = "nc_ptscloud_delinquent_tax"
SOURCE_SLUG = "counties_nc.nc_ptscloud_delinquent_tax"

ENABLED = os.environ.get("FORECLOSURE_PTSCLOUD_TYD") != "0"


def _already_done(raw: dict) -> bool:
    return isinstance(raw.get(RAW_KEY), dict)


def build_two_year_block(pts: dict, county: Optional[str]) -> Optional[dict]:
    """Pure: the raw['two_year_delinquent'] wrapper from one board row's own
    raw['nc_ptscloud_delinquent_tax']['by_year'] -- the SAME years/matured-year logic
    nc_ptscloud_delinquent_tax._canonical_tax_depth() uses for a freshly-scraped row, so a
    backfilled stale row and a fresh one agree. None when `by_year` isn't a list at all (the
    older, pre-10/18 block shape this module deliberately does not guess from)."""
    by_year = pts.get("by_year")
    if not isinstance(by_year, list):
        return None
    years = sorted({
        y for y in (tax_calendar.levy_year(b.get("tax_year")) for b in by_year if isinstance(b, dict))
        if y is not None
    })
    matured = [y for y in years if tax_calendar.levy_year_is_delinquent(y, "NC", county)]
    return {
        "is_two_year_plus": len(matured) >= 2,
        "years": len(matured),
        "oldest_year": years[0] if years else None,
        "source": SOURCE_SLUG,
    }


def enrich_ptscloud_two_year_delinquent(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every board row already carrying raw['nc_ptscloud_delinquent_tax'] and restate its
    already-collected by_year history into raw['two_year_delinquent']. Pure, no network, no cap
    needed -- the source data is already on the row."""
    stats = {"eligible": 0, "written": 0, "no_by_year_shape": 0}
    if not ENABLED:
        return stats
    for li in listings:
        raw = li.raw
        if not isinstance(raw, dict):
            continue
        pts = raw.get(SOURCE_KEY)
        if not isinstance(pts, dict) or _already_done(raw):
            continue
        stats["eligible"] += 1
        block = build_two_year_block(pts, li.county)
        if block is None:
            stats["no_by_year_shape"] += 1
            continue
        raw[RAW_KEY] = block
        stats["written"] += 1
    log.info("ptscloud_tyd.done", **stats)
    return stats
