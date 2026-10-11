#!/usr/bin/env python3
"""Wire walled_output data into the main board (docs/listings.json).

Reads all *_data.json files from data/walled_output/, converts each listing
dict to a Listing object, deduplicates against the existing board using
dedupe_key(), and writes the merged board via write_artifact().

MUST be run via scripts/with_board_lock.sh:
    scripts/with_board_lock.sh wire_walled -- .venv/bin/python scripts/wire_walled_to_board.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure src is on the path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Load .env (no python-dotenv)
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.web_artifact import load_board, write_artifact

WALLED_DIR = ROOT / "data" / "walled_output"


def _parse_listing_type(s: str) -> ListingType:
    """Parse 'ListingType.TAX_LIEN' or 'tax_lien' into a ListingType enum."""
    if not s:
        return ListingType.UNKNOWN
    # Strip "ListingType." prefix if present
    name = s.replace("ListingType.", "").strip()
    # Try by value first (e.g. "tax_lien")
    try:
        return ListingType(name)
    except ValueError:
        pass
    # Try by name (e.g. "TAX_LIEN")
    try:
        return ListingType[name]
    except KeyError:
        pass
    return ListingType.UNKNOWN


def _convert_walled_row(row: dict) -> Listing | None:
    """Convert a walled_output listing dict to a Listing object.

    The runner's _listing_to_dict produces:
      owner_name, address, city, state, zip, listing_type, source, raw_keys
    """
    source = row.get("source", "walled_unknown")
    owner = row.get("owner_name") or None
    addr = row.get("address") or None
    city = row.get("city") or None
    state = row.get("state") or None
    zip_code = row.get("zip") or None
    lt = _parse_listing_type(row.get("listing_type", ""))

    # Build raw dict from raw_keys if present
    raw_keys = row.get("raw_keys") or []
    raw = {k: True for k in raw_keys} if raw_keys else {}
    # Store the original source slug
    raw["walled_source"] = source

    now = datetime.now(timezone.utc)

    li = Listing(
        source=source,
        source_url=f"walled://{source}",
        listing_type=lt,
        property_kind=PropertyKind.UNKNOWN,
        street_address=addr,
        city=city,
        state=state,
        zip_code=zip_code,
        owner_name=owner,
        first_seen=now,
        last_seen=now,
        raw=raw,
    )
    return li


def main():
    docs_dir = ROOT / "docs"

    # 1. Load existing board
    print("Loading existing board...", flush=True)
    board = load_board(docs_dir)
    print(f"  Existing board: {len(board)} listings", flush=True)

    # Build dedupe index from existing board: key → index in board
    board_keys: dict[str, int] = {}
    for i, li in enumerate(board):
        k = li.dedupe_key()
        if k:
            board_keys[k] = i

    # Track keys of new listings to avoid intra-walled dupes
    new_keys: set[str] = set()

    # 2. Load all walled output
    print(f"Loading walled output from {WALLED_DIR}...", flush=True)
    new_listings: list[Listing] = []
    skipped_dupes = 0
    skipped_invalid = 0

    for f in sorted(WALLED_DIR.glob("*_data.json")):
        with open(f) as fh:
            data = json.load(fh)
        slug = data.get("slug", f.stem)
        listings = data.get("listings", [])
        print(f"  {f.name}: {len(listings)} rows", flush=True)

        for row in listings:
            li = _convert_walled_row(row)
            if li is None:
                skipped_invalid += 1
                continue

            k = li.dedupe_key()

            # Check if duplicate of existing board listing
            if k and k in board_keys:
                idx = board_keys[k]
                if idx < len(board):
                    board[idx].last_seen = li.last_seen
                skipped_dupes += 1
                continue

            # Check if duplicate of a new listing we just added
            if k and k in new_keys:
                skipped_dupes += 1
                continue

            # New listing
            new_listings.append(li)
            if k:
                new_keys.add(k)

    print(f"\n  New listings to add: {len(new_listings)}", flush=True)
    print(f"  Duplicates (last_seen updated): {skipped_dupes}", flush=True)
    print(f"  Invalid (skipped): {skipped_invalid}", flush=True)

    if not new_listings:
        print("No new listings to add. Exiting.", flush=True)
        return

    # 3. Merge: board + new_listings
    merged = board + new_listings
    print(f"  Merged board: {len(merged)} listings", flush=True)

    # 4. Write via write_artifact (requires board lock)
    print("Writing board via write_artifact()...", flush=True)
    summary = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "wire_walled_to_board.py",
        "total_listings": len(merged),
        "new_from_walled": len(new_listings),
        "duplicates_updated": skipped_dupes,
    }
    try:
        paths = write_artifact(merged, summary, docs_dir)
        print(f"  Written: {paths[0]}", flush=True)
        print(f"  Meta:    {paths[1]}", flush=True)
        print(f"\nDone! Board now has {len(merged)} listings.", flush=True)
    except Exception as exc:
        print(f"  ERROR: {exc}", flush=True)
        raise


if __name__ == "__main__":
    main()
