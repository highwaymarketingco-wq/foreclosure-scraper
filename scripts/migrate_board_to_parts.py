#!/usr/bin/env python3
"""One-shot: convert docs/listings.json.gz into docs/listings_part_NNN.json.gz (audit O1).

    .venv/bin/python scripts/migrate_board_to_parts.py                # DRY RUN (the default)
    .venv/bin/python scripts/migrate_board_to_parts.py --apply        # do it (takes the board lock)

WHY. listings.json.gz was 84 MiB on 2026-09-21 and grows 2 to 4 MiB a day against GitHub's 100 MiB
file limit (95 MiB pre-commit gate). The board is now published as independently gzipped parts of
at most 24 MiB (src/foreclosure_scraper/board_parts.py). write_artifact writes them from the next
board write on; this script converts the board that already exists, so the split can be published
without running a whole job.

WHAT IT DOES. It streams the source row by row (constant memory, about 300 MB; it does NOT call
load_board and does not decode rows into Listings), cuts the rows into parts under the size cap, and
proves the cut: it streams the parts back and compares every row's bytes, in order, with the source.
The rows are copied as their exact source text, never re-encoded, so a part holds exactly the
bytes the single file held.

  DRY RUN   writes the parts into a temporary directory (deleted afterwards), prints the layout
            (rows, bytes and sha256 per part), runs the round-trip proof, and prints the git steps.
            Touches nothing under docs/.
  --apply   takes the board lock, then: stages the parts in docs/.migrate_parts.<pid>/, computes the
            hashes of the big plain files, moves the parts into docs/, and writes run_meta.json's
            board_parts and docs/board.manifest.json (sealed last). Re-verifies the result and re-runs
            the round-trip proof from the final files. It never deletes docs/listings.json.gz: after
            the manifest lists parts every reader ignores it, and `git rm` is a separate, deliberate
            step (printed at the end, and in docs/payload_split_2026-09-21.md).

REFUSES (exit 1) unless --force:
  * the source is missing or is not a JSON array
  * the row count is not the count run_meta.json declares (board.count, else total): the dashboard
    compares the parts' total with that number and would refuse to render a board that disagrees
  * docs/ already has a manifest with a parts block (already migrated)
  * a board job holds the board lock (--apply only; exit 75)

Never pushes, never commits, never touches git.

Exit status: 0 done (or dry run fine), 1 refused or failed a check, 2 bad usage.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import board_parts as bp  # noqa: E402

MIB = 1024 * 1024


def _fail(msg: str) -> int:
    print(f"REFUSED: {msg}", file=sys.stderr)
    return 1


def _meta(docs: Path) -> dict:
    try:
        m = json.loads((docs / "run_meta.json").read_text())
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def declared_count(meta: dict):
    """The row count run_meta.json declares for the board: the slim block's count (what the
    dashboard's count gate compares with), else total."""
    b = meta.get("board")
    if isinstance(b, dict) and isinstance(b.get("count"), int):
        return b["count"], "board.count"
    if isinstance(meta.get("total"), int):
        return meta["total"], "total"
    return None, None


def roundtrip(source: Path, parts_dir: Path, entries: list) -> tuple:
    """Stream the source and the parts together and compare every row's exact text, in order.
    Returns (ok, rows_compared, message)."""
    src = bp.iter_row_texts(source)
    n = 0
    for ent in entries:
        p = parts_dir / ent["name"]
        got = 0
        for text in bp.iter_row_texts(p):
            want = next(src, None)
            if want is None:
                return False, n, f"{ent['name']} has more rows than the source (row {n})"
            if text != want:
                return False, n, f"row {n} differs between the source and {ent['name']}"
            n += 1
            got += 1
        if got != ent["records"]:
            return False, n, f"{ent['name']} holds {got} rows, recorded {ent['records']}"
    if next(src, None) is not None:
        return False, n, "the source has more rows than the parts"
    return True, n, "every row identical, in order"


def show(entries: list, cap: int) -> None:
    print(f"{'part':<28} {'rows':>20} {'records':>8} {'MiB':>7}  sha256")
    for e in entries:
        flag = "" if e["bytes"] <= cap else "  <-- OVER THE CAP"
        print(f"{e['name']:<28} {e['start']:>9,}-{e['end']:<10,} {e['records']:>8,} "
              f"{e['bytes'] / MIB:>7.2f}  {e['sha256'][:12]}{flag}")
    total = sum(e["bytes"] for e in entries)
    print(f"{len(entries)} parts, {entries[-1]['end']:,} rows, {total / MIB:.1f} MiB in all; "
          f"largest {max(e['bytes'] for e in entries) / MIB:.2f} MiB (cap {cap / MIB:.0f} MiB)")


GIT_STEPS = """\
Next, by hand (this script never touches git):

  cd {repo}
  cp docs/listings.json.gz backups/listings.json.gz.pre-split     # optional local rollback copy (backups/ is untracked)
  git rm docs/listings.json.gz                 # retire the single file; its history stays in git
  git add docs/listings_part_*.json.gz docs/board.manifest.json docs/run_meta.json
  python3 scripts/check_staged_parts.py        # the pre-commit hook runs this too: staged parts == manifest parts
  git commit -m "Payload split: publish the board as listings_part_NNN.json.gz (audit O1)"
  git push origin main

The single file stays in git history (rollback: docs/payload_split_2026-09-21.md).
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--docs", default=str(REPO / "docs"))
    ap.add_argument("--source", default=None, help="the single gzipped board (default: <docs>/listings.json.gz)")
    ap.add_argument("--apply", action="store_true", help="really convert (default is a dry run)")
    ap.add_argument("--force", action="store_true", help="skip the count check and the already-migrated check")
    ap.add_argument("--cap-bytes", type=int, default=None, help="part size cap (default board_parts.PART_MAX_BYTES, 24 MiB)")
    args = ap.parse_args(argv)

    docs = Path(args.docs)
    source = Path(args.source) if args.source else docs / "listings.json.gz"
    cap = int(args.cap_bytes) if args.cap_bytes else bp.max_bytes()
    if not docs.is_dir():
        return _fail(f"no such directory: {docs}")
    if not source.is_file():
        return _fail(f"source board not found: {source}")

    meta = _meta(docs)
    if not meta:
        return _fail(f"{docs / 'run_meta.json'} is missing or unreadable: the dashboard reads the part list from it")
    man = bp.read_manifest(docs)
    if not args.force and man is not None and bp.manifest_parts_block(man) is not None:
        return _fail("docs/board.manifest.json already lists board parts: this board is already migrated "
                     "(--force re-cuts them)")

    print(f"source : {source}  ({source.stat().st_size / MIB:.1f} MiB)")
    print(f"mode   : {'APPLY' if args.apply else 'DRY RUN (nothing under docs/ is touched)'}")
    print(f"cap    : {cap / MIB:.0f} MiB per part")
    t0 = time.time()

    if args.apply:
        from foreclosure_scraper import web_artifact as wa
        lock = wa.board_lock(docs.resolve().parent, owner="migrate_board_to_parts", max_runtime=3600)
    else:
        wa = None
        lock = None

    def run() -> int:
        stage = Path(tempfile.mkdtemp(prefix=".migrate_parts.", dir=str(docs) if args.apply else None))
        try:
            print("cutting: streaming the source row by row ...", flush=True)
            hint = ((bp.manifest_parts_block(man) or {}).get("rows_per_part")
                    or (meta.get("board_parts") or {}).get("rows_per_part"))
            res = bp.write_parts(stage, bp.iter_row_texts(source), cap=cap, hint_rows=hint)
            entries = res["entries"]
            print(f"  cut in {time.time() - t0:.0f}s (rows per part {res['rows_per_part']:,})")
            show(entries, cap)
            oversize = [e["name"] for e in entries if e["bytes"] > cap]
            if oversize:
                return _fail(f"parts over the cap: {', '.join(oversize)}")

            want, why = declared_count(meta)
            rows = entries[-1]["end"]
            if want is not None and rows != want:
                msg = f"the source holds {rows:,} rows but run_meta.json {why} says {want:,}"
                if not args.force:
                    return _fail(msg + " (the dashboard would refuse the board; --force to go ahead)")
                print(f"WARNING (--force): {msg}")
            else:
                print(f"row count {rows:,} matches run_meta.json {why}")

            print("proving the cut: streaming the parts back against the source ...", flush=True)
            ok, n, msg = roundtrip(source, stage, entries)
            print(f"  round trip: {'OK' if ok else 'FAILED'} ({n:,} rows compared): {msg}")
            if not ok:
                return _fail("the parts do not reproduce the source: " + msg)

            if not args.apply:
                print()
                print("Dry run complete. Nothing under docs/ changed.")
                print("To convert for real, with no other board job running:  "
                      ".venv/bin/python scripts/migrate_board_to_parts.py --apply")
                print(GIT_STEPS.format(repo=REPO))
                return 0

            # ---- apply -----------------------------------------------------------------
            block = bp.make_block(entries, rows_per_part=res["rows_per_part"], cap=cap)
            print("hashing the plain files (the slow part) ...", flush=True)
            pre = wa._seal_precompute(docs, meta, block)
            print("moving the parts into place and sealing ...", flush=True)
            for e in entries:
                os.replace(stage / e["name"], docs / e["name"])
            bp.remove_stale_parts(docs, len(entries))
            meta2 = dict(meta)
            meta2["board_parts"] = block
            wa._atomic_write_bytes(docs / "run_meta.json",
                                   json.dumps(meta2, ensure_ascii=False, default=str, indent=2).encode("utf-8"))
            wa.reseal_board(docs, precomputed=pre)
            v = wa.verify_manifest(docs, full=True)
            print(f"verify: ok={v['ok']} files checked={v['checked']}")
            if not v["ok"]:
                for p in v["problems"]:
                    print("  MISMATCH", p)
                return _fail("the manifest does not verify; docs/ is left as it is, see docs/RESTORE.md")
            ok, n, msg = roundtrip(source, docs, entries)
            print(f"final round trip: {'OK' if ok else 'FAILED'} ({n:,} rows compared): {msg}")
            if not ok:
                return _fail("the final parts do not reproduce the source: " + msg)
            print(f"done in {time.time() - t0:.0f}s. docs/listings.json.gz was NOT touched.")
            print(GIT_STEPS.format(repo=REPO))
            return 0
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    if lock is not None:
        try:
            with lock:
                return run()
        except wa.BoardLockBusy as exc:
            print(f"REFUSED: a board job holds the lock ({exc}); nothing was changed. Try again when it finishes.",
                  file=sys.stderr)
            return 75
    return run()


if __name__ == "__main__":
    sys.exit(main())
