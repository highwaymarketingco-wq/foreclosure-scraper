#!/usr/bin/env python3
"""Resolve address-less Anderson SC leads to a parcel from the offline assessor roll.

Anderson was a wall for the name resolver (no owner column on the live viewer, ACPASS is
login-walled, the live County_Parcels layer stopped publishing owners). The 2026-08-03
bulk roll on disk (data/sc_parcel_mailing.db) holds 113,406 Anderson owners and
sc_parcel_mailing.lookup_by_owner searches it offline, exact/strong matches only. It had
no callers until enrichment_resolve_name_to_property gained an `offline_roll` backend.

Zero network requests. --apply resolves the leads, then fills their owner mailing from the
same roll (enrich_owner_mailing checks the roll first, exact-key), so a resolved lead
leaves with parcel, situs, value and a mailing address.

    python scripts/resolve_anderson_from_roll.py            # streams the board, counts only
    python scripts/resolve_anderson_from_roll.py --apply    # ONLY board process (about 3 GB)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

COUNTY = "Anderson"


def _is_candidate(state, county, street, parcel) -> bool:
    return (state == "SC" and (county or "").replace(" County", "").strip() == COUNTY
            and not (street or "").strip() and not (parcel or "").strip())


def _classify(R, pm, name: str) -> str:
    """unique | ambiguous | none, by the resolver's own rules on offline roll rows."""
    cfg = R._offline_roll_cfg(COUNTY)
    if cfg is None:
        return "no_roll"
    for party in R._split_joint(name):
        rows = R._offline_roll_rows(cfg, party)
        hits = R._strict_matches(rows, cfg["owner_field"], party)
        if not hits:
            continue
        parcels = {R._row_parcel(r, cfg["parcel_field"]) for _k, r in hits}
        return "unique" if len(hits) == 1 or len(parcels) == 1 else "ambiguous"
    return "none"


def _dry_run() -> int:
    import foreclosure_scraper.enrichment_resolve_name_to_property as R
    from foreclosure_scraper import sc_parcel_mailing as pm
    from foreclosure_scraper.board_stream import iter_board_rows
    c: Counter = Counter()
    for r in iter_board_rows():
        if not _is_candidate(r.get("state"), r.get("county"), r.get("street_address"), r.get("parcel_id")):
            continue
        ns = SimpleNamespace(owner_name=r.get("owner_name"), defendant=r.get("defendant"))
        name = R._lead_name(ns)
        c["address-less Anderson leads"] += 1
        if not name:
            c["no usable name"] += 1
            continue
        prov = (r.get("raw") or {}).get("resolved_from_name") or {}
        if prov.get("queried"):
            c["already queried"] += 1
            continue
        c["would try: " + _classify(R, pm, name)] += 1
    for k, n in sorted(c.items()):
        print(f"  {n:6,}  {k}")
    print("\nDRY RUN, nothing written. Re-run with --apply (as the only board process).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        return _dry_run()

    import foreclosure_scraper.enrichment_resolve_name_to_property as R
    from foreclosure_scraper.enrichment_owner_mailing import enrich_owner_mailing
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    with board_lock(REPO, owner="resolve_anderson_from_roll"):
        rows = load_board(REPO / "docs")
        n = len(rows)
        targets = [li for li in rows if _is_candidate(li.state, li.county, li.street_address, li.parcel_id)]
        print(f"board rows: {n:,}; address-less Anderson leads: {len(targets):,}", flush=True)
        stats = asyncio.run(R.enrich_resolve_name_to_property(targets))
        print("resolver:", {k: v for k, v in stats.items() if v}, flush=True)
        resolved = [li for li in targets if (li.parcel_id or "").strip() or (li.street_address or "").strip()]
        if resolved:
            print("owner_mailing (offline roll):", asyncio.run(enrich_owner_mailing(resolved, max_concurrency=2)), flush=True)
        assert len(rows) == n
        write_artifact(rows, {"resolve_anderson_from_roll": {"targets": len(targets), "resolved": len(resolved)}},
                       docs_dir=REPO / "docs")
        print(f"wrote board: {n:,} rows; resolved {len(resolved):,} of {len(targets):,}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
