"""Convert verification ledgers from one file to the sharded layout, OFFLINE (no network).

docs/handoff/verification/<signal>.json becomes docs/handoff/verification/<signal>/manifest.json
plus NNN.json shards (verification/ledger.py, LAYOUTS): entries bucketed by a stable hash of the
entry key, each shard under 8 MiB, every entry line byte for byte the line the single file had.

  uv run python scripts/ledger_migrate.py                    # dry run: plan + in-memory round trip
  uv run python scripts/ledger_migrate.py --apply            # convert (takes the sweep's run lock)
  uv run python scripts/ledger_migrate.py --apply --commit   # ...and commit only the ledger paths
  uv run python scripts/ledger_migrate.py --signal tax_lien --ledger-dir <copy of the directory>

Per ledger:
  file    dry run: bucket count, shard sizes, and the round trip done in memory. --apply writes
          the shards beside the file, re-reads them strictly, checks that the shards hold
          exactly the file's entry lines, byte for byte, then removes the file. On any
          difference the new shard directory is removed, the file stays, and the exit is 1.
  mixed   both layouts (an older writer wrote the file after a migration): --apply merges them
          (the ledger's merge rules), writes the shards, checks they hold exactly the merged
          entries and every key of both copies, then removes the file.
  shards  checked (manifest, sha256, unlisted shards, the cap). --apply re-seals one that fails
          its manifest but can be read (re-written from what it holds). A clean one is left
          untouched, so a second --apply changes nothing.

--commit makes a local pathspec commit of the ledger paths only (both layouts, removals
included: ledger.commit_ledgers); it never pushes. Without it the working tree is left ready
to commit:  git add -A -- docs/handoff/verification && git commit -- docs/handoff/verification
Exit 0: done or nothing to do; 1: a check failed, a ledger is unreadable, or the lock is held.
"""
from __future__ import annotations

import argparse
import fcntl
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.verification import ledger as L  # noqa: E402
from foreclosure_scraper.verification.core import parse_ts  # noqa: E402

RUN_LOCK = REPO / "logs" / ".verification_sweep.lock"


def shard_lines_on_disk(sd: Path) -> list[str]:
    """Every entry line of every shard file the manifest lists, as it is on disk."""
    m = L.read_manifest(sd) or {}
    out: list[str] = []
    for ent in m.get("shards") or []:
        got = L.raw_row_lines((sd / str(ent.get("file"))).read_bytes())
        if got is None:
            raise L.LedgerUnreadable(f"{sd / str(ent.get('file'))}: not in the line layout")
        out.extend(got)
    return out


def _sizes(shards: list[dict]) -> str:
    b = [int(s["bytes"]) for s in shards]
    if not b:
        return "0 shards"
    return (f"{len(b)} shards, {sum(int(s['rows']) for s in shards):,} entries, "
            f"{sum(b):,} bytes; shard min {min(b):,} / median {sorted(b)[len(b) // 2]:,} / "
            f"max {max(b):,} bytes")


def plan_in_memory(led: L.Ledger, cap: int) -> tuple[int, list[dict], list[str]]:
    """(buckets, [{file, rows, bytes}], entry lines of the rendered shards): the shards a save
    would write, rendered in memory only."""
    lines = {k: L.row_line(k, v) for k, v in led.rows.items()}
    n, groups = led.plan_shards(lines, max_shard_bytes=cap)
    shards, got = [], []
    for b, keys in groups.items():
        data = L.render({"kind": L.SHARD_KIND, "schema": L.SCHEMA, "signal": led.signal,
                         "bucket": b, "buckets": n}, [lines[k] for k in keys])
        shards.append({"file": L.shard_name(b), "rows": len(keys), "bytes": len(data)})
        got.extend(L.raw_row_lines(data) or [])
    return n, shards, got


def file_lines(f: Path, led: L.Ledger) -> tuple[list[str], bool]:
    """(the single file's entry lines as on disk, True) or, for a file not in the line layout,
    (the canonical lines of its parsed entries, False)."""
    raw = L.raw_row_lines(f.read_bytes())
    if raw is not None and len(raw) == len(led.rows):
        return raw, True
    return [L.row_line(k, v) for k, v in sorted(led.rows.items())], False


def _all_keys(rows: dict) -> set[str]:
    out = set(rows)
    for e in rows.values():
        out.update(e.get("keys") or [])
    return out


def migrate_one(sig: str, d: Path, *, apply: bool, cap: int, say=print) -> tuple[bool, bool]:
    """(ok, wrote) for one ledger."""
    layout = L.ledger_layout(sig, d)
    f, sd = L.ledger_path(sig, d), L.shard_dir(sig, d)
    if layout == "none":
        say(f"{sig}: no ledger")
        return True, False

    if layout == "shards":
        issues = L.check_layout(d, max_shard_bytes=cap).get(sig, {}).get("issues") or []
        try:
            L.Ledger.load(sig, d)                          # strict: what a writer would see
        except L.LedgerUnreadable as exc:
            issues = issues or [str(exc)[:300]]
        m = L.read_manifest(sd) or {}
        if not issues:
            say(f"{sig}: already sharded, clean ({m.get('buckets')} buckets; "
                f"{_sizes(m.get('shards') or [])})")
            return True, False
        say(f"{sig}: sharded, {len(issues)} issue(s): " + "; ".join(issues)[:600])
        if not apply:
            return False, False
        return _reseal(sig, d, cap, say)

    if layout == "mixed":
        say(f"{sig}: BOTH layouts present ({f.name} {f.stat().st_size:,} bytes and {sd.name}/)")
        if not apply:
            try:
                led = L.Ledger.load(sig, d, recover=True)
            except L.LedgerUnreadable as exc:
                say(f"{sig}: unreadable: {exc}")
                return False, False
            n, shards, _ = plan_in_memory(led, cap)
            say(f"{sig}: dry run: merged {len(led.rows):,} entries -> {n} buckets; {_sizes(shards)}")
            return True, False
        return _reseal(sig, d, cap, say)

    # layout == "file"
    try:
        led = L.Ledger.load(sig, d)
    except L.LedgerUnreadable as exc:
        say(f"{sig}: unreadable, left as it is: {exc}")
        return False, False
    before, raw = file_lines(f, led)
    n, shards, rendered = plan_in_memory(led, cap)
    same = sorted(rendered) == sorted(before)
    say(f"{sig}: single file {f.stat().st_size:,} bytes, {len(led.rows):,} entries -> {n} buckets; "
        f"{_sizes(shards)}; round trip in memory: "
        f"{'byte-identical' if same else 'DIFFERS'}{'' if raw else ' (canonical lines: file not in line layout)'}")
    if not same:
        return False, False
    if not apply:
        return True, False
    existed = sd.exists()
    when = parse_ts(led.generated_at)
    led.save(sd, now=when, scrub=False, max_shard_bytes=cap)
    try:
        back = L.Ledger.load_shards(sd, strict=True)
        after = shard_lines_on_disk(sd)
        ok = sorted(after) == sorted(before) and len(back.rows) == len(led.rows) \
            and back.last_run == led.last_run
        why = "" if ok else (f"{len(after):,} lines on disk vs {len(before):,} in the file, "
                             f"{len(back.rows):,} entries read back")
    except L.LedgerUnreadable as exc:
        ok, why = False, str(exc)[:300]
    if not ok:
        if not existed:
            shutil.rmtree(sd, ignore_errors=True)
        say(f"{sig}: FAILED the on-disk check ({why}); {f.name} kept"
            + ("" if existed else f", {sd.name}/ removed"))
        return False, True
    f.unlink()
    say(f"{sig}: migrated: {len(after):,} entry lines byte-identical on disk; {f.name} removed; "
        f"{_sizes((L.read_manifest(sd) or {}).get('shards') or [])}")
    return True, True


def _reseal(sig: str, d: Path, cap: int, say) -> tuple[bool, bool]:
    """Re-write a readable ledger (mixed layouts, or shards that fail their manifest) as clean
    shards, and remove the single file."""
    f, sd = L.ledger_path(sig, d), L.shard_dir(sig, d)
    try:
        led = L.Ledger.load(sig, d, recover=True)
    except L.LedgerUnreadable as exc:
        say(f"{sig}: unreadable, left as it is: {exc}")
        return False, False
    sources = dict(led.rows)
    if f.is_file():
        sources.update({k: v for k, v in L.Ledger.load_file(f).rows.items() if k not in sources})
    want = sorted(L.row_line(k, v) for k, v in led.rows.items())
    keys_before = _all_keys(sources)
    led.save(sd, now=parse_ts(led.generated_at), scrub=False, max_shard_bytes=cap)
    try:
        back = L.Ledger.load_shards(sd, strict=True)
        after = sorted(shard_lines_on_disk(sd))
        lost = keys_before - _all_keys(back.rows)
        ok = after == want and not lost
        why = "" if ok else f"{len(lost)} key(s) lost" if lost else "entry lines differ"
    except L.LedgerUnreadable as exc:
        ok, why = False, str(exc)[:300]
    if not ok:
        say(f"{sig}: FAILED the re-seal check ({why}); nothing removed")
        return False, True
    if f.is_file():
        f.unlink()
    say(f"{sig}: re-sealed: {len(after):,} entries; "
        f"{_sizes((L.read_manifest(sd) or {}).get('shards') or [])}"
        + (f"; {f.name} removed" if not f.exists() else ""))
    return True, True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--signal", action="append", default=None,
                    help="ledger(s) to convert (repeatable or comma-separated); default: all")
    ap.add_argument("--ledger-dir", default=None, help="default docs/handoff/verification")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--commit", action="store_true",
                    help="with --apply: local pathspec commit of the ledger paths (no push)")
    ap.add_argument("--max-shard-bytes", type=int, default=L.SHARD_MAX_BYTES)
    args = ap.parse_args(argv)
    d = Path(args.ledger_dir) if args.ledger_dir else L.ledger_dir()
    wanted = [s.strip() for a in (args.signal or []) for s in a.split(",") if s.strip()]
    sigs = wanted or L.signals_on_disk(d)
    if not sigs:
        print(f"no ledgers in {d}")
        return 0
    if not args.apply:
        oks = [migrate_one(s, d, apply=False, cap=args.max_shard_bytes)[0] for s in sigs]
        print("dry run: nothing written" + ("" if all(oks) else "; a check FAILED"))
        return 0 if all(oks) else 1

    RUN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(RUN_LOCK, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("a verification sweep holds logs/.verification_sweep.lock: stop it first")
        fh.close()
        return 1
    try:
        results = {s: migrate_one(s, d, apply=True, cap=args.max_shard_bytes) for s in sigs}
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
    ok = all(r[0] for r in results.values())
    wrote = [s for s, r in results.items() if r[1] and r[0]]
    if args.commit and wrote:
        res, detail = L.commit_ledgers([L.shard_dir(s, d) for s in wrote],
                                       "verification ledgers: sharded layout for "
                                       + ", ".join(wrote) + " (scripts/ledger_migrate.py)")
        print(f"git: {res} {detail}")
        ok = ok and res in ("committed", "unchanged")
    elif wrote:
        print("ready to commit: git add -A -- " + " ".join(
            f"{L.ledger_path(s, d)} {L.shard_dir(s, d)}" for s in wrote))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
