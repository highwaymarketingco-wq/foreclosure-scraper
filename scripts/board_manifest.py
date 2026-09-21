#!/usr/bin/env python3
"""Verify, rebuild or row-check the board manifest (docs/board.manifest.json).

    .venv/bin/python scripts/board_manifest.py --verify            # default: hash every file
    .venv/bin/python scripts/board_manifest.py --verify --quick    # sizes only
    .venv/bin/python scripts/board_manifest.py --rebuild           # re-derive the manifest from disk
    .venv/bin/python scripts/board_manifest.py --validate-rows     # count rows load_board would drop

WHY. write_artifact writes the payload files one after another and seals the set by writing
this manifest last (audit O3); load_board and read_board_json refuse a file that disagrees
with it. That fail-closed reader needs a way out, and this is it:

  --verify         read-only. Exit 0 = every file matches, 1 = a mismatch (lists them).
  --rebuild        you have checked the files and they are right (restored by hand, or the
                   manifest went stale because a publisher staged the payload without it):
                   re-derive size + sha256 for every file on disk and write a fresh manifest.
                   Takes the board lock (or set FORECLOSURE_BOARD_LOCK_HELD via
                   scripts/with_board_lock.sh) because it rewrites a payload file.
  --validate-rows  read-only. Loads the board's records WITHOUT writing and reports how many
                   rows Listing.model_validate rejects and which sources they come from. This
                   is the number `except Exception: pass` in load_board used to hide, and the
                   only way to know the real drop rate before BOARD_LOAD_MAX_DROP_RATE (0.1%)
                   starts failing loads. It loads the whole board (about 3 GB): run it ONCE, when
                   no other board job is running, never in parallel with one.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import web_artifact as wa  # noqa: E402


def cmd_verify(docs: Path, quick: bool) -> int:
    res = wa.verify_manifest(docs, full=not quick)
    print(json.dumps({k: res[k] for k in ("ok", "checked", "count", "written_at") if k in res}))
    for p in res["problems"]:
        print("  MISMATCH", p)
    return 0 if res["ok"] else 1


def cmd_rebuild(docs: Path) -> int:
    meta = {}
    try:
        meta = json.loads((docs / "run_meta.json").read_text())
    except (OSError, ValueError):
        pass
    total = meta.get("total")
    pre = {}
    # records per file come from run_meta (parsing 1.1 GB just to count would defeat the point)
    if total is not None:
        for name in ("listings.json", "listings.json.gz"):
            fp = docs / name
            if fp.is_file():
                pre[name] = {"bytes": fp.stat().st_size, "sha256": wa._sha256_file(fp), "records": total}
        dc = meta.get("detail_count", total)
        for name in ("listings_detail.json", "listings_detail.json.gz"):
            fp = docs / name
            if fp.is_file():
                pre[name] = {"bytes": fp.stat().st_size, "sha256": wa._sha256_file(fp), "records": dc}
    board = meta.get("board") or {}
    mp = wa.write_manifest(docs, pre, meta, slim_count=board.get("count"),
                           shard_meta=board.get("detail_shards"))
    print(f"wrote {mp}")
    return cmd_verify(docs, quick=False)


def cmd_validate_rows(docs: Path) -> int:
    from foreclosure_scraper.models import Listing
    recs = wa.read_board_records(docs)
    bad = []
    for i, rec in enumerate(recs):
        try:
            Listing.model_validate(rec)
        except Exception as exc:  # noqa: BLE001
            bad.append((i, str(rec.get("source", "")) if isinstance(rec, dict) else "", f"{type(exc).__name__}: {str(exc)[:120]}"))
    rate = len(bad) / len(recs) if recs else 0.0
    print(f"rows={len(recs):,} invalid={len(bad):,} rate={rate:.4%} "
          f"(load_board fails above {float(os.environ.get('BOARD_LOAD_MAX_DROP_RATE', '0.001')):.3%})")
    by_src: dict = {}
    for _, s, _ in bad:
        by_src[s] = by_src.get(s, 0) + 1
    for s, n in sorted(by_src.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {n:>7,}  {s or '(no source)'}")
    for i, s, e in bad[:5]:
        print(f"  e.g. row {i} [{s}] {e}")
    return 0 if rate <= float(os.environ.get("BOARD_LOAD_MAX_DROP_RATE", "0.001")) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--docs", default=str(REPO / "docs"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--verify", action="store_true")
    g.add_argument("--rebuild", action="store_true")
    g.add_argument("--validate-rows", action="store_true")
    ap.add_argument("--quick", action="store_true", help="--verify: compare sizes only")
    args = ap.parse_args(argv)
    docs = Path(args.docs)
    if args.rebuild:
        # rewriting a payload file is a board write: hold the lock
        with wa.board_lock(docs.resolve().parent, owner="board_manifest.rebuild", max_runtime=1800):
            return cmd_rebuild(docs)
    if args.validate_rows:
        return cmd_validate_rows(docs)
    return cmd_verify(docs, args.quick)


if __name__ == "__main__":
    sys.exit(main())
