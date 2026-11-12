#!/usr/bin/env python3
"""Carry a gated full run's publish inputs onto the pre_publish checkpoint of a tail re-run.

WHY (2026-10-07, docs/HANDOFF.md item 81)
    ``deploy/oracle/vm_run.sh --stop-before-publish`` ends with a pre_publish checkpoint whose
    ``resume_state.json`` says what that run's own publish would write besides the board: the sold
    pool, run_health.json and the Sheet export + digest email, and it holds the scrape-phase health
    (``summary.source_status``, ``source_alarms``, ``errors``, ``regressions``) that only the scrape
    half of the run knows. When the reviewed board needs a fix that lives in the post-dot_ocr tail
    (scoring, verification), ``vm_resume.sh --enrich-only`` re-runs just that tail and saves a NEW
    pre_publish checkpoint, and a resume checkpoint says all three switches are OFF and has no
    per-source data: publishing it writes the board alone. This script puts the full run's inputs
    back, so the re-run's board publishes exactly what the full run's own publish would have.

WHAT IT DOES
    Reads the full run's saved state (a directory holding resume_state.json, manifest.json and
    sold_pool.json.gz: the archive copy made before the re-run) and the live checkpoint (the
    re-run's pre_publish). In the live ``resume_state.json`` it sets
        publish                the full run's three switches
        errors                 the full run's scraper error list
        enrichment_stats       the full run's stats, overlaid by the re-run's (same key: the re-run)
        summary.source_status, source_alarms, regressions, errors, off_footprint_removed
                               the full run's (the tail cannot know them)
        summary.by_source      the full run's per-source scrape counts, when the re-run has none
                               (a resume never does)
        summary.notes          the re-run's note plus a sentence naming the full run it carries
    and copies ``sold_pool.json.gz`` beside the board when the switch is on. Everything the tail
    recomputes from the new board (total, by_state, by_county_top, by_source, outreach,
    new_this_week, new_lis_pendens) is left as the re-run wrote it. The state's token still pairs
    it with the new manifest. Nothing here touches the board file.

REFUSES (exit 1, changes nothing) unless: the full run's manifest is a pre_publish checkpoint with
    its state file and a matching token; the live manifest is a pre_publish checkpoint saved by a
    resume (``resumed_from``) with a matching token; the live board is within 5% of the full run's
    row count; and a switch that needs the sold pool has it.

Usage:
    python3 scripts/carry_publish_state.py --from data/checkpoint_archive/pre_publish_<ts> [--dry-run]
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
LIVE_DIR = REPO / "data" / "checkpoint"
STATE_FILE = "resume_state.json"
MANIFEST_FILE = "manifest.json"
SOLD_POOL_FILE = "sold_pool.json.gz"
#: summary keys only the scrape half of a full run knows
SCRAPE_SUMMARY_KEYS = ("source_status", "source_alarms", "regressions", "errors",
                       "off_footprint_removed")
MAX_COUNT_DRIFT = 0.05


class CarryRefused(RuntimeError):
    """The two checkpoints do not belong together; nothing was changed."""


def _check_pair(old_manifest: dict, old_state: dict, new_manifest: dict, new_state: dict,
                *, old_has_sold_pool: bool) -> None:
    if old_manifest.get("phase") != "pre_publish":
        raise CarryRefused(f"the full run's checkpoint is phase {old_manifest.get('phase')!r}, "
                           "not pre_publish")
    if not old_manifest.get("publish_state"):
        raise CarryRefused("the full run's manifest names no state file")
    tok = old_manifest.get("state_token")
    if not tok or old_state.get("state_token") != tok:
        raise CarryRefused("the full run's state file does not belong to its manifest (token)")
    pub = old_state.get("publish") or {}
    if not isinstance(pub, dict) or not any(pub.values()):
        raise CarryRefused("the full run's state records no publish switch on; nothing to carry")
    if pub.get("write_sold_pool") and not old_has_sold_pool:
        raise CarryRefused("the full run's sold pool is switched on but its file is missing")
    if new_manifest.get("phase") != "pre_publish":
        raise CarryRefused(f"the live checkpoint is phase {new_manifest.get('phase')!r}, "
                           "not pre_publish (run --enrich-only first)")
    if not new_manifest.get("resumed_from"):
        raise CarryRefused("the live checkpoint was not saved by a resume (no resumed_from): "
                           "it is not a re-run to carry state onto")
    ntok = new_manifest.get("state_token")
    if not ntok or new_state.get("state_token") != ntok:
        raise CarryRefused("the live state file does not belong to the live manifest (token)")
    a, b = old_manifest.get("count"), new_manifest.get("count")
    if not isinstance(a, int) or not isinstance(b, int) or a <= 0:
        raise CarryRefused("a checkpoint manifest carries no row count")
    if abs(b - a) / a > MAX_COUNT_DRIFT:
        raise CarryRefused(f"the live board has {b:,} rows, the full run's {a:,}: more than "
                           f"{MAX_COUNT_DRIFT:.0%} apart, they are not the same run's board")


def carry(old_state: dict, new_state: dict, *, old_saved_at: Optional[str] = None) -> dict:
    """The live state with the full run's publish inputs carried over (pure; inputs unchanged)."""
    out = copy.deepcopy(new_state)
    out["publish"] = dict(old_state.get("publish") or {})
    out["errors"] = list(old_state.get("errors") or [])
    out["enrichment_stats"] = {**(old_state.get("enrichment_stats") or {}),
                               **(new_state.get("enrichment_stats") or {})}
    summary = dict(out.get("summary") or {})
    old_summary = old_state.get("summary") or {}
    for k in SCRAPE_SUMMARY_KEYS:
        if k in old_summary:
            summary[k] = copy.deepcopy(old_summary[k])
    # by_source is the scrape's per-source row count. A resume has no scrape, so its summary says
    # {} (main.TailState's empty Counter); publishing that made run_health.json show every source
    # at count 0 beside an "OK (3058)" status and mailed a digest with no per-source table (the
    # 10/7 publish, audit 2026-10-09). Carry the full run's when the re-run has none.
    if not summary.get("by_source") and old_summary.get("by_source"):
        summary["by_source"] = copy.deepcopy(old_summary["by_source"])
    note = str(summary.get("notes") or "").strip()
    carried = (f"scrape-phase health, errors, the sold pool and the publish switches carried from the "
               f"full run saved {old_saved_at or 'earlier'} (scripts/carry_publish_state.py)")
    summary["notes"] = (note + "; " if note else "") + carried
    out["summary"] = summary
    return out


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="src", required=True,
                    help="directory holding the full run's resume_state.json, manifest.json, "
                         "sold_pool.json.gz (the archive copy made before the re-run)")
    ap.add_argument("--live", default=str(LIVE_DIR), help="the live checkpoint directory")
    ap.add_argument("--dry-run", action="store_true", help="validate and print, change nothing")
    args = ap.parse_args(argv)
    src, live = Path(args.src), Path(args.live)
    try:
        old_manifest, old_state = _read(src / MANIFEST_FILE), _read(src / STATE_FILE)
        new_manifest, new_state = _read(live / MANIFEST_FILE), _read(live / STATE_FILE)
        _check_pair(old_manifest, old_state, new_manifest, new_state,
                    old_has_sold_pool=(src / SOLD_POOL_FILE).exists())
    except (CarryRefused, OSError, ValueError) as exc:
        print(f"carry_publish_state: refused: {exc}", file=sys.stderr)
        return 1
    out = carry(old_state, new_state, old_saved_at=old_manifest.get("saved_at"))
    pub = out["publish"]
    print(f"full run : {old_manifest.get('count'):,} rows saved {old_manifest.get('saved_at')}")
    print(f"re-run   : {new_manifest.get('count'):,} rows saved {new_manifest.get('saved_at')} "
          f"(resumed from {new_manifest.get('resumed_from')})")
    print("publish will write: the board"
          + "".join(f", {n}" for k, n in (("write_sold_pool", "sold pool"),
                                           ("write_run_health", "run_health.json"),
                                           ("export_and_email", "Sheet export + digest email"))
                    if pub.get(k)))
    print(f"carried summary keys: {[k for k in SCRAPE_SUMMARY_KEYS if k in (old_state.get('summary') or {})]}")
    if args.dry_run:
        print("dry run: nothing changed")
        return 0
    if pub.get("write_sold_pool"):
        shutil.copy2(src / SOLD_POOL_FILE, live / (SOLD_POOL_FILE + ".tmp"))
        (live / (SOLD_POOL_FILE + ".tmp")).replace(live / SOLD_POOL_FILE)
    tmp = live / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(out))
    tmp.replace(live / STATE_FILE)
    print("carried: resume_state.json rewritten" + (", sold_pool.json.gz copied" if pub.get("write_sold_pool") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
