"""Copart — salvage / rebuilt-title Porsches.

Copart's HTML is gated, but their Solr endpoint accepts unauthenticated
JSON POSTs (some queries get throttled — use proxies if so):

    POST https://www.copart.com/public/data/lotdetails/solr/lotSearch
    Body: {"query":["porsche"],"filter":{"MAKE":["PORSCHE"],
            "LCY":["2014..2030"]},"sort":["auction_date_utc asc"],
            "page":N,"size":100}

Response: data.results.content[] with mkn(make), lcy(year), mmd(model),
dynamicLotDetails.currentBid/buyItNowPrice, orr(odometer), td(title:
"CLEAR","SALVAGE","REBUILT","PARTS ONLY"). All Copart cars are salvage-
or insurance-auction; treat as salvage_auction.
"""
from __future__ import annotations

import logging

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_json, fetch_rendered
from ..models import (
    Listing,
    TitleStatus,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)

log = logging.getLogger(__name__)

BASE = "https://www.copart.com"
SEARCH_URL = f"{BASE}/public/data/lotdetails/solr/lotSearch"
EXCLUDED_MODELS_UPPER = ("PANAMERA", "CAYENNE", "MACAN")


def _td_to_status(td: str | None) -> TitleStatus:
    if not td:
        return TitleStatus.UNKNOWN
    s = td.upper()
    if "REBUILT" in s or "RECONSTRUCTED" in s:
        return TitleStatus.REBUILT
    if "PARTS" in s:
        return TitleStatus.PARTS_ONLY
    if "SALVAGE" in s or "JUNK" in s:
        return TitleStatus.SALVAGE
    if "FLOOD" in s or "WATER" in s:
        return TitleStatus.FLOOD
    if "CLEAR" in s or "CLEAN" in s:
        return TitleStatus.CLEAN
    return TitleStatus.UNKNOWN


def _drivable_from_copart(d: dict, status: TitleStatus, title: str) -> bool | None:
    """Copart marks "Run & Drive" as a boolean / icon. dynamic.runAndDriveYn=Y."""
    dyn = d.get("dynamicLotDetails") or {}
    if dyn.get("runAndDriveYn") == "Y" or d.get("rd") == "Y":
        return True
    if dyn.get("runAndDriveYn") == "N" or d.get("rd") == "N":
        return False
    return infer_drivable(title, status)


def _lot_to_listing(d: dict) -> Listing | None:
    if not d:
        return None
    mmd = (d.get("mmd") or "").strip()
    if mmd.upper() in EXCLUDED_MODELS_UPPER:
        return None  # Drop excluded models server-side too.
    lot_no = d.get("lotNumberStr") or d.get("ln")
    if not lot_no:
        return None
    url = f"{BASE}/lot/{lot_no}"
    title = " ".join(filter(None, [str(d.get("lcy") or ""), "Porsche", mmd]))
    dyn = d.get("dynamicLotDetails") or {}
    price = parse_price(dyn.get("buyItNowPrice") or d.get("buyItNowPrice"))
    bid = parse_price(dyn.get("currentBid") or d.get("currentBid"))
    status = _td_to_status(d.get("td") or d.get("ts"))
    listing = Listing(
        source="copart",
        source_url=url,
        listing_id=str(lot_no),
        vin=d.get("fv") or d.get("vin"),
        title=title,
        year=int(d["lcy"]) if str(d.get("lcy") or "").isdigit() else None,
        model=mmd or None,
        price_usd=price,
        current_bid_usd=bid,
        mileage=parse_miles(d.get("orr") or d.get("odometer")),
        location=d.get("yn") or d.get("yardName"),
        photo_url=d.get("lurl") or d.get("lotImageUrl"),
        title_status=status,
        seller_type="salvage_auction",
        raw={"copart": d},
    )
    listing.drivable = _drivable_from_copart(d, status, title)
    return listing


def parse_solr_response(payload: dict) -> list[Listing]:
    data = (payload or {}).get("data") or {}
    results = data.get("results") or {}
    content = results.get("content") or []
    out: list[Listing] = []
    seen: set[str] = set()
    for d in content:
        listing = _lot_to_listing(d)
        if listing and listing.listing_id not in seen:
            seen.add(listing.listing_id)
            out.append(listing)
    return out


class CopartScraper(BaseScraper):
    slug = "copart"
    name = "Copart (salvage)"
    timeout_s = 180.0

    def __init__(self, *, year_min: int = 2014, year_max: int = 2030, max_pages: int = 5):
        self.year_min = year_min
        self.year_max = year_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        """Try Solr JSON first; fall back to Scrapling-rendered HTML when
        the Solr endpoint rejects us (it does as of 2026-05).
        """
        out = await self._fetch_solr()
        if out:
            return out
        return await self._fetch_html()

    async def _fetch_solr(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(self.max_pages):
            body = {
                "query": ["porsche"],
                "filter": {
                    "MAKE": ["PORSCHE"],
                    "LCY": [f"{self.year_min}..{self.year_max}"],
                },
                "sort": ["auction_date_utc asc"],
                "page": page, "size": 100,
                "watchListOnly": False, "freeFormSearch": False,
            }
            try:
                payload = await fetch_json(
                    SEARCH_URL, method="POST", json_body=body, timeout=45,
                    headers={"Accept": "application/json", "Content-Type": "application/json",
                             "Origin": BASE,
                             "Referer": f"{BASE}/lotSearchResults?free=true&query=porsche"},
                )
            except Exception as exc:  # noqa: BLE001
                log.info("copart solr page %d: %s", page, exc)
                return out
            if payload.get("returnCode") not in (0, None):
                log.info("copart solr blocked: %s", payload.get("returnCodeDesc"))
                return out
            listings = parse_solr_response(payload)
            if not listings:
                break
            out.extend(listings)
        return out

    async def _fetch_html(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(self.max_pages):
            url = (f"{BASE}/lotSearchResults/?free=true&query=porsche"
                   f"&from={self.year_min}&to={self.year_max}&page={page}")
            try:
                html = await fetch_rendered(
                    url, timeout=90,
                    wait_for_selector="a[href*='/lot/']",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("copart html page %d: %s", page, exc)
                break
            tree = HTMLParser(html)
            anchors = tree.css("a[href*='/lot/']")
            if not anchors:
                break
            for a in anchors:
                href = a.attributes.get("href") or ""
                if "/lot/" not in href:
                    continue
                full = href if href.startswith("http") else f"{BASE}{href}"
                if full in seen:
                    continue
                seen.add(full)
                # The slug carries year+model: /lot/12345678/salvage-2015-porsche-911-...
                slug = href.rstrip("/").rsplit("/", 1)[-1].lower()
                if any(em in slug for em in ("panamera", "cayenne", "macan")):
                    continue
                title = a.text(strip=True)
                if not title or "porsche" not in title.lower():
                    # The label might be empty (icon-only anchor); use slug.
                    if "porsche" not in slug:
                        continue
                    title = slug.replace("-", " ").replace("salvage ", "").title()
                listing = Listing(
                    source="copart",
                    source_url=full,
                    listing_id=href.rstrip("/").rsplit("/")[-2],
                    title=title,
                    year=parse_year(title) or parse_year(slug),
                    title_status=(infer_title_status(slug) if "salvage" in slug or "rebuilt" in slug
                                  else TitleStatus.SALVAGE),
                    seller_type="salvage_auction",
                )
                listing.drivable = infer_drivable(title, listing.title_status)
                out.append(listing)
        return out
