#!/usr/bin/env python3
"""One-off repair: a 2026-11-06 backfill_jail_rosters.py run for Guilford NC matched exactly one
real lead (RODRIGUEZ, MIGUEL ANGEL, Guilford NC) whose identity fields (parcel_id, street_address,
case_number) were all empty, so Listing.dedupe_key() fell through to its last-resort
`url:{source_url}` branch. That source_url (https://bcpwa.ncptscloud.com/, a generic NC
land-records portal root, not a per-listing identifier) is shared by 11,033 other rows across 7
counties (Guilford, Beaufort, Pitt, Hyde, Madison, Henderson, Orange). _patch_parts_in_place()
(scripts/backfill_jail_rosters.py) correctly matches patches by dedupe_key() across the WHOLE
board, so every one of those 11,032 unrelated rows got the same person's raw['jail_booking']
merged in -- the previously-documented "dedupe_key url: fallback landmine" risk, fired for real.

This clears raw['jail_booking'] from every row sharing that exact URL + stamp EXCEPT the one
real match, restoring those 11,032 rows to their pre-corruption state (they had no
raw['jail_booking'] key before this). Uses the same safe in-place-per-part pattern as
_patch_parts_in_place: no re-chunking, only parts that actually change are rewritten, each at its
own existing row count.

    .venv/bin/python3 scripts/fix_guilford_jail_booking_url_bleed.py              # dry run
    .venv/bin/python3 scripts/fix_guilford_jail_booking_url_bleed.py --apply      # writes the board
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import board_parts as bp  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, reseal_board  # noqa: E402

BAD_URL = "https://bcpwa.ncptscloud.com/"
LEGIT_OWNER = "RODRIGUEZ, MIGUEL ANGEL"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the board (default: dry run)")
    args = ap.parse_args(argv)
    docs = REPO / "docs"

    def _fix_parts(dry_run: bool) -> dict:
        row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
        touched: list[tuple[str, int]] = []
        cleared = 0
        kept = 0
        by_county: dict = {}
        for fp in bp.list_part_files(docs):
            blobs: list[bytes] = []
            changed = False
            for text in bp.iter_gz_rows(fp, want_text=True):
                rec = json.loads(text)
                if (isinstance(rec, dict) and rec.get("source_url") == BAD_URL
                        and isinstance(rec.get("raw"), dict) and rec["raw"].get("jail_booking")):
                    if rec.get("owner_name") == LEGIT_OWNER:
                        kept += 1
                    else:
                        del rec["raw"]["jail_booking"]
                        cleared += 1
                        key = f"{rec.get('state')} {rec.get('county')}"
                        by_county[key] = by_county.get(key, 0) + 1
                        blobs.append(row_enc.encode(rec).encode("utf-8"))
                        changed = True
                        continue
                blobs.append(text.encode("utf-8"))
            if changed:
                touched.append((fp.name, len(blobs)))
                if not dry_run:
                    data = bp.gzip_array(blobs)
                    bp.atomic_write_bytes(fp, data)
        return {"touched_parts": touched, "cleared": cleared, "kept": kept, "by_county": by_county}

    if not args.apply:
        result = _fix_parts(dry_run=True)
        print(f"DRY RUN: would clear {result['cleared']:,} rows, keep {result['kept']} legit match, "
              f"across {len(result['touched_parts'])} part(s)")
        for county, n in sorted(result["by_county"].items(), key=lambda kv: -kv[1]):
            print(f"  {county:20} {n:,}")
        for name, n in result["touched_parts"]:
            print(f"  would rewrite {name} ({n:,} rows, same as before)")
        print("\nRe-run with --apply (as the only board process).")
        return 0

    with board_lock(REPO, owner="fix_guilford_jail_booking_url_bleed"):
        result = _fix_parts(dry_run=False)
        print(f"cleared {result['cleared']:,} rows, kept {result['kept']} legit match, "
              f"across {len(result['touched_parts'])} part(s)")
        for county, n in sorted(result["by_county"].items(), key=lambda kv: -kv[1]):
            print(f"  {county:20} {n:,}")
        for name, n in result["touched_parts"]:
            print(f"  rewrote {name} ({n:,} rows, same as before)")
        reseal_board(docs, resplit=False)
        print("manifest resealed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
