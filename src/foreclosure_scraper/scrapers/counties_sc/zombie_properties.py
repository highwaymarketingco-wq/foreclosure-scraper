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
1. Stream the published board (two passes; never load_board(), which refuses a board over 1,200 MB).
2. Group all listings by dedupe_key.
3. Find groups where:
   a. At least one listing has listing_type == "lis_pendens"
   b. The lis pendens first_seen is >12 months old
   c. NO listing in the group has listing_type in
      (FORECLOSURE_SALE, TAX_SALE, SHERIFF_SALE, AUCTION)
   d. The lis pendens itself does NOT carry a terminal auction_status
      (dismissed/satisfied/redeemed/etc.)
4. Yield those as DISTRESSED with a "zombie_property" flag in raw.

FOUND 2026-09-15 (background triage agent, this codebase's zero-row-
scraper audit; confirmed live by hand): condition (d) above did not
exist until now. Every one of this scraper's live rows (14/14, checked
by hand) carried `auction_status="dismissed"` copied verbatim from the
underlying lis pendens record -- a case that was formally DISMISSED is
RESOLVED, not "stalled" (the lender walked away / the case is stuck).
Checking only for progression to an actual SALE_TYPE misses dismissal
entirely, so this scraper was mislabeling 100% of resolved cases as
zombies. main._active_only() (which treats any terminal auction_status
as a closed matter) was silently catching and dropping every one of
these regardless -- so the false positives never actually reached the
board, but the derivation logic itself was still wrong, and would have
started producing garbage the moment anyone "fixed" the apparent
zero-row status by only adding a DATELESS_OK_SOURCES entry (which this
source ALSO needed, since a genuine, non-dismissed zombie property has
no sale_date either -- but that alone wasn't the real bug).

Slug: counties_sc.zombie_properties
Category: derived
ListingType: DISTRESSED
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind, TERMINAL_AUCTION_STATUSES

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


def _iter_board_listings():
    """Every row of the published board as a Listing, one at a time: the board never sits in memory."""
    from pathlib import Path

    from ...board_parts import iter_plain_rows
    from ...board_stream import iter_board_rows

    docs = Path(__file__).resolve().parents[4] / "docs"
    plain = docs / "listings.json"
    rows = iter_plain_rows(plain) if plain.exists() else iter_board_rows(docs / "listings.json.gz")
    for rec in rows:
        try:
            yield Listing.model_validate(rec)
        except Exception:  # noqa: BLE001 - one malformed row must not void the derivation
            continue


class ZombieProperties(BaseScraper):
    slug = "counties_sc.zombie_properties"
    name = "Zombie Properties Detector (stalled foreclosures)"
    category = "derived"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        # 2026-09-24: this scraper is the only one in the codebase that calls
        # load_board() from inside fetch() -- a fully synchronous, no-await
        # operation (gzip decompression + json.loads of docs/listings.json,
        # ~1.1GB, plus Listing.model_validate() on all ~193K rows, plus the
        # synchronous grouping/analysis loop below). A coroutine with zero
        # await points cannot be preempted by asyncio.wait_for -- Task
        # cancellation only takes effect at an await -- so this ran to
        # completion regardless of its own timeout_s=120.0 and froze the
        # ENTIRE event loop for its whole duration. CONFIRMED live 2026-09-23/24:
        # this scraper ran 23:55:53Z-00:37:43Z (41m50s) with ZERO log lines from
        # ANY other scraper anywhere in the run, then 10+ sibling scrapers'
        # timeouts (including counties_sc.qpaybill_delinquent_roll, itself
        # freshly fixed today to salvage partial progress on a real timeout)
        # all fired within an 800ms window the instant this one finally
        # returned -- because none of them ever got scheduler time to make
        # progress while this coroutine held the loop. Running the whole body
        # in a worker thread via asyncio.to_thread lets safe_run's timeout
        # actually apply (the thread keeps running past a timeout, but the
        # EVENT LOOP is freed immediately so every sibling scraper keeps
        # working) and stops this scraper from starving every other one.
        return await asyncio.to_thread(self._compute_zombies)

    def _compute_zombies(self) -> list[Listing]:
        out: list[Listing] = []

        # Two streaming passes over the published board (never load_board(): the whole board was 4.1 GB
        # on 2026-10-08, over the 1,200 MB load ceiling, so this source returned ZERO_RESULT on every VM run).
        # Pass 1 keeps four small facts per dedupe_key; pass 2 picks the base row of each zombie key only.
        try:
            facts: dict[str, list] = {}      # key -> [has_lis_pendens, oldest_lp_first_seen, has_sale, has_terminal]
            total = 0
            for listing in _iter_board_listings():
                total += 1
                f = facts.setdefault(listing.dedupe_key(), [False, None, False, False])
                if listing.listing_type == ListingType.LIS_PENDENS:
                    f[0] = True
                    if listing.first_seen and (f[1] is None or listing.first_seen < f[1]):
                        f[1] = listing.first_seen
                if listing.listing_type in _SALE_TYPES:
                    f[2] = True
                if (listing.auction_status or "").lower() in TERMINAL_AUCTION_STATUSES:
                    f[3] = True
        except Exception as exc:
            log.warning("zombie_properties.board_load_fail", error=str(exc)[:160])
            return out

        if not total:
            log.info("zombie_properties.empty_board")
            return out

        now = datetime.utcnow()
        cutoff = now - timedelta(days=ZOMBIE_AGE_MONTHS * 30)

        zombie_keys: dict[str, datetime] = {}
        for key, (has_lp, oldest, has_sale, has_terminal) in facts.items():
            if not has_lp:
                continue
            if has_sale:
                continue  # This property has progressed -- not a zombie
            # A lis pendens with a TERMINAL disposition (dismissed/satisfied/redeemed/etc.) is RESOLVED, not
            # stalled -- the case is over, whether or not it ever became a sale (found 2026-09-15: every live
            # row this scraper produced carried auction_status="dismissed"; see the module docstring).
            if has_terminal:
                continue
            oldest_lp = oldest if oldest is not None else now     # no first_seen anywhere: "now", never old enough
            if oldest_lp >= cutoff:
                continue  # Not old enough yet
            zombie_keys[key] = oldest_lp
        del facts

        if not zombie_keys:
            log.info("zombie_properties.done", count=0, total_board=total)
            return out

        # Pass 2: the base row of each zombie key = its lis pendens with the longest street address
        # (the first such row on a tie, like max() over the group did).
        bases: dict[str, Listing] = {}
        for listing in _iter_board_listings():
            if listing.listing_type != ListingType.LIS_PENDENS:
                continue
            key = listing.dedupe_key()
            if key not in zombie_keys:
                continue
            best = bases.get(key)
            if best is None or len(listing.street_address or "") > len(best.street_address or ""):
                bases[key] = listing

        zombies_found = 0
        for key, base in bases.items():
            oldest_lp = zombie_keys[key]
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

        log.info("zombie_properties.done", count=zombies_found, total_board=total)
        return out
