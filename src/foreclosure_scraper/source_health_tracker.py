"""Per-source silent-failure alarm: rolling baselines + consecutive-zero +
sustained-bleed detection across runs.

The existing run_health flags a SINGLE-run regression (got 0, expected >=N).
That misses two real failure modes:
  * a source that breaks and stays at 0 for weeks (a one-week 0 could be a
    transient blip; 2+ consecutive 0s after a real history = it's broken), and
  * a source that silently bleeds — was ~50/run, now quietly 5/run — which
    never trips the single-run check because 5 still clears its minimum.

This module keeps a small rolling history per source (docs/source_history.json)
and raises a CRITICAL alarm the owner sees in the weekly email. It is
deliberately conservative (won't fire on new or seasonal/sparse sources) so an
alarm always means "go look."
"""
from __future__ import annotations

import json
import os
import traceback
import urllib.request
from pathlib import Path
from typing import Any, Optional

import structlog

log = structlog.get_logger()

HISTORY_FILE = "source_history.json"
HISTORY_CAP = 12          # ~3 months of weekly runs
ZERO_STREAK_ALARM = 2     # 0 listings for >=2 consecutive runs -> dead
RELIABLE_FRAC = 0.5       # only "dead"-alarm sources that usually produce
BLEED_BASELINE_MIN = 8    # need meaningful volume before a drop is alarming
BLEED_RATIO = 0.4         # current < 40% of baseline = >60% drop
BLEED_CONSEC = 2          # sustained for >=2 runs (not a one-week dip)


def _median(xs: list[int]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    m = len(s) // 2
    return float(s[m]) if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


def evaluate_source(counts: list[int], expected_min: int = 0) -> Optional[dict]:
    """Pure check: given a source's run-count history (oldest..newest, current
    last), return an alarm dict or None. Conservative — needs real history."""
    if len(counts) < 2:
        return None  # not enough history to judge
    cur = counts[-1]
    prior = counts[:-1]
    prior_nonzero = [c for c in prior if c > 0]
    baseline = _median(prior_nonzero)
    reliable = (len(prior_nonzero) / len(prior)) >= RELIABLE_FRAC if prior else False

    # trailing consecutive zeros (including current)
    streak = 0
    for c in reversed(counts):
        if c == 0:
            streak += 1
        else:
            break

    # DEAD: a normally-producing source has gone silent for >=2 runs
    if streak >= ZERO_STREAK_ALARM and baseline > 0 and reliable:
        return {
            "kind": "dead",
            "current": cur,
            "baseline": round(baseline),
            "streak": streak,
            "reason": f"0 listings for {streak} consecutive runs "
                      f"(normally ~{round(baseline)}/run) — source likely broken",
        }

    # BLEEDING: meaningful source dropped >60% and stayed down (not a blip)
    if baseline >= BLEED_BASELINE_MIN and len(counts) >= BLEED_CONSEC + 1:
        last = counts[-BLEED_CONSEC:]
        if all(0 < c < baseline * BLEED_RATIO for c in last):
            drop = round(100 * (1 - cur / baseline))
            return {
                "kind": "bleeding",
                "current": cur,
                "baseline": round(baseline),
                "drop_pct": drop,
                "reason": f"down {drop}% ({cur} vs ~{round(baseline)} baseline) "
                          f"for {len(last)} runs — partial failure",
            }
    return None


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _send_ntfy(alarms: dict[str, dict]) -> None:
    """Free phone push when a source alarm fires. OFF unless NTFY_TOPIC is set
    (ntfy.sh — no account, no cost). Never raises."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic or not alarms:
        return
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    body = "\n".join(f"{slug}: {a.get('reason', 'alarm')}"
                     for slug, a in sorted(alarms.items()))[:3500]
    try:
        req = urllib.request.Request(
            f"{server}/{topic}", data=body.encode("utf-8"), method="POST",
            headers={
                "Title": f"{len(alarms)} foreclosure source alarm(s)",
                "Priority": "high", "Tags": "rotating_light",
            })
        urllib.request.urlopen(req, timeout=10)
        log.info("source_health.ntfy_sent", count=len(alarms))
    except Exception:
        log.error("source_health.ntfy_failed", traceback=traceback.format_exc())


def update_source_health(by_source: dict[str, int], expected: dict[str, int],
                         docs_dir: Path | str) -> dict[str, dict]:
    """Append this run's counts to the rolling history, evaluate each source,
    persist, and return {slug: alarm} for any source in alarm state.

    Resilient: never raises — a tracker failure must not fail the run."""
    alarms: dict[str, dict] = {}
    try:
        path = Path(docs_dir) / HISTORY_FILE
        hist = _load(path)
        slugs = set(expected) | set(by_source) | set(hist)
        for slug in slugs:
            n = int(by_source.get(slug, 0))
            rec = hist.setdefault(slug, {"counts": []})
            counts = list(rec.get("counts") or [])
            counts.append(n)
            counts = counts[-HISTORY_CAP:]
            rec["counts"] = counts
            a = evaluate_source(counts, int(expected.get(slug, 0)))
            if a:
                rec["alarm"] = a
                alarms[slug] = a
            else:
                rec.pop("alarm", None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(hist, indent=2, sort_keys=True))
        if alarms:
            log.warning("source_health.alarms", count=len(alarms),
                        slugs=sorted(alarms))
            _send_ntfy(alarms)
    except Exception:
        log.error("source_health.failed", traceback=traceback.format_exc())
    return alarms
