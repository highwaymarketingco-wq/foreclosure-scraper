#!/usr/bin/env python3
"""Recover delinquent-tax YEAR from the run checkpoint into the published board.

Tax delinquency aged 2-3 years is the primary lead filter for this business, and
on the published board only 2.6% of 90,414 tax leads carry a usable year - so the
filter can be applied to almost nothing.

Cause: web_artifact._slim_raw() dropped the tax sources' raw sub-dicts at publish
time, so the year was deleted from the board and cannot be re-parsed from it. The
RAW_KEEP fix (2026-08-24) preserves them, but it only landed in git on 2026-08-30,
AFTER the last successful publish on 2026-08-27.

The 2026-09-08 run DID re-scrape those sources with the fix in place - its
checkpoint carries the sub-dicts the board lacks (buncombe 887, nc_county_csv
1,211, spartanburg 1,900, multi_year 1,655). That run never published (the count
guard correctly refused a shrink), so the data is stranded in the checkpoint.

This copies ONLY the tax sub-dicts + tax_owed block from the checkpoint onto
matching board rows that lack them, then re-runs enrich_tax_owed to normalise the
year. Fill-only: never adds, removes, or overwrites a populated value, so the
count guard is untouched.

    python scripts/recover_tax_year_from_checkpoint.py --dry-run
    python scripts/recover_tax_year_from_checkpoint.py
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
DOCS = REPO / "docs"
CHECKPOINT = REPO / "data" / "checkpoint" / "board.json.gz"
NOW_YEAR = 2026

TAX_SUBDICTS = (
    "buncombe_delinquent_tax", "nc_county_csv_delinquent_tax",
    "spartanburg_delinquent_tax", "multi_year_delinquent_tax",
    "pickens_delinquent_parcels", "nc_ptscloud_delinquent_tax",
    "nc_county_pdf_delinquent_tax", "rutherford_wildfire",
    "sc_state_tax_lien", "oconee_forfeited_land",
)
_YEARISH = ("year", "tax_year", "first_cycle", "latest_cycle", "bill_year",
            "oldest_year", "bill_years", "tax_years", "year_span")


def _keys(rec: dict) -> list:
    """Identity keys, most specific first. dict for checkpoint rows, obj for board.

    BUG (found 2026-10-02, see docs/HANDOFF.md): `source_url` used to be listed
    FIRST, ahead of parcel_id. That is backwards for any bulk single-document
    source — every row scraped from one county PDF/CSV/API page shares the exact
    same source_url (e.g. every counties_nc.buncombe_delinquent_tax row carries
    the one PDF_URL), so `("u", source_url)` is the LEAST specific key available
    for those sources, not the most. With it tried first, every board row from
    such a source that still needed a year matched the SAME donor's "u" index
    entry (whichever checkpoint row happened to be indexed there first) and had
    THAT donor's principal_tax_due/tax_owed copied onto it — live-confirmed on
    the real board: 610 of 829 Buncombe tax-delinquency rows carried the
    IDENTICAL principal_tax_due ($775.59, one single real parcel's own value)
    despite being 610 genuinely different parcels, each with its own different
    real amount on today's live advertisement. Reordered so parcel_id (genuinely
    near-unique per real-world parcel) and the other per-record keys are tried
    BEFORE the coarse, often-shared source_url -- "most specific first" is now
    true, not just stated. `_build_index` below adds a second, independent
    guard: an identity key that maps to more than one DISTINCT donor payload
    (source_url being the one known to do this, but not the only one that
    could) is never used at all, rather than silently keeping "whichever donor
    happened to be inserted first."""
    g = rec.get if isinstance(rec, dict) else (lambda k, d=None: getattr(rec, k, d))
    out = []
    pid, cty = g("parcel_id"), g("county")
    if isinstance(pid, str) and len(pid) >= 5:
        out.append(("p", pid.strip().upper(), str(cty or "").strip().lower()))
    addr, zc = g("street_address"), g("zip_code")
    if isinstance(addr, str) and addr.strip() and zc:
        out.append(("a", re.sub(r"\s+", " ", addr).strip().upper(), str(zc)[:5]))
    cn = g("case_number")
    if isinstance(cn, str) and len(cn) >= 6:
        out.append(("c", cn.strip().upper()))
    su = g("source_url")
    if isinstance(su, str) and len(su) > 20:
        out.append(("u", su))
    return out


def _build_index(donors: list[tuple[list, dict]]) -> dict:
    """donors: [(keys_for_this_record, payload)]. Returns {key: payload}, but a
    key that more than one donor maps to a DIFFERENT payload under is dropped
    entirely rather than resolved by first-insert-wins -- an ambiguous key is
    worse than no key, since using it means guessing which donor it meant and
    copying that guess's dollar figures onto an unrelated parcel. Two donors
    sharing a key with an IDENTICAL payload (a true duplicate row) are not
    ambiguous and the key is kept."""
    idx: dict = {}
    ambiguous: set = set()
    for keys, payload in donors:
        for k in keys:
            if k in ambiguous:
                continue
            cur = idx.get(k)
            if cur is None:
                idx[k] = payload
            elif cur != payload:
                ambiguous.add(k)
                del idx[k]
    return idx


def _year_of(raw: dict) -> int | None:
    to = raw.get("tax_owed") or {}
    if not isinstance(to, dict):
        return None
    for k in _YEARISH:
        v = to.get(k)
        for cand in (v if isinstance(v, list) else [v]):
            m = re.search(r"(19|20)\d{2}", str(cand)) if cand is not None else None
            if m:
                y = int(m.group(0))
                if 1990 < y <= NOW_YEAR:
                    return y
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.web_artifact import load_board, write_artifact, board_lock
    from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed
    from foreclosure_scraper.config import in_scope

    if not CHECKPOINT.exists():
        print(f"no checkpoint at {CHECKPOINT}")
        return 1
    with gzip.open(CHECKPOINT, "rt") as f:
        cp = json.load(f)
    if isinstance(cp, dict):
        cp = cp.get("listings") or cp.get("data") or []
    print(f"checkpoint rows: {len(cp):,}")

    # index checkpoint rows that actually carry tax data worth copying
    donor_entries: list[tuple[list, dict]] = []
    donors = 0
    for rec in cp:
        raw = rec.get("raw") or {}
        payload = {k: raw[k] for k in TAX_SUBDICTS if isinstance(raw.get(k), dict)}
        to = raw.get("tax_owed")
        if isinstance(to, dict) and _year_of(raw):
            payload["tax_owed"] = to
        if not payload:
            continue
        donors += 1
        donor_entries.append((_keys(rec), payload))
    idx = _build_index(donor_entries)
    print(f"  donor rows with tax data: {donors:,}  (index keys {len(idx):,})")

    def stats(board):
        s = collections.Counter()
        for li in board:
            raw = li.raw if isinstance(getattr(li, "raw", None), dict) else {}
            lt = str(getattr(li, "listing_type", "") or "").lower()
            if not ("tax" in lt or raw.get("tax_owed") or raw.get("two_year_delinquent")):
                continue
            s["tax"] += 1
            y = _year_of(raw)
            if y:
                s["year"] += 1
                if getattr(li, "county", None) and in_scope(li.county, li.state):
                    age = NOW_YEAR - y
                    if age >= 2:
                        s["foot2"] += 1
                    if age >= 3:
                        s["foot3"] += 1
        return s

    # board_lock takes the REPO ROOT, not docs/. Passing DOCS builds
    # docs/logs/.board.lock - a phantom lock that excludes nothing, so this
    # writer runs concurrently with the 4h-holding vision pass and its work is
    # silently reverted when that pass flushes its stale in-memory board.
    with board_lock(REPO):
        board = load_board(DOCS)
        before = stats(board)
        print(f"\nboard {len(board):,} | tax leads {before['tax']:,}")
        print(f"  BEFORE  year {before['year']:,}  in-footprint 2yr+ {before['foot2']:,}  3yr+ {before['foot3']:,}")

        copied = 0
        for li in board:
            if not isinstance(getattr(li, "raw", None), dict):
                li.raw = {}
            raw = li.raw
            if _year_of(raw):
                continue                      # already has a year, leave it
            payload = None
            for k in _keys(li):
                payload = idx.get(k)
                if payload:
                    break
            if not payload:
                continue
            wrote = False
            for k, v in payload.items():
                if k not in raw:              # never overwrite
                    raw[k] = v
                    wrote = True
            if wrote:
                copied += 1
        print(f"  rows given tax sub-dicts from checkpoint: {copied:,}")

        res = enrich_tax_owed(board)
        print(f"  enrich_tax_owed: {res}")

        after = stats(board)
        print(f"  AFTER   year {after['year']:,}  in-footprint 2yr+ {after['foot2']:,}  3yr+ {after['foot3']:,}")
        print(f"\n  >>> year +{after['year']-before['year']:,}")
        print(f"  >>> THE FILTER (in-footprint, 2yr+): {before['foot2']:,} -> {after['foot2']:,}")

        if args.dry_run:
            print("\n--dry-run: nothing written")
            return 0
        summary = {
            "by_source": dict(collections.Counter(
                li.source for li in board if getattr(li, "source", None))),
            "notes": (f"tax year recovered from checkpoint: {before['year']}->{after['year']}, "
                      f"in-footprint 2yr+ {before['foot2']}->{after['foot2']}"),
        }
        lp, _ = write_artifact(board, summary, docs_dir=DOCS)
        print(f"\nboard rows {len(board):,} (unchanged) | wrote {lp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
