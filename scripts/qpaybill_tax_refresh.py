"""Scheduled/opt-in qPayBill delinquent-tax pass — fills raw['tax_owed'] balance
for county-tax leads whose county publishes on a qPayBill portal (SC Spartanburg
etc.) and that don't yet carry a balance. Runs on the committed board (no
re-scrape); board-writer — run alone.

Loads via web_artifact.load_board() so the lazy-detail sidecar round-trips.
Idempotent: skips leads that already have raw['tax_owed'].balance. Sets
QPAYBILL_TAX=1 itself.

Usage:  QPAYBILL_MAX_QUERIES=2000 uv run python scripts/qpaybill_tax_refresh.py
"""
from __future__ import annotations

import asyncio
import json  # noqa: F401  (kept for parity; load_board handles IO)
import os
from pathlib import Path

os.environ.setdefault("QPAYBILL_TAX", "1")

from foreclosure_scraper.enrichment_qpaybill_tax import enrich_qpaybill_tax
from foreclosure_scraper.web_artifact import write_artifact, load_board

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main() -> int:
    listings = load_board(DOCS)
    before = sum(1 for l in listings if (l.raw or {}).get("tax_owed", {}).get("balance"))
    print(f"loaded {len(listings)} | tax_owed before={before}", flush=True)

    stats = asyncio.run(enrich_qpaybill_tax(listings))
    print("qpaybill_tax:", stats, flush=True)

    after = sum(1 for l in listings if (l.raw or {}).get("tax_owed", {}).get("balance"))
    write_artifact(listings, {"notes": "qPayBill delinquent-tax balance refresh"}, docs_dir=DOCS)
    print(f"wrote board | tax_owed={after}(+{after - before})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
