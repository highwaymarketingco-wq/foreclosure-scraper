"""Retry pass for Claude Vision condition assessment.

Verbose, single-listing-at-a-time loop with explicit progress prints.
Bypasses the orchestrator's structlog config so output is visible in
standalone runs.

Usage:
  ANTHROPIC_API_KEY=$(cat .secrets/anthropic_api_key.txt) \
    VISION_INTER_CALL_DELAY=3 \
    uv run python scripts/retry_vision.py

NOTE: this is the legacy PAID Anthropic path, superseded by
scripts/patch_vision_gemini.py (free, 26-backend pool, incremental). It has no
caller anywhere in the repo — no launchd job, no workflow, no shell wrapper —
and is kept as a manual escape hatch. It is still a board writer, so it takes
the board lock and publishes through write_artifact like every other one.

BOARD I/O CONTRACT (do not regress):
  read  -> web_artifact.read_board_records(), which merges the lazy-detail
           sidecar back into each record's raw. A plain read of listings.json
           sees ZERO vision reports (vision is a LAZY_DETAIL_KEY), so this pass
           would re-score leads that already have a report, and writing that
           board back would strip comps/vision/CAMA from all of them.
  write -> web_artifact.write_artifact(), which re-splits the sidecar and emits
           the .gz twins, the slim payload and the detail shards from ONE
           payload. Hand-writing listings.json wrote one file out of six — and
           that one is gitignored, so the pass published nothing at all.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Configure logging BEFORE importing the scraper modules
import logging
logging.basicConfig(level=logging.WARNING, stream=sys.stdout, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from foreclosure_scraper.enrichment_vision import _assess_one, _select_image_urls
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.web_artifact import (
    BoardLockBusy, board_lock, read_board_records, write_artifact,
)

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"


def _publish(raw_data: list[dict], note: str) -> None:
    """Re-emit the whole payload set from `raw_data`.

    Records that fail Listing.model_validate go through the lenient hydrator
    rather than being dropped: publishing a board with fewer leads than it had
    is a far worse failure than a stale vision report, and this pass mutates
    dicts in place so every record must survive the round trip.
    """
    out: list[Listing] = []
    for d in raw_data:
        try:
            out.append(Listing.model_validate(d))
            continue
        except Exception:  # noqa: BLE001
            pass
        li = _dict_to_listing(d)
        if li is not None:
            li.raw = d.get("raw") or {}
            out.append(li)
    if len(out) != len(raw_data):
        print(f"REFUSING TO PUBLISH: {len(out)} of {len(raw_data)} records survived "
              f"hydration — a shrunken board is worse than a stale one", flush=True)
        return
    write_artifact(out, {"notes": note}, docs_dir=DOCS)


def _dict_to_listing(d: dict) -> Listing | None:
    fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    if "listing_type" in fields and isinstance(fields["listing_type"], str):
        try:
            fields["listing_type"] = ListingType(fields["listing_type"])
        except ValueError:
            del fields["listing_type"]
    if "property_kind" in fields and isinstance(fields["property_kind"], str):
        try:
            fields["property_kind"] = PropertyKind(fields["property_kind"])
        except ValueError:
            del fields["property_kind"]
    try:
        return Listing(**fields)
    except Exception:
        return None


async def main() -> int:
    # THE LOCK, held across read -> score -> write_artifact, including the
    # periodic checkpoint writes. A concurrent board writer silently reverts
    # whichever of the two finishes last. See web_artifact.board_lock.
    try:
        with board_lock(REPO, owner="retry_vision.py"):
            return await _run()
    except BoardLockBusy as exc:
        print(f"{exc} — refusing to write.", flush=True)
        return 1


async def _run() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set", flush=True)
        return 1

    delay = float(os.environ.get("VISION_INTER_CALL_DELAY", "3.0"))

    from anthropic import AsyncAnthropic
    import httpx

    # read_board_records: vision is a LAZY_DETAIL_KEY, so a plain read of
    # listings.json shows ZERO vision reports and the `missing` filter below
    # would select the entire board every run.
    raw_data = read_board_records(DOCS)
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(raw_data)} listings", flush=True)

    missing = [d for d in raw_data if not (d.get("raw") or {}).get("vision")]
    print(f"[{time.strftime('%H:%M:%S')}] {len(missing)} listings missing vision; processing serially with {delay}s delay", flush=True)

    if not missing:
        print("nothing to retry", flush=True)
        return 0

    # Hydrate
    pairs: list[tuple[dict, Listing]] = []
    for d in missing:
        li = _dict_to_listing(d)
        if li:
            urls = _select_image_urls(li)
            if urls:
                pairs.append((d, li))
    print(f"[{time.strftime('%H:%M:%S')}] {len(pairs)} have usable image URLs; starting", flush=True)

    client = AsyncAnthropic(api_key=api_key, max_retries=8, timeout=120.0)
    success = 0
    fail = 0
    overrides = 0
    last_save = time.time()

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
        for i, (d, li) in enumerate(pairs, 1):
            try:
                result = await _assess_one(client, li, http)
            except Exception as exc:
                print(f"[{time.strftime('%H:%M:%S')}] {i}/{len(pairs)} EXCEPTION: {str(exc)[:120]}", flush=True)
                fail += 1
                continue

            if result:
                d.setdefault("raw", {})
                d["raw"]["vision"] = result
                ct = result.get("condition_tier")
                conf = (result.get("confidence") or "").upper()
                if ct in ("move_in_ready", "cosmetic", "major", "gut") and conf in ("HIGH", "MEDIUM"):
                    old = d["raw"].get("condition_tier")
                    d["raw"]["condition_tier"] = ct
                    d["raw"]["condition_source"] = f"vision-{conf}"
                    if old != ct:
                        overrides += 1
                success += 1
                print(f"[{time.strftime('%H:%M:%S')}] {i}/{len(pairs)} OK  cond={ct} conf={conf}  {d.get('street_address') or '(no addr)'}", flush=True)
            else:
                fail += 1
                print(f"[{time.strftime('%H:%M:%S')}] {i}/{len(pairs)} FAIL {d.get('street_address') or '(no addr)'}", flush=True)

            # Periodic checkpoint save every 300 listings or 300 sec. Each save
            # is now a full write_artifact (six files, ~40s on the real board),
            # not a single json.dumps, so the old every-30-listings cadence
            # would have spent more time publishing than scoring.
            if i % 300 == 0 or (time.time() - last_save) > 300:
                _publish(raw_data, f"vision retry checkpoint: {success} scored")
                last_save = time.time()
                print(f"[{time.strftime('%H:%M:%S')}] checkpoint saved at {i}/{len(pairs)} (success={success} fail={fail})", flush=True)

            if delay > 0:
                await asyncio.sleep(delay)

    _publish(raw_data,
             f"vision retry: {success} scored, {fail} failed, {overrides} tier overrides")
    print(f"\n[{time.strftime('%H:%M:%S')}] DONE. success={success} fail={fail} overrides={overrides}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
