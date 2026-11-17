#!/usr/bin/env python3
"""One-off ingest: land SC Lancaster code-enforcement rows for real.

WHY THIS EXISTS
    Round 15 (project_code_enforcement_round15_2026-11-16.md) wired
    `lancaster_code_violations` into arcgis_distress_layers.py's LAYERS tuple
    (330 live rows on the county's ArcGIS Online `LC_ViolationPoints` feature
    service) and it has been LIVE in the generic counties_generic.arcgis_distress
    scraper since -- the generic scraper iterates the whole LAYERS tuple, so no
    main.py registration was needed -- but it had never actually been run
    against the real board: gap_matrix classified it `built-but-low-yield`,
    `ran=False`. Round 16 confirmed that live (board_stream.iter_board_rows()
    scan, 2026-11-17: 1,291 existing Lancaster SC rows from OTHER sources, 0
    from source=counties_generic.arcgis_distress.lancaster_code_violations)
    and this script is the catch-up pass, following the exact lesson the round
    16 brief itself names: wired-but-never-run code is this session's single
    highest-leverage recurring finding.

WHY A SCOPED SCRIPT, NOT THE FULL GENERIC SCRAPER
    ArcgisDistressLayers.fetch() iterates ALL ~20 layers in LAYERS through a
    LayerHarvest guard -- correct for a real scheduled run, but unnecessary
    network load (and risk of an unrelated single-host flake aborting this
    one county's land) for a one-time catch-up on ONE new layer. This calls
    the module's own `_fetch_layer(c, lay)` directly for just the Lancaster
    `Layer` entry -- the same function the full scraper uses per-layer, with
    zero parallel logic -- then runs the result through the SAME
    `main._active_only` / `main._in_scope` filters the orchestrator applies
    (same pattern scripts/ingest_counties_generic_never_run.py used, updated
    off that script's stale load_board()/write_artifact() onto the safe
    streaming primitives below).

BOARD I/O: board_stream.iter_board_rows() for the pre-check (read-only, no
lazy-detail sidecar) + web_artifact.board_lock() + append_new_rows() for the
write (task_0658b33b pattern) -- never load_board()/write_artifact() on this
board size (618,635 rows at time of writing). append_new_rows() does its own
full-board dedupe-signature streaming pass internally, so a brand-new source
with zero existing rows needs no separate collision check here.

    python scripts/backfill_lancaster_code_enforcement.py --dry-run
    python scripts/backfill_lancaster_code_enforcement.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.http_client import client, install_hard_sigint_kill  # noqa: E402
from foreclosure_scraper.main import _active_only, _in_scope  # noqa: E402
from foreclosure_scraper.scrapers.counties_generic import (  # noqa: E402
    arcgis_distress_layers as _adl,
)
from foreclosure_scraper.web_artifact import append_new_rows, board_lock  # noqa: E402

SLUG = "lancaster_code_violations"
SOURCE = f"counties_generic.arcgis_distress.{SLUG}"
HORIZON_DAYS = 120  # same default ingest_counties_generic_never_run.py used
_FETCH_TIMEOUT_S = 120.0

_LAYER = next(lay for lay in _adl.LAYERS if lay.slug == SLUG)


def _count_existing(docs: Path) -> tuple[int, int]:
    """(lancaster_sc_any_source, lancaster_this_source) via one streaming pass."""
    any_source = 0
    this_source = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if rec.get("state") == "SC" and (rec.get("county") or "").strip().lower() == "lancaster":
            any_source += 1
            if rec.get("source") == SOURCE:
                this_source += 1
    return any_source, this_source


async def _fetch_new() -> list:
    async with client(timeout=45.0) as c:
        rows = await asyncio.wait_for(_adl._fetch_layer(c, _LAYER), timeout=_FETCH_TIMEOUT_S)
    return rows


def main() -> int:
    install_hard_sigint_kill(reason="backfill_lancaster_code_enforcement")

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"

    any_source, this_source = _count_existing(docs)
    print(f"pre-check: Lancaster SC rows on board (any source): {any_source:,}")
    print(f"pre-check: Lancaster SC rows from {SOURCE}: {this_source:,}")

    print(f"\nlive-fetching layer {SLUG!r} ({_LAYER.url}) ...")
    rows = asyncio.run(_fetch_new())
    print(f"  scraped: {len(rows):,}")

    kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
    print(f"  kept after _active_only + _in_scope: {len(kept):,}")
    if not kept:
        print("\nnothing to land -- aborting.")
        return 1

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        for li in kept[:3]:
            print("  sample:", li.street_address, li.city, li.state, li.source)
        return 0

    with board_lock(REPO, owner="backfill_lancaster_code_enforcement"):
        result = append_new_rows(
            kept, {"backfill_lancaster_code_enforcement": f"{len(kept)} rows"},
            docs_dir=docs)
    print("\n=== append_new_rows result ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
