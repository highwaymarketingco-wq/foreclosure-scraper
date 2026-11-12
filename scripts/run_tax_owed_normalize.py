#!/usr/bin/env python3
"""Run the tax_owed normalization pass (enrichment_tax_owed.enrich_tax_owed)
against the live board and write it back.

Pure Python, no network — safe to run any time, not tied to any one
scraper's ingest. Found needed 2026-09-14 while ingesting Greenville's new
delinquent-tax source: raw.<source>.total_due was landing on the board, but
raw.tax_owed (the normalized field _SLIM_RAW actually ships to phones) is
only ever produced by this pass, and it hadn't run recently enough to cover
it — or, it turned out, most of the board's other tax-ish sources either
(24,741 rows stamped board-wide in one run, not just Greenville's ~2,300).

    python scripts/run_tax_owed_normalize.py --dry-run
    python scripts/run_tax_owed_normalize.py

BOARD I/O REWRITE (2026-10-02, same failure class as lrcpwa_refresh.py's/
_dq_common.run_apply()'s 2026-10-01 rewrites — docs/HANDOFF.md items 22/23):
this used to call load_board() to build the WHOLE board as `rows`, mutate
raw['tax_owed'] on it via enrich_tax_owed(), then write_artifact(rows, ...).
Confirmed on today's real production attempt (the 23GB Oracle VM, 2026-10-02):
write_artifact() builds `payload = [_to_dict(li) for li in listings]`, a
SECOND full in-memory copy of the board on top of the Listing list load_board()
already held — two full copies of a ~2.65GB board (each inflating to roughly
11-12GB as parsed Python objects) exceeded even 23GB, and the process was
kernel-OOM-killed (anon-rss:24GB at kill time, per `journalctl -k`).

CLASSIFICATION (read enrichment_tax_owed.py in full, not assumed). It does NOT
read any LAZY_DETAIL_KEYS ("vision", "foreclosure_sold_comps", "comps", "cama",
"rent_comps" — the lazy-detail sidecar load_board() merges in and plain
board_stream.iter_board_rows() does not): grepped the whole module for those
five names and for the substring "vision"/"comps"/"cama" — zero real hits (the
only "vision" look-alike was inside a comment, "lrcpwa, gis, cama, etc.",
itself just an example list for Pass C's generic "scan every OTHER raw
sub-dict for a year key" fallback, which addresses no LAZY_DETAIL_KEYS name
specifically and behaves identically whether those blocks are present,
absent, or empty). So the slim board_stream.iter_board_rows() reader (no
sidecar merge) is sufficient and correct — the same choice
_dq_common._light_rows() made for its own 9 callers, none of which touch a
LAZY_DETAIL_KEYS field either.

enrich_tax_owed(listings), however, is NOT a pure per-row function the way
lrcpwa_refresh.py's per-row recompute was — its own first line does
`listings = list(listings)` and then runs TWO passes over that one list: pass
1 normalizes each tax lead's own amount into an index keyed by (state, county,
parcel); pass 2 re-walks every row and cross-references the SAME index onto
any OTHER lead resolved to the same parcel. A row visited early in pass 2 may
depend on an index entry a row visited LATE in pass 1 contributed — there is
no way to know, for any given row, whether cross-referencing it is safe until
pass 1 has seen the WHOLE list. That is genuine cross-row dependency (the same
shape _dq_common.run_apply()'s docstring describes for its own callers that
need "repeated/random access... across rows"), not lrcpwa_refresh.py's "large
population of independent pure-per-row work" — so this script keeps the
function's own two-pass algorithm completely UNCHANGED and, like
_dq_common.run_apply(), materializes the full board as Listing objects (via
board_stream.iter_board_rows(), skipping only the sidecar merge) rather than
trying to stream-and-discard one row at a time.

A pre-mutation snapshot (scalars + a deep copy of raw) is taken for every row
BEFORE enrich_tax_owed() runs, and diffed against each row's post-mutation
state afterward to build a sparse patches dict — landed via ONE
web_artifact.patch_existing_rows() call instead of a whole-board
write_artifact(). enrichment_tax_owed.py never pops or deletes a raw key
(checked the whole file), so the diff is a plain add/change comparison, same
as lrcpwa_refresh.py's own _diff_raw() — no delete-as-None case to represent.

DISCLOSED BEHAVIOR CHANGE, deliberate (same class lrcpwa_refresh.py/
_dq_common.run_apply() already disclosed for themselves):
  1. A row that fails Listing.model_validate() is no longer silently DELETED
     from the board on the next write (load_board() drops it; write_artifact()
     then writes the board back without it). A patch-based write cannot delete
     anything it does not target: a malformed row simply does not get this
     run's tax_owed update and is otherwise left exactly as it was. Counted
     and printed, not hard-failed on.
  2. The OLD "nothing to do" gate (`not stats["stamped"] and not
     stats["cross_referenced"]`) only ever fired on a genuinely empty/disabled
     board, because enrich_tax_owed() re-stamps EVERY already-normalized tax
     row on every run (its own pass 1 unconditionally sets raw['tax_owed']
     again, even when the value does not change) — so on a normal re-run,
     `stamped` is a large nonzero number even when nothing actually changed,
     and the old script would call write_artifact() (a whole-board rewrite)
     anyway. The new gate is the actual patches dict: patch_existing_rows()
     itself already no-ops safely on an empty dict (returns `written: False`
     without touching the board — see its own docstring), so an idempotent
     re-run that re-derives the same values for every row now correctly
     writes nothing at all, where the old script silently rewrote the entire
     board every time.

RAW_KEEP already covers "tax_owed" ("*", full passthrough — confirmed by
reading web_artifact.RAW_KEEP directly), so there is no silent-drop-on-next-
full-rewrite risk the way a brand-new, unregistered key would have.

KNOWN INTERACTION WITH dedupe_key() IDENTITY (found while testing this
migration, not assumed). patch_existing_rows() identifies which board row(s)
a patch targets by Listing.dedupe_key() — and enrich_tax_owed()'s own
cross-reference mechanism exists SPECIFICALLY to find a second, separate
board row sharing the same (state, county, parcel_id) as a tax lead's own
record (a tax-delinquent-list row and a foreclosure-court row for the same
house, typically from different sources — not something dedupe() would have
already merged, since they are genuinely different leads, not duplicates of
each other). Both rows therefore share dedupe_key()'s strongest (parcel)
branch, by construction, every single time this cross-reference mechanism
actually fires. patch_existing_rows()'s own docstring already names this
general case ("a dedupe_key() matching MORE than one existing row... the
same identity is, by this codebase's own definition, the same property, so
the same field update is correct for all of them... should be rare") and
already counts it (`duplicate_key_matches`) rather than silently guessing —
but for THIS script specifically, it is not rare, it is the designed case:
when it fires, patch_existing_rows() applies ONE combined patch (whichever
of the two rows' diffs this script computed last, in board order) to BOTH
matching rows, so the "own_record" row and the "parcel_cross_ref" row can
end up carrying the IDENTICAL raw['tax_owed'] (same balance either way —
the enrichment only ever cross-references an identical balance/kind/source
onto the target — but potentially the "wrong" one of the two `basis` labels
on whichever row's patch lost the last-write race). This is a pre-existing
property of patch_existing_rows()'s one-patch-per-identity contract, not a
defect this migration introduces — the original load_board()/write_artifact()
script never had it (it mutated each Listing OBJECT directly, by position,
never by a shared string key) — so it is disclosed here rather than silently
inherited. Mitigating it generally (teaching patch_existing_rows() to apply
DIFFERENT patches to rows sharing one identity) is out of scope for this
plumbing migration; `tests/test_run_tax_owed_normalize_patch_integration.py`
proves the actual behavior (both rows end up with the same balance, the
collision is visible via `duplicate_key_matches`, nothing is silently
corrupted to an unrelated value) rather than ignoring it.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLoadDropError, board_lock, patch_existing_rows, _raise_if_board_too_large_to_patch,
)


def _light_rows(docs: Path) -> list[Listing]:
    """The board as Listing objects, WITHOUT the lazy-detail sidecar merged into raw -- see this
    module's own docstring (CLASSIFICATION) for why that is safe for enrich_tax_owed(). Same
    contract as _dq_common._light_rows()/web_artifact.load_board(): full validation (real enums/
    coercion), malformed rows dropped and counted, load fails above BOARD_LOAD_MAX_DROP_RATE
    (BOARD_LOAD_ALLOW_DROPS=1 overrides). Self-contained (not imported from _dq_common) so this
    script does not take on _dq_common's dq-fix-script-specific contract (apply_fn/backup/
    required-raw-key-list shape) it does not otherwise need -- the same choice lrcpwa_refresh.py made."""
    import os as _os
    from foreclosure_scraper.board_stream import iter_board_rows
    out: list[Listing] = []
    dropped = 0
    total = 0
    for total, rec in enumerate(iter_board_rows(docs / "listings.json.gz"), start=1):
        try:
            out.append(Listing.model_validate(rec))
        except Exception:  # noqa: BLE001 - counted below, same contract as load_board()
            dropped += 1
    rate = (dropped / total) if total else 0.0
    if dropped:
        limit = float(_os.environ.get("BOARD_LOAD_MAX_DROP_RATE", "0.001"))
        if rate > limit and _os.environ.get("BOARD_LOAD_ALLOW_DROPS", "").strip().lower() not in ("1", "true", "yes"):
            raise BoardLoadDropError(
                f"run_tax_owed_normalize dropped {dropped:,} of {total:,} rows ({rate:.3%}) "
                f"building its working set, over the {limit:.3%} limit. "
                f"BOARD_LOAD_ALLOW_DROPS=1 proceeds anyway."
            )
    return out


def _snapshot(rows: list[Listing]) -> list[tuple[str | None, dict, dict | None]]:
    """Pre-mutation (dedupe_key(), scalars, deep-copied raw) for every row, taken BEFORE
    enrich_tax_owed() runs -- enrich_tax_owed() never touches an identity field (state/county/
    parcel_id/street_address/zip_code/case_number/source_url), so capturing the key up front vs.
    after makes no practical difference here, but doing it unconditionally (not as a targeted
    exception) is the same safe-by-construction default resolver_backfill_parcel.py's/
    lrcpwa_refresh.py's own identity-field hazards are handled with."""
    out = []
    for li in rows:
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a row too malformed to key is simply unpatchable
            key = None
        scalars = li.model_dump(mode="json", exclude={"raw"})
        raw_copy = copy.deepcopy(li.raw) if isinstance(li.raw, dict) else None
        out.append((key, scalars, raw_copy))
    return out


def _diff_raw(before: dict | None, after: dict | None) -> dict:
    """Add/change-only diff -- enrichment_tax_owed.py never pops or deletes a raw key (verified
    by reading the whole module), so there is no delete-as-None case to represent here, unlike
    this week's backfill_derivation_flags.py/run_pending_signal_enrichers.py migrations."""
    before = before or {}
    after = after or {}
    return {k: v for k, v in after.items() if before.get(k) != v}


def _diff_to_patches(rows: list[Listing], pre: list[tuple]) -> dict[str, dict]:
    patches: dict[str, dict] = {}
    for li, (key, before_scalars, before_raw) in zip(rows, pre):
        if key is None:
            continue
        update: dict = {}
        after_scalars = li.model_dump(mode="json", exclude={"raw"})
        for k, v in after_scalars.items():
            if before_scalars.get(k) != v:
                update[k] = v
        raw_update = _diff_raw(before_raw, li.raw if isinstance(li.raw, dict) else None)
        if raw_update:
            update["raw"] = raw_update
        if update:
            patches[key] = update
    return patches


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="tax_owed_normalize")
    with lock:
        if not args.dry_run:
            # Fail before the expensive full-list build, not after -- the same ceiling
            # patch_existing_rows() itself re-checks before writing.
            _raise_if_board_too_large_to_patch(docs)
        rows = _light_rows(docs)
        before = len(rows)
        print(f"board rows: {before:,}")

        pre = _snapshot(rows)
        stats = enrich_tax_owed(rows)  # UNCHANGED function, same two-pass algorithm
        print(stats)

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        if not stats.get("stamped") and not stats.get("cross_referenced"):
            print("\nnothing to do.")
            return 0

        assert len(rows) == before, "row count changed — refusing to write"
        patches = _diff_to_patches(rows, pre)
        pstats = patch_existing_rows(patches, {"tax_owed_normalize": stats}, docs_dir=docs)
        existing = f"{pstats['existing']:,}" if pstats["existing"] is not None else "(no patch attempted)"
        print(f"\nwrote board: patched {pstats['applied']:,}/{len(patches):,} changed row(s) "
              f"(existing board: {existing}) | tax_owed stamped on {stats['stamped']:,}")
        if pstats.get("duplicate_key_matches"):
            # See this module's own docstring, "KNOWN INTERACTION WITH dedupe_key() IDENTITY" --
            # expected to fire on real cross-referenced parcels, never silent.
            print(f"NOTE: {pstats['duplicate_key_matches']:,} patch(es) matched more than one "
                  f"board row sharing a dedupe_key() (own-record + cross-ref rows on the same "
                  f"parcel) — the same combined update landed on all of them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
