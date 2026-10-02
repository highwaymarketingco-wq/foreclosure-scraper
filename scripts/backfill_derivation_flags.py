#!/usr/bin/env python3
"""Run enrichment_derivation_flags.enrich_derivation_flags() board-wide.

Wired into main.py but stale: derivation_flags present on only 1,564 of
175,518 rows. 100% offline -- free_and_clear (no open mortgages in ROD
history), tired_landlord (absentee + 10yr+ tenure, direct Dirty Deeds
Tier A #5), and divorce_flag (cross-ref against nc_ecourts_divorce), all
read-only over raw[] fields already on the board.

    python scripts/backfill_derivation_flags.py --dry-run
    python scripts/backfill_derivation_flags.py

BOARD I/O REWRITE (2026-10-02, docs/HANDOFF.md item 41, same failure class as
run_tax_owed_normalize.py's/lrcpwa_refresh.py's/_dq_common.run_apply()'s
2026-10-01/02 rewrites). This used to call load_board() to build the WHOLE
board, run enrich_derivation_flags() over it, then write_artifact(rows, ...)
-- the double materialization (write_artifact()'s `payload =
[_to_dict(li) for li in listings]`, a SECOND full copy on top of load_board()'s
own Listing list) that kernel-OOM-killed a real production attempt against
this exact board on a 23GB Oracle VM the same day (confirmed via `journalctl
-k`, anon-rss:24GB at kill time).

CLASSIFICATION (read enrichment_derivation_flags.py in full, not assumed).
Its own module docstring already states "All five are read-only computations
over existing raw[] fields. No I/O," and reading enrich_derivation_flags()
itself confirms it: a single `for li in listings` loop, no index built
across rows, no `for other in listings` anywhere -- unlike
run_tax_owed_normalize.py's enrich_tax_owed() (genuine two-pass, cross-row
dependency) this function is a PURE PER-ROW computation that merely happens
to accept the whole list as its interface. It also never reads a
LAZY_DETAIL_KEYS field ("vision"/"foreclosure_sold_comps"/"comps"/"cama"/
"rent_comps" -- grepped the whole module, zero hits), so there is no need for
the lazy-detail sidecar load_board() merges in. _free_and_clear()/
_unreleased_mortgage()/_subordinate_lien_foreclosure() read raw['rod'] (not
a lazy-detail key -- the register-of-deeds block every scraper attaches
directly, always present on the slim board); _tired_landlord() reads
raw['recorded_sales']/owner_mailing-derived fields; _divorce_flag() reads
only `li.source`/`li.listing_type`/raw['case_id'] (its own docstring claims a
"cross-reference any listing whose owner name matches a party in a divorce
filing" join, but the ACTUAL code has no such join -- confirmed by reading
the whole function body, which is two `if` branches on this ONE listing's own
source/listing_type, nothing else. The docstring is aspirational/stale, not a
description of a cross-row dependency this migration would need to honor).

Because the function is genuinely pure-per-row, this script does NOT need
_dq_common.run_apply()'s/run_tax_owed_normalize.py's "materialize the whole
board as Listing objects first" shape at all -- it streams
board_stream.iter_board_rows() one record at a time, validates it, calls
enrich_derivation_flags([li]) on a SINGLE-ROW LIST (confirmed safe: the
function carries no state across separate calls either -- every local is
declared fresh inside the function body each call, and main.py itself already
calls this same function on small per-run batches, not always the whole
board, at line ~3401), diffs that one row's raw dict, and discards it --
never holding more than one row in memory at a time. This is a TIGHTER memory
profile than both of this week's other two reference patterns
(_dq_common.run_apply()'s full materialization and lrcpwa_refresh.py's bounded
per-row-plus-small-target-list streaming), because this script has no bounded
network-bound target list to hold onto at all.

RAW-KEY DELETION HAZARD FOUND (the same class of "check before assuming
add/change is the only diff shape" that bit nothing here, but WOULD have bitten
a careless copy of lrcpwa_refresh.py's add/change-only _diff_raw()).
enrich_derivation_flags() calls `del li.raw["derivation_flags"]` when a
previously-set flag's inputs no longer support it -- the stale-flag cleanup
its own comment documents (added 2026-09-18 "before this these were never
removed -- 116 leads sat flagged free_and_clear with has_mortgage=True").
patch_existing_rows() can only MERGE a raw update via dict.update() -- it has
no delete primitive (see its own docstring) -- so representing this deletion
as raw['derivation_flags'] = None is the only way to persist it through a
patch, and is verified SAFE here the same way _dq_common.py's
_RAW_DELETE_SAFE_AS_NONE registry verifies its one entry ('scope'): grepped
every reader of "derivation_flags" in src/+scripts/+docs/dashboard.js --
the only other reader, enrichment_property_category.py, does
`raw.get("derivation_flags") or {}`, which treats None exactly like an
absent key. No other raw key is ever popped/deleted by this module (checked
the whole file) -- this is the ONE delete-as-None case this script's _diff_raw()
handles, kept local to this script rather than added to _dq_common's shared
_RAW_DELETE_SAFE_AS_NONE (that frozenset is scoped to the 7 already-migrated
_dq_common.run_apply() callers; extending a shared, already-audited safety
registry for an unrelated script is more coupling than this one extra key is
worth, so this script carries its own copy of the same reasoning instead).

DISCLOSED BEHAVIOR CHANGE, deliberate (same class as this week's other
migrations). A row that fails Listing.model_validate() is no longer silently
DELETED from the board on the next write -- it simply does not get this run's
derivation_flags update and is otherwise left exactly as it was; counted and
printed, not hard-failed on. Because this is a streaming, discard-as-you-go
design (never holding the whole board at once), this script does not enforce
BOARD_LOAD_MAX_DROP_RATE the way load_board()/_dq_common._light_rows() do --
there is no "rewrite the board minus the dropped rows" failure mode a drop-rate
ceiling exists to prevent here (a patch-based write cannot delete what it does
not target), so a high drop rate is counted and printed for visibility, not
raised on.

RAW_KEEP already covers "derivation_flags" ("*", full passthrough -- confirmed
by reading web_artifact.RAW_KEEP directly).
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_derivation_flags import enrich_derivation_flags  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, patch_existing_rows, _raise_if_board_too_large_to_patch,
)

_TOTAL_KEYS = ("free_and_clear", "unreleased_mortgage", "tired_landlord", "divorce",
               "subordinate_lien_foreclosure", "rows", "dropped_stale")


def _diff_raw(before: dict | None, after: dict | None) -> dict:
    """Add/change diff, PLUS the one verified-safe delete-as-None: see this module's own
    docstring, "RAW-KEY DELETION HAZARD FOUND"."""
    before = before or {}
    after = after or {}
    out = {k: v for k, v in after.items() if before.get(k) != v}
    if "derivation_flags" in before and "derivation_flags" not in after:
        out["derivation_flags"] = None
    return out


def _run(dry_run: bool) -> int:
    docs = REPO / "docs"
    totals = {k: 0 for k in _TOTAL_KEYS}
    before_count = after_count = total_rows = dropped = 0
    patches: dict[str, dict] = {}

    for rec in iter_board_rows(docs / "listings.json.gz"):
        try:
            li = Listing.model_validate(rec)
        except Exception:  # noqa: BLE001 - counted below; a patch-based write can't lose this row
            dropped += 1
            continue
        total_rows += 1

        pre_raw = li.raw if isinstance(li.raw, dict) else {}
        if pre_raw.get("derivation_flags"):
            before_count += 1

        key = None
        before_scalars = before_raw = None
        if not dry_run:
            try:
                key = li.dedupe_key()
            except Exception:  # noqa: BLE001 - a row too malformed to key is simply unpatchable
                key = None
            before_scalars = li.model_dump(mode="json", exclude={"raw"})
            before_raw = copy.deepcopy(li.raw) if isinstance(li.raw, dict) else None

        s = enrich_derivation_flags([li])  # UNCHANGED function, called on a single-row batch --
        for k in _TOTAL_KEYS:                # safe because it carries no cross-call state (see
            totals[k] += s.get(k, 0)          # this module's own CLASSIFICATION section).

        post_raw = li.raw if isinstance(li.raw, dict) else {}
        if post_raw.get("derivation_flags"):
            after_count += 1

        if dry_run or key is None:
            continue
        after_scalars = li.model_dump(mode="json", exclude={"raw"})
        update: dict = {k: v for k, v in after_scalars.items() if before_scalars.get(k) != v}
        raw_update = _diff_raw(before_raw, li.raw if isinstance(li.raw, dict) else None)
        if raw_update:
            update["raw"] = raw_update
        if update:
            patches[key] = update

    print(f"board rows: {total_rows:,}" + (f" | dropped={dropped:,}" if dropped else ""))
    print(f"derivation_flags before: {before_count:,}")
    print(f"\nstats: {totals}")
    print(f"derivation_flags after: {after_count:,} (+{after_count - before_count:,})")

    if dry_run:
        print("\nDRY RUN — nothing written.")
        return 0

    pstats = patch_existing_rows(patches, {"backfill_derivation_flags": totals}, docs_dir=docs)
    existing = f"{pstats['existing']:,}" if pstats["existing"] is not None else "(no patch attempted)"
    print(f"wrote board: patched {pstats['applied']:,}/{len(patches):,} changed row(s) "
          f"(existing board: {existing})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        return _run(dry_run=True)

    with board_lock(REPO, owner="backfill_derivation_flags"):
        docs = REPO / "docs"
        # Fail before the (now cheap, streaming) full pass, not after -- same ceiling
        # patch_existing_rows() itself re-checks before writing.
        _raise_if_board_too_large_to_patch(docs)
        return _run(dry_run=False)


if __name__ == "__main__":
    raise SystemExit(main())
