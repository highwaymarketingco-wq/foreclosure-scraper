#!/usr/bin/env python3
"""Quick enrich: surface_contacts + HUD FMR + email_extract.

Runs only the new enrichers on the board and persists to disk.
Much faster than a full enrich_board.py pass.
"""
import asyncio
import sys
import time
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.web_artifact import load_board, write_artifact
from foreclosure_scraper.models import Listing


async def main():
    docs_dir = Path(__file__).parent.parent / "docs"
    t0 = time.time()

    print("Loading board...")
    board = load_board(docs_dir)
    print(f"Board: {len(board)} listings")

    # 1. Surface contacts (phones + emails already in raw data)
    print("\n[1] Surface contacts...")
    from foreclosure_scraper.enrichment_surface_contacts import enrich_surface_contacts
    c_stats = enrich_surface_contacts(board)
    print(f"  Phones: {c_stats['phones_found']} ({c_stats['listings_with_new_phones']} listings)")
    print(f"  Emails: {c_stats['emails_found']} ({c_stats['listings_with_new_emails']} listings)")

    # 2. Email extraction (deeper scan)
    print("\n[2] Email extraction...")
    from foreclosure_scraper.enrichment_email_extract import enrich_extract_emails
    e_stats = enrich_extract_emails(board)
    print(f"  Listings with emails: {e_stats['listings_with_emails']}")
    print(f"  Total emails: {e_stats['total_emails']}")

    # 3. HUD FMR rent estimates
    print("\n[3] HUD FMR rent estimates...")
    from foreclosure_scraper.enrichment_hud_fmr import enrich_hud_fmr
    f_stats = await enrich_hud_fmr(board)
    print(f"  Downloaded: {f_stats.get('downloaded', False)}")
    print(f"  ZIPs in FMR data: {f_stats.get('total_zips_in_fmr', 0)}")
    print(f"  Listings with rent: {f_stats.get('listings_with_rent', 0)}")
    print(f"  ZIPs not found: {f_stats.get('zips_not_found', 0)}")

    # 4. Deduplicate
    seen_keys: set[str] = set()
    deduped: list = []
    for li in board:
        key = li.dedupe_key()
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        deduped.append(li)
    if len(deduped) < len(board):
        print(f"\n  Dedup: {len(board)} -> {len(deduped)} ({len(board) - len(deduped)} removed)")
        board = deduped

    # 5. Write board
    print(f"\n[4] Writing board: {len(board)} listings...")
    summary = {
        "total": len(board),
        "enrichment_pass": "quick_surface_fmr",
        "enrichers": {
            "surface_contacts": f"phones={c_stats['phones_found']}, emails={c_stats['emails_found']}",
            "email_extract": f"{e_stats['listings_with_emails']} listings, {e_stats['total_emails']} emails",
            "hud_fmr": f"matched={f_stats.get('listings_with_rent', 0)}, not_found={f_stats.get('zips_not_found', 0)}",
        },
        "by_state": dict(Counter(li.state or "?" for li in board)),
        "notes": "quick pass: surface_contacts + email_extract + hud_fmr",
    }
    write_artifact(board, summary, docs_dir)

    elapsed = time.time() - t0
    print(f"\nDONE: {len(board)} listings enriched in {elapsed:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
