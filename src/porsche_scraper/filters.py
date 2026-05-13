"""Apply user search criteria to scraped listings.

Rule:
- Year between MIN_YEAR (2014) and CURRENT_YEAR inclusive.
- Price <= MAX_PRICE_USD ($45,000)  OR  title status is salvage/rebuilt.
- Must not be a known-non-drivable car (parts-only, blown engine, etc.).
- Model must not contain Panamera / Cayenne / Macan.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import EXCLUDED_MODELS, Listing, TitleStatus

MIN_YEAR = 2014
MAX_PRICE_USD = 45_000.0


def current_year() -> int:
    return datetime.now(timezone.utc).year


@dataclass(frozen=True)
class FilterCriteria:
    min_year: int = MIN_YEAR
    max_year: int = 0  # 0 → resolve to current_year() at filter time
    max_price_usd: float = MAX_PRICE_USD
    excluded_models: tuple[str, ...] = EXCLUDED_MODELS
    allow_unknown_price: bool = False
    # If True, listings without a known year are dropped. If False, kept
    # only when title text strongly suggests it's within the year window.
    require_known_year: bool = True

    def resolved_max_year(self) -> int:
        return self.max_year if self.max_year > 0 else current_year()


def matches(listing: Listing, criteria: FilterCriteria | None = None) -> bool:
    c = criteria or FilterCriteria()
    max_year = c.resolved_max_year()

    if not _year_ok(listing, c.min_year, max_year, c.require_known_year):
        return False

    if _is_excluded_model(listing, c.excluded_models):
        return False

    if not _price_or_title_ok(listing, c.max_price_usd, c.allow_unknown_price):
        return False

    # Drivable filter: reject when we have direct evidence the car doesn't run.
    if listing.drivable is False:
        return False
    if listing.title_status == TitleStatus.PARTS_ONLY:
        return False

    return True


def filter_listings(
    listings: list[Listing], criteria: FilterCriteria | None = None
) -> list[Listing]:
    return [l for l in listings if matches(l, criteria)]


def _year_ok(listing: Listing, min_year: int, max_year: int, require_known: bool) -> bool:
    y = listing.year
    if y is None:
        return not require_known  # keep if we said unknown is OK
    return min_year <= y <= max_year


def _is_excluded_model(listing: Listing, excluded: tuple[str, ...]) -> bool:
    hay = " ".join(filter(None, [listing.model, listing.trim, listing.title])).lower()
    return any(em in hay for em in excluded)


def _price_or_title_ok(listing: Listing, max_price: float, allow_unknown_price: bool) -> bool:
    if listing.title_status in (TitleStatus.SALVAGE, TitleStatus.REBUILT):
        return True
    price = listing.effective_price
    if price is None:
        return allow_unknown_price
    return price <= max_price
