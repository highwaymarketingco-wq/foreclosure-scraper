#!/usr/bin/env python3
"""Full-depth multi-year re-scrape for one or more ITS Public tax-portal counties,
PATCHING existing board rows (not just appending new ones) with the fuller raw.

WHY THIS EXISTS. Round 50 gap-sweep: docs/gap_matrix still flags atty_tax_verified_confirmed
as sourced-not-built for Carteret (1,809 est_rows), Yadkin (1,272) and Person (787) NC --
all three ALREADY wired into nc_its_public_tax.py's own PORTALS dict (full_model=True), and
all three already named in that module's OWN docstring as starvation victims: Yadkin/Scotland
explicitly ("last counties in PORTALS... live-confirmed both portals answer fine"), Carteret
via the round-20 fix (land_nc_its_public_tax.py, commit history) that landed 2,418 NEW rows for
it. That fix is append-only (land_nc_its_public_tax.py's append_new_rows() skips any parcel
whose dedupe_key already matches a board row) -- it could only ever add previously-unseen
parcels, never deepen the raw history already sitting on a row matched before the fix. That is
the EXACT shape backfill_duplin_multiyear_tax.py's own docstring documents for Duplin ("2,902 of
3,519 Duplin rows carry raw['nc_its_public_tax'], but EVERY ONE sampled has exactly ONE bill
year on file -- a scraper RUN-DEPTH gap") and Granville before it -- not a missing source, a
shallow-first-fetch gap that only a PATCHING re-fetch fixes.

This script generalizes backfill_duplin_multiyear_tax.py (which is hardcoded to Duplin) by
lifting its county filter to a --county arg, and generalizes land_nc_its_public_tax.py's
--county-budget-s CLI shape (same env var, ITS_TAX_COUNTY_BUDGET_S) so a high-volume county
doesn't truncate mid-history the way Carteret's first single-county attempt did (documented in
land_nc_its_public_tax.py: "live-confirmed truncated=True at year 2022"). No new reader, no new
parser -- same NcItsPublicTax class, same classify-into-patch-or-append shape every backfill
this session uses (never load_board()/write_artifact() at this board's size).

    python scripts/backfill_its_public_multiyear_tax.py --county Carteret --county Yadkin --county Person --county-budget-s 1800 --dry-run
    python scripts/backfill_its_public_multiyear_tax.py --county Carteret --county Yadkin --county Person --county-budget-s 1800
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", action="append", required=True,
                     help="county name, repeatable (e.g. --county Carteret --county Yadkin)")
    ap.add_argument("--county-budget-s", type=float, default=None,
                     help="override ITS_TAX_COUNTY_BUDGET_S (default 420) for "
                          "high-volume counties that truncate at the default")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    os.environ["ITS_TAX_COUNTIES"] = ",".join(args.county)
    if args.county_budget_s:
        os.environ["ITS_TAX_COUNTY_BUDGET_S"] = str(args.county_budget_s)

    from foreclosure_scraper.board_stream import iter_board_rows
    from foreclosure_scraper.models import Listing
    from foreclosure_scraper.scrapers.counties_nc.nc_its_public_tax import NcItsPublicTax
    from foreclosure_scraper.web_artifact import (
        _APPEND_SIG_FIELDS, append_new_rows, board_lock, board_patch_size_state,
        patch_existing_rows,
    )

    targets = {c.strip().title() for c in args.county}

    def _is_target(rec_or_li) -> bool:
        county = str(rec_or_li.county if hasattr(rec_or_li, "county") else rec_or_li.get("county") or "")
        state = str(rec_or_li.state if hasattr(rec_or_li, "state") else rec_or_li.get("state") or "")
        return county.replace(" County", "").strip().title() in targets and state.upper() == "NC"

    print(f"ITS_TAX_COUNTIES scope: {os.environ['ITS_TAX_COUNTIES']}  "
          f"(county budget {os.environ.get('ITS_TAX_COUNTY_BUDGET_S', '420 default')}s)")

    async def _fetch_new():
        scraper = NcItsPublicTax()
        rows = list(await scraper.fetch())
        print(f"county_stats: {getattr(scraper, 'county_stats', {})}")
        return rows

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} parcel-level leads (full depth)")
    if not new_rows:
        print("nothing scraped -- aborting.")
        return 1

    multi_year = sum(1 for r in new_rows if isinstance(r.raw, dict) and r.raw.get("multi_year_delinquent_tax"))
    years_seen = sorted({y for r in new_rows if isinstance(r.raw, dict)
                         for y in (r.raw.get("nc_its_public_tax") or {}).get("years") or []})
    print(f"with multi_year_delinquent_tax (>=2 distinct unpaid years, >=1 matured): {multi_year:,}")
    print(f"distinct tax years covered this fetch: {years_seen}")

    docs_dir = REPO / "docs"
    existing_keys: dict[str, dict] = {}
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _is_target(rec):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        existing_keys[li.dedupe_key()] = rec
    print(f"\nexisting target-county dedupe_keys on board: {len(existing_keys):,}")

    patches: dict[str, dict] = {}
    appends: list[Listing] = []
    seen_this_run: set[str] = set()
    for li in new_rows:
        key = li.dedupe_key()
        if key in seen_this_run:
            continue
        seen_this_run.add(key)
        if key in existing_keys:
            patches[key] = {"raw": li.raw}
        else:
            appends.append(li)

    print(f"\nclassified {len(new_rows):,} fresh leads:")
    print(f"  merge into an EXISTING board row (patch): {len(patches):,}")
    print(f"  genuinely NEW board rows (append):        {len(appends):,}")
    patch_multi_year = sum(1 for p in patches.values() if p["raw"].get("multi_year_delinquent_tax"))
    append_multi_year = sum(1 for li in appends if isinstance(li.raw, dict) and li.raw.get("multi_year_delinquent_tax"))
    print(f"\n  of the patches, multi_year_delinquent_tax qualifies: {patch_multi_year:,}")
    print(f"  of the appends, multi_year_delinquent_tax qualifies: {append_multi_year:,}")

    by_county: dict[str, dict] = {}
    for key, p in patches.items():
        c = (existing_keys[key].get("county") or "?")
        by_county.setdefault(c, {"patch": 0, "patch_my": 0})
        by_county[c]["patch"] += 1
        if p["raw"].get("multi_year_delinquent_tax"):
            by_county[c]["patch_my"] += 1
    for li in appends:
        c = li.county or "?"
        by_county.setdefault(c, {"patch": 0, "patch_my": 0, "append": 0, "append_my": 0})
        by_county[c].setdefault("append", 0)
        by_county[c].setdefault("append_my", 0)
        by_county[c]["append"] += 1
        if isinstance(li.raw, dict) and li.raw.get("multi_year_delinquent_tax"):
            by_county[c]["append_my"] += 1
    print("\nper-county breakdown:")
    for c, stats in sorted(by_county.items()):
        print(f"  {c}: {stats}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    if not args.allow_large:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"]:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
    else:
        os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
        os.environ["BOARD_APPEND_ALLOW_LARGE"] = "1"

    with board_lock(REPO, owner="its_public_multiyear_tax_backfill", wait=600, poll=10):
        if patches:
            pstats = patch_existing_rows(patches, {"its_public_multiyear_tax_patch": len(patches)}, docs_dir=docs_dir)
            print("patch_existing_rows:", pstats)
        if appends:
            astats = append_new_rows(appends, {"its_public_multiyear_tax_append": len(appends)}, docs_dir=docs_dir)
            print("append_new_rows:", astats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
