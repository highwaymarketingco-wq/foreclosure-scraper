"""Scraper registry — central list of every source.

Adding a new site:
1. Implement `scrapers/<slug>.py` with a `BaseScraper` subclass.
2. Append its factory to `ALL_SCRAPERS` below.
"""
from __future__ import annotations

from typing import Callable

from .base import BaseScraper
from .scrapers.autotempest import AutoTempestScraper
from .scrapers.autotrader import AutotraderScraper
from .scrapers.bring_a_trailer import BringATrailerScraper
from .scrapers.cars_and_bids import CarsAndBidsScraper
from .scrapers.cars_com import CarsComScraper
from .scrapers.carsforsale import CarsForSaleScraper
from .scrapers.copart import CopartScraper
from .scrapers.ebay_motors import EbayMotorsScraper
from .scrapers.iaai import IaaiScraper


# (slug, factory) — factory takes (year_min, price_max) and returns a scraper.
ALL_SCRAPERS: list[tuple[str, Callable[[int, int | None], BaseScraper]]] = [
    ("cars_com", lambda y, p: CarsComScraper(year_min=y, price_max=p)),
    ("ebay_motors", lambda y, p: EbayMotorsScraper(year_min=y, price_max=p)),
    ("autotempest", lambda y, p: AutoTempestScraper(year_min=y, price_max=p)),
    ("carsforsale", lambda y, p: CarsForSaleScraper(year_min=y, price_max=p)),
    ("autotrader", lambda y, p: AutotraderScraper(year_min=y, price_max=p)),
    ("bring_a_trailer", lambda y, p: BringATrailerScraper()),
    ("cars_and_bids", lambda y, p: CarsAndBidsScraper(year_min=y, max_bid=p or 45000)),
    ("copart", lambda y, p: CopartScraper(year_min=y)),
    ("iaai", lambda y, p: IaaiScraper(year_min=y)),
]


def build_scrapers(
    *,
    year_min: int,
    price_max: int | None,
    only: list[str] | None = None,
    skip: list[str] | None = None,
) -> list[BaseScraper]:
    only_set = set(only or [])
    skip_set = set(skip or [])
    out: list[BaseScraper] = []
    for slug, factory in ALL_SCRAPERS:
        if only_set and slug not in only_set:
            continue
        if slug in skip_set:
            continue
        out.append(factory(year_min, price_max))
    return out
