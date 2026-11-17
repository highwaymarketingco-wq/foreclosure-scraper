#!/usr/bin/env python3
"""Land counties_sc.charleston_energov_history.py's real output for the first time.

FOUND 2026-11-16 (code_enforcement "no source known" research): the module writes a real
raw["code_enforcement"] block for Charleston County SC (sourced from the county's own live
EnerGov history MapServer, confirmed live: 0.2s response, 1,873 real Building-Services code
cases + 3,228 demolition permits all-time) and is correctly auto-discovered by
scrapers/_registry.py -- but it had ZERO rows on the board before this date. Not a code bug:
a direct `safe_run()` of the real scraper today finished clean in 126.3s (well inside its own
180s `timeout_s`), 5,080 cases -> 2,789 leads, 530 address-join misses. It had simply never
been run to completion in a real population pass since being added (main.py's 2026-10-07
DATELESS_OK_SOURCES comment dates it) -- the same "wired wasn't run" shape as
project_round8_sources_landed_2026-11-16.md. gap_matrix.py's "code_enforcement" Spec producers
tuple was ALSO missing this file (same bug class as the Gastonia/Spartanburg-vacancy omissions
its own comments already document), fixed separately in that file.

Pure append: the board has no prior rows from this source at all, so there is nothing of this
source's own to patch -- append_new_rows() still runs its own dedupe (dedupe.py's strong keys)
against the WHOLE board, so a Charleston lead this fetch rediscovers under a different existing
source is skipped automatically rather than double-landed.

    python scripts/land_charleston_energov_history.py --dry-run
    BOARD_APPEND_ALLOW_LARGE=1 python scripts/land_charleston_energov_history.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.scrapers.counties_sc.charleston_energov_history import (  # noqa: E402
    CharlestonEnergovHistory,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    append_new_rows, board_append_size_state, board_lock,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_append_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_APPEND_ALLOW_LARGE"] = "1"

    print("fetching Charleston County SC EnerGov code-case/demolition history (real run, "
          "~126s measured)...")
    s = CharlestonEnergovHistory()
    listings = asyncio.run(s.safe_run())
    print(f"outcome={s.last_outcome} fetched {len(listings)} candidate listings")
    if not listings:
        print("nothing to land.")
        return 0

    seen = set()
    deduped = []
    for li in listings:
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(li)
    print(f"deduped within this fetch: {len(listings)} -> {len(deduped)}")

    code_count = sum(1 for li in deduped if (li.raw or {}).get("code_enforcement"))
    demo_count = sum(1 for li in deduped if (li.raw or {}).get("demolition_permit"))
    print(f"of those: {code_count} carry a code_enforcement block, {demo_count} a "
          f"demolition_permit block (a lead can carry both)")

    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for li in deduped[:5]:
            ce = (li.raw or {}).get("code_enforcement")
            print("  NEW:", li.street_address, li.parcel_id,
                  "ce_open=", ce.get("open_violations") if ce else None)
        return 0

    with board_lock(REPO, owner="land_charleston_energov_history", wait=1200, poll=10):
        astats = append_new_rows(
            deduped, {"counties_sc.charleston_energov_history": len(deduped)},
            docs_dir=docs_dir)
        print(f"append_new_rows: {astats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
