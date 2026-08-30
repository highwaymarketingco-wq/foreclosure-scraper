"""Cumulative-board persistence for the full pipeline run.

main.run() rebuilds the board from a FRESH scrape (~22k active leads) each run.
write_artifact then REPLACES the published board with only that fresh set, which
has two costs:

  1. COUNT DROP — every persisted lead that wasn't re-scraped this run vanishes.
     That includes the manual ``sc_public_index_export`` lane (~4k leads that can
     NOT be re-scraped) and any source that produced fewer rows this run. The
     fresh set falls below the count-drop guard's 75% floor, the guard fires, and
     run_local.sh skips the publish — the 14h run updates nothing.
  2. RE-ENRICH WASTE — a lead that persists across runs is re-scraped as a fresh
     Listing with NO vision, so the vision pass re-grades it from scratch, burning
     free-tier quota on work already done.

``merge_prior_board`` folds the prior published board into the fresh scrape so the
run is ADDITIVE (same behavior as the scripts/merge_today_sources.py path, but
fresh-wins):

  - matched leads (in BOTH fresh + prior): the FRESH scrape's fields win (new
    sale_date / auction_status / opening_bid), and the prior enrichment
    (vision / images / gis / comps / grade) is carried onto the fresh Listing so
    the idempotent enrichers SKIP them (no re-grade, no re-image).
  - fresh-only leads: pass through untouched, enriched normally downstream.
  - prior-only leads (persisted but NOT re-scraped this run): kept but AGED via
    the SAME ``raw["pulled_sale"]`` consecutive-miss counter the pulled-sales
    enricher already uses. Dropped when terminal (``sold_confirmed`` / court
    sale confirmed / sale past the upset-bid window) OR after N consecutive
    misses (``FULLRUN_PERSIST_MAX_MISSES``, default = pulled-sales retention).

Reuses the existing ``dedupe()`` (so fresh<->prior collapse through the full
parcel/address/case/fuzzy/signature machinery — no double-count) and the existing
``pulled_sale`` aging field — no parallel mechanism is invented.
"""
from __future__ import annotations

import os
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import structlog

from .dedupe import dedupe
from .enrichment_pulled_sales import PULLED_RETENTION_WEEKS
from .models import Listing
from .web_artifact import load_board

log = structlog.get_logger()


# A prior-only lead whose foreclosure sale is this many days past is treated as
# terminal (the auction happened, the NC 10-day upset-bid window has closed) and
# dropped so the board doesn't accumulate dead post-sale rows.
TERMINAL_SALE_GRACE_DAYS = int(
    os.environ.get("FULLRUN_PERSIST_TERMINAL_GRACE_DAYS", "365")
)

# Sentinels stamped onto raw so the post-dedupe pass can tell, per merged row,
# whether a FRESH copy and/or a PRIOR copy contributed. Both are popped before
# the rows are returned so they never reach the published artifact.
_SEEN_FLAG = "_seen_this_run"   # set on every fresh-scrape lead
_PRIOR_FLAG = "_from_prior_board"  # set on every prior-board lead


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Drop tzinfo so prior-board (often tz-aware ISO) dates compare against a
    naive utcnow() without raising."""
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.replace(tzinfo=None)
    return dt


def _is_terminal(li: Listing, now: datetime) -> bool:
    """A prior-only lead that is no longer actionable and should be dropped
    outright (not aged): a confirmed sale, or a sale date past the upset-bid
    window."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    if raw.get("sold_confirmed"):
        return True
    if raw.get("court_sale_status") == "confirmed":
        return True
    dl = _naive(li.upset_bid_deadline)
    if dl is not None and dl < now:
        return True
    sd = _naive(li.sale_date)
    if sd is not None and sd < now - timedelta(days=TERMINAL_SALE_GRACE_DAYS):
        return True
    return False


def merge_prior_board(
    fresh_deduped: list[Listing],
    docs_dir: Path | str | None = None,
    now: Optional[datetime] = None,
    max_misses: Optional[int] = None,
) -> tuple[list[Listing], dict]:
    """Merge the prior published board into this run's fresh (deduped) scrape.

    Returns ``(merged_listings, stats)``. On an empty/missing prior board (the
    first-ever run) the fresh set is returned unchanged. On dedupe failure, this
    function re-raises — the caller must treat merge_prior_board as a critical
    phase: falling back to fresh-only silently drops 72% of the board.
    """
    if now is None:
        now = datetime.utcnow()
    if max_misses is None:
        max_misses = int(
            os.environ.get("FULLRUN_PERSIST_MAX_MISSES", str(PULLED_RETENTION_WEEKS))
        )
    if docs_dir is None:
        docs_dir = Path(__file__).resolve().parent.parent.parent / "docs"

    stats: dict = {
        "fresh_count": len(fresh_deduped),
        "prior_count": 0,
        "merged_count": 0,
        "matched": 0,
        "fresh_only": 0,
        "prior_only_kept": 0,
        "aged_out_terminal": 0,
        "aged_out_misses": 0,
        "carried_vision": 0,
    }

    try:
        prior = load_board(docs_dir)
    except FileNotFoundError:
        # No published board yet (first-ever run) — nothing to persist.
        prior = []
    stats["prior_count"] = len(prior)
    if not prior:
        # First run / no board yet — nothing to persist, ship fresh as-is.
        stats["merged_count"] = len(fresh_deduped)
        stats["fresh_only"] = len(fresh_deduped)
        return list(fresh_deduped), stats

    # Stamp provenance sentinels. Fresh leads get _SEEN_FLAG; prior leads get
    # _PRIOR_FLAG. After dedupe a merged row carries whichever of the two its
    # constituents had (deep-merged raw keeps both), which tells us matched vs
    # fresh-only vs prior-only.
    for li in fresh_deduped:
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw[_SEEN_FLAG] = True
    for li in prior:
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw[_PRIOR_FLAG] = True

    # Fresh FIRST so dedupe uses the fresh copy as the merge base: Listing.merge
    # keeps the base's (fresh) non-null fields and only backfills from the prior
    # copy where fresh is missing a value — fresh scrape wins, prior enrichment
    # is carried.
    combined = list(fresh_deduped) + list(prior)
    try:
        merged = dedupe(combined)
    except Exception:
        log.critical("board_persist.dedupe_failed", traceback=traceback.format_exc())
        # CRITICAL: do not fall back to fresh-only. Returning 22k instead of
        # 94k silently drops 72k records and the pipeline publishes it as the
        # full board (exit 0). Re-raise so the caller halts.
        raise

    kept: list[Listing] = []
    for li in merged:
        raw = li.raw if isinstance(li.raw, dict) else {}
        seen = bool(raw.pop(_SEEN_FLAG, False))
        from_prior = bool(raw.pop(_PRIOR_FLAG, False))

        if seen:
            # Re-scraped this run (fresh, possibly carrying prior enrichment).
            if from_prior:
                stats["matched"] += 1
                if raw.get("vision"):
                    stats["carried_vision"] += 1
                # A reappeared lead is active again — clear any stale pulled_sale
                # miss counter + presumed-withdrawn tag it accumulated while gone.
                if raw.get("pulled_sale"):
                    raw.pop("pulled_sale", None)
                    if li.auction_status == "presumed_withdrawn":
                        li.auction_status = None
            else:
                stats["fresh_only"] += 1
            li.raw = raw
            kept.append(li)
            continue

        # Not seen this run => prior-only (persisted but not re-scraped) => AGE.
        if _is_terminal(li, now):
            stats["aged_out_terminal"] += 1
            continue
        prev_pulled = raw.get("pulled_sale") or {}
        consecutive = prev_pulled.get("consecutive_misses", 0) + 1
        if consecutive > max_misses:
            stats["aged_out_misses"] += 1
            continue
        raw["pulled_sale"] = {
            "first_missed_at": prev_pulled.get(
                "first_missed_at", now.isoformat() + "Z"
            ),
            "consecutive_misses": consecutive,
            "presumed_withdrawn": True,
            "last_seen_source": li.source,
            "last_seen_sale_date": (
                li.sale_date.isoformat() if li.sale_date else None
            ),
        }
        if not li.auction_status:
            li.auction_status = "presumed_withdrawn"
        li.raw = raw
        kept.append(li)
        stats["prior_only_kept"] += 1

    stats["merged_count"] = len(kept)
    log.info("board_persist.done", **stats)
    return kept, stats
