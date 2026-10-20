#!/usr/bin/env python3
"""One county, bounded: run the ALREADY-BUILT SC "Online Record System" chain walk
(rod/sc_online_record_system.chain(), the SAME code enrichment_rod_chain.py uses for all 10 ORS
counties) against Florence SC's board rows, and stage patches into the shared
raw['rod_chain'] / raw['deed_latest'] contract gap_matrix.py's atty_deed_ref check
(deed_ref_present()) already reads.

WHY A SEPARATE SCRIPT (docs/gap_matrix/gap_list_2026-10-20.csv, read before writing a line here).
    atty_deed_ref shows sourced-not-built for Florence (3,882 applicable), source "register
    index: search.florencedeeds.com", built=no, next_action guessing a new reader is needed. One
    already exists, fully wired end to end, and needs NO new code:
        rod/sc_online_record_system.py's SC_ORS_COUNTIES already has "florence" (same platform as
        Abbeville/Barnwell/Berkeley/Colleton/Dorchester/Georgetown/Lancaster/Laurens/York);
        enrichment_generic_rod.CHAIN_ONLY_CONFIG already registers ("SC","Florence") against it;
        enrichment_rod_chain.enrich_rod_chain() already calls chain(), binds it to the row's own
        parcel (bind_chain()), and calls lawyer_lane.stamp_deed_latest() -- which writes
        raw['deed_latest'] the moment a chain's binding is CONFIRMED (book_page or sale_date), and
        scripts/gap_matrix.py's deed_ref_present() already reads raw['deed_latest'] (bound+book+
        page) as a hit for atty_deed_ref. Nothing here is new; see those modules' own docstrings.

    LIVE-VERIFIED 2026-10-20 (real HTTP against search.florencedeeds.com, read-only, no board
    touched): the site is live and NOT walled (GET NameSearch.php?Accept=Accept -> HTTP 200,
    204,827 bytes, title "Florence County Search Deeds"; no CAPTCHA/login/bot-check markers).
    A raw POST NamePick.php for the bare surname "SMITH" returns 2,000 real picker rows
    (SMITHAA ... ) -- parse_pick() reads every one of them correctly. chain("florence",
    "SMITH JOHN", ...) still answers status="not_found", because NamePick's own
    tor_last_name=<surname>-only search (there is no separate first-name field in this form) hits
    the platform's SEARCH_LIMIT=2000 cap before the alphabetically-later "SMITH JOHN..." entries
    are ever returned -- a measured, platform-inherent yield ceiling for COMMON surnames in a
    deep historical index, already guarded by this module's own `truncated` flag, NOT a wall and
    NOT a code bug. Five more real names from live board rows (ADJABENG, ALFORD, TAYARA, ALLEN,
    WILLARD) all answered "not_found" too -- consistent with, not contradicting, the gap matrix's
    own already-measured ~0.26% chain yield for this county (10/3,882): most owner names
    genuinely have no indexed deed under that exact name. The mechanism works; the ceiling is
    real and inherent to name-index search over a large county, not a missing feature.

WHY NOT JUST FLIP FORECLOSURE_ROD_CHAIN=1/FORECLOSURE_SC_ORS_ROD=1 AND RUN THE PIPELINE. Those
    flags are process-wide: enrich_rod_chain() walks EVERY (state, county) in chain_registry()
    with no per-county scope (unlike nc_its_public_tax.py's ITS_TAX_COUNTIES), so turning them on
    for real would also attempt every other NC register platform and all 9 sibling ORS counties
    in the same pass -- a far larger, far slower operation than this task's Florence-only scope.
    This script reuses the exact same chain()/bind_chain()/stamp_deed_latest() calls, scoped to
    Florence SC rows only, with its own bounded cap (politeness budget, NOT a shortcut around it).

POLITENESS. sc_polite.PoliteSession's own module-level per-host pacing (>= 1.6 s, one request at
    a time) applies automatically to every chain() call in this process, same as production. A
    chain can cost several requests (NamePick + NameDisplay + up to `--depth` prior-deed walks),
    so --limit (default 30, matching enrichment_rod_chain.py's own NC_ROD_MAX_LOOKUPS_PER_COUNTY
    convention for one register county in one run) bounds a single invocation; the full 3,872-row
    backlog needs several runs, same as the production pipeline would spread it over several
    passes.

Usage:
    python scripts/backfill_florence_rod_chain.py --dry-run --limit 30
    python scripts/backfill_florence_rod_chain.py --limit 30                 # writes (board_lock)
"""
from __future__ import annotations

import argparse
import contextlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_rod_chain import bind_chain  # noqa: E402
from foreclosure_scraper.lawyer_lane import deed_latest_from_chain  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.name_normalize import is_entity  # noqa: E402
from foreclosure_scraper.rod.sc_online_record_system import chain  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name", "parcel_id")
_RETRY_LATER = ("walled", "capped", "error")


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _already_has_deed_ref(raw: dict) -> bool:
    """Same bar scripts/gap_matrix.py's deed_ref_present() applies for raw['county_deed_ref'] /
    raw['deed_latest'] -- a row that already clears it needs no live request spent on it."""
    cd = raw.get("county_deed_ref")
    if isinstance(cd, dict) and cd.get("book") and cd.get("page"):
        return True
    dl = raw.get("deed_latest")
    return isinstance(dl, dict) and bool(dl.get("bound") and dl.get("book") and dl.get("page"))


def _collect_targets(docs: Path, limit: int) -> list[Listing]:
    out: list[Listing] = []
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if (rec.get("state") or "").upper() != "SC":
            continue
        if (rec.get("county") or "").strip().lower() != "florence":
            continue
        owner = rec.get("owner_name") or ""
        if not owner or is_entity(owner):
            continue
        raw = rec.get("raw")
        raw = raw if isinstance(raw, dict) else {}
        if _already_has_deed_ref(raw):
            continue
        out.append(_light(rec))
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=30,
                    help="Florence rows to attempt THIS run (politeness-bounded; default 30, "
                         "matching NC_ROD_MAX_LOOKUPS_PER_COUNTY's own convention).")
    ap.add_argument("--depth", type=int, default=3)
    args = ap.parse_args()

    docs = REPO / "docs"
    now = datetime.now(timezone.utc)

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="florence_rod_chain_backfill")
    with lock:
        targets = _collect_targets(docs, args.limit)
        print(f"Florence SC targets this run: {len(targets):,} (--limit {args.limit})")
        patches: dict[str, dict] = {}
        counts = {"ok": 0, "partial": 0, "not_found": 0, "walled": 0, "capped": 0, "error": 0,
                 "bound": 0, "name_only": 0, "deed_ref_gained": 0}
        t0 = time.monotonic()
        for li in targets:
            try:
                res = chain("florence", li.owner_name, state="SC", depth=args.depth)
            except Exception as exc:  # noqa: BLE001 - one lead never kills the pass
                counts["error"] += 1
                print(f"  ERROR {li.owner_name!r}: {type(exc).__name__}: {exc}")
                continue
            status = res.get("status", "error")
            counts[status] = counts.get(status, 0) + 1
            if status in _RETRY_LATER:
                continue
            patch_raw: dict = {"rod_chain": res}
            if status in ("ok", "partial") and res.get("last_deed"):
                b = bind_chain(li, res, now)
                res["binding"] = b
                if b["status"] == "contradicted":
                    res["status"] = "unbound"
                    counts["unbound"] = counts.get("unbound", 0) + 1
                elif b["status"] in ("sale_date", "book_page"):
                    counts["bound"] += 1
                else:
                    counts["name_only"] += 1
                dl = deed_latest_from_chain(li, res)
                if dl:
                    patch_raw["deed_latest"] = dl
                    counts["deed_ref_gained"] += 1
            try:
                key = li.dedupe_key()
            except Exception:  # noqa: BLE001
                continue
            patches[key] = {"raw": patch_raw}
        elapsed = time.monotonic() - t0
        print(f"\nelapsed: {elapsed:.1f}s")
        for k, v in sorted(counts.items()):
            print(f"  {k:20} {v:,}")
        print(f"\npatches staged: {len(patches):,} "
              f"(of which {counts['deed_ref_gained']:,} newly clear atty_deed_ref via raw['deed_latest'])")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0
        if not patches:
            print("\nnothing to do.")
            return 0
        size_state = board_patch_size_state(docs)
        if not size_state["ok"]:
            print(f"\nREFUSING: {size_state['reason']}. See patch_existing_rows()'s "
                  f"BOARD_PATCH_ALLOW_LARGE docstring in web_artifact.py.")
            return 1
        stats = patch_existing_rows(patches, dict(counts), docs_dir=docs)
        print(f"\nwrote board: patched {stats['applied']:,}/{len(patches):,} rows "
              f"(existing: {stats['existing']:,}, not_found: {stats['not_found']:,}, "
              f"duplicate_key_matches: {stats['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
