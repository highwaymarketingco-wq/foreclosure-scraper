"""Constant-memory, read-only iteration over the published board.

load_board() builds every row as a Listing: measured 2026-09-18 at ~2.8GB peak
RSS for the 170,588-row board, on an 8GB Mac. Read-only probes that only need
to count or sample fields do not need that. This yields the raw JSON dict for
each row one at a time (~295MB peak measured, ~7s for the full board).

Since the payload split (audit O1) the published board is a set of gzipped JSON-array PARTS,
docs/listings_part_NNN.json.gz (see board_parts.py). `iter_board_rows` still takes the path the
old single file lived at (docs/listings.json.gz, which ~25 scripts name): when that directory
holds a parts board, the parts are streamed in order, verified against docs/board.manifest.json
first; otherwise the path is read as the single gzipped array it always was (a scratch board in
a temp dir, a pre-split checkout). Row order is the file order either way, so two boards can be
compared by position.

It sees exactly what is published in those files -- the slim listings, WITHOUT the
lazy-detail sidecar (comps, vision, cama, ...). For anything that needs those
keys, or any write, use web_artifact.load_board() as the only board process.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from . import board_parts

_CHUNK = 1 << 20


def iter_board_rows(path: Path | str = "docs/listings.json.gz") -> Iterator[dict]:
    """Yield each row of the board, holding only the current chunk in memory.

    `path` is docs/listings.json.gz (or docs/listings.json). If a parts board sits beside it the
    parts are read (in order, after a manifest check: BoardIntegrityError if they disagree);
    else `path` itself is read as one gzipped JSON array."""
    try:
        res = board_parts.resolve_source(path)
    except board_parts.UnlistedPartsError:
        # part files nobody lists (an interrupted first write, a migration mid-flight): a complete
        # single file at `path` is still the last consistent board
        if Path(path).is_file() and str(path).endswith(".gz"):
            res = None
        else:
            raise
    if res is not None:
        yield from board_parts.iter_rows(res.docs, res=res)
        return
    yield from board_parts.iter_gz_rows(path)
