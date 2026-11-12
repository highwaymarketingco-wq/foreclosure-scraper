#!/usr/bin/env python3
"""Fail while there is still time when the repository is heading into a size wall.

TWO WALLS, both hit for real in October 2026:

  per file   GitHub refuses a push that contains a blob over 100 MiB, and the pre-commit gate
             (scripts/git_size_gate.sh) refuses 95 MiB. A daily job that commits a growing file
             meets that gate one morning with no warning: its commit is refused, the job prints a
             line and exits 0, and whatever reads the file goes stale. The Mac's stealth hand-off,
             docs/handoff/stealth_leads.json, reached 93.8 MiB on 2026-10-08 (it is sharded now).
             This check fails at 90 MiB, so the fix lands while the job still works.

  Pages      GitHub Pages will not publish a site over 1 GB, and .github/workflows/pages.yml stops
             a deploy at 950 MB. The deployed site was 972 MB on 2026-10-08 and every deploy failed
             until docs/handoff/ was excluded (d0422771). This check fails at 900 MB of deployed
             size: the tracked files under docs/ that docs/_config.yml does not exclude, decided
             exactly as scripts/check_pages_publish.py decides (Jekyll's prefix rules).

WHAT IT MEASURES. The committed tree (`git ls-tree -r -l <ref>`, default HEAD): what a push sends
and what Pages builds. Untracked and uncommitted files do not count. Standard library only, and
no payload has to be checked out, so it runs anywhere in about a second.

Runs in CI (.github/workflows/tests.yml, job repo-size) on every push and pull request, and as the
repo-size check of scripts/prerun_gate.py before a run.

USAGE
    python3 scripts/repo_size_check.py                 # HEAD, default limits
    python3 scripts/repo_size_check.py --ref origin/main --json
Exit 0 under every limit (warnings allowed), 1 over a limit, 2 the tree could not be read.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MIB = 1024 * 1024
MB = 1_000_000            # Pages sizes are decimal, as in pages.yml

MAX_FILE_MIB = 90.0       # fail: 5 MiB under the pre-commit gate, 10 under GitHub's refusal
WARN_FILE_MIB = 40.0      # list: GitHub itself starts warning at 50 MB
MAX_PAGES_MB = 900.0      # fail: 50 MB under pages.yml's stop, 100 under Pages' 1 GB
WARN_PAGES_MB = 800.0


def _pages_rules():
    """parse_config and decide from scripts/check_pages_publish.py (loaded by path: scripts/ is
    not a package, and the Pages decision must have exactly one implementation)."""
    spec = importlib.util.spec_from_file_location("check_pages_publish",
                                                  REPO / "scripts" / "check_pages_publish.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse_config, mod.decide


def tracked_blobs(repo: Path, ref: str = "HEAD") -> list[tuple[str, int]]:
    """(path, bytes) of every blob in the tree at ref."""
    out = subprocess.run(["git", "ls-tree", "-r", "-l", "-z", ref], cwd=repo,
                         capture_output=True, check=True).stdout
    blobs = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        parts = meta.split()
        if len(parts) != 4 or parts[1] != b"blob":
            continue                      # submodules ("commit") carry no size
        blobs.append((path.decode("utf-8", "surrogateescape"), int(parts[3])))
    return blobs


def measure(repo: Path = REPO, ref: str = "HEAD", *, max_file_mib: float = MAX_FILE_MIB,
            warn_file_mib: float = WARN_FILE_MIB, max_pages_mb: float = MAX_PAGES_MB,
            warn_pages_mb: float = WARN_PAGES_MB) -> dict:
    blobs = tracked_blobs(repo, ref)
    big = sorted(((p, s) for p, s in blobs if s > min(warn_file_mib, max_file_mib) * MIB),
                 key=lambda x: -x[1])
    over = [(p, s) for p, s in big if s > max_file_mib * MIB]

    parse_config, decide = _pages_rules()
    cfg = subprocess.run(["git", "show", f"{ref}:docs/_config.yml"], cwd=repo,
                         capture_output=True, text=True)
    exclude, include = parse_config(cfg.stdout if cfg.returncode == 0 else "")
    by_top: Counter = Counter()
    pages_bytes = pages_files = 0
    for path, size in blobs:
        if not path.startswith("docs/"):
            continue
        rel = path[len("docs/"):]
        if not decide(rel, exclude, include)[0]:
            continue
        pages_bytes += size
        pages_files += 1
        by_top[rel.split("/")[0] + "/" if "/" in rel else rel] += size
    pages_mb = pages_bytes / MB

    problems = [f"{p} is {s / MIB:.1f} MiB (limit {max_file_mib:.0f} MiB)" for p, s in over]
    if pages_mb > max_pages_mb:
        problems.append(f"the Pages site is {pages_mb:.1f} MB (limit {max_pages_mb:.0f} MB)")
    warnings = [f"{p} is {s / MIB:.1f} MiB" for p, s in big if (p, s) not in over]
    if max_pages_mb >= pages_mb > warn_pages_mb:
        warnings.append(f"the Pages site is {pages_mb:.1f} MB (warning above "
                        f"{warn_pages_mb:.0f} MB, limit {max_pages_mb:.0f} MB)")
    return {
        "ref": ref,
        "tracked_files": len(blobs),
        "tracked_mib": round(sum(s for _, s in blobs) / MIB, 1),
        "files_over_warn": [{"path": p, "mib": round(s / MIB, 1)} for p, s in big],
        "pages_mb": round(pages_mb, 1),
        "pages_files": pages_files,
        "pages_exclude_rules": len(exclude),
        "pages_top": [{"entry": k, "mb": round(v / MB, 1)} for k, v in by_top.most_common(8)],
        "limits": {"max_file_mib": max_file_mib, "warn_file_mib": warn_file_mib,
                   "max_pages_mb": max_pages_mb, "warn_pages_mb": warn_pages_mb},
        "problems": problems,
        "warnings": warnings,
        "ok": not problems,
    }


def summary(r: dict) -> str:
    """One line, for scripts/prerun_gate.py."""
    biggest = r["files_over_warn"][0] if r["files_over_warn"] else None
    head = (f"Pages site {r['pages_mb']:.0f} MB of {r['limits']['max_pages_mb']:.0f}; largest "
            + (f"tracked file {biggest['path']} {biggest['mib']:.1f} MiB"
               if biggest else f"tracked file under {r['limits']['warn_file_mib']:.0f} MiB"))
    if r["problems"]:
        return "; ".join(r["problems"])
    return head


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--max-file-mib", type=float, default=MAX_FILE_MIB)
    ap.add_argument("--warn-file-mib", type=float, default=WARN_FILE_MIB)
    ap.add_argument("--max-pages-mb", type=float, default=MAX_PAGES_MB)
    ap.add_argument("--warn-pages-mb", type=float, default=WARN_PAGES_MB)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        r = measure(Path(a.repo), a.ref, max_file_mib=a.max_file_mib,
                    warn_file_mib=a.warn_file_mib, max_pages_mb=a.max_pages_mb,
                    warn_pages_mb=a.warn_pages_mb)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"repo size check: could not read the tree at {a.ref}: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(r, indent=1))
    else:
        print(f"repo size check at {r['ref']}: {r['tracked_files']} tracked files, "
              f"{r['tracked_mib']:,.1f} MiB")
        print(f"  Pages site: {r['pages_mb']:.1f} MB in {r['pages_files']} files "
              f"(limit {a.max_pages_mb:.0f} MB; {r['pages_exclude_rules']} exclude rules)")
        for t in r["pages_top"]:
            print(f"    {t['mb']:8.1f} MB  {t['entry']}")
        print(f"  tracked files over {a.warn_file_mib:.0f} MiB: {len(r['files_over_warn'])}")
        for f in r["files_over_warn"]:
            print(f"    {f['mib']:8.1f} MiB  {f['path']}")
        for w in r["warnings"]:
            print(f"WARN  {w}")
        for p in r["problems"]:
            print(f"FAIL  {p}")
        print("OK" if r["ok"] else "FAILED: shard, exclude or untrack the files above before "
              "the next commit or deploy is refused")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
