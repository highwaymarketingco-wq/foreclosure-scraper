#!/usr/bin/env python3
"""Run the raw-key enrichers wired into main.py after the last full pipeline
landing, directly against the existing board -- WITHOUT a full scrape-everything
main.py pass.

WHY THIS EXISTS
    docs/completeness_audit_2026-09-29.md, Section 6: 8 signals were wired into
    main.py's run() between 2026-09-28 19:59 and 2026-09-29 12:47 (evening of
    the last full landing, commit 7f78473a, through the morning after) and show
    0 live rows on the board -- not because they're broken, but because no full
    main.py pass has executed since they were wired. All 8 are either pure
    compute over raw fields ALREADY on the board (no new scrape needed) or free/
    keyless public-API enrichers that already run this same way elsewhere in the
    pipeline (see scripts/catchup_failed_enrichers.py, scripts/enrich_gaps.py --
    this script is the same shape, generalized to this batch):

        liensnc_posthumous_filing   enrichment_liensnc_posthumous  (offline join)
        platted_lots                enrichment_platted_lots        (offline regex)
        divorce_no_subsequent_deed  enrichment_divorce_no_subsequent_deed (offline join)
        notice_service_defect       enrichment_notice_service_defect      (offline join)
        jail_booking_new            enrichment_jail_bookings       (free county roster APIs)
        bop_federal                 enrichment_bop_federal         (free bop.gov, keyless)
        landlocked + cemetery_proximity  enrichment_land_buildability (free NC OneMap ArcGIS)
        repeat_foreclosure_filing   enrichment_foreclosure_docket_history (offline sidecar join)

    NOT included: heir_naming_publication. That one is a SCRAPER
    (counties.column_legal_notices' SC quiet-title parsing), not an enrichment
    tag -- it needs scripts/run_scoped_scrapers.py --slugs counties.column_legal_notices
    instead, which actually fetches new notices. Running it here would do nothing
    (this script never scrapes).

USAGE
    python3 scripts/run_pending_signal_enrichers.py [--dry-run] [--only KEY ...]

    Refuses to run while the engine or another board writer looks to be running.
    Run it under the board lock, same as any board writer:

        scripts/with_board_lock.sh pending_signal_enrichers -- \\
            .venv/bin/python scripts/run_pending_signal_enrichers.py

    --dry-run loads the board, runs every step, prints before/after counts, and
    writes nothing. Same idempotence guarantee as the enrichers themselves: a
    second run only adds newly-eligible rows (a fresh jail booking, a newly
    parsed platted-lot description), it never un-tags or duplicates a hit.

BOARD I/O REWRITE (2026-10-02, docs/HANDOFF.md item 42, same failure class as
run_tax_owed_normalize.py's/backfill_derivation_flags.py's/lrcpwa_refresh.py's/
_dq_common.run_apply()'s 2026-10-01/02 rewrites). This used to call
load_board() to build the WHOLE board, run all 8 steps over it in place, then
write_artifact(listings, ...) -- the double materialization (write_artifact()'s
`payload = [_to_dict(li) for li in listings]`, a SECOND full copy on top of
load_board()'s own Listing list) that kernel-OOM-killed a real production
attempt against this exact board on a 23GB Oracle VM the same day (confirmed
via `journalctl -k`, anon-rss:24GB at kill time).

CLASSIFICATION (read all 8 enrichment modules in full, not assumed). None of
the 8 reads a LAZY_DETAIL_KEYS field ("vision"/"foreclosure_sold_comps"/
"comps"/"cama"/"rent_comps" -- grepped all 8 modules; the three incidental
hits were "supervision"/"subdivision" substring matches on "vision", not the
sidecar key), so the slim board_stream.iter_board_rows() reader (no sidecar
merge) is sufficient and correct, same choice run_tax_owed_normalize.py's and
_dq_common.run_apply()'s own callers made. None of the 8 is a pure per-row
function the way backfill_derivation_flags.py's enrich_derivation_flags()
turned out to be, either -- every one does genuine whole-list work: the four
async/network-bound steps (bop_federal, jail_bookings, land_buildability,
foreclosure_docket_history) each select a BOUNDED per-run query target subset
by scanning every row's current check-stamp/eligibility state first (e.g.
enrich_bop_federal()'s _select_targets() sorts ALL candidate rows by
never-checked-first/oldest-stamp before slicing to max_queries), and the
offline joins (liensnc_posthumous, divorce_no_subsequent_deed) cross-reference
one row's resolved-name/date fields against facts carried on OTHER rows
(state-scoped, per their own module docstrings). That is the same "large
population evaluated together, not independent per-row work" shape
_dq_common.run_apply()'s docstring describes for its own callers -- so this
follows run_tax_owed_normalize.py's/_dq_common.run_apply()'s full-
materialization pattern (board_stream.iter_board_rows() into a complete
list[Listing], no sidecar), not lrcpwa_refresh.py's bounded per-row streaming:
a snapshot is taken of every row BEFORE any step runs, the SAME STEPS loop /
_run_one() dispatch runs UNCHANGED over that one list (every step's own
internal target-selection logic, budget caps, and cross-row joins are
untouched), then every row is diffed against its own pre-run snapshot and
landed in ONE web_artifact.patch_existing_rows() call instead of a whole-
board write_artifact().

ONE RAW-KEY DELETION HAZARD FOUND among the 8 steps (grepped all 8 modules for
`.pop(`/`del li.raw`/`del raw[`): enrichment_bop_federal.py's
`li.raw.pop("bop_check", None)`, which fires when a real match is later found
for a name previously stamped a "no match" miss (raw['bop_check'] is itself a
negative-cache stamp -- "RAW_KEEP['bop_check'] = ... answered NO-match stamp
for enrichment_bop_federal, same shape as incarceration_check"). Verified safe
to represent as raw['bop_check'] = None via patch_existing_rows()'s merge-only
write (it has no delete primitive -- see its own docstring): grepped every
reader of "bop_check" in src/+scripts/+docs/dashboard.js -- the only reader is
enrichment_bop_federal.py's own _stamp_of(), which does
`li.raw.get("bop_check")`, never a presence test. No other raw key is ever
popped/deleted by any of the other 7 modules (checked each one in full).

LOCK HARDENING (disclosed, intentional addition, not a silent behavior
change). The original script never called board_lock() itself -- it relied
entirely on the external `scripts/with_board_lock.sh` wrapper (this file's own
USAGE section above already says to run it that way) plus _engine_running()'s
pgrep heuristic. write_artifact() already REQUIRED the lock via
require_board_lock() before this migration (same as every board writer, via
the FORECLOSURE_BOARD_LOCK_HELD env var the wrapper exports), so a standalone
invocation without the wrapper was already refused at the write step -- this
migration does not relax that in any way. What changes: this script now also
wraps the whole read -> enrich -> patch span in `with board_lock(...)` itself,
the same belt-and-suspenders lrcpwa_refresh.py/run_tax_owed_normalize.py/
backfill_derivation_flags.py already use (board_lock() is reentrant -- see its
own docstring -- so this is a no-op when the shell wrapper already holds it,
and gives a standalone/by-hand invocation real protection instead of relying
solely on the pgrep heuristic, which is advisory and can race).

DISCLOSED BEHAVIOR CHANGE, deliberate (same class as this week's other
migrations): a row that fails Listing.model_validate() is no longer silently
DELETED from the board on the next write -- it simply does not get this run's
signal updates and is otherwise left exactly as it was; counted and printed,
not hard-failed on.

RAW_KEEP already covers every key these 8 steps write ("liensnc_posthumous_
filing", "platted_lots", "divorce_no_subsequent_deed", "notice_service_
defect", "jail_booking_new", "bop_federal", "bop_check", "landlocked",
"cemetery_proximity", "repeat_foreclosure_filing" -- all "*", full passthrough,
confirmed by reading web_artifact.RAW_KEEP directly), so there is no silent-
drop-on-next-full-rewrite risk the way a brand-new, unregistered key would
have.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLoadDropError, board_lock, patch_existing_rows, _raise_if_board_too_large_to_patch,
)
from foreclosure_scraper.main import _await_capped  # noqa: E402

STEPS = [
    "liensnc_posthumous",
    "platted_lots",
    "divorce_no_subsequent_deed",
    "notice_service_defect",
    "jail_bookings",
    "bop_federal",
    "land_buildability",
    "foreclosure_docket_history",
]

# raw keys this script reports on (one step can stamp more than one key)
RAW_KEYS = [
    "liensnc_posthumous_filing",
    "platted_lots",
    "divorce_no_subsequent_deed",
    "notice_service_defect",
    "jail_booking_new",
    "bop_federal",
    "landlocked",
    "cemetery_proximity",
    "repeat_foreclosure_filing",
]


def _light_rows(docs: Path) -> list[Listing]:
    """The board as Listing objects, WITHOUT the lazy-detail sidecar merged into raw -- see this
    module's own docstring (CLASSIFICATION) for why that is safe for all 8 steps. Same contract
    as run_tax_owed_normalize.py's/_dq_common._light_rows()/web_artifact.load_board(): full
    validation (real enums/coercion), malformed rows dropped and counted, load fails above
    BOARD_LOAD_MAX_DROP_RATE (BOARD_LOAD_ALLOW_DROPS=1 overrides). Self-contained (not imported
    from _dq_common) so this script does not take on _dq_common's dq-fix-script-specific contract
    it does not otherwise need -- the same choice lrcpwa_refresh.py/run_tax_owed_normalize.py made."""
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
                f"run_pending_signal_enrichers dropped {dropped:,} of {total:,} rows ({rate:.3%}) "
                f"building its working set, over the {limit:.3%} limit. "
                f"BOARD_LOAD_ALLOW_DROPS=1 proceeds anyway."
            )
    return out


def _snapshot(rows: list[Listing]) -> list[tuple[str | None, dict, dict | None]]:
    """Pre-mutation (dedupe_key(), scalars, deep-copied raw) for every row, taken BEFORE any of
    the 8 steps run -- none of them touches an identity field (state/county/parcel_id/
    street_address/zip_code/case_number/source_url; checked all 8 modules), so capturing the key
    up front vs. after makes no practical difference here, but doing it unconditionally is the
    same safe-by-construction default resolver_backfill_parcel.py's/lrcpwa_refresh.py's own
    identity-field hazards are handled with."""
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


#: enrichment_bop_federal.py's li.raw.pop("bop_check", None) is the ONE raw-key deletion among
#: all 8 steps (grepped every module) -- see this file's own docstring, "ONE RAW-KEY DELETION
#: HAZARD FOUND", for why representing it as raw['bop_check'] = None is verified safe.
_RAW_DELETE_SAFE_AS_NONE = frozenset({"bop_check"})


def _diff_raw(before: dict | None, after: dict | None) -> dict:
    before = before or {}
    after = after or {}
    out = {k: v for k, v in after.items() if before.get(k) != v}
    for k in (set(before) - set(after)) & _RAW_DELETE_SAFE_AS_NONE:
        out[k] = None
    return out


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


def _engine_running() -> bool:
    # The pattern must not begin with "-": pgrep reads a leading dash as an
    # option, matches nothing, and the guard silently never fires.
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|load_board"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _truthy(v) -> bool:
    return v not in (None, "", [], {})


def _counts(listings) -> dict:
    out: dict = {}
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        for k in RAW_KEYS:
            if _truthy(raw.get(k)):
                out[k] = out.get(k, 0) + 1
    return out


async def _run_one(name: str, listings: list, dry_run: bool = False) -> dict:
    if name == "liensnc_posthumous":
        from foreclosure_scraper.enrichment_liensnc_posthumous import enrich_liensnc_posthumous
        return enrich_liensnc_posthumous(listings) or {}
    if name == "platted_lots":
        from foreclosure_scraper.enrichment_platted_lots import enrich_platted_lots
        return enrich_platted_lots(listings) or {}
    if name == "divorce_no_subsequent_deed":
        from foreclosure_scraper.enrichment_divorce_no_subsequent_deed import (
            enrich_divorce_no_subsequent_deed,
        )
        return enrich_divorce_no_subsequent_deed(listings) or {}
    if name == "notice_service_defect":
        from foreclosure_scraper.enrichment_notice_service_defect import enrich_notice_service_defect
        return enrich_notice_service_defect(listings) or {}
    if name == "jail_bookings":
        from foreclosure_scraper.enrichment_jail_bookings import enrich_jail_bookings
        # dry_run reaches jail_roster_history so a --dry-run pass here cannot
        # silently consume the sidecar's "new booking" detection for real (see
        # enrichment_jail_bookings.py's "DRY-RUN SIDECAR BUG" docstring note).
        return await _await_capped(
            enrich_jail_bookings(listings, dry_run=dry_run), "jail_bookings") or {}
    if name == "bop_federal":
        from foreclosure_scraper.enrichment_bop_federal import enrich_bop_federal
        return await _await_capped(enrich_bop_federal(listings), "bop_federal") or {}
    if name == "land_buildability":
        from foreclosure_scraper.enrichment_land_buildability import enrich_land_buildability
        return await _await_capped(enrich_land_buildability(listings), "land_buildability") or {}
    if name == "foreclosure_docket_history":
        from foreclosure_scraper.enrichment_foreclosure_docket_history import (
            enrich_foreclosure_docket_history,
        )
        return await _await_capped(
            enrich_foreclosure_docket_history(listings), "foreclosure_docket_history") or {}
    raise ValueError(f"unknown step {name!r}")


async def _run(which: list[str], docs: Path, *, dry_run: bool) -> int:
    t0 = time.time()
    listings = _light_rows(docs)
    print(f"board: {len(listings):,} leads ({time.time() - t0:.1f}s load)", flush=True)
    before = _counts(listings)
    print(f"before: {before}", flush=True)

    # Snapshot every row BEFORE any step runs (dry_run never needs it -- nothing gets patched).
    pre = None if dry_run else _snapshot(listings)

    stats: dict[str, dict] = {}
    for name in which:
        print(f"\n--- {name}", flush=True)
        t1 = time.time()
        try:
            stats[name] = await _run_one(name, listings, dry_run=dry_run)
            print(f"    {stats[name]}  ({time.time() - t1:.1f}s)", flush=True)
        except Exception as exc:  # noqa: BLE001 - one enricher must not stop the rest
            print(f"    FAILED: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
            stats[name] = {"failed": f"{type(exc).__name__}: {str(exc)[:200]}"}

    after = _counts(listings)
    print("\n=== before -> after (delta) ===", flush=True)
    for k in RAW_KEYS:
        b, a = before.get(k, 0), after.get(k, 0)
        print(f"  {k}: {b} -> {a} (+{a - b})", flush=True)

    if dry_run:
        print("\ndry run -- board not written", flush=True)
        return 0

    patches = _diff_to_patches(listings, pre)
    pstats = patch_existing_rows(
        patches,
        {"notes": f"pending signal enrichers (2026-09-29 audit follow-up): {', '.join(which)}"},
        docs_dir=docs)
    existing = f"{pstats['existing']:,}" if pstats["existing"] is not None else "(no patch attempted)"
    print(f"\nwrote board: patched {pstats['applied']:,}/{len(patches):,} changed row(s) "
          f"(existing board: {existing})", flush=True)
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", action="append", choices=STEPS,
                    help="run just these steps (default: all)")
    args = ap.parse_args()

    if _engine_running():
        print("engine/backfill/another loader is running -- refusing to touch the board",
              file=sys.stderr)
        return 1

    which = args.only or STEPS
    docs = REPO / "docs"

    if args.dry_run:
        return await _run(which, docs, dry_run=True)

    # LOCK HARDENING (see this module's own docstring) -- reentrant, a no-op when
    # scripts/with_board_lock.sh already holds it, real protection when run by hand.
    with board_lock(REPO, owner="pending_signal_enrichers"):
        # Fail before the expensive full-list build, not after -- the same ceiling
        # patch_existing_rows() itself re-checks before writing.
        _raise_if_board_too_large_to_patch(docs)
        return await _run(which, docs, dry_run=False)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
