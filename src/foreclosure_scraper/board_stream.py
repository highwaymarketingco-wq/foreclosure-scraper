"""Constant-memory, read-only iteration over the published board.

load_board() builds every row as a Listing: measured 2026-09-18 at ~2.8GB peak
RSS for the 170,588-row board, on an 8GB Mac. Read-only probes that only need
to count or sample fields do not need that. This yields the raw JSON dict for
each row one at a time (~295MB peak measured, ~7s for the full board) from
docs/listings.json.gz.

It sees exactly what is published in that file -- the slim listings, WITHOUT the
lazy-detail sidecar (comps, vision, cama, ...). For anything that needs those
keys, or any write, use web_artifact.load_board() as the only board process.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Iterator

_CHUNK = 1 << 20


def iter_board_rows(path: Path | str = "docs/listings.json.gz") -> Iterator[dict]:
    """Yield each row of a gzipped JSON array of objects, holding only the
    current chunk in memory. Row order matches the file, so two boards can be
    compared by position."""
    dec = json.JSONDecoder()
    buf = ""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        while True:
            chunk = f.read(_CHUNK)
            if chunk:
                buf += chunk
            elif not buf.strip():
                return
            i = 0
            while True:
                while i < len(buf) and buf[i] in " \n\r\t,[":
                    i += 1
                if i >= len(buf) or buf[i] == "]":
                    break
                try:
                    obj, j = dec.raw_decode(buf, i)
                except ValueError:
                    break                      # object continues in the next chunk
                yield obj
                i = j
            buf = buf[i:]
            if not chunk:
                return
