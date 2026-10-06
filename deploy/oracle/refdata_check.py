#!/usr/bin/env python3
"""Reference-data preflight for the Oracle VM full run (docs/HANDOFF.md item 72, 2026-10-06).

The full run reads local reference data that is not in git and that the run never rebuilds; it
is copied from the Mac (``rsync``). A missing or damaged file fails SILENTLY: parcel_cache.lookup()
returns nothing for a county without its file, parcel_inventory._connect() creates an EMPTY table
when the database is missing, enrichment_voter_phone finds no voter files, and the run publishes a
board with whole counties' situs addresses, owners, values, sqft estimates or phones missing,
with exit 0. So vm_run.sh refuses to start unless this passes.

REQUIRED (missing, empty, damaged = refuse)
    data/parcel_cache/<county>.sqlite   every county file the Mac's manifest lists (table parcels)
    data/sc_footprints.db               building footprints (table footprints)
    data/parcel_inventory.db            parcel inventory (table parcels)
    data/footprints_src/{North,South}Carolina.geojson.zip   footprint sources (zip CRC check)
RECOMMENDED (missing = a loud warning; present but damaged = refuse)
    data/ncvoter/ncvoter*.txt           NC voter files: the NC owner-phone match
    data/sc_parcel_mailing.db           SC bulk assessor mailing roll (table sc_parcel_mailing)
    data/sc_cama.db                     SC assessor CAMA (table sc_cama)

A SQLite file passes when it opens read-only, ``PRAGMA quick_check`` answers ok (a file cut short
by an interrupted copy fails here), and its table exists and has a row. The manifest
(data/refdata_manifest.json, written on the Mac by ``write-manifest`` and copied WITH the data)
is what makes "every county" checkable: without it a half-finished copy of data/parcel_cache/
would look complete. Parcel-cache files older than parcel_cache.CACHE_VALUE_MAX_AGE_DAYS (10, by
mtime: copy with rsync -a/-t so the Mac's mtimes survive) are reported: their market and tax
values are not used by the run.

    python3 deploy/oracle/refdata_check.py write-manifest     # on the Mac, before the copy
    python3 deploy/oracle/refdata_check.py verify             # on the VM (vm_run.sh does this)
Exit 0 = pass (warnings allowed), 1 = refuse. Standard library only: runs before ``uv sync``.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "data/refdata_manifest.json"
PARCEL_CACHE = "data/parcel_cache"
PARCEL_CACHE_TABLE = "parcels"
#: parcel_cache.CACHE_VALUE_MAX_AGE_DAYS (not imported: this runs before the venv exists)
CACHE_VALUE_MAX_AGE_DAYS = 10.0

REQUIRED: dict[str, tuple[str, str | None]] = {
    "data/sc_footprints.db": ("sqlite", "footprints"),
    "data/parcel_inventory.db": ("sqlite", "parcels"),
    "data/footprints_src/NorthCarolina.geojson.zip": ("zip", None),
    "data/footprints_src/SouthCarolina.geojson.zip": ("zip", None),
}
RECOMMENDED: dict[str, tuple[str, str | None]] = {
    "data/ncvoter": ("dir", "ncvoter*.txt"),
    "data/sc_parcel_mailing.db": ("sqlite", "sc_parcel_mailing"),
    "data/sc_cama.db": ("sqlite", "sc_cama"),
}


def _sqlite_problem(p: Path, table: str) -> str | None:
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            res = con.execute("PRAGMA quick_check(1)").fetchone()
            if not res or res[0] != "ok":
                return f"quick_check: {res[0] if res else 'no answer'}"
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                               (table,)).fetchone():
                return f"no table {table!r}"
            if con.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone() is None:
                return f"table {table!r} is empty"
        finally:
            con.close()
    except sqlite3.Error as exc:
        return f"sqlite: {exc}"
    return None


def _zip_problem(p: Path) -> str | None:
    try:
        with zipfile.ZipFile(p) as zf:
            bad = zf.testzip()
            if bad is not None:
                return f"zip member {bad!r} fails its CRC"
            if not zf.namelist():
                return "zip is empty"
    except (zipfile.BadZipFile, OSError) as exc:
        return f"zip: {exc}"
    return None


def _check(root: Path, rel: str, kind: str, arg: str | None) -> str | None:
    """None when the file is present and sound, else the problem."""
    p = root / rel
    if kind == "dir":
        files = sorted(p.glob(arg or "*")) if p.is_dir() else []
        if not files:
            return "missing" if not p.exists() else f"no {arg} files"
        empty = [f.name for f in files if f.stat().st_size == 0]
        return f"empty files: {', '.join(empty[:5])}" if empty else None
    if not p.is_file():
        return "missing"
    if p.stat().st_size == 0:
        return "empty file"
    return _sqlite_problem(p, arg or "") if kind == "sqlite" else _zip_problem(p)


def _cache_files(root: Path) -> list[str]:
    d = root / PARCEL_CACHE
    return sorted(f"{PARCEL_CACHE}/{f.name}" for f in d.glob("*.sqlite")) if d.is_dir() else []


def write_manifest(root: Path, out: Path) -> int:
    files = {}
    for rel in _cache_files(root) + sorted(REQUIRED) + sorted(RECOMMENDED):
        p = root / rel
        if p.is_file():
            st = p.stat()
            files[rel] = {"size": st.st_size, "mtime": datetime.fromtimestamp(
                st.st_mtime, timezone.utc).isoformat(timespec="seconds")}
    missing = [rel for rel in REQUIRED if rel not in files]
    n_cache = sum(1 for rel in files if rel.startswith(PARCEL_CACHE + "/"))
    if not n_cache or missing:
        print(f"refdata: NOT writing a manifest: {n_cache} parcel-cache files, missing here: "
              f"{', '.join(missing) or 'none'}", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps({"written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "host": socket.gethostname(), "files": files}, indent=1))
    os.replace(tmp, out)
    total = sum(v["size"] for v in files.values())
    print(f"refdata: manifest {out} lists {len(files)} files ({n_cache} parcel-cache counties, "
          f"{total / 2**30:.1f} GiB). Copy it WITH the data.")
    return 0


def verify(root: Path, manifest_path: Path) -> int:
    t0 = time.monotonic()
    problems: list[str] = []
    warnings: list[str] = []
    try:
        man = json.loads(manifest_path.read_text())
        listed = man.get("files") or {}
    except FileNotFoundError:
        print(f"refdata: REFUSED: no manifest at {manifest_path}. On the Mac: "
              f"python3 deploy/oracle/refdata_check.py write-manifest, then copy "
              f"{MANIFEST} with the data (docs/HANDOFF.md item 72).")
        return 1
    except (OSError, ValueError) as exc:
        print(f"refdata: REFUSED: manifest {manifest_path} unreadable: {exc}")
        return 1

    cache = sorted(set(_cache_files(root)) | {r for r in listed if r.startswith(PARCEL_CACHE + "/")})
    if not cache:
        problems.append(f"{PARCEL_CACHE}/: no county files and none listed in the manifest")
    checks = [(rel, "sqlite", PARCEL_CACHE_TABLE, True) for rel in cache]
    checks += [(rel, k, a, True) for rel, (k, a) in REQUIRED.items()]
    checks += [(rel, k, a, False) for rel, (k, a) in RECOMMENDED.items()]

    total = 0
    stale = []
    now = time.time()
    for rel, kind, arg, required in checks:
        why = _check(root, rel, kind, arg)
        p = root / rel
        if why == "missing" and not required:
            warnings.append(f"{rel}: missing (recommended: the run uses it; see refdata_check.py)")
            continue
        if why:
            problems.append(f"{rel}: {why}")
            continue
        if p.is_file():
            size = p.stat().st_size
            total += size
            want = (listed.get(rel) or {}).get("size")
            if want is not None and want != size:
                warnings.append(f"{rel}: {size:,} bytes, the manifest says {want:,} "
                                f"(passed its integrity check; changed since the copy?)")
            if rel.startswith(PARCEL_CACHE + "/") and (now - p.stat().st_mtime) / 86400 > CACHE_VALUE_MAX_AGE_DAYS:
                stale.append(p.stem)
        elif p.is_dir():
            total += sum(f.stat().st_size for f in p.glob(arg or "*"))
    if stale:
        warnings.append(f"{len(stale)} parcel-cache counties older than {CACHE_VALUE_MAX_AGE_DAYS:g} "
                        f"days (their market/tax values are not used): {', '.join(stale[:12])}"
                        + (" ..." if len(stale) > 12 else ""))

    for w in warnings:
        print(f"refdata: WARNING: {w}")
    for pr in problems:
        print(f"refdata: PROBLEM: {pr}")
    secs = time.monotonic() - t0
    if problems:
        print(f"refdata: REFUSED: {len(problems)} problem(s) in the reference data "
              f"({len(cache)} parcel-cache files checked, {secs:.0f}s)")
        return 1
    print(f"refdata: OK: {len(cache)} parcel-cache counties + {len(REQUIRED)} required files "
          f"intact ({total / 2**30:.1f} GiB, quick_check ok, manifest of "
          f"{man.get('written_at', '?')} from {man.get('host', '?')}), "
          f"{len(warnings)} warning(s), {secs:.0f}s")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", choices=("verify", "write-manifest"))
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent.parent),
                    help="repo root (default: this checkout)")
    ap.add_argument("--manifest", default=None, help=f"default <root>/{MANIFEST}")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    manifest = Path(a.manifest) if a.manifest else root / MANIFEST
    return write_manifest(root, manifest) if a.mode == "write-manifest" else verify(root, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
