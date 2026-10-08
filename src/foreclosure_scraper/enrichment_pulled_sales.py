"""Track listings that disappear between runs (presumed-withdrawn sales).

NC + SC trustees PULL roughly half of all foreclosure sales before they
go to auction — homeowner pays off, files BK 13, refinances, settles
with lender, sale gets postponed, etc. Pre-fix, when a listing
disappeared from a law-firm's roster between runs, our pipeline
silently dropped it from the dashboard. Investors lose visibility:
  - Did the property actually sell? (need to monitor for new buyer)
  - Was it withdrawn? (no longer actionable)
  - Was it postponed? (will reappear with new sale_date)

This module flags those by cross-referencing current-run listings
against the prior week's docs/listings.json. Any previously-seen
listing not in the current run gets tagged with raw['pulled_sale'].
After PULLED_RETENTION_WEEKS without reappearing, the listing drops
entirely (otherwise the dashboard would grow indefinitely with stale
data).

Output dict shape on each tagged listing:
  raw["pulled_sale"] = {
      "first_missed_at": ISO timestamp of first miss,
      "consecutive_misses": int,
      "presumed_withdrawn": True | False,  # True after 1+ misses
      "last_seen_source": "law_firms.brock_scott",
      "last_seen_sale_date": ISO date or None,
  }
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

from .models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


# Keep "pulled" listings on the dashboard for up to 4 weekly runs (~1
# month) before pruning. Gives time for postponed-then-resumed sales
# to reappear, plus investor lookback for "what got pulled lately".
PULLED_RETENTION_WEEKS = 4


# ListingType / PropertyKind enum string-value maps for hydration.
_LT_MAP = {lt.value: lt for lt in ListingType}
_PK_MAP = {pk.value: pk for pk in PropertyKind}


def _hydrate_listing(d: dict) -> Optional[Listing]:
    """Re-build a Listing from a docs/listings.json dict (ISO date strings,
    enum string values, slim raw payload). Returns None on failure."""
    d = dict(d)
    for k in ("first_seen", "last_seen", "sale_date", "upset_bid_deadline"):
        v = d.get(k)
        if isinstance(v, str):
            try:
                d[k] = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                d[k] = None
    d["listing_type"] = _LT_MAP.get(d.get("listing_type") or "unknown", ListingType.UNKNOWN)
    d["property_kind"] = _PK_MAP.get(d.get("property_kind") or "unknown", PropertyKind.UNKNOWN)
    valid_fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    try:
        return Listing(**valid_fields)
    except Exception:
        return None


def _load_previous(path: Path) -> list[Listing]:
    """Load the prior run's listings from docs/listings.json. Returns
    empty list if file missing/corrupt — first-ever run has nothing
    to compare against."""
    if not path.exists():
        return []
    # Streamed one row at a time (audit 2026-10-09, pipeline_gate): json.loads(path.read_text())
    # held the file's whole decoded text AND its parsed list of dicts at once -- on the VM that
    # file is the 4.1 GB plain board, the same pattern that had the watchdog kill two full runs in
    # carryover on 2026-10-07/08. main.run() reaches this whenever merge_prior_board did not run
    # (FULLRUN_PERSIST=0, or no prior board found). Same contract: a corrupt or non-array file
    # gives [] (nothing to compare against), never a partial list.
    out: list[Listing] = []
    try:
        for d in _iter_array_strict(path):
            if not isinstance(d, dict):
                continue
            li = _hydrate_listing(d)
            if li:
                out.append(li)
    except (ValueError, UnicodeDecodeError, OSError):
        return []
    return out


_CHUNK = 1 << 20
_MAX_ELEMENT = 256 << 20


def _iter_array_strict(path: Path):
    """The elements of one plain JSON array file, one at a time, holding one 1 MB chunk plus one
    element. Unlike board_parts._iter_array (which stops quietly at undecodable text), anything
    that is not a complete JSON array raises ValueError, so the caller can keep its
    all-or-nothing contract."""
    dec = json.JSONDecoder()
    with open(path, "rt", encoding="utf-8") as fh:
        buf = fh.read(_CHUNK).lstrip()
        if not buf.startswith("["):
            raise ValueError("not a JSON array")
        i, closed = 1, False
        while True:
            while True:
                while i < len(buf) and buf[i] in " \n\r\t,":
                    i += 1
                if i < len(buf) and buf[i] == "]":
                    closed = True
                    i += 1
                    break
                if i >= len(buf):
                    break
                try:
                    obj, j = dec.raw_decode(buf, i)
                except ValueError:
                    break                      # the element continues in the next chunk
                yield obj
                i = j
            buf = buf[i:]
            i = 0
            chunk = fh.read(_CHUNK)
            if closed:
                if (buf + chunk).strip():
                    raise ValueError("text after the closing bracket")
                return
            if not chunk:
                raise ValueError("JSON array is truncated or malformed")
            if len(buf) > _MAX_ELEMENT:
                raise ValueError("an element larger than any board row: malformed")
            buf += chunk


def enrich_with_pulled_sales(
    current: list[Listing],
    previous_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> tuple[list[Listing], dict]:
    """Detect previously-seen listings missing from the current run.
    Returns (augmented_listings, stats).

    Listings missing for >= PULLED_RETENTION_WEEKS consecutive runs are
    dropped from the output (their data is preserved in the prior
    listings.json snapshot but they no longer appear on the dashboard).
    """
    if now is None:
        now = datetime.utcnow()
    if previous_path is None:
        previous_path = Path("docs/listings.json")

    stats = {
        "previous_count": 0,
        "current_count": len(current),
        "tagged_new_misses": 0,
        "tagged_repeat_misses": 0,
        "dropped_past_retention": 0,
        "kept_as_pulled": 0,
    }

    previous = _load_previous(previous_path)
    stats["previous_count"] = len(previous)
    if not previous:
        return current, stats

    # Build dedup-key index of current listings
    current_keys = {li.dedupe_key() for li in current}

    # For each previous listing not in current, decide:
    #   - first miss this run: tag presumed_withdrawn=True, consecutive_misses=1
    #   - subsequent miss: increment consecutive_misses
    #   - past retention: drop entirely
    augmented = list(current)
    augmented_keys = set(current_keys)

    for prev in previous:
        pkey = prev.dedupe_key()
        if pkey in current_keys:
            continue  # Still present this run — already in `current`

        # Was this listing already marked as pulled in the previous run?
        prev_raw = prev.raw if isinstance(prev.raw, dict) else {}
        prev_pulled = prev_raw.get("pulled_sale") or {}
        consecutive = prev_pulled.get("consecutive_misses", 0) + 1

        if consecutive > PULLED_RETENTION_WEEKS:
            stats["dropped_past_retention"] += 1
            continue

        # Tag as pulled, preserve on dashboard
        if not isinstance(prev.raw, dict):
            prev.raw = {}
        prev.raw["pulled_sale"] = {
            "first_missed_at": prev_pulled.get(
                "first_missed_at", now.isoformat() + "Z"
            ),
            "consecutive_misses": consecutive,
            "presumed_withdrawn": True,
            "last_seen_source": prev.source,
            "last_seen_sale_date": (
                prev.sale_date.isoformat() if prev.sale_date else None
            ),
        }
        # Also flip auction_status so the dashboard's existing filters
        # treat this as withdrawn.
        if not prev.auction_status:
            prev.auction_status = "presumed_withdrawn"

        if consecutive == 1:
            stats["tagged_new_misses"] += 1
        else:
            stats["tagged_repeat_misses"] += 1

        # Dedup safety: don't double-add if somehow already there
        if pkey in augmented_keys:
            continue
        augmented_keys.add(pkey)
        augmented.append(prev)
        stats["kept_as_pulled"] += 1

    log.info("pulled_sales.done", **stats)
    return augmented, stats
