#!/usr/bin/env python3
"""Streaming slim + shard builder — reads the board one row at a time.

Does NOT call write_artifact() because that needs list[Listing] in memory,
which OOMs the 24GB VM on a 3.9GB board. Instead, this script:

1. Streams docs/listings.json one JSON object at a time (same char-by-char
   parser as clean_board.py — no ijson dependency, no full load).
2. For each row dict, calls _project_slim_record() and _shard_record()
   directly — these are pure functions that take a dict and return a dict.
3. Writes listings_slim.json incrementally (one row at a time to a temp
   file, then renames).
4. Writes detail shards in batches of DETAIL_SHARD_SIZE to .json.gz files.

This produces the same slim file and shard structure as write_artifact(),
just without the board rewrite (the board is already written) and without
the prior-detail sidecar join (which is a cross-run optimization, not
required for the dashboard to function).
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
from pathlib import Path

# Setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("PYTHONPATH", "src")

from foreclosure_scraper.web_artifact import (
    _project_slim_record,
    _shard_record,
    DETAIL_SHARD_DIR,
    DETAIL_SHARD_SIZE,
)

BOARD_PATH = Path("docs/listings.json")
DOCS_DIR = Path("docs")
SLIM_PATH = DOCS_DIR / "listings_slim.json"
SLIM_GZ_PATH = DOCS_DIR / "listings_slim.json.gz"
SHARD_DIR = DOCS_DIR / DETAIL_SHARD_DIR


def _stream_json_array(path: Path):
    """Yield one dict at a time from a JSON array file, char by char.

    Same approach as clean_board.py — reads the file character by character,
    tracking brace depth to find object boundaries. Never loads the full
    file into memory.
    """
    buf = []
    depth = 0
    in_string = False
    escape = False
    count = 0
    t0 = time.monotonic()

    # Read in 256KB chunks but process char by char
    with open(path, "r", encoding="utf-8", errors="replace", buffering=262144) as f:
        # Skip whitespace to find opening '['
        ch = f.read(1)
        while ch and ch in " \t\n\r":
            ch = f.read(1)
        if ch != "[":
            raise ValueError(f"Expected '[' at start of file, got {ch!r}")

        while True:
            chunk = f.read(262144)
            if not chunk:
                break
            for ch in chunk:
                if in_string:
                    buf.append(ch)
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                    continue

                if ch == '"':
                    in_string = True
                    buf.append(ch)
                    continue

                if ch == "{":
                    if depth == 0:
                        # Start of a new object — begin accumulating
                        buf = ["{"]
                        depth = 1
                        continue
                    depth += 1
                    buf.append(ch)
                    continue

                if ch == "}":
                    depth -= 1
                    buf.append(ch)
                    if depth == 0:
                        # End of object — parse it
                        obj_str = "".join(buf)
                        try:
                            obj = json.loads(obj_str)
                            count += 1
                            if count % 50000 == 0:
                                elapsed = time.monotonic() - t0
                                rate = count / elapsed if elapsed > 0 else 0
                                print(f"  {count:>8,d} rows scanned | "
                                      f"{rate:.0f} rows/s | {elapsed:.0f}s",
                                      flush=True)
                            yield obj
                        except json.JSONDecodeError:
                            pass  # Skip malformed
                    continue

                if depth > 0:
                    buf.append(ch)
                    continue

                # depth == 0, outside any object
                if ch == "]":
                    # End of array
                    return
                # Ignore commas and whitespace between objects


def main():
    print("=" * 60)
    print("STREAMING SLIM + SHARD BUILDER")
    print(f"Board: {BOARD_PATH} ({BOARD_PATH.stat().st_size / 1e9:.2f} GB)")
    print(f"Output: {SLIM_PATH} + {SHARD_DIR}/")
    print("=" * 60)

    t0 = time.monotonic()

    # Prepare shard directory
    if SHARD_DIR.exists():
        import shutil
        shutil.rmtree(SHARD_DIR)
    SHARD_DIR.mkdir(parents=True, exist_ok=True)

    # Temp files
    slim_tmp = SLIM_PATH.with_suffix(".tmp")
    shard_buf: list[bytes] = []
    shard_idx = 0
    total = 0

    print("Streaming board and building slim + shards...")
    with open(slim_tmp, "wb") as slim_f:
        slim_f.write(b"[")
        first = True

        for rec in _stream_json_array(BOARD_PATH):
            total += 1

            # Write slim record
            slim_rec = _project_slim_record(rec)
            slim_bytes = json.dumps(
                slim_rec, ensure_ascii=False, default=str,
                separators=(",", ":")
            ).encode("utf-8")
            if not first:
                slim_f.write(b",")
            slim_f.write(slim_bytes)
            first = False

            # Write shard record
            # _shard_record takes (rec, det) — det is the sidecar dict.
            # We pass empty dict since we're not doing the prior-detail join.
            try:
                shard_rec = _shard_record(rec, {})
                shard_bytes = json.dumps(
                    shard_rec, ensure_ascii=False, default=str,
                    separators=(",", ":")
                ).encode("utf-8")
                shard_buf.append(shard_bytes)
            except Exception:
                # If shard record fails, use a minimal record
                shard_buf.append(json.dumps(
                    {"i": total - 1}, separators=(",", ":")
                ).encode("utf-8"))

            # Flush shard when full
            if len(shard_buf) >= DETAIL_SHARD_SIZE:
                name = f"{shard_idx:05d}.json.gz"
                shard_bytes = gzip.compress(
                    b"[" + b",".join(shard_buf) + b"]",
                    compresslevel=9, mtime=0
                )
                (SHARD_DIR / name).write_bytes(shard_bytes)
                shard_buf = []
                shard_idx += 1

            if total % 50000 == 0:
                elapsed = time.monotonic() - t0
                print(f"  {total:>8,d} rows | slim+shards building | "
                      f"{total/elapsed:.0f} rows/s | {elapsed:.0f}s",
                      flush=True)

        # Write final partial shard
        if shard_buf:
            name = f"{shard_idx:05d}.json.gz"
            shard_bytes = gzip.compress(
                b"[" + b",".join(shard_buf) + b"]",
                compresslevel=9, mtime=0
            )
            (SHARD_DIR / name).write_bytes(shard_bytes)

        slim_f.write(b"]")

    # Rename slim temp to final
    slim_tmp.rename(SLIM_PATH)

    # Write gzipped slim
    print("Compressing slim file...")
    with open(SLIM_PATH, "rb") as f_in:
        with gzip.open(SLIM_GZ_PATH, "wb", compresslevel=9) as f_out:
            shutil_copy = f_out.write(f_in.read())
    # Reset mtime for reproducibility
    import shutil as _shutil
    # Read back and re-write with mtime=0
    with open(SLIM_GZ_PATH, "rb") as f:
        data = f.read()
    with open(SLIM_GZ_PATH, "wb") as f:
        f.write(gzip.compress(
            open(SLIM_PATH, "rb").read(),
            compresslevel=9, mtime=0
        ))

    elapsed = time.monotonic() - t0
    slim_size = SLIM_PATH.stat().st_size / 1e6
    slim_gz_size = SLIM_GZ_PATH.stat().st_size / 1e6
    n_shards = len(list(SHARD_DIR.glob("*.json.gz")))

    print()
    print("=" * 60)
    print(f"DONE in {elapsed:.0f}s")
    print(f"  Total rows:      {total:,}")
    print(f"  Slim file:       {SLIM_PATH} ({slim_size:.1f} MB)")
    print(f"  Slim gzip:       {SLIM_GZ_PATH} ({slim_gz_size:.1f} MB)")
    print(f"  Detail shards:   {SHARD_DIR} ({n_shards} files)")
    print("=" * 60)

    # Write marker for watchdog
    marker = Path("data/shards_rebuild_done.txt")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(time.time()))

    print(f"Marker written: {marker}")


if __name__ == "__main__":
    main()
