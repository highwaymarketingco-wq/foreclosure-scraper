"""New-this-run detection — the 'early access / geo alert' capability.

Owner ask: be better than ForeclosureHub, whose main selling point is
"geo-based monitoring notifies you about properties before they hit the
general listings." We already scrape the earliest public signal (lis
pendens) for the owner's target counties, so the only missing piece is
flagging what's NEW since last run and surfacing it loudly.

This compares the current run against the prior committed
docs/listings.json by stable dedupe identity (parcel / case / address),
marks each listing raw.is_new + raw.first_seen_run, and returns the set
of new listings (prioritizing fresh lis pendens — the earliest, highest-
value early-access signal). The email + dashboard then highlight them.

Geo is implicit: the pipeline only covers the owner's in-scope counties,
so every "new" listing is already in their territory.
"""
from __future__ import annotations

from datetime import datetime

import structlog

from .carryover import load_prior_listings
from .models import Listing, ListingType

log = structlog.get_logger()


def _prior_keys(prior: list[dict]) -> set[str]:
    """Reconstruct prior listings just enough to compute their dedupe_key."""
    keys: set[str] = set()
    for d in prior:
        try:
            li = Listing.model_validate(d)
            keys.add(li.dedupe_key())
        except Exception:
            continue
    return keys


def mark_new_listings(listings: list[Listing]) -> dict:
    """Tag listings new vs the prior run. Mutates raw.is_new in place.
    Returns stats for the run summary + email."""
    prior, _ = load_prior_listings()
    stamp = datetime.utcnow().isoformat() + "Z"

    if not prior:
        # First-ever run (no prior file): everything is "new", but don't
        # spam — mark them new=False so the first email isn't 100% alerts.
        for li in listings:
            if isinstance(li.raw, dict):
                li.raw["is_new"] = False
        log.info("new_listings.no_prior", count=len(listings))
        return {"new": 0, "prior_total": 0, "is_first_run": True}

    prior_keys = _prior_keys(prior)
    new_count = 0
    new_lp = 0
    for li in listings:
        if not isinstance(li.raw, dict):
            li.raw = {}
        is_new = li.dedupe_key() not in prior_keys
        li.raw["is_new"] = is_new
        if is_new:
            li.raw["first_seen_run"] = stamp
            new_count += 1
            if li.listing_type == ListingType.LIS_PENDENS:
                new_lp += 1

    log.info("new_listings.done", new=new_count, new_lis_pendens=new_lp,
             prior_total=len(prior))
    return {
        "new": new_count,
        "new_lis_pendens": new_lp,   # earliest-signal early-access leads
        "prior_total": len(prior),
        "is_first_run": False,
    }


def top_new_for_alert(listings: list[Listing], limit: int = 25) -> list[Listing]:
    """The new listings most worth an early-access alert: fresh lis pendens
    first (earliest signal), then by soonest sale date."""
    new = [li for li in listings if isinstance(li.raw, dict) and li.raw.get("is_new")]

    def rank(li: Listing):
        lp_first = 0 if li.listing_type == ListingType.LIS_PENDENS else 1
        sale = li.sale_date or datetime.max
        if hasattr(sale, "tzinfo") and sale.tzinfo is not None:
            sale = sale.replace(tzinfo=None)
        return (lp_first, sale)

    return sorted(new, key=rank)[:limit]
