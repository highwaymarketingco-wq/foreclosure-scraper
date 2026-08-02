"""Tag listings inside the NC upset-bid window per NCGS §45-21.27.

NC upset-bid mechanics:
  * §45-21.26: trustee must file the report of sale with the clerk
    within FIVE days after the sale.
  * §45-21.27: any person may file an upset bid within TEN days after
    the report of sale is filed (5% minimum increase, $750 min raise).

In practice we only know the sale_date, not the report-of-sale filing
date. The conservative operational model that NC foreclosure investors
use is **14 calendar days from sale_date** (assumes ~4 days for the
report to be filed, leaving 10 days from filing). Some sales — where
the trustee files the report same-day — have a tighter 10-11 day
window from sale; some — where the report is filed late — have up to
15. 14 is the standard honest estimate when you only know sale_date.

This is one of the highest-leverage foreclosure plays — the property
is already under court oversight, the sale price is public, and the
prior bidder's deposit is at risk.

Where the signal comes from in our existing data:
  * Law-firm trustee scrapers (Hutchens, Brock Scott, Bell Carrington,
    Finkel) publish upcoming sale calendars and keep listings live
    for 1-2 days post-sale before removing them
  * County tax-foreclosure scrapers (Forsyth, Mecklenburg, Wake, etc.)
    surface sale_date for their court calendar
  * National auction sites (auction.com, bid4assets) tag sale dates
    when they sync NC properties

What this enrichment does:
  1. For every NC listing with sale_date in the past 0-10 calendar days
     (inclusive), attach raw.upset_bid = {in_window, deadline_iso,
     days_remaining, sale_occurred_on_iso, statute, source_signal}
  2. Set li.upset_bid_deadline = sale_date + 10 days

What this enrichment does NOT do:
  * It does NOT touch a listing whose raw.upset_bid was PUBLISHED by the
    source (raw.upset_bid["source"] == "published" — set by
    scrapers.national.nc_upset_bids from a clerk/county/firm feed that
    prints the actual close date). Every successful upset restarts a
    fresh 10-day clock, so a published close date legitimately sits weeks
    past the sale date; the sale_date+10 rule below would judge those
    "outside the window" and null out a real, still-open deadline.
  * It does NOT cause listings to survive the active-only filter on
    its own — that's main._active_only's job (state-aware past cutoff).
  * It does NOT scrape clerk-of-court "Notice of Sale" / "Report of
    Sale" filings — those would be a future per-county effort.
  * It does NOT verify the sale actually happened (trustees occasionally
    leave sold listings up; occasionally postpone sales without updating).
    raw.upset_bid.confidence reflects that ambiguity.

Pure-Python, no I/O, idempotent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from .models import Listing

log = structlog.get_logger()


# NCGS §45-21.27 strict reading: 10 days from filing of report of sale.
# Combined with §45-21.26's 5-day filing deadline, the practical window
# from the actual sale date is up to 15 days. We use 14 as the operational
# threshold investors typically work with.
UPSET_BID_WINDOW_DAYS = 14


def _naive_utc(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d.replace(tzinfo=None) if d.tzinfo else d


def _confidence_for(li: Listing) -> str:
    """How sure are we this listing represents an actual recent sale?

    HIGH: source is a law-firm trustee scraper or county Master-in-Equity
          (these are the parties who actually conduct the sale)
    MEDIUM: source is a county tax-foreclosure or NC eCourts (sale_date
            comes from court calendar, may be scheduled rather than
            executed)
    LOW: anything else
    """
    src = (li.source or "").lower()
    if "law_firms" in src or "master_in_equity" in src or "courtrosters" in src:
        return "HIGH"
    if "county" in src or "ecourts" in src or "tax" in src:
        return "MEDIUM"
    return "LOW"


def enrich_upset_bid(listings: list[Listing]) -> dict[str, Any]:
    """Tag NC listings inside the 10-day upset-bid window. Idempotent.

    Returns stats dict for the run summary. Existing listings whose
    raw.upset_bid is already set (from the NC eCourts scraper's per-
    listing tagging) are re-evaluated — if their sale_date is now
    outside the window, we clear the flag.
    """
    stats = {
        "scanned": 0,
        "tagged_in_window": 0,
        "tag_cleared_outside_window": 0,
        "no_sale_date": 0,
        "non_nc": 0,
        "published_skipped": 0,
    }
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for li in listings:
        stats["scanned"] += 1
        if li.state != "NC":
            stats["non_nc"] += 1
            continue
        # A source that PRINTS the close date beats a date we derive. Stacked
        # upsets restart the 10-day clock, so the published deadline routinely
        # sits outside sale_date+10 and the derived rule would delete it.
        existing_raw = li.raw.get("upset_bid") if isinstance(li.raw, dict) else None
        if isinstance(existing_raw, dict) and existing_raw.get("source") == "published":
            stats["published_skipped"] += 1
            continue
        sd = _naive_utc(li.sale_date)
        if sd is None:
            stats["no_sale_date"] += 1
            continue

        days_since_sale = (now - sd).days
        in_window = 0 <= days_since_sale <= UPSET_BID_WINDOW_DAYS

        if not isinstance(li.raw, dict):
            li.raw = {}

        if in_window:
            deadline = sd + timedelta(days=UPSET_BID_WINDOW_DAYS)
            li.upset_bid_deadline = deadline
            li.raw["upset_bid"] = {
                "in_window": True,
                "window_days": UPSET_BID_WINDOW_DAYS,
                "deadline_iso": deadline.isoformat(),
                "days_remaining": max(0, UPSET_BID_WINDOW_DAYS - days_since_sale),
                "days_since_sale": days_since_sale,
                "sale_occurred_on_iso": sd.isoformat(),
                "statute": "NCGS §45-21.27",
                "confidence": _confidence_for(li),
                "source_signal": li.source,
            }
            stats["tagged_in_window"] += 1
        else:
            # Clear stale upset-bid flags — important when a listing's
            # sale_date moves (postponed/rescheduled) or this enrichment
            # runs on data scraped earlier that the NC eCourts scraper
            # had falsely tagged based on judgment date.
            existing = li.raw.get("upset_bid")
            if isinstance(existing, dict) and existing.get("in_window"):
                li.raw["upset_bid"] = {
                    **existing,
                    "in_window": False,
                    "days_remaining": 0,
                    "days_since_sale": days_since_sale,
                    "stale_reason": (
                        "outside 10-day window now"
                        if days_since_sale > UPSET_BID_WINDOW_DAYS
                        else "sale not yet"
                    ),
                }
                if days_since_sale > UPSET_BID_WINDOW_DAYS:
                    li.upset_bid_deadline = None
                stats["tag_cleared_outside_window"] += 1

    log.info("upset_bid.done", **stats)
    return stats
