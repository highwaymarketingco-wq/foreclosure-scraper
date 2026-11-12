"""Re-key a case-scoped verifier's ledger from property keys to case id + property, OFFLINE.

A verifier that declares IDENTITY = "case" (verification/registry.py; bankruptcy_stay and
jail_booking since 2026-10-06) keys its ledger by the case a row claims plus the property, so
two unrelated cases on one placeholder parcel no longer share one verdict. Entries written
before that are keyed by property only. This script streams the board read-only (board_stream),
gives each such entry the case its rows name (verification.ledger.migrate_to_case_scope: scoped,
attributed by the stored evidence, or marked `recheck` with its verdict moved to `superseded`
when it cannot be given to one case), and saves the ledger. Nothing is fetched; no entry is
dropped; the board is never written.

  uv run python scripts/verification_case_scope_migrate.py --dry-run
  uv run python scripts/verification_case_scope_migrate.py [--signal bankruptcy_stay] [--report F]

Commit the rewritten ledger files yourself (explicit paths), or pass --push to commit and push
only them (verification.ledger.publish_ledgers). Takes the sweep's run lock.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.verification import ledger as L  # noqa: E402
from foreclosure_scraper.verification.core import utc_now  # noqa: E402
from foreclosure_scraper.verification.registry import discover  # noqa: E402

RUN_LOCK = REPO / "logs" / ".verification_sweep.lock"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--signal", action="append", default=None,
                    help="signal(s) to migrate; default: every case-scoped verifier's")
    ap.add_argument("--ledger-dir", default=None, help="default docs/handoff/verification")
    ap.add_argument("--docs", default=str(REPO / "docs"), help="board directory (read-only)")
    ap.add_argument("--report", default=None, help="write the per-entry report (JSON) here")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--push", action="store_true", help="commit + push only the ledger files")
    args = ap.parse_args(argv)

    RUN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(RUN_LOCK, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("a verification sweep holds logs/.verification_sweep.lock; try again later")
        return 1
    try:
        return run(args)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def run(args) -> int:
    wanted = {s.strip() for a in (args.signal or []) for s in a.split(",") if s.strip()} or None
    scoped = [v for v in discover() if v.identity == "case"
              and (wanted is None or v.signal in wanted)]
    if not scoped:
        print("no case-scoped verifier selected")
        return 2
    ldir = Path(args.ledger_dir) if args.ledger_dir else L.ledger_dir()
    # one verifier per signal owns the migration (the first by module name, as in the sweep)
    by_sig: dict = {}
    for v in scoped:
        by_sig.setdefault(v.signal, v)
    ledgers = {s: L.Ledger.load(s, ldir) for s in by_sig}

    # one board pass: keep only the rows some case-scoped verifier names a case for
    rows: dict[str, list] = {s: [] for s in by_sig}
    n = 0
    for rec in iter_board_rows(Path(args.docs) / "listings.json.gz"):
        n += 1
        for s, v in by_sig.items():
            if v.case_of(rec):
                rows[s].append(rec)
    print(f"board rows {n}; rows naming a case: " + ", ".join(f"{s}={len(r)}" for s, r in rows.items()))

    now = utc_now()
    out_report = {}
    paths = []
    for s, v in by_sig.items():
        led = ledgers[s]
        before = led.counts()
        rep = L.migrate_to_case_scope(led, v, rows[s], now=now)
        after = led.counts()
        out_report[s] = {**{k: rep[k] for k in rep if k != "lines"}, "counts_before": before,
                         "counts_after": after, "lines": rep["lines"]}
        print(f"{s} ({v.name}): {len(rep['lines'])} property-keyed entries -> "
              f"scoped {rep['scoped']}, attributed {rep['attributed']}, "
              f"scoped_from_evidence {rep['scoped_from_evidence']}, recheck {rep['recheck']} "
              f"| ledger {before} -> {after}")
        why = Counter((ln["reason"], ln["verdict"]) for ln in rep["lines"] if ln["outcome"] == "recheck")
        for (reason, verdict), c in sorted(why.items()):
            print(f"  recheck {reason} (was {verdict}): {c}")
        for ln in rep["lines"]:
            if ln["outcome"] != "scoped":
                print(f"  {ln['outcome']:20} {ln['reason'] or '':28} cases={ln['cases']:<3} "
                      f"rows={ln['rows']:<3} was {ln['verdict']:11} {ln['key']}")
        if not args.dry_run:
            led.last_run = {**(led.last_run or {}), "case_scope_migration": {
                "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "host": socket.gethostname(),
                **{k: rep[k] for k in ("entries", "scoped", "attributed",
                                       "scoped_from_evidence", "recheck")}}}
            led.save()
            paths.append(led.path)
    if args.report:
        Path(args.report).write_text(json.dumps(out_report, indent=1, default=str))
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    if args.push and paths:
        res, detail = L.publish_ledgers(paths, "verification: case-scope migration of "
                                        + ", ".join(sorted(by_sig)))
        print(f"git: {res} {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
