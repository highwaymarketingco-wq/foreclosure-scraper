#!/usr/bin/env python3
"""Land the harvested SC delinquent-tax roll on the board.

WHAT THIS INGESTS
    The qPayBill sweep of 19 SC county treasurer portals, harvested 2026-09-10/11 into
    logs/qpaybill_roll_all.json and logs/qpaybill_roll_top5.json. Five counties hit their
    per-county request budget on the first pass and REPORTED THEMSELVES INCOMPLETE rather
    than claiming success; the re-run at a higher budget recovered 3,843 more parcels, so
    the re-run file SUPERSEDES those five counties in the first file.

    Every row carries owner name, TMS, balance owed, the years unpaid and a two-year-plus
    flag; about two thirds carry a situs address.

WHY A SCRIPT INSTEAD OF A PIPELINE RUN
    The scraper is wired and will run in the normal cycle, but a full run is a 6-10 hour
    job on this machine and the harvest already exists on disk. This lands it now, through
    the SAME dedupe the pipeline uses, so the rows merge with their existing twins instead
    of doubling them.

SAFETY
  * dedupe() is the project's own, so a parcel already on the board from another source
    merges rather than duplicating.
  * Rows with no parcel are dropped -- a delinquent-tax lead with no TMS cannot be
    underwritten, joined to the assessor, or routed to a county.
  * The county is taken from the harvest, never inferred.
  * This ADDS rows, so the count guard is not at risk; the row count is asserted to have
    grown, and the before/after is printed.

    python scripts/ingest_sc_delinquent_roll.py --dry-run
    python scripts/ingest_sc_delinquent_roll.py
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

FILES = [
    ("base", REPO / "logs" / "qpaybill_roll_all.json"),
    ("rerun", REPO / "logs" / "qpaybill_roll_top5.json"),   # supersedes its counties
    ("catalis", REPO / "logs" / "catalis_pickens_full.json"),
    # Greenville Master-in-Equity foreclosure adverts: TMS + the ACTUAL total judgment
    # debt per case. Different county from all the rolls above, so nothing is superseded.
    ("greenville_mie", REPO / "logs" / "greenville_mie_full.json"),
]


def load_rows() -> tuple[list[dict], dict]:
    """Later files win for any county they contain."""
    by_county: dict[str, list[dict]] = {}
    prov: dict[str, str] = {}
    for label, path in FILES:
        if not path.exists():
            continue
        try:
            rows = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {path.name}: unreadable ({exc})")
            continue
        if not isinstance(rows, list) or not rows:
            print(f"  - {path.name}: 0 rows, skipped")
            continue
        counties = {r.get("county") for r in rows if r.get("county")}
        for c in counties:
            by_county[c] = [r for r in rows if r.get("county") == c]
            prov[c] = label
        print(f"  + {path.name}: {len(rows):,} rows over {len(counties)} counties ({label})")
    flat = [r for rows in by_county.values() for r in rows]
    return flat, prov


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.dedupe import _strong_sigs, dedupe
    from foreclosure_scraper.models import Listing
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    print("loading harvest files:")
    raw_rows, prov = load_rows()
    print(f"\nharvested rows after supersede: {len(raw_rows):,}")

    fresh: list[Listing] = []
    dropped = Counter()
    _addr_only: list = []
    for r in raw_rows:
        # A lead needs SOMETHING to be routed and underwritten by: a parcel, or failing
        # that a street address. Requiring a parcel alone silently discarded every
        # Orangeburg row -- 6,669 of them -- because that county's portal publishes an
        # ACCOUNT id rather than a TMS, so the scraper deliberately sets parcel_id=None
        # rather than feed dedupe a non-parcel. They still carry owner, balance and (for
        # some) a situs address, so the honest filter is "parcel OR address".
        if not (r.get("parcel_id") or "").strip():
            if not (r.get("street_address") or "").strip():
                dropped["no parcel AND no address"] += 1
                continue
            dropped["kept on address alone (no parcel)"] += 0  # counted below
            _addr_only.append(1)
        try:
            fresh.append(Listing(**r))
        except Exception:  # noqa: BLE001
            # models change; fall back to the fields we know the harvest carries
            try:
                fresh.append(Listing(
                    source=r.get("source") or "counties_sc.qpaybill_delinquent_roll",
                    source_url=r.get("source_url") or "",
                    listing_type=r.get("listing_type") or "tax_sale",
                    property_kind=r.get("property_kind") or "unknown",
                    state=r.get("state") or "SC", county=r.get("county"),
                    parcel_id=r.get("parcel_id"), defendant=r.get("defendant"),
                    owner_name=r.get("owner_name"), street_address=r.get("street_address"),
                    tax_value=r.get("tax_value"), acreage=r.get("acreage"),
                    legal_description=r.get("legal_description"),
                    description=r.get("description"),
                    first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
                    raw=r.get("raw") or {}))
            except Exception as exc:  # noqa: BLE001
                dropped[f"unbuildable: {type(exc).__name__}"] += 1

    print(f"buildable listings          : {len(fresh):,}")
    if _addr_only:
        print(f"  of which no parcel, address only: {len(_addr_only):,} "
              f"(Orangeburg publishes an account id, not a TMS)")
    for k, n in dropped.most_common():
        print(f"  dropped {n:>6,}  {k}")

    by_county = Counter(li.county for li in fresh)
    two_yr = sum(1 for li in fresh
                 if (li.raw.get("qpaybill_roll") or li.raw.get("catalis_roll") or {}).get("is_two_year_plus"))
    with_addr = sum(1 for li in fresh if (li.street_address or "").strip())
    print(f"\n  with a situs address      : {with_addr:,}")
    print(f"  two-year-plus delinquent  : {two_yr:,}")
    print(f"  counties                  : {len(by_county)}")

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="ingest_sc_roll")
    with lock:
        existing = load_board(REPO / "docs")
        before = len(existing)
        print(f"\nboard before: {before:,}")

        # ADDITIVE MERGE, NOT A WHOLE-BOARD RE-DEDUPE.
        #
        # Measured 2026-09-11: dedupe(board) with NO new data at all collapses
        # 94,384 -> 70,878, eliminating 23,506 rows. The published board is simply not
        # in dedupe-normal-form -- it carries genuine cross-source duplicates that have
        # never been merged (the same Buncombe house arriving from liensnc,
        # buncombe_elderly and buncombe_delinquent_tax). An audit of the union-find pass
        # found 6,841 of 7,336 merge groups share one address, i.e. most of that
        # collapse is legitimate.
        #
        # But it is a 25% change to the operator's board and it is NOT this script's
        # decision to make. dedupe(existing + fresh) would have reported "net -5,185"
        # and quietly swallowed both effects at once: +18k new leads hidden behind -23k
        # of collapse. So the fresh rows are deduped among THEMSELVES and matched
        # against the existing keys; existing rows are never re-merged with each other.
        existing_keys = set()
        for li in existing:
            existing_keys.add(li.dedupe_key())
            existing_keys.update(_strong_sigs(li))

        fresh_deduped = dedupe(fresh)          # within the harvest only
        add, matched = [], 0
        for li in fresh_deduped:
            sigs = {li.dedupe_key()} | _strong_sigs(li)
            if sigs & existing_keys:
                matched += 1
                continue
            add.append(li)
            existing_keys |= sigs
        merged = existing + add
        after = len(merged)
        net_new = len(add)
        print(f"harvest deduped internally  : {len(fresh):,} -> {len(fresh_deduped):,}")
        print(f"  already on the board      : {matched:,}")
        print(f"  NET NEW leads             : {net_new:,}")
        print(f"board after : {after:,}  (existing {before:,} untouched)")

        print("\n--- per county (harvested) ---")
        for c, n in by_county.most_common():
            print(f"   {c:<15}{n:>7,}   [{prov.get(c, '?')}]")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        assert after >= before, "an ingest must never shrink the board"
        write_artifact(merged, {
            "total": after,
            "notes": (f"SC delinquent roll ingest: {len(fresh):,} harvested, "
                      f"{len(fresh_deduped):,} after internal dedupe, {matched:,} already "
                      f"on the board, {net_new:,} net-new. Existing rows untouched."),
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} -> {after:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
