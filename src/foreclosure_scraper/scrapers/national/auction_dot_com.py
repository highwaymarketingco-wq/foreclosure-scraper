"""Auction.com via Scrapling stealth (no Apify, no paid).

Auction.com is a major foreclosure auction site. SPA-rendered, no public
JSON endpoint. Scrapling's StealthyFetcher renders the search page, then
we parse properties from the DOM.

Capture model (verified 2026-06-24):
  * The state search page embeds the FULL result set as detail-link slugs in
    the DOM, e.g. ``/details/1402-tom-pepper-rd-creswell-nc-2045737`` — every
    slug carries the ``-{state}-{id}`` tail, so street + city parse straight
    out of the slug (NC ~342, SC ~168). This is far more than the ~14 cards
    that render with a full address node.
  * One embedded JSON-LD block (``@graph`` of ``SingleFamilyResidence``)
    carries ~50 of those with rich data (zip / price / geo / specs); we join
    it onto the slug set by detail-URL to enrich where available.
  * There is no URL-addressable pagination (the SPA "Load More"s in place and
    embeds the whole set on page 1). We still wrap the fetch in a page loop on
    auction.com's path-pagination token as a best-effort, dedupe by
    detail-URL, and stop as soon as a page yields no new hrefs.

Free, no auth required.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URLS = (
    ("NC", "https://www.auction.com/residential/nc/"),
    ("SC", "https://www.auction.com/residential/sc/"),
)

# Path-style pagination token auction.com uses internally, e.g.
# /residential/nc/page_2_p/ . Page 1 is the bare state URL.
PAGES_CAP = 25

JSONLD_RE = re.compile(
    r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S
)
# /details/<street-city-slug>-<st>-<id>
DETAIL_RE = re.compile(r"/details/([a-z0-9][a-z0-9-]*)-([a-z]{2})-(\d+)")
PRICE_RE = re.compile(r"\$([\d,]+)")


def _kind(raw: str | None) -> PropertyKind:
    if not raw:
        return PropertyKind.UNKNOWN
    s = str(raw).lower()
    if "single" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "land" in s or "lot" in s:
        return PropertyKind.LAND
    if "commercial" in s:
        return PropertyKind.COMMERCIAL
    if "mobile" in s or "manufactured" in s:
        return PropertyKind.MOBILE
    return PropertyKind.UNKNOWN


def _ltype_from_status(s: str) -> ListingType:
    s = (s or "").lower()
    if "auction" in s:
        return ListingType.AUCTION
    if "reo" in s or "bank" in s:
        return ListingType.REO
    if "fore" in s:
        return ListingType.FORECLOSURE_SALE
    return ListingType.AUCTION


def _split_slug_address(slug: str) -> tuple[str | None, str | None]:
    """Recover (street, city) from a detail slug like
    ``1402-tom-pepper-rd-creswell``. The trailing token is the city; the
    rest is the street. Best-effort and defensive — returns (None, None) if
    it can't make sense of the slug."""
    if not slug:
        return None, None
    words = [w for w in slug.split("-") if w]
    if len(words) < 2:
        return None, None
    # City is the trailing 1-2 tokens; we keep it simple (last token) and
    # title-case. Street is everything before it.
    city = words[-1].title()
    street = " ".join(words[:-1]).title()
    if len(street) < 2:
        return None, None
    return street, city


def _jsonld_index(html: str, state: str) -> dict[str, dict]:
    """Map detail-id -> rich node dict for SingleFamilyResidence entries in
    the given state. Defensive: bad JSON is skipped."""
    idx: dict[str, dict] = {}
    for m in JSONLD_RE.finditer(html):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        graph = data.get("@graph", []) if isinstance(data, dict) else []
        for node in graph:
            if not isinstance(node, dict):
                continue
            if node.get("@type") != "SingleFamilyResidence":
                continue
            addr = node.get("address") or {}
            if not isinstance(addr, dict):
                continue
            if (addr.get("addressRegion") or "").upper() != state:
                continue
            url = node.get("url") or node.get("@id") or ""
            dm = DETAIL_RE.search(url)
            if not dm:
                continue
            idx[dm.group(3)] = node
    return idx


def _node_listing(detail_id: str, slug: str, state: str,
                  node: dict | None) -> Listing | None:
    """Build a Listing for one detail-id, preferring JSON-LD ``node`` data
    and falling back to slug-parsed street/city."""
    link = (
        f"https://www.auction.com/details/{slug}-{state.lower()}-{detail_id}"
    )

    street = city = zip_code = None
    price = None
    kind = PropertyKind.UNKNOWN
    lat = lng = None
    beds = baths = sqft = year = None

    if node:
        addr = node.get("address") or {}
        if isinstance(addr, dict):
            street = addr.get("streetAddress") or None
            city = addr.get("addressLocality") or None
            zip_code = addr.get("postalCode") or None
        geo = node.get("geo") or {}
        if isinstance(geo, dict):
            lat = geo.get("latitude")
            lng = geo.get("longitude")
        beds = node.get("numberOfBedrooms")
        baths = node.get("numberOfBathroomsTotal")
        year = node.get("yearBuilt")
        fs = node.get("floorSize") or {}
        if isinstance(fs, dict):
            sqft = fs.get("value")
        kind = _kind(node.get("@type"))

    # Fall back to slug-derived street/city when JSON-LD absent.
    if not street:
        s_street, s_city = _split_slug_address(slug)
        street = s_street
        if not city:
            city = s_city
    if not street:
        return None

    def _flt(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _int(v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return Listing(
        source="national.auction_dot_com",
        source_url=link,
        listing_type=ListingType.AUCTION,
        property_kind=kind,
        street_address=street,
        city=city,
        state=state,
        zip_code=zip_code,
        opening_bid=price,
        latitude=_flt(lat),
        longitude=_flt(lng),
        case_number=f"auctioncom-{detail_id}",
        description="Auction.com foreclosure",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"auction_dot_com": {
            "detail_id": detail_id,
            "beds": _int(beds),
            "baths": _flt(baths),
            "sqft": _int(sqft),
            "year_built": _int(year),
            "enriched": node is not None,
        }},
    )


def _extract_page(html: str, state: str) -> dict[str, Listing]:
    """All NC/SC listings on one rendered page, keyed by detail-id."""
    ld = _jsonld_index(html, state)
    out: dict[str, Listing] = {}
    # Slug hrefs are the full result set; iterate them and enrich from JSON-LD.
    for m in DETAIL_RE.finditer(html):
        slug, st, detail_id = m.group(1), m.group(2).upper(), m.group(3)
        if st != state:
            continue
        if detail_id in out:
            continue
        li = _node_listing(detail_id, slug, state, ld.get(detail_id))
        if li is not None:
            out[detail_id] = li
    return out


async def _render(url: str) -> str:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("auction_dot_com.scrapling_missing")
        return ""

    async def page_action(page):
        try:
            await page.wait_for_selector(
                "a[href*='/details/'], [data-elm-id*='property'], "
                "[data-testid*='property']",
                timeout=30000,
            )
            await page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await page.wait_for_timeout(2500)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=120000,
            page_action=page_action,
        )
    except Exception as exc:
        log.warning("auction_dot_com.fetch_fail", url=url,
                    error=str(exc)[:200])
        return ""
    body = getattr(result, "body", b"")
    html = (
        body.decode("utf-8", errors="replace")
        if isinstance(body, bytes) else str(body or "")
    )
    if not html or len(html) < 5000:
        return ""
    return html


async def _fetch_state(state: str, url: str, pages_cap: int) -> list[Listing]:
    out: dict[str, Listing] = {}
    for page in range(1, pages_cap + 1):
        # Page 1 is the bare state URL; subsequent pages use the path token.
        page_url = url if page == 1 else f"{url}page_{page}_p/"
        html = await _render(page_url)
        if not html:
            break
        page_rows = _extract_page(html, state)
        new_this_page = 0
        for detail_id, li in page_rows.items():
            if detail_id in out:
                continue
            out[detail_id] = li
            new_this_page += 1
        log.info("auction_dot_com.page_done", state=state, page=page,
                 found=len(page_rows), new=new_this_page, total=len(out))
        # No new detail-hrefs -> we've exhausted the (single-page) result set.
        if new_this_page == 0:
            break
    return list(out.values())


class AuctionDotCom(BaseScraper):
    slug = "national.auction_dot_com"
    name = "Auction.com"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        pages_cap = int(
            os.environ.get("AUCTION_DOT_COM_PAGES", str(PAGES_CAP))
        )
        out: list[Listing] = []
        for state, url in URLS:
            try:
                listings = await _fetch_state(state, url, pages_cap)
                out.extend(listings)
                log.info("auction_dot_com.state_done", state=state,
                         count=len(listings))
            except Exception as exc:
                log.warning("auction_dot_com.state_failed", state=state,
                            error=str(exc)[:200])
        return out
