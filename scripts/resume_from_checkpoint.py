#!/usr/bin/env python3
"""Finish a full run that died after its last checkpoint: run main.py's REAL tail, then publish.

WHY THIS EXISTS (2026-10-05)
    The VM's 18h full run was OOM-killed one step before write_artifact, after scoring. Its last
    checkpoint (phase "dot_ocr", 270,232 leads) is post-scrape, post-merge, post-most-enrichment
    but PRE-scoring. scripts/recover_from_checkpoint.py publishes a checkpoint as-is -- unscored,
    so every HOT/WARM/COLD tier on the board would be the prior run's. This instead runs the
    part of main.run() that comes after that checkpoint, using the SAME functions run() calls
    (main.run_enrich_tail -> main.publish_tail), so the steps and their order cannot drift.

WHAT IT RUNS
    1. load the checkpoint (streamed; refuses one that is too old, see --max-age-h)
    2. the NC SOS hand-off apply step (no network). It sits BEFORE the dot_ocr checkpoint in
       main.run(), so a dot_ocr resume would otherwise skip it. Idempotent.
    3. main.run_enrich_tail(): every step after the dot_ocr checkpoint, network enrichers
       included, each under its normal per-phase cap (divorce, name resolver, ACPASS, resolved
       catch-up incl. vision, tax_relief, rollback, court_bid, fhfa_value, dew_liens, valuation,
       assessor_card, equity, ..., score_board, every post-score signal, burke history, lrcpwa
       photos, homepath uuids, board quality/QA, the run summary, the count-drop guard).
       A failing enricher is logged and skipped exactly as in run().
    4. checkpoint the scored board as phase "pre_publish" (+ data/checkpoint/resume_state.json)
       so a failed publish can be retried with --publish-only instead of repeating step 3.
       The checkpoint being replaced is archived first under data/checkpoint_archive/.
    5. main.publish_tail(): write_artifact under the board lock; then, unlike run(), NO sold-pool
       file (a resume has no sold pool: it would write []), NO run_health.json and NO Sheet
       export / digest email (there is no per-source scrape status to report), and NO
       source_history update (the failed run already recorded this run's real per-source
       counts). run_meta.json carries the prior per-source health forward, labelled stale.
    Committing and pushing docs/ is the wrapper's job (deploy/oracle/vm_resume.sh), the same way
    vm_run.sh does it after main.

PLACEHOLDER-TWIN CLEAN-UP (opt-in, 2026-10-05)
    The 10/5 run's merge kept ~380 parcels twice: the re-scraped row with a "no number" sentinel
    situs ("0 PATCH DR") beside the aging prior copy of the SAME source's row that the parcel
    cache had given a real situs ("499 PATCH DR"). See src/foreclosure_scraper/placeholder_twins.py
    (rule, guards, real examples); board_persist.merge_prior_board() no longer does this.
    --collapse-dry-run streams the checkpoint FILE (two passes, read-only, no lock, no Listing
    objects) and prints the groups that would collapse: counts by source, skip reasons, a sample,
    and a plan digest. Applying is OFF unless RESUME_COLLAPSE_PLACEHOLDER_TWINS is set (or
    --collapse-placeholder-twins is passed) for --publish-only / --run: right after the
    pre_publish checkpoint is loaded (or saved) and before write_artifact, each group's live row
    absorbs its aging copies via Listing.merge() (live row first) and the copies are dropped.
    Set the variable to the digest the dry run printed to apply exactly the reviewed plan (a
    different plan is then skipped with an error and the board is published uncollapsed); "1"
    applies whatever the plan is at publish time.

RESEEN-ROW REPAIR (opt-in, same dry run, same digest, 2026-10-05)
    main.run()'s second dedupe() folded some LIVE rows into the aged prior copies
    merge_prior_board() kept, aged rows first, so the live row came out tagged presumed
    withdrawn (raw['pulled_sale'], the status, then board_quality's stale_case and HOT->WARM).
    dedupe.merge_rows() fixes future runs; see placeholder_twins.repair_reseen() for this one.
    Pass the run's start with --seen-since (dry run) and RESUME_SEEN_SINCE (publish), e.g.
    2026-10-05T01:27:29Z for the 10/5 run (orchestrator.start in its log): a tagged row whose
    last_seen is at or after it absorbed a row created this run. The plan, the digest and the
    apply then cover both parts; without it they are the twins-only plan and digest, unchanged.

USAGE
    python3 scripts/resume_from_checkpoint.py                 # show the checkpoint, change nothing
    python3 scripts/resume_from_checkpoint.py --run           # steps 1-5
    python3 scripts/resume_from_checkpoint.py --enrich-only   # steps 1-4 (stop before publish)
    python3 scripts/resume_from_checkpoint.py --publish-only  # step 5 from a pre_publish checkpoint
    python3 scripts/resume_from_checkpoint.py --collapse-dry-run [--seen-since ISO] [--plan-out F] [--sample N]
    RESUME_COLLAPSE_PLACEHOLDER_TWINS=<digest> [RESUME_SEEN_SINCE=ISO] bash deploy/oracle/vm_resume.sh --publish-only
Exit codes follow main.cli(): 0 ok, 3 write failed, 6 scoring failed, 75 lock busy, 1 usage.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import checkpoint  # noqa: E402
from foreclosure_scraper import main as M  # noqa: E402  (also runs load_dotenv(), like the run)

STATE_FILE = "resume_state.json"


def _rss() -> dict:
    """This process's memory, Linux /proc (VmRSS, VmSwap, VmHWM) in MiB; {} elsewhere."""
    out: dict = {}
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            k, _, v = line.partition(":")
            if k in ("VmRSS", "VmSwap", "VmHWM"):
                out[k] = round(int(v.split()[0]) / 1024, 1)
    except OSError:
        pass
    return out


def _mark(stage: str, **kw) -> None:
    M.log.info("resume.stage", stage=stage, **_rss(), **kw)


def _archive_checkpoint() -> Path | None:
    """Copy the current checkpoint aside before it is overwritten (never moved: the live one
    must stay loadable until the new save has atomically replaced it)."""
    m = checkpoint.manifest() or {}
    src = checkpoint.CHECKPOINT_DIR
    board = src / checkpoint.BOARD_FILE
    if not board.exists():
        return None
    tag = f"{m.get('phase', 'unknown')}_{str(m.get('saved_at', 'na')).replace(':', '')}"
    dest = src.parent / "checkpoint_archive" / tag
    if (dest / checkpoint.BOARD_FILE).exists():
        return dest
    free = shutil.disk_usage(src).free
    need = board.stat().st_size * 2 + (1 << 30)
    if free < need:
        M.log.warning("resume.archive_skipped_low_disk", free_mb=free >> 20, need_mb=need >> 20)
        return None
    dest.mkdir(parents=True, exist_ok=True)
    for name in (checkpoint.BOARD_FILE, checkpoint.MANIFEST_FILE):
        if (src / name).exists():
            shutil.copy2(src / name, dest / name)
    M.log.info("resume.checkpoint_archived", path=str(dest))
    return dest


def _load(max_age_h: float | None, want_phase: str | None) -> list | None:
    m = checkpoint.manifest() or {}
    if want_phase and m.get("phase") != want_phase:
        print(f"checkpoint phase is {m.get('phase')!r}, expected {want_phase!r}", file=sys.stderr)
        return None
    t0 = time.monotonic()
    listings = checkpoint.load(max_age_h=max_age_h)
    _mark("checkpoint_loaded", leads=len(listings or []), phase=m.get("phase"),
          seconds=round(time.monotonic() - t0, 1))
    return listings


async def _enrich(listings: list, args) -> tuple[M.TailState, dict]:
    from foreclosure_scraper.config import RuntimeConfig
    from foreclosure_scraper.sos_agent_handoff import apply_sos_agent_handoff

    enrichment_stats: dict = {}
    # Same call, same guard as main.run() (it sits before the dot_ocr checkpoint there).
    try:
        s = apply_sos_agent_handoff(listings)
        if s:
            enrichment_stats["sos_agent_handoff"] = s
    except Exception:  # noqa: BLE001
        import traceback
        M.log.error("sos_agent_handoff.failed", traceback=traceback.format_exc())
    _mark("sos_handoff_applied", stats=enrichment_stats.get("sos_agent_handoff"))

    st = M.TailState(
        enriched=listings, enrichment_stats=enrichment_stats, errors=[],
        cfg=RuntimeConfig.from_env(),
        update_source_health=False, write_sold_pool=False, write_run_health=False,
        export_and_email=False,
    )
    t0 = time.monotonic()
    summary = await M.run_enrich_tail(st)
    _mark("enrich_tail_done", leads=len(st.enriched), seconds=round(time.monotonic() - t0, 1),
          scoring_failed=st.scoring_failed)
    return st, summary


def _resume_note(m: dict) -> str:
    return (f"resumed from checkpoint phase {m.get('phase')!r} saved {m.get('saved_at')} "
            f"({m.get('count')} leads) by scripts/resume_from_checkpoint.py")


def _save_state(st: M.TailState, summary: dict) -> None:
    state = {"summary": summary, "enrichment_stats": st.enrichment_stats,
             "errors": st.errors, "scoring_failed": st.scoring_failed}
    p = checkpoint.CHECKPOINT_DIR / STATE_FILE
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, default=str, ensure_ascii=False))
    os.replace(tmp, p)


COLLAPSE_ENV = "RESUME_COLLAPSE_PLACEHOLDER_TWINS"
SEEN_SINCE_ENV = "RESUME_SEEN_SINCE"


def _collapse_wanted(args) -> str:
    """'' (off, the default), '1' (apply whatever the plan is) or a plan digest to require."""
    v = (args.collapse_placeholder_twins or os.environ.get(COLLAPSE_ENV) or "").strip()
    return "" if v.lower() in ("", "0", "no", "off", "false") else v


def _seen_since(args) -> str | None:
    """The run start that turns the reseen-row repair on (--seen-since, else RESUME_SEEN_SINCE);
    None (the default) plans the placeholder twins only."""
    v = (getattr(args, "seen_since", None) or os.environ.get(SEEN_SINCE_ENV) or "").strip()
    return v or None


def _collapse_dry_run(args) -> int:
    """Read-only: stream the checkpoint file twice and print the placeholder-twin plan."""
    from foreclosure_scraper.board_parts import iter_gz_rows
    from foreclosure_scraper.placeholder_twins import plan_collapse

    m = checkpoint.manifest() or {}
    if args.phase and m.get("phase") != args.phase:
        print(f"checkpoint phase is {m.get('phase')!r}, expected {args.phase!r}", file=sys.stderr)
        return 1
    board = checkpoint.CHECKPOINT_DIR / checkpoint.BOARD_FILE
    t0 = time.monotonic()
    seen = _seen_since(args)
    try:
        plan = plan_collapse(lambda: iter_gz_rows(board), seen_since=seen)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if isinstance(m.get("count"), int) and plan.rows_scanned != m["count"]:
        print(f"read {plan.rows_scanned} rows, manifest says {m['count']}: refusing a partial plan",
              file=sys.stderr)
        return 1
    out = plan.summary(sample=args.sample)
    out.update(phase=m.get("phase"), saved_at=m.get("saved_at"),
               seconds=round(time.monotonic() - t0, 1), **_rss())
    print(json.dumps(out, indent=1, default=str))
    if args.plan_out:
        full = plan.summary(sample=max(len(plan.groups), len(plan.reseen)))
        Path(args.plan_out).write_text(json.dumps(full, indent=1, default=str))
        print(f"full plan ({len(plan.groups)} groups) written to {args.plan_out}")
    env = f"{COLLAPSE_ENV}={plan.digest()}" + (f" {SEEN_SINCE_ENV}={seen}" if seen else "")
    print(f"\nto apply exactly this plan at publish:\n  {env} "
          "setsid nohup bash deploy/oracle/vm_resume.sh --publish-only >/dev/null 2>&1 < /dev/null &")
    return 0


def _collapse(st: M.TailState, summary: dict, wanted: str) -> None:
    """Opt-in placeholder-twin collapse on the in-memory board, before write_artifact. Any
    failure leaves the board as loaded (published uncollapsed), never half-collapsed."""
    from foreclosure_scraper.placeholder_twins import apply_collapse, plan_collapse

    t0 = time.monotonic()
    rows = st.enriched
    try:
        plan = plan_collapse(lambda: rows, seen_since=os.environ.get(SEEN_SINCE_ENV) or None)
    except ValueError as exc:
        M.log.error("resume.placeholder_twins_skipped", reason=str(exc))
        return
    digest = plan.digest()
    if wanted != "1" and wanted != digest:
        M.log.error("resume.placeholder_twins_skipped", reason="plan digest differs from the "
                    "reviewed one", wanted=wanted, digest=digest, groups=len(plan.groups),
                    rows_dropped=plan.rows_dropped)
        return
    try:
        res = apply_collapse(rows, plan)
    except Exception as exc:  # noqa: BLE001 - apply_collapse checks everything before mutating
        M.log.error("resume.placeholder_twins_skipped", reason=f"{type(exc).__name__}: {exc}")
        return
    note = (f"; collapsed {res['rows_dropped']} placeholder-twin duplicate rows "
            f"({res['groups']} parcels, plan {digest})")
    if plan.seen_since is not None:
        note += (f"; removed the presumed-withdrawn tag from {res['reseen_repaired']} rows this run "
                 f"saw (HOT restored on {res['reseen'].get('hot_restored', 0)}; tier counts in this "
                 f"summary predate it)")
    summary["notes"] = str(summary.get("notes") or "") + note
    _mark("placeholder_twins_collapsed", **res, by_source=dict(plan.by_source().most_common()),
          seconds=round(time.monotonic() - t0, 1))


def _publish(st: M.TailState, summary: dict) -> int:
    t0 = time.monotonic()
    rc = M.publish_tail(st, summary)
    _mark("published" if rc in (M.EXIT_OK, M.EXIT_SCORE_FAILED) else "publish_failed",
          rc=rc, seconds=round(time.monotonic() - t0, 1))
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--run", action="store_true", help="enrich tail + pre_publish checkpoint + publish")
    g.add_argument("--enrich-only", action="store_true", help="stop after the pre_publish checkpoint")
    g.add_argument("--publish-only", action="store_true", help="publish a pre_publish checkpoint")
    g.add_argument("--collapse-dry-run", action="store_true",
                   help="read-only: print the placeholder-twin groups the checkpoint holds")
    ap.add_argument("--collapse-placeholder-twins", nargs="?", const="1", default=None,
                    metavar="DIGEST", help=f"collapse placeholder twins before publishing (also "
                    f"{COLLAPSE_ENV}=1|<digest>); off by default")
    ap.add_argument("--seen-since", default=None, metavar="ISO",
                    help=f"--collapse-dry-run: the run's start; also plans the reseen-row repair "
                         f"(publish reads {SEEN_SINCE_ENV}); off by default")
    ap.add_argument("--plan-out", default=None, help="--collapse-dry-run: write the full plan here")
    ap.add_argument("--sample", type=int, default=15, help="--collapse-dry-run: sample size")
    ap.add_argument("--max-age-h", type=float, default=None,
                    help="refuse a checkpoint older than this (default: checkpoint.MAX_AGE_H, 48)")
    ap.add_argument("--phase", default=None,
                    help="require this checkpoint phase (default: dot_ocr for --run/--enrich-only, "
                         "pre_publish for --publish-only)")
    args = ap.parse_args()
    os.chdir(REPO)      # data/checkpoint and the run's other relative paths, as vm_run.sh does

    m = checkpoint.manifest()
    if not m:
        print(f"no checkpoint in {checkpoint.CHECKPOINT_DIR}", file=sys.stderr)
        return 1
    age = checkpoint.age_hours()
    print(f"checkpoint: phase={m.get('phase')!r} leads={m.get('count')} saved={m.get('saved_at')} "
          f"age={age:.1f}h dir={checkpoint.CHECKPOINT_DIR}" if age is not None else f"checkpoint: {m}")
    if args.collapse_dry_run:
        return _collapse_dry_run(args)
    if not (args.run or args.enrich_only or args.publish_only):
        print("dry run -- pass --run, --enrich-only or --publish-only")
        return 0
    collapse = _collapse_wanted(args)
    if collapse and args.enrich_only:
        print("note: the placeholder-twin collapse only applies when publishing; ignored here")

    M._setup_logging()
    from foreclosure_scraper.web_artifact import BoardLockBusy, BoardMemoryPressure, board_lock
    want = args.phase or ("pre_publish" if args.publish_only else "dot_ocr")
    try:
        with board_lock(owner="resume_from_checkpoint",
                        max_runtime=int(os.environ.get("FULLRUN_LOCK_MAX_RUNTIME", "259200"))):
            _mark("start", mode="publish-only" if args.publish_only else
                  "enrich-only" if args.enrich_only else "run", phase=m.get("phase"))
            listings = _load(args.max_age_h, want)
            if not listings:
                print("checkpoint could not be loaded (wrong phase, too old or unreadable)",
                      file=sys.stderr)
                return 1

            if args.publish_only:
                sp = checkpoint.CHECKPOINT_DIR / STATE_FILE
                state = json.loads(sp.read_text()) if sp.exists() else {}
                from foreclosure_scraper.config import RuntimeConfig
                st = M.TailState(enriched=listings,
                                 enrichment_stats=state.get("enrichment_stats") or {},
                                 errors=state.get("errors") or [], cfg=RuntimeConfig.from_env(),
                                 update_source_health=False, write_sold_pool=False,
                                 write_run_health=False, export_and_email=False,
                                 scoring_failed=state.get("scoring_failed"))
                summary = state.get("summary") or {"notes": _resume_note(m)}
                if collapse:
                    _collapse(st, summary, collapse)
                return _publish(st, summary)

            # Archived BEFORE the tail: a scoring failure checkpoints "score_failed" over it
            # (main.run_enrich_tail does that on purpose), and the next save is pre_publish.
            _archive_checkpoint()
            st, summary = asyncio.run(_enrich(listings, args))
            del listings
            summary["notes"] = _resume_note(m) + "; " + str(summary.get("notes") or "")
            summary["recovered_from_checkpoint"] = True
            summary["checkpoint_phase"] = m.get("phase")

            t0 = time.monotonic()
            saved = checkpoint.save(st.enriched, "pre_publish",
                                    extra={"resumed_from": {k: m.get(k) for k in ("phase", "saved_at", "count")}})
            if saved:
                _save_state(st, summary)
            _mark("pre_publish_checkpoint", saved=saved, seconds=round(time.monotonic() - t0, 1))
            if args.enrich_only:
                return M.EXIT_SCORE_FAILED if st.scoring_failed else M.EXIT_OK
            if collapse:
                _collapse(st, summary, collapse)
            return _publish(st, summary)
    except BoardLockBusy as exc:
        print(f"resume: not started: {exc}", file=sys.stderr)
        return M.EXIT_LOCK_BUSY
    except BoardMemoryPressure as exc:
        print(f"resume: not started: {exc}", file=sys.stderr)
        return M.EXIT_LOCK_BUSY
    except M.ScoreBoardFailed as exc:
        print(f"resume: {exc}", file=sys.stderr)
        return M.EXIT_SCORE_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
