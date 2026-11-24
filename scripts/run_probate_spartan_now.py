#!/usr/bin/env python3
"""One-shot/resumable driver for enrichment_probate_spartan.py.

Greenwood (20,545 decedents) and Newberry (13,366) never got a completed
cache on disk (only Calhoun did, same day the module was built 2026-10-09) --
confirmed 2026-11-24 this is NOT a code bug (a direct read_index() call against
Greenwood's real portal works fine) and NOT a missing-precondition issue (the
board carries 1,303 Greenwood + 1,253 Newberry SC rows, easily enough to pass
enrich_probate_spartan()'s own `want` gate). Whatever has kept this from ever
completing in main.py's regular enrichment pass, the fix here is the same as
fill_gaston_rod_batch.py's: just run it directly, with a real deadline, and
let its own resumable on-disk cache (read_index()/save_cache()) carry partial
progress across invocations until each county's index is complete.

Usage:
    python scripts/run_probate_spartan_now.py
    python scripts/run_probate_spartan_now.py --budget-s 1400
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_probate_spartan import ENV_BUDGET  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402


def _collect(docs: Path, counties: set[str]) -> list[Listing]:
    out: list[Listing] = []
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if rec.get("state") != "SC":
            continue
        county = (rec.get("county") or "").strip().title().replace(" County", "")
        if county not in counties:
            continue
        try:
            out.append(Listing.model_validate(rec))
        except Exception:  # noqa: BLE001
            continue
    return out


def main() -> int:
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-s", type=float, default=1400.0)
    ap.add_argument("--counties", default="Greenwood,Newberry,Calhoun")
    args = ap.parse_args()
    os.environ[ENV_BUDGET] = str(args.budget_s)
    os.environ.setdefault("BOARD_PATCH_ALLOW_LARGE", "1")

    docs = REPO / "docs"
    counties = {c.strip().title() for c in args.counties.split(",") if c.strip()}
    targets = _collect(docs, counties)
    print(f"targets: {len(targets):,} SC rows across {sorted(counties)}")

    from foreclosure_scraper.enrichment_probate_spartan import enrich_probate_spartan
    pre_keys = {li.dedupe_key(): li for li in targets}
    stats = asyncio.run(enrich_probate_spartan(targets))
    print("enrich_probate_spartan stats:", {k: v for k, v in stats.items() if k != "counties"})
    print("per-county detail:", stats.get("counties"))

    patches: dict[str, dict] = {}
    for key, li in pre_keys.items():
        if isinstance(li.raw, dict) and (li.raw.get("probate_index_match") or li.raw.get("probate")):
            patch = {}
            if li.raw.get("probate_index_match"):
                patch["probate_index_match"] = li.raw["probate_index_match"]
            if li.raw.get("probate"):
                patch["probate"] = li.raw["probate"]
            patches[key] = {"raw": patch}

    print(f"rows with a real probate match to patch: {len(patches):,}")
    if not patches:
        print("nothing to patch this run (indexes may still be building -- rerun to resume).")
        return 0

    with board_lock(REPO, owner="run_probate_spartan_now", wait=1800, poll=10):
        result = patch_existing_rows(
            patches, {"notes": "SC Spartan-portal probate decedent-index match (Greenwood/Newberry/Calhoun)"},
            docs_dir=docs)
    print("patch result:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
