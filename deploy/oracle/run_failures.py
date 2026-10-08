#!/usr/bin/env python3
"""What a run swallowed: every enricher/phase failure and time cap in a run log, counted.

WHY (audit 2026-10-09, pipeline_gate)
    main.run() and main.run_enrich_tail() wrap ~200 steps in try/except that log and carry on
    (`<step>.failed` at level error, `enrich.time_capped` / `<step>.time_capped` at warning). That
    keeps one broken enricher from costing an 18-hour run, but nothing else reports it: the run
    summary's `errors` lists only scrapers with 0 rows, run_health shows no entry for a step that
    failed (its stats are simply absent), the digest email says nothing, and the exit code is 0.
    A dead enricher looks exactly like one that found nothing. This prints them at the end of
    vm_run.sh / vm_resume.sh (vm_lib.sh vm_report_swallowed) and is what scripts/canary_run.py
    asserts is empty.

USAGE
    python3 deploy/oracle/run_failures.py LOG [--json]
Exit 0 always (a report). --json prints {"failed": {event: n}, "time_capped": {phase: n},
"item_failures": {event: n}, "item_failures_total": n, "errors_other": n}. Standard library only (runs on the VM's system python).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

#: error-level events that are part of normal operation, not a swallowed step failure
IGNORED_ERROR_EVENTS = frozenset({
    "orchestrator.count_drop_alert",        # reported on its own by vm_run.sh
    "orchestrator.scraper_task_failed",     # a scraper; reported through source_status
})


def scan(lines) -> dict:
    failed: Counter = Counter()
    items: Counter = Counter()
    capped: Counter = Counter()
    other = 0
    for line in lines:
        line = line.strip()
        if not line.startswith("{") or '"event"' not in line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        name = str(ev.get("event") or "")
        level = ev.get("level")
        if name.endswith("time_capped"):
            capped[str(ev.get("phase") or name[: -len(".time_capped")] or name)] += 1
        elif level in ("error", "critical") and name not in IGNORED_ERROR_EVENTS:
            # a STEP failure: main.py's `except Exception: log.error("<step>.failed",
            # traceback=...)` (and _await_capped / _gather_phases, which log the same way)
            if name.endswith(".failed") and "traceback" in ev:
                failed[name] += 1
            elif name.endswith(("_failed", ".failed")):
                items[name] += 1        # one fetch / one record inside a step that carried on
            else:
                other += 1
    return {"failed": dict(failed.most_common()), "time_capped": dict(capped.most_common()),
            "item_failures": dict(items.most_common(20)), "item_failures_total": sum(items.values()),
            "errors_other": other}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        with open(a.log, encoding="utf-8", errors="replace") as fh:
            res = scan(fh)
    except OSError as exc:
        print(f"run_failures: cannot read {a.log}: {exc}", file=sys.stderr)
        return 0
    if a.json:
        print(json.dumps(res))
        return 0
    nf, nc = sum(res["failed"].values()), sum(res["time_capped"].values())
    if not nf and not nc:
        print("==> swallowed failures: none (no step logged .failed or a time cap)")
        return 0
    if nf:
        print(f"==> ⚠️  {nf} swallowed step failure(s): the run carried on without them and no "
              f"summary, run_health or email reports them:")
        print("==>     " + ", ".join(f"{k} x{v}" for k, v in res["failed"].items()))
    if nc:
        print(f"==> ⚠️  {nc} time-capped phase(s) (partial work kept): "
              + ", ".join(f"{k} x{v}" for k, v in res["time_capped"].items()))
    if res["item_failures_total"]:
        print(f"==>     plus {res['item_failures_total']} per-item fetch failures inside steps "
              f"(top: " + ", ".join(f"{k} x{v}" for k, v in list(res["item_failures"].items())[:5]) + ")")
    if res["errors_other"]:
        print(f"==>     plus {res['errors_other']} other error-level log events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
