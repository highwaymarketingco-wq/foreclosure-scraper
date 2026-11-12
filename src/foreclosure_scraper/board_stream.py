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
lazy-detail sidecar (comps, vision, cama, ...). iter_board_rows_with_detail() streams the
index-aligned sidecar (docs/listings_detail.json(.gz)) in lockstep and merges only the detail
keys the caller names (e.g. the comps verifier's "comps"), still one row at a time and still
read-only. For a write, use web_artifact.load_board() as the only board process.
"""
from __future__ import annotations

import itertools
from pathlib import Path
from typing import Iterable, Iterator

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


DETAIL_NAME = "listings_detail.json"


def detail_source(docs: Path | str) -> Path:
    """The lazy-detail sidecar file to read beside the board in `docs`: the gzipped one, else
    the plain one. When the manifest lists the file, its size and sha256 must match (a plain
    twin left by an older write does not), and the manifest's detail_count must equal its
    count; otherwise BoardIntegrityError. FileNotFoundError when there is no sidecar."""
    docs = Path(docs)
    man = board_parts.read_manifest(docs)
    files = (man or {}).get("files") or {}
    if man and man.get("detail_count") is not None and man.get("count") is not None \
            and man["detail_count"] != man["count"]:
        raise board_parts.BoardIntegrityError(
            f"manifest detail_count {man['detail_count']} != count {man['count']}")
    why = []
    for name in (DETAIL_NAME + ".gz", DETAIL_NAME):
        p = docs / name
        if not p.is_file():
            continue
        entry = files.get(name)
        if not man or not entry:
            if not man:
                return p
            why.append(f"{name}: not in the manifest")
            continue
        if entry.get("bytes") is not None and p.stat().st_size != entry["bytes"]:
            why.append(f"{name}: size {p.stat().st_size} != manifest {entry['bytes']}")
            continue
        if entry.get("sha256") and board_parts.sha256_file(p) != entry["sha256"]:
            why.append(f"{name}: sha256 differs from the manifest")
            continue
        return p
    if why:
        raise board_parts.BoardIntegrityError("no detail sidecar matches the manifest: "
                                              + "; ".join(why))
    raise FileNotFoundError(f"no {DETAIL_NAME}(.gz) in {docs}")


_MISSING = object()


def iter_board_rows_with_detail(path: Path | str = "docs/listings.json.gz",
                                keys: Iterable[str] = ()) -> Iterator[dict]:
    """iter_board_rows(path), with the named lazy-detail keys (e.g. ("comps",)) merged into each
    row's raw from the index-aligned sidecar beside it (detail_source()). Both files are
    streamed together, one row at a time; only `keys` are copied, so a row costs what its
    own detail costs. No keys: exactly iter_board_rows(). A sidecar with a different row count
    is a mixed board: BoardIntegrityError when the shorter stream ends."""
    keys = tuple(k for k in keys if k)
    if not keys:
        yield from iter_board_rows(path)
        return
    src = detail_source(Path(path).parent)
    details = (board_parts.iter_gz_rows(src) if src.name.endswith(".gz")
               else board_parts.iter_plain_rows(src))
    n = 0
    for rec, det in itertools.zip_longest(iter_board_rows(path), details, fillvalue=_MISSING):
        if rec is _MISSING or det is _MISSING:
            raise board_parts.BoardIntegrityError(
                f"{src.name} is not index-aligned with the board: one ends at row {n}")
        if isinstance(det, dict) and isinstance(rec, dict):
            picked = {k: det[k] for k in keys if k in det}
            if picked:
                raw = rec.get("raw")
                if not isinstance(raw, dict):
                    raw = rec["raw"] = {}
                raw.update(picked)
        yield rec
        n += 1
