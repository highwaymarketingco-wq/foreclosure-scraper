"""Retry pass for Claude Vision condition assessment.

Verbose, single-listing-at-a-time loop with explicit progress prints.
Bypasses the orchestrator's structlog config so output is visible in
standalone runs.

Usage:
  ANTHROPIC_API_KEY=$(cat .secrets/anthropic_api_key.txt) \
    VISION_INTER_CALL_DELAY=3 \
    uv run python scripts/retry_vision.py
"""
from __future__ import annotations

import asyncio
import json
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
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set", flush=True)
        return 1

    delay = float(os.environ.get("VISION_INTER_CALL_DELAY", "3.0"))

    from anthropic import AsyncAnthropic
    import httpx

    listings_path = Path("docs/listings.json")
    raw_data = json.loads(listings_path.read_text())
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

            # Periodic checkpoint save every 30 listings or 60 sec
            if i % 30 == 0 or (time.time() - last_save) > 60:
                listings_path.write_text(json.dumps(raw_data, default=str))
                last_save = time.time()
                print(f"[{time.strftime('%H:%M:%S')}] checkpoint saved at {i}/{len(pairs)} (success={success} fail={fail})", flush=True)

            if delay > 0:
                await asyncio.sleep(delay)

    listings_path.write_text(json.dumps(raw_data, default=str))
    print(f"\n[{time.strftime('%H:%M:%S')}] DONE. success={success} fail={fail} overrides={overrides}", flush=True)

    meta_path = Path("docs/run_meta.json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["vision_retry"] = {"attempted": len(pairs), "succeeded": success, "failed": fail}
        meta_path.write_text(json.dumps(meta, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
