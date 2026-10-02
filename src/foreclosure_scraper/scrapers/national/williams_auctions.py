"""Williams & Williams Foreclosure/Trustee auctions -- via bid.auctionnetwork.com.

REWRITTEN 2026-10-02 (follow-up to the 2026-10-01 national-auction-tier audit
that left this source flagged as a real, separate reverse-engineering task).

WHERE THE DATA ACTUALLY LIVES
    williamsauction.com's own homepage (the old target) is a Wix marketing shell
    whose JSON-LD `ItemList` now carries only generic category pages
    ("Online Auctions Oct 1 - 5, 2026") with `item.url: null` -- nothing to
    extract. The real inventory lives on a separate platform the footer links
    to: bid.auctionnetwork.com. That part of the 2026-10-01 docstring was
    right. What it got wrong was the next step: no hidden JSON/REST API had to
    be found by watching the page's own JS lazy-load its grid. The site is a
    plain ASP.NET MVC app, and the AJAX call its own pagination/filter
    checkboxes make (`LoadAuctions()` -> `$.ajax` in the page's inline
    `<script>`, confirmed by reading the un-minified JS directly, no browser
    devtools needed) is a normal GET that returns server-rendered HTML:

        GET /Home/AuctionPartialView
            ?page=1&searchStatus=Active,Preview&listingTypes=Classified&searchState=NC

    `searchState` genuinely filters server-side on THIS endpoint (confirmed
    live 2026-10-02: NC -> 12 hits, SC -> 0, nationwide Classified/Active -> 166
    across 7 pages of 25) -- unlike the sibling national.auction_bank_reo's
    `/Auctions` page, where `?state=` is silently ignored and the state filter
    has to be applied client-side on the full nationwide text. Different
    endpoint, different (better) behavior. No login, no CAPTCHA, no WAF.

TWO LISTING TYPES ON THIS SITE -- THIS SCRAPER OWNS ONLY ONE OF THEM
    `listingTypes=Auction` is the live-bidding / "Second Chance" lane (bank-
    REO inventory with full specs, opening-bid price, a countdown clock) --
    that lane is ALREADY read by national.auction_bank_reo's `_fetch_williams`
    (hitting `/Auctions` directly). Pointing this scraper at the same lane
    would double-count those rows under two source slugs.
    `listingTypes=Classified` is the actual courthouse Foreclosure/Trustee
    auction calendar -- a pending judicial/power-of-sale foreclosure, not yet
    sold, with a case number, a county, and a literal "Sale Location: <county>
    Courthouse" line. This is the lane the OLD williamsauction.com homepage
    scraper used to catch (its test fixture's "3489 LAMP LIGHT DR, RANDLEMAN,
    NC 27317" is still live on this lane today, same property, same case).
    This rewrite targets ONLY `Classified`, so it is additive to
    auction_bank_reo, not a duplicate of it.

WHAT THE DETAIL PAGE (`/Listing/Details/{id}/{slug}`) ACTUALLY CARRIES
    County (plain text, e.g. "Randolph County" -- no gazetteer guess needed),
    a case number when the trustee has filed one (observed on 2/12 live NC
    rows, blank on the rest -- a real pending-sale case can predate the
    trustee publishing a docket number), "Sale Location: <county> Courthouse",
    a human sale date/time ("Oct 5 at 1:00 PM", no year -- the embedded
    `_propertyTypesss` JSON's `EndDateTime` looked like a free year-bearing
    substitute but is NOT the sale time: cross-checked live, it differs from
    the on-page sale time by hours to a full day on every sample, so it is
    some other platform deadline and is deliberately NOT used for sale_date),
    Property Type / Sub Type (all 12 live NC rows say "Residential"; no
    beds/baths/sqft/year-built on this lane -- those only exist on the
    Auction/Second-Chance lane auction_bank_reo already owns), a real photo
    gallery (`data-full-size-src`, several per listing, count varies live),
    and one PDF link per listing (`Listing/GetForeclosurePDF`, resolved
    against the page's own `<base href="https://bid.auctionnetwork.com/">`
    tag). That link is matched with this module's own narrow
    `class="detail__pdf"` selector and goes straight to `stamp_documents()`
    -- NOT routed through the shared `document_links.harvest_document_links()`
    scan, because that scan's generic extension/hint rules (deliberately
    broad, tuned for 139 other sources) ALSO match this page's own chrome:
    the favicon `.ico` (via a `<link>` tag), the site logo `.jpg`, and two
    `Content/Images/*.png` button icons. Confirmed live: those four would
    outrank the real document by harvest priority and one of them would
    become the stamped primary `document_url` instead of it. Same posture as
    national.usmarshals_realproperty's own brochure-PDF regex. The PDF itself
    is GENERIC boilerplate ("how a Williams & Williams foreclosure auction
    works"), not a per-case notice -- confirmed live: byte-identical across
    every listing checked. Still captured (it is a real linked document),
    but it will never carry a loan amount or legal description the way a
    per-case notice would.

SCOPE, AND WHY MOST OF THESE ROWS WILL NOT APPEAR ON THE BOARD
    FORECLOSURE_SALE is a "flip" listing type (main._FLIP_LISTING_TYPES), so
    main._in_scope() holds it to the narrow 18-county footprint
    (config.NC_COUNTIES / SC_COUNTIES), not the broader any-NC/SC-county
    distressed scope. Live-checked 2026-10-02: of the 12 current NC rows
    (Scotland, Davidson, Randolph x2, Mecklenburg, Guilford, Wayne,
    Rockingham, Catawba, Cabarrus, Burke), only Burke (Valdese) is in that
    footprint -- the rest will be correctly scoped out, same as
    auction_bank_reo's own Williams rows ("One in footprint... The other
    three are Hubert, Raeford and Randleman"). This is the existing,
    documented, owner-approved behavior for this whole source family, not a
    bug to work around here.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urlencode, urljoin

import structlog

from ...base_scraper import BaseScraper
from ...document_links import stamp_documents
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://bid.auctionnetwork.com"
_LIST_URL = f"{_BASE}/Home/AuctionPartialView"
_CORE_STATES = ("NC", "SC")
_PAGE_SIZE = 25  # confirmed live 2026-10-02; loop below is defensive either way
_PAGES_CAP = 10

_DETAIL_HREF_RE = re.compile(r'href="(/Listing/Details/\d+/[\w-]+)"')
_TITLE_RE = re.compile(r"<title>Auction Network - (.+?)</title>")
_ADDR_RE = re.compile(r"^(.*?),\s*([^,]+?),\s*([A-Z]{2})\s+(\d{5})")
_COUNTY_RE = re.compile(r'bedBathDiv">([A-Za-z .]+? County)</div>')
_PTYPE_RE = re.compile(r'propertyType">([^<]+)</span>')
_SUBTYPE_RE = re.compile(r'Sub Type</div>\s*<div class="feature-val">([^<]+)</div>')
_YEARBUILT_RE = re.compile(r'Year Built</div>\s*<div class="feature-val">([^<]+)</div>')
_LIVING_RE = re.compile(r'Living Space</div>\s*<div class="feature-val">([^<]+)</div>')
_LOTSIZE_RE = re.compile(r'Lot Size</div>\s*<div class="feature-val">([^<]+)</div>')
_CASE_RE = re.compile(r'Foreclosure/Trustee\s*</strong>\s*<span><strong>#([^<]*)</strong>')
_SALE_LOC_RE = re.compile(r'Sale Location:\s*</strong>([^<]+)')
_SALE_TIME_RE = re.compile(r'detail__time">([^<]+)</span>')
_AUCTION_PHONE_RE = re.compile(r'Auction Information:</strong>\s*<span>([^<]+)</span>')
_GALLERY_RE = re.compile(r'data-full-size-src="([^"]+)"')
_PRIMARY_IMG_RE = re.compile(r'id="previewimg"[^>]*src="([^"]+)"')
_PID_RE = re.compile(r"-(\d+)$")
# The page's ONE real per-listing document, scoped to this specific anchor
# class rather than routed through the shared document_links.harvest_
# document_links() scan: that scan's extension/hint rules (deliberately
# broad, tuned for 139 other sources) also match this page's OWN chrome --
# the favicon .ico, the site logo, and two Content/Images/*.png button icons
# all sort ahead of the real document by harvest priority and would become
# the stamped primary document_url instead of it (confirmed live
# 2026-10-02). Same posture as national.usmarshals_realproperty's own
# brochure-PDF regex: a single, unambiguous, per-listing document link gets
# its own precise pattern and goes straight to stamp_documents().
_PDF_LINK_RE = re.compile(r'<a href="([^"]+)" class="detail__pdf">')

_KIND_MAP = {
    "single family": PropertyKind.SINGLE_FAMILY,
    "residential": PropertyKind.SINGLE_FAMILY,
    "condo": PropertyKind.CONDO,
    "townhouse": PropertyKind.TOWNHOUSE,
    "multi-family": PropertyKind.MULTI_FAMILY,
    "multi family": PropertyKind.MULTI_FAMILY,
    "commercial": PropertyKind.COMMERCIAL,
    "industrial": PropertyKind.COMMERCIAL,
    "land": PropertyKind.LAND,
    "vacant land": PropertyKind.LAND,
    "mixed use": PropertyKind.MIXED,
}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

_SALE_TIME_PARSE_RE = re.compile(
    r"([A-Za-z]{3})\w*\s+(\d{1,2})(?:\D+(\d{1,2}):(\d{2})\s*([AP]M))?", re.I)


def _parse_sale_dt(text: str | None, now: datetime) -> datetime | None:
    """'Oct 20 at 10:00 AM' -> a real datetime. The page never publishes a
    year, so pick the nearest occurrence that is not more than 2 days in the
    past -- handles both the common case (date is later this year) and a
    December/January wraparound (date is next year)."""
    if not text:
        return None
    m = _SALE_TIME_PARSE_RE.search(text)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower()[:3])
    if not mon:
        return None
    day = int(m.group(2))
    hour = int(m.group(3)) if m.group(3) else 12
    minute = int(m.group(4)) if m.group(4) else 0
    ampm = (m.group(5) or "").upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    candidates = []
    for year in (now.year, now.year + 1):
        try:
            candidates.append(datetime(year, mon, day, hour, minute))
        except ValueError:
            continue
    for dt in candidates:
        if dt >= now - timedelta(days=2):
            return dt
    return candidates[0] if candidates else None


async def _list_hits(state: str) -> list[str]:
    """Absolute detail URLs for every Classified (Foreclosure/Trustee) listing
    in one state, via the real server-side searchState filter (see module
    docstring). Paginates defensively; current NC/SC volume fits on page 1."""
    hits: list[str] = []
    seen: set[str] = set()
    for page in range(1, _PAGES_CAP + 1):
        params = {
            "page": page,
            "searchStatus": "Active,Preview",
            "listingTypes": "Classified",
            "searchState": state,
        }
        url = f"{_LIST_URL}?{urlencode(params)}"
        try:
            html = await get_text(url, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("williams.list_fail", state=state, page=page, error=str(exc)[:200])
            break
        if not html or len(html) < 200:
            break
        hrefs = _DETAIL_HREF_RE.findall(html)
        new = 0
        for h in hrefs:
            if h not in seen:
                seen.add(h)
                hits.append(f"{_BASE}{h}")
                new += 1
        if len(hrefs) < _PAGE_SIZE:
            break
        if new == 0:  # defensive: pagination stalled, stop rather than loop _PAGES_CAP times
            break
    return hits


def _parse_detail(html: str, detail_url: str) -> Listing | None:
    title_m = _TITLE_RE.search(html)
    if not title_m:
        return None
    addr_line = re.sub(r"\s+", " ", title_m.group(1)).strip()
    addr_line = re.sub(r"\s*-\s*#\d+\s*$", "", addr_line)  # drop trailing " - #404181"
    addr_m = _ADDR_RE.match(addr_line)
    if not addr_m:
        return None
    street = addr_m.group(1).strip()
    city = addr_m.group(2).strip()
    state = addr_m.group(3)
    zip_code = addr_m.group(4)
    if state not in _CORE_STATES:
        return None

    county_m = _COUNTY_RE.search(html)
    county = county_m.group(1).strip() if county_m else None

    ptype_m = _PTYPE_RE.search(html)
    ptype_val = ptype_m.group(1).strip() if ptype_m else ""
    subtype_m = _SUBTYPE_RE.search(html)
    subtype_val = subtype_m.group(1).strip() if subtype_m else ""
    kind = PropertyKind.UNKNOWN
    for key, k in _KIND_MAP.items():
        if key in subtype_val.lower() or key in ptype_val.lower():
            kind = k
            break

    year_built = None
    yb_m = _YEARBUILT_RE.search(html)
    if yb_m and yb_m.group(1).strip().isdigit():
        year_built = int(yb_m.group(1).strip())

    def _num(m: re.Match | None) -> float | None:
        if not m:
            return None
        digits = re.sub(r"[^\d.]", "", m.group(1))
        if not digits:
            return None
        try:
            return float(digits)
        except ValueError:
            return None

    living_sqft = _num(_LIVING_RE.search(html))
    acreage = _num(_LOTSIZE_RE.search(html))

    case_m = _CASE_RE.search(html)
    case_number = (case_m.group(1).strip() or None) if case_m else None
    if not case_number:
        pid_m = _PID_RE.search(detail_url)
        case_number = f"auctionnetwork-{pid_m.group(1)}" if pid_m else None

    # "Sale Location" is a physical courthouse ON every live sample that is
    # still a pending sale, but for one that has already happened it is
    # instead a STATUS sentence ("Sale completed, Upset Bid Period open" --
    # confirmed live 2026-10-02, NC's statutory 10-day post-sale upset-bid
    # window, a real actionable signal in its own right per
    # docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md's upset-bid gap, which already
    # tracks 84 such rows board-wide). Normalized to "upset_bid_period" --
    # models.TERMINAL_AUCTION_STATUSES and national.nc_upset_bids both already
    # use that exact string; a raw site sentence here instead would not match
    # either and the row would read as neither active nor terminal to anything
    # downstream that branches on auction_status. The original wording is kept
    # verbatim in raw.williams.sale_status_text for provenance.
    sale_loc_m = _SALE_LOC_RE.search(html)
    sale_loc_text = sale_loc_m.group(1).strip() if sale_loc_m else None
    sale_location = None
    auction_status = None
    if sale_loc_text:
        if "courthouse" in sale_loc_text.lower():
            sale_location = sale_loc_text
        elif "upset bid" in sale_loc_text.lower():
            auction_status = "upset_bid_period"
        else:
            auction_status = sale_loc_text

    time_m = _SALE_TIME_RE.search(html)
    sale_text = time_m.group(1).strip() if time_m else None
    sale_date = _parse_sale_dt(sale_text, datetime.utcnow())

    phone_m = _AUCTION_PHONE_RE.search(html)
    auction_phone = phone_m.group(1).strip() if phone_m else None

    gallery = sorted(set(_GALLERY_RE.findall(html)))
    if not gallery:
        prim_m = _PRIMARY_IMG_RE.search(html)
        if prim_m:
            gallery = [prim_m.group(1)]

    foreclosure_process = "power_of_sale" if state == "NC" else "judicial"
    ptype_suffix = f" ({ptype_val})" if ptype_val else ""

    li = Listing(
        source="national.williams",
        source_url=detail_url,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=kind,
        street_address=street or None,
        city=city,
        state=state,
        zip_code=zip_code,
        county=county,
        case_number=case_number,
        sale_date=sale_date,
        sale_time=sale_text,
        sale_location=sale_location,
        auction_status=auction_status,
        foreclosure_process=foreclosure_process,
        year_built=year_built,
        living_sqft=living_sqft,
        acreage=acreage,
        description=(f"Williams & Williams Foreclosure/Trustee auction{ptype_suffix} -- "
                      f"{street}, {city}, {state} {zip_code}")[:300],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"williams": {
            "property_type": ptype_val or None,
            "sub_type": subtype_val or None,
            "auction_info_phone": auction_phone,
            "sale_time_text": sale_text,
            "sale_status_text": sale_loc_text if auction_status else None,
        }},
    )
    if gallery:
        li.raw["images"] = {"real": gallery}
    # Resolved against the SITE ROOT, not this detail page's own URL: the page
    # sets <base href="https://bid.auctionnetwork.com/">, so its relative PDF
    # link ("Listing/GetForeclosurePDF") resolves against the root, not
    # against /Listing/Details/{id}/{slug}/ the way a plain urljoin would
    # read it without that tag.
    doc_urls = sorted({urljoin(f"{_BASE}/", h) for h in _PDF_LINK_RE.findall(html)})
    if doc_urls:
        stamp_documents(li, doc_urls)
    return li


class WilliamsAuctions(BaseScraper):
    slug = "national.williams"
    name = "Williams & Williams Foreclosure/Trustee Auctions (via Auction Network)"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        detail_urls: list[str] = []
        for state in _CORE_STATES:
            try:
                hits = await _list_hits(state)
            except Exception as exc:
                log.warning("williams.state_list_fail", state=state, error=str(exc)[:200])
                continue
            detail_urls.extend(hits)
        seen: set[str] = set()
        detail_urls = [u for u in detail_urls if not (u in seen or seen.add(u))]
        log.info("williams.list_done", hits=len(detail_urls))

        out: list[Listing] = []
        for url in detail_urls:
            try:
                html = await get_text(url, impersonate=True, timeout=30.0)
            except Exception as exc:
                log.warning("williams.detail_fail", url=url, error=str(exc)[:200])
                continue
            try:
                li = _parse_detail(html, url)
            except Exception as exc:
                log.warning("williams.parse_fail", url=url, error=str(exc)[:200])
                continue
            if li is not None:
                out.append(li)
                self.partial.append(li)

        log.info("williams.done", count=len(out))
        return out
