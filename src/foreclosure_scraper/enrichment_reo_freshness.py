"""Snapshot-REO freshness pruner + upserter.

Fannie Mae HomePath publishes its COMPLETE current REO inventory on every run.
When a property SELLS it drops out of the feed — but because the merge/regenerate
carry leads over from the persisted dashboard, the sold listing lingers. Its
per-property SPA URL (``/property/{uuid}``) then renders a *client-side* 404 in
the browser once the uuid leaves inventory (the HTTP status is still 200 — only
the JS app knows it's gone), so the operator clicks a dead link.

This module re-runs the snapshot scrapers and does two things with the result:

1. PRUNE — builds the set of still-live per-property URLs and drops any
   carried-over lead whose URL is no longer live (sold/withdrawn).
2. UPSERT — lands the fresh pull onto the board. A fresh row that matches an
   existing board row on (source, normalized street address, state) — NOT on
   source_url/case_number, which embed Fannie's propertyUuid and ROTATE on
   every pull, which is exactly why the per-property link 404s in the first
   place — has its volatile fields (source_url, case_number, opening_bid,
   last_seen) refreshed in place, preserving every enrichment field (vision,
   comps, grade, ...) already on that row. A fresh row with NO match is a
   listing the earlier scrape/dedupe/scope pipeline never landed (most often
   because the main scrape phase's own attempt at this same scraper timed out
   — see tests/test_fannie_homepath_timeout.py and
   docs/full_run_execution_audit_2026-09-23.md) and is appended as a new row,
   gated through the SAME `_in_scope` check the main pipeline applies to every
   national.* row (imported lazily from `.main`, mirroring the identical
   pattern scripts/daily_api_refresh.py already uses for the same reason) so
   this late-pipeline add can't reintroduce out-of-footprint noise.

MEASURED 2026-09-23 (docs/full_run_execution_audit_2026-09-23.md, "fannie_
homepath fix -- did it behave as expected?"): before this fix, this module
fetched 8,244 live, currently-for-sale Fannie Mae properties, used them ONLY to
prune 24 stale carryover rows (`reo_freshness.done pruned={'national.
fannie_homepath': 24}`), and discarded the other 8,220 -- leaving the board at
124 fannie_homepath rows, 1.5% of the source's verified-reachable live
inventory. The fetch was never the problem; landing what it fetched was.

Fail-safe by design: a scraper that errors OR returns zero rows is skipped, so a
transient Fannie outage can never mass-delete the whole source, and a source
whose fresh pull we didn't get can never gain "new" rows either. Only sources
with a stable per-property URL belong here — HUD (search-page URLs) and
law-firm/court feeds do NOT, and must never be added.
"""
from __future__ import annotations

import structlog

from .models import Listing, _normalize_addr
from .scrapers._registry import all_scrapers

log = structlog.get_logger(__name__)

# Complete-inventory snapshot feeds with stable per-property URLs. Absence from a
# fresh pull == the property sold / was withdrawn. Keep this list TIGHT.
SNAPSHOT_REO_SOURCES: tuple[str, ...] = ("national.fannie_homepath",)


def _addr_id(li: Listing) -> tuple[str, str, str] | None:
    """Stable (source, normalized_addr, state) identity for matching a fresh
    pull's rows against the board. NOT source_url/case_number — those embed
    Fannie's propertyUuid, which rotates on every pull (module docstring)."""
    addr = _normalize_addr(li.street_address or "")
    if not addr:
        return None
    return (li.source or "", addr, (li.state or "").upper())


async def prune_stale_reo(listings: list[Listing]) -> tuple[list[Listing], dict]:
    """Drop carried-over snapshot-REO leads no longer live, AND land the fresh
    pull's still-live rows onto the board (matched rows refreshed in place, new
    rows appended in-scope). Returns (kept_listings, stats). Never raises on a
    single source failing.
    """
    scrapers = {s.slug: s for s in all_scrapers() if s.slug in SNAPSHOT_REO_SOURCES}
    live_urls: dict[str, set[str]] = {}
    fresh_by_slug: dict[str, list[Listing]] = {}
    fresh_addr_ids: dict[str, set[tuple[str, str, str]]] = {}

    for slug, s in scrapers.items():
        try:
            fresh = list(await s.safe_run())
        except Exception as exc:  # noqa: BLE001
            log.warning("reo_freshness.scrape_failed", slug=slug, error=str(exc)[:150])
            continue
        urls = {(li.source_url or "").strip() for li in fresh if li.source_url}
        if not urls:
            # Empty pull — treat as a transient outage, NOT "everything sold".
            log.warning("reo_freshness.empty_skip", slug=slug,
                        note="fresh pull empty — skipping prune to avoid mass-drop")
            continue
        live_urls[slug] = urls
        fresh_by_slug[slug] = fresh
        fresh_addr_ids[slug] = {aid for li in fresh if (aid := _addr_id(li)) is not None}
        log.info("reo_freshness.live", slug=slug, live=len(urls))

    if not live_urls:
        return listings, {"pruned": 0, "note": "no live inventory fetched; nothing pruned"}

    kept: list[Listing] = []
    pruned: dict[str, int] = {}
    # Address identity -> board row, for every SURVIVING row whose source we have
    # a fresh pull for. Used below to match fresh rows against the board instead
    # of re-adding them as duplicates.
    existing_by_id: dict[tuple[str, str, str], Listing] = {}
    for li in listings:
        slug = li.source or ""
        if slug in live_urls:
            aid = _addr_id(li)
            # "Still live" if EITHER signal says so: the url (works when the
            # uuid happened not to rotate between this pull and the last) OR
            # the address (works when it DID rotate -- the whole reason
            # address matching exists here). Checking the url alone would
            # prune every address-matched row below before the upsert loop
            # ever got a chance to refresh it, since a rotated uuid's OLD url
            # is by definition absent from the fresh live-url set.
            still_live = ((li.source_url or "").strip() in live_urls[slug]
                          or (aid is not None and aid in fresh_addr_ids.get(slug, ())))
            if not still_live:
                pruned[slug] = pruned.get(slug, 0) + 1
                continue
            if aid is not None:
                existing_by_id[aid] = li
        kept.append(li)

    # --- UPSERT: land the fresh pull instead of only using it to decide what
    # to prune. This is the fix for the 1.5%-coverage bug described in the
    # module docstring — the fetch above already succeeded; discarding its
    # rows here was the actual gap, not a missing scraper capability.
    landed = {"matched": 0, "added": 0, "skipped_no_addr": 0, "skipped_out_of_scope": 0}
    _in_scope = None  # lazy-imported once, only if we actually have a candidate
    for slug, fresh in fresh_by_slug.items():
        for fr in fresh:
            aid = _addr_id(fr)
            if aid is None:
                landed["skipped_no_addr"] += 1
                continue
            existing = existing_by_id.get(aid)
            if existing is not None:
                # Same property, possibly-rotated uuid — refresh only the
                # volatile fields. Enrichment (vision/comps/grade/... in .raw)
                # is untouched, mirroring scripts/daily_api_refresh.py's own
                # fresh<->prior match/update for this exact source.
                if fr.source_url:
                    existing.source_url = fr.source_url
                if fr.case_number:
                    existing.case_number = fr.case_number
                if fr.opening_bid is not None:
                    existing.opening_bid = fr.opening_bid
                if fr.last_seen:
                    existing.last_seen = fr.last_seen
                landed["matched"] += 1
                continue
            # No board row for this address — a genuinely new listing the
            # earlier pipeline stages never landed. Gate through the same
            # in-scope check every national.* row goes through in the main
            # scrape phase (imported lazily — see module docstring — avoids a
            # module-level import cycle with .main, which imports THIS module).
            if _in_scope is None:
                from .main import _in_scope as _in_scope_fn
                _in_scope = _in_scope_fn
            if not _in_scope(fr):
                landed["skipped_out_of_scope"] += 1
                continue
            kept.append(fr)
            existing_by_id[aid] = fr
            landed["added"] += 1

    log.info("reo_freshness.done", pruned=pruned, kept=len(kept), landed=landed)
    return kept, {"pruned": sum(pruned.values()), "by_source": pruned, "landed": landed}
