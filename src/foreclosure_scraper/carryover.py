"""Last-known-good carryover for sources that regress to zero.

Anti-bot escalation, scheduled maintenance, sudden 403/429/500 — any of
these can cause a source that produced healthy output last week to
return zero listings this run. The data was real last week and is
almost certainly still on the upstream site this week; only our
fetch failed. Without a backstop, the dashboard goes blank for that
source and downstream systems lose continuity.

Strategy:
  1. Stream the prior run's docs/listings.json one row at a time, counting rows per `source` slug and
     keeping ONLY the rows of sources that could need carryover (a registered scraper that produced 0
     rows this run). It is NEVER loaded whole: the plain file was 4.1 GB / 350,013 rows on 2026-10-08, and
     json.loads(read_text()) of it took the VM from 4 GB to over 25 GB in 70 seconds: two gated full runs were
     killed by the memory watchdog exactly there (the same class of bug new_listings.py fixed on 2026-10-05).
  2. Index the kept rows by `source` slug.
  3. After scraping, identify sources where:
       prior_run had >= MIN_PRIOR listings AND this run has 0
  4. Replay the prior listings into the current pipeline, marked
     `raw.carryover = {from_run, stale: True, reason: ...}`.
  5. Carryover listings flow through filter/dedupe/enrichment normally.
     If their sale_date has aged out of the horizon, _active_only drops
     them — that's correct behavior. If a fresh scrape next week
     supersedes them by parcel/case/url, dedupe wins — also correct.
  6. run_health gets a `carryovers` block so we know which sources
     are being papered over and for how long.

Drift safety:
  * Only carry forward MAX_CARRYOVER_AGE_DAYS (28d default). After
    that, blank is more honest than ancient data.
  * Skip carryover for any source that's already inherently blocked
    (paywall_required, render_required) — its zero is acknowledged,
    not regressed.
  * Skip dateless/event sources that intentionally churn each week
    if the upstream calendar moved on.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import structlog

from .board_parts import iter_plain_rows
from .models import Listing

log = structlog.get_logger()


#: A source must have produced at least this many listings in the prior
# run before we'll consider its zero this run a regression worth papering
# over. One-off matches aren't worth replaying.
MIN_PRIOR_FOR_CARRYOVER = 3

#: Carryover listings older than this many days are dropped — better to
# show blank than month-stale data.
MAX_CARRYOVER_AGE_DAYS = 28


def _docs_dir() -> Path:
    """Project-root /docs (consistent with web_artifact + run_health)."""
    return Path(__file__).resolve().parent.parent.parent / "docs"


def _prior_run_ts(docs: Path) -> datetime | None:
    """run_time of the previous run from docs/run_meta.json (None if missing or unreadable)."""
    meta_path = docs / "run_meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        ts = meta.get("run_time")
        if ts:
            # run_time is ISO-formatted with trailing Z
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception as exc:  # noqa: BLE001
        log.warning("carryover.prior_meta_read_failed", error=str(exc))
    return None


def _stream_prior(listings_path: Path, wanted) -> tuple[dict[str, int], dict[str, list[dict]]]:
    """(rows per source slug in the prior board, the rows of the slugs `wanted(slug)` accepts), read one
    row at a time. Raises on an unreadable file: the caller treats that as 'no prior' (best-effort)."""
    counts: dict[str, int] = {}
    kept: dict[str, list[dict]] = {}
    for d in iter_plain_rows(listings_path):
        if not isinstance(d, dict):
            continue
        slug = (d.get("source") or "").strip()
        if not slug:
            continue
        counts[slug] = counts.get(slug, 0) + 1
        if wanted(slug):
            kept.setdefault(slug, []).append(d)
    return counts, kept


def _too_old(prior_run_ts: datetime | None) -> bool:
    if prior_run_ts is None:
        return False
    age = datetime.now(timezone.utc) - prior_run_ts
    return age > timedelta(days=MAX_CARRYOVER_AGE_DAYS)


def _to_listing(d: dict, *, prior_run_iso: str, reason: str) -> Listing | None:
    """Round-trip a serialized listing dict back into a Listing model.

    Pydantic validation matches what the prior run wrote, so this rarely
    fails. Any failure → skip that one record (drop, don't crash).
    """
    try:
        # Strip computed fields the model doesn't accept on input
        clean = {k: v for k, v in d.items() if not k.startswith("_")}
        # Mark carryover before instantiation so raw is preserved through
        # the pipeline (validation/enrichment don't strip raw.*)
        raw = clean.get("raw") or {}
        if not isinstance(raw, dict):
            raw = {}
        raw = dict(raw)  # don't mutate the loaded dict
        raw["carryover"] = {
            "from_run": prior_run_iso,
            "stale": True,
            "reason": reason,
        }
        clean["raw"] = raw
        return Listing.model_validate(clean)
    except Exception as exc:  # noqa: BLE001
        log.debug("carryover.skip_unparseable", error=str(exc))
        return None


def carryover_for_zeroed_sources(
    *,
    by_source_now: dict[str, int],
    expected_min: dict[str, int],
    skip_slugs: Iterable[str] = (),
    docs_dir: Path | None = None,
) -> tuple[list[Listing], dict[str, int]]:
    """Build replacement listings for sources that regressed to zero.

    Args:
      by_source_now: this run's per-slug listing counts
      expected_min: each scraper's expected_min_count (from registry)
      skip_slugs: don't carry forward for these (paywall/apify/render-blocked)
      docs_dir: override the docs path (for tests)

    Returns:
      (carryover_listings, stats_by_source)
        stats_by_source = {slug: count_carried_over}
    """
    docs = docs_dir or _docs_dir()
    listings_path = docs / "listings.json"
    if not listings_path.exists():
        log.info("carryover.no_prior_run")
        return [], {}

    prior_run_ts = _prior_run_ts(docs)
    if _too_old(prior_run_ts):
        log.info("carryover.prior_too_old", prior_run=str(prior_run_ts))
        return [], {}

    prior_run_iso = prior_run_ts.isoformat() if prior_run_ts else "unknown"
    skip = set(skip_slugs)

    def _could_need_carryover(slug: str) -> bool:
        # the same three gates the loop below applies to a slug, evaluated BEFORE its rows are kept
        return (slug not in skip
                and expected_min.get(slug, 0) > 0     # a source not expected to produce: its zero is normal
                and by_source_now.get(slug, 0) <= 0)  # fresh data this run: nothing to replace

    try:
        prior_counts, kept_rows = _stream_prior(listings_path, _could_need_carryover)
    except Exception as exc:  # noqa: BLE001 - carryover is best-effort, never blocks a run
        log.warning("carryover.prior_listings_read_failed", error=str(exc))
        return [], {}
    if not prior_counts:
        log.info("carryover.no_prior_run")
        return [], {}

    carried: list[Listing] = []
    stats: dict[str, int] = {}

    for slug, prior_listings in kept_rows.items():
        if prior_counts.get(slug, 0) < MIN_PRIOR_FOR_CARRYOVER:
            continue  # too sparse last week to be confident

        reason = f"source produced 0 this run; prior run had {prior_counts[slug]}"
        added = 0
        for d in prior_listings:
            li = _to_listing(d, prior_run_iso=prior_run_iso, reason=reason)
            if li is not None:
                carried.append(li)
                added += 1
        if added:
            stats[slug] = added
            log.warning(
                "carryover.applied",
                source=slug,
                count=added,
                prior_run=prior_run_iso,
                reason=reason,
            )

    return carried, stats
