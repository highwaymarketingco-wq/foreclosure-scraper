#!/usr/bin/env python3
"""One-time backfill: stamp raw['two_year_delinquent'] / raw['_nc_tax_lien_ads_mydt_checked']
onto EXISTING Hoke/Lee/Davidson/Randolph NC board rows that nc_tax_lien_ads.py already landed.

CONTEXT (2026-11-16/17 gap_matrix "no source known" tax-cluster survey). nc_tax_lien_ads.py's
own annual-ad sources never carry a real multi-year history (each is a single-levy-year 105-369
publication -- see that module's 2026-11-17 docstring fix), so these rows can never honestly
claim is_two_year_plus=True, but reading the ad IS a real screen of the tax roll for every
parcel it lists -- not an unchecked row -- for both two_year_delinquent (checked = any dict
present) and multi_year_delinquent_tax (checked = the _nc_tax_lien_ads_mydt_checked shadow key
gap_matrix.py's checked_columns() now recognizes, same pattern as Gaston/Pasquotank/New
Hanover). No live fetch needed: every row already carries raw['nc_tax_lien_ad'], the only fact
this backfill needs.

    python scripts/backfill_nc_tax_lien_ads_checked.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_nc_tax_lien_ads_checked.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

RAW_KEY = "nc_tax_lien_ad"
TWOYR_KEY = "two_year_delinquent"
CHECKED_KEY = "_nc_tax_lien_ads_mydt_checked"
SLUG = "counties_nc.nc_tax_lien_ads"
_COUNTIES = {"hoke", "lee", "davidson", "randolph"}

_IN_SCOPE = lambda rec: (  # noqa: E731
    str(rec.get("county") or "").replace(" County", "").strip().lower() in _COUNTIES
    and str(rec.get("state") or "").upper() == "NC"
)


def _candidates(docs_dir: Path) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IN_SCOPE(rec):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if not isinstance(raw.get(RAW_KEY), dict):
            continue  # not landed by this producer at all
        if TWOYR_KEY in raw or CHECKED_KEY in raw:
            continue  # already stamped (idempotent re-run)
        new_raw = dict(raw)
        new_raw[TWOYR_KEY] = {"is_two_year_plus": False, "years_delinquent": 1, "source": SLUG}
        new_raw[CHECKED_KEY] = True
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        out.append((li.dedupe_key(), new_raw))
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
    print(f"Hoke/Lee/Davidson/Randolph rows to stamp (checked, not multi-year): {len(cands)}")
    if not cands:
        print("nothing to do.")
        return 0

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    all_patches = {key: {"raw": new_raw} for key, new_raw in cands}
    with board_lock(REPO, owner="nc_tax_lien_ads_checked_backfill", wait=600, poll=10):
        wstats = patch_existing_rows(
            all_patches, {"nc_tax_lien_ads_checked_backfill": len(all_patches)},
            docs_dir=docs_dir)
        print("patch_existing_rows:", wstats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
