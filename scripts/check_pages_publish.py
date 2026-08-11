#!/usr/bin/env python3
"""Prove that GitHub Pages will actually publish the dashboard's payload files.

Jekyll's exclude/include are PREFIX matches, not globs:

    Jekyll::EntryFilter#glob_include?  ->  entry_with_source.start_with?(pattern_with_source)

so `exclude: listings.json` also drops `listings.json.gz`, because the .gz name
starts with the excluded string. That bug has silently 404'd this dashboard's
data on the live site before (see the header of docs/_config.yml). It re-arms
every time someone adds a new payload file and follows the file's own
convention of excluding the uncompressed twin.

This script reimplements Jekyll's decision over the REAL contents of docs/ plus
the exclude/include lists in docs/_config.yml, and fails loudly if any file the
dashboard fetches would be dropped from the deploy.

Run it after ANY edit to docs/_config.yml:

    python3 scripts/check_pages_publish.py

Exit code 0 = every required payload publishes. 1 = something would 404.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CONFIG = DOCS / "_config.yml"
WEB_ARTIFACT = ROOT / "src" / "foreclosure_scraper" / "web_artifact.py"


def _shard_dir_name() -> str:
    """Read DETAIL_SHARD_DIR out of web_artifact.py without importing it.

    This script must run under a bare system python3 with no dependencies (it is
    called from shell wrappers and from the Pages workflow before `uv sync`), and
    importing the package pulls in structlog and pydantic. Reading the constant
    is still better than hardcoding it: a rename of the shard directory changes
    what this check asks about, instead of leaving it asking about a path that
    no longer exists and passing vacuously.
    """
    try:
        text = WEB_ARTIFACT.read_text()
    except OSError:
        return "detail_shards"
    m = re.search(r'^DETAIL_SHARD_DIR\s*=\s*[\'"]([^\'"]+)[\'"]', text, re.M)
    return m.group(1) if m else "detail_shards"


DETAIL_SHARD_DIR = _shard_dir_name()

# Files the dashboard fetches at runtime. If any of these is dropped from the
# Pages deploy, the board 404s. Keep in sync with docs/dashboard.js fetches and
# docs/index.html <link>/<script> tags.
REQUIRED = [
    "index.html",
    "dashboard.js",
    "style.css",
    "premium.css",
    "listings.json.gz",
    "listings_detail.json.gz",
    "listings_slim.json.gz",
    # The mobile detail payload. It was NOT listed here, and that hole was
    # provable: adding `- detail_shards` to docs/_config.yml's exclude turned
    # tests/test_detail_shards.py red and left this script at exit 0. A shard is
    # the only payload the LEAN client fetches to open a lead, so dropping the
    # directory 404s every detail panel on every phone while desktop is fine.
    #
    # The FIRST shard specifically, not the directory: Jekyll's decision is per
    # ENTRY, and `detail_shards/00000.json.gz` is what proves both the directory
    # rule and the file inside it survive. It is in SIMULATED too, so this stays
    # meaningful on a checkout where no publish has run yet.
    f"{DETAIL_SHARD_DIR}/00000.json.gz",
    "run_meta.json",
    "multifamily.json",
    "foreclosure_sold_pool.json",
]

# Payload files that may not exist on disk yet (a build step has not run) but
# must still be simulated, or the check passes vacuously and the trap survives.
SIMULATED = [
    "listings.json",
    "listings.json.gz",
    "listings_detail.json",
    "listings_detail.json.gz",
    "listings_slim.json",
    "listings_slim.json.gz",
    f"{DETAIL_SHARD_DIR}/00000.json.gz",
]


def parse_config(text: str) -> tuple[list[str], list[str]]:
    """Minimal YAML read of the two top-level list keys we care about.

    Deliberately not a YAML library: this must run with no dependencies, and
    the only structure it needs is `key:` followed by `  - value` lines.
    """
    lists: dict[str, list[str]] = {"exclude": [], "include": []}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")) and stripped.endswith(":"):
            key = stripped[:-1].strip()
            current = key if key in lists else None
            continue
        if current and stripped.startswith("- "):
            value = stripped[2:].split("#", 1)[0].strip().strip("'\"")
            if value:
                lists[current].append(value)
            continue
        if not line.startswith((" ", "\t")):
            current = None
    return lists["exclude"], lists["include"]


def prefix_match(entry: str, patterns: list[str]) -> str | None:
    """Jekyll's rule: entry_with_source.start_with?(pattern_with_source).

    Both sides are joined onto the site source first, so the comparison is on
    whole paths relative to docs/. Returns the matching pattern, or None.
    """
    for pattern in patterns:
        p = pattern.rstrip("/")
        if entry == p or entry.startswith(p):
            return pattern
    return None


def is_special(entry: str) -> bool:
    """Jekyll drops these regardless of `include` (EntryFilter#special?)."""
    for segment in entry.split("/"):
        if segment.startswith(("_", ".", "#")) or segment.endswith("~"):
            return True
    return False


def decide(entry: str, exclude: list[str], include: list[str]) -> tuple[bool, str]:
    """Return (published, reason) for one entry path relative to docs/."""
    inc = prefix_match(entry, include)
    if inc is not None:
        return True, f"include '{inc}' overrides"
    if is_special(entry):
        return False, "special (leading _ . # or trailing ~)"
    exc = prefix_match(entry, exclude)
    if exc is not None:
        return False, f"exclude '{exc}' prefix-matches"
    return True, "no rule matches"


def main() -> int:
    exclude, include = parse_config(CONFIG.read_text())
    if not exclude:
        print(f"FAIL: parsed no exclude entries from {CONFIG} — parser or file is wrong")
        return 1

    entries = set(SIMULATED)
    for path in DOCS.rglob("*"):
        if path.is_file():
            entries.add(path.relative_to(DOCS).as_posix())

    print(f"docs/_config.yml exclude ({len(exclude)}): {', '.join(exclude)}")
    print(f"docs/_config.yml include ({len(include)}): {', '.join(include)}")
    print(f"entries evaluated: {len(entries)} "
          f"({len(entries) - len([e for e in entries if (DOCS / e).exists()])} simulated)\n")

    verdicts = {e: decide(e, exclude, include) for e in sorted(entries)}

    print("REQUIRED PAYLOAD FILES")
    failures = []
    for name in REQUIRED:
        published, reason = verdicts.get(name, decide(name, exclude, include))
        on_disk = "" if (DOCS / name).exists() else "  [not on disk yet — simulated]"
        mark = "PUBLISH" if published else "DROPPED"
        print(f"  {mark:8} {name:34} {reason}{on_disk}")
        if not published:
            failures.append(name)

    dropped = sorted(e for e, (ok, _) in verdicts.items() if not ok)
    by_rule: dict[str, list[str]] = {}
    for entry in dropped:
        by_rule.setdefault(verdicts[entry][1], []).append(entry)

    print(f"\nDROPPED FROM DEPLOY: {len(dropped)} of {len(entries)} entries")
    for reason in sorted(by_rule, key=lambda r: -len(by_rule[r])):
        names = by_rule[reason]
        sample = ", ".join(names[:4]) + (f", … (+{len(names) - 4} more)" if len(names) > 4 else "")
        print(f"  {len(names):5}  {reason}\n           {sample}")

    if failures:
        print(f"\nFAIL: {len(failures)} required file(s) would 404 on the live site: "
              f"{', '.join(failures)}")
        print("Fix: every `- <name>.json` in `exclude` needs `- <name>.json.gz` in `include`.")
        return 1
    print("\nOK: every required dashboard payload survives the Pages deploy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
