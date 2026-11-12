"""TrueCar — nationwide used-car marketplace, large Porsche inventory.

WHERE THE DATA IS
    TrueCar renders a schema.org ItemList of Vehicle objects into the page. Each
    carries everything needed, cleanly:

        "@type":"Vehicle","name":"2018 Porsche Macan S","model":"Macan",
        "offers":{...,"price":"26697.00","priceCurrency":"USD",
                  "sku":"WP1AA2AY0LDA07110",
                  "url":".../listing/WP1AA2AY0LDA07110/","seller":"Spartanburg Honda"},
        "vehicleIdentificationNumber":"WP1AA2AY0LDA07110"

    So this renders the search page (fetch_rendered), scrolls, and regex-parses
    the JSON-LD Vehicle blocks — same approach as the Carvana reader. Confirmed
    live 2026-08-14: full VIN + price + seller per car.

NO LOGIN, NO API KEY. Nationwide.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from ..base import BaseScraper
from ..http_client import fetch_rendered
from ..models import Listing, infer_drivable, infer_title_status, parse_year

log = logging.getLogger(__name__)

_VEHICLE_START = re.compile(r'"@type":"Vehicle","name":"')
_PAGES = 6  # TrueCar paginates ?page=N.


def _parse_vehicle_chunk(chunk: str) -> Listing | None:
    name_m = re.search(r'"name":"([^"]+)"', chunk)
    if not name_m:
        return None
    name = name_m.group(1).strip()
    low = name.lower()
    if "porsche" not in low:
        return None
    if any(em in low for em in ("panamera", "macan")):
        return None

    vin_m = re.search(r'"vehicleIdentificationNumber":"([A-HJ-NPR-Z0-9]{17})"', chunk) \
        or re.search(r'"sku":"([A-HJ-NPR-Z0-9]{17})"', chunk)
    vin = vin_m.group(1) if vin_m else None
    price_m = re.search(r'"price":"?([\d.]+)"?', chunk)
    miles_m = re.search(r'"mileageFromOdometer":\{[^}]*?"value":"?(\d+)', chunk)
    url_m = re.search(r'"url":"(https://www\.truecar\.com/used-cars-for-sale/listing/[^"]+)"', chunk)

    try:
        price_val = float(price_m.group(1)) if price_m else None
    except (TypeError, ValueError):
        price_val = None

    url = (url_m.group(1) if url_m else
           (f"https://www.truecar.com/used-cars-for-sale/listing/{vin}/" if vin
            else "https://www.truecar.com/used-cars-for-sale/listings/porsche/"))
    status = infer_title_status(name)
    listing = Listing(
        source="truecar",
        source_url=url,
        listing_id=vin,
        vin=vin,
        title=name,
        year=parse_year(name),
        mileage=int(miles_m.group(1)) if miles_m else None,
        price_usd=price_val,
        title_status=status,
        seller_type="dealer",
    )
    listing.drivable = infer_drivable(name, status)
    return listing


def _iter_listings(html: str) -> Iterable[Listing]:
    for m in _VEHICLE_START.finditer(html):
        li = _parse_vehicle_chunk(html[m.start():m.start() + 1000])
        if li is not None:
            yield li


class TrueCarScraper(BaseScraper):
    """Nationwide used Porsches from TrueCar via rendered JSON-LD."""

    slug = "truecar"
    name = "TrueCar"
    timeout_s = 600.0

    def __init__(self, *, price_max: int = 40_000, year_min: int = 2014):
        self.price_max = price_max
        self.year_min = year_min

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, _PAGES + 1):
            url = ("https://www.truecar.com/used-cars-for-sale/listings/porsche/"
                   f"?page={page}")
            try:
                html = await fetch_rendered(
                    url, timeout=75, scroll_iterations=3,
                    post_scroll_wait_ms=1800, wait_for_selector="body")
            except Exception as exc:  # noqa: BLE001
                log.warning("truecar page %d failed: %s", page, exc)
                continue
            page_listings = list(_iter_listings(html))
            if not page_listings:
                break
            for li in page_listings:
                key = li.vin or li.source_url
                if key and key not in seen:
                    seen.add(key)
                    out.append(li)
        log.info("truecar: %d unique porsches across %d pages", len(out), _PAGES)
        return out
