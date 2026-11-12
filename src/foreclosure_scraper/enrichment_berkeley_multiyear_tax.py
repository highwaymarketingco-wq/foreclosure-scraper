"""Berkeley County SC paystar.io delinquent roll -- counties_sc.berkeley_paystar_tax's own
per-parcel multi-invoice history (_merge_invoices()'s `bills` list), restated into the shared
raw['multi_year_delinquent_tax'] contract gap_matrix.py's own checked_columns()/
positive_columns() already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-20.csv, read before writing a line here).
    multi_year_delinquent_tax shows sourced-not-built for SC Berkeley (3,012 applicable),
    source "tax/property card: berkeleycountysc.paystar.io" (the SAME host as
    rollback_exposure -- Paystar is a shared tax-PAYMENT vendor, not a separate per-signal
    API). The next_action guesses a brand-new tax-roll reader is needed; one already exists
    and is already wired into main.py (counties_sc.berkeley_paystar_tax).

    SAME PATTERN AS THIS SESSION'S TWO NC SIBLINGS (enrichment_ptscloud_multiyear_tax.py,
    enrichment_gaston_multiyear_tax.py): an upstream scraper already reads a parcel's full
    per-year bill history, but nothing ever restated it under the ONE shared raw key the gap
    matrix actually credits. counties_sc/berkeley_paystar_tax.py's own _merge_invoices()
    (pre-existing, 2026-10-09 source audit) already collapses a parcel's unpaid prior-year
    invoices onto one row and builds `bills` -- a list of {tax_year, total_due,
    invoice_number, delinquent} dicts, one per distinct unpaid year -- the EXACT shape this
    module's reused build_block() (enrichment_ptscloud_multiyear_tax.build_block, imported
    rather than re-implemented: it reads entry['tax_year']/entry['total_due'] and nothing
    tenant-specific) already expects as its `by_year` argument.

    LIVE-VERIFIED 2026-10-20 (real search + per-invoice fetch against the real host, read-
    only, no board touched, no new vendor integration): of 2,725 currently-unpaid real-
    property invoices on the live roll, grouped into distinct parcels the same way
    _merge_invoices() does, a real and material share carries >=2 distinct unpaid tax years
    with at least one past its SC statutory delinquent date (tax_calendar.
    completed_delinquent_years) -- see this session's report for the exact measured count.

    Board state measured live 2026-10-20 (board_stream.iter_board_rows, read-only): of the
    board's 2,211 Berkeley paystar rows, only 25 carry a `bills` list at all, and every one of
    those 25 has length exactly 1 -- i.e. ZERO rows on the live board today have the >=2-year
    history this column's gate needs, even though the live API confirms that history exists
    for real parcels right now. The board's cached Berkeley rows predate _merge_invoices()
    reaching most of them (most carry no `bills` key at all -- an older, single-invoice-per-
    row scrape, or a run that hit this scraper's documented per-request-latency ceiling before
    finishing the roll). This module will fire the moment those rows are re-scraped; it does
    nothing against the board's current cache (reported, not hidden).

GATE (identical to the ptscloud/Gaston siblings, so a downstream consumer sees one consistent
    contract regardless of producer): at least MIN_YEARS (2) distinct unpaid tax years, AND at
    least one of them past its statutory delinquent date.

NOT COUNTY-RESTRICTED BY A DIFFERENT KEY. Runs over every row carrying
    raw['berkeley_paystar_tax'] (gated additionally on county=='Berkeley' -- the same
    cross-contamination guard enrichment_berkeley_two_year_delinquent.py already documents: 2
    pre-existing non-Berkeley rows were found carrying a stray block with a junk parent_tms).
    Idempotent: a row that already carries raw['multi_year_delinquent_tax'] is left untouched.

Pure, no network, no cap needed -- the source data is already on the row.
Gate off entirely with FORECLOSURE_BERKELEY_MYDT=0.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Iterable, Optional

import structlog

from .enrichment_ptscloud_multiyear_tax import build_block as _ptscloud_build_block
from .models import Listing

log = structlog.get_logger()

RAW_KEY = "multi_year_delinquent_tax"
SOURCE_KEY = "berkeley_paystar_tax"
SOURCE_SLUG = "counties_sc.berkeley_paystar_tax"

ENABLED = os.environ.get("FORECLOSURE_BERKELEY_MYDT") != "0"
MIN_YEARS = int(os.environ.get("BERKELEY_MYDT_MIN_YEARS", "2"))


def _already_done(raw: dict) -> bool:
    return isinstance(raw.get(RAW_KEY), dict)


def build_block(parcel_id: Optional[str], blk: dict, *, today: Optional[date] = None) -> Optional[dict]:
    """Pure: the raw['multi_year_delinquent_tax'] block from one board row's own
    raw['berkeley_paystar_tax']['bills'] list, reusing enrichment_ptscloud_multiyear_tax's
    build_block() (generic over any by_year list shaped {tax_year, total_due, ...}) and then
    restating the two source-identifying fields it fills in for its own vendor."""
    bills = blk.get("bills")
    if not isinstance(bills, list) or not bills:
        return None
    rec = _ptscloud_build_block(parcel_id, "SC", "Berkeley", bills, tenant=None, today=today)
    if rec is None:
        return None
    rec["layers"] = ["berkeley_paystar_tax"]
    rec["tenant"] = None
    rec["source_url"] = "https://berkeleycountysc.paystar.io"
    return rec


def enrich_berkeley_multiyear_tax(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every board row already carrying raw['berkeley_paystar_tax'] and restate its
    per-year `bills` history into raw['multi_year_delinquent_tax'] when it clears the
    multi-year gate. Pure, no network, no cap needed -- the source data is already on the
    row."""
    stats = {"eligible": 0, "qualified": 0, "insufficient_history": 0,
              "skipped_wrong_county": 0}
    if not ENABLED:
        return stats
    today = date.today()
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
        block = build_block(li.parcel_id, blk, today=today)
        if block is None:
            stats["insufficient_history"] += 1
            continue
        raw[RAW_KEY] = block
        stats["qualified"] += 1
    log.info("berkeley_mydt.done", **stats)
    return stats
