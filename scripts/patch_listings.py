"""Targeted post-run patch for docs/listings.json.

Runs ONLY the enrichments / corrections that the most-recent weekly
pipeline run left incomplete. Designed for the case where a long full
pipeline (~2 hours) finished but specific listings have stale or missing
data due to rate limits / credit outages / link-validator drops:

  * Re-run Vision on listings whose stored ``_n_photos`` < current photo
    count (the Marietta-style fix: with photos-first ordering, listings
    that previously saw 1-photo-only Vision now have 5-6 photo galleries
    and need re-Vision for an accurate condition tier).

  * Re-run validation gate (state↔county, parcel, comp, numeric bounds).

  * Re-run calc + grade + data_quality on touched listings only.

  * Re-write docs/listings.json + docs/run_health.json patch summary.

Cost: only Vision API calls (~$0.01-0.03 per re-Vision; typically <$10).
Runtime: 10-20 minutes vs. ~2 hours for a full pipeline.

Usage (locally):  uv run python scripts/patch_listings.py
Usage (CI):       triggered by .github/workflows/patch-listings.yml
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc as valuation_calc
from foreclosure_scraper.valuation import grading as valuation_grading
from foreclosure_scraper.validation import validate as validate_listings
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
from foreclosure_scraper.enrichment_judgment_amount import enrich_judgment_amount

log = structlog.get_logger()


LT_MAP = {lt.value: lt for lt in ListingType}
PK_MAP = {pk.value: pk for pk in PropertyKind}


def _hydrate_listing(d: dict) -> Listing | None:
    """Re-build a Listing from a docs/listings.json dict."""
    d = dict(d)
    for k in ("first_seen", "last_seen", "sale_date", "upset_bid_deadline"):
        v = d.get(k)
        if isinstance(v, str):
            try:
                d[k] = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                d[k] = None
    d["listing_type"] = LT_MAP.get(d.get("listing_type") or "unknown",
                                   ListingType.LIS_PENDENS)
    d["property_kind"] = PK_MAP.get(d.get("property_kind") or "unknown",
                                    PropertyKind.UNKNOWN)
    valid_fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    try:
        return Listing(**valid_fields)
    except Exception as exc:
        log.warning("patch.hydrate_failed", error=str(exc)[:200],
                    case=d.get("case_number"))
        return None


def _needs_revision(li: Listing) -> bool:
    """True if Vision should be re-run on this listing."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    images = raw.get("images") or {}
    real = images.get("real") or []
    n_real = len(real) if isinstance(real, list) else 0
    vision = raw.get("vision") or {}
    n_vision = vision.get("_n_photos") or 0
    if not vision.get("condition_tier"):
        return n_real >= 1  # never run vision; do it now
    return n_real > n_vision  # vision saw fewer photos than we now have


async def _revision_with_full_galleries(targets: list[Listing]) -> dict:
    """Re-run Vision on each target. Imported lazily so the module can be
    imported (and tested) even when ANTHROPIC_API_KEY isn't set."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("patch.vision_skipped_no_key")
        return {"queried": 0, "overrides": 0, "cost_estimate_usd": 0,
                "skipped_no_key": len(targets)}

    from foreclosure_scraper.enrichment_vision import enrich_with_vision

    log.info("patch.vision_start", target_count=len(targets))
    # The enrich_with_vision function has its own internal targeting that
    # picks listings without good vision data — we feed it just the targets
    # we already filtered for, so it processes them all.
    await enrich_with_vision(targets)
    # The enrichment writes stats internally; we summarize from the data.
    refreshed = sum(1 for li in targets
                    if (li.raw or {}).get("vision", {}).get("condition_tier"))
    return {"queried": len(targets), "overrides": refreshed}


async def main() -> int:
    # THE LOCK, held across read -> re-Vision -> write_artifact. This script
    # runs for 10-20 minutes and republishes the whole board; a concurrent board
    # writer silently reverts whichever of the two finishes first, with no error
    # anywhere. See web_artifact.board_lock.
    from foreclosure_scraper.web_artifact import BoardLockBusy, board_lock
    try:
        with board_lock(ROOT, owner="patch_listings.py"):
            return await _run()
    except BoardLockBusy as exc:
        log.error("patch.board_locked", detail=str(exc))
        return 1


async def _run() -> int:
    docs_dir = ROOT / "docs"
    listings_path = docs_dir / "listings.json"
    run_health_path = docs_dir / "run_health.json"

    # "exists" is the wrong question: the uncompressed twin is gitignored
    # (>100MB) and is absent on every fresh clone and every CI checkout, which
    # is exactly where this workflow runs. The committed .gz is the board there.
    from foreclosure_scraper.web_artifact import _board_file_present
    if not _board_file_present(listings_path):
        log.error("patch.no_listings_file", path=str(listings_path))
        return 1

    # read_board_records, NOT read_board_json. read_board_json reads only the
    # slim listings.json, and every heavy key lives in the index-aligned sidecar
    # listings_detail.json: comps (33,484 records), vision (13,088), CAMA
    # (12,952), rent comps (6,401), foreclosure sold comps (5,524). This script
    # then wrote the board back, so it published a board with all of that
    # stripped — and _needs_revision() saw an un-visioned board besides.
    from foreclosure_scraper.web_artifact import read_board_records, write_artifact
    raw_data = read_board_records(docs_dir)
    log.info("patch.loaded", listings=len(raw_data))

    # Hydrate
    listings: list[Listing] = []
    skipped = 0
    for d in raw_data:
        li = _hydrate_listing(d)
        if li is None:
            skipped += 1
            continue
        listings.append(li)
    log.info("patch.hydrated", live=len(listings), skipped=skipped)

    # Identify Vision targets
    vision_targets = [li for li in listings if _needs_revision(li)]
    log.info("patch.vision_targets", count=len(vision_targets))

    # Re-Vision
    vision_stats = {"queried": 0, "overrides": 0}
    if vision_targets:
        try:
            vision_stats = await _revision_with_full_galleries(vision_targets)
        except Exception:
            log.error("patch.vision_failed",
                      traceback=traceback.format_exc())

    # Re-run validation gate
    validation_stats = validate_listings(listings)

    # Re-run judgment_amount text-mining (cheap, idempotent)
    ja_stats = enrich_judgment_amount(listings)

    # Re-run calc + grade on every listing — these are pure functions, fast.
    valuation_failures = 0
    for li in listings:
        try:
            c = valuation_calc.compute(li)
            g = valuation_grading.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = valuation_calc.to_dict(c)
            li.raw["grade"] = valuation_grading.to_dict(g)
        except Exception:
            valuation_failures += 1

    log.info("patch.valuation_recomputed",
             count=len(listings) - valuation_failures,
             failures=valuation_failures)

    # Re-run data-quality flags LAST — after validation so they reflect any
    # nulls it wrote, and after the calc/grade loop above because every ARV
    # caveat this writes (arv_unreliable / arv_bid_and_roi_withheld /
    # arv_no_independent_check / arv_sanity_flag / arv_outlier) is read out of
    # raw['calc']. This call used to sit above the loop, so this script wrote
    # docs/listings.json with the fresh valuation and the PREVIOUS run's
    # caveats — a warning that describes a number that is no longer on the
    # board. tests/test_enrichment_order.py fails if it moves back.
    dq_stats = enrich_data_quality(listings)

    # Write back THROUGH write_artifact, not by hand.
    #
    # `listings_path.write_text(json.dumps(...))` wrote one file out of six. It
    # did not regenerate listings.json.gz (the file the dashboard actually
    # fetches), listings_detail.json / .gz, listings_slim.json.gz,
    # docs/detail_shards/ or run_meta.json — and docs/listings.json is
    # gitignored, so on the CI runner this workflow publishes from, the entire
    # output of the patch was a file git would never commit. The workflow then
    # pushed run_health.json alone: a health report describing a board it did
    # not ship. write_artifact emits all six from one payload, which is also the
    # only way the index-aligned join across them stays true.
    write_artifact(listings, {"notes": f"patch_listings: {len(listings)} listings "
                                       f"revalidated, {vision_stats.get('overrides', 0)} "
                                       f"vision overrides"},
                   docs_dir=docs_dir)
    out_data = listings
    log.info("patch.wrote_listings", path=str(listings_path), count=len(out_data))

    # Update / merge run_health.json with patch metadata
    health = {}
    if run_health_path.exists():
        try:
            health = json.loads(run_health_path.read_text())
        except (ValueError, json.JSONDecodeError):
            health = {}
    health.setdefault("patches", []).append({
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "vision": vision_stats,
        "validation": validation_stats,
        "data_quality": dq_stats,
        "judgment_amount": ja_stats,
        "valuation_failures": valuation_failures,
        "total_listings_after_patch": len(out_data),
    })
    run_health_path.write_text(json.dumps(health, indent=2, default=str))
    log.info("patch.done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
