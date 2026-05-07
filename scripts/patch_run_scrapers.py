"""Targeted re-run of specific scrapers + address-filling enrichments,
merge into docs/listings.json.

Use when ONE OR MORE specific scrapers were silently dropping listings
due to a code bug (e.g. NC eCourts dropping all 571 because sale_date
was historic ordered_date that failed _active_only's future horizon),
the bug is fixed, and you want the missing listings backfilled NOW
without paying 60-90 min for a full weekly run.

Pipeline (mirrors main.run() for the address-filling stages, drops
paid/slow non-essential enrichments — Vision / RentCast / HomeHarvest
photos+comps / Scrapling-rendered detail pages — which the next
weekly run will fill in):

  1. Load + hydrate existing docs/listings.json
  2. Run only the requested scraper slugs
  3. Filter chain: _in_scope -> _active_only -> _flip_candidate
  4. Address + property enrichments (in the order main.py runs them):
       - enrich_arcgis             county GIS by parcel/address
       - enrich_with_court_records NC eCourts + SC PI plaintiff/trustee
       - enrich_geocode            Nominatim lat/lng
       - valuation_location        Census ACS
       - rod.enrich_all            ROD recorded docs
       - enrich_addresses_from_owner   address backfill by owner-name
       - enrich_bankruptcy_property    BK debtor address lookup
       - enrich_with_parcel_lookup     PIN/parcel lookup
       - enrich_with_aggressive_address  cross-county owner search (capped)
       - enrich_lis_pendens_addresses  SC GIS resolver
       - enrich_parcel_reverse_geo     centroid reverse-geo
       - enrich_with_address_synthesis final synth fallback
       - enrich_property_kind          cheap backfill
       - enrich_judgment_amount        text-mining (free)
       - validate_listings             county/parcel/numeric gate
       - enrich_data_quality           investor flags
       - calc + grade per listing
  5. Merge into existing via dedupe_key + Listing.merge() (existing
     wins on non-null, new fills gaps), then re-dedupe across ALL
     for fuzzy address overlaps
  6. Write back docs/listings.json + append "rerun_scrapers" patch
     entry to docs/run_health.json

Patch output is NOT an island — the next weekly run re-scrapes
everything fresh and replaces docs/listings.json from scratch.
Carryover module preserves the patched listings if a source
regresses to zero post-patch.

Usage (locally):
    uv run python scripts/patch_run_scrapers.py counties_nc.nc_ecourts_lis_pendens
    uv run python scripts/patch_run_scrapers.py --all-fixed
    uv run python scripts/patch_run_scrapers.py --all-fixed --dry-run

Usage (CI):
    triggered by .github/workflows/patch-run-scrapers.yml
"""
from __future__ import annotations

import argparse
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

from foreclosure_scraper.config import RuntimeConfig
from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.enrichment_arcgis import enrich as enrich_gis
from foreclosure_scraper.enrichment_courts import enrich_with_court_records
from foreclosure_scraper.enrichment_geocode import enrich as enrich_geocode
from foreclosure_scraper.flags import compute_flags
from foreclosure_scraper.main import (
    _active_only,
    _flip_candidate,
    _in_scope,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers._registry import all_scrapers
from foreclosure_scraper.valuation import calc as valuation_calc
from foreclosure_scraper.valuation import grading as valuation_grading
from foreclosure_scraper.valuation import location as valuation_location
from foreclosure_scraper.validation import validate as validate_listings
from foreclosure_scraper.enrichment_county_pin import enforce_case_pinned_county
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality
from foreclosure_scraper.enrichment_judgment_amount import enrich_judgment_amount
from foreclosure_scraper.enrichment_property_kind import enrich_property_kind
from foreclosure_scraper.enrichment_upset_bid import enrich_upset_bid

log = structlog.get_logger()


# Default target list when --all-fixed is passed. As bugs get fixed, this
# list shrinks; as new ones are discovered, add them here. Comments tag
# the commit that landed the fix.
KNOWN_FIXED = (
    "counties_nc.nc_ecourts_lis_pendens",   # 1bf92a9: sale_date=None fix
    # Tax-foreclosure scrapers paired with the paragraph-fallback parser
    # in 3ee745c. Only the ones whose counties are still in scope after
    # the 2026-05-07 eastern-NC scope rollback are listed here — Wake /
    # Forsyth / Guilford / Durham tax pages are scraped pointlessly if
    # their listings will fail _in_scope.
    "counties_nc.new_hanover_tax",          # 3ee745c
    "counties_nc.buncombe_tax",             # 3ee745c
    "counties_nc.cleveland_tax",            # 3ee745c
    "counties_nc.henderson_tax",            # 3ee745c
    "counties_nc.polk_tax",                 # 3ee745c
    "counties_nc.rutherford_tax",           # 3ee745c
    "counties_nc.brunswick_tax",            # 11e00d4: Brunswick scraper added
    # Sold-comp sources — added 2026-05-07
    "counties_sc.spartanburg_master_in_equity",  # 92752da: sold-price extraction
    "counties_sc.anderson_master_in_equity",     # 92752da
    "counties_sc.pickens_master_in_equity",      # 92752da
    "counties_nc.nc_rod_substitute_trustee",     # 7d3f1c1: Trustee's Deed Upon Sale post-sale sweep
    # SC Public Index lis pendens — Scrapling-only, captures lis pendens
    # for SC counties with active filings each week
    "counties_sc.sc_public_index_lis_pendens",
    "counties_sc.sc_courtrosters",
)


LT_MAP = {lt.value: lt for lt in ListingType}
PK_MAP = {pk.value: pk for pk in PropertyKind}


def _hydrate_listing(d: dict) -> Listing | None:
    """Re-build a Listing from a docs/listings.json dict.

    Handles JSON-mode serialization (ISO datetime strings, enum values,
    slim raw payload). Returns None on hydration failure (logged); a
    handful of bad rows shouldn't tank the whole patch.
    """
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
    except Exception as exc:  # noqa: BLE001
        log.warning("patch_run.hydrate_failed", error=str(exc)[:200],
                    case=d.get("case_number"))
        return None


def _select_scrapers(slugs: set[str]):
    """Resolve slugs to scraper instances. Returns (scrapers, not_found)."""
    out = [s for s in all_scrapers() if s.slug in slugs]
    found = {s.slug for s in out}
    not_found = sorted(slugs - found)
    return out, not_found


async def _run_scrapers(scrapers, parallel: int):
    """Execute the listed scrapers concurrently, return [(slug, listings)]."""
    sem = asyncio.Semaphore(parallel)

    async def bounded(s):
        async with sem:
            return s.slug, await s.safe_run()

    return await asyncio.gather(*(bounded(s) for s in scrapers))


def _filter_pipeline(listings: list[Listing], cfg: RuntimeConfig) -> list[Listing]:
    """Apply the same filter chain main.run() does, in the same order.
    These filters are why the bug existed — _active_only with a historic
    sale_date dropped 571 NC eCourts listings every run."""
    in_area = [li for li in listings if _in_scope(li)]
    active = [li for li in in_area if _active_only(li, cfg.sale_horizon_days)]
    flip = [li for li in active if _flip_candidate(li)]
    return flip


async def _run_address_enrichments(new_listings: list[Listing]) -> dict:
    """Run the chain of address-finding + value-cheap enrichments on the
    new listings only (existing listings already had this last week).

    Each step wrapped in try/except so one failure doesn't kill the rest.
    Order matches main.py for parity. Returns {step: stat_or_status}.
    """
    stats: dict = {}

    # County GIS (free, parcel/address lookup)
    try:
        await enrich_gis(new_listings)
        stats["enrich_gis"] = "ok"
    except Exception:
        log.error("patch_run.gis_failed", traceback=traceback.format_exc())
        stats["enrich_gis"] = "failed"

    # Court records (NC eCourts + SC Public Index for plaintiff/trustee)
    try:
        await enrich_with_court_records(new_listings)
        stats["enrich_courts"] = "ok"
    except Exception:
        log.error("patch_run.courts_failed", traceback=traceback.format_exc())
        stats["enrich_courts"] = "failed"

    # Local computed flags (absentee_owner, vacant, high_equity, etc.)
    try:
        compute_flags(new_listings)
        stats["compute_flags"] = "ok"
    except Exception:
        log.error("patch_run.flags_failed", traceback=traceback.format_exc())
        stats["compute_flags"] = "failed"

    # Geocoding (Nominatim — free but rate-limited)
    try:
        await enrich_geocode(new_listings)
        stats["geocode"] = "ok"
    except Exception:
        log.error("patch_run.geocode_failed", traceback=traceback.format_exc())
        stats["geocode"] = "failed"

    # Census ACS by ZIP (location grade signal)
    try:
        await valuation_location.enrich(new_listings)
        stats["location"] = "ok"
    except Exception:
        log.error("patch_run.location_failed", traceback=traceback.format_exc())
        stats["location"] = "failed"

    # Per-county Register of Deeds
    try:
        from foreclosure_scraper.rod import enrich as rod_enrich
        await rod_enrich.enrich_all(new_listings)
        stats["rod"] = "ok"
    except Exception:
        log.error("patch_run.rod_failed", traceback=traceback.format_exc())
        stats["rod"] = "failed"

    # PRIMARY ADDRESS FILLERS — run in main.py order
    try:
        from foreclosure_scraper.enrichment_address_backfill import (
            enrich_addresses_from_owner,
        )
        await enrich_addresses_from_owner(new_listings)
        stats["address_backfill"] = "ok"
    except Exception:
        log.error("patch_run.addr_backfill_failed",
                  traceback=traceback.format_exc())
        stats["address_backfill"] = "failed"

    try:
        from foreclosure_scraper.enrichment_bankruptcy_property import (
            enrich_bankruptcy_property,
        )
        await enrich_bankruptcy_property(new_listings)
        stats["bk_property"] = "ok"
    except Exception:
        log.error("patch_run.bk_property_failed",
                  traceback=traceback.format_exc())
        stats["bk_property"] = "failed"

    try:
        from foreclosure_scraper.enrichment_parcel_lookup import (
            enrich_with_parcel_lookup,
        )
        await enrich_with_parcel_lookup(new_listings)
        stats["parcel_lookup"] = "ok"
    except Exception:
        log.error("patch_run.parcel_lookup_failed",
                  traceback=traceback.format_exc())
        stats["parcel_lookup"] = "failed"

    try:
        from foreclosure_scraper.enrichment_aggressive_address import (
            enrich_with_aggressive_address,
        )
        await enrich_with_aggressive_address(new_listings)
        stats["aggressive_address"] = "ok"
    except Exception:
        log.error("patch_run.aggressive_failed",
                  traceback=traceback.format_exc())
        stats["aggressive_address"] = "failed"

    try:
        from foreclosure_scraper.enrichment_lis_pendens_resolver import (
            enrich_lis_pendens_addresses,
        )
        s = await enrich_lis_pendens_addresses(new_listings)
        stats["lis_pendens_resolver"] = s or "ok"
    except Exception:
        log.error("patch_run.lp_resolver_failed",
                  traceback=traceback.format_exc())
        stats["lis_pendens_resolver"] = "failed"

    try:
        from foreclosure_scraper.enrichment_parcel_reverse_geo import (
            enrich_parcel_reverse_geo,
        )
        s = await enrich_parcel_reverse_geo(new_listings)
        stats["parcel_reverse_geo"] = s or "ok"
    except Exception:
        log.error("patch_run.parcel_reverse_geo_failed",
                  traceback=traceback.format_exc())
        stats["parcel_reverse_geo"] = "failed"

    try:
        from foreclosure_scraper.enrichment_address_final import (
            enrich_with_address_synthesis,
        )
        enrich_with_address_synthesis(new_listings)
        stats["address_synth"] = "ok"
    except Exception:
        log.error("patch_run.addr_synth_failed",
                  traceback=traceback.format_exc())
        stats["address_synth"] = "failed"

    # Enforce case-pinned county on the new listings AFTER all address
    # enrichments. Catches the cross-county GIS-overwrite bug where
    # earlier enrichments mistagged county based on a same-name match
    # in a different county. Pure-Python.
    try:
        s = enforce_case_pinned_county(new_listings)
        stats["county_pin"] = s
    except Exception:
        log.error("patch_run.county_pin_failed",
                  traceback=traceback.format_exc())
        stats["county_pin"] = "failed"

    # Property kind backfill (must precede validation/calc which read
    # property_kind for kind-specific logic)
    try:
        enrich_property_kind(new_listings)
        stats["property_kind"] = "ok"
    except Exception:
        log.error("patch_run.property_kind_failed",
                  traceback=traceback.format_exc())
        stats["property_kind"] = "failed"

    # Judgment amount text-mining (free, fast)
    try:
        s = enrich_judgment_amount(new_listings)
        stats["judgment_amount"] = s
    except Exception:
        log.error("patch_run.judgment_amount_failed",
                  traceback=traceback.format_exc())
        stats["judgment_amount"] = "failed"

    # Pre-write validation gate
    try:
        s = validate_listings(new_listings)
        stats["validation"] = s
    except Exception:
        log.error("patch_run.validate_failed",
                  traceback=traceback.format_exc())
        stats["validation"] = "failed"

    # Investor-facing data-quality flags (post-validation so they reflect nulls)
    try:
        s = enrich_data_quality(new_listings)
        stats["data_quality"] = s
    except Exception:
        log.error("patch_run.data_quality_failed",
                  traceback=traceback.format_exc())
        stats["data_quality"] = "failed"

    # NC upset-bid window tagging (NCGS §45-21.27, ~14 days from sale).
    # Pure-Python, idempotent. Reads sale_date set by the law-firm /
    # county-tax / auction-site scrapers; tags raw.upset_bid + sets
    # upset_bid_deadline for any NC listing 0-14 days post-sale.
    try:
        s = enrich_upset_bid(new_listings)
        stats["upset_bid"] = s
    except Exception:
        log.error("patch_run.upset_bid_failed",
                  traceback=traceback.format_exc())
        stats["upset_bid"] = "failed"

    return stats


def _calc_and_grade(listings: list[Listing]) -> int:
    """Calc + grade per listing with try/except isolation. Returns failure
    count."""
    failures = 0
    for li in listings:
        try:
            c = valuation_calc.compute(li)
            g = valuation_grading.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = valuation_calc.to_dict(c)
            li.raw["grade"] = valuation_grading.to_dict(g)
        except Exception:
            failures += 1
    return failures


def _merge_into_existing(
    existing: list[Listing], new: list[Listing],
) -> tuple[list[Listing], dict[str, int]]:
    """Dedupe-merge new listings into the existing set.

    Listing.merge() preserves the BASE's non-null fields and fills its
    nulls from the other. Existing data is treated as authoritative;
    new scrape only fills gaps. Listings whose dedupe_key doesn't match
    anything existing are added as-is.
    """
    by_key: dict[str, Listing] = {li.dedupe_key(): li for li in existing}
    added = merged = 0
    for li in new:
        k = li.dedupe_key()
        if k in by_key:
            by_key[k] = by_key[k].merge(li)
            merged += 1
        else:
            by_key[k] = li
            added += 1
    return list(by_key.values()), {"added": added, "merged": merged}


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Targeted scraper re-run + merge into docs/listings.json",
    )
    parser.add_argument(
        "slugs", nargs="*",
        help="Scraper slugs to re-run (e.g. counties_nc.nc_ecourts_lis_pendens)",
    )
    parser.add_argument(
        "--all-fixed", action="store_true",
        help=f"Re-run all known-fixed scrapers ({len(KNOWN_FIXED)} sources)",
    )
    parser.add_argument(
        "--parallel", type=int, default=4,
        help="Max scrapers to run concurrently (default 4)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run scrapers + filters + enrichments, but don't write back",
    )
    args = parser.parse_args()

    if args.all_fixed:
        target_slugs = set(KNOWN_FIXED)
    elif args.slugs:
        target_slugs = set(args.slugs)
    else:
        parser.print_help()
        return 1

    listings_path = ROOT / "docs" / "listings.json"
    sold_pool_path = ROOT / "docs" / "foreclosure_sold_pool.json"
    run_health_path = ROOT / "docs" / "run_health.json"
    if not listings_path.exists():
        log.error("patch_run.no_listings_file", path=str(listings_path))
        return 1

    # Hydrate existing active listings
    raw_data = json.loads(listings_path.read_text())
    existing: list[Listing] = []
    skipped = 0
    for d in raw_data:
        li = _hydrate_listing(d)
        if li is None:
            skipped += 1
            continue
        existing.append(li)
    log.info("patch_run.loaded_existing",
             live=len(existing), skipped=skipped)

    # Hydrate existing sold pool (separate file). May not exist yet.
    existing_sold: list[Listing] = []
    if sold_pool_path.exists():
        try:
            sold_data = json.loads(sold_pool_path.read_text())
            for d in sold_data:
                li = _hydrate_listing(d)
                if li is not None:
                    existing_sold.append(li)
            log.info("patch_run.loaded_sold_pool", count=len(existing_sold))
        except (ValueError, json.JSONDecodeError):
            pass

    # Resolve scrapers
    scrapers, not_found = _select_scrapers(target_slugs)
    if not_found:
        log.warning("patch_run.unknown_slugs", slugs=not_found)
    if not scrapers:
        log.error("patch_run.no_scrapers_resolved")
        return 1
    log.info("patch_run.targets",
             slugs=[s.slug for s in scrapers], count=len(scrapers))

    # Run them
    results = await _run_scrapers(scrapers, args.parallel)
    new_raw: list[Listing] = []
    per_slug_raw: dict[str, int] = {}
    for slug, listings in results:
        per_slug_raw[slug] = len(listings)
        for li in listings:
            if not li.source:
                li.source = slug
            new_raw.append(li)
    log.info("patch_run.scraper_output",
             total=len(new_raw), by_slug=per_slug_raw)

    if not new_raw:
        log.warning("patch_run.zero_new_listings")
        return 0

    # Partition: sold pool vs active candidates (mirrors main.py orchestrator)
    from foreclosure_scraper.enrichment_foreclosure_sold_comps import (
        is_sold_pool_candidate, enrich_foreclosure_sold_comps,
    )
    new_sold_raw = [li for li in new_raw if is_sold_pool_candidate(li)]
    new_active_raw = [li for li in new_raw if not is_sold_pool_candidate(li)]
    log.info("patch_run.partitioned",
             new_active=len(new_active_raw), new_sold=len(new_sold_raw))

    # Filter chain on active (matches main.py)
    cfg = RuntimeConfig.from_env()
    new_filtered = _filter_pipeline(new_active_raw, cfg)
    # Sold pool only needs scope check (already past sales)
    new_sold = [li for li in new_sold_raw if _in_scope(li)]
    log.info("patch_run.after_filter",
             active_kept=len(new_filtered), sold_kept=len(new_sold))

    # Address enrichments on new active listings
    enrichment_stats = await _run_address_enrichments(new_filtered)

    # ---- Sold-pool mini-pipeline (mirrors main.py's sold pool branch) ----
    if new_sold:
        log.info("patch_run.sold_pool_enrich_start", count=len(new_sold))
        # Address backfill
        try:
            from foreclosure_scraper.enrichment_address_backfill import (
                enrich_addresses_from_owner,
            )
            await enrich_addresses_from_owner(new_sold)
        except Exception:
            log.error("patch_run.sold_addr_backfill_failed",
                      traceback=traceback.format_exc())
        # County GIS for sqft/beds/baths
        try:
            from foreclosure_scraper.enrichment_arcgis import enrich as _gis
            await _gis(new_sold)
        except Exception:
            log.error("patch_run.sold_gis_failed",
                      traceback=traceback.format_exc())
        # SC MIE addresses bake city into street_address; split out so
        # HomeHarvest's by-address lookup can fire.
        try:
            from foreclosure_scraper.main import _split_embedded_city
            _split_embedded_city(new_sold)
        except Exception:
            log.error("patch_run.sold_city_split_failed",
                      traceback=traceback.format_exc())
        # HomeHarvest photos
        try:
            from foreclosure_scraper.enrichment_photos import (
                enrich_with_address_photos,
            )
            await enrich_with_address_photos(new_sold)
        except Exception:
            log.error("patch_run.sold_photos_failed",
                      traceback=traceback.format_exc())
        # OSM map fallback
        try:
            from foreclosure_scraper.enrichment_images import enrich_with_images
            await enrich_with_images(new_sold, use_mapillary=False)
        except Exception:
            log.error("patch_run.sold_images_failed",
                      traceback=traceback.format_exc())
        # Vision condition assessment — separate budget so it can't eat
        # active-listing Vision spend on a parallel run.
        try:
            from foreclosure_scraper.enrichment_vision import (
                enrich_with_vision as _ev,
            )
            sold_vision_cap = int(os.environ.get(
                "SOLD_POOL_VISION_MAX_LISTINGS", "100"
            ))
            await _ev(new_sold, max_listings=sold_vision_cap)
        except Exception:
            log.error("patch_run.sold_vision_failed",
                      traceback=traceback.format_exc())
        # Validate / county_pin / property_kind
        try:
            validate_listings(new_sold)
            enforce_case_pinned_county(new_sold)
            enrich_property_kind(new_sold)
        except Exception:
            pass
        log.info("patch_run.sold_pool_enrich_done")

    # Calc + grade for new active
    valuation_failures = _calc_and_grade(new_filtered)
    log.info("patch_run.valuation",
             ok=len(new_filtered) - valuation_failures,
             failures=valuation_failures)

    # Merge new active into existing active (dedupe-merge), then dedupe
    merged_all, merge_stats = _merge_into_existing(existing, new_filtered)
    final_active = dedupe(merged_all)

    # Merge sold pools (existing + new)
    sold_merged, sold_merge_stats = _merge_into_existing(existing_sold, new_sold)
    final_sold = dedupe(sold_merged)

    log.info(
        "patch_run.merged",
        active_added=merge_stats["added"],
        active_merged=merge_stats["merged"],
        active_final=len(final_active),
        sold_added=sold_merge_stats["added"],
        sold_merged=sold_merge_stats["merged"],
        sold_final=len(final_sold),
        net_change=len(final_active) - len(existing),
    )

    # ---- NC eCourts case-status enrichment (Order Confirming Sale detection) ----
    # Runs on the FULL active set so existing listings can be promoted to
    # the sold pool when Tyler's docket shows their case is now confirmed
    # at sale.
    if os.environ.get("PATCH_NC_CASE_STATUS", "1") == "1":
        try:
            from foreclosure_scraper.enrichment_nc_case_status import (
                enrich_with_nc_case_status,
            )
            nc_cap = int(os.environ.get("PATCH_NC_CASE_STATUS_CAP", "50"))
            await enrich_with_nc_case_status(
                final_active, concurrency=2, max_check=nc_cap,
            )
        except Exception:
            log.error("patch_run.nc_case_status_failed",
                      traceback=traceback.format_exc())

    # Promote to sold pool: any active listing where case-status surfaced
    # raw.actual_sold_price + promoted_to_sold_comp moves to the sold pool.
    promoted = []
    kept_active = []
    for li in final_active:
        raw = li.raw if isinstance(li.raw, dict) else {}
        if (isinstance(raw.get("actual_sold_price"), (int, float))
                and raw.get("nc_case_status", {}).get("promoted_to_sold_comp")):
            promoted.append(li)
        else:
            kept_active.append(li)
    if promoted:
        log.info("patch_run.promoted_to_sold_pool", count=len(promoted))
        final_active = kept_active
        final_sold = final_sold + promoted

    # Run the comp matcher
    try:
        s = enrich_foreclosure_sold_comps(final_active, final_sold)
        log.info("patch_run.sold_comps_match", **s)
    except Exception:
        log.error("patch_run.sold_comps_match_failed",
                  traceback=traceback.format_exc())

    # Upset-bid tagging
    try:
        from foreclosure_scraper.enrichment_upset_bid import enrich_upset_bid
        ub_stats = enrich_upset_bid(final_active)
        log.info("patch_run.upset_bid_post_merge", **ub_stats)
    except Exception:
        log.error("patch_run.upset_bid_failed",
                  traceback=traceback.format_exc())

    if args.dry_run:
        log.info("patch_run.dry_run_done")
        return 0

    # Write back BOTH files
    listings_path.write_text(
        json.dumps([li.model_dump(mode="json") for li in final_active],
                   indent=2, default=str)
    )
    sold_pool_path.write_text(
        json.dumps([li.model_dump(mode="json") for li in final_sold],
                   indent=2, default=str)
    )
    log.info("patch_run.wrote",
             active=len(final_active), sold_pool=len(final_sold))

    # Patch entry in run_health
    health: dict = {}
    if run_health_path.exists():
        try:
            health = json.loads(run_health_path.read_text())
        except (ValueError, json.JSONDecodeError):
            health = {}
    health.setdefault("patches", []).append({
        "kind": "rerun_scrapers",
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "scraper_slugs": sorted(target_slugs),
        "raw_per_slug": per_slug_raw,
        "active_kept": len(new_filtered),
        "sold_pool_kept": len(new_sold),
        "promoted_to_sold_via_case_status": len(promoted),
        "active_added_new": merge_stats["added"],
        "active_merged_into_existing": merge_stats["merged"],
        "active_final": len(final_active),
        "sold_pool_final": len(final_sold),
        "valuation_failures": valuation_failures,
        "enrichment_stats": enrichment_stats,
    })
    run_health_path.write_text(json.dumps(health, indent=2, default=str))
    log.info("patch_run.done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
