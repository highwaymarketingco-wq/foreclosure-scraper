"""Bankruptcy delta runner.

Reads the most-recent docs/listings.json, runs the CourtListener bankruptcy
scraper + cross-reference enrichment, merges results back, rewrites
docs/listings.json. Avoids re-paying for Vision/comps/etc.

Usage:
    cd /Users/cashhigh/Desktop/foreclosure-scraper
    uv run python scripts/bankruptcy_delta.py

Requires .secrets/courtlistener_token.txt (or COURTLISTENER_TOKEN env var).
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Make `foreclosure_scraper` importable when running as a script
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from foreclosure_scraper.enrichment_bankruptcy import enrich_with_bankruptcy  # noqa: E402
from foreclosure_scraper.enrichment_bankruptcy_property import (  # noqa: E402
    enrich_bankruptcy_property,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.national.courtlistener_bankruptcy import (  # noqa: E402
    CourtListenerBankruptcy,
)
from foreclosure_scraper.web_artifact import _to_dict  # noqa: E402

LISTINGS_PATH = ROOT / "docs" / "listings.json"
META_PATH = ROOT / "docs" / "run_meta.json"


def _print(msg: str) -> None:
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def _load_listings() -> list[Listing]:
    if not LISTINGS_PATH.exists():
        raise SystemExit(f"missing {LISTINGS_PATH}")
    rows = json.loads(LISTINGS_PATH.read_text(encoding="utf-8"))
    out: list[Listing] = []
    for r in rows:
        try:
            out.append(Listing.model_validate(r))
        except Exception as exc:
            _print(f"skip-malformed: {exc}")
    return out


def _key(li: Listing) -> tuple[str, str, str | None]:
    return (li.source, li.source_url or "", li.case_number)


async def main() -> int:
    _print("loading listings.json...")
    listings = _load_listings()
    _print(f"loaded {len(listings)} listings")

    # 1. Cross-reference: tag every existing listing whose defendant matches
    #    a recent NC/SC bankruptcy debtor.
    _print("running bankruptcy cross-reference enrichment...")
    await enrich_with_bankruptcy(listings)
    tagged = sum(1 for li in listings if isinstance(li.raw, dict) and li.raw.get("bankruptcy"))
    _print(f"cross-reference: {tagged} listings tagged with bankruptcy match")

    # 2. Discovery: pull bankruptcy filings as standalone leads (debtor name
    #    only, no address — but still useful pre-foreclosure signal).
    #
    #    Strategy: drop ALL existing bankruptcy-source listings before merge so
    #    we get fresh chapter data (CourtListener backfills bankruptcy_information
    #    over time, so older runs may have stale "?" chapters).
    pre_drop = len(listings)
    listings = [li for li in listings if li.source != "national.courtlistener_bankruptcy"]
    dropped = pre_drop - len(listings)
    _print(f"dropped {dropped} stale bankruptcy listings before refresh")

    _print("running CourtListener bankruptcy scraper...")
    scraper = CourtListenerBankruptcy()
    new_listings = list(await scraper.fetch())
    _print(f"scraper: {len(new_listings)} bankruptcy filings pulled")

    # Merge: dedupe by (source, source_url, case_number).
    seen: set[tuple[str, str, str | None]] = {_key(li) for li in listings}
    added = 0
    for li in new_listings:
        k = _key(li)
        if k not in seen:
            listings.append(li)
            seen.add(k)
            added += 1
    _print(f"merged: {added} new listings added (skipped {len(new_listings) - added} dupes)")

    # 2b. Bankruptcy property lookup — for every BK listing, scan county GIS
    #     by debtor name to recover address + property specs. Without this,
    #     BK listings are just "Mary Lee Harrell, Ch.7" with no property info.
    _print("running bankruptcy property lookup (debtor name → county GIS)...")
    await enrich_bankruptcy_property(listings)
    bk_with_addr = sum(
        1
        for li in listings
        if li.source == "national.courtlistener_bankruptcy" and li.street_address
    )
    _print(f"bk-property: {bk_with_addr} bankruptcy listings now have addresses")

    # 3. Rewrite listings.json with the same trim logic the orchestrator uses.
    _print("rewriting listings.json...")
    payload = [_to_dict(li) for li in listings]
    LISTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8"
    )
    size_kb = LISTINGS_PATH.stat().st_size // 1024
    _print(f"wrote {LISTINGS_PATH} ({len(payload)} listings, {size_kb} KB)")

    # 4. Patch run_meta.json with the bankruptcy delta info (best-effort).
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
            meta["bankruptcy_delta"] = {
                "run_time": datetime.utcnow().isoformat() + "Z",
                "listings_tagged": tagged,
                "new_listings_added": added,
                "scraper_total": len(new_listings),
            }
            meta["total"] = len(payload)
            by_source = meta.get("by_source") or {}
            # SET the count from actual listings — re-running delta should not
            # accumulate; idempotent based on current listings.json state.
            bk_count = sum(
                1 for r in payload if r.get("source") == "national.courtlistener_bankruptcy"
            )
            by_source["national.courtlistener_bankruptcy"] = bk_count
            meta["by_source"] = by_source
            META_PATH.write_text(
                json.dumps(meta, ensure_ascii=False, default=str, indent=2), encoding="utf-8"
            )
            _print(f"patched {META_PATH} with bankruptcy delta info")
        except Exception as exc:
            _print(f"warn: could not patch run_meta.json: {exc}")

    _print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
