"""Pipeline dedupe + filter orchestration."""
from __future__ import annotations

import asyncio
from typing import Iterable

from porsche_scraper.base import BaseScraper
from porsche_scraper.filters import FilterCriteria
from porsche_scraper.models import Listing, TitleStatus
from porsche_scraper.pipeline import dedupe, run_all


class FakeScraper(BaseScraper):
    def __init__(self, slug: str, listings: list[Listing], boom: bool = False):
        self.slug = slug
        self._listings = listings
        self._boom = boom

    async def fetch(self) -> Iterable[Listing]:
        if self._boom:
            raise RuntimeError("scraper down")
        return self._listings


def _make(**kw) -> Listing:
    base = dict(
        source="x",
        source_url="https://example.com/x",
        title="2016 Porsche 911",
        year=2016,
        model="911",
        price_usd=30_000,
    )
    base.update(kw)
    return Listing(**base)


def test_dedupe_by_vin_prefers_richer_record():
    a = _make(vin="WP0AB2A91GS123456", source="cars_com", mileage=70_000, price_usd=None)
    b = _make(
        vin="WP0AB2A91GS123456",
        source="ebay_motors",
        mileage=72_000,
        price_usd=30_000,
        source_url="https://ebay.com/x",
    )
    out = dedupe([a, b])
    assert len(out) == 1
    # b has price + higher mileage, prefer b
    assert out[0].source == "ebay_motors"


def test_pipeline_runs_in_parallel_and_filters():
    listings_a = [
        _make(source="cars_com", title="2016 Porsche 911", year=2016, price_usd=30_000),
        _make(source="cars_com", title="2018 Porsche Macan", year=2018, model="Macan",
              source_url="https://example.com/macan"),
    ]
    listings_b = [
        _make(source="ebay_motors", title="2014 Porsche 911 — parts only", year=2014,
              source_url="https://example.com/parts",
              title_status=TitleStatus.PARTS_ONLY, drivable=False),
        _make(source="ebay_motors", title="2017 Porsche Boxster", year=2017,
              source_url="https://example.com/box", price_usd=27_000, model="Boxster"),
    ]
    scrapers = [
        FakeScraper("a", listings_a),
        FakeScraper("b", listings_b),
        FakeScraper("c", [], boom=True),  # Errors are absorbed.
    ]
    crit = FilterCriteria(min_year=2014, max_year=2026, max_price_usd=45_000)
    out = asyncio.run(run_all(scrapers, criteria=crit))
    titles = {l.title for l in out}
    assert "2016 Porsche 911" in titles
    assert "2017 Porsche Boxster" in titles
    assert not any("Macan" in t for t in titles)
    assert not any("parts only" in t for t in titles)
