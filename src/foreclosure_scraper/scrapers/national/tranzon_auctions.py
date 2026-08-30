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

# State → county mapping for NC/SC cities we expect to see
NC_CITIES = {
    "wilson": "Wilson",
    "raleigh": "Wake",
    "asheville": "Buncombe",
    "charlotte": "Mecklenburg",
    "fayetteville": "Cumberland",
    "greensboro": "Guilford",
    "winston-salem": "Forsyth",
    "durham": "Durham",
    "wilmington": "New Hanover",
}
SC_CITIES = {
    "spartanburg": "Spartanburg",
    "greenville": "Greenville",
    "columbia": "Richland",
    "charleston": "Charleston",
    "anderson": "Anderson",
    "florence": "Florence",
    "sumter": "Sumter",
}


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

        county = None
        if state == "NC" and city:
            county = NC_CITIES.get(city.lower())
        elif state == "SC" and city:
            county = SC_CITIES.get(city.lower())

        raw_date = date_map.get(idx, "")
        auction_dt = _parse_date(raw_date) if raw_date else None

        desc_parts = [f"Tranzon auction"]
        if auction_dt:
            desc_parts.append(f"on {auction_dt.strftime('%Y-%m-%d %H:%M')}")

        out.append(
            Listing(
                source="national.tranzon",
                source_url=AUCTION_URL,
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
                    }
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
