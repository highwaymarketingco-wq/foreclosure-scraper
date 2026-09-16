#!/usr/bin/env python3
"""Run enrich_owner_name_signal() and enrich_tenure() board-wide in one pass.

Both are wired into main.py's pipeline but the board has never had a full
main.py run against today's newly-added data (geocode/parcel/comps/deed_chain
backfills all landed outside main.py). Confirmed stale: owner_name_signal on
4,935/175,518 despite 153,627 rows carrying an owner_name; tenure on
13,113/175,518. Both are 100% offline (owner_name_signal is a pure regex
classify on li.owner_name; tenure reads raw.gis.last_sale/raw.cama, both of
which the deed_chain/gis_attrs_full backfills just substantially expanded).

Direct implementation of Tier A items #1 (owner-name death/heir token
classification) and the "tired landlord" tenure signal from
docs/dirty_deeds_synthesis_2026-09-10.md.

    python scripts/backfill_signal_flags.py --dry-run
    python scripts/backfill_signal_flags.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_owner_name_signal import enrich_owner_name_signal  # noqa: E402
from foreclosure_scraper.enrichment_tenure import enrich_tenure  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_signal_flags")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        ons_before = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("owner_name_signal"))
        tenure_before = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("tenure"))
        print(f"owner_name_signal before: {ons_before:,}  tenure before: {tenure_before:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        s1 = enrich_owner_name_signal(rows)
        print(f"owner_name_signal stats: {s1}")
        s2 = enrich_tenure(rows)
        print(f"tenure stats: {s2}")

        ons_after = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("owner_name_signal"))
        tenure_after = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("tenure"))
        print(f"owner_name_signal after: {ons_after:,} (+{ons_after - ons_before:,})")
        print(f"tenure after: {tenure_after:,} (+{tenure_after - tenure_before:,})")

        write_artifact(rows, {"backfill_signal_flags": {"owner_name_signal": s1, "tenure": s2}}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
