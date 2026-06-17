"""Fast re-Vision patch: apply Gemini Vision to the CURRENT docs/listings.json
without re-running the full pipeline, then recompute calc + grade + rewrite.

Use when the scraped/enriched data is fresh but Vision needs (re)running on a
different provider/config. Honors VISION_PROVIDER / VISION_MAX_LISTINGS /
VISION_INTER_CALL_DELAY from the env (run_local.sh-style). Gemini runs one
parallel stream per key.

  GEMINI_API_KEY_1=.. GEMINI_API_KEY_2=.. VISION_PROVIDER=gemini \
    VISION_MAX_LISTINGS=800 uv run python scripts/patch_vision_gemini.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_vision import enrich_with_vision
from foreclosure_scraper.valuation import calc as valuation_calc
from foreclosure_scraper.valuation import grading as valuation_grading
from foreclosure_scraper.web_artifact import _to_dict


def _hydrate(d: dict) -> Listing | None:
    fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    if isinstance(fields.get("listing_type"), str):
        try:
            fields["listing_type"] = ListingType(fields["listing_type"])
        except ValueError:
            fields.pop("listing_type", None)
    if isinstance(fields.get("property_kind"), str):
        try:
            fields["property_kind"] = PropertyKind(fields["property_kind"])
        except ValueError:
            fields.pop("property_kind", None)
    try:
        li = Listing.model_validate(fields)
    except Exception:
        return None
    li.raw = d.get("raw") or {}
    return li


async def main() -> int:
    path = Path("docs/listings.json")
    data = json.loads(path.read_text())
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(data)} listings", flush=True)

    listings: list[Listing] = []
    by_id: dict[int, dict] = {}
    for d in data:
        li = _hydrate(d)
        if li:
            listings.append(li)
            by_id[id(li)] = d  # map back to the source dict to update in place

    cap = int(os.environ.get("VISION_MAX_LISTINGS", "800"))
    print(f"[{time.strftime('%H:%M:%S')}] running {os.environ.get('VISION_PROVIDER','?')} "
          f"vision (cap {cap}) across {len(listings)} hydrated listings…", flush=True)
    t0 = time.time()
    await enrich_with_vision(listings, max_listings=cap)
    print(f"[{time.strftime('%H:%M:%S')}] vision done in {int(time.time()-t0)}s", flush=True)

    # Recompute calc + grade (condition_tier may have changed) and write the
    # updated vision/condition/calc/grade back onto the source dicts.
    scored = 0
    for li in listings:
        d = by_id[id(li)]
        try:
            c = valuation_calc.compute(li)
            g = valuation_grading.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = valuation_calc.to_dict(c)
            li.raw["grade"] = valuation_grading.to_dict(g)
        except Exception:
            pass
        # Re-slim + copy the refreshed listing back into the source dict.
        fresh = _to_dict(li)
        d["raw"] = fresh["raw"]
        if (li.raw or {}).get("vision"):
            scored += 1

    path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[{time.strftime('%H:%M:%S')}] wrote {path} — {scored} now have Gemini vision", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
