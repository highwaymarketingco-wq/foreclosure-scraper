"""Zombie Properties Detector — derived distress signal.

A "zombie property" is a property where a lis pendens (pre-foreclosure
filing) was recorded more than 12 months ago but never progressed to
a foreclosure sale, tax sale, sheriff sale, or auction.  These are
stalled foreclosures — the lender may have walked away, the owner may
be in limbo, or the case may be stuck in legal proceedings.

This is NOT a web scraper.  It loads the board database, cross-references
lis pendens listings against sale-type listings, and yields zombie
properties as DISTRESSED leads.

Logic:
1. Load board with load_board().
2. Group all listings by dedupe_key.
3. Find groups where:
   a. At least one listing has listing_type == "lis_pendens"
   b. The lis pendens first_seen is >12 months old
   c. NO listing in the group has listing_type in
      (FORECLOSURE_SALE, TAX_SALE, SHERIFF_SALE, AUCTION)
4. Yield those as DISTRESSED with a "zombie_property" flag in raw.

Slug: counties_sc.zombie_properties
Category: derived
ListingType: DISTRESSED
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# Sale types that indicate a lis pendens has progressed
_SALE_TYPES = {
    ListingType.FORECLOSURE_SALE,
    ListingType.TAX_SALE,
    ListingType.SHERIFF_SALE,
    ListingType.AUCTION,
    ListingType.REO,
}

ZOMBIE_AGE_MONTHS = 12


class ZombieProperties(BaseScraper):
    slug = "counties_sc.zombie_properties"
    name = "Zombie Properties Detector (stalled foreclosures)"
    category = "derived"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []

        try:
            from ..web_artifact import load_board
            board = load_board()
        except Exception as exc:
            log.warning("zombie_properties.board_load_fail", error=str(exc)[:160])
            return out

        if not board:
            log.info("zombie_properties.empty_board")
            return out

        cutoff = datetime.utcnow() - timedelta(days=ZOMBIE_AGE_MONTHS * 30)

        # Group listings by dedupe_key
        groups: dict[str, list[Listing]] = {}
        for listing in board:
            key = listing.dedupe_key()
            groups.setdefault(key, []).append(listing)

        zombies_found = 0
        for key, listings in groups.items():
            # Find lis pendens entries in this group
            lp_entries = [
                l for l in listings
                if l.listing_type == ListingType.LIS_PENDENS
            ]
            if not lp_entries:
                continue

            # Check if any listing in the group has progressed to sale
            has_sale = any(
                l.listing_type in _SALE_TYPES for l in listings
            )
            if has_sale:
                continue  # This property has progressed — not a zombie

            # Check if the oldest lis pendens is >12 months old
            oldest_lp = min(
                (l.first_seen for l in lp_entries if l.first_seen),
                default=datetime.utcnow(),
            )
            if oldest_lp >= cutoff:
                continue  # Not old enough yet

            # This is a zombie property — use the most detailed listing
            # as the base (prefer one with an address)
            base = max(lp_entries, key=lambda l: len(l.street_address or ""))

            zombie = base.model_copy(deep=True)
            zombie.listing_type = ListingType.DISTRESSED
            zombie.source = "counties_sc.zombie_properties"
            zombie.last_seen = datetime.utcnow()
            zombie.description = (
                f"Zombie property: lis pendens filed {oldest_lp.strftime('%Y-%m-%d')}, "
                f"no sale recorded in {ZOMBIE_AGE_MONTHS}+ months. "
                f"Original source: {base.source}."
            )

            # Preserve zombie metadata in raw
            if not zombie.raw:
                zombie.raw = {}
            zombie.raw["zombie_property"] = {
                "original_source": base.source,
                "lis_pendens_date": oldest_lp.isoformat(),
                "months_stalled": int(
                    (datetime.utcnow() - oldest_lp).days / 30
                ),
                "dedupe_key": key,
            }

            out.append(zombie)
            zombies_found += 1

        log.info("zombie_properties.done", count=zombies_found, total_board=len(board))
        return out
