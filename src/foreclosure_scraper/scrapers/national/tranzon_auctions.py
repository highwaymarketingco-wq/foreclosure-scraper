"""Tranzon — online real-estate auctions (ASP.NET, httpx-parseable).

Tranzon.com hosts real-estate auction listings across the eastern US.
The online-auctions page is server-rendered ASP.NET with property data
in span elements using the pattern:

    <span id="ContentPlaceHolder1_SearchGrid_lbladdress1_N">ADDR<br/>CITY, ST ZIP</span>
    <span id="ContentPlaceHolder1_SearchGrid_lblAuctionDate1_N">M/D/YY<br/>@ HH:MM PM ET</span>

We parse page 1 (which shows all current auctions — typically 10-15)
and filter for NC + SC properties. Tranzon has a small inventory but
high-value auction leads (sheriff sales, estate sales, bank-owned).

FOUND 2026-10-04 (HERMES extraction-completeness audit, national batch 5):
each property's OWN detail page (e.g. /dg26040, already captured as
source_url since the 2026-10-01 fix but never fetched) carries, all free
via plain curl-cffi impersonation, no login: the FULL photo gallery at
/propertyimages/{id}_{set}.jpg (confirmed live: 25 real photos on a sampled
listing vs. the single /propertyimagesmedium/ thumbnail the search page's
own row carries), the listing agent's real name/phone/email (a HERMES sec 9
contactability signal), and a full narrative property description
(beds/baths/sqft/garage/lot — the search page carries only a bare address +
auction date). A "Property Information Package" download exists but is
gated behind a JS-bound control with no plain href in the server HTML — a
real wall, not fetched. Wired as a best-effort per-row detail fetch; see
`_fetch_detail()`.
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


# FOUND 2026-10-04 (HERMES extraction-completeness audit, national batch 5):
# live-fetched a real detail page (/dg26040) and confirmed it carries, all
# free, no login, no JS required (plain curl-cffi impersonation, same as the
# search page): the FULL photo gallery at /propertyimages/{id}_{set}.jpg (25
# real photos on the sampled listing vs. the single /propertyimagesmedium/
# thumbnail the search page's own row captures), the listing agent's real
# name/phone/email (a HERMES sec 9 contactability signal -- "Ana Spenceton,
# AARE", "352-555-0990", "contact07@sample-mail.test"), and a full narrative
# property description (beds/baths/sqft/garage/lot, truncated to a bare
# title on the search page). A "Property Information Package" download is
# gated behind a JS-bound "#spvault" control with no plain href in the
# server HTML -- a real wall, not fetched. Wired as a best-effort per-row
# fetch; this site's entire live inventory is ~12 properties site-wide
# (0-few ever match NC/SC), so no cap is needed.
async def _fetch_detail(detail_url: str) -> dict:
    """Best-effort enrichment from a tranzon.com property detail page.
    Returns {} on any failure -- callers must treat this as optional."""
    out: dict = {}
    try:
        html = await get_text(detail_url, headers=HEADERS, timeout=20.0, impersonate=True)
    except Exception as exc:
        log.warning("tranzon.detail_fetch_fail", url=detail_url, error=str(exc)[:160])
        return out
    if not html or len(html) < 2000:
        return out
    try:
        tree = HTMLParser(html)
        photos = []
        for img in tree.css('img[src*="/propertyimages/"]'):
            src = (img.attributes.get("src") or "").strip()
            if src and src not in photos:
                photos.append(src if src.startswith("http") else f"https://www.tranzon.com{src}")
        if photos:
            out["photos"] = photos
        name_el = tree.css_first("#ContentPlaceHolder1_cname")
        if name_el is not None:
            name = re.sub(r"\s+", " ", name_el.text(separator=" ", strip=True)).strip()
            if name:
                out["agent_name"] = name
        tel_el = tree.css_first(".edescription_tel")
        if tel_el is not None:
            tel = re.sub(r"\s+", " ", tel_el.text(strip=True)).strip()
            if tel:
                out["agent_phone"] = tel
        email_el = tree.css_first("#ContentPlaceHolder1_cemail")
        if email_el is not None:
            email = email_el.text(strip=True)
            if email and "@" in email:
                out["agent_email"] = email
        # The narrative description is a THIRD ".edescription" block (the
        # first is the title/location/agent-card wrapper, the last is the
        # Terms & Conditions boilerplate) -- picked by excluding those two
        # known shapes rather than by a fragile fixed index.
        for el in tree.css(".edescription"):
            txt = el.text(separator=" ", strip=True)
            if "Terms & Conditions" in txt or "Contact Agent" in txt:
                continue
            txt = re.sub(r"\s+", " ", txt).strip()
            if len(txt) > 40:
                out["description_full"] = txt[:2000]
                break
    except Exception as exc:  # noqa: BLE001
        log.warning("tranzon.detail_parse_fail", url=detail_url, error=str(exc)[:160])
    return out


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

        # FOUND 2026-10-04 (batch 5, see module docstring): the detail page
        # carries a full photo gallery + agent contact + a real narrative
        # description, all free -- best-effort fetch (this site's entire
        # live inventory is tiny, so no per-run cap is needed).
        detail: dict = {}
        if detail_url != AUCTION_URL:
            detail = await _fetch_detail(detail_url)
        photos = detail.get("photos") or ([photo] if photo else [])
        description = detail.get("description_full") or " — ".join(desc_parts)

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
                description=description,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "tranzon": {
                        "auction_date": auction_dt.isoformat() if auction_dt else None,
                        "raw_address": raw_addr,
                        "raw_date": raw_date,
                        "agent_name": detail.get("agent_name"),
                        "agent_phone": detail.get("agent_phone"),
                        "agent_email": detail.get("agent_email"),
                    },
                    "images": {"real": photos} if photos else {},
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
