"""Xome auctions via Scrapling stealth.

Xome's `/auctions/bank-owned/{ST}` state-filtered URL renders only an
empty state-landing shell — no real listings. The unfiltered
`/auctions/bank-owned` and `/auctions/foreclosure-homes` pages DO render
real cards across all states; we filter to NC + SC post-fetch.

Card structure (verified 2026-05-14):
  <div class="srp-property-card"
       listingkey="{id}"
       detail-href="/auctions/{slug}-{id}"
       listing-lat="..."  listing-lng="...">
    .property-bidding $price
    .bank-type / .auction-type (REO / Auction / etc.)
    <span id="streetAddress-{id}">...
    <span id="city-{id}">...
    <span id="stateOrProvinceCode-{id}">{ST}
    + bare <span>{zip}

Pagination (verified 2026-06-24):
  The SRP shows 50 cards/page with a JS-driven control inside
  ``#newPaginationHolder`` — total pages live in ``#maxPageCount`` (e.g. 11)
  and the running count in ``#totalEntry`` (e.g. 518). There is NO
  URL-addressable page param; clicking ``#right-navigation`` APPENDS the next
  page's cards to the DOM (cumulative 100 -> 150 -> 200 ...). So we click
  "next" page-by-page inside the render session until the control disables or
  ``#maxPageCount`` is reached (capped at PAGES_CAP), then parse the final
  accumulated DOM once. NC/SC cards are sparse per page but accumulate across
  all pages — materially more than the page-1-only ~3.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URLS = (
    "https://www.xome.com/auctions/bank-owned",
    "https://www.xome.com/auctions/foreclosure-homes",
    "https://www.xome.com/auctions/foreclosuresales",
)

PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
PAGES_CAP = 25


def _ltype(text: str) -> ListingType:
    s = (text or "").lower()
    if "bank owned" in s or "reo" in s:
        return ListingType.REO
    if "foreclosure" in s and "pre" not in s:
        return ListingType.FORECLOSURE_SALE
    if "pre-foreclosure" in s or "pre foreclosure" in s:
        return ListingType.LIS_PENDENS
    return ListingType.AUCTION  # default — Xome is auction-first


def _parse_card(card, slug: str) -> Listing | None:
    attrs = card.attributes or {}
    listing_id = (attrs.get("listingkey") or "").strip() or None
    detail_href = (attrs.get("detail-href") or "").strip()
    if not listing_id or not detail_href:
        return None
    lat = attrs.get("listing-lat")
    lng = attrs.get("listing-lng")

    street_node = card.css_first(f"#streetAddress-{listing_id}")
    city_node = card.css_first(f"#city-{listing_id}")
    state_node = card.css_first(f"#stateOrProvinceCode-{listing_id}")
    if street_node is None or state_node is None:
        return None
    state = (state_node.text(strip=True) or "").strip().upper()
    if state not in ("NC", "SC"):
        return None

    street = street_node.text(strip=True) or None
    if not street:
        return None
    city = city_node.text(strip=True) if city_node else None

    # ZIP — the bare <span> after stateOrProvinceCode
    zip_code = None
    addr_block = card.css_first("address")
    if addr_block is not None:
        m = re.search(r"\b(\d{5})\b", addr_block.text())
        zip_code = m.group(1) if m else None

    # Price
    price = None
    price_node = card.css_first(".property-bidding")
    if price_node is not None:
        pm = PRICE_RE.search(price_node.text())
        if pm:
            try:
                price = float(pm.group(1).replace(",", ""))
            except ValueError:
                price = None

    # Photo: <img class="lazyload" data-src="...">
    photos: list[str] = []
    img_node = card.css_first("img.lazyload, img[data-src]")
    if img_node is not None:
        src = (img_node.attributes.get("data-src") or img_node.attributes.get("src") or "").strip()
        if src.startswith("http"):
            photos.append(src)

    # Listing type from bank-type / auction-type chips
    type_chip_text = ""
    for sel in (".bank-type", ".auction-type", ".property-auction-type"):
        n = card.css_first(sel)
        if n is not None:
            type_chip_text += " " + n.text()

    def _flt(v):
        try:
            return float(v) if v else None
        except (TypeError, ValueError):
            return None

    return Listing(
        source=slug,
        source_url=f"https://www.xome.com{detail_href}",
        listing_type=_ltype(type_chip_text),
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        city=city,
        zip_code=zip_code,
        street_address=street,
        case_number=f"xome-{listing_id}",
        latitude=_flt(lat),
        longitude=_flt(lng),
        opening_bid=price,
        description=(type_chip_text or "Xome auction").strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "xome_listing_id": listing_id,
            "images": {"real": photos} if photos else {},
        },
    )


async def _fetch_page(url: str, slug: str, pages_cap: int) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    async def page_action(page):
        try:
            await page.wait_for_selector(".srp-property-card", timeout=30000)
        except Exception:
            return
        # Read the total page count from the rendered pagination control;
        # fall back to the cap if the marker is missing/garbled.
        max_pages = pages_cap
        try:
            txt = await page.eval_on_selector(
                "#maxPageCount", "el => el.textContent"
            )
            n = int(re.sub(r"[^\d]", "", txt or ""))
            if n > 0:
                max_pages = min(n, pages_cap)
        except Exception:
            pass
        # Click "next" — Xome APPENDS each page's cards to the DOM, so after
        # the loop the page holds every card. Stop when the control disables.
        for _ in range(1, max_pages):
            try:
                nxt = await page.query_selector("#right-navigation")
                if nxt is None:
                    break
                cls = (await nxt.get_attribute("class")) or ""
                if "disable" in cls.lower():
                    break
                prev = await page.eval_on_selector_all(
                    ".srp-property-card", "els => els.length"
                )
                await nxt.click()
                await page.wait_for_timeout(1500)
                cur = await page.eval_on_selector_all(
                    ".srp-property-card", "els => els.length"
                )
                if cur <= prev:  # no growth -> reached the end
                    break
            except Exception:
                break
        # Final settle + lazy-load nudge.
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=False, timeout=180000,
            page_action=page_action, solve_cloudflare=False,
        )
    except Exception as exc:
        log.warning("xome.fetch_failed", url=url, error=str(exc)[:200])
        return []
    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 5000:
        return []
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for card in tree.css(".srp-property-card"):
        try:
            li = _parse_card(card, slug)
        except Exception:
            continue
        if li is None:
            continue
        # Dedupe within this (accumulated) page by detail-URL.
        if li.source_url in seen:
            continue
        seen.add(li.source_url)
        out.append(li)
    return out


class Xome(BaseScraper):
    slug = "national.xome"
    name = "Xome (REO + foreclosure auctions, NC + SC)"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    requires_render = True
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        pages_cap = int(os.environ.get("XOME_PAGES", str(PAGES_CAP)))
        out: list[Listing] = []
        seen: set[str] = set()
        for url in URLS:
            try:
                rows = await _fetch_page(url, self.slug, pages_cap)
            except Exception as exc:
                log.warning("xome.page_failed", url=url, error=str(exc)[:200])
                continue
            kept = 0
            for li in rows:
                k = li.source_url or li.case_number
                if k in seen:
                    continue
                seen.add(k)
                out.append(li)
                kept += 1
            log.info("xome.page_done", url=url, found=len(rows), kept=kept)
        return out
