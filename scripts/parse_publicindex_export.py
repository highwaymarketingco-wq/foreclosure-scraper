#!/usr/bin/env python
"""Parse SAVED SC Judicial Public Index search-results HTML file(s).

The SC Public Index (``https://publicindex.sccourts.org/<County>/PublicIndex/``)
is F5/Shape bot-walled, so we DON'T scrape it here. The operator runs the
PISearch in their own browser (any court type / case sub-type — Foreclosure,
Partition, Ejectment/Possession, State Tax Lien, Judgment, ...), saves the
results page (Ctrl-S / "Save Page As"), and drops the .html file into the repo
(or a directory passed as an argument). This standalone runner scans for those
saved files, parses each with ``ingest_sc_publicindex_export``, and reports how
many rows landed in each lane per county.

This runner makes NO network request. It imports NO fetcher.

Usage:
    # scan the repo root for saved SC Public Index *.html / *.htm files
    uv run python scripts/parse_publicindex_export.py

    # parse specific files (multiple allowed)
    uv run python scripts/parse_publicindex_export.py export1.html export2.htm

    # scan a directory
    uv run python scripts/parse_publicindex_export.py ~/Downloads/pi_exports/

    # stamp a fallback county for rows whose case# can't decode one, and dump
    # the parsed Listings as JSON
    uv run python scripts/parse_publicindex_export.py export.html \
        --county Spartanburg --json out.json

    # keep rows whose sub-type matches no known lane (as ListingType.UNKNOWN)
    uv run python scripts/parse_publicindex_export.py export.html --keep-all
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Repo root default scan location.
REPO_ROOT = Path("/Users/cashhigh/foreclosure-scraper")

# Filename hints + content markers that flag a page as an SC Public Index export.
_NAME_HINTS = ("publicindex", "public_index", "pisearch", "sccourts", "sc_public")
_CONTENT_MARKERS = (
    "ContentPlaceHolder1_SearchResults",
    "publicindex.sccourts.org",
    "PISearch",
)


def _looks_like_publicindex(path: Path) -> bool:
    """True when the file name OR content indicates an SC Public Index page."""
    name = path.name.lower()
    if any(h in name for h in _NAME_HINTS):
        return True
    try:
        # Sniff the head; the marker table id / host appears early enough.
        head = path.read_text(encoding="utf-8", errors="replace")[:200_000]
    except OSError:
        return False
    return any(marker in head for marker in _CONTENT_MARKERS)


def _collect_files(args_paths: list[str]) -> list[Path]:
    """Expand argv paths (files or dirs) into a de-duplicated list of candidate
    *.html/*.htm files that look like SC Public Index exports. With no paths,
    scan the repo root recursively."""
    candidates: list[Path] = []
    roots = [Path(p) for p in args_paths] if args_paths else [REPO_ROOT]
    for root in roots:
        if root.is_file():
            candidates.append(root)
        elif root.is_dir():
            for ext in ("*.html", "*.htm"):
                candidates.extend(root.rglob(ext))
        else:
            print(f"WARN: no such path: {root}", file=sys.stderr)

    # De-dupe (rglob can double via symlinks) + keep only PublicIndex-looking.
    seen: set[Path] = set()
    out: list[Path] = []
    for p in candidates:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        if _looks_like_publicindex(p):
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "paths",
        nargs="*",
        help="saved .html/.htm file(s) or director(ies) to scan "
        "(default: repo root)",
    )
    ap.add_argument(
        "--county",
        default=None,
        help="fallback county to stamp when a case# can't decode one",
    )
    ap.add_argument(
        "--keep-all",
        action="store_true",
        help="emit rows whose sub-type matches no known lane (as UNKNOWN)",
    )
    ap.add_argument("--json", default=None, help="write parsed Listings JSON here")
    args = ap.parse_args()

    # Imported here so --help works even if deps are missing, and to keep the
    # 'no fetcher' guarantee obvious: only the offline parser is imported.
    from foreclosure_scraper.ingest_sc_publicindex_export import parse_publicindex_html

    files = _collect_files(args.paths)
    if not files:
        print(
            "No SC Public Index HTML files found. Pass a file/dir, or drop a "
            "saved PISearch results page into the repo.",
            file=sys.stderr,
        )
        return 1

    all_listings = []
    # lane -> county -> count
    tally: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for path in files:
        html = path.read_text(encoding="utf-8", errors="replace")
        # Filename fallback county: --county wins, else a county-named file.
        default_county = args.county or _county_from_filename(path)
        listings = parse_publicindex_html(
            html, default_county=default_county, keep_all_subtypes=args.keep_all
        )
        all_listings.extend(listings)
        for li in listings:
            lane = li.listing_type.value
            county = li.county or "UNKNOWN"
            tally[lane][county] += 1
        print(f"{path}: {len(listings)} row(s)", file=sys.stderr)

    # Report: rows per lane per county.
    print("\n=== SC Public Index export — rows per lane per county ===")
    if not all_listings:
        print("(no rows parsed)")
    for lane in sorted(tally):
        counties = tally[lane]
        lane_total = sum(counties.values())
        print(f"\n{lane}  (total {lane_total})")
        for county in sorted(counties):
            print(f"    {county:<16} {counties[county]}")
    print(f"\nTOTAL rows: {len(all_listings)} across {len(files)} file(s)")

    if args.json:
        payload = [json.loads(li.model_dump_json()) for li in all_listings]
        Path(args.json).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"wrote {len(payload)} Listing(s) -> {args.json}", file=sys.stderr)

    return 0


def _county_from_filename(path: Path) -> str | None:
    """Best-effort: if the saved file is named after a county (e.g.
    'Spartanburg_foreclosure.html'), use that as the fallback county."""
    from foreclosure_scraper.enrichment_lis_pendens_resolver import SC_COUNTY_BY_CODE

    stem = path.stem.lower()
    for county in SC_COUNTY_BY_CODE.values():
        if county.lower() in stem:
            return county
    return None


if __name__ == "__main__":
    raise SystemExit(main())
