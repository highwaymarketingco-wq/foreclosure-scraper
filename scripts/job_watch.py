#!/usr/bin/env python3
"""Alert when a scheduled job has not reported a healthy outcome recently.

Run from launchd (deploy/mac/com.highway.foreclosure.jobwatch.plist, hourly):

    /usr/bin/python3 scripts/job_watch.py

WHY (audit 2026-09-21 O4, O10). The board had no monitor of its own. dailycourt failed
31 days in a row with "uv: command not found" and nobody was told; lrcpwa did not commit
between 9/14 and 9/21; the repo-size alert went to a GitHub issue that had no readers.
Every scheduled wrapper now appends one line per outcome to logs/job_events.jsonl
(scripts/job_event.sh, src/foreclosure_scraper/job_events.py). This reads that file and
raises an alarm in two places, so it cannot be missed by looking in only one:

  * a macOS notification (osascript display notification), and
  * one line appended to logs/job_alerts.log

An alarm is raised when

  1. a job has no healthy outcome inside its window. "Healthy" is outcome ok OR no_change
     (the job ran and correctly found nothing to do: an SOS pass with no new contacts, a
     land-records pass with no new parcels). skipped_lock, skipped_memory, failed and
     push_failed are NOT healthy. Default window 48 hours, longer for weekly jobs.
  2. the last three outcomes of a job are all failed or push_failed (a job that runs and
     fails every time, which a 48 hour window would take two days to notice).
  3. a payload file is over the warn line (scripts/check_payload_size.py, default 80 MiB)
     or the deployed site nears the Pages limit. GitHub rejects a push over 100 MiB. Since the
     payload split (audit O1) the board is docs/listings_part_NNN.json.gz, each under 24 MiB; a
     part over that cap, or a part set that disagrees with docs/board.manifest.json, also alarms.

A job that has NEVER reported (no line at all) is only alarmed once the watcher has itself
been running longer than that job's window, so installing this before every wrapper is
wired does not start with a wall of false alarms.

An alarm for the same job is repeated at most every 12 hours (--realert-hours) so a broken
job does not spam. State lives in logs/.job_watch_state.json.

    --expect job:hours   add or override an expectation (repeatable)
    --report             print the table of every job and exit (no alarms, no state)
    --no-notify          write the log line but do not raise the macOS notification
    --now ISO            pin the clock (tests)

Stdlib only and Python 3.9 compatible: launchd runs it with /usr/bin/python3.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# job -> hours allowed without a healthy outcome. Names are the job labels the wrappers
# pass to job_event_begin. Weekly jobs get a week plus slack.
DEFAULT_EXPECT = {
    "dailyvision": 48,
    "lrcpwa": 48,
    "sosagent": 48,
    "parcelcache": 200,          # Sundays
    "full_run": 240,             # popup Tue/Fri; 10 days is two missed weeks minus a day
    "family_qpaybill": 200,      # weekly
    "family_nc_tax": 200,        # weekly
    "family_sc_tax": 200,        # weekly
    "family_nc_ecourts": 72,     # daily-ish
    "backup_local_state": 72,    # nightly
}
HEALTHY = ("ok", "no_change")
PAYLOAD_WARN_MIB = 80.0


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except ValueError:
            return None


def read_events(path: Path) -> list:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    # a rotated file holds the older half of the history
    rotated = path.with_name(path.name + ".1")
    if rotated.exists():
        older = []
        try:
            for line in rotated.read_text(encoding="utf-8").splitlines():
                try:
                    older.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            pass
        out = older + out
    return out


def evaluate(events: list, expect: dict, now: datetime, first_run: datetime) -> list:
    """One row per expected job: last healthy outcome, age, verdict."""
    jobs = {}
    for e in events:
        if e.get("kind") != "job":
            continue
        jobs.setdefault(e.get("job"), []).append(e)
    rows = []
    for job, hours in sorted(expect.items()):
        evs = sorted(jobs.get(job, []), key=lambda e: e.get("end") or e.get("ts") or "")
        healthy = [e for e in evs if e.get("outcome") in HEALTHY]
        last = evs[-1] if evs else None
        last_ok = parse_ts(healthy[-1].get("end") or healthy[-1].get("ts")) if healthy else None
        age_h = (now - last_ok).total_seconds() / 3600.0 if last_ok else None
        recent = [e.get("outcome") for e in evs[-3:]]
        streak_bad = len(recent) == 3 and all(o in ("failed", "push_failed") for o in recent)
        verdict, why = "ok", ""
        if last_ok is None:
            if (now - first_run) > timedelta(hours=hours):
                verdict, why = "ALARM", "no healthy outcome has ever been reported (watcher has run %.0f h)" % (
                    (now - first_run).total_seconds() / 3600.0)
            else:
                verdict, why = "waiting", "no events yet (watcher started %.0f h ago)" % (
                    (now - first_run).total_seconds() / 3600.0)
        elif age_h > hours:
            verdict = "ALARM"
            why = "no healthy outcome for %.0f h (limit %d h); last outcome: %s" % (
                age_h, hours, last.get("outcome") if last else "none")
        if streak_bad:
            verdict = "ALARM"
            why = (why + "; " if why else "") + "last 3 runs all failed (%s)" % ", ".join(recent)
        rows.append({"job": job, "limit_h": hours, "last_outcome": last.get("outcome") if last else None,
                     "last_ok": last_ok.strftime("%Y-%m-%d %H:%M") if last_ok else None,
                     "age_h": round(age_h, 1) if age_h is not None else None,
                     "runs": len(evs), "verdict": verdict, "why": why})
    return rows


def payload_alarms(root: Path) -> list:
    out = []
    script = root / "scripts" / "check_payload_size.py"
    if not script.exists():
        return out
    try:
        res = subprocess.run([sys.executable, str(script), "--json", "--root", str(root),
                              "--warn-mib", str(PAYLOAD_WARN_MIB)],
                             capture_output=True, text=True, timeout=120)
        data = json.loads(res.stdout or "{}")
    except Exception:  # noqa: BLE001
        return out
    for f in data.get("files", []):
        if f.get("status") in ("WARN", "BLOCK") and f["mib"] >= PAYLOAD_WARN_MIB:
            out.append({"key": "payload:" + f["path"],
                        "msg": "%s is %.1f MiB (%.0f%% of GitHub's 100 MiB push limit)" % (
                            f["path"], f["mib"], f["pct_of_github_limit"])})
        elif f.get("status") == "OVER_PART":
            # a board part over its own cap (24 MiB): far from GitHub's wall, but it means the
            # writer did not cut the board (audit O1), and the next growth spurt would not be caught
            out.append({"key": "payload:" + f["path"],
                        "msg": "%s is %.1f MiB, over the %.0f MiB board-part cap (the payload split did not "
                               "run or a part was written by hand)" % (
                                   f["path"], f["mib"], (data.get("board_parts") or {}).get("part_max_mib", 24))})
    for i, msg in enumerate((data.get("parts_problems") or []) + (data.get("parts_warnings") or [])):
        out.append({"key": "payload:parts:%d" % i, "msg": "board parts: " + msg})
    site = data.get("site") or {}
    if site.get("status") in ("WARN", "FAIL"):
        out.append({"key": "payload:site", "msg": "deployed site is %.0f MB (Pages warns at %d, fails at %d)" % (
            site["mb"], site["warn_mb"], site["fail_mb"])})
    return out


def notify(title: str, message: str) -> None:
    if sys.platform != "darwin":
        return
    msg = message.replace("\\", " ").replace('"', "'")[:230]
    ttl = title.replace("\\", " ").replace('"', "'")[:60]
    try:
        subprocess.run(["osascript", "-e", 'display notification "%s" with title "%s"' % (msg, ttl)],
                       capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--events", default=None)
    ap.add_argument("--expect", action="append", default=[], help="job:hours (repeatable)")
    ap.add_argument("--realert-hours", type=float, default=12.0)
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--no-payload", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--now", default=None)
    args = ap.parse_args(argv)

    root = Path(args.root)
    logs = root / "logs"
    events_path = Path(args.events) if args.events else logs / "job_events.jsonl"
    now = parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    expect = dict(DEFAULT_EXPECT)
    for item in args.expect:
        name, _, hrs = item.partition(":")
        expect[name.strip()] = float(hrs)

    state_path = logs / ".job_watch_state.json"
    state = {}
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    first_run = parse_ts(state.get("first_run")) or now

    events = read_events(events_path)
    rows = evaluate(events, expect, now, first_run)

    if args.report:
        print("%-22s %-6s %-14s %-16s %-8s %s" % ("job", "limit", "last outcome", "last healthy", "age_h", "verdict"))
        for r in rows:
            print("%-22s %-6s %-14s %-16s %-8s %s %s" % (
                r["job"], r["limit_h"], r["last_outcome"] or "-", r["last_ok"] or "-",
                r["age_h"] if r["age_h"] is not None else "-", r["verdict"], r["why"]))
        return 0

    alarms = [{"key": "job:" + r["job"], "msg": "%s: %s" % (r["job"], r["why"])} for r in rows if r["verdict"] == "ALARM"]
    if not args.no_payload:
        alarms += payload_alarms(root)

    last_alert = state.get("last_alert") or {}
    raised = []
    for a in alarms:
        prev = parse_ts(last_alert.get(a["key"]))
        if prev is not None and (now - prev) < timedelta(hours=args.realert_hours):
            continue
        raised.append(a)
        last_alert[a["key"]] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # forget keys that are healthy again so a later relapse alarms immediately
    active = {a["key"] for a in alarms}
    last_alert = {k: v for k, v in last_alert.items() if k in active}

    logs.mkdir(parents=True, exist_ok=True)
    if raised:
        with open(logs / "job_alerts.log", "a", encoding="utf-8") as fh:
            for a in raised:
                fh.write("%s ALERT %s\n" % (now.strftime("%Y-%m-%d %H:%M:%S"), a["msg"]))
        if not args.no_notify:
            first = raised[0]["msg"]
            more = " (+%d more, see logs/job_alerts.log)" % (len(raised) - 1) if len(raised) > 1 else ""
            notify("Foreclosure engine needs attention", first + more)
        for a in raised:
            print("ALERT", a["msg"])
    else:
        print("job_watch: %d job(s) checked, %d active alarm(s), %d newly raised" % (len(rows), len(alarms), len(raised)))

    state.update({"first_run": first_run.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "last_run": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "last_alert": last_alert})
    try:
        state_path.write_text(json.dumps(state, indent=1))
    except OSError:
        pass
    return 1 if alarms else 0


if __name__ == "__main__":
    sys.exit(main())
