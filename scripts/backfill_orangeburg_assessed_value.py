#!/usr/bin/env python3
"""Orangeburg SC-scoped catch-up for qpaybill_delinquent_roll's own STAGED DETAIL PASS.

WHY THIS EXISTS. gap_matrix.py (2026-11-16 re-run) flagged Orangeburg SC's
`assessed_value` as a 'sourced-not-built' gap: 4,676 rows, 0% filled, source
"county GIS: gis2.orangeburgcounty.org". The SAME re-derive also flagged
`beds_baths`/`sqft` (2,303 rows each, source "tax/property card:
orangeburgtreasurer.qpaybill.com" -- the SAME qpaybill host this script uses).

Investigation (2026-11-16) found gis2.orangeburgcounty.org genuinely down --
RE-VERIFIED LIVE today (raw TCP connect timeout, port 443, from this Mac via both
the stdlib probe in scripts/check_orangeburg_gis.py AND a separate curl check;
DNS resolves fine (165.166.126.23) and the county's main site (different host)
answers HTTP 403 in <1s, so this is not a general network problem -- the on-prem
GIS server itself is unreachable, consistent with the 2026-10-20 and 2026-10-07
reads of the same host in county_records_matrix.json). That host was the ONLY
known source anyone had identified for assessed_value (its CLU_mtc CAMA popup
layer) and for beds_baths/sqft (the same layer, unverified for those fields,
never reached). Do not build against it; see docs/handoff or
logs/orangeburg_gis_health_check.log for the standing recheck.

beds_baths/sqft: live-verified NOT fixable right now. Fetched a REAL Orangeburg
qpaybill detail page today (TaxesDetailsType4.aspx) and grepped its raw HTML for
every bed/bath/sqft-shaped label (bed, bath, sq ft, square feet, heated, living
area, dwelling) -- zero matches, same dead end Lexington's identical vendor
software already confirmed (commit 535e71d0). The only configured ArcGIS layer
for this county (parcel_cache.py PARCEL_LAYERS["Orangeburg"], AGOL
Main_Public_Tax_Parcel_Map_WFL1) empirically carries ZERO bedrooms/bathrooms/
living_sqft/market_value across all 124,447 cached rows (checked live via
data/parcel_cache/orangeburg.sqlite) -- its own module comment already documents
why: the layer maps only owner/owner_mailing/acreage, nothing CAMA. So unlike
Lexington (where the ArcGIS cache DID carry Nbr_Bedroom/Nbr_FullBath/SqftLA, just
silently dropped downstream), Orangeburg has NO live, reachable source for these
two columns at all right now. Not built here; left as a gap pending gis2's
recovery (the only known lead, CLU_mtc, sits on that one dead host).

assessed_value: DOES have a live, already-coded, independent escape hatch that
has nothing to do with gis2. qpaybill_delinquent_roll.py's own STAGED DETAIL PASS
(DETAIL_ENABLED=1 by default since 2026-10-07) fetches each parcel's
TaxesDetailsType4.aspx page and parse_detail() already extracts
`"assessed_value": money("Total Assessed:")` as a CANONICAL Listing field
(`assessed_value=det.get("assessed_value")`, not nested under raw) -- live-
verified today against a real Orangeburg parcel (notice 058629263, map
01810700025001): appraised_value=22700.0, assessed_value=1360.0, ratio=6%,
acres, legal_description, map_number all parsed correctly from the real page.

So every piece already exists and already works -- confirmed live, not assumed
by analogy. What's missing is that the production pass has never actually
reached Orangeburg's rows: a read-only streaming board check (iter_board_rows,
never load_board()) found 3,470 Orangeburg rows from this source and ZERO of
them carry a `raw.qpaybill_roll.detail` nest, despite the pass being enabled
the whole time. The likely cause: `stage_detail_targets()`'s cap (DETAIL_MAX,
2000/run) is spent GLOBALLY across all ~19-27 qpaybill counties at once, ranked
HOT-then-WARM-then-COLD tier then largest-balance-first (ordered_detail_targets);
if Orangeburg's leads never crack that cross-county top-2000 cut, they never get
detailed, no matter how many runs pass. This script does NOT touch that shared
budget/ranking (it has a long, hard-won tuning history across 18+ OTHER
counties -- see this module's own MAX_CONCURRENT_COUNTIES/_GLOBAL_CONCURRENCY
docstrings for the 2026-09-23/09-25/10-03 incidents) and does not try to prove
the exact starvation mechanism further; it reuses the SAME proven functions
(sweep_county, fetch_details, parse_detail, _to_listings) with Orangeburg's OWN
dedicated, uncontended budget -- the same "county-scoped sibling" shape as
scripts/backfill_lexington_gis_attrs.py / backfill_mecklenburg_gis_attrs.py.

JOIN KEY. qpaybill's "Identification No." (`ident`) is this source's natural
account/parcel key (ACCOUNT_ID_ONLY for Orangeburg -- ident is an account
number, never a TMS; `parcel_id` is always None on these board rows). A FRESH
live sweep's ident values line up with the EXISTING board rows' own
raw.qpaybill_roll.identification_no (same real-world account numbers). This
script matches on ident, not on Listing.dedupe_key() -- the final board key for
a row with no parcel_id and no street_address falls all the way through to
`url:<source_url>`, which is IDENTICAL for every row of this source in this
county (models.py Listing.dedupe_key, final branch) -- a known, pre-existing
collision risk this project already has on record
(feedback_dedupe_key_url_fallback_landmine). Keying on ident instead avoids
ever needing to resolve a collision; dedupe_key() is computed only AFTER a
unique ident match, straight from that EXISTING row's own stored identity
fields (never re-synthesized), and an ident matching more than one existing
board row (the rare bulk-tax-buyer, multi-property case 2026-11-14 already
found) is skipped rather than guessed.

FILL-ONLY. Never overwrites a non-null board value; only ever fills a field
that is currently null/zero/empty.

SAFETY. patch_existing_rows() only (never load_board()/write_artifact()),
board_lock() with a real wait/poll (never forces past a held lock).

    python scripts/backfill_orangeburg_assessed_value.py --dry-run --max-detail 50
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_orangeburg_assessed_value.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import httpx  # noqa: E402

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_qpaybill_tax import _UA  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import (  # noqa: E402
    QPAYBILL_SUBS, _Budget, _to_listings, fetch_details, sweep_county,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, BoardLockBusy, board_lock, board_patch_size_state, patch_existing_rows,
)

STATE, COUNTY = "SC", "Orangeburg"
SOURCE = "counties_sc.qpaybill_delinquent_roll"
_TOP_FIELDS = ("assessed_value", "tax_value", "acreage", "legal_description")


def _board_index(docs_dir: Path) -> dict[str, list[dict]]:
    """{ident: [{"key": dedupe_key, "current": {field: value}}, ...]} for every
    existing Orangeburg qpaybill_roll board row, read streaming (never load_board())."""
    by_ident: dict[str, list[dict]] = {}
    n = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if (rec.get("state") or "") != STATE or (rec.get("county") or "") != COUNTY:
            continue
        if rec.get("source") != SOURCE:
            continue
        n += 1
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        qr = raw.get("qpaybill_roll") if isinstance(raw.get("qpaybill_roll"), dict) else {}
        ident = qr.get("identification_no")
        if not ident:
            continue
        li = Listing.model_construct(**{f: rec.get(f) for f in _APPEND_SIG_FIELDS})
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        current = {f: rec.get(f) for f in _TOP_FIELDS}
        by_ident.setdefault(ident, []).append({"key": key, "current": current})
    print(f"board: {n:,} existing {COUNTY} {STATE} rows from {SOURCE}, "
          f"{len(by_ident):,} distinct idents")
    return by_ident


async def _live_sweep_and_detail(max_detail: int) -> list[Listing]:
    sub = QPAYBILL_SUBS[COUNTY]
    budget = _Budget(2500)
    print(f"sweeping {sub}.qpaybill.com live (Orangeburg's own dedicated budget, "
          f"no cross-county contention)...")
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True,
                                 headers={"User-Agent": _UA}) as client:
        rows, stats = await sweep_county(client, COUNTY, sub, budget)
        print(f"  sweep done: {len(rows):,} raw rows, {stats}, "
              f"{time.monotonic() - t0:.0f}s")

        hrefs = [r["detail_href"] for r in rows if r.get("detail_href")]
        print(f"  rows with a detail_href: {len(hrefs):,} / {len(rows):,}")
        if max_detail:
            hrefs = hrefs[:max_detail]
            print(f"  --max-detail {max_detail}: capped to {len(hrefs):,} detail requests")

        dbudget = _Budget(len(hrefs) + 10)
        dstats: dict = {}
        t1 = time.monotonic()
        got = await fetch_details(client, sub, hrefs, dbudget, dstats)
        print(f"  detail fetch done: {len(got):,} parsed of {len(hrefs):,} requested, "
              f"{dstats}, {time.monotonic() - t1:.0f}s")

    for r in rows:
        rec = re.search(r"receiptNo=([^&]+)", r.get("detail_href") or "")
        if rec and rec.group(1) in got:
            r["detail"] = got[rec.group(1)]
    listings = _to_listings(COUNTY, rows)
    with_assessed = sum(1 for li in listings if li.assessed_value)
    print(f"  listings rebuilt: {len(listings):,}, with assessed_value: {with_assessed:,}")
    return listings


def build_patches(listings: list[Listing], by_ident: dict[str, list[dict]]
                  ) -> tuple[dict[str, dict], dict[str, int]]:
    """Pure (no I/O) patch-building step, split out of main() so it is unit-testable
    without a live network sweep or a real board.

    For each fresh listing with a usable `ident`, match it to the board's OWN existing
    row for that ident (never re-synthesized) and build a FILL-ONLY patch keyed by that
    row's dedupe_key -- see this module's docstring ("JOIN KEY") for why ident, not
    dedupe_key, is the match key, and why an ident mapping to more than one existing
    board row is skipped rather than guessed.
    """
    patches: dict[str, dict] = {}
    stats = {"skipped_ambiguous": 0, "skipped_no_match": 0, "skipped_no_new_data": 0,
             "skipped_no_ident": 0}
    for li in listings:
        qr = li.raw.get("qpaybill_roll") if isinstance(li.raw, dict) else None
        ident = qr.get("identification_no") if isinstance(qr, dict) else None
        if not ident:
            stats["skipped_no_ident"] += 1
            continue
        candidates = by_ident.get(ident)
        if not candidates:
            stats["skipped_no_match"] += 1
            continue
        if len(candidates) != 1:
            # Rare multi-property-per-ident case (2026-11-14 fix). Disambiguating by
            # address is possible but not worth the risk of a wrong match here --
            # skip, don't guess.
            stats["skipped_ambiguous"] += 1
            continue
        current = candidates[0]["current"]
        key = candidates[0]["key"]
        patch: dict = {}
        for f in _TOP_FIELDS:
            new_val = getattr(li, f, None)
            if new_val in (None, "", 0):
                continue
            if current.get(f) not in (None, "", 0):
                continue  # fill-only: never overwrite an existing value
            patch[f] = new_val
        if patch:
            patches[key] = patch
        else:
            stats["skipped_no_new_data"] += 1
    return patches, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-detail", type=int, default=0,
                     help="cap detail requests this run (0 = all parcels with an href)")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    by_ident = _board_index(docs_dir)
    if not by_ident:
        print("nothing to do (no existing Orangeburg qpaybill_roll rows found).")
        return 0

    listings = asyncio.run(_live_sweep_and_detail(args.max_detail))
    patches, stats = build_patches(listings, by_ident)

    print(f"idents from this sweep with a detail result applied: "
          f"{len(patches) + stats['skipped_no_new_data']:,}")
    print(f"  no matching board row (new/stale ident): {stats['skipped_no_match']:,}")
    print(f"  ambiguous (ident maps to >1 board row): {stats['skipped_ambiguous']:,}")
    print(f"  matched but nothing new to fill: {stats['skipped_no_new_data']:,}")
    print(f"rows to patch: {len(patches):,}")

    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, p)
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    try:
        with board_lock(REPO, owner="backfill_orangeburg_assessed_value", wait=3600, poll=10):
            pstats = patch_existing_rows(
                patches, {"backfill_orangeburg_assessed_value": len(patches)}, docs_dir=docs_dir)
    except BoardLockBusy as exc:
        print(f"{exc} -- refusing to write ({len(patches):,} patches from this "
              f"invocation are lost; re-run to redo them and retry).")
        return 1
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
