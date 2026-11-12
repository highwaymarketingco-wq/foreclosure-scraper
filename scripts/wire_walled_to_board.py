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
from foreclosure_scraper.verification.core import row_keys
from foreclosure_scraper.web_artifact import append_new_rows, write_artifact

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

    run_walled_sources.py now serializes the full Pydantic model via
    model_dump(), so every Listing field is present in the dict.  We
    reconstruct the Listing from those fields directly instead of hand-
    picking a few and renaming them (the old code read ``address``/``zip``
    which don't exist on Listing, so every row got None and dedupe_key()
    collapsed to ``url:walled://<source>``).
    """
    # If the row is a full model_dump, we can validate directly.
    # Strip fields that need type conversion.
    clean = {k: v for k, v in row.items() if k not in ("raw_keys",)}
    # raw was kept as a dict in the serialized form
    if "raw" not in clean:
        clean["raw"] = {}
    # walled_source tag
    source = clean.get("source", "walled_unknown")
    clean.setdefault("source", source)
    # Ensure source_url exists — dedupe_key() falls back to it.
    if not clean.get("source_url"):
        clean["source_url"] = f"walled://{source}"

    # Parse listing_type back from string if needed
    lt = clean.get("listing_type")
    if isinstance(lt, str):
        clean["listing_type"] = _parse_listing_type(lt)
    elif lt is None:
        clean["listing_type"] = ListingType.UNKNOWN

    # Parse property_kind
    pk = clean.get("property_kind")
    if isinstance(pk, str):
        try:
            clean["property_kind"] = PropertyKind(pk)
        except (ValueError, KeyError):
            clean["property_kind"] = PropertyKind.UNKNOWN
    elif pk is None:
        clean["property_kind"] = PropertyKind.UNKNOWN

    # Parse datetime fields
    for dt_field in ("sale_date", "upset_bid_deadline", "redemption_deadline",
                      "first_seen", "last_seen"):
        v = clean.get(dt_field)
        if isinstance(v, str) and v:
            try:
                clean[dt_field] = datetime.fromisoformat(v)
            except ValueError:
                clean[dt_field] = None
        elif v is None:
            if dt_field in ("first_seen", "last_seen"):
                clean[dt_field] = datetime.now(timezone.utc)
            else:
                clean[dt_field] = None

    try:
        li = Listing.model_validate(clean)
    except Exception:
        # Fallback: construct with just the identity fields
        li = Listing(
            source=source,
            source_url=clean.get("source_url", f"walled://{source}"),
            listing_type=clean.get("listing_type", ListingType.UNKNOWN),
            property_kind=clean.get("property_kind", PropertyKind.UNKNOWN),
            street_address=clean.get("street_address"),
            city=clean.get("city"),
            state=clean.get("state"),
            zip_code=clean.get("zip_code"),
            county=clean.get("county"),
            parcel_id=clean.get("parcel_id"),
            case_number=clean.get("case_number"),
            owner_name=clean.get("owner_name"),
            plaintiff=clean.get("plaintiff"),
            defendant=clean.get("defendant"),
            raw=clean.get("raw", {}),
        )
    return li


def main():
    docs_dir = ROOT / "docs"

    # 1. Load all walled output into Listing objects (this is small — tens of
    #    thousands of rows, not the 3.9 GB board).  Deduplicate within the
    #    walled set using row_keys().
    print(f"Loading walled output from {WALLED_DIR}...", flush=True)
    new_listings: list[Listing] = []
    new_keys: set[str] = set()
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

            keys = row_keys(li)

            # Check if duplicate of a listing we already added
            if any(k in new_keys for k in keys):
                skipped_dupes += 1
                continue

            new_listings.append(li)
            new_keys.update(keys)

    print(f"\n  New listings to add: {len(new_listings)}", flush=True)
    print(f"  Duplicates within walled set: {skipped_dupes}", flush=True)
    print(f"  Invalid (skipped): {skipped_invalid}", flush=True)

    if not new_listings:
        print("No new listings to add. Exiting.", flush=True)
        return

    # 2. Append to board using append_new_rows() which STREAMS the existing
    #    board from disk — never loads the full 3.9 GB into memory.  It
    #    deduplicates against existing board rows using the same row_keys()
    #    signatures during a single streaming pass.
    print(f"Appending {len(new_listings)} listings to board (streaming)...", flush=True)
    summary = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "wire_walled_to_board.py",
        "new_from_walled": len(new_listings),
        "duplicates_within_walled": skipped_dupes,
        "invalid_skipped": skipped_invalid,
    }
    try:
        result = append_new_rows(new_listings, summary, docs_dir)
        print(f"  Result: {result}", flush=True)
        print(f"\nDone! Appended {len(new_listings)} listings to board.", flush=True)
    except Exception as exc:
        print(f"  ERROR: {exc}", flush=True)
        raise


if __name__ == "__main__":
    main()
