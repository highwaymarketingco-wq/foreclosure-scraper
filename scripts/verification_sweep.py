"""Per-listing verification sweep: the MAC side of the Mac -> VM verification hand-off.

Checks board claims live against their authoritative sources with the verifier modules in
src/foreclosure_scraper/verification/verifiers/ (auto-discovered), WITHOUT writing the board:

  1. ONE read-only stream of the board (board_stream.iter_board_rows(), ~300 MB peak). For
     each row and each verifier whose applies(row) is true, the row is a candidate when its
     ledger entry is missing, past the verifier's TTL_DAYS (RETRY_DAYS for an unconfirmed
     answer), or was checked by another verifier VERSION. Candidates are ranked HOT -> WARM ->
     COLD, then never-checked first, then oldest check, and only the top --max-rows per
     signal are kept (a bounded heap: memory does not grow with the backlog).
  2. Each candidate goes through its verifier's verify(row, Fetcher): http_client's per-host
     throttle plus VERIFY_HOST_MIN_INTERVAL_S (1.5 s) spacing per host, one row at a time,
     a per-row timeout, a global time budget (--budget-s).
  3. Every answer is merged into the cumulative ledger docs/handoff/verification/<signal>.json
     (verification/ledger.py), saved every --save-every rows and at the end, merged with the
     file on disk first so nothing is lost.
  4. Only the ledger files are committed and pushed (HANDOFF_PUSH=0 skips git; pull --rebase
     --autostash before the push). The VM's next run attaches the verdicts before scoring
     (verification/apply.py, wired in main.py's run_enrich_tail()).

A run lock (logs/.verification_sweep.lock) stops two sweeps from overlapping.

Compliance: verifiers only fetch free, no-login, no-CAPTCHA public pages. A walled source's
verifier (SC Public Index: ToS-restricted for automated querying; NC eCourts / NC SOS: the human
lane, verification_human_lane.py) never fetches and answers "wall".

Usage:
  uv run python scripts/verification_sweep.py --signal tax_lien --county Buncombe --max-rows 50
  uv run python scripts/verification_sweep.py --dry-run          # candidates only, no fetch
  uv run python scripts/verification_sweep.py --recheck-only     # after a VERSION bump
  HANDOFF_PUSH=0 uv run python scripts/verification_sweep.py ...  # write the ledger, skip git
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import heapq
import os
import socket
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.verification import ledger as L  # noqa: E402
from foreclosure_scraper.verification.core import (  # noqa: E402
    iso_z, parse_ts, result, row_keys, tier_of, tier_rank, utc_now,
)
from foreclosure_scraper.verification.fetch import Fetcher  # noqa: E402
from foreclosure_scraper.verification.registry import discover  # noqa: E402

RUN_LOCK = REPO / "logs" / ".verification_sweep.lock"


def select(board_path: Path, verifiers, ledgers: dict, *, county: str | None, cap: int,
           now: datetime, recheck_only: bool = False,
           tiers: set[str] | None = None) -> tuple[dict, dict]:
    """One streaming pass. Returns ({signal: [(prio, key, row, verifier)] best first},
    {signal: Counter of why rows were or were not due}). recheck_only: only rows that already
    have a ledger entry (TTL / VERSION re-checks), e.g. right after a VERSION bump. tiers:
    only rows of these tiers (HOT/WARM/COLD; "-" for untiered), e.g. to sample the COLD tail."""
    heaps: dict[str, list] = {v.signal: [] for v in verifiers}
    inheap: dict[str, dict] = {v.signal: {} for v in verifiers}   # key -> item, per signal
    why: dict[str, Counter] = {v.signal: Counter() for v in verifiers}
    want_county = county.strip().lower() if county else None
    order = 0
    for rec in iter_board_rows(board_path):
        if want_county and str(rec.get("county") or "").strip().lower() != want_county:
            continue
        if tiers and (tier_of(rec) or "-") not in tiers:
            continue
        done: set[str] = set()
        for v in verifiers:
            if v.signal in done or not v.safe_applies(rec):
                continue
            done.add(v.signal)             # first applicable verifier of a signal owns the row
            keys = row_keys(rec)
            _, entry = ledgers[v.signal].find(keys)
            due, reason = L.is_due(entry, v, now)
            why[v.signal]["applies"] += 1
            if recheck_only and entry is None:
                why[v.signal]["skipped_new_recheck_only"] += 1
                continue
            why[v.signal][("due_" if due else "not_due_") + reason] += 1
            if not due:
                continue
            lt = parse_ts(((entry or {}).get("latest") or {}).get("checked_at"))
            order += 1
            # best first: HOT -> WARM -> COLD, never checked, oldest check, board order.
            # heapq is a min-heap: store the negated priority so h[0] is the WORST kept row.
            prio = (tier_rank(rec), 0 if lt is None else 1, lt.timestamp() if lt else 0.0, order)
            item = (tuple(-x for x in prio), keys[0], rec, v.name)
            h, seen = heaps[v.signal], inheap[v.signal]
            prev = seen.get(keys[0])
            if prev is not None:
                # another board row of the same property is already queued: one check covers
                # both (they share the ledger entry); keep the better-ranked row
                why[v.signal]["same_property_queued"] += 1
                if item[0] > prev[0]:
                    h[h.index(prev)] = item
                    heapq.heapify(h)
                    seen[keys[0]] = item
                continue
            if len(h) < cap:
                heapq.heappush(h, item)
                seen[keys[0]] = item
            elif h and item[0] > h[0][0]:
                gone = heapq.heapreplace(h, item)
                seen.pop(gone[1], None)
                seen[keys[0]] = item
    out = {}
    byname = {v.name: v for v in verifiers}
    for sig, h in heaps.items():
        items = sorted(h, key=lambda i: i[0], reverse=True)       # best first
        out[sig] = [(tuple(-x for x in i[0]), i[1], i[2], byname[i[3]]) for i in items]
    return out, why


async def run_checks(plan: dict, ledgers: dict, fetcher, *, budget_s: float, save_every: int,
                     row_timeout_s: float, host: str) -> dict:
    t0 = time.monotonic()
    tallies: dict[str, Counter] = {}
    for sig, items in plan.items():
        led = ledgers[sig]
        tally = tallies.setdefault(sig, Counter())
        since_save = 0
        for prio, key, row, v in items:
            if time.monotonic() - t0 > budget_s:
                tally["budget_stop"] += 1
                break
            try:
                res = await asyncio.wait_for(v.verify(row, fetcher), timeout=row_timeout_s)
            except Exception as exc:  # noqa: BLE001 - a verifier crash is an unconfirmed answer
                res = result(v.signal, "unconfirmed",
                             {"reason": "verifier_error",
                              "error": f"{type(exc).__name__}: {str(exc)[:200]}"},
                             source=v.source, version=v.version, verifier=v.name)
            if not res.verifier:
                res.verifier = v.name
            if not res.verifier_version:
                res.verifier_version = v.version
            led.record(row, res, ttl_days=v.ttl_days, governs=v.governs)
            tally[res.verdict] += 1
            tally["checked"] += 1
            print(f"  {sig} {res.verdict:11} {key}  {row.get('street_address') or ''} "
                  f"[{('HOT', 'WARM', 'COLD', '-')[int(prio[0])]}] "
                  f"{_brief(res.evidence)}", flush=True)
            since_save += 1
            if since_save >= save_every:
                _save(led, host)
                since_save = 0
        _save(led, host)
    return {s: dict(c) for s, c in tallies.items()}


def _brief(ev: dict) -> str:
    bits = []
    for k in ("total_delinquent", "years_delinquent", "reason", "owner_match",
              "value_ratio_board_to_county"):
        if ev.get(k) not in (None, "", 0, {}):
            bits.append(f"{k}={ev[k]}")
    for c in ev.get("bills_checked") or []:
        if c.get("paid_late"):
            bits.append(f"paid_late {c.get('year')} on {c.get('paid_on')}")
    return " ".join(bits)


def _save(led, host: str) -> None:
    """Merge with the file on disk (another writer, e.g. the human lane), then write."""
    try:
        disk = L.Ledger.load(led.signal, led.path.parent if led.path else None)
        led.merge_from(disk)
    except L.LedgerUnreadable:
        raise
    led.save(host=host)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--signal", action="append", default=None,
                    help="signal(s) to sweep (repeatable or comma-separated); default: all")
    ap.add_argument("--county", default=None, help="only rows in this county")
    ap.add_argument("--max-rows", type=int,
                    default=int(os.environ.get("VERIFY_MAX_ROWS_PER_SIGNAL", "200")),
                    help="per-signal cap on rows checked this run (default 200)")
    ap.add_argument("--budget-s", type=float,
                    default=float(os.environ.get("VERIFY_MAX_SECONDS", "2700")),
                    help="global time budget for the live checks (default 2700 s)")
    ap.add_argument("--row-timeout-s", type=float, default=120.0)
    ap.add_argument("--save-every", type=int, default=10)
    ap.add_argument("--capture-dir", default=None,
                    help="save every fetched response body here (fixtures, audits)")
    ap.add_argument("--ledger-dir", default=None, help="default docs/handoff/verification")
    ap.add_argument("--docs", default=str(REPO / "docs"), help="board directory (read-only)")
    ap.add_argument("--tier", action="append", default=None,
                    help="only rows of this tier (HOT/WARM/COLD, repeatable or comma-separated)")
    ap.add_argument("--recheck-only", action="store_true",
                    help="only rows already in the ledger (TTL/VERSION re-checks), no new rows")
    ap.add_argument("--dry-run", action="store_true", help="select candidates only")
    args = ap.parse_args(argv)

    RUN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(RUN_LOCK, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another verification sweep holds logs/.verification_sweep.lock, skipping", flush=True)
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
    now = utc_now()
    host = socket.gethostname()
    wanted = None
    if args.signal:
        wanted = {s.strip() for arg in args.signal for s in arg.split(",") if s.strip()}
    verifiers = [v for v in discover() if wanted is None or v.signal in wanted]
    if not verifiers:
        print(f"no verifier for {sorted(wanted or [])}", flush=True)
        return 2
    ldir = Path(args.ledger_dir) if args.ledger_dir else L.ledger_dir()
    ledgers = {}
    for v in verifiers:
        if v.signal in ledgers:
            continue
        try:
            ledgers[v.signal] = L.Ledger.load(v.signal, ldir)
        except L.LedgerUnreadable as exc:
            print(f"!! ledger unreadable, refusing to overwrite it: {exc}", flush=True)
            return 1
    print(f"verifiers: {', '.join(f'{v.name}({v.signal} {v.version}, ttl {v.ttl_days:g}d)' for v in verifiers)}"
          f" | ledgers: {', '.join(f'{s}={len(led.rows)}' for s, led in ledgers.items())}", flush=True)

    t0 = time.monotonic()
    plan, why = select(Path(args.docs) / "listings.json.gz", verifiers, ledgers,
                       county=args.county, cap=max(0, args.max_rows), now=now,
                       recheck_only=args.recheck_only,
                       tiers={t.strip().upper() for a in (args.tier or []) for t in a.split(",") if t.strip()} or None)
    scan_s = time.monotonic() - t0
    for sig in plan:
        tiers = Counter(("HOT", "WARM", "COLD", "-")[int(p[0][0])] for p in plan[sig])
        print(f"{sig}: {dict(why[sig])} | this run {len(plan[sig])} rows {dict(tiers)} "
              f"(board scan {scan_s:.0f}s)", flush=True)
    if args.dry_run:
        for sig, items in plan.items():
            for prio, key, row, v in items[:15]:
                print(f"  candidate {sig} {key} {row.get('street_address') or ''} via {v.name}",
                      flush=True)
        print("dry run: nothing fetched, nothing written", flush=True)
        return 0

    fetcher = Fetcher(capture_dir=args.capture_dir)
    t1 = time.monotonic()
    tallies = asyncio.run(run_checks(plan, ledgers, fetcher, budget_s=args.budget_s,
                                     save_every=max(1, args.save_every),
                                     row_timeout_s=args.row_timeout_s, host=host))
    secs = round(time.monotonic() - t1)
    paths = []
    for sig, led in ledgers.items():
        led.last_run = {"at": iso_z(datetime.now(timezone.utc)), "host": host,
                        "county": args.county, "max_rows": args.max_rows, "seconds": secs,
                        "recheck_only": bool(args.recheck_only), "tier": args.tier,
                        "selection": dict(why.get(sig) or {}), "result": tallies.get(sig, {}),
                        "requests": fetcher.stats()}
        _save(led, host)
        paths.append(led.path)
        c = led.counts()
        print(f"{sig}: this run {tallies.get(sig, {})} in {secs}s | ledger {c} -> "
              f"{led.path}", flush=True)
    print(f"requests: {fetcher.stats()}", flush=True)

    checked = sum(t.get("checked", 0) for t in tallies.values())
    msg = ("verification hand-off: " + "; ".join(
        f"{sig} +{t.get('checked', 0)} ({', '.join(f'{k} {n}' for k, n in sorted(t.items()) if k not in ('checked', 'budget_stop'))})"
        for sig, t in tallies.items()) + f" [{now.date().isoformat()}]")
    if not checked:
        print("nothing checked; no commit", flush=True)
        return 0
    res, detail = L.publish_ledgers(paths, msg)
    print(f"git: {res} {detail}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
