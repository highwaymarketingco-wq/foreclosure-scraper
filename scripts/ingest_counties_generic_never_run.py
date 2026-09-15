#!/usr/bin/env python3
"""Ingest three counties_generic.* scrapers fixed/confirmed in the 2026-09-15
misc-category zero-row audit:

    counties_generic.arcgis_distress_layers  -- was hard-failing the whole
        18-layer batch every run because one flaky single-host layer
        (lincoln_code_violations) has an incomplete TLS chain; added to the
        harvester's existing tolerate-list. Also fixed a DATELESS_OK_SOURCES
        gap that only whitelisted 1 of 18 layers by exact string instead of
        the shared dynamic-slug prefix.
    counties_generic.state_contamination     -- already correctly wired,
        missing its DATELESS_OK_SOURCES prefix entry.
    counties_generic.epa_frs_sites           -- same, missing prefix entry.

All three ship rows under dynamic per-layer/per-registry/per-program source
slugs (not their class-level scraper slug), so dedupe is scoped by the UNION
of every real source prefix these three scrapers can emit, all confirmed at
0 existing board rows.

    python scripts/ingest_counties_generic_never_run.py --dry-run
    python scripts/ingest_counties_generic_never_run.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.dedupe import dedupe  # noqa: E402
from foreclosure_scraper.main import _active_only, _in_scope  # noqa: E402
from foreclosure_scraper.scrapers.counties_generic.arcgis_distress_layers import ArcgisDistressLayers  # noqa: E402
from foreclosure_scraper.scrapers.counties_generic.epa_frs_sites import EpaFrsSites  # noqa: E402
from foreclosure_scraper.scrapers.counties_generic.state_contamination import StateContamination  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

HORIZON_DAYS = 120

SCRAPERS = [
    ("arcgis_distress_layers", ArcgisDistressLayers),
    ("state_contamination", StateContamination),
    ("epa_frs_sites", EpaFrsSites),
]
# Real per-row source prefixes each scraper actually emits (dynamic slugs),
# not the class-level self.slug.
SOURCE_PREFIXES = (
    "counties_generic.arcgis_distress.",
    "counties_generic.state_contamination.",
    "counties_generic.epa_frs.",
)


async def _fetch_new() -> list:
    out: list = []
    for name, cls in SCRAPERS:
        try:
            rows = list(await cls().fetch())
        except Exception as e:
            print(f"  [FAIL] {name}: {e!r}")
            continue
        kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
        print(f"  [OK]   {name}: scraped={len(rows)} kept={len(kept)}")
        out.extend(kept)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("scraping 3 sources...")
    new_rows = asyncio.run(_fetch_new())
    print(f"\ntotal kept rows: {len(new_rows):,}")
    if not new_rows:
        print("nothing to land — aborting.")
        return 1

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="counties_generic_never_run_ingest")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows before: {before:,}")

        is_target = lambda li: (li.source or "").startswith(SOURCE_PREFIXES)
        target_rows = [li for li in rows if is_target(li)]
        other_rows = [li for li in rows if not is_target(li)]
        print(f"existing rows from these sources: {len(target_rows):,}")

        target_merged = dedupe(target_rows + new_rows)
        merged = other_rows + target_merged
        print(f"board rows after dedupe: {len(merged):,} (net new: {len(merged) - before:,})")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(merged, {"counties_generic_never_run_ingest": len(new_rows)}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(merged):,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
