#!/usr/bin/env python3
"""Stamp existing link_check verdicts with the time they were actually taken.

Link validation used to record ``{"status": "ok", "http": 200}`` with no
timestamp. The new incremental validator trusts an "ok" for LINK_RECHECK_DAYS,
but an undated verdict has to be re-checked once and stamped, so without this
backfill the first run after the change still pays the full 7.7-hour pass.

Those links were checked. We just failed to write down when. This reads the
run log for the ``link.validate.done`` event, takes that moment as the truth,
and stamps every undated "ok"/"skipped" verdict with it.

Only "ok" and "skipped" are stamped. Broken, auth-walled and unreachable links
are re-checked every run regardless of age, so dating them changes nothing and
would only make a stale failure look freshly confirmed.

Refuses to run while the engine is running: one board-writer at a time.

    python3 scripts/backfill_link_check_timestamps.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact  # noqa: E402

STAMPABLE = {"ok", "skipped"}


def _engine_running() -> bool:
    # The pattern must not start with "-": pgrep parses a leading dash as an
    # option, silently matches nothing, and the mutex never fires. "--" ends
    # option parsing so the pattern is taken literally.
    r = subprocess.run(
        ["pgrep", "-f", "--", r"run_local\.sh|-m foreclosure_scraper"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _validation_time() -> str | None:
    """When link validation last finished, from the newest run log."""
    logs = sorted((REPO / "logs").glob("local-run-*.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    for log in logs[:3]:
        hit = None
        with log.open("r", errors="replace") as fh:
            for line in fh:
                if '"link.validate.done"' in line:
                    hit = line
        if not hit:
            continue
        m = re.search(r'"timestamp":\s*"([^"]+)"', hit)
        if m:
            return m.group(1)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--checked-at", help="ISO8601 override for the stamp")
    args = ap.parse_args()

    if _engine_running():
        print("engine is running — refusing to touch the board", file=sys.stderr)
        return 1

    stamp = args.checked_at or _validation_time()
    if not stamp:
        print("no link.validate.done in the recent run logs; pass --checked-at",
              file=sys.stderr)
        return 1
    print(f"stamping undated verdicts as checked at {stamp}")

    listings = load_board()

    stamped = skipped_state = already = missing = 0
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        lc = raw.get("link_check")
        if not isinstance(lc, dict):
            missing += 1
            continue
        if lc.get("checked"):
            already += 1
            continue
        if lc.get("status") not in STAMPABLE:
            skipped_state += 1
            continue
        lc["checked"] = stamp
        stamped += 1

    print(f"  stamped            {stamped:,}")
    print(f"  left undated       {skipped_state:,}  (broken/auth/unreachable, "
          f"re-checked every run by design)")
    print(f"  already had a date {already:,}")
    print(f"  no link_check      {missing:,}")

    if args.dry_run:
        print("dry run — board not written")
        return 0
    if not stamped:
        print("nothing to stamp — board not written")
        return 0

    lp, _ = write_artifact(
        listings,
        {"notes": f"link_check timestamp backfill (checked {stamp})"},
    )
    print(f"wrote {lp}: {len(listings):,} leads")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
