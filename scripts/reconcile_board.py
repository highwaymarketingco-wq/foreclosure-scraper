#!/usr/bin/env python3
"""Re-apply the cheap, local, late-binding steps to a scored checkpoint: no scrapers, no network.

WHY (audit 2026-10-09, pipeline_gate)
    After an 18-hour run, the things that change most are the cheapest to apply: a verification
    ledger the Mac's sweep updated, a tax-binding rule, a scorer fix. Until now each needed either a
    new full run (~18 h) or `vm_resume.sh --enrich-only`, which re-runs the WHOLE post-dot_ocr tail
    including its network enrichers (divorce, the name resolver, tax relief, court bids, assessor
    cards, photos, ...: 3 h 12 min on 10/5). This runs the same tail, the SAME function
    (main.run_enrich_tail, so the steps and their order cannot drift), with every network step
    stubbed out and the network itself blocked. What is left is local: the tax scrub inside
    enrich_tax_owed (tax_binding.scrub_unbound_tax), tax aging, valuation and grades, equity, deed
    chain, flags, verification apply, restore_verified_tax, score_board and every post-score
    signal, board quality and QA, the run summary.

WHAT IT DOES
    1. reads the checkpoint (default data/checkpoint; a pre_publish one, from a gated full run, an
       --enrich-only resume or an earlier reconcile) and its publish inputs (resume_state.json,
       sold pool), refusing a checkpoint whose inputs are missing or not its own;
    2. optional --prior-correction: enrichment_prior_correction.correct_prior_rows (needs the
       parcel cache; idempotent, it runs before the dot_ocr checkpoint in main.run);
    3. main.run_enrich_tail() with the NETWORK_STUBS below (each returns "skipped", rows keep what
       the run gave them) and every socket connect refused (an unlisted network step fails fast
       inside its own try/except and is reported, never fetches);
    4. saves the result as a pre_publish checkpoint (the old one is archived first by
       checkpoint.save_pre_publish), carrying the run's publish switches, scrape-phase health,
       errors, by_source and sold pool exactly as scripts/carry_publish_state.py does;
    5. runs scripts/audit_suite.py and scripts/board_selfcheck.py --checkpoint on it (--no-checks
       skips). Publishing stays a separate, reviewed step: vm_resume.sh --publish-only.
    It never writes docs/: outreach (docs/crm.json, docs/outreach_maillist.csv) is a stub here, and
    the source-health history, run_health, the sold pool file, the Sheet and the email are publish
    or full-run steps.

WHAT IT CANNOT DO (use the full run or --enrich-only)
    Anything a network step would change (new rows, a jail roster re-read, a resolver match, a
    county exemption layer), and anything BEFORE the dot_ocr checkpoint other than the optional
    prior correction: merge_prior_board, dedupe, gis_attrs, the scrapers.

MEMORY
    It holds the board as Listings, like the resume: ~12.5 GB measured for 350K rows on the VM
    (the --enrich-only resume of 10/7). On macOS it refuses a checkpoint over --max-rows (default
    25,000) so it can only be pointed at a canary or a sample there.

USAGE
    python3 scripts/reconcile_board.py [--checkpoint DIR] [--prior-correction] [--no-checks]
    setsid nohup bash deploy/oracle/vm_resume.sh --reconcile >/dev/null 2>&1 < /dev/null &
Exit: 0 saved and the checks passed; 1 refused or not saved; 4 saved but a check failed (review);
6 scoring failed (nothing saved); 75 board lock busy.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

#: Network steps of main.run_enrich_tail, by (module under foreclosure_scraper, attribute): what the
#: stub returns. "skip" an awaitable giving {"skipped": "reconcile"}; "none" an awaitable giving
#: None; "sync_skip" a plain call giving {"skipped": "reconcile"}; "passthrough" an awaitable giving
#: (its first argument, {"skipped": "reconcile"}); "unmatched" an awaitable giving {"matched": 0}.
#: tests/test_reconcile_board.py fails when run_enrich_tail imports a step that is in neither this
#: nor LOCAL_STEPS, so a new tail step must be classified before a reconcile can run it.
NETWORK_STUBS: dict[tuple[str, str], str] = {
    ("enrichment_jail_bookings", "enrich_jail_bookings"): "skip",       # county jail rosters
    ("enrichment_nc_divorce", "enrich_nc_divorce"): "skip",
    ("enrichment_sc_divorce", "enrich_sc_divorce"): "skip",
    ("enrichment_resolve_name_to_property", "enrich_resolve_name_to_property"): "skip",
    ("enrichment_acpass", "enrich"): "skip",
    ("enrichment_recorded_comps", "enrich"): "none",                    # resolved catch-up
    ("enrichment_comps", "enrich_with_comps"): "none",
    ("enrichment_photos", "enrich_with_address_photos"): "none",
    ("enrichment_images", "enrich_with_images"): "none",
    ("enrichment_vision", "enrich_with_vision"): "none",
    ("enrichment_tax_relief", "enrich_tax_relief"): "skip",             # county exemption layers
    ("enrichment_rollback_deferral", "enrich_with_rollback_exposure"): "skip",
    ("enrichment_court_bid", "enrich_court_bid"): "skip",
    ("enrichment_fhfa_value", "enrich_fhfa_value"): "skip",
    ("enrichment_dew_liens", "enrich_dew_liens"): "skip",
    ("enrichment_assessor_card", "enrich_assessor_card"): "sync_skip",
    ("obituary_lookup", "enrich_obituary_lookups"): "skip",
    ("enrichment_burke_history", "enrich_burke_parcel_history"): "none",
    ("enrichment_lrcpwa_photo", "enrich_lrcpwa_photo"): "skip",
    ("enrichment_homepath_uuid", "enrich_homepath_uuids"): "skip",
    ("enrichment_reo_freshness", "prune_stale_reo"): "passthrough",     # keeps every row
    ("enrichment_fema_disaster", "fetch_helene_disaster_data"): "none",  # rows keep their block
    ("enrichment_opportunity_zone", "enrich_opportunity_zones"): "none",
    ("enrichment_usps_vacancy", "enrich_usps_vacancy"): "none",
    ("valuation.rentcast", "enrich_top_n"): "unmatched",
    ("outreach", "generate_outreach"): "sync_skip",                     # writes docs/crm.json
}

#: Local steps run_enrich_tail imports that a reconcile RUNS (no network; they read the rows, the
#: ledgers in docs/handoff/verification, local reference data, or the published board's keys).
LOCAL_STEPS: frozenset[tuple[str, str]] = frozenset({
    ("tax_binding", "scrub_unbound_tax"), ("tax_binding", "restore_verified_tax"),
    ("block_binding", "scrub_unbound_blocks"),
    ("enrichment_assessor_comps", "enrich_assessor_comps"),
    ("enrichment_tax_owed", "enrich_tax_owed"), ("enrichment_amount_owed", "promote_tax_owed_amount_owed"),
    ("enrichment_tax_aging", "enrich_tax_aging"), ("enrichment_bankruptcy_tax_combo", "enrich_bankruptcy_tax_combo"),
    ("enrichment_tenure", "enrich_tenure"), ("enrichment_life_events", "enrich_life_events"),
    ("enrichment_upset_bid", "enrich_upset_bid"), ("enrichment_process_timing", "enrich_process_timing"),
    ("enrichment_lien_stack", "enrich_lien_stack"), ("enrichment_sc_cama", "enrich_sc_cama"),
    ("enrichment_footprint_sqft", "enrich_footprint_sqft"),
    ("enrichment_court_owner_verify", "enrich_court_owner_verify"),
    ("enrichment_entity_type", "enrich_entity_type"), ("enrichment_equity", "enrich_equity"),
    ("enrichment_deed_chain", "enrich_deed_chain"), ("enrichment_title_risk", "enrich_title_risk"),
    ("enrichment_vacant_landuse", "enrich_vacant_landuse"), ("verification.apply", "apply_verification"),
    ("distress_score", "score_board"), ("distress_score", "ScoreBoardError"), ("distress_score", "LAST_STATS"),
    ("enrichment_derived_signals", "enrich_derived_signals"),
    ("enrichment_owner_name_signal", "enrich_owner_name_signal"),
    ("enrichment_co_defendant_signal", "enrich_co_defendant_signal"),
    ("enrichment_hoa_plaintiff_signal", "enrich_hoa_plaintiff_signal"),
    ("enrichment_owner_cluster", "enrich_owner_cluster"), ("enrichment_repeat_tax_loss", "enrich_repeat_tax_loss"),
    ("enrichment_liensnc_posthumous", "enrich_liensnc_posthumous"),
    ("enrichment_obituary_match", "enrich_obituary_match"), ("enrichment_heir_candidates", "enrich_heir_candidates"),
    ("enrichment_platted_lots", "enrich_platted_lots"),
    ("enrichment_divorce_no_subsequent_deed", "enrich_divorce_no_subsequent_deed"),
    ("enrichment_notice_service_defect", "enrich_notice_service_defect"), ("fullmer_rank", "rank_board"),
    ("enrichment_derivation_flags", "enrich_derivation_flags"), ("enrichment_strategy_fit", "enrich_strategy_fit"),
    ("enrichment_eviction_market", "enrich_eviction_market"), ("enrichment_corroboration", "enrich_corroboration"),
    ("enrichment_competition", "enrich_competition"), ("enrichment_lead_signals", "enrich_lead_signals"),
    ("enrichment_buyer_match", "enrich_buyer_match"), ("enrichment_data_quality", "enrich_data_quality"),
    ("new_listings", "mark_new_listings"), ("enrichment_board_quality", "enrich_board_quality"),
    ("enrichment_last_sale", "enrich_last_sale"), ("enrichment_board_qa", "enrich_board_qa"),
    ("enrichment_source_link", "enrich_source_link"), ("web_artifact", "plain_board_row_count"),
    # imported by the tail but never called by a reconcile (TailState.update_source_health=False)
    ("source_health_tracker", "update_source_health"),
})

#: raw marker that keeps the resolved-lead catch-up (comps / photos / vision for rows the name
#: resolver just placed) from running in a reconcile: its enrichers are stubs, and it would then
#: stamp _resolved_deep_enriched on rows that got nothing. Removed again after the tail.
HOLD = "reconcile_hold"


class NetworkBlocked(ConnectionRefusedError):
    """A reconcile never opens a network connection."""


@contextlib.contextmanager
def network_blocked():
    """Refuse every TCP/UDP connect and name lookup while active (AF_UNIX stays allowed)."""
    orig_connect, orig_connect_ex = socket.socket.connect, socket.socket.connect_ex
    orig_create, orig_gai = socket.create_connection, socket.getaddrinfo

    def _connect(self, addr, *a, **k):
        if getattr(socket, "AF_UNIX", None) is not None and self.family == socket.AF_UNIX:
            return orig_connect(self, addr, *a, **k)
        raise NetworkBlocked(f"reconcile_board: network blocked ({addr!r})")

    def _connect_ex(self, addr, *a, **k):
        if getattr(socket, "AF_UNIX", None) is not None and self.family == socket.AF_UNIX:
            return orig_connect_ex(self, addr, *a, **k)
        raise NetworkBlocked(f"reconcile_board: network blocked ({addr!r})")

    def _create(addr, *a, **k):
        raise NetworkBlocked(f"reconcile_board: network blocked ({addr!r})")

    def _gai(host, *a, **k):
        raise NetworkBlocked(f"reconcile_board: name lookup blocked ({host!r})")

    socket.socket.connect, socket.socket.connect_ex = _connect, _connect_ex
    socket.create_connection, socket.getaddrinfo = _create, _gai
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex = orig_connect, orig_connect_ex
        socket.create_connection, socket.getaddrinfo = orig_create, orig_gai


def _stub(kind: str, name: str):
    skipped = {"skipped": "reconcile"}
    if kind == "sync_skip":
        return lambda *a, **k: dict(skipped)

    async def _a(*a, **k):
        if kind == "skip":
            return dict(skipped)
        if kind == "passthrough":
            return (a[0] if a else k.get("listings")), dict(skipped)
        if kind == "unmatched":
            return {"matched": 0, **skipped}
        return None
    _a.__name__ = f"reconcile_stub_{name}"
    return _a


@contextlib.contextmanager
def network_stubbed():
    """Replace every NETWORK_STUBS attribute on its module (run_enrich_tail imports each one at
    call time, so it gets the stub), restoring the originals afterwards."""
    saved = []
    try:
        for (mod_name, attr), kind in NETWORK_STUBS.items():
            mod = importlib.import_module(f"foreclosure_scraper.{mod_name}")
            saved.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, _stub(kind, attr))
        yield
    finally:
        for mod, attr, orig in reversed(saved):
            setattr(mod, attr, orig)


def hold_catchup(listings) -> list:
    """Mark the rows the resolved-lead catch-up would pick (see HOLD); return them."""
    held = []
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else None
        if raw is None:
            continue
        if ((raw.get("resolved_from_name") or {}).get("confidence") == "unique_match"
                and (li.street_address or li.parcel_id) and not raw.get("_resolved_deep_enriched")):
            raw["_resolved_deep_enriched"] = HOLD
            held.append(li)
    return held


def release_catchup(held) -> None:
    for li in held:
        if isinstance(li.raw, dict) and li.raw.get("_resolved_deep_enriched") == HOLD:
            del li.raw["_resolved_deep_enriched"]


async def reconcile_tail(listings, *, enrichment_stats: dict | None = None):
    """main.run_enrich_tail() on `listings`, local steps only. Returns (TailState, summary)."""
    import foreclosure_scraper.main as M
    from foreclosure_scraper.config import RuntimeConfig
    st = M.TailState(enriched=listings, enrichment_stats=dict(enrichment_stats or {}), errors=[],
                     cfg=RuntimeConfig.from_env(), update_source_health=False, write_sold_pool=False,
                     write_run_health=False, export_and_email=False)
    held = hold_catchup(listings)
    try:
        with network_stubbed(), network_blocked():
            summary = await M.run_enrich_tail(st)
    finally:
        release_catchup(held)
    st.enrichment_stats["reconcile"] = {"catchup_held": len(held), "network_stubs": len(NETWORK_STUBS)}
    return st, summary


def carried_publish_inputs(old_state: dict, st, summary: dict) -> tuple[dict, dict]:
    """(state dict for st, summary) with the run's publish inputs carried over the reconcile's."""
    import carry_publish_state as C
    new_state = {"summary": summary, "enrichment_stats": st.enrichment_stats, "errors": st.errors,
                 "publish": {}, "scoring_failed": st.scoring_failed}
    out = C.carry(old_state, new_state, old_saved_at=None) if old_state else new_state
    return out, out.get("summary") or summary


def _run_checks(ckpt: Path) -> tuple[bool, list[str]]:
    out, ok = [], True
    for cmd in ([sys.executable, str(REPO / "scripts" / "audit_suite.py"), "--checkpoint", str(ckpt),
                 "--out", str(ckpt / "suite_result.json")],
                [sys.executable, str(REPO / "scripts" / "board_selfcheck.py"), "--checkpoint", str(ckpt)]):
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        name = Path(cmd[1]).name
        out.append(f"{name}: exit {r.returncode}")
        print((r.stdout or "")[-4000:])
        ok = ok and r.returncode == 0
    return ok, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--checkpoint", default=str(REPO / "data" / "checkpoint"))
    ap.add_argument("--prior-correction", action="store_true",
                    help="also run correct_prior_rows (needs data/parcel_cache)")
    ap.add_argument("--allow-phase", default="pre_publish",
                    help="the checkpoint phase to accept (default pre_publish: a scored board)")
    ap.add_argument("--max-age-h", type=float, default=None)
    ap.add_argument("--max-rows", type=int,
                    default=25_000 if sys.platform == "darwin" else 0,
                    help="refuse a bigger checkpoint (0 = no limit; default 25,000 on macOS)")
    ap.add_argument("--no-checks", action="store_true")
    a = ap.parse_args(argv)
    os.chdir(REPO)

    from foreclosure_scraper import checkpoint
    checkpoint.CHECKPOINT_DIR = Path(a.checkpoint)
    m = checkpoint.manifest()
    if not m:
        print(f"no checkpoint in {a.checkpoint}", file=sys.stderr)
        return 1
    if m.get("phase") != a.allow_phase:
        print(f"checkpoint phase is {m.get('phase')!r}, not {a.allow_phase!r}: a reconcile re-applies "
              f"the late steps to a SCORED board (a dot_ocr checkpoint needs vm_resume.sh --enrich-only)",
              file=sys.stderr)
        return 1
    if a.max_rows and int(m.get("count") or 0) > a.max_rows:
        print(f"checkpoint has {m.get('count'):,} rows, over --max-rows {a.max_rows:,}: a reconcile holds "
              f"the whole board as Listings (~12.5 GB at 350K rows); run it on the VM", file=sys.stderr)
        return 1
    state, why = checkpoint.load_publish_state()
    if why:
        print(f"not reconciling: {why}", file=sys.stderr)
        return 1
    pub = state.get("publish") or {}
    sold = checkpoint.load_sold_pool() if pub.get("write_sold_pool") else None
    if pub.get("write_sold_pool") and sold is None:
        print("not reconciling: the run's sold pool is switched on but unreadable", file=sys.stderr)
        return 1

    import foreclosure_scraper.main as M
    M._setup_logging()
    from foreclosure_scraper.web_artifact import BoardLockBusy, BoardMemoryPressure, board_lock
    t0 = time.monotonic()
    try:
        with board_lock(owner="reconcile_board",
                        max_runtime=int(os.environ.get("FULLRUN_LOCK_MAX_RUNTIME", "259200"))):
            limit = a.max_age_h if a.max_age_h is not None else checkpoint.PRE_PUBLISH_MAX_AGE_H
            listings = checkpoint.load(max_age_h=limit)
            if not listings:
                print("checkpoint could not be loaded (too old or unreadable)", file=sys.stderr)
                return 1
            M.log.info("reconcile.loaded", leads=len(listings), phase=m.get("phase"),
                       saved_at=m.get("saved_at"))
            # Archived BEFORE anything changes: a scoring failure inside the tail checkpoints
            # "score_failed" over this directory (main.run_enrich_tail does that on purpose), and
            # the archive is how the reviewed board comes back.
            checkpoint.archive()
            pre_stats: dict = {}
            if a.prior_correction:
                from foreclosure_scraper.enrichment_prior_correction import CacheReader, correct_prior_rows
                with network_blocked():
                    pre_stats["prior_correction"] = correct_prior_rows(listings, cache=CacheReader())
            try:
                st, summary = asyncio.run(reconcile_tail(listings, enrichment_stats=pre_stats))
            except M.ScoreBoardFailed as exc:
                print(f"reconcile: {exc}", file=sys.stderr)
                return M.EXIT_SCORE_FAILED
            new_state, summary = carried_publish_inputs(state, st, summary)
            st.errors = new_state.get("errors") or []
            st.enrichment_stats = new_state.get("enrichment_stats") or st.enrichment_stats
            st.write_sold_pool = bool(pub.get("write_sold_pool"))
            st.sold_pool = sold or []
            st.write_run_health = bool(pub.get("write_run_health"))
            st.export_and_email = bool(pub.get("export_and_email"))
            note = (f"reconciled (local late-binding steps, scripts/reconcile_board.py) from the "
                    f"{m.get('phase')} checkpoint saved {m.get('saved_at')}")
            summary["notes"] = (str(summary.get("notes") or "") + "; " + note).strip("; ")
            saved = checkpoint.save_pre_publish(
                st, summary, extra={"reconciled_from": {k: m.get(k) for k in ("phase", "saved_at", "count")},
                                    **({"origin": m["origin"]} if m.get("origin") else {}),
                                    **({"resumed_from": m["resumed_from"]} if m.get("resumed_from") else {})})
            M.log.info("reconcile.saved", saved=saved, leads=len(st.enriched),
                       seconds=round(time.monotonic() - t0, 1), scoring_failed=st.scoring_failed)
            if not saved:
                return 1
    except BoardLockBusy as exc:
        print(f"reconcile: not started: {exc}", file=sys.stderr)
        return 75
    except BoardMemoryPressure as exc:
        print(f"reconcile: not started: {exc}", file=sys.stderr)
        return 75
    print(f"reconciled {m.get('count'):,} rows in {time.monotonic() - t0:.0f}s -> pre_publish checkpoint "
          f"{a.checkpoint}; publish after review: vm_resume.sh --publish-only")
    if a.no_checks:
        return 0
    ok, lines = _run_checks(Path(a.checkpoint))
    print("checks: " + "; ".join(lines))
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
