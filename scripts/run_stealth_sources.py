#!/usr/bin/env python3
"""Mac side of the cloud split — run ONLY the residential-IP stealth scrapers
and hand their leads to the VM.

The 39 stealth-browser sources (sc_public_index, nc_sos_ucc, the law-firm
foreclosure calendars, zillow/auction, nc_ecourts, the DataDome land sites,
...) only clear their bot walls from a clean residential IP, so they stay on
this Mac. This script runs just those, writes their leads to
``docs/handoff/stealth_leads/`` (manifest.json + one JSON Lines shard per source,
format in foreclosure_scraper.stealth_handoff_store), and pushes ONLY that
directory. The Oracle VM's normal run ingests it (national.stealth_handoff) and
does all the heavy enrichment + board publish.

It used to write one file, docs/handoff/stealth_leads.json. That file reached
93.8 MiB on 2026-10-08 (51,730 leads), 1.2 MiB under the pre-commit gate's
95 MiB limit (scripts/git_size_gate.sh), so the first bigger morning would have
had its commit refused. The first sharded run deletes the legacy file in the
same commit; the VM reader still falls back to it when no manifest exists.

Deliberately lightweight: it never loads the 560 MB board and runs no
enrichment, so it stays well under 8 GB and finishes fast.

Run:            uv run python scripts/run_stealth_sources.py
No-push (test): HANDOFF_PUSH=0 uv run python scripts/run_stealth_sources.py
Schedule:       deploy/mac/install_stealth_schedule.sh
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from foreclosure_scraper import stealth_handoff_store as store  # noqa: E402
from foreclosure_scraper.scrapers._registry import all_scrapers  # noqa: E402
from foreclosure_scraper.source_split import residential_slugs   # noqa: E402

HANDOFF_ROOT = ROOT / "docs" / "handoff"
HANDOFF_DIR = store.shard_dir(HANDOFF_ROOT)          # docs/handoff/stealth_leads/
LEGACY = store.legacy_file(HANDOFF_ROOT)             # docs/handoff/stealth_leads.json (removed)
PUSH = os.environ.get("HANDOFF_PUSH", "1") != "0"


def _git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", "-C", str(ROOT), *args],
                       capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def _publish(lead_count: int, run_log: list[dict]) -> None:
    """Commit + push ONLY the hand-off. The board (docs/listings_part_*.json.gz)
    is written by the VM, never here, so there is no board conflict — a rebase
    handles the two hosts pushing different files to the same branch.

    The commit names its paths (`git commit -- <paths>`), so anything else that
    happens to be staged in this working tree stays out of the hand-off commit.
    The legacy single file is in the pathspec so its deletion is committed too."""
    paths = [str(HANDOFF_DIR.relative_to(ROOT))]
    if _git("ls-files", "--error-unmatch", str(LEGACY.relative_to(ROOT)))[0] == 0:
        paths.append(str(LEGACY.relative_to(ROOT)))
    _git("add", "-A", "--", *paths)
    rc, _ = _git("diff", "--staged", "--quiet", "--", *paths)
    if rc == 0:
        print("hand-off unchanged — nothing to push", flush=True)
        return
    rc, out = _git("commit", "-q", "-m",
                   f"mac stealth hand-off: {lead_count} leads ({datetime.now().date()})",
                   "--", *paths)
    if rc != 0:
        print(f"⚠️  hand-off commit refused: {out[:300]}", flush=True)
        return
    for attempt in range(3):
        _git("pull", "--rebase", "--autostash", "origin", "main")
        rc, out = _git("push", "origin", "main")
        if rc == 0:
            print("✓ hand-off pushed to GitHub", flush=True)
            return
        print(f"push attempt {attempt + 1} failed: {out[:160]}", flush=True)
    print("⚠️  hand-off committed locally but push failed after retries", flush=True)


async def main() -> int:
    res = residential_slugs()
    by_slug = {s.slug: s for s in all_scrapers() if s.slug in res}
    print(f"stealth sources to run: {len(by_slug)}", flush=True)

    # one JSON line per lead, grouped by the scraper that produced it (the shard key)
    lines_by_slug: dict[str, list[str]] = {}
    run_log: list[dict] = []
    for slug in sorted(by_slug):
        s = by_slug[slug]
        try:
            results = list(await s.safe_run())
            lines_by_slug[slug] = [li.model_dump_json() for li in results]
            outcome = getattr(s, "last_outcome", "OK")
            print(f"  {slug}: {len(results)} ({outcome})", flush=True)
            run_log.append({"slug": slug, "count": len(results), "outcome": str(outcome)})
        except Exception as exc:  # noqa: BLE001 - one dead source must not stop the rest
            print(f"  {slug}: ERROR {str(exc)[:120]}", flush=True)
            run_log.append({"slug": slug, "count": 0, "outcome": "ERROR",
                            "error": str(exc)[:200]})

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": os.uname().nodename,
        "sources_run": len(by_slug),
        "by_source": run_log,
    }
    manifest = store.write_sharded(HANDOFF_ROOT, meta, lines_by_slug)
    lead_count = manifest["lead_count"]
    ok = sum(1 for r in run_log if r["count"] > 0)
    biggest = max((sh["bytes"] for sh in manifest["shards"]), default=0)
    print(f"\nwrote {lead_count} leads from {ok}/{len(by_slug)} live sources -> "
          f"{HANDOFF_DIR} ({manifest['shard_count']} shards, largest "
          f"{biggest / 1048576:.1f} MiB)", flush=True)

    if PUSH:
        _publish(lead_count, run_log)
    else:
        print("HANDOFF_PUSH=0 — skipped git push", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
