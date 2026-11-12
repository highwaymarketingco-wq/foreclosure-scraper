#!/usr/bin/env python3
"""Publish the board a crashed run had already built.

WHY THIS EXISTS
    On 2026-08-06 the Mac rebooted 44.6 hours into a run, one phase short of
    publishing. Every bit of it was lost — the merged 47,090-lead board plus
    GIS, geocoding, owner resolution, parcel lookups and comps — because the
    only write to disk was the final publish.

    Checkpointing now runs through the whole pass (see checkpoint.py). This is
    the other half: it takes the newest checkpoint and publishes it, so an
    interrupted run costs the time it had left, not everything it had done.

WHAT IT DOES NOT DO
    It does not finish the run. A checkpoint taken at, say, the owner_mailing
    phase has not been through vision, comps or the later enrichers. Those
    fields will be missing until the next full run fills them — which it will,
    because the enrichers are idempotent and target only leads still missing
    the field. Publishing a partial board beats publishing a three-day-old one.

USAGE
    python3 scripts/recover_from_checkpoint.py            # show what is there
    python3 scripts/recover_from_checkpoint.py --publish  # write it to the board
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import checkpoint  # noqa: E402
from foreclosure_scraper.web_artifact import load_board, write_artifact  # noqa: E402


def _engine_running() -> bool:
    # Pattern must not start with "-": pgrep reads a leading dash as an option,
    # matches nothing, and the guard silently never fires.
    r = subprocess.run(
        ["pgrep", "-f", "--", r"run_local\.sh|-m foreclosure_scraper|merge_today_sources"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _coverage(listings) -> dict:
    def has(li, f):
        return bool(str(getattr(li, f, "") or "").strip())
    return {
        "leads": len(listings),
        "with address": sum(1 for li in listings if has(li, "street_address")),
        "with owner": sum(1 for li in listings if has(li, "owner_name")),
        "with parcel": sum(1 for li in listings if has(li, "parcel_id")),
        "with coords": sum(1 for li in listings
                           if li.latitude is not None and li.longitude is not None),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true",
                    help="actually write the checkpoint to the published board")
    ap.add_argument("--max-age-h", type=float, default=None)
    args = ap.parse_args()

    m = checkpoint.manifest()
    if not m:
        print("no checkpoint found", file=sys.stderr)
        return 1
    age = checkpoint.age_hours()
    print(f"checkpoint: phase={m.get('phase')!r}  leads={m.get('count'):,}  "
          f"saved={m.get('saved_at')}  age={age:.1f}h" if age is not None
          else f"checkpoint: {m}")

    if _engine_running():
        print("\nengine is running — refusing to touch the board", file=sys.stderr)
        return 1

    listings = checkpoint.load(max_age_h=args.max_age_h)
    if not listings:
        print("checkpoint could not be loaded (too old or unreadable)", file=sys.stderr)
        return 1

    try:
        current = load_board()
    except Exception:  # noqa: BLE001
        current = []
    print(f"\n{'':22}{'checkpoint':>12}{'published now':>16}")
    ck, cur = _coverage(listings), _coverage(current)
    for k in ck:
        print(f"  {k:20}{ck[k]:>12,}{cur.get(k, 0):>16,}")

    if len(listings) < len(current):
        print(f"\n  NOTE: the checkpoint has FEWER leads than what is published "
              f"({len(listings):,} < {len(current):,}). Check before publishing.")

    if not args.publish:
        print("\ndry run — pass --publish to write it")
        return 0

    lp, _ = write_artifact(
        listings,
        {"notes": f"recovered from checkpoint taken at phase {m.get('phase')!r}",
         "recovered_from_checkpoint": True, "checkpoint_phase": m.get("phase")})
    print(f"\nwrote {lp}: {len(listings):,} leads")
    print("the next full run will fill the enrichers this checkpoint never reached")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
