"""Scheduled NC SOS registered-agent pass — fills raw['sos_agent'] (registered
agent + officers = a free mailable contact) for entity-owned NC leads that
otherwise have no owner contact. Runs on the committed board (no re-scrape);
stealth + slow so it is its own opt-in pass, not part of the weekly crawl.

Board-writer — run it alone (the weekly/merge/lrcpwa passes must not be active).
Idempotent: skips leads that already carry raw['sos_agent']. Sets SOS_AGENT=1
itself so the enricher is enabled.

BOARD I/O REWRITE (2026-09-30, same pattern as resolver_backfill_parcel.py's/
resolver_backfill_geocode.py's 2026-09-29 rewrites): this used to call
load_board() to build the WHOLE board as `listings`, mutate `sos_agent` in
place on the resolved/propagated subset, then write_artifact(listings, ...) —
the whole ~217K-row board re-validated and re-serialized to land what a single
run actually changes (SOS_AGENT_MAX_CHECK=60 new entities' worth of lookups,
plus however many co-owned rows propagate from them). That is exactly the
double materialization BOARD_LOAD_MAX_SOURCE_MB now refuses on this board's
real size (2,645+ MB, over the 1,200 MB ceiling — see web_artifact.py): this
script was, in practice, BLOCKED, failing every scheduled 14:00 run since
2026-09-30.

enrich_with_sos_agent()'s OWN cross-row logic (enrichment_sos_agent.py) is
genuinely board-wide: an entity name resolved on ANY lead is propagated to
EVERY OTHER lead sharing that entity name, anywhere on the board, for free
(no network). That is still board-wide cross-referencing here, but it is
GROUP-BY-KEY (entity name), not board-relative math — which streams fine as a
hash join, unlike (for contrast) distress_score.score_board()'s board-relative
percentile tiers. So:

  1. PASS 1 (_collect_resolved_profiles): stream the published board
     (board_stream.iter_board_rows(), read-only, no lazy-detail sidecar --
     sos_agent/owner_name/defendant are all in the slim payload, never
     LAZY_DETAIL_KEYS) to build entity name -> first already-resolved
     sos_agent profile (has a sosid) found ANYWHERE on the board. Mirrors
     enrich_with_sos_agent()'s own first loop exactly, including that it does
     NOT filter by state either.
  2. PASS 2 (_collect_targets): stream the board again for NC rows with an
     entity name and no sos_agent yet. A name already in resolved_profiles
     (from pass 1) is a propagation candidate -- patched immediately, no
     network, exactly like the original's second loop. Everything else is
     grouped by name and ranked HOT/WARM first (mirroring the original's
     local _prio(), duplicated here as a 4-line literal rather than reaching
     into enrich_with_sos_agent()'s closure -- it cannot be imported, being
     itself a nested function).
  3. The SOS_AGENT_MAX_CHECK-capped name list goes through the REAL, unchanged
     enrichment_sos_agent._batch_lookup() (the actual Scrapling/sosnc.gov
     network call -- imported directly, same convention that module itself
     uses importing enrichment_sos_dissolution._is_business/
     _strip_business_suffix: this codebase imports underscore-prefixed
     helpers across module boundaries rather than duplicate real logic).
  4. Every patch (propagated + newly resolved) lands in ONE
     web_artifact.patch_existing_rows() call, keyed by each row's
     dedupe_key() (identity fields are untouched by this pass, so capturing
     the key at collection time is safe with no pre/post-mutation ordering
     concern, unlike resolver_backfill_parcel.py's parcel_id case).

Usage:  SOS_AGENT_MAX_CHECK=80 uv run python scripts/sos_agent_refresh.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("SOS_AGENT", "1")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_sos_agent import _batch_lookup, _entity_of, _MAX_CHECK  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, board_lock, patch_existing_rows,
)

DOCS = REPO / "docs"

# Same identity fields web_artifact._APPEND_SIG_FIELDS keys patches on -- kept as a local
# literal rather than importing a private symbol (same choice resolver_backfill_geocode.py/
# run_dew_lien_enrichment.py made).
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")
_LIGHT_FIELDS = tuple(set(_SIG_FIELDS) | {"owner_name", "defendant", "raw"})


def _light_listing(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _prio(li: Listing) -> int:
    """Same ranking enrich_with_sos_agent()'s local _prio() closure uses -- HOT/WARM
    first -- duplicated here (not imported: it is a nested function, not a module-level
    name)."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    tier = ((raw.get("distress_stack") or {}).get("tier")
            or (raw.get("grade") or {}).get("tier") or "")
    return {"HOT": 0, "WARM": 1}.get(str(tier).upper(), 2)


def _collect_resolved_profiles(docs: Path) -> tuple[dict[str, dict], int, int]:
    """entity name -> first already-resolved sos_agent profile (has a sosid) found
    ANYWHERE on the board -- matches enrich_with_sos_agent()'s first pass exactly (no
    state filter there either). Also returns (total_rows, rows_with_any_sos_agent) so
    the caller can print the same "already have" baseline the original script did,
    without a second full-board scan just for that count.
    """
    resolved: dict[str, dict] = {}
    total = 0
    with_any = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        sa = raw.get("sos_agent")
        if not isinstance(sa, dict):
            continue
        with_any += 1
        if not sa.get("sosid"):
            continue
        li = _light_listing(rec)
        nm = _entity_of(li)
        if nm and nm not in resolved:
            resolved[nm] = sa
    return resolved, total, with_any


def _collect_targets(docs: Path, resolved_profiles: dict[str, dict]):
    """Second pass, matching enrich_with_sos_agent()'s second loop: NC rows with an
    entity name and no sos_agent yet. A name already in resolved_profiles is a
    propagation candidate (patched immediately, no network); everything else is
    grouped by name for a possible SOS lookup this run, ranked HOT/WARM first exactly
    as the original's local _prio() does.

    Returns (name_to_keys, ranked, propagate_patches, propagated).
    """
    name_to_keys: dict[str, list[str]] = {}
    ranked: list[tuple[int, str]] = []
    seen_names: set[str] = set()
    propagate_patches: dict[str, dict] = {}
    propagated = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if rec.get("state") != "NC":
            continue
        li = _light_listing(rec)
        name = _entity_of(li)
        if not name:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        if isinstance(raw.get("sos_agent"), dict):
            continue  # already resolved on this lead
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
            continue
        if name in resolved_profiles:
            propagate_patches[key] = {"raw": {"sos_agent": resolved_profiles[name]}}
            propagated += 1
            continue
        if name not in seen_names:
            seen_names.add(name)
            ranked.append((_prio(li), name))
        name_to_keys.setdefault(name, []).append(key)
    return name_to_keys, ranked, propagate_patches, propagated


def main() -> int:
    # THE LOCK, held across the two read passes -> lookup -> patch.
    #
    # Reentrant: scripts/sos_agent_refresh.sh already holds it when it invokes
    # this script and passes it down through FORECLOSURE_BOARD_LOCK_HELD, so
    # this acquire is a no-op there. It matters when the pass is run by hand.
    try:
        with board_lock(REPO, owner="sos_agent_refresh.py"):
            return _run()
    except BoardLockBusy as exc:
        print(f"{exc} — skipping this pass.", flush=True)
        return 0


def _run() -> int:
    resolved_profiles, total_rows, with_any_sos_agent = _collect_resolved_profiles(DOCS)
    name_to_keys, ranked, propagate_patches, propagated = _collect_targets(DOCS, resolved_profiles)

    ranked.sort(key=lambda t: t[0])
    names = [n for _, n in ranked][:_MAX_CHECK]
    print(f"loaded {total_rows} | already have sos_agent={with_any_sos_agent} | "
          f"resolved entities={len(resolved_profiles)} | propagate-candidates={propagated} | "
          f"new-entity targets={len(names)} (of {len(name_to_keys)} unresolved names)", flush=True)

    counts = {"targets": len(names), "resolved": 0, "with_contact": 0, "misses": 0,
              "propagated": propagated}
    pending_patches: dict[str, dict] = dict(propagate_patches)

    if os.environ.get("SOS_AGENT") == "1" and names:
        results = asyncio.run(_batch_lookup(names))
        for name, prof in results.items():
            if not prof or not prof.get("sosid"):
                counts["misses"] += 1
                continue
            counts["resolved"] += 1
            if prof.get("best_contact_address") or prof.get("best_contact_name"):
                counts["with_contact"] += 1
            for key in name_to_keys.get(name, []):
                pending_patches[key] = {"raw": {"sos_agent": prof}}

    print("sos_agent:", counts, flush=True)

    if not pending_patches:
        print("nothing to patch", flush=True)
        return 0

    stats = patch_existing_rows(
        pending_patches, {"notes": "scheduled NC SOS registered-agent refresh"}, docs_dir=DOCS)
    with_contact_added = sum(
        1 for p in pending_patches.values()
        if ((p.get("raw") or {}).get("sos_agent") or {}).get("best_contact_name"))
    print(f"patched {stats['applied']}/{len(pending_patches)} rows "
          f"(existing board: {stats['existing']:,}) | "
          f"sos_agent≈{with_any_sos_agent + stats['applied']} "
          f"(+{stats['applied']}: {propagated} propagated, {counts['resolved']} newly resolved) | "
          f"with_contact_added={with_contact_added}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
