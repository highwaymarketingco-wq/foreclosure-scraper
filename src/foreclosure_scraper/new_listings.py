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

from . import carryover
from .board_parts import iter_plain_rows
from .models import Listing, ListingType

log = structlog.get_logger()


def _prior_keys(prior) -> set[str]:
    """Reconstruct prior listings just enough to compute their dedupe_key.
    `prior` may be any iterable of row dicts; it is consumed once."""
    keys: set[str] = set()
    for d in prior:
        try:
            li = Listing.model_validate(d)
            keys.add(li.dedupe_key())
        except Exception:
            continue
    return keys


def _prior_keys_streamed(docs_dir=None) -> tuple[set[str], int]:
    """(dedupe keys, row count) of the prior docs/listings.json, streamed one row at a time.

    Same source and same keys as the old `_prior_keys(load_prior_listings()[0])`, without ever
    holding the board: that call did json.loads(path.read_text()) of the full plain file (2.5 GB
    on 2026-10-05) -- its text and every parsed row alive together -- on top of ~270K live
    Listings, and the VM run that day was OOM-killed about a minute after the step before this
    one. A missing or unreadable file is "no prior", exactly as before (load_prior_listings
    returned [] for both)."""
    path = (docs_dir or carryover._docs_dir()) / "listings.json"
    if not path.exists():
        return set(), 0
    count = 0

    def _rows():
        nonlocal count
        for d in iter_plain_rows(path):
            count += 1
            yield d

    try:
        keys = _prior_keys(_rows())
    except Exception as exc:  # noqa: BLE001 - same contract as load_prior_listings
        log.warning("carryover.prior_listings_read_failed", error=str(exc))
        return set(), 0
    return keys, count


def mark_new_listings(listings: list[Listing]) -> dict:
    """Tag listings new vs the prior run. Mutates raw.is_new in place.
    Returns stats for the run summary + email."""
    prior_keys, prior_total = _prior_keys_streamed()
    stamp = datetime.utcnow().isoformat() + "Z"

    if not prior_total:
        # First-ever run (no prior file): everything is "new", but don't
        # spam — mark them new=False so the first email isn't 100% alerts.
        for li in listings:
            if isinstance(li.raw, dict):
                li.raw["is_new"] = False
        log.info("new_listings.no_prior", count=len(listings))
        return {"new": 0, "prior_total": 0, "is_first_run": True}

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
             prior_total=prior_total)
    return {
        "new": new_count,
        "new_lis_pendens": new_lp,   # earliest-signal early-access leads
        "prior_total": prior_total,
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
