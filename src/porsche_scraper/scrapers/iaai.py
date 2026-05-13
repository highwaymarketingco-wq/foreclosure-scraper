"""IAA (iaai.com) — salvage / rebuilt-title Porsches.

IAA's old `POST /Search/GetVehicleSearchResults` JSON endpoint was
retired (returns 404). The current live URL is the SEO-friendly
`/Vehiclelisting/<Make>` route, which server-renders 100+ vehicle
cards as `<a href="/VehicleDetail/<stock>~US">` links plus an inline
`data-vehicleids='[{"Id":"..."}]'` JSON blob on `#searchHistory`.

curl-cffi `chrome124` impersonation gets through Imperva on this
route — no challenge, just a plain 200.
"""
from __future__ import annotations

import json
import logging
import re

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_text_stealth
from ..models import (
    Listing,
    TitleStatus,
    infer_drivable,
    parse_miles,
    parse_price,
    parse_year,
)

log = logging.getLogger(__name__)

BASE = "https://www.iaai.com"
LISTING_URL = f"{BASE}/Vehiclelisting/Porsche"
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


# IAA's listing page server-renders each vehicle as a thumbnail anchor
# (`<a href="/VehicleDetail/<stock>~US">`) wrapped around a "View All
# Images" button whose onclick carries the structured vehicle data:
#
#   ImageModalClicked(salvageId, stockId, maskedVin, branchId, year,
#                     make, model, trim, hasFullSet)
#
# Price + mileage + title-status are loaded by a separate JS call that
# fires after page load, so they're NOT in the initial HTML. We harvest
# what's available (year, model, trim, VIN-prefix) and tag the listing
# as `salvage_auction` so the dashboard treats it as a salvage signal
# even when an asking price hasn't been posted yet.
_IMAGE_MODAL_RE = re.compile(
    r"ImageModalClicked\("
    r"'(?P<salvage>\d+)',\s*"
    r"'(?P<stock>\d+)~[A-Z]+',\s*"
    r"'(?P<vin>[^']+)',\s*"
    r"'(?P<branch>\d+)',\s*"
    r"'(?P<year>\d{4})',\s*"
    r"'(?P<make>[^']+)',\s*"
    r"'(?P<model>[^']*)',\s*"
    r"'(?P<trim>[^']*)'"
)


def parse_listing_page(html: str) -> list[Listing]:
    """Parse the server-rendered /Vehiclelisting/Porsche page.

    Anchors on the `ImageModalClicked(...)` call attached to each card's
    "View All Images" button — that's where the structured vehicle data
    lives. The page only renders 100 cards per request (no traditional
    pagination); for deeper coverage we'd need to hit a backend AJAX
    endpoint, which is currently undocumented.
    """
    out: list[Listing] = []
    seen: set[str] = set()
    for m in _IMAGE_MODAL_RE.finditer(html):
        stock = m.group("stock")
        if stock in seen:
            continue
        seen.add(stock)
        model = (m.group("model") or "").strip().title()
        trim = (m.group("trim") or "").strip().title()
        # Substring-match — IAA uses "Cayenne Coupe", "Cayenne Hybrid"
        # variants that would slip past an exact-equals check.
        if any(em in model.upper() for em in EXCLUDED_MODELS_UPPER):
            continue
        try:
            year = int(m.group("year"))
        except (TypeError, ValueError):
            continue
        title_parts = [str(year), "Porsche", model]
        if trim and trim.lower() not in ("none", "", " "):
            title_parts.append(trim)
        title = " ".join(p for p in title_parts if p)
        url = f"{BASE}/VehicleDetail/{stock}~US"
        listing = Listing(
            source="iaai",
            source_url=url,
            listing_id=stock,
            vin=m.group("vin") if "*" not in m.group("vin") else None,
            title=title,
            year=year,
            model=model or None,
            trim=trim or None,
            # IAA is a salvage auction — default tier is SALVAGE. Detail
            # pages confirm clean/rebuilt/parts-only on a per-lot basis;
            # we don't have that here, but defaulting to SALVAGE keeps
            # the project-tier dashboard accurate.
            title_status=TitleStatus.SALVAGE,
            seller_type="salvage_auction",
        )
        listing.drivable = infer_drivable(title, listing.title_status)
        out.append(listing)
    return out


class IaaiScraper(BaseScraper):
    slug = "iaai"
    name = "IAA (salvage)"
    timeout_s = 120.0

    def __init__(self, *, year_min: int = 2014, year_max: int = 2030, max_pages: int = 5):
        self.year_min = year_min
        self.year_max = year_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        try:
            html = await fetch_text_stealth(
                LISTING_URL, timeout=45, impersonate="chrome124"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("iaai fetch failed: %s", exc)
            return []
        listings = parse_listing_page(html)
        return [l for l in listings if l.year is None or l.year >= self.year_min]
