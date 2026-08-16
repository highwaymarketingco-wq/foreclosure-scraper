"""CarFax — used-car listings with accident history, nationwide Porsche inventory.

WHERE THE DATA IS
    CarFax renders schema.org Vehicle JSON-LD, one block per car:

        "@type":"Vehicle","name":"2020 Porsche Cayenne","bodyType":"SUV",
        "image":"...","offers":{"@type":"Offer","price":48998,"priceCurrency":"USD"},
        "knownVehicleDamages":"No Accident or Damage Reported",
        "mileageFromOdometer":41230, ...

    Same rendered-browser + JSON-LD approach as the Carvana and TrueCar readers.
    Note two CarFax specifics: `price` and `mileageFromOdometer` are plain
    integers (not the nested "value" objects Carvana uses), and each car carries
    `knownVehicleDamages` — the accident summary, kept in raw for the dashboard.

    Confirmed live 2026-08-14 at `carfax.com/Used-Porsche_m28` (the real Porsche
    make code; m14 is Infiniti). No login, no API key, nationwide.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from ..base import BaseScraper
from ..http_client import fetch_rendered
from ..models import Listing, infer_drivable, infer_title_status, parse_year

log = logging.getLogger(__name__)

_VEHICLE_START = re.compile(r'"@type":"Vehicle"')
_PAGES = 6  # CarFax paginates ?page=N.


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

    price_m = re.search(r'"price":(\d+)', chunk)
    miles_m = re.search(r'"mileageFromOdometer":(\d+)', chunk)
    img_m = re.search(r'"image":"([^"]+)"', chunk)
    dmg_m = re.search(r'"knownVehicleDamages":"([^"]+)"', chunk)
    vin_m = re.search(r'\b([A-HJ-NPR-Z0-9]{17})\b', chunk)

    try:
        price_val = float(price_m.group(1)) if price_m else None
    except (TypeError, ValueError):
        price_val = None

    vin = vin_m.group(1) if vin_m else None
    status = infer_title_status(name)
    listing = Listing(
        source="carfax",
        source_url=(f"https://www.carfax.com/vehicle/{vin}" if vin
                    else "https://www.carfax.com/Used-Porsche_m28"),
        listing_id=vin,
        vin=vin,
        title=name,
        year=parse_year(name),
        mileage=int(miles_m.group(1)) if miles_m else None,
        price_usd=price_val,
        photo_url=img_m.group(1) if img_m else None,
        title_status=status,
        seller_type="dealer",
        raw={"carfax": {"known_damages": dmg_m.group(1)}} if dmg_m else {},
    )
    listing.drivable = infer_drivable(name, status)
    return listing


def _iter_listings(html: str) -> Iterable[Listing]:
    for m in _VEHICLE_START.finditer(html):
        li = _parse_vehicle_chunk(html[m.start():m.start() + 900])
        if li is not None:
            yield li


class CarfaxScraper(BaseScraper):
    """Nationwide used Porsches from CarFax via rendered JSON-LD."""

    slug = "carfax"
    name = "CarFax"
    timeout_s = 600.0

    def __init__(self, *, price_max: int = 40_000, year_min: int = 2014):
        self.price_max = price_max
        self.year_min = year_min

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, _PAGES + 1):
            url = f"https://www.carfax.com/Used-Porsche_m28?page={page}"
            try:
                html = await fetch_rendered(
                    url, timeout=75, scroll_iterations=3,
                    post_scroll_wait_ms=1800, wait_for_selector="body")
            except Exception as exc:  # noqa: BLE001
                log.warning("carfax page %d failed: %s", page, exc)
                continue
            page_listings = list(_iter_listings(html))
            if not page_listings:
                break
            new = 0
            for li in page_listings:
                key = li.vin or li.title
                if key and key not in seen:
                    seen.add(key)
                    out.append(li)
                    new += 1
            if new == 0:
                break  # same page repeating — pagination exhausted
        log.info("carfax: %d unique porsches across %d pages", len(out), _PAGES)
        return out
