"""Address backfill delta — run owner-name GIS lookup on existing listings.json
without re-running the full pipeline. Useful to test the enrichment in
isolation before committing the orchestrator changes.

Usage:
    cd /Users/cashhigh/Desktop/foreclosure-scraper
    uv run python scripts/address_backfill_delta.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from foreclosure_scraper.enrichment_address_backfill import (  # noqa: E402
    enrich_addresses_from_owner,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import _to_dict  # noqa: E402

LISTINGS_PATH = ROOT / "docs" / "listings.json"


def _print(msg: str) -> None:
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


async def main() -> int:
    # GUARD (2026-08-14): this script writes docs/listings.json directly with
    # write_text(json.dumps(...)) — it does NOT go through load_board()/write_artifact(),
    # so it wipes the vision/comps/cama/staleness sidecar (RAW_KEEP) and emits only 1 of
    # the 6 board files. The dashboard streams listings.json.gz, so its edits never land AND
    # the next full run reads a misaligned board. Superseded by scripts/resolve_addresses.py
    # (ADDR_WRITE=1) — same address lanes, correct board writer + board_lock + dedupe.
    import os as _os
    if _os.environ.get("ALLOW_UNSAFE_BOARD_WRITE") != "1":
        print("REFUSING: this script corrupts the board (writes listings.json without "
              "load_board/write_artifact). Use:  ADDR_WRITE=1 .venv/bin/python "
              "scripts/resolve_addresses.py")
        return 2
    rows = json.loads(LISTINGS_PATH.read_text(encoding="utf-8"))
    listings: list[Listing] = []
    for r in rows:
        try:
            listings.append(Listing.model_validate(r))
        except Exception:
            pass
    _print(f"loaded {len(listings)} listings")

    no_addr_before = sum(
        1
        for li in listings
        if not li.street_address and li.source != "national.courtlistener_bankruptcy"
    )
    _print(f"missing addresses (pre-backfill): {no_addr_before}")

    await enrich_addresses_from_owner(listings)

    no_addr_after = sum(
        1
        for li in listings
        if not li.street_address and li.source != "national.courtlistener_bankruptcy"
    )
    _print(f"missing addresses (post-backfill): {no_addr_after}")
    _print(f"backfilled: {no_addr_before - no_addr_after}")

    payload = [_to_dict(li) for li in listings]
    LISTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8"
    )
    _print(f"wrote {LISTINGS_PATH} ({len(payload)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
