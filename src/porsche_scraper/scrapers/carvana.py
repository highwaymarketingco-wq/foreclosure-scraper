"""Carvana — nationwide online dealer, one of the largest used-Porsche inventories.

WHERE THE DATA IS
    Carvana is a Next.js app that loads inventory client-side, so the raw HTML
    shell has none of it. But the rendered page embeds one **schema.org JSON-LD
    Vehicle** block per car:

        {"@context":"https://schema.org","@type":"Vehicle",
         "name":"2022 Porsche Macan","manufacturer":"Porsche","model":"Macan",
         "url":".../vehicle/4447311","offers":{...,"price":"40990"},
         "mileageFromOdometer":{"value":"31000"}, ...}

    So this renders the search page in a real browser (fetch_rendered), scrolls
    to load the grid, and parses the JSON-LD — clean, structured, no DOM
    guesswork. Confirmed live 2026-08-14: 21 Porsches per page with name + id +
    price.

NO LOGIN, NO API KEY. Nationwide, so a real volume source unlike local
Marketplace.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from ..base import BaseScraper
from ..http_client import fetch_rendered
from ..models import Listing, infer_drivable, infer_title_status, parse_year

log = logging.getLogger(__name__)

# One schema.org Vehicle block per car. Read a bounded chunk from each start
# marker and pull fields by regex — Carvana's objects nest and sometimes exceed
# a naive brace scan, so field regex over a window is the reliable path (it is
# what actually extracted all 21 per page in testing).
_JSONLD_START = re.compile(r'\{"@context":"https://schema\.org","@type":"Vehicle"')
_PAGES = 6  # Carvana paginates ?page=N; each page is ~20 cars.


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

    id_m = re.search(r'carvana\.com/vehicle/(\d+)', chunk)
    lid = id_m.group(1) if id_m else None
    price_m = re.search(r'"price":"?([\d.]+)"?', chunk)
    miles_m = (
        re.search(r'"mileageFromOdometer":\{[^}]*?"value":"?(\d+)', chunk)
        or re.search(r'"value":"?(\d+)"?,"unitCode":"SMI"', chunk)
    )
    img_m = re.search(r'"image":"([^"]+)"', chunk)

    try:
        price_val = float(price_m.group(1)) if price_m else None
    except (TypeError, ValueError):
        price_val = None

    status = infer_title_status(name)
    listing = Listing(
        source="carvana",
        source_url=(f"https://www.carvana.com/vehicle/{lid}" if lid
                    else "https://www.carvana.com/cars/porsche"),
        listing_id=lid,
        title=name,
        year=parse_year(name),
        mileage=int(miles_m.group(1)) if miles_m else None,
        price_usd=price_val,
        photo_url=img_m.group(1) if img_m else None,
        title_status=status,
        seller_type="dealer",
    )
    listing.drivable = infer_drivable(name, status)
    return listing


def _iter_listings(html: str) -> Iterable[Listing]:
    for m in _JSONLD_START.finditer(html):
        li = _parse_vehicle_chunk(html[m.start():m.start() + 1200])
        if li is not None:
            yield li


class CarvanaScraper(BaseScraper):
    """Nationwide used Porsches from Carvana via rendered JSON-LD."""

    slug = "carvana"
    name = "Carvana"
    timeout_s = 600.0

    def __init__(self, *, price_max: int = 40_000, year_min: int = 2014):
        self.price_max = price_max
        self.year_min = year_min

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, _PAGES + 1):
            url = f"https://www.carvana.com/cars/porsche?page={page}"
            try:
                html = await fetch_rendered(
                    url, timeout=75, scroll_iterations=3,
                    post_scroll_wait_ms=1800, wait_for_selector="body")
            except Exception as exc:  # noqa: BLE001
                log.warning("carvana page %d failed: %s", page, exc)
                continue
            page_listings = list(_iter_listings(html))
            if not page_listings:
                break  # ran past the last page
            for li in page_listings:
                key = li.listing_id or li.source_url
                if key and key not in seen:
                    seen.add(key)
                    out.append(li)
        log.info("carvana: %d unique porsches across %d pages", len(out), _PAGES)
        return out
