"""Berkeley County SC paystar.io delinquent roll -- TotalBuildingCount restated into the
shared raw['vacant_lot'] contract gap_matrix.py's own checked_columns()/positive_columns()
already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-20.csv, read before writing a line here).
    vacant_lot shows sourced-not-built for SC Berkeley (3,012 applicable), source "county GIS:
    gis.berkeleycountysc.gov", next_action "add the county parcel layer ... to parcel_cache".
    That parcel_cache entry ALREADY EXISTS (parcel_cache.py PARCEL_LAYERS["Berkeley"], added
    earlier) -- live-checked 2026-10-20 against the layer's own field metadata
    (gis.berkeleycountysc.gov/arcgis/rest/services/internet/MapServer/4?f=json): it is a true
    dead end for this column, not an oversight. The layer carries 26 fields total and NONE of
    them is a land-use/property-class code or a building/improvement value of any kind -- only
    TotalTaxValue, a single COMBINED land+building figure with no split (confirmed against the
    live schema, not assumed). There is nothing here for the Sumter/Greenwood "value-only, no
    land_use field" fallback (enrichment_vacant_landuse.py's _VALUE_ONLY_NO_LANDUSE) to read.

    The real, unmapped signal lives on a DIFFERENT already-built source for the same county:
    counties_sc.berkeley_paystar_tax's own per-invoice assetMetaJson carries
    `TotalBuildingCount` -- the county's own CAMA structure count, the same kind of field this
    project already treats as ground truth elsewhere (parcel_cache.py's Barnwell note: "no
    building-COUNT field exists ... Barnwell's own ground truth"). Live-verified 2026-10-20
    against 600 real unpaid invoices via the scraper's own documented public API (plain httpx,
    no auth, no CAPTCHA): TotalBuildingCount is ALWAYS a clean small integer string ("0", "1",
    "2", ...), never blank, on every sampled row -- a 250-row sub-sample split 149 count==0 /
    101 count>=1. That field existed in the scraper's own _BILL_MONEY dict already
    (counties_sc/berkeley_paystar_tax.py) but was silently DROPPED on every row where it read 0
    -- the scraper's generic "if v: out[k]=v" truthy filter, correct for every money field
    (where 0 really does mean "no charge"), wrongly treated a real 0 structure count as "not
    fetched" and discarded it before it ever reached the board. Fixed in that file (see its
    2026-10-20 _bill_detail() comment) to capture building_count unconditionally; this module is
    the pure, no-network restatement that turns the now-correctly-captured field into the shared
    key once a row carries it.

    Board state measured live 2026-10-20 (board_stream.iter_board_rows, read-only, no write):
    2,211 of 3,012 Berkeley rows already carry raw['berkeley_paystar_tax'], but only 17 of those
    2,211 carry a 'building_count' key at all -- the vast majority of the board's cached
    Berkeley rows predate even the OLD (truthy-only) building_count capture, let alone this
    fix. This module will fire the moment those rows are re-scraped with the fix in place; it
    does nothing useful against the board's current, stale cache (reported, not hidden).

GATE. Only county=='Berkeley' (not just the source key's presence) -- the same
    cross-contamination guard enrichment_berkeley_two_year_delinquent.py already documents (2
    pre-existing non-Berkeley rows were found carrying a stray raw['berkeley_paystar_tax']
    block with a junk parent_tms). building_count must be an explicit 0 (not missing/None) --
    "no reading" and "confirmed no structure" are never conflated. A row already carrying
    raw['vacant_lot'] (from any producer) is left untouched.

Pure, no network, no cap needed -- the source data is already on the row.
Gate off entirely with FORECLOSURE_BERKELEY_VACANT_LOT=0.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

import structlog

from .models import Listing

log = structlog.get_logger()

RAW_KEY = "vacant_lot"
SOURCE_KEY = "berkeley_paystar_tax"
SOURCE_SLUG = "counties_sc.berkeley_paystar_tax"

ENABLED = os.environ.get("FORECLOSURE_BERKELEY_VACANT_LOT") != "0"


def _already_done(raw: dict) -> bool:
    return isinstance(raw.get(RAW_KEY), dict)


def build_vacant_lot_block(blk: dict) -> dict | None:
    """Pure: the raw['vacant_lot'] record from one board row's own
    raw['berkeley_paystar_tax']['building_count'], or None when that count is missing or
    nonzero (an improved parcel, or no reading at all -- never guessed)."""
    bc = blk.get("building_count")
    if bc is None:
        return None
    try:
        bc = float(bc)
    except (TypeError, ValueError):
        return None
    if bc != 0.0:
        return None
    return {
        "building_count": 0,
        "basis": "cama_structure_count",
        "source": SOURCE_SLUG,
        "source_key": SOURCE_KEY,
    }


def enrich_berkeley_vacant_lot(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every board row already carrying raw['berkeley_paystar_tax'] and restate a literal
    building_count==0 reading into raw['vacant_lot']. Pure, no network, no cap needed -- the
    source data is already on the row."""
    stats = {"eligible": 0, "written": 0, "skipped_wrong_county": 0, "no_reading": 0,
              "improved": 0}
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
        block = build_vacant_lot_block(blk)
        if block is None:
            if "building_count" in blk:
                stats["improved"] += 1
            else:
                stats["no_reading"] += 1
            continue
        raw[RAW_KEY] = block
        stats["written"] += 1
    log.info("berkeley_vacant_lot.done", **stats)
    return stats
