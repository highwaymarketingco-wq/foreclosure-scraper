#!/usr/bin/env python3
"""Run enrichment_surface_contacts.enrich_surface_contacts() board-wide.

Not wired into main.py at all (confirmed via grep). 100% offline, no
network calls -- it only surfaces phone/email patterns already sitting in
raw text fields (agent phones, attorney contact blocks, free-text notices)
onto li.raw['owner_phone'] / li.raw['owner_email'] when not already set.

    python scripts/backfill_surface_contacts.py --dry-run
    python scripts/backfill_surface_contacts.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_surface_contacts import enrich_surface_contacts  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_surface_contacts")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        phone_before = sum(1 for li in rows if isinstance(li.raw, dict) and (li.raw.get("owner_phone") or {}).get("phone"))
        email_before = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("owner_email"))
        print(f"owner_phone before: {phone_before:,}  owner_email before: {email_before:,}")

        if args.dry_run:
            print("\nDRY RUN — enrich_surface_contacts() not called, nothing written.")
            return 0

        stats = enrich_surface_contacts(rows)
        phone_after = sum(1 for li in rows if isinstance(li.raw, dict) and (li.raw.get("owner_phone") or {}).get("phone"))
        email_after = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("owner_email"))
        print(f"\nstats: {stats}")
        print(f"owner_phone after: {phone_after:,} (+{phone_after - phone_before:,})")
        print(f"owner_email after: {email_after:,} (+{email_after - email_before:,})")

        write_artifact(rows, {"backfill_surface_contacts": stats}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
