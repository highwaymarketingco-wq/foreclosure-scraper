"""Merge user-saved SC PublicIndex export pages into the board.

Board-writer — run ALONE. Loads via web_artifact.load_board() so the lazy-detail
sidecar round-trips. Parses every saved PublicIndex *.html in the scan dirs
(default: repo root + ~/Downloads), dedupes by case number against the board,
appends net-new court leads, resolves property/owner from the defendant name via
county GIS, then rescores. Idempotent — re-running only adds cases not already on
the board.

Usage:  uv run python scripts/ingest_publicindex_files.py [dir ...]
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from foreclosure_scraper.ingest_sc_publicindex_export import parse_publicindex_html
from foreclosure_scraper.enrichment_lis_pendens_resolver import enrich_lis_pendens_addresses
from foreclosure_scraper.enrichment_owner_mailing import enrich_owner_mailing
from foreclosure_scraper.distress_score import score_board
from foreclosure_scraper.web_artifact import load_board, write_artifact

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
SCAN = [Path(p) for p in sys.argv[1:]] or [REPO, Path.home() / "Downloads"]
BUDGET_S = float(os.environ.get("INGEST_BUDGET_S", "2400"))

# Footprint counties for the filename -> default-county fallback (only used when
# the case number can't decode a venue; the case# venue code wins when present).
_FOOTPRINT = (
    "Spartanburg", "Anderson", "Pickens", "Oconee", "Cherokee", "Union", "Laurens",
)


def _county_from_name(name: str) -> str | None:
    low = name.lower()
    for c in _FOOTPRINT:
        if c.lower() in low:
            return c
    return None


def _looks_publicindex(html: str) -> bool:
    return "ContentPlaceHolder1_SearchResults" in html or "publicindex" in html.lower()


def main() -> int:
    listings = load_board(DOCS)
    existing = {li.case_number for li in listings if li.case_number}

    files: list[Path] = []
    for d in SCAN:
        if d.is_dir():
            files += sorted(d.glob("*.htm")) + sorted(d.glob("*.html"))

    new = []
    seen: set[str] = set()
    for f in files:
        try:
            html = f.read_text(errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if not _looks_publicindex(html):
            continue
        rows = parse_publicindex_html(html, default_county=_county_from_name(f.name))
        kept = 0
        for li in rows:
            cn = li.case_number
            if cn and cn not in existing and cn not in seen:
                seen.add(cn)
                new.append(li)
                kept += 1
        if rows:
            print(f"  {f.name[:46]:46} parsed {len(rows):3} | net-new {kept}", flush=True)

    print(f"loaded {len(listings)} | net-new PublicIndex leads: {len(new)}", flush=True)
    if not new:
        print("nothing new — board unchanged", flush=True)
        return 0

    listings.extend(new)

    async def go():
        try:
            r = await asyncio.wait_for(enrich_lis_pendens_addresses(new), timeout=BUDGET_S / 2)
            print("resolver:", r, flush=True)
        except Exception as exc:  # noqa: BLE001
            print("resolver bailed:", str(exc)[:160], flush=True)
        try:
            r = await asyncio.wait_for(enrich_owner_mailing(new, max_concurrency=2), timeout=BUDGET_S / 2)
            print("owner_mailing:", r, flush=True)
        except Exception as exc:  # noqa: BLE001
            print("mailing bailed:", str(exc)[:160], flush=True)

    asyncio.run(go())

    score_board(listings, previous_path=DOCS / "listings.json")
    resolved = sum(1 for li in new if (li.street_address or "").strip() or (li.parcel_id or "").strip())
    write_artifact(
        listings,
        {"notes": f"merged {len(new)} saved SC PublicIndex court leads"},
        docs_dir=DOCS,
    )
    print(f"wrote board | +{len(new)} leads (now {len(listings)}) | address/parcel resolved: {resolved}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
