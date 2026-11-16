#!/usr/bin/env python3
"""One-time backfill: run enrichment_pasquotank_delinquent_tax.py's existing, already-wired
enrich_pasquotank_delinquent_tax() against the Pasquotank NC backlog it has never actually
touched. The module was built and wired into main.py 2026-11-05/committed 2026-11-10 (per its
own docstring, targeting the county's annual NCGS 105-369 delinquent-tax PDF at
www.pasquotankcountync.org), but a live board probe on 2026-11-16 found ZERO Pasquotank rows
carrying raw['pasquotank_tax_lien'] or raw['_pasquotank_tax_checked'] -- it has never run to
completion against the real board (main.py's full nightly pipeline runs ~30 enrichments in
sequence before reaching this one; whatever the cause, nothing from it has ever landed). Nothing
new to build here, just run the existing, unmodified function directly against this one county's
~2,470-row slice (small enough for a single pass -- no internal batching needed, unlike the
26,620-row Gaston backlog scripts/backfill_gaston_multiyear_tax.py mirrors).

Expected result, per the module's OWN docstring ("WHY MULTI-YEAR DOESN'T FILL YET"): this run
will likely populate raw['tax_owed'] / raw['pasquotank_tax_lien'] for matched owners (a real,
useful improvement feeding two_year_delinquent / tax_aging_surfaced downstream) but
raw['multi_year_delinquent_tax'] itself will probably stay empty for every row -- only ONE
year's PDF (2025) has ever been published/linked on the county's site, and the column's own
MIN_YEARS=2 gate genuinely needs two. per_year is designed to ACCUMULATE across runs, so a
future year's PDF will complete the gate without this script being touched again.

    python scripts/backfill_pasquotank_delinquent_tax.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_pasquotank_delinquent_tax.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_pasquotank_delinquent_tax import (  # noqa: E402
    CHECKED_KEY, MYDT_KEY, RAW_KEY, enrich_pasquotank_delinquent_tax,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_IS_PASQUOTANK = lambda rec: (  # noqa: E731
    str(rec.get("county") or "").replace(" County", "").strip().lower() == "pasquotank"
    and str(rec.get("state") or "").upper() == "NC"
)


def _candidates(docs_dir: Path) -> list[tuple[str, Listing]]:
    """Every never-checked Pasquotank NC row, reconstructed as a minimal Listing. owner_name is
    NOT in _APPEND_SIG_FIELDS (that tuple was built for parcel-keyed sources) but this module's
    own _eligible() requires it -- set explicitly below, the one addition over the Gaston/
    Cabarrus template this otherwise mirrors."""
    out: list[tuple[str, Listing]] = []
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_PASQUOTANK(rec):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if RAW_KEY in raw or CHECKED_KEY in raw:
            continue
        if not rec.get("owner_name"):
            continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        li.owner_name = rec.get("owner_name")
        li.raw = dict(raw)
        out.append((li.dedupe_key(), li))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    cands = _candidates(docs_dir)
    print(f"Pasquotank NC eligible (never checked by this module): {len(cands)}")
    if not cands:
        print("nothing to do.")
        return 0

    listings = [li for _, li in cands]
    stats = asyncio.run(enrich_pasquotank_delinquent_tax(listings))
    print("enrich_pasquotank_delinquent_tax stats:", stats)

    all_patches: dict[str, dict] = {}
    checked = 0
    qualified = 0
    for key, li in cands:
        if RAW_KEY in li.raw or CHECKED_KEY in li.raw:
            checked += 1
            if MYDT_KEY in li.raw:
                qualified += 1
            all_patches[key] = {"raw": li.raw}

    print(f"\npatches staged: {len(all_patches)}")
    print(f"    multi_year_delinquent_tax qualified: {qualified}")
    print(f"    checked (tax_owed matched / no_match / ambiguous), not multi-year: "
          f"{checked - qualified}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    if not all_patches:
        print("nothing to write.")
        return 0

    with board_lock(REPO, owner="pasquotank_tax_backfill", wait=600, poll=10):
        wstats = patch_existing_rows(all_patches, {"pasquotank_tax_backfill": len(all_patches)},
                                     docs_dir=docs_dir)
        print("patch_existing_rows:", wstats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
