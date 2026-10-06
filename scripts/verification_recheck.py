"""Re-verify specific per-listing verification ledger entries, e.g. after a verifier fix.

verification_sweep.py re-checks what is DUE (a missing entry, a TTL, a VERSION bump) in priority
order. This tool re-checks exactly the entries you name, right now, and tells you what changed:

  uv run python scripts/verification_recheck.py --signal tax_lien --verdicts stale,refuted
  uv run python scripts/verification_recheck.py --signal jail_booking --keys-file keys.txt
  uv run python scripts/verification_recheck.py --signal tax_lien --verdicts stale --max-rows 20 --dry-run
  HANDOFF_PUSH=0 uv run python scripts/verification_recheck.py ... --ledger-dir /tmp/led

WHICH ENTRIES. The ledger entries whose latest verdict is in --verdicts (default stale,refuted when
no --keys-file is given: the two verdicts that remove a claim from a lead's score, so a wrong one
hides a real lead), or the entries named by --keys-file (one ledger key per line, "#" comments
allowed; any key an entry claims finds it, a case-scoped "<case>@<property>" key included; the
verdict filter then applies only when --verdicts is also given). --max-rows caps the entries.

HOW. ONE read-only pass over the board (board_stream.iter_board_rows, never written) finds each
entry's board row through the verifier's own ledger_keys() (the row_keys() machinery of
verification/core.py); the best-ranked row of an entry is kept. Each row then goes through the
sweep's own run_checks(): the registered verifier's verify() with the same Fetcher (the per-host
1.5 s spacing, per-row timeout and time budget), the answer merged into the ledger with
Ledger.record(), saved with the sweep's merge-with-disk _save(). Only the ledger files are written
(--ledger-dir, HANDOFF_PUSH=0 and the git hand-off are the sweep's: Ledger.publish_ledgers).

REPORT. Counts only, no names: how many entries were selected / found on the board / rechecked,
the old -> new verdict table, and for every answer that is still unconfirmed its reason. An entry
with no matching board row (the row left the board) is counted, not rechecked.

A run lock (logs/.verification_sweep.lock, the sweep's own) stops a recheck and a sweep from
writing the same ledger at once.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import os
import socket
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import verification_sweep as sweep  # noqa: E402  (run_checks, _save: the sweep's own internals)
from foreclosure_scraper.board_parts import BoardIntegrityError  # noqa: E402
from foreclosure_scraper.board_stream import (  # noqa: E402
    detail_source, iter_board_rows, iter_board_rows_with_detail,
)
from foreclosure_scraper.verification import ledger as L  # noqa: E402
from foreclosure_scraper.verification.core import iso_z, tier_rank, utc_now  # noqa: E402
from foreclosure_scraper.verification.fetch import Fetcher  # noqa: E402
from foreclosure_scraper.verification.registry import discover  # noqa: E402

RUN_LOCK = sweep.RUN_LOCK
DEFAULT_VERDICTS = ("stale", "refuted")


def read_keys(path: Path | str) -> list[str]:
    """Ledger keys from a file: one per line, blank lines and '#' comments skipped."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            out.append(s)
    return out


def select_entries(led: L.Ledger, *, verdicts: set[str] | None, keys: list[str] | None,
                   cap: int) -> tuple[dict[str, dict], list[str]]:
    """({entry key: entry}, [listed keys that match no entry]), in key order, at most `cap`.
    A listed key finds an entry through Ledger.find (any key the entry claims)."""
    chosen: dict[str, dict] = {}
    missing: list[str] = []
    if keys:
        for k in keys:
            ek, e = led.find([k])
            if e is None or not e.get("latest"):
                missing.append(k)
                continue
            chosen.setdefault(ek, e)
    else:
        for ek, e in led.rows.items():
            if isinstance(e.get("latest"), dict):
                chosen[ek] = e
    if verdicts:
        chosen = {ek: e for ek, e in chosen.items()
                  if (e["latest"] or {}).get("verdict") in verdicts}
    ordered = dict(sorted(chosen.items()))
    if cap >= 0:
        ordered = dict(list(ordered.items())[:cap])
    return ordered, missing


def find_rows(board_path: Path, verifiers, led_by_signal: dict, wanted: dict[str, set[str]]
              ) -> dict[str, dict]:
    """ONE read-only streaming pass. {signal: {entry key: (rank, row, verifier)}}: for every
    entry key in `wanted[signal]`, the best-ranked board row (HOT > WARM > COLD, then board
    order) whose verifier applies and whose ledger_keys() finds that entry."""
    found: dict[str, dict] = {sig: {} for sig in wanted}
    todo = {sig for sig, w in wanted.items() if w}
    if not todo:
        return found
    detail_keys = sorted({k for v in verifiers if v.signal in todo
                          for k in (getattr(v, "detail_keys", ()) or ())})
    rows = iter_board_rows(board_path)
    if detail_keys:
        try:
            detail_source(Path(board_path).parent)
            rows = iter_board_rows_with_detail(board_path, detail_keys)
        except (FileNotFoundError, BoardIntegrityError) as exc:
            print(f"!! lazy-detail sidecar unavailable ({exc}); rows carry no {detail_keys}",
                  flush=True)
    order = 0
    for rec in rows:
        done: set[str] = set()
        for v in verifiers:
            if v.signal not in todo or v.signal in done or not v.safe_applies(rec):
                continue
            done.add(v.signal)                     # the first applicable verifier owns the row
            ek, entry = led_by_signal[v.signal].find(v.ledger_keys(rec))
            if entry is None or ek not in wanted[v.signal]:
                continue
            order += 1
            rank = (tier_rank(rec), order)
            cur = found[v.signal].get(ek)
            if cur is None or rank < cur[0]:
                found[v.signal][ek] = (rank, rec, v)
    return found


def build_plan(found: dict[str, dict]) -> dict:
    """The shape sweep.run_checks takes: {signal: [(prio, key, row, verifier)]}, best first."""
    plan = {}
    for sig, items in found.items():
        rows = sorted(items.items(), key=lambda kv: kv[1][0])
        plan[sig] = [((float(rank[0]), 0, 0.0, rank[1]), ek, row, v)
                     for ek, (rank, row, v) in rows]
    return plan


def answer_of(led: L.Ledger, keys: list[str], started: float) -> tuple[str, str | None] | None:
    """(this run's verdict, its reason) for the entry these keys find, or None when the entry was
    not answered in this run. The verdict is the run's own attempt (last_attempt); the reason is
    read from the entry's latest record when that is this run's answer. When an older decisive
    answer of the same verifier version is kept as `latest` (the ledger's rule: a flaky page never
    erases a verdict) the run's verdict is still what is reported."""
    from foreclosure_scraper.verification.core import parse_ts
    _, e = led.find(keys)
    la = (e or {}).get("last_attempt") or {}
    t = parse_ts(la.get("checked_at"))
    if e is None or t is None or t.timestamp() < started - 1:
        return None
    lat = e.get("latest") or {}
    reason = (lat.get("evidence") or {}).get("reason") if lat.get("checked_at") == la.get("checked_at") else None
    return str(la.get("verdict") or "-"), reason


def report(signal: str, selected: int, missing: int, on_board: int, before: dict[str, str],
           after: dict[str, tuple[str, str | None]], not_on_board: int) -> list[str]:
    """Report lines: counts, the old -> new table, the reasons of the unconfirmed answers."""
    lines = [f"{signal}: selected {selected}" + (f" ({missing} listed key(s) match no entry)" if missing else "")
             + f" | on the board {on_board} | not on the board {not_on_board} | rechecked {len(after)}"]
    moves: Counter = Counter()
    reasons: Counter = Counter()
    for ek, (new, reason) in after.items():
        old = before.get(ek, "-")
        moves[(old, new)] += 1
        if new == "unconfirmed":
            reasons[reason or "-"] += 1
    changed = sum(n for (a, b), n in moves.items() if a != b)
    lines.append(f"  changed {changed} of {len(after)}")
    for (a, b), n in sorted(moves.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {a:11} -> {b:11} {n:4}" + ("" if a != b else "   (unchanged)"))
    if reasons:
        lines.append("  unconfirmed reasons: " + ", ".join(f"{r} {n}" for r, n in reasons.most_common()))
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--signal", action="append", required=True,
                    help="signal(s) to recheck (repeatable or comma-separated)")
    ap.add_argument("--verdicts", default=None,
                    help="comma-separated latest verdicts to recheck (default stale,refuted "
                         "unless --keys-file is given)")
    ap.add_argument("--keys-file", default=None, help="ledger keys to recheck, one per line")
    ap.add_argument("--max-rows", type=int, default=-1, help="cap on entries rechecked per signal")
    ap.add_argument("--ledger-dir", default=None, help="default docs/handoff/verification")
    ap.add_argument("--docs", default=str(REPO / "docs"), help="board directory (read-only)")
    ap.add_argument("--budget-s", type=float,
                    default=float(os.environ.get("VERIFY_MAX_SECONDS", "2700")))
    ap.add_argument("--row-timeout-s", type=float, default=120.0)
    ap.add_argument("--save-every", type=int, default=10)
    ap.add_argument("--capture-dir", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="select and find the board rows only: no fetch, nothing written")
    args = ap.parse_args(argv)

    RUN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(RUN_LOCK, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"another verification sweep or recheck holds {RUN_LOCK.name}, skipping", flush=True)
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


def run(args) -> int:
    signals = {s.strip() for arg in args.signal for s in arg.split(",") if s.strip()}
    verifiers = [v for v in discover() if v.signal in signals]
    if not verifiers:
        print(f"no verifier for {sorted(signals)}", flush=True)
        return 2
    keys = read_keys(args.keys_file) if args.keys_file else None
    verdicts = ({v.strip() for v in args.verdicts.split(",") if v.strip()} if args.verdicts
                else (None if keys else set(DEFAULT_VERDICTS)))
    ldir = Path(args.ledger_dir) if args.ledger_dir else L.ledger_dir()
    ledgers: dict[str, L.Ledger] = {}
    for sig in sorted({v.signal for v in verifiers}):
        try:
            ledgers[sig] = L.Ledger.load(sig, ldir)
        except L.LedgerUnreadable as exc:
            print(f"!! ledger unreadable, refusing to overwrite it: {exc}", flush=True)
            return 1
    selected: dict[str, dict] = {}
    missing: dict[str, list] = {}
    for sig, led in ledgers.items():
        selected[sig], missing[sig] = select_entries(led, verdicts=verdicts, keys=keys,
                                                     cap=args.max_rows)
    print(f"verifiers: {', '.join(f'{v.name}({v.signal} {v.version})' for v in verifiers)} | "
          f"entries selected: {', '.join(f'{s}={len(e)}' for s, e in selected.items())}", flush=True)

    t0 = time.monotonic()
    found = find_rows(Path(args.docs) / "listings.json.gz", verifiers, ledgers,
                      {sig: set(e) for sig, e in selected.items()})
    print(f"board pass {time.monotonic() - t0:.0f}s (read-only)", flush=True)
    before = {sig: {ek: str((e.get("latest") or {}).get("verdict")) for ek, e in sel.items()}
              for sig, sel in selected.items()}
    plan = build_plan(found)
    if args.dry_run:
        for sig in selected:
            print(f"{sig}: {len(found[sig])} of {len(selected[sig])} entries have a board row "
                  f"| would recheck {Counter(before[sig][ek] for ek in found[sig])}", flush=True)
        print("dry run: nothing fetched, nothing written", flush=True)
        return 0

    fetcher = Fetcher(capture_dir=args.capture_dir)
    host = socket.gethostname()
    started = time.time()
    t1 = time.monotonic()
    tallies = asyncio.run(sweep.run_checks(plan, ledgers, fetcher, budget_s=args.budget_s,
                                           save_every=max(1, args.save_every),
                                           row_timeout_s=args.row_timeout_s, host=host))
    secs = round(time.monotonic() - t1)
    paths = []
    print("", flush=True)
    for sig, led in ledgers.items():
        answered: dict[str, tuple[str, str | None]] = {}
        for ek, (_rank, row, v) in found[sig].items():
            a = answer_of(led, v.ledger_keys(row), started)
            if a is not None:
                answered[ek] = a
        led.last_run = {"at": iso_z(datetime.now(timezone.utc)), "host": host, "seconds": secs,
                        "recheck": True, "verdicts": sorted(verdicts or []),
                        "keys_file": bool(keys), "result": tallies.get(sig, {}),
                        "requests": fetcher.stats()}
        sweep._save(led, host)
        paths.append(led.path)
        for line in report(sig, len(selected[sig]), len(missing[sig]), len(found[sig]),
                           before[sig], answered, len(selected[sig]) - len(found[sig])):
            print(line, flush=True)
    print(f"requests: {fetcher.stats()}", flush=True)

    checked = sum(t.get("checked", 0) for t in tallies.values())
    if not checked:
        print("nothing rechecked; no commit", flush=True)
        return 0
    msg = ("verification recheck: " + "; ".join(
        f"{sig} {t.get('checked', 0)} ({', '.join(f'{k} {n}' for k, n in sorted(t.items()) if k not in ('checked', 'budget_stop'))})"
        for sig, t in tallies.items()) + f" [{utc_now().date().isoformat()}]")
    res, detail = L.publish_ledgers(paths, msg)
    print(f"git: {res} {detail}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
