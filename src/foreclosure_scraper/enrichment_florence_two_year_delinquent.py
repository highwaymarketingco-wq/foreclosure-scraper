"""raw['two_year_delinquent'] for Florence County SC -- a pure, no-network restatement of
raw['florence_tax_inquiry'] (enrichment_florence_tax_inquiry.py) into the shared contract
gap_matrix.py's checked_columns()/positive_columns() and tax_binding.py's DERIVED_TAX_KEYS
actually read, same pattern as this project's siblings for other vendors:
enrichment_dorchester_two_year_delinquent.py (billtrax), enrichment_berkeley_two_year_delinquent.py,
enrichment_qpaybill_multiyear_tax.py's build_two_year_block().

WHY THIS EXISTS (gap_matrix "sourced-not-built", Florence two_year_delinquent, ~3,883 est rows,
paired with tax_aging_surfaced). tax_binding.py's own DERIVED_TAX_KEYS frozenset lists
two_year_delinquent as "this pipeline's own output, never a source's record" -- it is always a
restate of a source block's own count, copied, not re-derived, exactly as
enrichment_dorchester_two_year_delinquent.py's docstring explains for its vendor. Florence had no
source block to restate from until enrichment_florence_tax_inquiry.py was built alongside this
module; this is the other half of that same build.

GATE. Written unconditionally once raw['florence_tax_inquiry'] is a dict (even a single-year or
zero-balance parcel -- is_two_year_plus states the truth either way, same as Dorchester's rule).
`years` here is the SAME field the shared contract uses elsewhere: a COUNT of matured/late levy
years (late_years, already gated by tax_calendar.levy_year_is_delinquent inside
enrichment_florence_tax_inquiry.build_block), not the raw list of years carrying any balance.

Pure, no network, no cap needed -- the source data is already on the row. Idempotent: a row that
already carries raw['two_year_delinquent'] is left untouched.
Gate off entirely with FORECLOSURE_FLORENCE_TYD=0.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

import structlog

from .models import Listing

log = structlog.get_logger()

RAW_KEY = "two_year_delinquent"
SOURCE_KEY = "florence_tax_inquiry"
SOURCE_SLUG = "florence_tax_inquiry"

ENABLED = os.environ.get("FORECLOSURE_FLORENCE_TYD") != "0"


def _already_done(raw: dict) -> bool:
    return isinstance(raw.get(RAW_KEY), dict)


def build_two_year_block(blk: dict) -> dict:
    """Pure: the raw['two_year_delinquent'] wrapper from one row's own
    raw['florence_tax_inquiry'] -- trusts years_delinquent/is_two_year_plus as that block already
    computed them (tax_calendar-gated), copied rather than re-derived."""
    return {
        "is_two_year_plus": bool(blk.get("is_two_year_plus")),
        "years": int(blk.get("years_delinquent") or 0),
        "oldest_year": blk.get("oldest_year"),
        "source": SOURCE_SLUG,
    }


def enrich_florence_two_year_delinquent(listings: Iterable[Listing]) -> dict[str, Any]:
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
    log.info("florence_tyd.done", **stats)
    return stats
