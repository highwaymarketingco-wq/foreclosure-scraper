#!/usr/bin/env python3
"""Merge title search results from the 38,108-board back into the restored 53,851-board.

Root cause: scripts used stream_save() which doesn't write listings_detail.json
(the lazy-detail sidecar). Each load_board() call silently dropped records that
failed Pydantic validation without the sidecar merge, losing 15,743 listings.

This script:
1. Loads the 38,108-board (from git commit 969b71a) as raw dicts
2. Builds a lookup by parcel_id (+ source_url fallback)
3. Loads the restored 53,851-board (from commit 342c07f) via load_board
4. For each listing in 53,851, if match found in 38,108: copy its raw dict
   (which has all title search results + red flags)
5. Saves via write_artifact() — the CORRECT save function that writes
   listings.json, listings_detail.json, and all derivatives
"""
import gc, json, os, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("PATH", os.path.expanduser("~/bin") + ":" + os.environ.get("PATH", ""))

from foreclosure_scraper.web_artifact import load_board, write_artifact, read_board_records

DOCS = REPO / "docs"

# Fields added by title search pipeline (copy from 38k board to 53k board)
TITLE_SEARCH_FIELDS = {
    "deed_chain", "title_risk", "life_events", "tax_owed", "eviction_market",
    "vacant_lot", "liens", "courtlistener", "bankruptcy", "bankruptcy_prop",
    "courts", "incarceration", "code_enforcement", "storm_damage",
    "usps_vacancy", "sos_dissolution", "fema_repetitive_loss", "septic",
    "derived_signals", "strategy_fit", "distress_stack", "signal_stack",
    "relationship_signal", "bankruptcy_stay", "upset_bid", "rod_docs",
    "sc_tax_delinquent", "nc_ptscloud_delinquent_tax", "divorce",
    "condemned", "owner_mismatch", "owner_mailing", "skip_trace",
    "loan_amount", "red_flags",
}


def main():
    t0 = time.time()

    # ── Step 1: Load the 38,108-board from the current docs/ (still has
    #    the title search results from the last push)
    print("Step 1: Loading 38,108-board (title search results)...", flush=True)
    enriched_records = read_board_records(DOCS)
    print(f"  Loaded {len(enriched_records)} enriched records", flush=True)

    # ── Step 2: Build lookup by parcel_id + source_url
    print("Step 2: Building lookup...", flush=True)
    by_parcel = {}
    by_url = {}
    for rec in enriched_records:
        pid = rec.get("parcel_id")
        if pid:
            by_parcel[pid] = rec
        url = rec.get("source_url")
        if url:
            by_url[url] = rec
    print(f"  Lookup: {len(by_parcel)} by parcel_id, {len(by_url)} by source_url", flush=True)

    # Free the list (we have the dicts in the lookup)
    del enriched_records
    gc.collect()

    # ── Step 3: Restore the 53,851 board from git commit 342c07f
    print("Step 3: Restoring 53,851-board from commit 342c07f...", flush=True)
    import subprocess
    # Write restored files to a temp dir
    tmp_dir = Path("/tmp/board_restore")
    tmp_dir.mkdir(exist_ok=True)

    # Extract the 53,851 board from git
    gz_path = tmp_dir / "listings.json.gz"
    detail_gz_path = tmp_dir / "listings_detail.json.gz"

    subprocess.run(
        ["git", "show", "342c07f:docs/listings.json.gz"],
        stdout=open(gz_path, "wb"),
        cwd=str(REPO), check=True
    )
    subprocess.run(
        ["git", "show", "342c07f:docs/listings_detail.json.gz"],
        stdout=open(detail_gz_path, "wb"),
        cwd=str(REPO), check=True
    )

    # Copy to docs/ (overwrite the 38k board with the 53k board)
    import shutil
    shutil.copy(gz_path, DOCS / "listings.json.gz")
    shutil.copy(detail_gz_path, DOCS / "listings_detail.json.gz")

    # Decompress for load_board
    subprocess.run(["gunzip", "-kf", str(DOCS / "listings.json.gz")], check=True)
    subprocess.run(["gunzip", "-kf", str(DOCS / "listings_detail.json.gz")], check=True)

    # Clean up temp
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("  Restored 53,851 board to docs/", flush=True)

    # ── Step 4: Load the 53,851 board
    print("Step 4: Loading 53,851-board...", flush=True)
    board = load_board(DOCS)
    print(f"  Loaded {len(board)} listings", flush=True)

    # ── Step 5: Merge title search results
    print("Step 5: Merging title search results...", flush=True)
    matched = 0
    unmatched = 0
    for i, li in enumerate(board):
        pid = getattr(li, "parcel_id", None) or ""
        url = getattr(li, "source_url", None) or ""

        src = by_parcel.get(pid) or by_url.get(url)
        if src:
            matched += 1
            src_raw = src.get("raw", {})
            if isinstance(src_raw, dict) and src_raw:
                # Get current raw as dict
                if not isinstance(li.raw, dict):
                    li.raw = {}
                # Copy title search fields from the 38k board
                for field in TITLE_SEARCH_FIELDS:
                    if field in src_raw:
                        li.raw[field] = src_raw[field]
                # Also copy any top-level fields that might have been updated
                for field in ("amount_owed", "equity", "strategy_fit",
                              "distress_stack", "signal_stack", "derived_signals"):
                    if field in src_raw:
                        li.raw[field] = src_raw[field]
        else:
            unmatched += 1

        if (i + 1) % 10000 == 0:
            print(f"  ...{i+1}/{len(board)} ({matched} matched, {unmatched} unmatched)", flush=True)
            gc.collect()

    print(f"\n  Matched: {matched:,} ({matched/len(board)*100:.1f}%)")
    print(f"  Unmatched: {unmatched:,} (no title search data — will have equity only)")

    # Free lookup dicts
    del by_parcel, by_url
    gc.collect()

    # ── Step 6: Save with write_artifact (the CORRECT save function)
    print("\nStep 6: Saving with write_artifact()...", flush=True)
    write_artifact(board, {})
    print(f"  Done! Board saved with {len(board)} listings ({time.time()-t0:.1f}s total)")

    # ── Step 7: Verify
    print("\nStep 7: Verifying...", flush=True)
    board2 = load_board(DOCS)
    print(f"  Reloaded: {len(board2)} listings (should be {len(board)})")

    # Check a few title search fields
    has_deed = sum(1 for li in board2 if isinstance(li.raw, dict) and li.raw.get("deed_chain"))
    has_flags = sum(1 for li in board2 if isinstance(li.raw, dict) and li.raw.get("red_flags"))
    has_equity = sum(1 for li in board2 if isinstance(li.raw, dict) and li.raw.get("equity"))
    print(f"  deed_chain: {has_deed:,}")
    print(f"  red_flags: {has_flags:,}")
    print(f"  equity: {has_equity:,}")


if __name__ == "__main__":
    main()
