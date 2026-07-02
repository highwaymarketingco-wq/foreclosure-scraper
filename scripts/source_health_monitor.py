"""Source-health monitor — flags any scraper whose output has cratered.

Reliability guard for the fragile render/stealth tier: a scraper can silently start
returning 0 rows (portal redesign, WAF change) and you'd only notice by leads
drifting down. This snapshots each source's FRESH-lead count (leads whose last_seen
is within HEALTH_FRESH_DAYS) to a rolling history and flags any source that craters
vs. its own trailing median.

Read-only on the board (docs/listings.json) — writes only docs/source_health*.json.
Not a board-writer, so it's safe to run anytime / alongside a pipeline pass. Exit
code 1 when anything is flagged, so a cron/CI step can surface it.

Usage:  uv run python scripts/source_health_monitor.py
"""
from __future__ import annotations

import json
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
HISTORY = DOCS / "source_health_history.json"
REPORT = DOCS / "source_health.json"

KEEP = 60            # snapshots to retain
MIN_BASELINE = 5     # ignore tiny sources (noise)
CRATER_RATIO = 0.4   # flag if fresh now < 40% of trailing median


def _parse_dt(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def evaluate(rows: list[dict], history: list[dict], now: datetime,
             fresh_days: float = 3.0) -> tuple[dict, list[dict]]:
    """Pure core: build this run's snapshot + the flags vs. prior history.

    A source is flagged when its trailing-median fresh count is >= MIN_BASELINE and
    this run's fresh count is < CRATER_RATIO of that median (ZEROED/CRATERED), or when
    a previously-healthy source produced no fresh leads at all this run (GONE).
    """
    cutoff = now - timedelta(days=fresh_days)
    total, fresh = Counter(), Counter()
    for r in rows:
        src = r.get("source") or "?"
        total[src] += 1
        ls = _parse_dt(r.get("last_seen"))
        if ls and ls >= cutoff:
            fresh[src] += 1
    snap = {"ts": now.isoformat(), "fresh": dict(fresh), "total": dict(total)}

    trailing: dict[str, list[int]] = defaultdict(list)
    for h in history[-KEEP:]:
        for src, v in (h.get("fresh") or {}).items():
            trailing[src].append(v)

    flags: list[dict] = []
    seen = set()
    for src, fnow in fresh.items():
        seen.add(src)
        past = trailing.get(src, [])
        if len(past) < 2:
            continue
        med = statistics.median(past)
        if med >= MIN_BASELINE and fnow < CRATER_RATIO * med:
            flags.append({"source": src, "fresh_now": fnow, "trailing_median": med,
                          "severity": "ZEROED" if fnow == 0 else "CRATERED"})
    # previously-healthy sources that emitted nothing fresh this run
    for src, past in trailing.items():
        if src in seen or len(past) < 2:
            continue
        med = statistics.median(past)
        if med >= MIN_BASELINE:
            flags.append({"source": src, "fresh_now": 0, "trailing_median": med, "severity": "GONE"})

    flags.sort(key=lambda f: f["trailing_median"], reverse=True)
    return snap, flags


def main() -> int:
    rows = json.loads((DOCS / "listings.json").read_text())
    now = datetime.now(timezone.utc)
    fresh_days = float(os.environ.get("HEALTH_FRESH_DAYS", "3"))

    history = []
    if HISTORY.exists():
        try:
            history = json.loads(HISTORY.read_text())
        except Exception:  # noqa: BLE001
            history = []

    snap, flags = evaluate(rows, history, now, fresh_days)

    history.append(snap)
    history = history[-KEEP:]
    HISTORY.write_text(json.dumps(history))
    REPORT.write_text(json.dumps(
        {"ts": now.isoformat(), "flags": flags,
         "sources_tracked": len(snap["total"]), "snapshots": len(history)}, indent=2))

    print(f"health: {len(snap['total'])} sources | {len(history)} snapshots | {len(flags)} flagged", flush=True)
    for f in flags[:25]:
        print(f"  ⚠️  {f['severity']:<9} {f['source']:<42} fresh={f['fresh_now']} vs median {f['trailing_median']:.0f}", flush=True)
    if len(history) < 3:
        print("  (building baseline — flags kick in after 2+ prior snapshots)", flush=True)
    return 1 if flags else 0


if __name__ == "__main__":
    raise SystemExit(main())
