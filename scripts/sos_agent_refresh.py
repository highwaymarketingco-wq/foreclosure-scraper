"""Daily NC SOS registered-agent lookups: the MAC side of the Mac -> VM hand-off.

Fills raw['sos_agent'] (registered agent + officers = a free mailable contact) for entity-owned
NC leads, WITHOUT writing the board. Driven daily at 14:00 ET by launchd
`com.highway.foreclosure.sosagent` -> scripts/sos_agent_refresh.sh -> this script.

WHY IT NO LONGER WRITES THE BOARD (2026-10-05). The lookups worked (17-27 entities resolved a
day) and then patch_existing_rows() refused the 2,652 MB board (BoardLoadTooLarge) at the save
step, every day since late September; nothing cached the finds, so they were thrown away. The
Mac cannot write the board at all now -- the Oracle VM is the single board writer. So:

  1. ONE read-only stream of the board (board_stream.iter_board_rows(), no size ceiling, about
     300 MB peak): NC rows with an entity name and no sos_agent are lookup candidates, ranked
     exactly as before (HOT/WARM first via enrichment_sos_agent._prio(), first-seen order).
     Profiles already on the board seed the ledger (sos_agent_handoff.seed_from_board_profile).
  2. Candidates the ledger already answers are skipped: resolved (the VM applies it), an
     answered miss checked under 30 days ago, a no-answer under 3 days ago.
  3. The capped list goes through the REAL, unchanged enrichment_sos_agent._batch_lookup().
  4. Every answer is merged into the CUMULATIVE ledger docs/handoff/sos_agent_results.json
     (format: sos_agent_handoff.py's docstring), written before any git step so a failed push
     never loses a lookup.
  5. That one file is committed and pushed (run_stealth_sources.py's pattern: HANDOFF_PUSH=0
     skips git; pull --rebase before the push). The VM's nightly run attaches the profiles
     (sos_agent_handoff.apply_sos_agent_handoff()).

The board lock is gone from the lookup (nothing writes the board); it is taken only around the
git commit and the rebase, which rewrite the working tree (scripts/publish_helper.sh does the
same for its rebase). A separate run lock (logs/.sos_agent_refresh.lock) stops two SOS runs --
two stealth browsers on an 8 GB Mac -- from overlapping.

ADAPTIVE CAP: see sos_agent_handoff.py (choose_cap/next_cap). State: data/sos_agent_backoff.json.

RESULT SELECTION (2026-10-05): _batch_lookup() now opens only the search result that IS the
entity (enrichment_sos_agent.select_result()); a search with candidates but no confident match
comes back under outcome["ambiguous"] and is recorded as status "ambiguous" (never applied).
Every run first re-checks the ledger's resolved entries against the same rule
(sos_agent_handoff.recheck_resolved()): a failing one becomes "mismatch", is not applied by the
VM, and is re-queried here ahead of every other target. Rows that still carry a rejected
profile count as lookup candidates (the VM clears the profile from them on its next run).

Usage:
  uv run python scripts/sos_agent_refresh.py             # what the scheduled job runs
  uv run python scripts/sos_agent_refresh.py --dry-run   # scan + targets only: no lookups, no writes
  uv run python scripts/sos_agent_refresh.py --cap 10    # one-off small run (never raises the
                                                         # adaptive cap; a bad run still lowers it)
  HANDOFF_PUSH=0 uv run python scripts/sos_agent_refresh.py   # write the ledger, skip git
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("SOS_AGENT", "1")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import sos_agent_handoff as ho  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_sos_agent import (  # noqa: E402
    _batch_lookup, _entity_of, _prio, entity_key, stamp_profile,
)
from foreclosure_scraper.models import Listing  # noqa: E402

DOCS = REPO / "docs"
HANDOFF = REPO / "docs" / "handoff" / "sos_agent_results.json"
BACKOFF = REPO / "data" / "sos_agent_backoff.json"
RUN_LOCK = REPO / "logs" / ".sos_agent_refresh.lock"
PUSH = os.environ.get("HANDOFF_PUSH", "1") != "0"

_LIGHT_FIELDS = ("state", "owner_name", "defendant", "raw")


def _light_listing(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def scan_board(docs: Path, entities: dict, today: str) -> dict:
    """One streaming pass: seed the ledger from profiles already on the board and collect
    lookup candidates. Mirrors enrich_with_sos_agent()'s selection: NC rows with an entity
    name and no sos_agent dict; one candidate per entity_key under its first-seen spelling,
    ranked by the first-seen row's _prio(). A row whose profile the ledger REJECTED for its
    entity (sos_agent_handoff.row_profile_rejected(), the VM's own clear rule) is a candidate
    too: the VM takes that profile off it on its next run."""
    total = with_sos = seeded = unseedable = carrying_rejected = 0
    cand: dict[str, dict] = {}
    rejected = ho.rejected_sosids_by_key({"entities": entities})
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        sa = raw.get("sos_agent")
        li = _light_listing(rec)
        if isinstance(sa, dict):
            with_sos += 1
            if sa.get("sosid"):
                n = ho.seed_from_board_profile(entities, sa, _entity_of(li), today=today)
                seeded += n
                if not ho.seed_names_for_board_profile(sa, _entity_of(li)):
                    unseedable += 1
            if not ho.row_profile_rejected(sa, _entity_of(li), rejected):
                continue
            carrying_rejected += 1
        if rec.get("state") != "NC":
            continue
        name = _entity_of(li)
        if not name:
            continue
        k = entity_key(name)
        c = cand.get(k)
        if c is None:
            cand[k] = {"name": name, "prio": _prio(li), "order": len(cand), "rows": 1}
        else:
            c["rows"] += 1
    return {"total": total, "with_sos": with_sos, "seeded": seeded,
            "unseedable": unseedable, "carrying_rejected": carrying_rejected,
            "candidates": cand}


def pick_targets(cand: dict, entities: dict, cap: int, today: str) -> dict:
    """Split candidates by what the ledger knows; rank the due ones and cap them. A mismatch
    (a profile the ledger rejected under the 2026-10-05 matching rule) goes first of all, so
    the next run re-queries it; then by priority, never-checked names before due rechecks at
    the same priority, so each run advances the frontier."""
    pending_rows = pending_entities = not_due = 0
    due: list[tuple[int, int, int, str, str]] = []
    for k, c in cand.items():
        e = entities.get(k)
        if e and e.get("status") == "resolved":
            pending_entities += 1
            pending_rows += c["rows"]
            continue
        if not ho.is_due(e, today):
            not_due += 1
            continue
        first = 0 if (e or {}).get("status") == "mismatch" else 1
        due.append((first, c["prio"], 0 if e is None else 1, c["order"], c["name"], k))
    due.sort()
    return {"names": [t[4] for t in due[:max(0, cap)]], "due": len(due),
            "rechecks": sum(1 for t in due if t[2]), "not_due": not_due,
            "requeries": sum(1 for t in due if t[0] == 0),
            "pending_entities": pending_entities, "pending_rows": pending_rows}


# ---------------------------------------------------------------------------
# git: commit + push ONLY the hand-off file
# ---------------------------------------------------------------------------

def _git(*args: str, timeout: float = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"git {args[0]} timed out after {int(timeout)}s"


def _abort_stuck_rebase() -> None:
    gitdir = REPO / ".git"
    if (gitdir / "rebase-merge").exists() or (gitdir / "rebase-apply").exists():
        _git("rebase", "--abort")


def publish(message: str) -> tuple[str, str]:
    """Commit and push the hand-off file. Returns (result, detail), result one of
    pushed | unchanged | push_failed | commit_failed.

    The commit and the rebase run under the board lock (they rewrite the working tree, the
    same reason scripts/publish_helper.sh re-takes it for its rebase); the fetch and the push
    run outside it."""
    from foreclosure_scraper.web_artifact import BoardLockBusy, board_lock

    rel = str(HANDOFF.relative_to(REPO))
    wait = float(os.environ.get("SOS_GIT_LOCK_WAIT", "600"))
    committed = False
    try:
        with board_lock(REPO, owner="sos_agent_refresh.git", wait=wait, max_runtime=900):
            _git("add", "--", rel)
            rc, _ = _git("diff", "--cached", "--quiet", "--", rel)
            if rc != 0:
                rc, out = _git("commit", "-q", "-m", message, "--", rel)
                if rc != 0:
                    return "commit_failed", out[-400:]
                committed = True
    except BoardLockBusy as exc:
        return "push_failed", f"git step skipped, board lock busy: {str(exc)[:300]}"

    _git("fetch", "-q", "origin", "main", timeout=float(os.environ.get("SOS_GIT_FETCH_TIMEOUT", "600")))
    rc, ahead = _git("rev-list", "--count", "origin/main..HEAD")
    if not committed and rc == 0 and ahead.strip() == "0":
        return "unchanged", "hand-off unchanged and nothing unpushed"

    last = ""
    for attempt in range(3):
        try:
            with board_lock(REPO, owner="sos_agent_refresh.rebase", wait=wait, max_runtime=900):
                rc, out = _git("pull", "--rebase", "--autostash", "-q", "origin", "main",
                               timeout=float(os.environ.get("SOS_GIT_FETCH_TIMEOUT", "600")))
                if rc != 0:
                    last = f"pull --rebase failed: {out[-300:]}"
                _abort_stuck_rebase()
        except BoardLockBusy as exc:
            last = f"board lock busy for the rebase: {str(exc)[:200]}"
        rc, out = _git("push", "origin", "main",
                       timeout=float(os.environ.get("SOS_GIT_PUSH_TIMEOUT", "300")))
        if rc == 0:
            _, sha = _git("rev-parse", "--short", "HEAD")
            return "pushed", sha
        last = out[-300:]
        print(f"push attempt {attempt + 1} failed: {last[:160]}", flush=True)
        time.sleep(float(os.environ.get("SOS_GIT_RETRY_SLEEP", "20")) * (attempt + 1))
    return "push_failed", last


# ---------------------------------------------------------------------------

def _write_outcome(outcome: str, rows: int | str, note: str) -> None:
    """For the shell wrapper's job_event line (logs/job_events.jsonl)."""
    p = os.environ.get("SOS_AGENT_OUTCOME_FILE")
    if not p:
        return
    try:
        Path(p).write_text(f"{outcome}\n{rows}\n{note.replace(chr(10), ' ')[:400]}\n")
    except OSError:
        pass


def run(args) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        ledger = ho.load_ledger(HANDOFF)
    except ho.LedgerUnreadable as exc:
        # refusing beats overwriting: rewriting an unreadable ledger would lose every entry
        print(f"!! hand-off ledger unreadable, refusing to overwrite it: {exc}", flush=True)
        _write_outcome("failed", "", f"ledger unreadable: {exc}")
        return 1
    entities = ledger.setdefault("entities", {})
    before = ho.ledger_counts(entities)
    # re-check every resolved entry against the current matching rule (idempotent)
    rc = ho.recheck_resolved(entities, today=today)
    if rc["mismatch"] or rc["contacts_cleaned"]:
        print(f"ledger re-check: {len(rc['mismatch'])} resolved -> mismatch {rc['by_reason']} "
              f"({', '.join(entities[k].get('entity') or k for k in rc['mismatch'][:8])}"
              f"{', ...' if len(rc['mismatch']) > 8 else ''}); contacts cleaned on "
              f"{len(rc['contacts_cleaned'])}", flush=True)

    t0 = time.monotonic()
    scan = scan_board(DOCS, entities, today)
    scan_s = time.monotonic() - t0

    state = ho.load_backoff(BACKOFF)
    limits = ho.cap_limits()
    adaptive_cap, adaptive_why = ho.choose_cap(state, limits)
    if args.cap is not None:
        cap, why = int(args.cap), (f"manual --cap {args.cap} (one-off; adaptive cap stays "
                                   f"{adaptive_cap} unless this run goes badly)")
    else:
        cap, why = adaptive_cap, adaptive_why
    tg = pick_targets(scan["candidates"], entities, cap, today)
    names = tg["names"]

    print(f"board {scan['total']} rows ({scan_s:.0f}s scan) | with sos_agent={scan['with_sos']} "
          f"| ledger before: {before['resolved']} resolved, {before['miss']} miss, "
          f"{before['error']} no-answer | seeded from board: +{scan['seeded']} "
          f"({scan['unseedable']} board profiles not fileable) | candidate entities="
          f"{len(scan['candidates'])} | awaiting VM apply: {tg['pending_entities']} entities / "
          f"{tg['pending_rows']} rows | rows carrying a rejected profile="
          f"{scan['carrying_rejected']} | not due={tg['not_due']} | due={tg['due']} "
          f"({tg['rechecks']} rechecks, {tg['requeries']} mismatch re-queries)", flush=True)
    print(f"cap={cap} ({why}) | targets this run={len(names)}", flush=True)

    if args.dry_run:
        for n in names[:20]:
            print("  target:", n, flush=True)
        print("dry run: no lookups, nothing written", flush=True)
        _write_outcome("no_change", 0, "dry run")
        return 0

    outcome: dict = {}
    results: dict = {}
    if names and os.environ.get("SOS_AGENT") == "1":
        t1 = time.monotonic()
        results = asyncio.run(_batch_lookup(names, outcome=outcome))
        outcome["seconds"] = round(time.monotonic() - t1)
    else:
        outcome = {"attempted": 0, "resolved": [], "misses": [], "errors": [], "ambiguous": [],
                   "ambiguous_detail": {}, "breaker_tripped": False, "deadline_hit": False,
                   "session_failed": False}

    with_contact = new_rows = 0
    for name in outcome.get("resolved", []):
        prof = stamp_profile(results[name], name)
        ho.record_result(entities, name, "resolved", prof, today=today)
        if prof.get("best_contact_name") or prof.get("best_contact_address"):
            with_contact += 1
        c = scan["candidates"].get(entity_key(name))
        new_rows += c["rows"] if c else 0
    for name in outcome.get("ambiguous", []):
        ho.record_result(entities, name, "ambiguous", today=today,
                         detail=(outcome.get("ambiguous_detail") or {}).get(name))
    for name in outcome.get("misses", []):
        ho.record_result(entities, name, "miss", today=today)
    for name in outcome.get("errors", []):
        ho.record_result(entities, name, "error", today=today)

    n_res, n_miss, n_err, n_amb = (len(outcome.get(k, []))
                                   for k in ("resolved", "misses", "errors", "ambiguous"))
    for name in outcome.get("ambiguous", []):
        d = (outcome.get("ambiguous_detail") or {}).get(name) or {}
        print(f"  ambiguous: {name}: {d.get('reason')} ({d.get('exact', 0)} same-name of "
              f"{d.get('candidates', 0)} candidates)", flush=True)
    print(f"sos_agent: targets={len(names)} attempted={outcome.get('attempted', 0)} "
          f"resolved={n_res} (with contact {with_contact}, {new_rows} board rows for the VM) "
          f"ambiguous={n_amb} misses={n_miss} no-answer={n_err} "
          f"breaker={outcome.get('breaker_tripped')} "
          f"deadline={outcome.get('deadline_hit')} session_failed={outcome.get('session_failed')} "
          f"in {outcome.get('seconds', 0)}s"
          + (f" error={outcome.get('error')}" if outcome.get("error") else ""), flush=True)

    # back-off: the next run's cap
    nxt, verdict, reason = ho.next_cap(adaptive_cap, outcome, len(names), limits)
    if args.cap is not None and verdict != "back_off":
        nxt, verdict, reason = adaptive_cap, "hold", f"manual --cap run, adaptive cap unchanged ({reason})"
    run_rec = {"at": datetime.now(timezone.utc).isoformat(), "cap_used": cap,
               "manual": args.cap is not None, "targets": len(names),
               "attempted": outcome.get("attempted", 0), "resolved": n_res, "misses": n_miss,
               "ambiguous": n_amb, "no_answer": n_err, "breaker_tripped": bool(outcome.get("breaker_tripped")),
               "deadline_hit": bool(outcome.get("deadline_hit")),
               "session_failed": bool(outcome.get("session_failed")),
               "seconds": outcome.get("seconds", 0), "verdict": verdict, "next_cap": nxt}
    hist = (state.get("history") or [])[-29:] + [run_rec]
    ho.save_backoff({"cap": nxt, "reason": f"{verdict}: {reason}", "updated_at": run_rec["at"],
                     "last_run": run_rec, "history": hist}, BACKOFF)
    print(f"next cap={nxt} ({verdict}: {reason})", flush=True)

    # the ledger: merge with what is on disk now (never lose an entry), then write
    try:
        ho.merge_ledgers(ledger, ho.load_ledger(HANDOFF))
    except ho.LedgerUnreadable:
        pass
    ho.recheck_resolved(entities, today=today)     # whatever the merge brought back
    ledger["last_run"] = {k: v for k, v in run_rec.items() if k != "manual"} | {
        "seeded_from_board": scan["seeded"], "awaiting_vm_rows": tg["pending_rows"] + new_rows,
        "rechecked_to_mismatch": len(rc["mismatch"]), "mismatch_requeries": tg["requeries"]}
    ho.save_ledger(ledger, HANDOFF, host=socket.gethostname())
    after = ledger["counts"]
    print(f"ledger: {after['entities']} entities ({after['resolved']} resolved, "
          f"{after['ambiguous']} ambiguous, {after['mismatch']} mismatch, {after['miss']} "
          f"miss, {after['error']} no-answer) -> {HANDOFF.relative_to(REPO)}", flush=True)

    if not PUSH:
        print("HANDOFF_PUSH=0: skipped git", flush=True)
        _write_outcome("ok" if n_res else "no_change", n_res, f"{n_res} resolved; HANDOFF_PUSH=0")
        return 0

    msg = (f"sos_agent hand-off: +{n_res} resolved, {n_amb} ambiguous, {n_miss} miss, "
           f"{n_err} no-answer ({after['resolved']} resolved total, {today})")
    result, detail = publish(msg)
    print(f"git: {result} {detail}", flush=True)
    note = (f"targets={len(names)} resolved={n_res} ambiguous={n_amb} misses={n_miss} "
            f"no_answer={n_err} "
            f"cap={cap} next={nxt} ({verdict}); git {result} {detail[:120]}")
    if result in ("push_failed", "commit_failed"):
        _write_outcome("push_failed", n_res, note)
        return 0      # the ledger is safe on disk; the next run's push carries it
    _write_outcome("ok" if n_res else "no_change", n_res, note)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="scan + targets only")
    ap.add_argument("--cap", type=int, default=None, help="one-off cap for this run")
    args = ap.parse_args(argv)

    RUN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(RUN_LOCK, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another sos_agent_refresh run holds logs/.sos_agent_refresh.lock, skipping",
              flush=True)
        _write_outcome("skipped_lock", "", "another SOS run is active")
        return 0
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        return run(args)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


if __name__ == "__main__":
    raise SystemExit(main())
