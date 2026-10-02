"""Tranzon — online real-estate auctions (ASP.NET, httpx-parseable).

Tranzon.com hosts real-estate auction listings across the eastern US.
The online-auctions page is server-rendered ASP.NET with property data
in span elements using the pattern:

    <span id="ContentPlaceHolder1_SearchGrid_lbladdress1_N">ADDR<br/>CITY, ST ZIP</span>
    <span id="ContentPlaceHolder1_SearchGrid_lblAuctionDate1_N">M/D/YY<br/>@ HH:MM PM ET</span>

We parse page 1 (which shows all current auctions — typically 10-15)
and filter for NC + SC properties. Tranzon has a small inventory but
high-value auction leads (sheriff sales, estate sales, bank-owned).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

AUCTION_URL = "https://www.tranzon.com/online-real-estate-auctions.aspx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
}

# FIXED 2026-10-01 (national-auction-tier audit, batch 4): this hardcoded
# city->county map only covered ~9 big-metro cities per state, NONE of
# which are in the 18-county footprint (Wilson/Raleigh/Charlotte/.../
# Durham for NC; Greenville/Columbia/Charleston/... for SC are all
# out-of-footprint or outright DENIED). A real in-footprint hit (e.g.
# Rutherfordton, Hendersonville, Spartanburg itself was the one accidental
# overlap) would have silently gotten county=None. Use the shared
# WNC/upstate-SC gazetteer instead (same helper national.gsa_realproperty,
# national.hibid_real_estate and national.gsa_surplus already use) via
# _county_for() below.


def _parse_address(raw: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Parse '2716 South Crater RoadPetersburg, VA 23805' or '2716 South Crater Road<br/>Petersburg, VA 23805' into (street, city, state, zip)."""
    # selectolax .text() strips <br/> tags, concatenating street+city
    # Try splitting on <br/> first (if raw HTML), then fall back to city-state regex
    parts = re.split(r"<br\s*/?>", raw, maxsplit=1)
    if len(parts) == 2:
        street = parts[0].strip()
        cs = parts[1].strip()
        m = re.match(r"([^,]+),\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)?", cs)
        if m:
            return street, m.group(1).strip(), m.group(2), m.group(3)
        return street, None, None, None

    # Fallback: text() already stripped <br/>, so find ", XX 12345" pattern
    m = re.search(r",\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)?", raw)
    if m:
        state = m.group(1)
        zip_code = m.group(2)
        # City is before the comma
        city_m = re.search(r"([A-Za-z .]+),\s*" + state, raw)
        city = city_m.group(1).strip() if city_m else None
        # Street is everything before the city
        if city:
            idx = raw.find(city)
            street = raw[:idx].strip() if idx > 0 else None
        else:
            street = None
        return street, city, state, zip_code

    return None, None, None, None


def _parse_date(raw: str) -> datetime | None:
    """Parse '8/20/26<br/>@ 12:00 PM ET' into a datetime."""
    raw = re.sub(r"<br\s*/?>", " ", raw).strip()
    raw = re.sub(r"\s*@\s*", " ", raw)
    raw = re.sub(r"\s+ET$", "", raw, flags=re.I)
    for fmt in ("%m/%d/%y %I:%M %p", "%m/%d/%y %H:%M", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _county_for(city: str | None, state: str) -> str | None:
    """Best-effort city -> in-footprint county via the shared gazetteer.
    Returns None when unknown (the row is still emitted)."""
    if not city:
        return None
    try:
        from ..._upstate_city_to_county import upstate_county_for
        return upstate_county_for(city, state)
    except Exception:  # noqa: BLE001
        return None


async def _fetch_tranzon() -> list[Listing]:
    out: list[Listing] = []
    try:
        html = await get_text(AUCTION_URL, headers=HEADERS, timeout=30.0, impersonate=True)
    except Exception as exc:
        log.warning("tranzon.fetch_fail", error=str(exc)[:200])
        return out

    if not html or len(html) < 5000:
        log.warning("tranzon.bad_response", size=len(html) if html else 0)
        return out
    tree = HTMLParser(html)

    # Each property is in a row with spans like:
    # ContentPlaceHolder1_SearchGrid_lbladdress1_N (street + city + state + zip)
    # ContentPlaceHolder1_SearchGrid_lblcitysate_N (city, state)
    # ContentPlaceHolder1_SearchGrid_lblAuctionDate1_N (auction date)
    addr_spans = tree.css("span[id^='ContentPlaceHolder1_SearchGrid_lbladdress1_']")
    date_spans = tree.css("span[id^='ContentPlaceHolder1_SearchGrid_lblAuctionDate1_']")
    city_spans = tree.css("span[id^='ContentPlaceHolder1_SearchGrid_lblcitysate_']")
    # FIXED 2026-10-01 (national-auction-tier audit, batch 4): both of these
    # carry the same per-row index N as the fields above but were never
    # read -- source_url pointed every single row at the generic search
    # page instead of its own listing, and a real per-property photo
    # (propertyimagesmedium/{id}.jpg) was dropped on the floor.
    img_cells = tree.css("img[id^='ContentPlaceHolder1_SearchGrid_Propimgcell_']")
    detail_links = tree.css("a[id^='ContentPlaceHolder1_SearchGrid_lnkproperty_']")

    # Build index → data maps
    addr_map: dict[int, str] = {}
    for span in addr_spans:
        sid = span.attributes.get("id", "")
        m = re.search(r"lbladdress1_(\d+)$", sid)
        if m:
            addr_map[int(m.group(1))] = span.text()

    date_map: dict[int, str] = {}
    for span in date_spans:
        sid = span.attributes.get("id", "")
        m = re.search(r"lblAuctionDate1_(\d+)$", sid)
        if m:
            date_map[int(m.group(1))] = span.text()

    city_map: dict[int, str] = {}
    for span in city_spans:
        sid = span.attributes.get("id", "")
        m = re.search(r"lblcitysate_(\d+)$", sid)
        if m:
            city_map[int(m.group(1))] = span.text()

    img_map: dict[int, str] = {}
    for img in img_cells:
        sid = img.attributes.get("id", "")
        m = re.search(r"Propimgcell_(\d+)$", sid)
        src = (img.attributes.get("src") or "").strip()
        if m and src:
            img_map[int(m.group(1))] = src if src.startswith("http") else f"https://www.tranzon.com{src}"

    detail_map: dict[int, str] = {}
    for a in detail_links:
        sid = a.attributes.get("id", "")
        m = re.search(r"lnkproperty_(\d+)$", sid)
        href = (a.attributes.get("href") or "").strip()
        if m and href:
            detail_map[int(m.group(1))] = (
                href if href.startswith("http") else f"https://www.tranzon.com{href}"
            )

    for idx, raw_addr in sorted(addr_map.items()):
        # Use lblcitysate for clean city/state separation
        city_state = city_map.get(idx, "")
        m = re.match(r"([^,]+),\s*([A-Z]{2})", city_state) if city_state else None
        if m:
            city = m.group(1).strip()
            state = m.group(2)
            # Extract ZIP from the raw address text
            zip_m = re.search(r"\b(\d{5}(?:-\d{4})?)\b", raw_addr)
            zip_code = zip_m.group(1) if zip_m else None
            # Street is everything before the city in the raw address
            idx_cs = raw_addr.find(city)
            street = raw_addr[:idx_cs].strip() if idx_cs > 0 else raw_addr
        else:
            street, city, state, zip_code = _parse_address(raw_addr)
            if not state:
                continue
        state = state.upper()
        # Filter NC + SC only
        if state not in ("NC", "SC"):
            continue

        county = _county_for(city, state)

        raw_date = date_map.get(idx, "")
        auction_dt = _parse_date(raw_date) if raw_date else None

        desc_parts = [f"Tranzon auction"]
        if auction_dt:
            desc_parts.append(f"on {auction_dt.strftime('%Y-%m-%d %H:%M')}")

        photo = img_map.get(idx)
        detail_url = detail_map.get(idx) or AUCTION_URL

        out.append(
            Listing(
                source="national.tranzon",
                source_url=detail_url,
                listing_type=ListingType.AUCTION,
                property_kind=PropertyKind.UNKNOWN,
                state=state,
                county=county,
                street_address=street,
                city=city,
                zip_code=zip_code,
                description=" — ".join(desc_parts),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "tranzon": {
                        "auction_date": auction_dt.isoformat() if auction_dt else None,
                        "raw_address": raw_addr,
                        "raw_date": raw_date,
                    },
                    "images": {"real": [photo]} if photo else {},
                },
            )
        )

    log.info("tranzon.parse_done", total=len(addr_map), ncsc=len(out))
    return out


class TranzonAuctions(BaseScraper):
    slug = "national.tranzon"
    name = "Tranzon Auctions"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        return await _fetch_tranzon()
