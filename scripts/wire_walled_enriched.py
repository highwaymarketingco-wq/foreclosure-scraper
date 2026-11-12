#!/usr/bin/env python3
"""Wire walled_output data through the real enrichment pipeline, then to the board.

This replaces scripts/wire_walled_to_board.py for the full path:
  1. Load all *_data.json from data/walled_output/ → Listing objects
  2. Deduplicate within the walled set using row_keys()
  3. Run enrichment enrichers on the new Listings:
     a. enrich_resolve_name_to_property (name→parcel via GIS)
     b. apply_verification (attach ledger verdicts)
     c. tax_binding.scrub_unbound_tax (drop wrong-parcel tax debts)
     d. block_binding.scrub_unbound_blocks
     e. identity.run_identity_pass (merge twins, split fused rows)
     f. valuation_calc + valuation_grading (investor calc + A-F grade)
     g. compute_flags (absentee, high_equity, vacant, etc.)
     h. call_ready.stamp_board (lane, tier, reason)
     i. distress_score.score_board (HOT/WARM/COLD)
  4. Append to board via append_new_rows() (streaming, deduped)

Usage:
  BOARD_LOAD_ALLOW_LARGE=1 BOARD_LOCK_BYPASS=1 BOARD_APPEND_ALLOW_LARGE=1 \
    PYTHONPATH=src:.venv/lib/python3.12/site-packages \
    .venv/bin/python3.12 scripts/wire_walled_enriched.py

Environment:
  FORECLOSURE_NAME_RESOLVE=0  — skip name resolution (default: on)
  ENRICH_SKIP_NETWORK=1       — skip network enrichers, run only local ones
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Load .env
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.verification.core import row_keys
from foreclosure_scraper.web_artifact import append_new_rows

WALLED_DIR = ROOT / "data" / "walled_output"
DOCS_DIR = ROOT / "docs"


def _parse_listing_type(s: str) -> ListingType:
    if not s:
        return ListingType.UNKNOWN
    name = s.replace("ListingType.", "").strip()
    try:
        return ListingType(name)
    except ValueError:
        pass
    try:
        return ListingType[name]
    except KeyError:
        pass
    return ListingType.UNKNOWN


def _convert_walled_row(row: dict) -> Listing | None:
    """Convert a walled_output listing dict to a Listing object."""
    clean = {k: v for k, v in row.items() if k not in ("raw_keys",)}
    if "raw" not in clean:
        clean["raw"] = {}
    source = clean.get("source", "walled_unknown")
    clean.setdefault("source", source)
    if not clean.get("source_url"):
        clean["source_url"] = f"walled://{source}"

    lt = clean.get("listing_type")
    if isinstance(lt, str):
        clean["listing_type"] = _parse_listing_type(lt)
    elif lt is None:
        clean["listing_type"] = ListingType.UNKNOWN

    pk = clean.get("property_kind")
    if isinstance(pk, str):
        try:
            clean["property_kind"] = PropertyKind(pk)
        except (ValueError, KeyError):
            clean["property_kind"] = PropertyKind.UNKNOWN
    elif pk is None:
        clean["property_kind"] = PropertyKind.UNKNOWN

    for dt_field in ("sale_date", "upset_bid_deadline", "redemption_deadline",
                      "first_seen", "last_seen"):
        v = clean.get(dt_field)
        if isinstance(v, str) and v:
            try:
                clean[dt_field] = datetime.fromisoformat(v)
            except ValueError:
                clean[dt_field] = None
        elif v is None:
            if dt_field in ("first_seen", "last_seen"):
                clean[dt_field] = datetime.now(timezone.utc)
            else:
                clean[dt_field] = None

    try:
        li = Listing.model_validate(clean)
    except Exception:
        li = Listing(
            source=source,
            source_url=clean.get("source_url", f"walled://{source}"),
            listing_type=clean.get("listing_type", ListingType.UNKNOWN),
            property_kind=clean.get("property_kind", PropertyKind.UNKNOWN),
            street_address=clean.get("street_address"),
            city=clean.get("city"),
            state=clean.get("state"),
            zip_code=clean.get("zip_code"),
            county=clean.get("county"),
            parcel_id=clean.get("parcel_id"),
            case_number=clean.get("case_number"),
            owner_name=clean.get("owner_name"),
            plaintiff=clean.get("plaintiff"),
            defendant=clean.get("defendant"),
            raw=clean.get("raw", {}),
        )
    return li


def _load_walled_listings() -> list[Listing]:
    """Load all walled output, dedup within the set."""
    print(f"Loading walled output from {WALLED_DIR}...", flush=True)
    new_listings: list[Listing] = []
    new_keys: set[str] = set()
    skipped_dupes = 0
    skipped_invalid = 0

    for f in sorted(WALLED_DIR.glob("*_data.json")):
        with open(f) as fh:
            data = json.load(fh)
        slug = data.get("slug", f.stem)
        listings = data.get("listings", [])
        print(f"  {f.name}: {len(listings)} rows", flush=True)

        for row in listings:
            li = _convert_walled_row(row)
            if li is None:
                skipped_invalid += 1
                continue
            keys = row_keys(li)
            if any(k in new_keys for k in keys):
                skipped_dupes += 1
                continue
            new_listings.append(li)
            new_keys.update(keys)

    print(f"\n  New listings to add: {len(new_listings)}", flush=True)
    print(f"  Duplicates within walled set: {skipped_dupes}", flush=True)
    print(f"  Invalid (skipped): {skipped_invalid}", flush=True)
    return new_listings


async def _enrich_listings(enriched: list[Listing]) -> dict:
    """Run the enrichment tail on new listings (subset of run_enrich_tail)."""
    stats = {}
    skip_network = os.environ.get("ENRICH_SKIP_NETWORK", "0").strip() in ("1", "true", "yes")

    # 1. Name → Property resolver (NETWORK — hits county GIS)
    if not skip_network:
        try:
            from foreclosure_scraper.enrichment_resolve_name_to_property import enrich_resolve_name_to_property
            print("  [enrich] name→property resolver...", flush=True)
            t0 = time.time()
            s = await enrich_resolve_name_to_property(enriched)
            if s:
                stats["name_resolve"] = s
                print(f"    resolved={s.get('resolved', 0)}/{s.get('targets', 0)} ({time.time()-t0:.0f}s)", flush=True)
        except Exception as e:
            print(f"    ERROR: {e}", flush=True)

    # 2. Verification verdicts (LOCAL — reads ledger files)
    try:
        from foreclosure_scraper.verification.apply import apply_verification
        print("  [enrich] apply_verification...", flush=True)
        s = apply_verification(enriched)
        if s:
            stats["verification"] = s
            print(f"    {s}", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

    # 3. Tax binding scrub (LOCAL)
    try:
        from foreclosure_scraper.tax_binding import scrub_unbound_tax
        print("  [enrich] tax_binding scrub...", flush=True)
        s = scrub_unbound_tax(enriched)
        if s:
            stats["tax_scrub"] = s
            print(f"    {s}", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

    # 4. Block binding scrub (LOCAL)
    try:
        from foreclosure_scraper.block_binding import scrub_unbound_blocks
        print("  [enrich] block_binding scrub...", flush=True)
        s = scrub_unbound_blocks(enriched)
        if s:
            stats["block_scrub"] = s
            print(f"    {s}", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

    # 5. Identity pass (LOCAL — merge twins, split fused rows)
    try:
        from foreclosure_scraper.identity import run_identity_pass
        print("  [enrich] identity pass...", flush=True)
        s = run_identity_pass(enriched)
        if s:
            stats["identity"] = s
            print(f"    {s}", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

    # 6. Valuation calc + grade (LOCAL)
    try:
        from foreclosure_scraper.valuation import calc as valuation_calc
        from foreclosure_scraper.valuation import grading as valuation_grading
        print("  [enrich] valuation calc + grade...", flush=True)
        failures = 0
        for li in enriched:
            try:
                c = valuation_calc.compute(li)
                g = valuation_grading.grade(li, c)
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["calc"] = valuation_calc.to_dict(c)
                li.raw["grade"] = valuation_grading.to_dict(g)
            except Exception:
                failures += 1
        stats["valuation"] = {"count": len(enriched), "failures": failures}
        print(f"    graded {len(enriched)} ({failures} failures)", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

    # 7. Equity engine (LOCAL)
    try:
        from foreclosure_scraper.enrichment_equity import enrich_equity
        print("  [enrich] equity engine...", flush=True)
        s = enrich_equity(enriched)
        if s:
            stats["equity"] = s
            print(f"    {s}", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

    # 8. Compute flags (LOCAL)
    try:
        from foreclosure_scraper.flags import compute_flags
        print("  [enrich] compute_flags...", flush=True)
        compute_flags(enriched)
        stats["flags"] = {"count": len(enriched)}
        print(f"    flagged {len(enriched)}", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

    # 9. Title risk (LOCAL)
    try:
        from foreclosure_scraper.enrichment_title_risk import enrich_title_risk
        print("  [enrich] title_risk...", flush=True)
        s = enrich_title_risk(enriched)
        if s:
            stats["title_risk"] = s
            print(f"    {s}", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

    # 10. Call-ready gate (LOCAL)
    try:
        from foreclosure_scraper.call_ready import stamp_board as _call_ready_stamp
        print("  [enrich] call_ready gate...", flush=True)
        s = _call_ready_stamp(enriched)
        if s:
            stats["call_ready"] = s
            print(f"    {s}", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

    # 11. Distress score (LOCAL — HOT/WARM/COLD tiers)
    try:
        from foreclosure_scraper.distress_score import score_board
        print("  [enrich] distress_score (HOT/WARM/COLD)...", flush=True)
        s = score_board(enriched)
        if s:
            stats["distress_score"] = s
            print(f"    {s}", flush=True)
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)

    return stats


def main():
    print("=" * 60, flush=True)
    print("wire_walled_enriched.py — full enrichment pipeline for walled data", flush=True)
    print("=" * 60, flush=True)

    # 1. Load walled output
    new_listings = _load_walled_listings()
    if not new_listings:
        print("No new listings to add. Exiting.", flush=True)
        return

    # 2. Run enrichment
    print(f"\n--- Enrichment phase ({len(new_listings)} listings) ---", flush=True)
    enrich_stats = asyncio.run(_enrich_listings(new_listings))
    print(f"\nEnrichment stats: {json.dumps(enrich_stats, indent=2, default=str)}", flush=True)

    # 3. Append to board (streaming)
    print(f"\n--- Board append (streaming, deduped) ---", flush=True)
    summary = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "wire_walled_enriched.py",
        "new_from_walled": len(new_listings),
        "enrichment": enrich_stats,
    }
    try:
        result = append_new_rows(new_listings, summary, DOCS_DIR)
        print(f"  Result: {result}", flush=True)
        print(f"\nDone! Enriched and appended {len(new_listings)} listings to board.", flush=True)
    except Exception as exc:
        print(f"  ERROR: {exc}", flush=True)
        raise


if __name__ == "__main__":
    main()
