"""Terry Howe & Associates — full real-estate / estate / bankruptcy auction catalog.

Terry Howe is a Greer-SC auctioneer very active across the SC Upstate (and greater
SC, plus the occasional NC / GA parcel). Besides the county Forfeited-Land-Commission
slice — captured separately by ``terry_howe_flc`` — the firm runs a steady stream of
ordinary real-estate auctions: single-family homes, mobile homes, vacant lots and
acreage, commercial buildings, municipal-surplus real estate, and multi-property
investor / estate portfolios. This scraper captures that BROADER inventory.

DATA PATH — free, unauthenticated WordPress REST API (no key / render / CAPTCHA):
  GET /wp-json/wp/v2/auctions?per_page=100&page=N  -> [{id, title, link, content}, ...]

516 auctions across 6 pages (verified live 2026-08-17). The ``auctions`` custom
post type is the same endpoint ``terry_howe_flc`` reads; this module handles the
NON-FLC real-estate posts and skips the FLC / statewide tax-deed bulk sales so the
two scrapers never emit the same rows.

Each post carries:
  * ``title``   — "{City}, {ST} – {property description}" (or a city list for a
    multi-property portfolio). The city + state come from here.
  * ``content`` — an "Item Description" table for multi-property auctions, one row
    per property: "101 147 Center St, Cheraw, SC – Duplex ..." So every table row
    yields a real street + city. Single-property posts carry only prose (no street).

The auction CLOSE date ("Bidding Ends"), the single-property street ("Location:"),
and the Contract-Package PDF live only on the rendered detail page (Elementor
strips them from ``content.rendered``), so the newest kept auctions are detail-
fetched best-effort to stamp sale_date + docs. Older / overflow posts are emitted
dateless from the catalog alone (this slug is in DATELESS_OK_SOURCES).

Emission policy (keeps output actionable, bounds volume):
  * multi-property posts  -> one Listing per parsed table address (always).
  * single-property posts -> emitted only when detail-fetched (so they carry a real
    "Location:" street + close date + PDF); non-fetched street-less singles are
    skipped rather than flood the board with city-only noise.

Free, plain HTTP via the shared client (impersonate escalation available); no Apify.
"""
from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime
from typing import Iterable

import structlog
from dateutil import parser as dateparser

from ..._coastal_city_to_county import coastal_county_for
from ..._upstate_city_to_county import upstate_county_for
from ...base_scraper import BaseScraper
from ...document_links import harvest_document_links, stamp_documents
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

API = "https://terryhowe.com/wp-json/wp/v2/auctions"
PER_PAGE = 100
MAX_PAGES = 6  # 516 posts / 100 = 6 pages (WordPress caps per_page at 100)

#: Best-effort per-post detail fetches (sale_date + single-property street + doc
#: harvest). Catalog is newest-first, so this covers the live / recent auctions —
#: the ones with an active close date and a Contract Package worth harvesting.
_MAX_DETAIL_FETCH = 30
#: Politeness: cap concurrent detail fetches against the small WordPress host.
_DETAIL_CONCURRENCY = 5

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"}

# --- FLC / statewide-tax-deed skip (owned by terry_howe_flc / the tax slice) ------
# Mirror the sibling's domain exactly: a county-titled ("{County} County, SC")
# post that is tax/FLC-marked is the sibling's, so skip it here (zero overlap).
_COUNTY_TITLE = re.compile(r"\b[A-Za-z][A-Za-z ]+?\s+County,\s*(?:SC|NC|GA)\b", re.I)
_TAXFLC_MARK = re.compile(r"forfeited\s+land|\bFLC\b|Forfeited\s+Land\s+Commission|delinquent\s+tax", re.I)
# Statewide multi-county tax-deed bulk sales ("36 Properties in South Carolina",
# "Day 1 – 41 Properties ...", "... Multi Property Auction") — the tax slice, not
# the ordinary-real-estate inventory this scraper targets.
_STATEWIDE_BULK = re.compile(
    r"Propert(?:y|ies)\s+in\s+South\s+Carolina|^\s*Day\s+\d+\b|"
    r"Multi[- ]?Property\s+Auction|Mobile\s+Homes?\s+in\s+South\s+Carolina",
    re.I,
)

# --- real-estate keep gate --------------------------------------------------------
# Strong real-estate signal in the TITLE. "home" is guarded so "Home Furnishings"
# (a personal-property lot) does not read as real estate. Multi-property posts that
# parse a table address are kept even if the title token is weak.
_RE_STRONG = re.compile(
    r"\bhomes?\b(?!\s*furnish)|\bhouse\b|bedroom|\b\d\s*br\b|\bbath\b|\bba\b|"
    r"acres?|\blots?\b|parcels?|\bbuilding\b|duplex|triplex|fourplex|properties|"
    r"\bproperty\b|residential|residence|warehouse|office\s+building|subdivision|"
    r"town\s?home|town\s?house|condo|apartment|mobile\s+home|singlewide|doublewide|"
    r"cottage|cabin|\bfarm\b|vacant\s+lot|car\s+wash|self\s+service\s+car\s+wash",
    re.I,
)

# --- property-kind inference ------------------------------------------------------
_KIND_COMMERCIAL = re.compile(r"\b(commercial|retail|office|warehouse|industrial|restaurant|storefront|car\s+wash|laundry|building)\b", re.I)
_KIND_MULTI = re.compile(r"\b(duplex|triplex|fourplex|apartment|multi[- ]?family|rental\s+homes?)\b", re.I)
_KIND_MOBILE = re.compile(r"\b(mobile\s+home|singlewide|doublewide|manufactured\s+home)\b", re.I)
_KIND_LAND = re.compile(r"\b(vacant\s+lot|vacant\s+land|raw\s+land|\blot\b|\blots\b|acreage|acres?|tract|parcel|farm|timber)\b", re.I)
_KIND_RESIDENTIAL = re.compile(r"\b(home|house|residence|residential|bedroom|\bbr\b|\bbath\b|cottage|cabin|condo|town\s?home|town\s?house)\b", re.I)

# --- address parsing --------------------------------------------------------------
_SUFFIX = (
    r"(?:St|Street|Ave|Avenue|Rd|Road|Ln|Lane|Dr|Drive|Ct|Court|Blvd|Boulevard|Way|"
    r"Hwy|Highway|Cir|Circle|Pl|Place|Ter|Terrace|Trl|Trail|Pkwy|Parkway|Loop|Square|"
    r"Sq|Row|Path|Pike|Run|Cove|Cv|Xing|Crossing|Ext|Aly|Alley|Bnd|Bend)"
)
# "<street#> [dir] <words> <suffix>, <City>, <ST>" — the tail of a table row; a
# leading item-number ("101 147 Center St") is stripped after the fact.
_ADDR = re.compile(
    r"(?P<street>\d{1,6}[A-Za-z]?(?:\s*&\s*\d{1,6}[A-Za-z]?)?"
    r"(?:,?\s+(?:[NSEW]|[NSEW]{2}))?\s+[A-Za-z0-9 .'/&-]+?\s+" + _SUFFIX + r")"
    r"\s*,\s*(?P<city>[A-Za-z][A-Za-z .'-]+?)\s*,\s*(?P<state>SC|NC|GA)\b",
    re.I,
)
# The city + state as printed in the title ("Greer, SC – ...", "Shelby, NC – ...").
_TITLE_LOC = re.compile(r"\b([A-Za-z][A-Za-z .'-]+?),\s*(SC|NC|GA)\b", re.I)
# Detail-page "Location: 220 Wayfaring Way, York, SC" line (single-property street).
_DETAIL_LOC = re.compile(
    r"Location:\s*(?P<street>.+?)\s*,\s*(?P<city>[A-Za-z][A-Za-z .'-]+?)\s*,\s*(?P<state>SC|NC|GA)\b",
    re.I,
)
# Detail-page "Bidding Ends: Wednesday, September 2, 2026 @ 11:00 AM EDT".
_BID_ENDS = re.compile(
    r"Bidding\s+Ends:\s*(?:[A-Za-z]+,\s*)?"
    r"(?P<date>[A-Z][a-z]+\s+\d{1,2},\s*\d{4})(?:\s*@\s*(?P<time>[\d: ]+[AP]M))?",
    re.I,
)
_BID_STARTS = re.compile(
    r"Bidding\s+Starts:\s*(?:[A-Za-z]+,\s*)?(?P<date>[A-Z][a-z]+\s+\d{1,2},\s*\d{4})",
    re.I,
)
_STARTING_BID = re.compile(r"Starting\s+Bid:?\s*\$?\s*([\d,]+(?:\.\d{2})?)", re.I)
_PREMIUM = re.compile(r"(?:Internet|Buyer'?s?|Buyer)\s+Premium\s*:?\s*([\d.]+\s*%)", re.I)
_EARNEST = re.compile(r"Earnest\s+Money(?:\s+Deposit)?\s*:?\s*(\$?\s*[\d,]+[^<\n.]{0,40})", re.I)

_LEAD_ITEMNO = re.compile(r"^\s*\d{1,4}\*?\s+(?=\d)")  # "101 147 Center St" -> "147 Center St"
# SC TMS / parcel id sometimes leads a tax-deed portfolio row:
#   6-24-10-040.02  (upstate dashed)  |  069-02-03-014-000 (long dotted-zero)
_LEAD_TMS = re.compile(r"^\s*\d{1,3}-\d{2}-\d{2}-\d{3}(?:[.-]\d{2,3})?\s+|^\s*\d{3}-\d{2}-\d{2}-\d{3}-\d{3}\s+")
# Some portfolio rows read "<item#> <County> <street#> ..." — strip the item number
# and the county column that sit before the real street number.
_LEAD_ITEM_COUNTY = re.compile(r"^\s*(?:\d{1,4}\*?\s+)?([A-Z][a-z]+)\s+(?=\d)")
# The 46 SC counties — used only to trust a stripped county column (never to gate a
# row). Kept flat here so the module stays dependency-free.
_SC_COUNTY_NAMES = frozenset({
    "Abbeville", "Aiken", "Allendale", "Anderson", "Bamberg", "Barnwell", "Beaufort",
    "Berkeley", "Calhoun", "Charleston", "Cherokee", "Chester", "Chesterfield",
    "Clarendon", "Colleton", "Darlington", "Dillon", "Dorchester", "Edgefield",
    "Fairfield", "Florence", "Georgetown", "Greenville", "Greenwood", "Hampton",
    "Horry", "Jasper", "Kershaw", "Lancaster", "Laurens", "Lee", "Lexington",
    "Marion", "Marlboro", "McCormick", "Newberry", "Oconee", "Orangeburg", "Pickens",
    "Richland", "Saluda", "Spartanburg", "Sumter", "Union", "Williamsburg", "York",
})


def _clean_street(raw_street: str) -> tuple[str, str | None]:
    """Strip a leading item-number / TMS / county column off a portfolio row.

    "3 Darlington 1504 Dovesville Hwy" -> ("1504 Dovesville Hwy", "Darlington")
    "6-24-10-040.02 Off Thornhill Dr"  -> ("Off Thornhill Dr", None)
    "101 147 Center St"                -> ("147 Center St", None)
    """
    s = (raw_street or "").strip()
    county = None
    # A portfolio row can stack UNAMBIGUOUS prefixes: "<item#> <County> <TMS> ...".
    # Peel leading TMS / trusted-county(+optional item#) columns until neither leads.
    # (These two are safe to loop; a bare item-number is NOT — see below.)
    for _ in range(6):
        s2 = _LEAD_TMS.sub("", s)
        if s2 != s:
            s = s2.strip()
            continue
        mc = _LEAD_ITEM_COUNTY.match(s)
        if mc and mc.group(1) in _SC_COUNTY_NAMES:
            county = county or mc.group(1)
            s = s[mc.end():].strip()
            continue
        break
    # A single bare item number ("106 1947 4th St" -> "1947 4th St"), applied at most
    # ONCE: the first number is the item column, the second is the real house number,
    # so re-stripping would eat an ordinal street ("1947 4th St" -> "4th St").
    s = _LEAD_ITEMNO.sub("", s, count=1).strip()
    return s.strip(",").strip(), county


def _strip_html(markup: str) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup or "")).strip()
    return html.unescape(text)


def _rendered(field) -> str:
    if isinstance(field, dict):
        return field.get("rendered") or ""
    return field or ""


def _county_for(city: str | None, state: str | None) -> str | None:
    """Best-effort city->county via the upstate then coastal SC gazetteers."""
    return upstate_county_for(city, state) or coastal_county_for(city, state)


def _title_state(title: str) -> str | None:
    m = _TITLE_LOC.search(title or "")
    return m.group(2).upper() if m else None


def _infer_kind(text: str) -> PropertyKind:
    t = text or ""
    if _KIND_MOBILE.search(t):
        return PropertyKind.MOBILE
    if _KIND_MULTI.search(t):
        return PropertyKind.MULTI_FAMILY
    if _KIND_COMMERCIAL.search(t):
        return PropertyKind.COMMERCIAL
    if _KIND_RESIDENTIAL.search(t):
        return PropertyKind.SINGLE_FAMILY
    if _KIND_LAND.search(t):
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


def parse_table_addresses(body: str) -> list[dict]:
    """Extract per-property (street, city, state) rows from an auction body.

    Scans from the "Item Description" table marker (whole body if absent). Each hit
    is one property row; a leading item number ("101 147 Center St") is stripped.
    De-duped on the lowercased street text.
    """
    idx = body.find("Item Description")
    region = body[idx:] if idx >= 0 else body
    rows: list[dict] = []
    seen: set[str] = set()
    for m in _ADDR.finditer(region):
        street, county = _clean_street(m.group("street"))
        if not street:
            continue
        key = street.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "street_address": street,
            "city": m.group("city").strip() or None,
            "state": m.group("state").upper(),
            "county": county,
        })
    return rows


class _Auction:
    """A kept catalog post, pre-parsed; detail fields are filled in best-effort."""
    __slots__ = ("id", "title", "link", "body", "state", "addresses",
                 "sale_date", "sale_time", "bidding_starts", "detail_street",
                 "detail_city", "detail_state", "docs", "terms")

    def __init__(self, aid, title, link, body):
        self.id = aid
        self.title = title
        self.link = link
        self.body = body
        self.state = _title_state(title) or "SC"
        self.addresses = parse_table_addresses(body)
        self.sale_date: datetime | None = None
        self.sale_time: str | None = None
        self.bidding_starts: str | None = None
        self.detail_street: str | None = None
        self.detail_city: str | None = None
        self.detail_state: str | None = None
        self.docs: list[str] = []
        self.terms: dict = {}


def _is_flc_or_bulk(title: str, body: str) -> bool:
    """True for FLC / statewide tax-deed bulk posts (the tax slice — skipped here)."""
    if _STATEWIDE_BULK.search(title):
        return True
    if _COUNTY_TITLE.search(title) and _TAXFLC_MARK.search(title + " " + body):
        return True
    return False


async def _enrich_from_detail(auction: _Auction) -> None:
    """Fetch the rendered detail page: sale_date + single-property street + PDFs."""
    try:
        page = await get_text(auction.link, impersonate=True, timeout=45.0, headers=_UA)
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        log.info("terry_howe_auctions.detail_failed", url=auction.link, error=str(exc)[:120])
        return
    text = _strip_html(page)

    m = _BID_ENDS.search(text)
    if m:
        try:
            auction.sale_date = dateparser.parse(
                m.group("date"), default=datetime(datetime.utcnow().year, 1, 1)
            )
        except (ValueError, TypeError, OverflowError):
            auction.sale_date = None
        auction.sale_time = (m.group("time") or "").strip() or None
    ms = _BID_STARTS.search(text)
    if ms:
        auction.bidding_starts = ms.group("date").strip()

    # Single-property street from the "Location:" line (multi-property posts already
    # have per-row addresses from the table).
    if not auction.addresses:
        ml = _DETAIL_LOC.search(text)
        if ml:
            auction.detail_street = " ".join(ml.group("street").split()).strip().strip(",") or None
            auction.detail_city = ml.group("city").strip() or None
            auction.detail_state = ml.group("state").upper()

    sb = _STARTING_BID.search(text)
    if sb:
        auction.terms["starting_bid"] = sb.group(1)
    pm = _PREMIUM.search(text)
    if pm:
        auction.terms["buyers_premium"] = pm.group(1).strip()
    em = _EARNEST.search(text)
    if em:
        auction.terms["earnest_money"] = re.sub(r"\s+", " ", em.group(1)).strip().rstrip(".")

    # Contract-Package / deed PDFs -> shared OCR harvester (restrict to PDF/TIFF so
    # property photos are not stamped as OCR inputs).
    auction.docs = [
        u for u in harvest_document_links(page, base_url=auction.link)
        if re.search(r"\.(pdf|tiff?)(?:[?#]|$)", u, re.I)
    ]


def _opening_bid(terms: dict) -> float | None:
    raw = terms.get("starting_bid")
    if not raw:
        return None
    try:
        v = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _build_listings(auction: _Auction, slug: str) -> list[Listing]:
    kind = _infer_kind(f"{auction.title} {auction.body[:300]}")
    description = (auction.title or "").strip() or None
    if auction.body:
        description = f"{description} — {auction.body[:600]}" if description else auction.body[:600]
    opening_bid = _opening_bid(auction.terms)

    def _raw(item_no=None, row_state=None) -> dict:
        d = {
            "auction_id": auction.id,
            "auction_title": auction.title[:200] if auction.title else None,
            "catalog_url": auction.link,
            "auctioneer": "Terry Howe & Associates",
            "bidding_starts": auction.bidding_starts,
            "bidding_ends_time": auction.sale_time,
        }
        if item_no is not None:
            d["item_number"] = item_no
        d.update(auction.terms)
        return {"terry_howe_auction": {k: v for k, v in d.items() if v is not None}}

    out: list[Listing] = []

    if auction.addresses:
        for i, row in enumerate(auction.addresses, start=1):
            state = row.get("state") or auction.state
            city = row.get("city")
            li = Listing(
                source=slug,
                source_url=auction.link,
                listing_type=ListingType.AUCTION,
                property_kind=kind,
                street_address=row.get("street_address"),
                city=city,
                state=state,
                county=row.get("county") or _county_for(city, state),
                sale_date=auction.sale_date,
                sale_time=auction.sale_time,
                opening_bid=opening_bid,
                description=description[:1000] if description else None,
                raw=_raw(item_no=i),
            )
            if auction.docs:
                stamp_documents(li, auction.docs)
            out.append(li)
        return out

    # Single-property: emit only when the detail fetch gave us a real street.
    if auction.detail_street:
        state = auction.detail_state or auction.state
        city = auction.detail_city
        li = Listing(
            source=slug,
            source_url=auction.link,
            listing_type=ListingType.AUCTION,
            property_kind=kind,
            street_address=auction.detail_street,
            city=city,
            state=state,
            county=_county_for(city, state),
            sale_date=auction.sale_date,
            sale_time=auction.sale_time,
            opening_bid=opening_bid,
            description=description[:1000] if description else None,
            raw=_raw(),
        )
        if auction.docs:
            stamp_documents(li, auction.docs)
        out.append(li)
    return out


class TerryHoweAuctions(BaseScraper):
    slug = "counties_sc.terry_howe_auctions"
    name = "Terry Howe & Associates (SC real-estate / estate auctions)"
    category = "county_court"
    requires_apify = False
    timeout_s = 240.0
    #: The firm's live real-estate inventory swings widely between sale cycles; an
    #: empty run is legitimate, never a regression.
    expected_min_count = 0

    async def _fetch_catalog(self) -> list[_Auction]:
        kept: list[_Auction] = []
        for page in range(1, MAX_PAGES + 1):
            url = f"{API}?per_page={PER_PAGE}&page={page}&_fields=id,title,link,content&orderby=date&order=desc"
            try:
                raw = await get_text(url, impersonate=True, timeout=45.0, headers=_UA)
            except Exception as exc:  # noqa: BLE001 — one page must not kill the run
                log.warning("terry_howe_auctions.page_failed", page=page, error=str(exc)[:160])
                break
            try:
                import json
                posts = json.loads(raw)
            except ValueError:
                log.warning("terry_howe_auctions.json_failed", page=page)
                break
            if not isinstance(posts, list) or not posts:
                break
            for p in posts:
                title = _strip_html(_rendered(p.get("title")))
                body = _strip_html(_rendered(p.get("content")))
                link = p.get("link") or ""
                if not link or not title:
                    continue
                if _is_flc_or_bulk(title, body):
                    continue  # tax / FLC slice — owned by terry_howe_flc
                has_table = bool(parse_table_addresses(body))
                if not (has_table or _RE_STRONG.search(title)):
                    continue  # personal-property lot (trucks / furniture / equipment)
                kept.append(_Auction(p.get("id"), title, link, body))
            if len(posts) < PER_PAGE:
                break
        return kept

    async def fetch(self) -> Iterable[Listing]:
        auctions = await self._fetch_catalog()
        if not auctions:
            log.info("terry_howe_auctions.empty_catalog")
            return []

        # Detail-enrich the newest kept posts (sale_date + single-property street +
        # docs), bounded + politely concurrent.
        to_enrich = auctions[:_MAX_DETAIL_FETCH]
        sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)

        async def _guarded(a: _Auction) -> None:
            async with sem:
                await _enrich_from_detail(a)

        await asyncio.gather(*(_guarded(a) for a in to_enrich), return_exceptions=True)

        out: list[Listing] = []
        seen: set[tuple] = set()
        for a in auctions:
            for li in _build_listings(a, self.slug):
                key = (li.state, (li.street_address or li.source_url).lower(),
                       (li.city or "").lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append(li)

        log.info("terry_howe_auctions.done", auctions=len(auctions), listings=len(out),
                 enriched=len(to_enrich))
        return out
