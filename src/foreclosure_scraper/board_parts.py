"""The published board as N independently gzipped JSON-array PARTS (audit O1).

WHY. docs/listings.json.gz was one gzip of a 170k-row JSON array: 84 MiB on 2026-09-21,
growing 2 to 4 MiB a day, against GitHub's hard 100 MiB per-file limit and the 95 MiB
pre-commit gate (scripts/git_size_gate.sh). Nothing about the board needs it to be one file,
so it is now published as contiguous slices of the same array:

    docs/listings_part_000.json.gz  rows [0, n0)
    docs/listings_part_001.json.gz  rows [n0, n0 + n1)
    ...

Each part is its own gzip of a complete JSON array (`[row, row, ...]`), so any single part
is a valid board slice, and concatenating the parts' arrays IN NAME ORDER gives exactly the
array the single file held. Row ORDER is the contract: index i is the join key across
listings, listings_detail, listings_slim and detail_shards, and a part boundary must never
move a row. Every part stays under PART_MAX_BYTES (24 MiB, so each also fits Cloudflare's
25 MiB per-asset cap); the writer chooses how many rows go in a part from the measured
compression ratio and re-cuts a part that comes out oversized, so a growing board makes
MORE parts, never a bigger one.

THE LIST OF PARTS IS RECORDED TWICE, both times with size and sha256 per part:
  * docs/board.manifest.json  "parts" block (sealed LAST by write_artifact; Python readers
    verify against it, and a part set that disagrees with it is refused: BoardIntegrityError)
  * docs/run_meta.json        "board_parts" block (the dashboard reads this one, with the same
    ?t=<run_time> cache key it uses for every payload file)

NAMING. `listings_part_NNN.json.gz` is deliberate. Jekyll's exclude/include are PREFIX
matches (docs/OPERATIONS.md section 4): `listings.json`, `listings_detail.json` and
`listings_slim.json` are excluded from the Pages build, and none of them is a prefix of
`listings_part_...`, so the parts publish without an `include` line. The Worker allowlist
matches `^/listings_part_\\d{3,4}\\.json\\.gz$` exactly.

This module is STDLIB ONLY and Python 3.9 compatible, and imports nothing from the package:
scripts/check_pages_publish.py, check_payload_size.py, check_staged_parts.py and job_watch.py
run under a bare /usr/bin/python3 (a pre-commit hook, launchd, the Pages workflow before any
`uv sync`) and load it by file path. It is also the one place the rest of the repo asks
"which files make up the board and are they all from the same write?".
"""
from __future__ import annotations

import gzip
import hashlib
import io
import itertools
import json
import os
import re
import sys
from collections import deque
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence

PARTS_SCHEMA = "board-parts-v1"
PART_PREFIX = "listings_part_"
PART_SUFFIX = ".json.gz"
PART_NAME_RE = re.compile(r"^listings_part_(\d{3,})\.json\.gz$")

MANIFEST_NAME = "board.manifest.json"
MANIFEST_SCHEMA = "board-manifest-v1"

DEFAULT_PART_MAX_BYTES = 24 * 1024 * 1024
# Read at call time by every function below (never `from board_parts import PART_MAX_BYTES`):
# tests, and an operator in an emergency, override it with BOARD_PART_MAX_BYTES or by
# assigning this attribute.
PART_MAX_BYTES = int(os.environ.get("BOARD_PART_MAX_BYTES") or DEFAULT_PART_MAX_BYTES)

# Aim each part at this fraction of the cap. Part size drifts with the data (a dense region
# compresses worse than the average), so the headroom is what keeps a normal write from
# tripping the re-cut path.
TARGET_FILL = 0.80
# Keep the previous write's rows-per-part while the estimate says it is still within this band:
# stable boundaries mean a change confined to some rows rewrites only the parts holding them
# (git stores a part that did not change once, not once per publish).
KEEP_HINT_LOW = 0.75
KEEP_HINT_HIGH = 1.20
ROW_QUANTUM = 500              # round estimated rows-per-part down to a multiple of this
SAMPLE_CHUNKS = 6              # contiguous chunks compressed to measure the ratio
SAMPLE_CHUNK_ROWS = 400
STREAM_SAMPLE_ROWS = 2400      # rows buffered first when the source is an iterator

_READ_CHUNK = 1 << 20


class BoardIntegrityError(RuntimeError):
    """A board file on disk does not match its manifest (torn or mixed write)."""


class UnlistedPartsError(BoardIntegrityError):
    """Part files are on disk but no manifest or run_meta listing names them: an interrupted first
    write (or a migration mid-flight). A caller holding a complete single-file board falls back
    to it; everyone else refuses."""


class PartTooLargeError(RuntimeError):
    """One row alone compresses past the part cap: the cap or the row is wrong."""


def max_bytes() -> int:
    return int(PART_MAX_BYTES)


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------

def part_name(i: int) -> str:
    return "%s%03d%s" % (PART_PREFIX, i, PART_SUFFIX)


def part_index(name: str) -> Optional[int]:
    m = PART_NAME_RE.match(os.path.basename(str(name)))
    return int(m.group(1)) if m else None


def is_part_name(name: str) -> bool:
    return PART_NAME_RE.match(os.path.basename(str(name))) is not None


def list_part_files(docs) -> List[Path]:
    """The part files in docs/, in index order. Temp files and look-alikes are ignored."""
    docs = Path(docs)
    found = []
    try:
        for p in docs.iterdir():
            idx = part_index(p.name)
            if idx is not None and p.is_file():
                found.append((idx, p))
    except OSError:
        return []
    found.sort(key=lambda t: t[0])
    return [p for _, p in found]


# ---------------------------------------------------------------------------
# manifest access (a tiny reader: this module may not import web_artifact)
# ---------------------------------------------------------------------------

def _skip_manifest() -> bool:
    return os.environ.get("BOARD_MANIFEST_SKIP", "").strip().lower() in ("1", "true", "yes")


def read_manifest(docs) -> Optional[dict]:
    """The parsed manifest, or None when absent, unreadable, of an unknown schema, or when
    BOARD_MANIFEST_SKIP is set (the documented escape hatch)."""
    if _skip_manifest():
        return None
    try:
        man = json.loads((Path(docs) / MANIFEST_NAME).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(man, dict) or man.get("schema") != MANIFEST_SCHEMA:
        return None
    if not isinstance(man.get("files"), dict):
        return None
    return man


def manifest_parts_block(man) -> Optional[dict]:
    """The manifest's "parts" block, or None for a legacy (single-gz) manifest."""
    if not isinstance(man, dict):
        return None
    blk = man.get("parts")
    if isinstance(blk, dict) and blk.get("schema") == PARTS_SCHEMA and isinstance(blk.get("files"), list):
        return blk
    return None


def normalize_entries(block) -> List[dict]:
    """Validate a parts block (from the manifest OR run_meta) and return its entries.

    Each entry: name, start, end, records, bytes, sha256. Names must be part_000..part_{n-1},
    row ranges contiguous from 0, records == end - start, and the block's own count/records
    must agree with the list. A block that fails any of that is a corrupt manifest, and the
    right answer is a refusal, not a guess."""
    if not isinstance(block, dict) or not isinstance(block.get("files"), list):
        raise BoardIntegrityError("parts block is missing or malformed")
    out = []
    expect_start = 0
    for i, ent in enumerate(block["files"]):
        if not isinstance(ent, dict):
            raise BoardIntegrityError("parts block entry %d is not an object" % i)
        name = ent.get("name")
        if name != part_name(i):
            raise BoardIntegrityError("parts block entry %d is %r, expected %r (parts must be "
                                      "listed in order and contiguous)" % (i, name, part_name(i)))
        start, end, recs = ent.get("start"), ent.get("end"), ent.get("records")
        if not (isinstance(start, int) and isinstance(end, int) and isinstance(recs, int)):
            raise BoardIntegrityError("%s: start/end/records must be integers" % name)
        if start != expect_start or end < start or recs != end - start:
            raise BoardIntegrityError("%s: rows [%s, %s) records=%s do not continue from row %d"
                                      % (name, start, end, recs, expect_start))
        if not isinstance(ent.get("bytes"), int) or not ent.get("sha256"):
            raise BoardIntegrityError("%s: bytes and sha256 are required" % name)
        expect_start = end
        out.append({"name": name, "start": start, "end": end, "records": recs,
                    "bytes": ent["bytes"], "sha256": ent["sha256"]})
    if block.get("count") is not None and block["count"] != len(out):
        raise BoardIntegrityError("parts block says %s parts but lists %d" % (block["count"], len(out)))
    if block.get("records") is not None and block["records"] != expect_start:
        raise BoardIntegrityError("parts block says %s records but the parts cover %d"
                                  % (block["records"], expect_start))
    return out


def make_block(entries: Sequence[dict], *, rows_per_part: Optional[int] = None,
               cap: Optional[int] = None) -> dict:
    """The public description of a part set (manifest "parts" and run_meta "board_parts")."""
    files = [{"name": e["name"], "start": e["start"], "end": e["end"], "records": e["records"],
              "bytes": e["bytes"], "sha256": e["sha256"]} for e in entries]
    return {"schema": PARTS_SCHEMA, "count": len(files),
            "records": files[-1]["end"] if files else 0,
            "max_bytes": int(cap if cap is not None else max_bytes()),
            "rows_per_part": rows_per_part, "files": files}


# ---------------------------------------------------------------------------
# hashing and verification
# ---------------------------------------------------------------------------

def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as fh:
        while True:
            chunk = fh.read(8 * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# (resolved path, mtime_ns, size, sha) -> True once that file's sha256 matched. A process reads
# the same parts more than once (load, then the prior sidecar read inside write_artifact).
_VERIFIED: dict = {}


def check_entries(docs, entries: Sequence[dict], verify: bool = True) -> List[str]:
    """Problems (strings) between the parts on disk and `entries`. Empty means consistent.
    Size is always compared; sha256 only when `verify`."""
    docs = Path(docs)
    problems: List[str] = []
    for ent in entries:
        p = docs / ent["name"]
        try:
            st = p.stat()
        except OSError:
            problems.append("%s: missing" % ent["name"])
            continue
        if st.st_size != ent["bytes"]:
            problems.append("%s: size %d != manifest %d" % (ent["name"], st.st_size, ent["bytes"]))
            continue
        if not verify:
            continue
        key = (str(p.resolve()), st.st_mtime_ns, st.st_size, ent["sha256"])
        if key in _VERIFIED:
            continue
        got = sha256_file(p)
        if got != ent["sha256"]:
            problems.append("%s: sha256 %s != manifest %s" % (ent["name"], got[:12], ent["sha256"][:12]))
            continue
        _VERIFIED[key] = True
    return problems


def stray_parts(docs, entries: Sequence[dict]) -> List[str]:
    """Part files on disk that the parts list does not name (a stale higher-numbered part)."""
    named = set(e["name"] for e in entries)
    return [p.name for p in list_part_files(docs) if p.name not in named]


class Resolution(object):
    """Which part files make up the board in a docs directory, and how sure we are."""

    def __init__(self, docs, paths, entries, source):
        self.docs = Path(docs)
        self.paths = list(paths)          # Path objects, in order
        self.entries = entries            # list of dicts (manifest-backed) or None (unverified)
        self.source = source              # "manifest" or "disk"

    @property
    def names(self):
        return [p.name for p in self.paths]

    @property
    def records(self) -> Optional[int]:
        return self.entries[-1]["end"] if self.entries else None


def _read_run_meta_block(docs) -> Optional[dict]:
    try:
        rm = json.loads((Path(docs) / "run_meta.json").read_text())
    except (OSError, ValueError):
        return None
    blk = rm.get("board_parts") if isinstance(rm, dict) else None
    if isinstance(blk, dict) and blk.get("schema") == PARTS_SCHEMA and isinstance(blk.get("files"), list):
        return blk
    return None


def _torn(docs, problems) -> BoardIntegrityError:
    return BoardIntegrityError(
        "the board parts do not match %s: %s. The part set is torn or mixed (a write was "
        "interrupted, or parts from two different publishes are on disk). Restore a "
        "consistent set (scripts/restore_board.sh <commit>) or, if you know the files are "
        "right, scripts/board_manifest.py --rebuild. BOARD_MANIFEST_SKIP=1 bypasses this "
        "check." % (MANIFEST_NAME, "; ".join(problems[:5]) + (" ..." if len(problems) > 5 else "")))


def resolve(docs, *, verify: bool = True, man: Optional[dict] = None) -> Optional[Resolution]:
    """The board's parts in `docs`, or None when this directory has none (a legacy single-gz
    board, or no board at all).

    A parts board is only ever read through a LISTING that says which parts make it up, because
    a directory that holds listings_part_000..003 could be a finished four-part board or the
    first four of seven written by a write that died (or is still running):

    * a manifest with a "parts" block is AUTHORITATIVE: every part must exist with the recorded
      size (and sha256 when `verify`), otherwise BoardIntegrityError. Extra part files the
      manifest does not name are ignored here (verify_dir reports them).
    * a manifest WITHOUT a parts block (a pre-split manifest) means the legacy single-gz layout:
      return None, parts on disk are not consulted.
    * NO manifest (lost, or BOARD_MANIFEST_SKIP=1): run_meta.json's board_parts block is the
      listing, checked the same way. write_artifact writes it after the last part, so a
      half-written set has no listing that matches it.
    * no listing anywhere: BoardIntegrityError. BOARD_PARTS_ALLOW_UNLISTED=1 reads the contiguous
      parts found on disk unverified (an operator who has checked them by hand)."""
    docs = Path(docs)
    man = man if man is not None else read_manifest(docs)
    if man is not None:
        blk = manifest_parts_block(man)
        if blk is None:
            return None
        entries = normalize_entries(blk)
        problems = check_entries(docs, entries, verify)
        if problems:
            raise _torn(docs, problems)
        return Resolution(docs, [docs / e["name"] for e in entries], entries, "manifest")
    files = list_part_files(docs)
    if not files:
        return None
    blk = _read_run_meta_block(docs)
    if blk is not None:
        try:
            entries = normalize_entries(blk)
        except BoardIntegrityError:
            entries = None
        if entries is not None:
            problems = check_entries(docs, entries, verify)
            if problems:
                raise _torn(docs, problems)
            return Resolution(docs, [docs / e["name"] for e in entries], entries, "run_meta")
    if os.environ.get("BOARD_PARTS_ALLOW_UNLISTED", "").strip().lower() in ("1", "true", "yes"):
        for i, p in enumerate(files):
            if part_index(p.name) != i:
                raise BoardIntegrityError("board parts are not contiguous: expected %s, found %s"
                                          % (part_name(i), p.name))
        return Resolution(docs, files, None, "disk")
    raise UnlistedPartsError(
        "%d board part file(s) are on disk (%s ...) but neither %s nor run_meta.json lists them. "
        "That is what an interrupted first write looks like: the set may be incomplete. Restore a "
        "consistent set (scripts/restore_board.sh <commit>) or, after checking them, seal them with "
        "scripts/board_manifest.py --rebuild. BOARD_PARTS_ALLOW_UNLISTED=1 reads them unverified."
        % (len(files), files[0].name, MANIFEST_NAME))


def has_parts(docs) -> bool:
    """Cheap presence test (no hashing): is there a parts board here?"""
    docs = Path(docs)
    man = read_manifest(docs)
    if man is not None:
        return manifest_parts_block(man) is not None
    return bool(list_part_files(docs))


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def _iter_array(fh, want_text: bool) -> Iterator:
    """Yield the elements of one JSON array from a text stream, holding one chunk at a time.
    want_text=True yields each element's exact source text instead of the decoded object."""
    dec = json.JSONDecoder()
    buf = ""
    while True:
        chunk = fh.read(_READ_CHUNK)
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
                break                      # the element continues in the next chunk
            yield buf[i:j] if want_text else obj
            i = j
        buf = buf[i:]
        if not chunk:
            return


def iter_gz_rows(path, want_text: bool = False) -> Iterator:
    """Stream the rows of ONE gzipped JSON array (a part, or the legacy single file)."""
    with gzip.open(str(path), "rt", encoding="utf-8") as fh:
        for item in _iter_array(fh, want_text):
            yield item


def iter_rows(docs, *, verify: bool = True, res: Optional[Resolution] = None,
              want_text: bool = False) -> Iterator:
    """Stream every row of the parts board in order, one row at a time (constant memory).
    Raises BoardIntegrityError up front when the parts do not match the manifest, and after a
    part when its row count is not what the manifest recorded."""
    res = res if res is not None else resolve(docs, verify=verify)
    if res is None:
        raise FileNotFoundError("no board parts in %s" % docs)
    for i, p in enumerate(res.paths):
        n = 0
        for item in iter_gz_rows(p, want_text):
            n += 1
            yield item
        if res.entries is not None and n != res.entries[i]["records"]:
            raise BoardIntegrityError("%s holds %d rows, the manifest says %d"
                                      % (p.name, n, res.entries[i]["records"]))


def read_rows(docs, *, verify: bool = True, res: Optional[Resolution] = None) -> list:
    """All rows as a list (each part parsed in one call; peak memory is the board itself)."""
    res = res if res is not None else resolve(docs, verify=verify)
    if res is None:
        raise FileNotFoundError("no board parts in %s" % docs)
    out: list = []
    for i, p in enumerate(res.paths):
        rows = json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
        if not isinstance(rows, list):
            raise BoardIntegrityError("%s is not a JSON array" % p.name)
        if res.entries is not None and len(rows) != res.entries[i]["records"]:
            raise BoardIntegrityError("%s holds %d rows, the manifest says %d"
                                      % (p.name, len(rows), res.entries[i]["records"]))
        out.extend(rows)
    return out


def resolve_source(path) -> Optional[Resolution]:
    """For a caller holding a PATH to the board (docs/listings.json.gz or docs/listings.json):
    the parts board that lives beside it, or None to use the path as a plain/single file.

    This is what lets the ~25 scripts that name docs/listings.json.gz keep working unchanged
    through board_stream.iter_board_rows: they hand over the old path and get the parts."""
    p = Path(path)
    if p.name not in ("listings.json.gz", "listings.json"):
        return None
    return resolve(p.parent)


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------

def atomic_write_bytes(path, data: bytes) -> None:
    """Temp file in the same directory + os.replace, named by PID (two writers must never share
    a temp name: see web_artifact._atomic_write_bytes for the incident)."""
    path = Path(path)
    tmp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
    try:
        tmp.write_bytes(data)
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def gzip_array(blobs: Sequence[bytes], sep: bytes = b", ", level: int = 9) -> bytes:
    """gzip of `[blob0, blob1, ...]`, deterministic (mtime 0) and without ever holding the
    joined document: rows go into the compressor one at a time."""
    bio = io.BytesIO()
    with gzip.GzipFile(fileobj=bio, mode="wb", compresslevel=level, mtime=0) as gz:
        gz.write(b"[")
        first = True
        for b in blobs:
            if not first:
                gz.write(sep)
            gz.write(b)
            first = False
        gz.write(b"]")
    return bio.getvalue()


def _estimate_rows(groups: Sequence[Sequence[bytes]], cap: int) -> int:
    """Rows per part that land near TARGET_FILL of `cap`, from the measured compression ratio
    of contiguous sample groups."""
    raw = 0
    comp = 0
    rows = 0
    for g in groups:
        if not g:
            continue
        raw += sum(len(b) for b in g) + 2 * len(g)
        comp += len(gzip_array(g))
        rows += len(g)
    if rows == 0 or comp == 0:
        return ROW_QUANTUM
    bytes_per_row_compressed = comp / float(rows)
    est = int((cap * TARGET_FILL) / bytes_per_row_compressed)
    return max(1, est)


def _quantize(n: int) -> int:
    if n >= 2 * ROW_QUANTUM:
        return (n // ROW_QUANTUM) * ROW_QUANTUM
    return max(1, n)


def choose_rows_per_part(sample_groups: Sequence[Sequence[bytes]], cap: int,
                         hint: Optional[int] = None) -> int:
    est = _estimate_rows(sample_groups, cap)
    if hint and est * KEEP_HINT_LOW <= hint <= est * KEEP_HINT_HIGH:
        return int(hint)
    return _quantize(est)


def _sample_groups(blobs: Sequence[bytes]) -> List[Sequence[bytes]]:
    n = len(blobs)
    if n <= SAMPLE_CHUNKS * SAMPLE_CHUNK_ROWS:
        return [blobs]
    span = (n - SAMPLE_CHUNK_ROWS) // (SAMPLE_CHUNKS - 1)
    return [blobs[k * span:k * span + SAMPLE_CHUNK_ROWS] for k in range(SAMPLE_CHUNKS)]


def write_parts(docs, blobs: Iterable[bytes], *, cap: Optional[int] = None,
                hint_rows: Optional[int] = None, level: int = 9,
                write=None, remove_stale: bool = True) -> dict:
    """Cut `blobs` (one bytes object per row, in board order) into gzipped JSON-array parts of
    at most `cap` bytes each (default PART_MAX_BYTES) and write them to docs/.

    Returns {"entries": [...], "rows_per_part": n, "cap": cap, "records": total} where each entry
    is {name, start, end, records, bytes, sha256}.

    Rows per part come from the compression ratio measured on contiguous samples, snapped to a
    multiple of 500 and kept equal to `hint_rows` (the previous write's value) while that is
    still a good fit, so boundaries stay put from one write to the next. Whatever the estimate
    says, every part is compressed and MEASURED: one that comes out over the cap is cut down to
    the rows that fit (at least one row) and the rest moves to the next part, so the cap is
    never exceeded. A single row that alone exceeds the cap raises PartTooLargeError.

    Stale higher-numbered parts (from a longer previous board) are removed AFTER every new part
    is on disk. Parts are written atomically one by one; the manifest that seals the set is the
    caller's job, and until it is written the on-disk set disagrees with the old manifest, which
    the loaders detect."""
    docs = Path(docs)
    docs.mkdir(parents=True, exist_ok=True)
    cap = int(cap if cap is not None else max_bytes())
    writer = write or atomic_write_bytes

    if isinstance(blobs, (list, tuple)):
        total_known = len(blobs)
        groups = _sample_groups(blobs)
        source = iter(blobs)
    else:
        head = list(itertools.islice(blobs, STREAM_SAMPLE_ROWS))
        total_known = None
        groups = [head]
        source = itertools.chain(head, blobs)
    n_per = choose_rows_per_part(groups, cap, hint_rows)

    pending: deque = deque()
    entries: List[dict] = []
    row = 0
    exhausted = False
    while True:
        chunk: list = []
        while len(chunk) < n_per and pending:
            chunk.append(pending.popleft())
        if len(chunk) < n_per and not exhausted:
            more = list(itertools.islice(source, n_per - len(chunk)))
            if len(more) < n_per - len(chunk):
                exhausted = True
            chunk.extend(more)
        if not chunk:
            break
        data = gzip_array(chunk, level=level)
        while len(data) > cap:
            if len(chunk) == 1:
                raise PartTooLargeError("a single board row compresses to %d bytes, over the %d byte "
                                        "part cap" % (len(data), cap))
            keep = max(1, min(len(chunk) - 1, int(len(chunk) * (cap / float(len(data))) * 0.94)))
            pending.extendleft(reversed(chunk[keep:]))
            chunk = chunk[:keep]
            n_per = min(n_per, _quantize(keep))
            data = gzip_array(chunk, level=level)
        name = part_name(len(entries))
        writer(docs / name, data)
        entries.append({"name": name, "start": row, "end": row + len(chunk), "records": len(chunk),
                        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        row += len(chunk)
        if exhausted and not pending:
            break
    if not entries:
        # an empty board is still a board: one part holding `[]`
        data = gzip_array([], level=level)
        writer(docs / part_name(0), data)
        entries.append({"name": part_name(0), "start": 0, "end": 0, "records": 0,
                        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    if remove_stale:
        remove_stale_parts(docs, len(entries))
    return {"entries": entries, "rows_per_part": n_per, "cap": cap, "records": row}


def remove_stale_parts(docs, keep_count: int) -> List[str]:
    """Delete part files numbered >= keep_count (left by a longer previous board) and any part
    temp files. Returns the names removed."""
    docs = Path(docs)
    removed = []
    for p in list_part_files(docs):
        idx = part_index(p.name)
        if idx is not None and idx >= keep_count:
            try:
                p.unlink()
                removed.append(p.name)
            except OSError:
                pass
    try:
        for p in docs.iterdir():
            if p.name.startswith(PART_PREFIX) and p.name.endswith(".tmp"):
                try:
                    p.unlink()
                except OSError:
                    pass
    except OSError:
        pass
    return removed


def iter_row_texts(path) -> Iterator[bytes]:
    """Every row of a board file as its exact source bytes, one at a time. `path` may be a
    gzipped array (listings.json.gz, or a part) or a plain array (listings.json). This is how the
    migration and the direct-writer helper split a board WITHOUT decoding and re-encoding rows
    (so the parts carry the original bytes)."""
    p = Path(path)
    if p.suffix == ".gz":
        for t in iter_gz_rows(p, want_text=True):
            yield t.encode("utf-8")
        return
    with open(str(p), "rt", encoding="utf-8") as fh:
        for t in _iter_array(fh, True):
            yield t.encode("utf-8")


# ---------------------------------------------------------------------------
# whole-directory verification (used by verify_manifest, board_manifest.py, the gate)
# ---------------------------------------------------------------------------

def verify_dir(docs, *, verify: bool = True, man: Optional[dict] = None) -> dict:
    """{"ok", "problems", "parts", "records"} for the parts board in docs/. A legacy layout
    (no parts block) is ok with parts=0. Never raises."""
    docs = Path(docs)
    man = man if man is not None else read_manifest(docs)
    if man is None:
        n = len(list_part_files(docs))
        blk = _read_run_meta_block(docs)
        if blk is not None:
            try:
                entries = normalize_entries(blk)
            except BoardIntegrityError as exc:
                return {"ok": False, "problems": [str(exc)], "parts": n, "records": None}
            problems = check_entries(docs, entries, verify)
            extra = stray_parts(docs, entries)
            if extra:
                problems.append("part file(s) on disk that run_meta.json does not list: %s" % ", ".join(extra[:4]))
            return {"ok": not problems, "problems": problems, "parts": len(entries),
                    "records": entries[-1]["end"] if entries else 0,
                    "note": "no manifest: checked against run_meta.json"}
        return {"ok": n == 0, "problems": [] if n == 0 else
                ["%d part file(s) on disk and no manifest or run_meta listing to check them against" % n],
                "parts": n, "records": None}
    blk = manifest_parts_block(man)
    if blk is None:
        strays = list_part_files(docs)
        probs = ["part files on disk but the manifest has no parts block: %s"
                 % ", ".join(p.name for p in strays[:4])] if strays else []
        return {"ok": not probs, "problems": probs, "parts": 0, "records": None}
    try:
        entries = normalize_entries(blk)
    except BoardIntegrityError as exc:
        return {"ok": False, "problems": [str(exc)], "parts": 0, "records": None}
    problems = check_entries(docs, entries, verify)
    extra = stray_parts(docs, entries)
    if extra:
        problems.append("part file(s) on disk that the manifest does not list: %s" % ", ".join(extra[:4]))
    cnt = man.get("count")
    if cnt is not None and entries and cnt != entries[-1]["end"]:
        problems.append("manifest count %s != parts total %d" % (cnt, entries[-1]["end"]))
    return {"ok": not problems, "problems": problems, "parts": len(entries),
            "records": entries[-1]["end"] if entries else 0}


def _main(argv) -> int:
    """python3 board_parts.py verify [docs] | names [docs]   (for shell callers)"""
    if len(argv) < 2 or argv[1] not in ("verify", "names"):
        sys.stderr.write("usage: board_parts.py verify|names [docs-dir]\n")
        return 2
    docs = Path(argv[2]) if len(argv) > 2 else Path("docs")
    if argv[1] == "names":
        man = read_manifest(docs)
        blk = manifest_parts_block(man) if man else None
        names = [e["name"] for e in normalize_entries(blk)] if blk else [p.name for p in list_part_files(docs)]
        for n in names:
            print(n)
        return 0
    res = verify_dir(docs)
    print(json.dumps({k: res[k] for k in ("ok", "parts", "records") if k in res}))
    for p in res["problems"]:
        print("  PROBLEM " + p)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
