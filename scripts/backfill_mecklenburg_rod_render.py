#!/usr/bin/env python3
"""Mecklenburg-scoped checkpointed backfill for raw['rod'] (register-of-deeds lien existence) via
the REAL, already-wired enrich_nc_rod_render() / rod/nc_harris.py Harris 'ROD Web Access' adapter
-- the gap_matrix 2026-11-11 run's "atty_rod_lien_checked" AND "liens" entries for Mecklenburg NC
(39,861 rows each). Both gap_list rows are THE SAME underlying signal: gap_matrix.py's own
checked_columns() marks "liens" checked whenever raw['rod'] is present (`if raw.get("rod") or
raw.get("liens"): out |= {"liens", "lien_priority"}`), so one producer call closes both rows.

THE GAP_LIST'S OWN ENRICHER NAMES ARE WRONG FOR MECKLENBURG (read, not assumed, 2026-11-11):
    atty_rod_lien_checked points at enrichment_aumentum_rod / enrichment_cchs_rod; liens points at
    enrichment_dew_liens / enrichment_irs_lien. These are gap_matrix.py's SPECS producer tuples --
    the generic, whole-family list of every module that CAN write this kind of field somewhere on
    the board, not a per-county lookup. None of the four actually reach Mecklenburg:
      * enrichment_aumentum_rod.py's own _COUNTIES = {"Buncombe"} only. Mecklenburg IS in the SAME
        vendor module's raw AUMENTUM_COUNTIES url map (rod/aumentum.py), but that module's own
        2026-10-02 dead-host investigation already records a live probe result for it: "sibling
        Aumentum tenants Buncombe (0.4s) and Mecklenburg (0.4s, 403 as expected without
        impersonation)" -- consistent with the enricher's own county set never including it.
      * enrichment_cchs_rod.py's _COUNTIES = {Burke, Cleveland, Madison, Henderson, Lincoln, Duplin}
        -- a different vendor (Courthouse Computer Systems classic ASP). Never Mecklenburg.
      * enrichment_dew_liens.py is SC-only: it cross-references the SC Dept of Employment &
        Workforce lien registry against SC leads by owner name. Structurally cannot touch an NC row.
      * enrichment_irs_lien.py is RETIRED -- its own docstring: "main.py does not run this module
        and nothing should" (2026-10-09 unwired-enrichers audit). Not callable from the real
        pipeline at all.

THE REAL PRODUCER (confirmed by reading main.py's own wiring):
    raw['rod'] for Mecklenburg comes from enrichment_nc_rod_render.enrich_nc_rod_render(), called
    from main.py (~line 3231, `_await_capped(enrich_nc_rod_render(enriched), "nc_rod_render", ...)`)
    every run -- but ONLY over that run's own freshly-merged `enriched` list, the SAME "never a
    full historical sweep" shape backfill_tax_aging_surfaced.py's docstring already diagnosed for
    enrich_tax_aging(). It dispatches via enrichment_generic_rod.RENDER_ROD_CONFIG[("NC",
    "Mecklenburg")] = ("nc_harris", "FORECLOSURE_NC_HARRIS_ROD", "0") -- rod/nc_harris.py's Harris
    'ROD Web Access' adapter, LIVE-VERIFIED WORKING on Mecklenburg 2026-10-07 (its own docstring:
    "FLOW (live-checked 2026-10-07 on Carteret and Mecklenburg)"; WALLED_COUNTIES = ("Moore",) only
    -- NOT Mecklenburg). So this is NOT a CAPTCHA/login wall (not Hermes's lane): no sign-in, no
    CAPTCHA, just one disclaimer click-through, same as a ToS click-through.

    BUT it is also NOT a cheap offline recompute like enrich_tax_aging()/enrich_deed_chain() either.
    It is a genuine LIVE, per-owner-name, HEADLESS-BROWSER lookup (rod/nc_render.py), and
    rod/nc_platform.py's NcRodPlatform.search() holds ONE LOOKUP AT A TIME PER COUNTY (a county
    lock -- the search/results flow lives in server-side session state, so two interleaved lookups
    would mix their names). Mecklenburg lookups cannot run concurrently with each other no matter
    how this script is written. enrichment_nc_rod_render.py's own docstring: "a browser lookup costs
    tens of seconds." At a conservative 15-30s/lookup, strictly serial, the full 39,861-row backlog
    is an estimated 7-17 DAYS of continuous run time -- a capacity/policy decision (matching why
    EVERY RENDER_ROD_CONFIG entry, for every platform, ships its flag default "0"), not a bug this
    script shortcuts. rod/nc_polite.py's per-run lookup cap (FORECLOSURE_NC_HARRIS_ROD_MAX, default
    30 via DEFAULT_MAX_LOOKUPS_PER_COUNTY) is an in-memory, per-PROCESS counter (nc_polite._lookups,
    never persisted) -- a real bulk run needs that raised well above 30 so one long-running process
    (which caches its browser session for SESSION_TTL_S=20min) does the work, not 30-lookup process
    restarts repeatedly re-paying session-open overhead.

WHAT THIS SCRIPT DOES: the SAME checkpointed-batch pattern scripts/backfill_lincoln_cchs_rod.py
established for exactly this situation (an existing, wired, network-calling enricher never run
against one county's full backlog) -- but for enrich_nc_rod_render()/nc_harris instead of
enrich_cchs_rod(). Streams the board once (board_stream.iter_board_rows(), never load_board()),
scopes to --county/--state (default Mecklenburg/NC), builds cheap Listing.model_construct()
objects carrying only what enrich_nc_rod_render() actually reads (state/county/owner_name/raw)
plus the identity fields dedupe_key() needs, runs the REAL unmodified enrich_nc_rod_render() per
batch, diffs raw['rod'] before/after per row (so a batch the function's own BUDGET_S cuts short
mid-way still lands whatever it did finish), and writes via patch_existing_rows() in small batches
-- one board write per batch, so an interrupted multi-day run loses at most one batch.

--DRY-RUN IS DELIBERATELY NARROWER HERE THAN backfill_lincoln_cchs_rod.py's OWN --dry-run.
    Lincoln's script's --dry-run skips only the final board WRITE -- it still calls the real,
    network-calling enrich_cchs_rod() for real. That is right for CCHS (plain httpx, ~0.3s/lookup)
    but wrong to copy unmodified here: a Mecklenburg "dry run" under that same convention would
    still drive a real headless browser against meckrod.manatron.com from whatever machine runs
    it. This script's --dry-run instead skips the board_lock AND the network call entirely -- it
    only scans/scopes/counts eligible rows (owner_name present, raw['rod'] absent -- the exact
    idempotency test enrich_nc_rod_render() itself applies) so its numbers are a LOGIC/ELIGIBILITY
    validation, not a yield measurement. Running the real lookups -- even a small bounded trial --
    is a deliberate, separate call for the orchestrating session to make (see --batch-size/
    --max-batches below for a way to bound a first supervised trial rather than committing to the
    full multi-day backlog). FORECLOSURE_NC_HARRIS_ROD=1 is set by this script itself via
    os.environ.setdefault (so an operator who deliberately exported "0" to force the platform off
    is still respected).

    python scripts/backfill_mecklenburg_rod_render.py --dry-run
    python scripts/backfill_mecklenburg_rod_render.py --dry-run --county Mecklenburg --state NC
    # orchestrating session, on the VM -- a bounded first trial to measure the real per-lookup
    # time before committing to the full ~39.8K-row backlog:
    BOARD_PATCH_ALLOW_LARGE=1 FORECLOSURE_NC_HARRIS_ROD_MAX=500 \\
        python scripts/backfill_mecklenburg_rod_render.py --batch-size 20 --max-batches 1
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
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name")

# Set before importing enrichment_nc_rod_render / enrichment_generic_rod so their module-level
# reads of this flag (via platform_enabled(), checked per-call not cached, so this is really just
# documentation of intent) see it turned on for this process. setdefault: an operator who
# deliberately exported "0" to force the platform off is respected, never overridden.
os.environ.setdefault("FORECLOSURE_NC_HARRIS_ROD", "1")


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _candidates(docs_dir: Path, want_state: str | None, want_county: str | None
                 ) -> list[tuple[str | None, Listing]]:
    """Every row in scope whose owner_name is set and whose raw['rod'] is not already present --
    the exact idempotency test enrich_nc_rod_render() itself applies (`if isinstance(li.raw, dict)
    and li.raw.get("rod"): continue`), so this never double-counts a row the real function would
    itself skip."""
    out = []
    total = 0
    in_scope = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        total += 1
        st = (rec.get("state") or "").strip().upper()
        co = (rec.get("county") or "").strip()
        if want_state and st != want_state:
            continue
        if want_county and co != want_county:
            continue
        in_scope += 1
        li = _light(rec)
        if not (li.owner_name or "").strip():
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if raw.get("rod"):
            continue  # already checked -- idempotent, matches the real function's own skip
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            key = None
        out.append((key, li))
    print(f"board rows scanned: {total:,} | in-scope "
          f"(state={want_state or 'any'}/county={want_county or 'any'}): {in_scope:,}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--batch-size", type=int, default=20,
                    help="Rows per enrich_nc_rod_render() call. Kept small by default (unlike "
                         "backfill_lincoln_cchs_rod.py's 1000): at tens of seconds per lookup, "
                         "even 20 rows can take ~10 minutes, a sane checkpoint interval.")
    ap.add_argument("--max-batches", type=int, default=5,
                    help="Stop after this many batches (default 5 => up to 100 rows). Raise this "
                         "deliberately once the real per-lookup time on the VM is measured.")
    ap.add_argument("--state", default="NC")
    ap.add_argument("--county", default="Mecklenburg")
    args = ap.parse_args()

    docs_dir = REPO / "docs"
    want_state = (args.state or "").strip().upper() or None
    want_county = (args.county or "").strip() or None

    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        print(f"board_patch_size_state: {size_state}")
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
    else:
        print(f"board_patch_size_state (informational): {board_patch_size_state(docs_dir)}")

    all_cands = _candidates(docs_dir, want_state, want_county)
    no_key = sum(1 for k, _ in all_cands if k is None)
    print(f"eligible (owner present, raw['rod'] absent): {len(all_cands):,} "
          f"(of which no usable dedupe_key: {no_key:,})")
    # tens-of-seconds-per-lookup, strictly serial (one county lock) -- see module docstring.
    for lo, hi, label in ((15, 30, "15-30s/lookup"),):
        days_lo = len(all_cands) * lo / 86400
        days_hi = len(all_cands) * hi / 86400
        print(f"estimated wall-clock for the FULL eligible set at {label}, strictly serial: "
              f"{days_lo:.1f}-{days_hi:.1f} days")
    if not all_cands:
        print("nothing to do.")
        return 0

    if args.dry_run:
        print("\nDRY RUN -- enrich_nc_rod_render() was NOT called (no network, no headless "
              "browser). This is an eligibility/logic validation only, not a yield measurement -- "
              "see module docstring for why this script's --dry-run differs from "
              "backfill_lincoln_cchs_rod.py's.")
        return 0

    total_searched = 0
    total_with_instruments = 0
    total_written = 0

    for batch_num in range(1, args.max_batches + 1):
        start = (batch_num - 1) * args.batch_size
        chunk = all_cands[start:start + args.batch_size]
        if not chunk:
            print(f"batch {batch_num}: no more rows, stopping")
            break
        print(f"\n=== Mecklenburg nc_rod_render batch {batch_num}: {len(chunk)} rows ===")
        from foreclosure_scraper.enrichment_nc_rod_render import enrich_nc_rod_render
        listings = [li for _, li in chunk]
        stats = asyncio.run(enrich_nc_rod_render(listings))
        print(f"  {stats}")
        total_searched += stats.get("searched", 0)
        total_with_instruments += stats.get("with_instruments", 0)

        patches = {}
        for key, li in chunk:
            if key is not None and isinstance(li.raw, dict) and "rod" in li.raw:
                patches[key] = {"raw": {"rod": li.raw["rod"]}}
        print(f"  patches this batch: {len(patches)}")

        if not patches:
            continue
        with board_lock(REPO, owner="mecklenburg_rod_render_backfill", wait=600, poll=10):
            pstats = patch_existing_rows(
                patches, {"mecklenburg_rod_render_backfill_batch": len(patches)}, docs_dir=docs_dir)
        print(f"  patch_existing_rows: {pstats}")
        total_written += pstats.get("applied", 0)

    print(f"\ntotals: searched={total_searched:,} with_instruments={total_with_instruments:,} "
          f"written={total_written:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
