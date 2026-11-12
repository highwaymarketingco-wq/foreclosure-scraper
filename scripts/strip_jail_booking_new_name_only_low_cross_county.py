#!/usr/bin/env python3
"""Strip the uncorroborated jail_booking_new tag from the board.

2026-10-02 HYGIENE CORRECTION. A real backfill run earlier today (before
commit b374f4ab's fix landed) wrote raw['jail_booking_new'] onto 12,337 board
rows via `enrichment_jail_bookings.match_cross_county`'s then-current logic:
an exact first+last name match against the WHOLE board, with NO corroborating
signal at all (no middle name, no DOB, no county check). b374f4ab fixed the
function going forward (requires `name_normalize.party_middle_verdict(...) ==
"agrees"` before stamping a match) and renamed its confidence tag from
"name_only_low_cross_county" to "middle_corroborated_cross_county" so old and
new rows can never be read as the same thing.

This script corrects the 12,337 rows the OLD code already wrote. It does NOT
re-run match_cross_county: `data/jail_roster_history.db` shows exactly one
fetch ever recorded for every one of its 3,359 booking rows
(first_seen_at == last_seen_at, all at 2026-10-02T18:00:42-18:01:03Z) -- the
"is_new_booking" gate match_cross_county depends on is a first-ever-INSERT
flag in that sidecar, so re-fetching the same rosters now would find every
one of those names already recorded and return is_new_booking=False for the
entire original candidate pool, regardless of what a middle-name check would
have found. A "fresh re-run" would silently report ~0 matches and look like
confirmation nothing was recoverable, when the real reason is the sidecar
gate being structurally exhausted by the one cold-start fetch, not an absence
of corroborating signal. None of the original 12,337 rows carry the roster
hit's middle name on the board either (raw['jail_booking_new']['matched_name']
was written as "{first} {last}", never the middle) -- the data needed to
retroactively corroborate any of them was never persisted and is not
re-derivable without a live re-fetch, which the paragraph above rules out as
misleading right now. A bare strip is therefore the honest correction: none
of these matches was ever corroborated, and the fixed code requires
corroboration before it will stamp a match at all -- so "no longer flagged"
is the correct post-fix state for every one of them, not an approximation.

Verified safe to represent as `raw['jail_booking_new'] = None` for
patch_existing_rows() (which can only MERGE via dict.update(), never delete) --
same reasoning as scripts/backfill_derivation_flags.py's `derivation_flags`
case and item 42's `bop_check` case in docs/HANDOFF.md: `jail_booking_new` is
RAW_KEEP'd ("*", full passthrough) and, per enrichment_jail_bookings.py's own
module docstring ("Checked whether any scorer compounds this"), is read by
nothing outside that module, its own tests, and
scripts/run_pending_signal_enrichers.py -- which only counts/patches it via
`raw.get("jail_booking_new")`, a truthy check that treats None exactly like
absent. distress_score.py never reads this key at all (it scores
raw['jail_booking']/raw['incarceration'], the separate same-county tier,
untouched by this bug or this script).

Streams board_stream.iter_board_rows() one record at a time (the
backfill_derivation_flags.py / lrcpwa_refresh.py streaming-patch pattern) and
writes only the touched rows via patch_existing_rows() -- never materializes
the ~219K-row board as Listing objects, never a second full in-memory copy.

    python scripts/strip_jail_booking_new_name_only_low_cross_county.py --dry-run
    python scripts/strip_jail_booking_new_name_only_low_cross_county.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, patch_existing_rows, _raise_if_board_too_large_to_patch,
)

OLD_TAG = "name_only_low_cross_county"
NEW_TAG = "middle_corroborated_cross_county"


def _run(dry_run: bool) -> int:
    docs = REPO / "docs"
    total_rows = 0
    dropped = 0
    old_tag_count = 0
    new_tag_count = 0
    patches: dict[str, dict] = {}

    for rec in iter_board_rows(docs / "listings.json.gz"):
        try:
            li = Listing.model_validate(rec)
        except Exception:  # noqa: BLE001 - counted below; a patch-based write can't lose this row
            dropped += 1
            continue
        total_rows += 1

        raw = li.raw if isinstance(li.raw, dict) else {}
        jbn = raw.get("jail_booking_new")
        if isinstance(jbn, dict) and jbn.get("confidence") == NEW_TAG:
            new_tag_count += 1
        if not (isinstance(jbn, dict) and jbn.get("confidence") == OLD_TAG):
            continue
        old_tag_count += 1

        if dry_run:
            continue

        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a row too malformed to key is simply unpatchable
            continue
        patches[key] = {"raw": {"jail_booking_new": None}}

    print(f"board rows: {total_rows:,}" + (f" | dropped={dropped:,}" if dropped else ""))
    print(f"rows carrying jail_booking_new confidence={OLD_TAG!r} (bad, pre-fix): {old_tag_count:,}")
    print(f"rows carrying jail_booking_new confidence={NEW_TAG!r} (good, post-fix): {new_tag_count:,}")

    if dry_run:
        print("\nDRY RUN — nothing written.")
        return 0

    print(f"\npatches staged (stripping jail_booking_new entirely): {len(patches):,}")
    pstats = patch_existing_rows(
        patches,
        {"strip_jail_booking_new_name_only_low_cross_county": {"stripped": len(patches)}},
        docs_dir=docs,
    )
    existing = f"{pstats['existing']:,}" if pstats["existing"] is not None else "(no patch attempted)"
    print(f"wrote board: patched {pstats['applied']:,}/{len(patches):,} row(s) "
          f"(existing board: {existing})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        return _run(dry_run=True)

    with board_lock(REPO, owner="strip_jail_booking_new_name_only_low_cross_county"):
        docs = REPO / "docs"
        _raise_if_board_too_large_to_patch(docs)
        return _run(dry_run=False)


if __name__ == "__main__":
    raise SystemExit(main())
