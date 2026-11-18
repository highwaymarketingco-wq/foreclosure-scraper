#!/usr/bin/env python3
"""One county, bounded: run the ALREADY-BUILT SC "older Cott eSearch" chain walk
(rod/sc_cott_esearch.chain()) against Marlboro SC's board rows, and stage patches into the shared
raw['rod_chain'] / raw['deed_latest'] contract gap_matrix.py's atty_deed_ref check
(deed_ref_present()) already reads. Mirrors scripts/backfill_florence_rod_chain.py /
backfill_abbeville_rod_chain.py exactly, re-pointed at Marlboro's own Cott eSearch platform (a
DIFFERENT, older ASP.NET classic product -- cotthosting.com/scmarlboro, "Guest User", no
password -- from the Blazor-Server "Cott RecordHub" product already confirmed login/SignalR-
walled for Saluda/Chesterfield/Dillon/Bamberg/Fairfield/Chester elsewhere in this repo; the two
are not the same dead end).

WHY A SEPARATE SCRIPT (docs/gap_matrix/gap_list_2026-11-18.csv, round 31, read before writing a
    line here). atty_deed_ref shows sourced-not-built for Marlboro (1,488 applicable), source
    "register index: www.cotthosting.com", built=no. One already exists, fully wired, and needs
    NO new code: rod/sc_cott_esearch.py's COTT_ESEARCH_COUNTIES already has "marlboro"
    (http://www.cotthosting.com/scmarlboro); enrichment_generic_rod.ROD_CONFIG already registers
    ("SC","Marlboro") against it, ENABLED by default (flag default "1", the only one of its
    siblings not gated off); enrichment_rod_chain.chain_registry() merges ROD_CONFIG +
    RENDER_ROD_CONFIG + CHAIN_ONLY_CONFIG into one flat registry and calls the registered
    module's own chain() for every entry uniformly regardless of which of the three dicts it
    came from -- Marlboro is NOT treated differently from Florence/Abbeville here. sc_cott_
    esearch.chain() returns the exact same rod/sc_chain.ChainResult.to_dict() shape
    sc_online_record_system.chain() does (both call the shared run_chain() helper), so
    bind_chain() / deed_latest_from_chain() apply unchanged.

    THE REAL GAP (why it still reads 0 hits despite being enabled by default).
    enrichment_generic_rod.py's own module comment (2026-10-07) already recorded a real result:
    "Marlboro 2 chains of 5" -- i.e. sc_cott_esearch.chain() was spot-tested against 5 real
    Marlboro owners and 2 resolved a chain, a measured ~40% hit rate, dramatically higher than
    the ORS platform's own measured ceiling (Florence 0.26%, Abbeville's live sample this round).
    But FORECLOSURE_ROD_CHAIN -- the flag enrich_rod_chain() (the function that actually calls
    chain()/bind_chain()/stamp_deed_latest() to populate raw['deed_latest']) checks -- is a
    SEPARATE, process-wide flag from FORECLOSURE_SC_COTT_ESEARCH_ROD (which only gates
    enrichment_generic_rod.py's own PLAIN EXISTENCE-check summary, raw['rod'] with
    instrument_count/kinds/instruments -- note deed_ref_present() only reads book/page/
    instrument_no/instrument OFF THE TOP LEVEL of raw['rod'], never off items inside its nested
    'instruments' list, so this existence-check path structurally can never satisfy atty_deed_ref
    no matter how many real instruments it counts). Nothing in this repo has ever run the CHAIN
    path specifically for Marlboro before -- this script is that first scoped run, same shape as
    Florence's/Abbeville's own first backfill.

LIVE RE-VERIFIED this round (2026-11-18): GET cotthosting.com/scmarlboro/LandRecords/protected/
    SrchQuickName.aspx -> HTTP 200, "Guest User" text present, no login wall (same as the
    county_records_matrix.json 2026-10-07 finding: 'Requesting the name search ... lands as
    Guest User on the name search form (no password asked)'). Index types LAND RECORDS/PLAT;
    the matrix flags IMAGES as pay-per-copy (a shopping-cart confirm page), but the deed book/
    page REFERENCE this column needs comes off the free name-search grid itself, not the image.

WHY NOT JUST FLIP FORECLOSURE_ROD_CHAIN=1. Process-wide, no per-county scope: it would also walk
    every other registered NC/SC register platform in the same pass. This script reuses the
    exact same chain()/bind_chain()/deed_latest_from_chain() calls, scoped to Marlboro SC rows
    only, with its own bounded cap.

POLITENESS. sc_cott_esearch's own PoliteSession pacing applies automatically to every chain()
    call in this process, same as production.

Usage:
    python scripts/backfill_marlboro_rod_chain.py --dry-run --limit 30
    python scripts/backfill_marlboro_rod_chain.py --limit 30                 # writes (board_lock)
"""
from __future__ import annotations

import argparse
import contextlib
import os
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
from foreclosure_scraper.rod.sc_cott_esearch import chain  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name", "parcel_id")
_RETRY_LATER = ("walled", "capped", "error")
_COUNTY = "marlboro"


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _already_has_deed_ref(raw: dict) -> bool:
    cd = raw.get("county_deed_ref")
    if isinstance(cd, dict) and cd.get("book") and cd.get("page"):
        return True
    dl = raw.get("deed_latest")
    return isinstance(dl, dict) and bool(dl.get("bound") and dl.get("book") and dl.get("page"))


def _already_tried_chain(raw: dict) -> bool:
    """Skip a row this SAME script already attempted (any status) in a prior run -- without
    this, repeat invocations would keep reprocessing the same leading rows forever, since a
    not_found/name_only chain result alone doesn't set deed_latest."""
    rc = raw.get("rod_chain")
    return isinstance(rc, dict) and rc.get("status") is not None


def _collect_targets(docs: Path, limit: int) -> list[Listing]:
    out: list[Listing] = []
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if (rec.get("state") or "").upper() != "SC":
            continue
        if (rec.get("county") or "").strip().lower() != _COUNTY:
            continue
        owner = rec.get("owner_name") or ""
        if not owner or is_entity(owner):
            continue
        raw = rec.get("raw")
        raw = raw if isinstance(raw, dict) else {}
        if _already_has_deed_ref(raw) or _already_tried_chain(raw):
            continue
        out.append(_light(rec))
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--depth", type=int, default=3)
    args = ap.parse_args()

    docs = REPO / "docs"
    now = datetime.now(timezone.utc)

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="marlboro_rod_chain_backfill")
    with lock:
        targets = _collect_targets(docs, args.limit)
        print(f"Marlboro SC targets this run: {len(targets):,} (--limit {args.limit})")
        patches: dict[str, dict] = {}
        counts = {"ok": 0, "partial": 0, "not_found": 0, "walled": 0, "capped": 0, "error": 0,
                 "bound": 0, "name_only": 0, "deed_ref_gained": 0}
        t0 = time.monotonic()
        for li in targets:
            try:
                res = chain(_COUNTY, li.owner_name, state="SC", depth=args.depth)
            except Exception as exc:  # noqa: BLE001
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
        _allow_large = os.environ.get("BOARD_PATCH_ALLOW_LARGE", "").strip().lower() in ("1", "true", "yes")
        if not size_state["ok"] and not _allow_large:
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
