#!/usr/bin/env python3
"""One-off backfill: populate raw['heir_estate']['heir_names'] on estate_lead
rows that were already published BEFORE commit 4dfc728b (2026-10-02) added
that field to counties_nc/nc_heir_estate_parcels.py.

WHY THIS EXISTS

    task_heir_names_coverage_gap, 2026-10-04. `heir_names` (a structured list
    of {raw, name, role} dicts, one per co-owner/heir subfield) was added to
    nc_heir_estate_parcels.py on 2026-10-02 (commit 4dfc728b) because the
    joined `owner_of_record` string was not machine-readable as a list.

    Confirmed LIVE 2026-10-04 (board_stream.iter_board_rows(), read-only): 0
    of 1,039 estate_lead rows on the published board carry heir_names (52 of
    52 sampled in Buncombe). This is NOT a publish-pipeline bug --
    `web_artifact.RAW_KEEP["heir_estate"] = "*"` is a wholesale wildcard, so
    `_slim_raw()` already keeps the ENTIRE heir_estate dict (including
    whatever nested keys it has) verbatim; there is nothing in RAW_KEEP or
    board_dedupe_stream.py that drops or sub-projects it (see
    tests/test_nc_heir_estate_parcels.py::
    test_gaston_multi_heir_heir_names_survives_the_publish_slim for the
    end-to-end proof). The real cause is simpler: the full pipeline has not
    written the board since 2026-08-29 (see run_scoped_scrapers.py's own
    module docstring), and every nc_heir_estate_parcels row actually on the
    board has last_seen <= 2026-09-22 -- more than a week before heir_names
    existed in the code at all.

    Simply re-running nc_heir_estate_parcels will NOT retroactively fix the
    1,039 rows already published. Every landing path this project actually
    uses outside a full pipeline run (`web_artifact.append_new_rows` /
    `apply_rows_streaming`, what `scripts/run_scoped_scrapers.py --apply`
    calls) is ADDITIVE ONLY: a freshly-scraped row that matches an existing
    board row by dedupe_key()/_strong_sigs() is skipped and counted, and the
    existing row is never touched (see append_new_rows()'s own docstring).
    Since this scraper is dateless and re-discovers the SAME parcels on every
    run, re-scraping alone would only add heir_names to brand-new parcels
    going forward -- every already-published row would stay stuck without it
    forever.

    This script closes the gap WITHOUT a re-scrape or any live network call:
    heir_names is fully DERIVABLE from data already sitting on the board.
    `raw['heir_estate']['owner_of_record']` IS `_owner_display(owner_fields)`
    -- the scraper's own "; ".join() of the exact same `owner_fields`
    `_heir_names()` parses -- so splitting it back on "; " and running the
    scraper's own, UNMODIFIED `_parse_owner_field()` over each piece
    reconstructs the identical structured list a live re-scrape would have
    produced (see that function's docstring for the three role-encoding
    shapes it strips: trailing "<NAME> HEIRS" / "<NAME> ESTATE" / "<NAME>
    TRUSTEE 1/2", and leading "ESTATE OF <NAME>").

    ONE caveat, disclosed rather than hidden: `_owner_display()` dedupes
    owner_fields case-insensitively before joining, so a row whose ORIGINAL
    owner_fields happened to carry an exact-text duplicate subfield would
    get one fewer heir_names entry here than a live re-scrape would produce
    straight from the GIS attributes. Not reconstructable from published data
    alone -- a future live re-scrape remains the source of truth going
    forward; this script only closes the gap on what is already published.

SCOPE: every board row with listing_type == "estate_lead",
source == "counties_nc.nc_heir_estate_parcels", raw['heir_estate'] present as
a dict, and "heir_names" not already a key in it.

RAW-UPDATE GOTCHA (read web_artifact.patch_existing_rows()'s own docstring
before changing this script): the patch's raw update is merged into the
row's raw dict via plain `raw.update(raw_update)` -- ONE LEVEL deep only. A
patch of {"raw": {"heir_estate": {"heir_names": [...]}}} would REPLACE the
entire existing heir_estate dict wholesale, silently deleting
owner_of_record/mailing/care_of/match. `_build_patch()` below always carries
the row's full EXISTING heir_estate dict forward (spread first, heir_names
added after), never a partial one -- see
tests/test_backfill_heir_names.py::test_build_patch_preserves_sibling_keys.

BOARD I/O: board_stream.iter_board_rows() (read-only streaming scan, ~300 MB
per its own docstring) for everything, including --dry-run -- pure
derivation from already-published data, no live network call needed at all.
--apply additionally takes board_lock and calls
web_artifact.patch_existing_rows(). NOT run with --apply this session (the
task this script was written under is explicit: no live board-file writes on
this 8GB Mac) -- only --dry-run (read-only) has been run here, to confirm the
targeting logic against the real board.

    .venv/bin/python scripts/backfill_heir_names.py --dry-run
    .venv/bin/python scripts/backfill_heir_names.py --apply   # NOT run this session
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.nc_heir_estate_parcels import (  # noqa: E402
    _parse_owner_field,
)

#: Same identity fields web_artifact._APPEND_SIG_FIELDS keys patches on (that
#: tuple is private to web_artifact.py; this local copy matches
#: backfill_anderson_situs_value.py's own precedent for the same situation).
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

_SOURCE = "counties_nc.nc_heir_estate_parcels"
_LISTING_TYPE = "estate_lead"


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def derive_heir_names(owner_of_record: str | None) -> list[dict]:
    """Reconstruct the structured heir_names list from the already-published,
    ";"-joined `owner_of_record` string -- see module docstring for why this
    exactly matches what a live re-scrape's `_heir_names()` would produce
    (modulo the disclosed dedupe caveat). Reuses the scraper's own, unmodified
    `_parse_owner_field()` -- no reimplementation of its role-token parsing."""
    parts = [p.strip() for p in (owner_of_record or "").split(";")]
    return [_parse_owner_field(p) for p in parts if p]


def build_patch(heir_estate: dict, names: list[dict]) -> dict:
    """The raw update for one row: the EXISTING heir_estate dict, with
    heir_names added -- never a partial dict (see module docstring's RAW-
    UPDATE GOTCHA; patch_existing_rows() replaces this sub-dict wholesale,
    one level deep, so every sibling key must be carried forward explicitly)."""
    return {"raw": {"heir_estate": {**heir_estate, "heir_names": names}}}


def _collect_targets(docs: Path):
    """ONE streaming pass over the whole board (read-only, no board_lock
    needed -- nothing is written here regardless of --dry-run/--apply).
    Returns (scanned, eligible, already_has, no_owner, key_counts, candidates)
    where candidates is [(dedupe_key, heir_estate_dict), ...]."""
    key_counts: Counter = Counter()
    candidates: list[tuple[str | None, dict]] = []
    scanned = eligible = already_has = no_owner = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        scanned += 1
        key = _dedupe_key(rec)
        if key is not None:
            key_counts[key] += 1
        if rec.get("listing_type") != _LISTING_TYPE or rec.get("source") != _SOURCE:
            continue
        he = (rec.get("raw") or {}).get("heir_estate")
        if not isinstance(he, dict):
            continue
        if "heir_names" in he:
            already_has += 1
            continue
        owner = he.get("owner_of_record")
        if not owner:
            no_owner += 1
            continue
        eligible += 1
        candidates.append((key, he))
    return scanned, eligible, already_has, no_owner, key_counts, candidates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually write via patch_existing_rows(). Default is a "
                         "read-only dry run.")
    ap.add_argument("--limit", type=int, default=None, help="Cap candidates (testing)")
    args = ap.parse_args()

    docs = REPO / "docs"
    scanned, eligible, already_has, no_owner, key_counts, candidates = _collect_targets(docs)
    print(f"scanned {scanned:,} board rows")
    print(f"  {_SOURCE} {_LISTING_TYPE} rows missing heir_names, with an "
          f"owner_of_record: {eligible:,}")
    print(f"  already carrying heir_names: {already_has:,}")
    print(f"  missing heir_names AND missing owner_of_record (unfixable from "
          f"published data alone): {no_owner:,}")

    if args.limit:
        candidates = candidates[:args.limit]

    stats: Counter = Counter()
    patches: dict[str, dict] = {}
    for key, he in candidates:
        if key is None:
            stats["skipped_no_key"] += 1
            continue
        if key_counts[key] > 1:
            # Same defensive collision guard every other backfill_*.py script in this
            # repo uses: never guess which of several board rows sharing one
            # dedupe_key() a patch was meant for.
            stats["skipped_key_collision"] += 1
            continue
        names = derive_heir_names(he.get("owner_of_record"))
        if not names:
            stats["skipped_no_names_derived"] += 1
            continue
        patches[key] = build_patch(he, names)
        stats["matched"] += 1

    print("\n=== match stats ===")
    for k, v in sorted(stats.items()):
        print(f"  {v:7,d}  {k}")
    print(f"\ntotal patches ready: {len(patches):,}  (== {stats['matched']:,} from "
          f"match stats, must match)")
    assert len(patches) == stats["matched"], (
        "patches dict size diverged from the matched counter -- investigate "
        "before trusting either number")

    if not args.apply:
        print("\nDRY RUN -- nothing written. Pass --apply to write for real.")
        return 0

    from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows
    with board_lock(REPO, owner="backfill_heir_names"):
        result = patch_existing_rows(
            patches, {"backfill_heir_names": f"{len(patches)} rows"}, docs_dir=docs)
        print("\n=== patch_existing_rows result ===")
        for k, v in result.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
