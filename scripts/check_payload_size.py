#!/usr/bin/env python3
"""Report every publishable payload file against GitHub's limits.

GitHub rejects a push containing a file over 100 MiB and warns above 50 MiB. On
2026-09-21 docs/listings.json.gz was 84.3 MiB and growing 2 to 4 MiB a day, which puts
the wall 4 to 8 days out (audit O1). Every publisher here commits first and pushes
second and prints a message and exits 0 when the push fails, so the first anyone learns
of it is a stale dashboard. This script is the measurement; scripts/job_watch.py runs it
from launchd and alerts long before the wall.

The board is now docs/listings_part_NNN.json.gz (src/foreclosure_scraper/board_parts.py):
contiguous gzip slices, each under 24 MiB. Every part is checked on its own against GitHub's
limits AND against the 24 MiB part cap (status OVER_PART, exit 1), the board's total across
parts is printed as one line, and a part set that disagrees with docs/board.manifest.json (a
missing part, a wrong size, a stale extra part, a single listings.json.gz still shadowing the
set) is reported as a PARTS PROBLEM and exits 2 (the lingering single file alone is a warning, exit 1).

    python3 scripts/check_payload_size.py            # human table
    python3 scripts/check_payload_size.py --json     # machine readable
    python3 scripts/check_payload_size.py --warn-mib 80 --gate-mib 95

Exit status: 0 all files under the warn line, 1 at least one file over WARN (default
50 MiB, GitHub's own warning), 2 at least one file over GATE (default 95 MiB, the
repo's pre-commit size gate; GitHub's hard limit is 100 MiB).

Stdlib only and Python 3.9 compatible: it runs under /usr/bin/python3 from launchd.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

MIB = 1024 * 1024
GITHUB_HARD_MIB = 100
GITHUB_WARN_MIB = 50
PAGES_SITE_WARN_MB = 600      # .github/workflows/pages.yml warns here
PAGES_SITE_FAIL_MB = 950      # ... and fails the build here

ROOT = Path(__file__).resolve().parent.parent

# Same list as scripts/board_payload.sh (a file that does not exist is skipped). The board itself
# is docs/listings_part_NNN.json.gz (collect() adds every part on disk); docs/listings.json.gz is
# the legacy single file, still reported while one lingers so a stale 84 MiB copy cannot hide.
PAYLOAD_FILES = (
    "docs/listings.json.gz",
    "docs/listings_detail.json.gz",
    "docs/listings_slim.json.gz",
    "docs/run_meta.json",
    "docs/run_health.json",
    "docs/board.manifest.json",
    "docs/foreclosure_sold_pool.json",
    "docs/multifamily.json",
)
PAYLOAD_DIRS = ("docs/detail_shards", "docs/parcel_photos")

# The per-file cap for a board part (src/foreclosure_scraper/board_parts.py PART_MAX_BYTES, 24 MiB;
# each part also has to fit Cloudflare's 25 MiB per-asset cap). A part over it means the split did
# not run, or something wrote a part by hand: WARN. GitHub's own limits still apply on top.
PART_MAX_MIB = 24.0
PART_GLOB = "listings_part_*.json.gz"


def collect(root: Path) -> list:
    rows = []
    for rel in PAYLOAD_FILES:
        p = root / rel
        if p.is_file():
            rows.append((rel, p.stat().st_size))
    docs = root / "docs"
    if docs.is_dir():
        for p in sorted(docs.glob(PART_GLOB)):
            if p.is_file():
                rows.append((str(p.relative_to(root)), p.stat().st_size))
    for rel in PAYLOAD_DIRS:
        d = root / rel
        if d.is_dir():
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    rows.append((str(p.relative_to(root)), p.stat().st_size))
    return rows


def site_bytes(root: Path) -> int:
    """Bytes of tracked files under docs/: what GitHub Pages actually deploys."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "docs"],
                             capture_output=True, timeout=30).stdout
        total = 0
        for name in out.split(b"\0"):
            if not name:
                continue
            p = root / name.decode("utf-8", "replace")
            if p.is_file():
                total += p.stat().st_size
        return total
    except Exception:  # noqa: BLE001
        return sum(sz for _, sz in collect(root))


def parts_problems(root: Path) -> tuple:
    """(problems, warnings) from a cheap consistency check of the board parts against
    docs/board.manifest.json: names and sizes (problems), and a lingering single
    listings.json.gz that shadows nothing but wastes 84 MiB of every deploy (warning).
    No hashing here (job_watch runs this hourly); scripts/board_manifest.py --verify hashes."""
    out = []
    warn = []
    docs = root / "docs"
    try:
        man = json.loads((docs / "board.manifest.json").read_text())
    except (OSError, ValueError):
        man = None
    blk = man.get("parts") if isinstance(man, dict) else None
    on_disk = sorted(p.name for p in docs.glob(PART_GLOB) if p.is_file()) if docs.is_dir() else []
    if isinstance(blk, dict) and isinstance(blk.get("files"), list):
        listed = [e.get("name") for e in blk["files"] if isinstance(e, dict)]
        for e in blk["files"]:
            if not isinstance(e, dict):
                continue
            p = docs / str(e.get("name"))
            if not p.is_file():
                out.append("%s is in the manifest but missing on disk" % e.get("name"))
            elif e.get("bytes") is not None and p.stat().st_size != e["bytes"]:
                out.append("%s is %d bytes, the manifest says %s (a torn or half-written set)"
                           % (e.get("name"), p.stat().st_size, e["bytes"]))
        for n in on_disk:
            if n not in listed:
                out.append("%s is on disk but not in the manifest (a stale part)" % n)
        if (docs / "listings.json.gz").is_file():
            warn.append("docs/listings.json.gz still exists beside the parts: retire it (git rm) "
                        "so the stale single file stops shipping")
    return out, warn


def evaluate(rows: list, warn_mib: float, gate_mib: float, part_max_mib: float = PART_MAX_MIB) -> dict:
    """Every file against GitHub's limits, and every board part against the PART cap.

    The per-file check: a listings_part_NNN.json.gz over `part_max_mib` is WARN (status
    "OVER_PART") even though it is far below GitHub's 100 MiB, because the split's whole
    guarantee is that no part gets close; a part that is over the cap means the writer did not cut
    it. The board's TOTAL (all parts) is reported separately and is not a per-file figure: it is
    the number that grows 2 to 4 MiB a day and it is fine for it to."""
    files = []
    worst = 0
    parts_total = 0
    parts_n = 0
    for rel, size in rows:
        mib = size / MIB
        is_part = os.path.basename(rel).startswith("listings_part_")
        if mib >= gate_mib:
            status, code = "BLOCK", 2
        elif mib >= warn_mib:
            status, code = "WARN", 1
        elif is_part and mib > part_max_mib:
            status, code = "OVER_PART", 1
        else:
            status, code = "ok", 0
        if is_part:
            parts_total += size
            parts_n += 1
        worst = max(worst, code)
        files.append({"path": rel, "bytes": size, "mib": round(mib, 2),
                      "pct_of_github_limit": round(100.0 * mib / GITHUB_HARD_MIB, 1),
                      "status": status})
    files.sort(key=lambda f: -f["bytes"])
    res = {"worst": worst, "files": files}
    if parts_n:
        res["board_parts"] = {"count": parts_n, "total_mib": round(parts_total / MIB, 2),
                              "largest_mib": max(f["mib"] for f in files
                                                 if os.path.basename(f["path"]).startswith("listings_part_")),
                              "part_max_mib": part_max_mib}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--warn-mib", type=float, default=float(os.environ.get("PAYLOAD_WARN_MIB", GITHUB_WARN_MIB)))
    ap.add_argument("--gate-mib", type=float, default=float(os.environ.get("PAYLOAD_GATE_MIB", 95)))
    ap.add_argument("--part-max-mib", type=float, default=float(os.environ.get("PAYLOAD_PART_MAX_MIB", PART_MAX_MIB)),
                    help="per-file cap for a board part (default 24 MiB)")
    ap.add_argument("--top", type=int, default=12, help="rows shown in the table")
    ap.add_argument("--no-site", action="store_true", help="skip the Pages deploy-size line")
    args = ap.parse_args(argv)

    root = Path(args.root)
    res = evaluate(collect(root), args.warn_mib, args.gate_mib, args.part_max_mib)
    res["parts_problems"], res["parts_warnings"] = parts_problems(root)
    if res["parts_problems"]:
        res["worst"] = max(res["worst"], 2)
    elif res["parts_warnings"]:
        res["worst"] = max(res["worst"], 1)
    site = None
    if not args.no_site:
        b = site_bytes(root)
        site = {"mb": round(b / 1_000_000, 1), "warn_mb": PAGES_SITE_WARN_MB, "fail_mb": PAGES_SITE_FAIL_MB,
                "status": "FAIL" if b / 1_000_000 >= PAGES_SITE_FAIL_MB
                else "WARN" if b / 1_000_000 >= PAGES_SITE_WARN_MB else "ok"}
        if site["status"] == "FAIL":
            res["worst"] = max(res["worst"], 2)
        elif site["status"] == "WARN":
            res["worst"] = max(res["worst"], 1)
    res["site"] = site
    res["limits"] = {"github_hard_mib": GITHUB_HARD_MIB, "warn_mib": args.warn_mib, "gate_mib": args.gate_mib}

    if args.json:
        print(json.dumps(res, indent=1))
        return res["worst"]

    print(f"payload files vs GitHub limits (warn {args.warn_mib:g} MiB, repo gate {args.gate_mib:g} MiB, "
          f"GitHub hard limit {GITHUB_HARD_MIB} MiB)")
    for f in res["files"][: args.top]:
        print(f"  {f['status']:<5} {f['mib']:>9.2f} MiB  {f['pct_of_github_limit']:>5.1f}%  {f['path']}")
    extra = len(res["files"]) - args.top
    if extra > 0:
        print(f"  ... and {extra} smaller file(s)")
    bp = res.get("board_parts")
    if bp:
        print(f"board: {bp['count']} parts, {bp['total_mib']:.1f} MiB in all, largest {bp['largest_mib']:.1f} MiB "
              f"(cap {bp['part_max_mib']:g} MiB per part; GitHub limits apply per FILE, so the total may grow)")
    for msg in res.get("parts_problems", []):
        print(f"  PARTS PROBLEM: {msg}")
    for msg in res.get("parts_warnings", []):
        print(f"  PARTS WARNING: {msg}")
    if site:
        print(f"deployed site (tracked docs/): {site['mb']:.1f} MB  [{site['status']}]  "
              f"(Pages warns at {PAGES_SITE_WARN_MB} MB, fails the build at {PAGES_SITE_FAIL_MB} MB)")
    label = {0: "OK", 1: "WARN", 2: "BLOCK"}[res["worst"]]
    print(f"result: {label}")
    return res["worst"]


if __name__ == "__main__":
    sys.exit(main())
