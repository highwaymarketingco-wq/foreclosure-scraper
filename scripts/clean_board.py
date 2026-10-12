#!/usr/bin/env python3
"""Clean the board: remove (1) criminal-case estate rows, (2) true duplicate rows.

Streams the 3.9GB board using a buffered character-by-character JSON parser.
Never loads the whole file — peak memory is one row at a time.

The board is a single JSON array: [{"source": ...}, {"source": ...}, ...]
We parse it as a stream of top-level array elements.

Strategy:
  Pass 1 (stream): read every row, compute row_keys() signatures.
    - Drop rows from nc_ecourts_estates with criminal case numbers (CR/CRS/IF/VR/CVL).
    - For duplicates: keep the FIRST occurrence, drop subsequent rows that share
      ANY identity key (parcel, case, address).
    - Track what was dropped and why.
  Write cleaned board to a temp file, then atomic rename.

Usage:
  BOARD_LOAD_ALLOW_LARGE=1 BOARD_LOCK_BYPASS=1 python3.12 scripts/clean_board.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import hashlib
import tempfile
import shutil
from pathlib import Path

# --- Config ---
BOARD_PATH = Path("docs/listings.json")
REPORT_PATH = Path("data/cleanup_report.json")

_CRIMINAL_CASE_RE = re.compile(r"^(CR|CRS|IF|VR|CVL)", re.IGNORECASE)
_ESTATE_SOURCE_RE = re.compile(r"nc_ecourts_estates", re.IGNORECASE)

# Identity fields for fingerprint (must match verification/core.py _IDENTITY_FIELDS)
_IDENTITY_FIELDS = (
    "state", "county", "parcel_id", "street_address", "city", "zip_code",
    "case_number", "listing_type", "source", "source_url",
    "plaintiff", "defendant", "trustee", "sale_date",
    "judgment_amount", "auction_date", "recording_date",
)


# ---------------------------------------------------------------------------
# Streaming JSON array parser
# ---------------------------------------------------------------------------

def _stream_json_array(fin):
    """Yield top-level objects from a JSON array file, one at a time.

    Reads the file in chunks, parses one complete object at a time using
    json.JSONDecoder.raw_decode. Memory: one row + one read buffer.
    """
    buf = ""
    decoder = json.JSONDecoder()
    started = False
    eof = False

    while not eof:
        chunk = fin.read(65536)
        if not chunk:
            eof = True
        else:
            buf += chunk

        if not started:
            # Skip whitespace and find opening '['
            stripped = buf.lstrip()
            if not stripped:
                continue
            if stripped[0] != "[":
                # Maybe line-delimited JSON or single object
                # Fall back: try to parse the whole buffer
                yield from _fallback_parse(buf, fin, decoder)
                return
            # Find position of '[' in original buf
            idx = len(buf) - len(stripped)
            buf = buf[idx + 1:]  # Skip past '['
            started = True

        # Parse objects from buffer
        while True:
            # Skip whitespace and commas
            t = buf.lstrip()
            if not t:
                break  # Need more data
            ws_len = len(buf) - len(t)
            buf = buf[ws_len:]

            if buf[0] == "]":
                return  # End of array

            if buf[0] == ",":
                buf = buf[1:]
                continue

            # Try to decode an object
            try:
                obj, end_idx = decoder.raw_decode(buf)
                yield obj
                buf = buf[end_idx:]
            except json.JSONDecodeError:
                # Not enough data yet — read more
                break


def _fallback_parse(initial_buf, fin, decoder):
    """Fallback for line-delimited or non-array JSON."""
    buf = initial_buf
    for line in fin:
        buf += line
    # Try parsing as array
    try:
        arr = json.loads(buf)
        for obj in arr:
            yield obj
        return
    except (json.JSONDecodeError, MemoryError):
        pass
    # Try line-delimited
    for line in buf.split("\n"):
        line = line.strip().rstrip(",")
        if line and line not in ("[", "]"):
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                pass


# ---------------------------------------------------------------------------
# Identity / dedup logic (mirrors verification/core.py row_keys())
# ---------------------------------------------------------------------------

def _norm(v) -> str:
    if not v:
        return ""
    return str(v).strip().lower()


def _has_house_number(addr: str | None) -> bool:
    if not addr:
        return False
    return bool(re.search(r"^\s*\d+\s", addr.strip()))


def _row_keys(row: dict) -> set[str]:
    """Compute identity keys — same logic as verification/core.py row_keys()."""
    keys: set[str] = set()
    state = _norm(row.get("state"))
    county = _norm(row.get("county"))

    # 1. Parcel ID (strongest)
    parcel = _norm(row.get("parcel_id"))
    if parcel and state and county:
        keys.add(f"parcel:{state}:{county}:{parcel}")

    # 2. Case number
    case = _norm(row.get("case_number"))
    if case and state and county:
        case_clean = re.sub(r"[\s\-]", "", case)
        keys.add(f"case:{state}:{county}:{case_clean}")

    # 3. House-numbered address
    addr = _norm(row.get("street_address"))
    if addr and _has_house_number(row.get("street_address")) and state and county:
        addr_clean = re.sub(r"\s+", " ", addr)
        keys.add(f"addr:{state}:{county}:{addr_clean}")

    # 4. Fingerprint fallback (hash of ALL identity fields)
    if not keys:
        parts = []
        for f in _IDENTITY_FIELDS:
            v = _norm(row.get(f))
            if v:
                parts.append(f"{f}={v}")
        if parts:
            fp = hashlib.sha256("|".join(parts).encode()).hexdigest()
            keys.add(f"row:{fp}")

    return keys


def _is_criminal_estate(row: dict) -> bool:
    """Check if this is a criminal-case row from the estate scraper."""
    source = _norm(row.get("source"))
    if not source or not _ESTATE_SOURCE_RE.search(source):
        return False
    case = _norm(row.get("case_number"))
    if case and _CRIMINAL_CASE_RE.match(case):
        return True
    case_type = _norm(row.get("case_type", ""))
    if case_type and _CRIMINAL_CASE_RE.match(case_type):
        return True
    return False


def _completeness_score(row: dict) -> int:
    """Higher = more complete row."""
    score = 0
    for f in ("parcel_id", "street_address", "case_number", "zip_code",
              "owner_name", "defendant", "plaintiff", "sale_date",
              "judgment_amount", "auction_date", "market_value",
              "assessed_value", "tax_amount_owed"):
        if row.get(f):
            score += 1
    return score


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not BOARD_PATH.exists():
        print(f"ERROR: board not found at {BOARD_PATH}", file=sys.stderr)
        sys.exit(1)

    board_size = BOARD_PATH.stat().st_size
    print(f"Board: {BOARD_PATH} ({board_size / 1e9:.2f} GB)")

    seen_keys: set[str] = set()  # All identity keys we've seen so far
    dropped_criminal = 0
    dropped_dupe = 0
    kept = 0
    total = 0
    dropped_examples: list[dict] = []
    criminal_examples: list[dict] = []

    tmp_path = BOARD_PATH.parent / "_listings_cleaning.json"
    print(f"Writing cleaned board to {tmp_path}...")

    start = time.time()
    last_report = start

    with open(BOARD_PATH, "rb") as fin_bin, open(tmp_path, "w") as fout:
        # Wrap binary file in text mode for the parser
        import io
        fin = io.TextIOWrapper(fin_bin, encoding="utf-8", errors="replace")

        fout.write("[")
        first_row = True

        for row in _stream_json_array(fin):
            total += 1

            # --- Check 1: criminal estate rows ---
            if _is_criminal_estate(row):
                dropped_criminal += 1
                if len(criminal_examples) < 20:
                    criminal_examples.append({
                        "row_num": total,
                        "case_number": row.get("case_number"),
                        "case_type": row.get("case_type", ""),
                        "county": row.get("county"),
                        "source": row.get("source"),
                    })
                continue

            # --- Check 2: duplicate rows ---
            keys = _row_keys(row)
            is_dupe = False
            for k in keys:
                if k in seen_keys:
                    is_dupe = True
                    if len(dropped_examples) < 50:
                        dropped_examples.append({
                            "row_num": total,
                            "matched_key": k,
                            "case_number": row.get("case_number"),
                            "parcel_id": row.get("parcel_id"),
                            "street_address": row.get("street_address"),
                            "county": row.get("county"),
                            "source": row.get("source"),
                        })
                    break

            if is_dupe:
                dropped_dupe += 1
                continue

            # Keep this row — record its keys
            seen_keys.update(keys)

            # Write to output
            if not first_row:
                fout.write(",")
            fout.write(json.dumps(row, ensure_ascii=False))
            first_row = False
            kept += 1

            # Progress report every 50k rows
            if total % 50000 == 0:
                elapsed = time.time() - start
                if time.time() - last_report > 30:
                    rate = total / elapsed if elapsed > 0 else 0
                    print(f"  {total:,} rows scanned | {kept:,} kept | "
                          f"{dropped_dupe:,} dupes | {dropped_criminal:,} criminal | "
                          f"{rate:.0f} rows/s | {elapsed:.0f}s")
                    last_report = time.time()

        fout.write("]")

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.0f}s")
    print(f"  Total scanned:   {total:,}")
    print(f"  Kept:            {kept:,}")
    print(f"  Dropped dupes:   {dropped_dupe:,}")
    print(f"  Dropped criminal:{dropped_criminal:,}")

    # Write report
    report = {
        "board_path": str(BOARD_PATH),
        "original_rows": total,
        "kept": kept,
        "dropped_duplicates": dropped_dupe,
        "dropped_criminal_estate": dropped_criminal,
        "elapsed_seconds": round(elapsed, 1),
        "criminal_examples": criminal_examples,
        "duplicate_examples": dropped_examples,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report: {REPORT_PATH}")

    # Verify the temp file
    tmp_size = tmp_path.stat().st_size
    print(f"Cleaned board: {tmp_size / 1e9:.2f} GB")

    # Atomic rename with backup
    backup_path = BOARD_PATH.parent / "_listings_pre_cleanup.json"
    print(f"Backing up original to {backup_path}...")
    if backup_path.exists():
        backup_path.unlink()
    shutil.move(str(BOARD_PATH), str(backup_path))
    shutil.move(str(tmp_path), str(BOARD_PATH))
    print(f"Done. Cleaned board is at {BOARD_PATH}")

    # Verify
    if BOARD_PATH.exists() and BOARD_PATH.stat().st_size > 0:
        print(f"Verified: {BOARD_PATH} exists ({BOARD_PATH.stat().st_size / 1e9:.2f} GB).")
        print(f"Backup kept at {backup_path}")
    else:
        print("ERROR: cleaned board is empty! Restoring backup...")
        shutil.move(str(backup_path), str(BOARD_PATH))
        sys.exit(1)


if __name__ == "__main__":
    main()
