#!/usr/bin/env python3
"""Report every publishable payload file against GitHub's limits.

GitHub rejects a push containing a file over 100 MiB and warns above 50 MiB. On
2026-09-21 docs/listings.json.gz was 84.3 MiB and growing 2 to 4 MiB a day, which puts
the wall 4 to 8 days out (audit O1). Every publisher here commits first and pushes
second and prints a message and exits 0 when the push fails, so the first anyone learns
of it is a stale dashboard. This script is the measurement; scripts/job_watch.py runs it
from launchd and alerts long before the wall.

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

# Same list as scripts/board_payload.sh (a file that does not exist is skipped).
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


def collect(root: Path) -> list:
    rows = []
    for rel in PAYLOAD_FILES:
        p = root / rel
        if p.is_file():
            rows.append((rel, p.stat().st_size))
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


def evaluate(rows: list, warn_mib: float, gate_mib: float) -> dict:
    files = []
    worst = 0
    for rel, size in rows:
        mib = size / MIB
        if mib >= gate_mib:
            status, code = "BLOCK", 2
        elif mib >= warn_mib:
            status, code = "WARN", 1
        else:
            status, code = "ok", 0
        worst = max(worst, code)
        files.append({"path": rel, "bytes": size, "mib": round(mib, 2),
                      "pct_of_github_limit": round(100.0 * mib / GITHUB_HARD_MIB, 1),
                      "status": status})
    files.sort(key=lambda f: -f["bytes"])
    return {"worst": worst, "files": files}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--warn-mib", type=float, default=float(os.environ.get("PAYLOAD_WARN_MIB", GITHUB_WARN_MIB)))
    ap.add_argument("--gate-mib", type=float, default=float(os.environ.get("PAYLOAD_GATE_MIB", 95)))
    ap.add_argument("--top", type=int, default=12, help="rows shown in the table")
    ap.add_argument("--no-site", action="store_true", help="skip the Pages deploy-size line")
    args = ap.parse_args(argv)

    root = Path(args.root)
    res = evaluate(collect(root), args.warn_mib, args.gate_mib)
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
    if site:
        print(f"deployed site (tracked docs/): {site['mb']:.1f} MB  [{site['status']}]  "
              f"(Pages warns at {PAGES_SITE_WARN_MB} MB, fails the build at {PAGES_SITE_FAIL_MB} MB)")
    label = {0: "OK", 1: "WARN", 2: "BLOCK"}[res["worst"]]
    print(f"result: {label}")
    return res["worst"]


if __name__ == "__main__":
    sys.exit(main())
