#!/usr/bin/env python3
"""Refuse a commit whose STAGED board is not one consistent set of parts (audit O1).

The board is docs/listings_part_NNN.json.gz (src/foreclosure_scraper/board_parts.py), cut
from one write_artifact() call and listed, with size and sha256 per part, in
docs/board.manifest.json and docs/run_meta.json. Row index i is the join across the parts,
listings_detail, listings_slim and detail_shards, so a commit that carries parts from two
different writes ships a mis-joined board: one property's owner and phone on another's card,
with no error anywhere. Publishers stage the parts in one `git add`; this is the second lock
on the same door, and it reads the INDEX (what is about to be committed), never the working
tree:

  * a commit that touches no part and not the manifest passes without doing any work
  * the staged parts must be EXACTLY the parts the staged manifest lists (no stray higher
    number, none missing), each with the recorded size and sha256
  * the manifest's parts block must be well formed (contiguous names and row ranges)
  * staged run_meta.json must carry the same part list (the dashboard reads that copy) and be
    the run_meta.json the manifest hashed
  * a legacy layout (no parts anywhere, or a manifest without a parts block and no parts
    staged) passes: this check only guards the parts board

Run by scripts/git_size_gate.sh (the pre-commit hook) and by board_payload_verify_staged in
scripts/board_payload.sh (publishers, workflows and fresh clones with no hook installed).

    python3 scripts/check_staged_parts.py [--root DIR]

Exit 0 = fine, 1 = refuse the commit (problems on stderr). Stdlib only, Python 3.9.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PART_RE = re.compile(r"^docs/listings_part_(\d{3,})\.json\.gz$")
MANIFEST = "docs/board.manifest.json"
RUN_META = "docs/run_meta.json"


def _load_parts_module(root: Path):
    src = root / "src" / "foreclosure_scraper" / "board_parts.py"
    if not src.is_file():
        return None
    spec = importlib.util.spec_from_file_location("board_parts_gate", str(src))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["board_parts_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=120)


def staged_paths(root: Path) -> list:
    r = _git(root, "diff", "--cached", "--name-only", "-z")
    return [p.decode("utf-8", "replace") for p in r.stdout.split(b"\0") if p]


def index_blobs(root: Path, pathspec: str) -> dict:
    """{path: object id} for every path under `pathspec` that is IN THE INDEX (not just changed)."""
    r = _git(root, "ls-files", "-s", "-z", "--", pathspec)
    out = {}
    for rec in r.stdout.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        parts = meta.split()
        if len(parts) == 3:
            out[path.decode("utf-8", "replace")] = parts[1].decode()
    return out


def blob_bytes(root: Path, oid: str) -> bytes:
    return _git(root, "cat-file", "blob", oid).stdout


def check(root: Path) -> list:
    """The list of problems; empty means the staged board is consistent (or not a parts board)."""
    changed = staged_paths(root)
    touches = [p for p in changed if PART_RE.match(p) or p == MANIFEST]
    if not touches:
        return []
    bp = _load_parts_module(root)
    if bp is None:
        return []     # a checkout that predates the split: nothing to enforce

    parts_idx = {p: oid for p, oid in index_blobs(root, "docs/listings_part_*.json.gz").items()
                 if PART_RE.match(p)}
    man_blobs = index_blobs(root, MANIFEST)
    if MANIFEST not in man_blobs:
        if parts_idx:
            return ["board parts are staged but docs/board.manifest.json is not in the index; "
                    "the manifest lists the parts and must travel with them"]
        return []
    try:
        man = json.loads(blob_bytes(root, man_blobs[MANIFEST]).decode("utf-8"))
    except ValueError as exc:
        return ["staged docs/board.manifest.json is not valid JSON: %s" % exc]
    blk = bp.manifest_parts_block(man)
    if blk is None:
        if parts_idx:
            return ["board parts are staged but the staged manifest has no parts block "
                    "(a manifest from the single-file layout describes a different board)"]
        return []

    problems = []
    try:
        entries = bp.normalize_entries(blk)
    except Exception as exc:  # noqa: BLE001
        return ["staged manifest parts block is malformed: %s" % exc]

    listed = {"docs/" + e["name"]: e for e in entries}
    for path in sorted(set(parts_idx) - set(listed)):
        problems.append("%s is staged but the staged manifest does not list it (a stale "
                        "higher-numbered part, or parts from two different writes)" % path)
    for path in sorted(listed):
        oid = parts_idx.get(path)
        if oid is None:
            problems.append("%s is listed by the manifest but is not in the index" % path)
            continue
        data = blob_bytes(root, oid)
        ent = listed[path]
        if len(data) != ent["bytes"]:
            problems.append("%s: staged size %d != manifest %d" % (path, len(data), ent["bytes"]))
        elif hashlib.sha256(data).hexdigest() != ent["sha256"]:
            problems.append("%s: staged sha256 does not match the manifest (parts from a "
                            "different write than the manifest)" % path)
    if entries and man.get("count") is not None and man["count"] != entries[-1]["end"]:
        problems.append("manifest count %s != rows covered by its parts %d"
                        % (man["count"], entries[-1]["end"]))

    meta_blobs = index_blobs(root, RUN_META)
    if RUN_META not in meta_blobs:
        problems.append("docs/run_meta.json is not in the index: the dashboard reads the part list "
                        "from it")
    else:
        raw = blob_bytes(root, meta_blobs[RUN_META])
        want = (man.get("files") or {}).get("run_meta.json") or {}
        if want.get("sha256") and hashlib.sha256(raw).hexdigest() != want["sha256"]:
            problems.append("staged docs/run_meta.json is not the run_meta.json the staged manifest "
                            "hashed (run_meta and the manifest are from different writes)")
        try:
            meta = json.loads(raw.decode("utf-8"))
            rb = meta.get("board_parts") if isinstance(meta, dict) else None
            if rb is None:
                problems.append("staged docs/run_meta.json has no board_parts list")
            else:
                got = [(e["name"], e["bytes"], e["sha256"]) for e in bp.normalize_entries(rb)]
                exp = [(e["name"], e["bytes"], e["sha256"]) for e in entries]
                if got != exp:
                    problems.append("staged run_meta.json board_parts differs from the staged "
                                    "manifest's parts")
        except Exception as exc:  # noqa: BLE001
            problems.append("staged run_meta.json board_parts is unusable: %s" % exc)
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    root = Path(args.root)
    problems = check(root)
    if not problems:
        return 0
    sys.stderr.write("parts gate: REFUSED. The staged board is not one consistent set of parts:\n")
    for p in problems:
        sys.stderr.write("  - %s\n" % p)
    sys.stderr.write("Nothing was committed. Re-stage the whole payload from ONE write "
                     "(. scripts/board_payload.sh; board_payload_add <root>), or "
                     "`git reset` and let the next publisher carry it. See docs/payload_split_2026-09-21.md.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
