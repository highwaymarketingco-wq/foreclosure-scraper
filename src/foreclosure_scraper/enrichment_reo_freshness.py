"""Snapshot-REO freshness pruner.

Fannie Mae HomePath publishes its COMPLETE current REO inventory on every run.
When a property SELLS it drops out of the feed — but because the merge/regenerate
carry leads over from the persisted dashboard, the sold listing lingers. Its
per-property SPA URL (``/property/{uuid}``) then renders a *client-side* 404 in
the browser once the uuid leaves inventory (the HTTP status is still 200 — only
the JS app knows it's gone), so the operator clicks a dead link.

This module re-runs the snapshot scrapers, builds the set of still-live
per-property URLs, and drops any carried-over lead whose URL is no longer live.

Fail-safe by design: a scraper that errors OR returns zero rows is skipped, so a
transient Fannie outage can never mass-delete the whole source. Only sources with
a stable per-property URL belong here — HUD (search-page URLs) and law-firm/court
feeds do NOT, and must never be added.
"""
from __future__ import annotations

import structlog

from .models import Listing
from .scrapers._registry import all_scrapers

log = structlog.get_logger(__name__)

# Complete-inventory snapshot feeds with stable per-property URLs. Absence from a
# fresh pull == the property sold / was withdrawn. Keep this list TIGHT.
SNAPSHOT_REO_SOURCES: tuple[str, ...] = ("national.fannie_homepath",)


async def prune_stale_reo(listings: list[Listing]) -> tuple[list[Listing], dict]:
    """Drop carried-over snapshot-REO leads no longer in the live inventory.

    Returns (kept_listings, stats). Never raises on a single source failing.
    """
    scrapers = {s.slug: s for s in all_scrapers() if s.slug in SNAPSHOT_REO_SOURCES}
    live_urls: dict[str, set[str]] = {}

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
        log.info("reo_freshness.live", slug=slug, live=len(urls))

    if not live_urls:
        return listings, {"pruned": 0, "note": "no live inventory fetched; nothing pruned"}

    kept: list[Listing] = []
    pruned: dict[str, int] = {}
    for li in listings:
        slug = li.source or ""
        if slug in live_urls and (li.source_url or "").strip() not in live_urls[slug]:
            pruned[slug] = pruned.get(slug, 0) + 1
            continue
        kept.append(li)

    log.info("reo_freshness.done", pruned=pruned, kept=len(kept))
    return kept, {"pruned": sum(pruned.values()), "by_source": pruned}
