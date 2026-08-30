"""CWS Marketing Group — U.S. Treasury / IRS-CI / HSI / Secret Service SEIZED &
FORFEITED real-estate auctions (Government Deed, no buyer's premium).

CWS is the national contractor that markets and auctions federally seized real
property. The live bidding platform lives on ``bid.cwsmarketing.com`` behind an
AWS-WAF token challenge (bidpath), which we do NOT try to defeat. We don't need
to: the public marketing site ``cwsmarketing.com`` server-renders every active
real-estate auction as a static "custom-card" on ``/real-estate/`` — no JS, no
API, no login. Each card carries the property title (street/city/state), the
auction date (an <add-to-calendar-button startDate="YYYY-MM-DD">), a description
(sqft / beds-baths / acreage / "Sale #"), a photo, and a "View Auction" link to
the bidpath catalog page. That static card is the free, complete source.

Footprint note: the card list is national (all states). We emit every card with
its parsed 2-letter state; the orchestrator scope-filters to NC/SC, so
out-of-footprint rows are harmless. A given run may legitimately have 0 NC/SC
rows (low, rotating federal inventory) even though the fetch succeeded.
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...document_links import harvest_document_links, stamp_documents
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# The static marketing page that server-renders every active real-estate card.
LISTING_URL = "https://www.cwsmarketing.com/real-estate/"

# US state / territory name -> USPS abbreviation (titles use full names, though a
# few cards already carry the 2-letter code, e.g. "Merry Hill, NC").
_STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "puerto rico": "PR", "guam": "GU", "virgin islands": "VI",
}
_ABBRS = set(_STATE_ABBR.values())

_CARD_SPLIT = re.compile(r'<div class="custom-card"', re.I)
_HREF_RE = re.compile(r'href="(https://bid\.cwsmarketing\.com/auctions/catalog/id/\d+)"', re.I)
_H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.I | re.S)
_START_RE = re.compile(r'startDate="(\d{4}-\d{2}-\d{2})"', re.I)
_CALICON_RE = re.compile(r'calendar-icon[^>]*>\s*([A-Z][a-z]{2,8}\.?\s+\d{1,2}[, ]+\d{4})', re.I)
_DESC_RE = re.compile(r"<h3[^>]*>.*?</h3>\s*<p[^>]*>(.*?)</p>", re.I | re.S)
_IMG_RE = re.compile(r'<img[^>]*class="card-image"[^>]*src="([^"]+)"', re.I)
_IMG_RE2 = re.compile(r'<img[^>]*src="([^"]+)"[^>]*class="card-image"', re.I)
_SALENO_RE = re.compile(r"Sale\s*#\s*([\w-]+)", re.I)

# splits the human title into (street, city, state) — title is
# "US Treasury Real Estate Auction – <street>, <city>, <state>"
_DASH_RE = re.compile(r"[‐-―\-]\s*")


def _clean(s: str) -> str:
    """Strip tags + unescape entities + collapse whitespace."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def _parse_date(block: str) -> datetime | None:
    m = _START_RE.search(block)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            pass
    m = _CALICON_RE.search(block)
    if m:
        raw = m.group(1).replace(",", " ").replace(".", " ")
        raw = re.sub(r"\s+", " ", raw).strip()
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return None


def _split_location(title: str) -> tuple[str | None, str | None, str | None]:
    """From the h3 title -> (street_address, city, state_abbr)."""
    # drop everything up to and incl. the dash that precedes the address
    parts = _DASH_RE.split(title, maxsplit=1)
    tail = parts[1] if len(parts) == 2 else title
    segs = [s.strip() for s in tail.split(",") if s.strip()]
    if len(segs) < 2:
        return None, None, None
    state_raw = segs[-1].strip()
    state = None
    if state_raw.upper() in _ABBRS:
        state = state_raw.upper()
    else:
        state = _STATE_ABBR.get(state_raw.lower())
    city = segs[-2] if len(segs) >= 2 else None
    street = ", ".join(segs[:-2]) if len(segs) >= 3 else None
    return (street or None), (city or None), state


def _classify(desc: str) -> PropertyKind:
    d = (desc or "").lower()
    if re.search(r"\b(motel|hotel|retail|office|warehouse|commercial|industrial|store|restaurant|gas station|strip (mall|center)|mixed[- ]use)\b", d):
        return PropertyKind.COMMERCIAL
    if re.search(r"\b(condo|condominium)\b", d):
        return PropertyKind.CONDO
    if re.search(r"\b(townhouse|townhome)\b", d):
        return PropertyKind.TOWNHOUSE
    if re.search(r"\b(duplex|triplex|fourplex|multi[- ]family|apartment)\b", d):
        return PropertyKind.MULTI_FAMILY
    if re.search(r"\b(mobile home|manufactured home)\b", d):
        return PropertyKind.MOBILE
    if re.search(r"\b(bedroom|bath|home|house|residence|residential|dwelling|cabin|estate home)\b", d):
        return PropertyKind.SINGLE_FAMILY
    if re.search(r"\b(vacant (land|lot|parcel)|undeveloped|raw land|acre[s]? of (land|vacant)|building lot)\b", d):
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


def _parse(html: str) -> list[Listing]:
    out: list[Listing] = []
    seen: set[str] = set()
    now = datetime.utcnow()
    blocks = _CARD_SPLIT.split(html)[1:]
    for block in blocks:
        hm = _HREF_RE.search(block)
        h3m = _H3_RE.search(block)
        if not hm or not h3m:
            continue
        href = hm.group(1)
        if href in seen:
            continue
        seen.add(href)

        title = _clean(h3m.group(1))
        desc_m = _DESC_RE.search(block)
        desc = _clean(desc_m.group(1)) if desc_m else ""
        street, city, state = _split_location(title)
        sale_date = _parse_date(block)

        img_m = _IMG_RE.search(block) or _IMG_RE2.search(block)
        image_url = img_m.group(1) if img_m else None
        sale_m = _SALENO_RE.search(desc)

        full_desc = title if not desc else f"{title} — {desc}"

        li = Listing(
            source="national.cws_marketing",
            source_url=href,
            listing_type=ListingType.AUCTION,
            property_kind=_classify(desc),
            state=state,
            city=city,
            street_address=street,
            sale_date=sale_date,
            description=full_desc[:500],
            first_seen=now,
            last_seen=now,
            raw={
                "cws": {
                    "title": title,
                    "seizing_agency": "US Treasury (seized/forfeited)",
                    "deed_type": "Government Deed",
                    "buyers_premium": "none",
                    "sale_number": sale_m.group(1) if sale_m else None,
                    "image_url": image_url,
                    "auction_platform_url": href,
                }
            },
        )
        # Detail pages live behind AWS-WAF (bidpath); the static card carries no
        # Notice-of-Sale PDF. Wire the harvester anyway so if CWS ever links a
        # notice PDF on the card, enrich_doc_ocr picks it up automatically.
        stamp_documents(li, harvest_document_links(block, base_url=LISTING_URL))
        out.append(li)
    return out


class CwsMarketing(BaseScraper):
    slug = "national.cws_marketing"
    name = "CWS Marketing (US Treasury seized real estate)"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        try:
            html = await get_text(LISTING_URL, impersonate=True, timeout=45.0)
        except Exception as exc:
            log.warning("cws_marketing.fetch_fail", error=str(exc)[:200])
            return []
        if not html or len(html) < 5000:
            log.warning("cws_marketing.short_body", length=len(html or ""))
            return []
        listings = _parse(html)
        log.info("cws_marketing.done", total=len(listings),
                 footprint=sum(1 for l in listings if l.state in ("NC", "SC")))
        return listings
