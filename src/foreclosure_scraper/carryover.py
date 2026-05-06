"""Last-known-good carryover for sources that regress to zero.

Anti-bot escalation, scheduled maintenance, sudden 403/429/500 — any of
these can cause a source that produced healthy output last week to
return zero listings this run. The data was real last week and is
almost certainly still on the upstream site this week; only our
fetch failed. Without a backstop, the dashboard goes blank for that
source and downstream systems lose continuity.

Strategy:
  1. Before scraping, load the prior week's docs/listings.json.
  2. Index it by `source` slug.
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


def load_prior_listings(docs_dir: Path | None = None) -> tuple[list[dict], datetime | None]:
    """Read the previous week's docs/listings.json + run_meta.json.

    Returns ([], None) if either is missing or malformed — carryover
    is best-effort, never blocks a run.
    """
    docs = docs_dir or _docs_dir()
    listings_path = docs / "listings.json"
    meta_path = docs / "run_meta.json"
    if not listings_path.exists():
        return [], None
    try:
        prior = json.loads(listings_path.read_text(encoding="utf-8"))
        if not isinstance(prior, list):
            return [], None
    except Exception as exc:  # noqa: BLE001
        log.warning("carryover.prior_listings_read_failed", error=str(exc))
        return [], None

    prior_run_ts: datetime | None = None
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ts = meta.get("run_time")
            if ts:
                # run_time is ISO-formatted with trailing Z
                prior_run_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception as exc:  # noqa: BLE001
            log.warning("carryover.prior_meta_read_failed", error=str(exc))

    return prior, prior_run_ts


def _index_by_source(prior: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in prior:
        slug = (d.get("source") or "").strip()
        if not slug:
            continue
        out.setdefault(slug, []).append(d)
    return out


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
    prior, prior_run_ts = load_prior_listings(docs_dir)
    if not prior:
        log.info("carryover.no_prior_run")
        return [], {}

    if _too_old(prior_run_ts):
        log.info("carryover.prior_too_old", prior_run=str(prior_run_ts))
        return [], {}

    prior_run_iso = prior_run_ts.isoformat() if prior_run_ts else "unknown"
    by_source_prior = _index_by_source(prior)
    skip = set(skip_slugs)

    carried: list[Listing] = []
    stats: dict[str, int] = {}

    for slug, prior_listings in by_source_prior.items():
        if slug in skip:
            continue
        if expected_min.get(slug, 0) <= 0:
            # Source isn't expected to produce — its zero is normal,
            # not a regression. Don't carry forward.
            continue
        if by_source_now.get(slug, 0) > 0:
            continue  # source produced fresh data, no carryover needed
        if len(prior_listings) < MIN_PRIOR_FOR_CARRYOVER:
            continue  # too sparse last week to be confident

        reason = f"source produced 0 this run; prior run had {len(prior_listings)}"
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
