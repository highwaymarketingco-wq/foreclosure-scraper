"""On-disk format of the Mac -> VM stealth hand-off: sharded JSON Lines plus a manifest.

WHY. The hand-off was one file, docs/handoff/stealth_leads.json, written whole every morning by
scripts/run_stealth_sources.py. On 2026-10-08 it held 51,730 leads in 98,406,892 bytes (93.8 MiB),
up from 46 MB the day before. The repo's pre-commit gate (scripts/git_size_gate.sh) refuses any
file over 95 MiB and GitHub refuses 100 MiB, so the first morning it crossed the gate the hand-off
commit would have been refused and the VM would have ingested an ever older file.

FORMAT (FORMAT below):
    docs/handoff/stealth_leads/manifest.json      the commit point; lists every shard
    docs/handoff/stealth_leads/<slug>.<NNN>.jsonl one lead per line, one producing scraper per
                                                  shard, each at most SHARD_MAX_BYTES
The manifest carries the old file's header fields (generated_at, host, sources_run, lead_count,
by_source) plus one entry per shard: file, slug, count, bytes, sha256.

WHY PLAIN JSON AND NOT GZIP. Git already zlib-compresses every blob, and plain text deltas
against the previous day's version; gzip output does not. Measured on the real hand-off history:
the 10/7 file cost 0.81 MB in a pack that already held 10/6, while its gzip is 3.1 MB and the
10/8 gzip is 6.4 MB, every byte of it new each day. Gzip would have grown the repository about
eight times faster. The reader still accepts `.jsonl.gz` shards, so switching is a writer flag
(HANDOFF_SHARD_GZIP=1), not a format change.

WHY ONE SCRAPER PER SHARD. The same slug lands at the same path every day, so git pairs each
shard with yesterday's copy of the same source and the delta stays small. A source bigger than
SHARD_MAX_BYTES continues in <slug>.001.jsonl and so on.

TRANSITION. The reader (scrapers/national/stealth_handoff.py) prefers the manifest and falls back
to the legacy single file, so a checkout from before the switch still ingests. The writer removes
the legacy file in the same commit that adds the shards.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterator

FORMAT = "stealth_leads/2"
DIR_NAME = "stealth_leads"
MANIFEST = "manifest.json"
LEGACY_NAME = "stealth_leads.json"
#: per-shard cap on the uncompressed size. GitHub warns at 50 MB and refuses 100 MiB; the repo's
#: own gate refuses 95 MiB and scripts/repo_size_check.py fails at 90 MiB. 20 MiB leaves room for a
#: source to double overnight without any shard getting near either line.
SHARD_MAX_BYTES = int(os.environ.get("HANDOFF_SHARD_MAX_BYTES", str(20 * 1024 * 1024)))

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")
_SHARD_FILE = re.compile(r"^[A-Za-z0-9_.-]+\.jsonl(\.gz)?$")


def shard_dir(handoff_dir: Path) -> Path:
    return handoff_dir / DIR_NAME


def legacy_file(handoff_dir: Path) -> Path:
    return handoff_dir / LEGACY_NAME


def _slug_file_stem(slug: str) -> str:
    stem = _SAFE_NAME.sub("_", slug or "unknown").strip("._") or "unknown"
    return stem[:120]


def _iter_chunks(lines: list[str], max_bytes: int) -> Iterator[list[str]]:
    """Split one source's lines into runs of at most max_bytes (a single line bigger than the
    cap still gets a shard of its own: a lead is never split)."""
    chunk: list[str] = []
    size = 0
    for line in lines:
        n = len(line.encode("utf-8")) + 1
        if chunk and size + n > max_bytes:
            yield chunk
            chunk, size = [], 0
        chunk.append(line)
        size += n
    if chunk:
        yield chunk


def write_sharded(handoff_dir: Path, meta: dict[str, Any],
                  lines_by_slug: dict[str, list[str]], *,
                  max_bytes: int | None = None, gzip_shards: bool | None = None,
                  remove_legacy: bool = True) -> dict[str, Any]:
    """Write the hand-off as shards + manifest under handoff_dir/stealth_leads, atomically.

    lines_by_slug: producing scraper slug -> its leads, each already one line of JSON (no
    newline). meta: the header fields (generated_at, host, sources_run, by_source). The whole
    directory is built beside the live one and swapped in with two renames, so a crash leaves
    either the old hand-off or the new one, never a manifest that names missing shards.
    Returns the manifest."""
    max_bytes = max_bytes or SHARD_MAX_BYTES
    if gzip_shards is None:
        gzip_shards = os.environ.get("HANDOFF_SHARD_GZIP", "0") == "1"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    final = shard_dir(handoff_dir)
    tmp = handoff_dir / f".{DIR_NAME}.new"
    old = handoff_dir / f".{DIR_NAME}.old"
    for leftover in (tmp, old):
        if leftover.exists():
            shutil.rmtree(leftover)
    tmp.mkdir()

    shards: list[dict[str, Any]] = []
    total = 0
    used: set[str] = set()
    for slug in sorted(lines_by_slug):
        lines = lines_by_slug[slug]
        if not lines:
            continue
        stem = _slug_file_stem(slug)
        while stem in used:                      # two slugs that sanitise to the same name
            stem += "_"
        used.add(stem)
        for i, chunk in enumerate(_iter_chunks(lines, max_bytes)):
            body = ("\n".join(chunk) + "\n").encode("utf-8")
            name = f"{stem}.{i:03d}.jsonl"
            data = body
            if gzip_shards:
                name += ".gz"
                data = gzip.compress(body, mtime=0)
            (tmp / name).write_bytes(data)
            shards.append({"file": name, "slug": slug, "count": len(chunk), "bytes": len(data),
                           "sha256": hashlib.sha256(data).hexdigest()})
            total += len(chunk)

    manifest = {"format": FORMAT, **meta, "lead_count": total, "shard_count": len(shards),
                "shard_max_bytes": max_bytes, "shards": shards}
    (tmp / MANIFEST).write_text(json.dumps(manifest, indent=1, default=str) + "\n")

    if final.exists():
        os.replace(final, old)
    os.replace(tmp, final)
    if old.exists():
        shutil.rmtree(old)
    if remove_legacy:
        legacy = legacy_file(handoff_dir)
        if legacy.exists():
            legacy.unlink()
    return manifest


def read_manifest(path: Path) -> dict[str, Any] | None:
    """The manifest at path (a manifest.json or the shard directory), or None when it is absent,
    unreadable or not this format."""
    if path.is_dir():
        path = path / MANIFEST
    try:
        m = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or not isinstance(m.get("shards"), list):
        return None
    return m


def iter_shard_rows(directory: Path, manifest: dict[str, Any],
                    stats: dict[str, int]) -> Iterator[Any]:
    """Every lead (parsed JSON) of every shard the manifest lists, one shard in memory at a time.

    stats is filled in: shards_read, shards_missing, shards_corrupt (unreadable, wrong sha256, or
    a name that is not a plain shard file name), lines_bad (a line that is not JSON) and
    count_mismatch (shards whose line count differs from the manifest)."""
    for key in ("shards_read", "shards_missing", "shards_corrupt", "lines_bad", "count_mismatch"):
        stats.setdefault(key, 0)
    for entry in manifest.get("shards") or []:
        name = str((entry or {}).get("file") or "")
        if not _SHARD_FILE.match(name):
            stats["shards_corrupt"] += 1
            continue
        p = directory / name
        try:
            data = p.read_bytes()
        except FileNotFoundError:
            stats["shards_missing"] += 1
            continue
        except OSError:
            stats["shards_corrupt"] += 1
            continue
        want = entry.get("sha256")
        if want and hashlib.sha256(data).hexdigest() != want:
            stats["shards_corrupt"] += 1
            continue
        try:
            text = (gzip.decompress(data) if name.endswith(".gz") else data).decode("utf-8")
        except (OSError, UnicodeDecodeError, EOFError):
            stats["shards_corrupt"] += 1
            continue
        stats["shards_read"] += 1
        n = 0
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                stats["lines_bad"] += 1
                continue
            n += 1
            yield row
        if isinstance(entry.get("count"), int) and entry["count"] != n:
            stats["count_mismatch"] += 1


_GEN_AT = re.compile(rb'"generated_at"\s*:\s*"([^"]+)"')


def peek_generated_at(path: Path, head_bytes: int = 4096) -> str | None:
    """generated_at of a legacy single-file hand-off without parsing the whole file: the writer
    always put it first in the object."""
    try:
        with open(path, "rb") as fh:
            m = _GEN_AT.search(fh.read(head_bytes))
    except OSError:
        return None
    return m.group(1).decode("utf-8", "replace") if m else None

