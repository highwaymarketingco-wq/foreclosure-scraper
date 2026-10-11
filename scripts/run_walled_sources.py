"""Run ALL 37 Type-A walled sources standalone, output to data/walled_output/.

Design principles (learned from 3 failed runs):
  1. NO outer asyncio.wait_for — let safe_run() use its own internal timeout.
     safe_run already has partial-salvage logic; wrapping it in a second
     timeout kills the salvage before it can fire.
  2. Override timeout_s to 300s at the instance level — this becomes the
     internal safe_run timeout, so partial salvage works.
  3. Write each scraper's output IMMEDIATELY after it finishes — not after
     the whole wall completes. A killed process doesn't lose completed work.
  4. One JSON file per scraper slug, plus a _summary.json at the end.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("PYTHONPATH", "src")
# Enable curl_cffi WAF token solver for Tyler portal (estates scraper).
os.environ.setdefault("TYLER_USE_WAF_SOLVER", "1")

# Load .env manually (no python-dotenv installed)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from foreclosure_scraper.scrapers._registry import discover
from foreclosure_scraper.base_scraper import (
    OUTCOME_OK, OUTCOME_ZERO, OUTCOME_TIMEOUT,
    OUTCOME_BLOCKED, OUTCOME_ERROR, OUTCOME_PARTIAL,
)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "walled_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Hard cap per scraper: 5 minutes. safe_run's internal timeout fires here,
# triggering partial salvage for scrapers that use self.partial.
PER_SCRAPER_TIMEOUT = 300.0

# Some scrapers legitimately need more time (board pass + login + incremental
# scrape). Give them a longer budget so safe_run doesn't kill them mid-work.
SPECIAL_TIMEOUTS = {
    # liensnc: board pass (~30s) + login (~10s) + incremental scrape
    "counties_generic.liensnc": 900.0,
}

# The 37 Type-A walled source IDs from docs/walls_register.json
# and the scraper slugs that map to them.
WALLED_SOURCE_MAP = {
    # NC eCourts (captcha) — enrichment_waf_oss wired
    "nc_sp": ["counties_nc.nc_ecourts_divorce", "counties_nc.nc_ecourts_lis_pendens"],
    "nc_est": ["counties_nc.nc_ecourts_estates"],
    "nc_verify": ["counties_nc.nc_ecourts_estates"],
    "nc_notice_body": ["public_notices.ncnotices", "public_notices.nc_notices_counties"],

    # NC SOS (Cloudflare)
    "nc_sos_liens": ["national.nc_sos_ucc"],

    # SC sources
    "sc_probate_net": ["counties_sc.sc_probate_net"],
    "sc_sos": ["national.sc_sos_entity"],
    "sc_notice_body": ["counties_sc.sc_public_notices", "counties_sc.sc_probate_notices"],
    "sc_publicindex": ["national.sc_public_index", "counties_sc.sc_public_index", "counties_sc.sc_public_index_lis_pendens"],

    # People search / obits
    "obits": ["public_notices.echovita_obituaries", "public_notices.obituary_feeds", "public_notices.gannett_obituaries", "public_notices.funeral_home_rss"],

    # PropWire (DataDome + login)
    "propwire": ["national.propwire"],

    # NC ROD/tax
    "polk_tax": ["counties_nc.polk_tax"],

    # SC site scrapers
    "spartanburg_site": ["counties_sc.spartanburg_city_condemned", "counties_sc.spartanburg_condemned", "counties_sc.spartanburg_vacant", "counties_sc.spartanburg_master_in_equity"],
    "york_site": ["counties_sc.york_delinquent_tax", "counties_sc.york_overage_claims", "counties_sc.york_tax_sale_parcels"],
    "anderson_probate": ["counties_sc.anderson_acpass_deeds"],
    "nc_county_lists": ["national.sheriff_sales"],
    "richland_taxsale": ["counties_sc.richland_flc"],
    "avenu": ["counties_sc.cherokee_rod"],

    # SC lien registries (spa_key_extractor wired)
    "sc_lien_registries": ["counties_sc.sc_dew_lien_registry"],

    # LiensNC
    "liensnc_login": ["counties_generic.liensnc"],

    # New scrapers built 2026-10-11
    "sc_qpublic": ["counties_sc.sc_qpublic"],
    "people_search": ["national.people_search"],
    "unclaimed": ["national.nc_unclaimed"],
    "gaston_rod": ["counties_nc.nc_cchs_deeds"],
    "avalon_tax": ["counties_nc.nc_avalon_tax"],
    "nc_rod_captcha": ["counties_nc.nc_rod_captcha"],
    "nc_cchs_cf": ["counties_nc.nc_cchs_deeds"],
    "nc_tax_walled": ["counties_nc.nc_avalon_tax"],
    "sc_tax_walled": ["counties_sc.sc_tax_walled"],
    "dc_ip_block": ["counties_nc.dc_ip_block"],
    "lexington_probate": ["counties_sc.lexington_probate"],
    "sc_rod_walled": ["counties_sc.sc_rod_walled"],
    "morganton": ["counties_nc.morganton_nc"],
    "city_union": ["counties_sc.city_of_union"],
    "lawyer_owner_pulls": [],
    "nc_rowan_cott": ["counties_nc.nc_rowan_cott"],
    "nc_tylertech_estates": ["counties_nc.nc_tylertech_estates"],
    "nc_forsyth_vital": [],  # TRUE WALL: login required — manual lane only
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _listing_to_dict(li) -> dict:
    """Convert a Listing object to a JSON-serializable dict.

    Serializes the full Pydantic model so field names can never drift from
    the Listing definition.  The wire_walled_to_board.py script reads these
    dicts back into Listing objects; if a field is missing here it is None
    there, which means dedupe_key() falls back to url:walled://<source> and
    every row from one source collapses to a single board entry.
    """
    # Pydantic v2: model_dump() gives every field.
    if hasattr(li, "model_dump"):
        d = li.model_dump(mode="json")
        # Drop empty raw to save space, but keep the keys for debugging.
        raw = d.pop("raw", None)
        if raw:
            d["raw_keys"] = list(raw.keys())
            d["raw"] = raw  # keep for wire_walled_to_board
        return d
    # Fallback for non-Pydantic objects (shouldn't happen in this codebase).
    fields = [
        "source", "source_url", "listing_type", "property_kind",
        "street_address", "city", "state", "zip_code", "county",
        "parcel_id", "legal_description", "latitude", "longitude",
        "sale_date", "sale_time", "sale_location", "opening_bid",
        "judgment_amount", "upset_bid_deadline", "auction_status",
        "redemption_deadline", "foreclosure_process",
        "plaintiff", "defendant", "trustee", "case_number",
        "zoning", "acreage", "lot_size_sqft", "living_sqft",
        "living_sqft_estimated", "bedrooms", "bathrooms", "year_built",
        "assessed_value", "market_value", "tax_value",
        "owner_name", "land_use", "description",
        "first_seen", "last_seen",
    ]
    d = {}
    for f in fields:
        v = getattr(li, f, None)
        if v is not None:
            d[f] = v
    raw = getattr(li, "raw", None)
    if raw:
        d["raw_keys"] = list(raw.keys())
        d["raw"] = raw
    return d


async def run_one_scraper(scraper_cls) -> dict:
    """Run a single scraper via safe_run(). No outer timeout — safe_run
    handles its own timeout + partial salvage internally."""
    slug = getattr(scraper_cls, "slug", "unknown")
    name = getattr(scraper_cls, "name", slug)
    was_disabled = getattr(scraper_cls, "disabled", False)

    # Force-enable and cap timeout
    instance = scraper_cls()
    instance.disabled = False
    instance.disabled_reason = ""
    # Override timeout so safe_run's internal asyncio.wait_for fires here,
    # not the runner's outer one. This lets partial salvage work.
    instance.timeout_s = SPECIAL_TIMEOUTS.get(slug, PER_SCRAPER_TIMEOUT)

    t0 = time.monotonic()
    result = {
        "slug": slug,
        "name": name,
        "was_disabled": was_disabled,
        "timeout_s": instance.timeout_s,
        "rows": 0,
        "outcome": "",
        "reason": "",
        "elapsed_s": 0.0,
        "error": "",
        "sample": [],
        "timestamp": _now_iso(),
    }

    try:
        # NO outer asyncio.wait_for — safe_run() handles timeout internally
        listings = await instance.safe_run()
        elapsed = time.monotonic() - t0
        result["rows"] = len(listings)
        result["outcome"] = instance.last_outcome
        result["reason"] = instance.last_reason
        result["elapsed_s"] = round(elapsed, 1)

        if listings:
            result["sample"] = [_listing_to_dict(li) for li in listings[:10]]
            # Save ALL listings (not just sample) to a separate file
            all_data_file = OUTPUT_DIR / f"{slug}_data.json"
            with open(all_data_file, "w") as f:
                json.dump(
                    {"slug": slug, "timestamp": _now_iso(), "count": len(listings),
                     "listings": [_listing_to_dict(li) for li in listings]},
                    f, indent=2, default=str,
                )

    except Exception as e:
        result["outcome"] = OUTCOME_ERROR
        result["error"] = f"{type(e).__name__}: {e}"
        result["elapsed_s"] = round(time.monotonic() - t0, 1)
        result["reason"] = traceback.format_exc()[-500:]

    # Write this scraper's result IMMEDIATELY — don't wait for the wall
    result_file = OUTPUT_DIR / f"{slug}.json"
    with open(result_file, "w") as f:
        json.dump(result, f, indent=2, default=str)

    return result


async def main():
    print("=" * 70)
    print("WALLED SOURCES STANDALONE RUN (v3 — no double timeout)")
    print(f"Started: {_now_iso()}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Per-scraper timeout: {PER_SCRAPER_TIMEOUT}s (internal safe_run)")
    print("=" * 70)

    # Discover all scraper classes
    all_classes = discover()
    class_by_slug = {}
    for cls in all_classes:
        class_by_slug[getattr(cls, "slug", "")] = cls

    # Build the run plan
    run_plan = []
    no_scraper_count = 0
    scraper_count = 0

    for wall_id, slugs in WALLED_SOURCE_MAP.items():
        if not slugs:
            run_plan.append((wall_id, []))
            no_scraper_count += 1
        else:
            classes = []
            for slug in slugs:
                if slug in class_by_slug:
                    classes.append(class_by_slug[slug])
                else:
                    print(f"  WARNING: slug '{slug}' for wall '{wall_id}' not found in registry")
            run_plan.append((wall_id, classes))
            scraper_count += len(classes)

    print(f"\nWall sources: {len(WALLED_SOURCE_MAP)}")
    print(f"Sources with scraper code: {len(WALLED_SOURCE_MAP) - no_scraper_count}")
    print(f"Sources with NO scraper code: {no_scraper_count}")
    print(f"Total scraper instances to run: {scraper_count}")
    print(f"\nEach scraper's result is saved immediately to {OUTPUT_DIR}/<slug>.json")
    print()

    # Run each scraper sequentially
    all_results = []

    for wall_id, scraper_classes in run_plan:
        if not scraper_classes:
            print(f"  [{wall_id:25s}] NO SCRAPER CODE — skipped")
            all_results.append({
                "wall_id": wall_id,
                "scrapers": [],
                "total_rows": 0,
                "status": "NO_SCRAPER",
            })
            continue

        wall_results = []
        wall_total = 0
        for cls in scraper_classes:
            slug = getattr(cls, "slug", "?")
            print(f"  [{wall_id:25s}] running {slug}...", end=" ", flush=True)
            result = await run_one_scraper(cls)
            wall_results.append(result)
            wall_total += result["rows"]
            status = "OK" if result["rows"] > 0 else result["outcome"]
            print(f"{result['rows']:5d} rows ({status}, {result['elapsed_s']}s)")

        # Write wall summary
        out_file = OUTPUT_DIR / f"wall_{wall_id}.json"
        wall_data = {
            "wall_id": wall_id,
            "timestamp": _now_iso(),
            "scrapers": wall_results,
            "total_rows": wall_total,
        }
        with open(out_file, "w") as f:
            json.dump(wall_data, f, indent=2, default=str)

        all_results.append(wall_data)

    # Write final summary
    summary = {
        "run_timestamp": _now_iso(),
        "per_scraper_timeout_s": PER_SCRAPER_TIMEOUT,
        "total_wall_sources": len(WALLED_SOURCE_MAP),
        "sources_with_scrapers": len(WALLED_SOURCE_MAP) - no_scraper_count,
        "sources_without_scrapers": no_scraper_count,
        "total_scrapers_run": scraper_count,
        "total_rows_collected": sum(r["total_rows"] for r in all_results),
        "results": [],
    }

    data_count = zero_count = no_scraper_count2 = error_count = blocked_count = 0

    for r in all_results:
        if not r["scrapers"]:
            status = "NO_SCRAPER"
        elif r["total_rows"] > 0:
            status = "DATA"
        else:
            # Distinguish WHY a source produced zero rows.
            # BLOCKED: WAF/anti-bot (403/406/429). TIMEOUT: exceeded budget.
            # ERROR: code/parse exception. ZERO_RESULT: ran clean, genuinely empty.
            outcomes = [s["outcome"] for s in r["scrapers"]]
            if any(o == OUTCOME_BLOCKED for o in outcomes):
                status = "BLOCKED"
            elif any(o == OUTCOME_TIMEOUT for o in outcomes):
                status = "TIMEOUT"
            elif any(o == OUTCOME_ERROR for o in outcomes):
                status = "ERROR"
            elif any(o == OUTCOME_PARTIAL for o in outcomes):
                status = "PARTIAL"
            else:
                status = "ZERO"
        summary["results"].append({
            "wall_id": r["wall_id"],
            "total_rows": r["total_rows"],
            "status": status,
            "scraper_count": len(r["scrapers"]),
            "outcomes": [(s["slug"], s["outcome"], s["rows"]) for s in r["scrapers"]],
        })

        if status == "DATA":
            data_count += 1
        elif status == "ZERO":
            zero_count += 1
        elif status == "NO_SCRAPER":
            no_scraper_count2 += 1
        for s in r["scrapers"]:
            if s["outcome"] == OUTCOME_BLOCKED:
                blocked_count += 1
            elif s["outcome"] == OUTCOME_ERROR:
                error_count += 1

    summary_file = OUTPUT_DIR / "_summary.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    # Print final report
    print("\n" + "=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(f"Total wall sources: {summary['total_wall_sources']}")
    print(f"Sources with scraper code: {summary['sources_with_scrapers']}")
    print(f"Sources with NO scraper code: {summary['sources_without_scrapers']}")
    print(f"Total scrapers run: {summary['total_scrapers_run']}")
    print(f"Total rows collected: {summary['total_rows_collected']}")
    print()

    for r in summary["results"]:
        status = r["status"]
        rows = r["total_rows"]
        wid = r["wall_id"]
        if status == "DATA":
            print(f"  DATA     {wid:25s} {rows:6d} rows")
        elif status == "ZERO":
            outcomes = ", ".join(f"{s[0]}={s[1]}" for s in r["outcomes"])
            print(f"  ZERO     {wid:25s} {0:6d} rows ({outcomes})")
        elif status == "BLOCKED":
            outcomes = ", ".join(f"{s[0]}={s[1]}" for s in r["outcomes"])
            print(f"  BLOCKED  {wid:25s} {0:6d} rows ({outcomes})")
        elif status == "TIMEOUT":
            outcomes = ", ".join(f"{s[0]}={s[1]}" for s in r["outcomes"])
            print(f"  TIMEOUT  {wid:25s} {0:6d} rows ({outcomes})")
        elif status == "ERROR":
            outcomes = ", ".join(f"{s[0]}={s[1]}" for s in r["outcomes"])
            print(f"  ERROR    {wid:25s} {0:6d} rows ({outcomes})")
        elif status == "PARTIAL":
            outcomes = ", ".join(f"{s[0]}={s[1]}" for s in r["outcomes"])
            print(f"  PARTIAL  {wid:25s} {rows:6d} rows ({outcomes})")
        elif status == "NO_SCRAPER":
            print(f"  NOSCRAPER {wid:25s} — no code exists")

    print(f"\nSources with data: {data_count}")
    print(f"Sources with zero results: {zero_count}")
    print(f"Sources with no scraper: {no_scraper_count2}")
    print(f"Blocked outcomes: {blocked_count}")
    print(f"Error outcomes: {error_count}")
    print(f"\nOutput files in: {OUTPUT_DIR}")
    print(f"Summary: {summary_file}")


if __name__ == "__main__":
    asyncio.run(main())
