"""IAA (iaai.com) — salvage / rebuilt-title Porsches.

IAA's search backend accepts JSON POSTs:

    POST https://www.iaai.com/Search/GetVehicleSearchResults
    Body: {"Keyword":"porsche","Year":[2014,2030],
            "BuyNowPrice":[0,45000],"PageSize":100,"PageNumber":N}

Response: { Vehicles: [...] }. Each entry has Year, Make, Model,
CurrentBid, BuyNowPrice, Odometer, BranchName, StockNumber,
VehicleDetailsUrl, LargeImage, LossType, PrimaryDamage, SaleTitleType,
RunAndDrive ("Yes"/"No"/None).

IAA sits behind Imperva so stealth transport + proxies are recommended.
"""
from __future__ import annotations

import logging

from ..base import BaseScraper
from ..http_client import fetch_json
from ..models import (
    Listing,
    TitleStatus,
    infer_drivable,
    parse_miles,
    parse_price,
)

log = logging.getLogger(__name__)

BASE = "https://www.iaai.com"
SEARCH_URL = f"{BASE}/Search/GetVehicleSearchResults"
EXCLUDED_MODELS_UPPER = ("PANAMERA", "CAYENNE", "MACAN")


def _title_status(raw: str | None) -> TitleStatus:
    if not raw:
        return TitleStatus.UNKNOWN
    s = raw.lower()
    if "rebuilt" in s or "reconstructed" in s:
        return TitleStatus.REBUILT
    if "parts" in s or "non-repairable" in s or "non repairable" in s:
        return TitleStatus.PARTS_ONLY
    if "salvage" in s:
        return TitleStatus.SALVAGE
    if "flood" in s or "water" in s:
        return TitleStatus.FLOOD
    if "clean" in s or "clear" in s:
        return TitleStatus.CLEAN
    return TitleStatus.UNKNOWN


def _drivable(v: dict, status: TitleStatus, title: str) -> bool | None:
    rd = (v.get("RunAndDrive") or v.get("run_and_drive") or "").lower()
    if rd in ("yes", "y", "true"):
        return True
    if rd in ("no", "n", "false"):
        return False
    return infer_drivable(title, status)


def _vehicle_to_listing(v: dict) -> Listing | None:
    model = (v.get("Model") or "").strip()
    if model.upper() in EXCLUDED_MODELS_UPPER:
        return None
    stock = v.get("StockNumber") or v.get("Stock") or v.get("Id")
    if not stock:
        return None
    detail = v.get("VehicleDetailsUrl") or f"/VehicleDetail/{stock}~US"
    url = detail if detail.startswith("http") else f"{BASE}{detail}"
    title = " ".join(filter(None, [str(v.get("Year") or ""), "Porsche", model]))
    status = _title_status(v.get("SaleTitleType") or v.get("TitleType"))
    listing = Listing(
        source="iaai",
        source_url=url,
        listing_id=str(stock),
        vin=v.get("VIN") or v.get("Vin"),
        title=title,
        year=int(v["Year"]) if str(v.get("Year") or "").isdigit() else None,
        model=model or None,
        price_usd=parse_price(v.get("BuyNowPrice")),
        current_bid_usd=parse_price(v.get("CurrentBid")),
        mileage=parse_miles(v.get("Odometer")),
        location=v.get("BranchName") or v.get("Branch"),
        photo_url=v.get("LargeImage") or v.get("ThumbnailImage"),
        title_status=status,
        seller_type="salvage_auction",
        raw={"iaai": v},
    )
    listing.drivable = _drivable(v, status, title)
    return listing


def parse_search_response(payload: dict) -> list[Listing]:
    out: list[Listing] = []
    seen: set[str] = set()
    for v in (payload or {}).get("Vehicles") or []:
        listing = _vehicle_to_listing(v)
        if listing and listing.listing_id not in seen:
            seen.add(listing.listing_id)
            out.append(listing)
    return out


class IaaiScraper(BaseScraper):
    slug = "iaai"
    name = "IAA (salvage)"
    timeout_s = 180.0

    def __init__(self, *, year_min: int = 2014, year_max: int = 2030, max_pages: int = 5):
        self.year_min = year_min
        self.year_max = year_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(1, self.max_pages + 1):
            body = {
                "Keyword": "porsche",
                "Year": [self.year_min, self.year_max],
                "PageSize": 100,
                "PageNumber": page,
                "SortColumn": "AuctionDate",
                "SortDirection": "Asc",
            }
            try:
                payload = await fetch_json(
                    SEARCH_URL,
                    method="POST",
                    json_body=body,
                    timeout=45,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Origin": BASE,
                        "Referer": f"{BASE}/Search?Keyword=porsche",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("iaai page %d failed: %s", page, exc)
                break
            listings = parse_search_response(payload)
            if not listings:
                break
            out.extend(listings)
        return out
