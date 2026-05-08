"""NC foreclosure case-status enrichment — heuristic-based.

Replaces the broken Tyler Odyssey portal scraper (commit 27d1bdd attempted
to navigate from /Portal/ to bypass a 405; runs #1 + #2 confirmed AWS WAF
on portal-nc.tylertech.cloud is presenting a CAPTCHA challenge to all
non-browser requests, including Scrapling/Playwright stealth, with
`x-amzn-waf-action: captcha` in the response headers).

All 100 NC counties share that single Tyler portal — there's no per-county
alternative court website. But we don't actually need Tyler:

  1. **Sale-date heuristic** — NCGS §45-21.27 says the upset-bid window
     runs 10 days from the sale; allowing 1-3 days for clerk filing,
     14 days is the conservative cutoff. Pure date math, no network.

  2. **Trustee's Deed cross-reference** — when a Trustee's Deed Upon Sale
     is recorded in the ROD for a foreclosure (already captured by
     scrapers/counties_nc/nc_rod_substitute_trustee.py), that IS the
     legal confirmation. Deed-delivered = sale confirmed.

Tags listing.raw["nc_case_status"] = {
    "status": "scheduled" | "upset_bid" | "pending_confirmation" | "confirmed",
    "in_upset_bid_window": bool,
    "upset_bid_deadline": ISO date or None,
    "method": "sale_date_heuristic" | "trustee_deed_match",
    "checked_at": ISO timestamp,
}
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import structlog

from .models import Listing, ListingType

log = structlog.get_logger()


# NCGS §45-21.27: 10-day statutory upset-bid window. Adding 4 days of
# clerk-filing slack means listings within 14 days of sale_date are still
# treated as in-window (could yet be upset by a higher bidder).
UPSET_BID_DAYS = 14


def _to_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if hasattr(dt, "tzinfo") and dt.tzinfo:
        return dt.replace(tzinfo=None)
    return dt


def _status_from_sale_date(sale_date: Optional[datetime], now: datetime) -> Optional[dict]:
    """Pure-function status inference from sale_date alone. Returns None
    if sale_date is unknown."""
    if not sale_date:
        return None
    sale_date = _to_naive(sale_date)
    days_diff = (now - sale_date).days

    if days_diff < 0:
        # Sale hasn't happened yet
        return {
            "status": "scheduled",
            "in_upset_bid_window": False,
            "upset_bid_deadline": None,
            "days_since_sale": days_diff,
            "method": "sale_date_heuristic",
        }

    deadline = sale_date + timedelta(days=UPSET_BID_DAYS)

    if days_diff <= UPSET_BID_DAYS:
        return {
            "status": "upset_bid",
            "in_upset_bid_window": True,
            "upset_bid_deadline": deadline.date().isoformat(),
            "days_since_sale": days_diff,
            "method": "sale_date_heuristic",
        }

    if days_diff <= 30:
        return {
            "status": "pending_confirmation",
            "in_upset_bid_window": False,
            "upset_bid_deadline": deadline.date().isoformat(),
            "days_since_sale": days_diff,
            "method": "sale_date_heuristic",
        }

    return {
        "status": "confirmed",
        "in_upset_bid_window": False,
        "upset_bid_deadline": deadline.date().isoformat(),
        "days_since_sale": days_diff,
        "method": "sale_date_heuristic",
    }


def _norm_addr_key(li: Listing) -> Optional[str]:
    """Cheap key for cross-referencing active listing against post-sale
    ROD recording. street + zip is good enough for same-jurisdiction
    matches — fancy fuzzy-match would be overkill here."""
    if not li.street_address:
        return None
    s = li.street_address.upper().strip()
    z = (li.zip_code or "").strip()[:5]
    if not z:
        return None
    return f"{s}|{z}"


def _build_trustee_deed_index(sold_pool: list[Listing]) -> dict[str, Listing]:
    """Index post-sale ROD recordings (Trustee's Deed Upon Sale) by
    address+zip for O(1) cross-reference against active listings."""
    idx: dict[str, Listing] = {}
    for li in sold_pool:
        # Only deeds we sourced from the post-sale ROD sweep — these are
        # the ones with raw.actual_sold_price already populated.
        if li.state != "NC":
            continue
        if not (isinstance(li.raw, dict) and li.raw.get("actual_sold_price")):
            continue
        key = _norm_addr_key(li)
        if not key:
            continue
        # Keep most-recent recording when duplicates exist
        existing = idx.get(key)
        if existing and existing.sale_date and li.sale_date:
            if _to_naive(existing.sale_date) > _to_naive(li.sale_date):
                continue
        idx[key] = li
    return idx


def enrich_with_nc_case_status(
    listings: list[Listing],
    sold_pool: Optional[list[Listing]] = None,
) -> None:
    """For NC foreclosure listings, infer current case status from
    sale_date + cross-reference against the post-sale ROD pool.

    Synchronous, network-free, deterministic. Replaces the previous Tyler
    Odyssey portal scraper which AWS WAF blocked (see module docstring).

    sold_pool is optional; when provided, listings with a recorded
    Trustee's Deed at the same address are tagged status='confirmed' with
    method='trustee_deed_match' (overrides the pure-date heuristic).
    """
    targets = [
        li
        for li in listings
        if li.state == "NC"
        and li.listing_type
        in (ListingType.FORECLOSURE_SALE, ListingType.LIS_PENDENS, ListingType.SHERIFF_SALE)
        and li.source not in ("national.courtlistener_bankruptcy",)
    ]

    if not targets:
        log.info("nc_case_status.no_targets")
        return

    deed_index = _build_trustee_deed_index(sold_pool or [])
    now = datetime.utcnow()
    counts = {
        "scanned": 0,
        "tagged": 0,
        "in_upset_bid": 0,
        "trustee_deed_matched": 0,
        "no_sale_date": 0,
    }
    log.info(
        "nc_case_status.start",
        target_count=len(targets),
        trustee_deed_index_size=len(deed_index),
    )

    for li in targets:
        counts["scanned"] += 1

        # Path 1: cross-reference against recorded Trustee's Deeds (highest
        # confidence — deed-recorded means the sale was legally confirmed)
        info: Optional[dict] = None
        key = _norm_addr_key(li)
        if key and key in deed_index:
            deed = deed_index[key]
            info = {
                "status": "confirmed",
                "in_upset_bid_window": False,
                "upset_bid_deadline": None,
                "method": "trustee_deed_match",
                "trustee_deed_sale_date": _to_naive(deed.sale_date).date().isoformat() if deed.sale_date else None,
                "trustee_deed_price": (deed.raw or {}).get("actual_sold_price"),
            }
            counts["trustee_deed_matched"] += 1

        # Path 2: pure sale_date heuristic
        if info is None:
            info = _status_from_sale_date(li.sale_date, now)
            if info is None:
                counts["no_sale_date"] += 1
                continue

        info["checked_at"] = now.isoformat() + "Z"

        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["nc_case_status"] = info
        counts["tagged"] += 1
        if info.get("in_upset_bid_window"):
            counts["in_upset_bid"] += 1

    log.info("nc_case_status.done", **counts)


# Backwards-compat shim: legacy callers pass concurrency=, max_check=
# kwargs from when this was async + Tyler-driven. New impl ignores them.
async def enrich_with_nc_case_status_legacy_async(
    listings: list[Listing],
    concurrency: int = 2,
    max_check: int = 100,
    sold_pool: Optional[list[Listing]] = None,
) -> None:
    """Async wrapper kept for orchestrator compatibility — internal logic
    is now synchronous heuristic compute."""
    enrich_with_nc_case_status(listings, sold_pool=sold_pool)
