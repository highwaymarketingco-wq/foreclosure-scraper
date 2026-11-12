#!/usr/bin/env python3
"""Fold a harvested JSON file of Listing dicts onto the board.

Generic sibling of ingest_sc_delinquent_roll.py, for harvests that already exist on
disk. Uses the PROJECT'S OWN dedupe so a lead already on the board from another
source merges instead of doubling, and reports FIELD gains rather than raw-key
counts (a key-count comparison once reported "0 enriched" on a run that was filling
tax_value on thousands of rows).

    python scripts/ingest_json_leads.py logs/ncnotices_foreclosure.json --dry-run
    python scripts/ingest_json_leads.py logs/ncnotices_foreclosure.json
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.dedupe import _strong_sigs, dedupe  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    board_lock, load_board, write_artifact,
)

WATCH = ("tax_value", "market_value", "living_sqft", "acreage", "street_address",
         "owner_name", "case_number", "sale_date", "zip_code", "city",
         "judgment_amount", "opening_bid", "trustee", "defendant")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = json.loads(Path(args.path).read_text())
    fresh: list[Listing] = []
    bad = 0
    for r in raw:
        try:
            fresh.append(Listing(**r))
        except Exception:  # noqa: BLE001
            bad += 1
    print(f"{args.path}: {len(raw):,} rows -> {len(fresh):,} valid listings"
          + (f" ({bad} unparseable)" if bad else ""))

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="json_ingest")
    with lock:
        existing = load_board(REPO / "docs")
        before = len(existing)
        print(f"board before: {before:,}")

        by_sig: dict = {}
        for li in existing:
            for sig in {li.dedupe_key()} | _strong_sigs(li):
                by_sig.setdefault(sig, li)

        fresh_deduped = dedupe(fresh)
        add, matched, enriched = [], 0, 0
        gains = Counter()
        for li in fresh_deduped:
            sigs = {li.dedupe_key()} | _strong_sigs(li)
            twin = next((by_sig[s] for s in sigs if s in by_sig), None)
            if twin is not None:
                matched += 1
                before_vals = {f: getattr(twin, f, None) for f in WATCH}
                merged = twin.merge(li)
                if merged is not twin:
                    twin.__dict__.update(merged.__dict__)
                got = [f for f in WATCH
                       if before_vals[f] in (None, "") and getattr(twin, f, None) not in (None, "")]
                if got:
                    enriched += 1
                    for f in got:
                        gains[f] += 1
                continue
            add.append(li)
            for s in sigs:
                by_sig.setdefault(s, li)

        print(f"harvest deduped: {len(fresh):,} -> {len(fresh_deduped):,}")
        print(f"  already on the board : {matched:,}")
        print(f"    of those, ENRICHED : {enriched:,}")
        for f, n in gains.most_common():
            print(f"        + {n:>5}  {f}")
        print(f"  NET NEW leads        : {len(add):,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        out = existing + add
        assert len(out) >= before, "row count shrank — refusing to write"
        write_artifact(out, {"json_ingest": Path(args.path).name, "net_new": len(add)},
                       docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} -> {len(out):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
