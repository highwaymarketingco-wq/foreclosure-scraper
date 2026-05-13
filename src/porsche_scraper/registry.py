"""Scraper registry — central list of every source.

Adding a new site:
1. Implement `scrapers/<slug>.py` with a `BaseScraper` subclass (or
   reuse one of the generic config-driven base scrapers in
   `salvage_brokers.py`, `enthusiast_auctions.py`, `live_collector.py`,
   `government_auctions.py`).
2. Append its factory to `ALL_SCRAPERS` below.
"""
from __future__ import annotations

from typing import Callable

from .base import BaseScraper

# Original sources
from .scrapers.autotempest import AutoTempestScraper
from .scrapers.autotrader import AutotraderScraper
from .scrapers.bring_a_trailer import BringATrailerScraper
from .scrapers.cars_and_bids import CarsAndBidsScraper
from .scrapers.cars_com import CarsComScraper
from .scrapers.carsforsale import CarsForSaleScraper
from .scrapers.copart import CopartScraper
from .scrapers.ebay_motors import EbayMotorsScraper
from .scrapers.iaai import IaaiScraper

# Salvage brokers
from .scrapers.salvage_brokers import (
    make_abetter_bid,
    make_auctionexport,
    make_autobidmaster,
    make_cars4_bid,
    make_sca_auction,
)

# Porsche-specific
from .scrapers.elferspot import ElferspotScraper
from .scrapers.forum_classifieds import (
    PcaMartScraper,
    RennlistScraper,
    SixSpeedOnlineScraper,
)
from .scrapers.pcarmarket import PCarMarketScraper

# Enthusiast auctions
from .scrapers.enthusiast_auctions import (
    make_autohunter,
    make_broad_arrow,
    make_collecting_cars,
    make_hagerty,
    make_iconic,
    make_themarket,
)

# Live collector auctions
from .scrapers.live_collector import (
    make_barrett_jackson,
    make_bonhams_cars,
    make_gooding,
    make_mecum,
    make_rm_sothebys,
)

# Government auctions
from .scrapers.government_auctions import (
    GsaAuctionsScraper,
    make_cws_marketing,
    make_govdeals,
    make_municibid,
    make_property_room,
    make_public_surplus,
)

# General classifieds
from .scrapers.general_classifieds import (
    AutoTraderClassicsScraper,
    ClassicCarsDotComScraper,
    HemmingsScraper,
)

# Sitemap-driven (high-volume URL discovery)
from .scrapers.classiccars_sitemap import ClassicCarsSitemapScraper
from .scrapers.elferspot_sitemap import ElferspotSitemapScraper

# Porsche Approved CPO (official Porsche dealer inventory)
from .scrapers.porsche_cpo import PorscheCPOScraper

# Salvage aggregators — Copart/IAA mirrors + dealer salvage filters
from .scrapers.salvage_aggregators import (
    make_autoauctionspy,
    make_bid_cars,
    make_cargurus_salvage,
    make_carfast,
    make_ebay_salvage,
)

# Peer-to-peer (off by default)
from .scrapers.peer_to_peer import CraigslistScraper, FacebookMarketplaceScraper


# (slug, factory). Factory takes (year_min, price_max) and returns a scraper.
ALL_SCRAPERS: list[tuple[str, Callable[[int, int | None], BaseScraper]]] = [
    # Mainstream
    ("cars_com", lambda y, p: CarsComScraper(year_min=y, price_max=p)),
    ("ebay_motors", lambda y, p: EbayMotorsScraper(year_min=y, price_max=p)),
    ("autotempest", lambda y, p: AutoTempestScraper(year_min=y, price_max=p)),
    ("carsforsale", lambda y, p: CarsForSaleScraper(year_min=y, price_max=p)),
    ("autotrader", lambda y, p: AutotraderScraper(year_min=y, price_max=p)),
    # Big auction houses
    ("bring_a_trailer", lambda y, p: BringATrailerScraper()),
    ("cars_and_bids", lambda y, p: CarsAndBidsScraper(year_min=y, max_bid=p or 45000)),
    # Salvage
    ("copart", lambda y, p: CopartScraper(year_min=y)),
    ("iaai", lambda y, p: IaaiScraper(year_min=y)),
    ("sca_auction", lambda y, p: make_sca_auction(y, p or 45000)),
    ("autobidmaster", lambda y, p: make_autobidmaster(y, p or 45000)),
    ("abetter_bid", lambda y, p: make_abetter_bid(y, p or 45000)),
    ("cars4_bid", lambda y, p: make_cars4_bid(y, p or 45000)),
    ("auctionexport", lambda y, p: make_auctionexport(y, p or 45000)),
    # Porsche-specific
    ("pcarmarket", lambda y, p: PCarMarketScraper()),
    ("rennlist", lambda y, p: RennlistScraper()),
    ("6speedonline", lambda y, p: SixSpeedOnlineScraper()),
    ("pca_mart", lambda y, p: PcaMartScraper(year_min=y)),
    ("elferspot", lambda y, p: ElferspotScraper(year_min=y)),
    # Enthusiast auctions
    ("hagerty_marketplace", lambda y, p: make_hagerty(y, p or 45000)),
    ("collecting_cars", lambda y, p: make_collecting_cars(y, p or 45000)),
    ("themarket", lambda y, p: make_themarket(y, p or 45000)),
    ("autohunter", lambda y, p: make_autohunter(y, p or 45000)),
    ("broad_arrow", lambda y, p: make_broad_arrow(y, p or 45000)),
    ("iconic_auctioneers", lambda y, p: make_iconic(y, p or 45000)),
    # Live collector auctions
    ("mecum", lambda y, p: make_mecum()),
    ("barrett_jackson", lambda y, p: make_barrett_jackson()),
    ("rm_sothebys", lambda y, p: make_rm_sothebys()),
    ("gooding", lambda y, p: make_gooding()),
    ("bonhams_cars", lambda y, p: make_bonhams_cars()),
    # Government / seized
    ("govdeals", lambda y, p: make_govdeals()),
    ("gsa_auctions", lambda y, p: GsaAuctionsScraper()),
    ("public_surplus", lambda y, p: make_public_surplus()),
    ("property_room", lambda y, p: make_property_room()),
    ("municibid", lambda y, p: make_municibid()),
    ("cws_marketing", lambda y, p: make_cws_marketing()),
    # General classifieds
    ("hemmings", lambda y, p: HemmingsScraper(year_min=y, price_max=p or 45000)),
    ("classiccars_com", lambda y, p: ClassicCarsDotComScraper(year_min=y, price_max=p or 45000)),
    ("autotrader_classics", lambda y, p: AutoTraderClassicsScraper(year_min=y, price_max=p or 45000)),
    # Peer-to-peer (off by default)
    ("fb_marketplace", lambda y, p: FacebookMarketplaceScraper(year_min=y, price_max=p or 45000)),
    ("craigslist", lambda y, p: CraigslistScraper(year_min=y, price_max=p or 45000)),
    # Sitemap-driven (high-volume URL discovery)
    ("elferspot_sitemap", lambda y, p: ElferspotSitemapScraper(year_min=y)),
    ("classiccars_sitemap", lambda y, p: ClassicCarsSitemapScraper(year_min=y)),
    # Porsche Approved CPO (official Porsche-dealer inventory)
    ("porsche_cpo", lambda y, p: PorscheCPOScraper()),
    # Salvage aggregators — Copart/IAA mirrors + dealer salvage-title filters
    ("bid_cars",         lambda y, p: make_bid_cars()),
    ("carfast",          lambda y, p: make_carfast()),
    ("autoauctionspy",   lambda y, p: make_autoauctionspy()),
    ("cargurus_salvage", lambda y, p: make_cargurus_salvage()),
    ("ebay_salvage",     lambda y, p: make_ebay_salvage()),
]


# Scrapers off by default. Three buckets:
#   - need auth (fb_marketplace = FB_USER_COOKIE)
#   - slow / lossy (craigslist = per-city fan-out)
#   - bot-blocked from datacenter IPs (the 5 salvage aggregators added in
#     PR #18 — correctly architected but all five sites consistently
#     403/503 from GitHub-Actions and similar cloud egress. Run them via
#     `sf_crawl.py` from a residential IP, or set PROXY_URL to a
#     residential proxy, then opt back in via --include-off.)
DEFAULT_OFF: set[str] = {
    "fb_marketplace",
    "craigslist",
    "bid_cars",
    "carfast",
    "autoauctionspy",
    "cargurus_salvage",
    "ebay_salvage",
}


def build_scrapers(
    *,
    year_min: int,
    price_max: int | None,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    include_off_by_default: bool = False,
) -> list[BaseScraper]:
    only_set = set(only or [])
    skip_set = set(skip or [])
    out: list[BaseScraper] = []
    for slug, factory in ALL_SCRAPERS:
        if only_set:
            if slug not in only_set:
                continue
        else:
            if slug in skip_set:
                continue
            if slug in DEFAULT_OFF and not include_off_by_default:
                continue
        out.append(factory(year_min, price_max))
    return out
