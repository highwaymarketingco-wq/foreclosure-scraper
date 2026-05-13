"""Porsche Approved CPO — finder.porsche.com.

The official Porsche-dealer CPO inventory. Heavy bot defences from
datacenter IPs (we see 429 on both curl-cffi and Scrapling stealth from
GitHub Actions / cloud sandboxes), so this scraper relies on `fetch_rendered`
(Patchright stealth) and is realistically reliable only when invoked
from a residential / non-datacenter IP (the user's laptop or via the
local SF wrapper).

Search URL pattern (US locale):
    https://finder.porsche.com/us/en-US/search?modelRange={911|Cayman|Boxster}

Results are React-rendered; the page emits a JSON island in
`<script id="__NEXT_DATA__">` that contains the listing array. We parse
that first, fall back to scraping the rendered DOM for vehicle links.

Listings are official Porsche CPO inventory — clean-title only, so they
all land in tier=clean. Useful as a price-reference upper bound and for
finding the cheapest CPO 718/Cayman/Boxster.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_rendered
from ..models import (
    Listing,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)

log = logging.getLogger(__name__)

BASE = "https://finder.porsche.com"
WANTED_MODEL_RANGES = ("911", "718 Cayman", "Cayman", "718 Boxster", "Boxster", "718 Spyder")


def _search_url(model_range: str, page: int = 1) -> str:
    # The finder accepts multiple modelRange params; we send one per call
    # because the result schema is the same.
    return (
        f"{BASE}/us/en-US/search"
        f"?modelRange={model_range.replace(' ', '+')}"
        f"&page={page}"
    )


def _extract_next_data_listings(html: str) -> list[dict]:
    tree = HTMLParser(html)
    node = tree.css_first("script#__NEXT_DATA__")
    if not node:
        return []
    try:
        blob = json.loads(node.text() or "{}")
    except json.JSONDecodeError:
        return []
    # The exact path varies by Next.js version; try the common ones.
    pp = ((blob.get("props") or {}).get("pageProps") or {})
    for key in ("results", "vehicles", "searchResults", "listings", "items"):
        cand = pp.get(key)
        if isinstance(cand, list):
            return [d for d in cand if isinstance(d, dict)]
        if isinstance(cand, dict):
            inner = cand.get("vehicles") or cand.get("results") or cand.get("items")
            if isinstance(inner, list):
                return [d for d in inner if isinstance(d, dict)]
    return []


def _listing_from_dict(d: dict) -> Listing | None:
    # Finder result keys (observed): id, modelRange, year (or modelYear),
    # price, mileage, exteriorColor, dealer{name,city,state}, vehicleUrl,
    # primaryImage{url} (or images[0].url), vin.
    url = (
        d.get("vehicleUrl")
        or d.get("url")
        or d.get("detailUrl")
        or (d.get("links") or {}).get("vehicle")
    )
    if not url:
        return None
    if not url.startswith("http"):
        url = urljoin(BASE, url)
    year = d.get("modelYear") or d.get("year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None
    model = d.get("modelRange") or d.get("model") or ""
    trim = d.get("trim") or d.get("variant") or ""
    title = " ".join(filter(None, [str(year or ""), "Porsche", model, trim])).strip()
    dealer = d.get("dealer") or {}
    loc = ", ".join(filter(None, [dealer.get("city"), dealer.get("state")])) or None
    image = (
        (d.get("primaryImage") or {}).get("url")
        if isinstance(d.get("primaryImage"), dict)
        else d.get("primaryImage")
    )
    if not image and isinstance(d.get("images"), list) and d.get("images"):
        first = d["images"][0]
        image = first.get("url") if isinstance(first, dict) else first
    listing = Listing(
        source="porsche_cpo",
        source_url=url,
        listing_id=str(d.get("id") or d.get("vin") or url.rsplit("/", 1)[-1]),
        vin=d.get("vin"),
        title=title,
        year=year,
        model=model or None,
        trim=trim or None,
        price_usd=parse_price(d.get("price") or (d.get("pricing") or {}).get("amount")),
        mileage=parse_miles(d.get("mileage") or d.get("odometer")),
        location=loc,
        photo_url=image,
        title_status=infer_title_status(title),
        seller_type="dealer",
        raw={"porsche_cpo": d},
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


_VEHICLE_HREF_RE = re.compile(r"/us/en-US/details/[\w-]+")
_PRICE_RE = re.compile(r"\$\s*([\d,]+)")


def _listings_from_html_fallback(html: str) -> list[Listing]:
    """When __NEXT_DATA__ is absent or the schema doesn't match, walk the
    rendered DOM for vehicle-detail anchors.
    """
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if not _VEHICLE_HREF_RE.search(href):
            continue
        url = href if href.startswith("http") else urljoin(BASE, href)
        if url in seen:
            continue
        seen.add(url)
        # Climb up to the surrounding result card and harvest text.
        card = a
        for _ in range(4):
            if card is None:
                break
            card = card.parent
        if card is None:
            card = a
        title = (a.text(strip=True) or "")
        if "porsche" not in title.lower():
            title = "Porsche " + title
        # Find price/mileage in the card's text.
        card_text = card.text(strip=True) if card else ""
        price_m = _PRICE_RE.search(card_text)
        listing = Listing(
            source="porsche_cpo",
            source_url=url,
            listing_id=url.rstrip("/").rsplit("/", 1)[-1],
            title=title,
            year=parse_year(title) or parse_year(card_text),
            price_usd=parse_price(price_m.group(0)) if price_m else None,
            mileage=parse_miles(card_text),
            title_status=infer_title_status(title),
            seller_type="dealer",
        )
        listing.drivable = infer_drivable(listing.title, listing.title_status)
        out.append(listing)
    return out


def parse_results(html: str) -> list[Listing]:
    """Parse one finder.porsche.com search-results page."""
    out: list[Listing] = []
    seen: set[str] = set()
    for d in _extract_next_data_listings(html):
        listing = _listing_from_dict(d)
        if listing and listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    if out:
        return out
    for listing in _listings_from_html_fallback(html):
        if listing.source_url not in seen:
            seen.add(listing.source_url)
            out.append(listing)
    return out


class PorscheCPOScraper(BaseScraper):
    """Official Porsche Approved CPO inventory.

    finder.porsche.com is React-rendered + heavily bot-protected, so this
    uses Scrapling/Patchright stealth via `fetch_rendered`. Even then,
    cloud / datacenter IPs frequently get 429'd. Best-effort scraper —
    realistically reliable from a residential IP.
    """

    slug = "porsche_cpo"
    name = "Porsche Approved CPO"
    timeout_s = 360.0

    def __init__(self, *, max_pages_per_model: int = 3):
        self.max_pages_per_model = max_pages_per_model

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for model_range in WANTED_MODEL_RANGES:
            for page in range(1, self.max_pages_per_model + 1):
                url = _search_url(model_range, page=page)
                try:
                    html = await fetch_rendered(
                        url,
                        timeout=90,
                        wait_for_selector=(
                            'a[href*="/details/"], [data-result], '
                            'script#__NEXT_DATA__'
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "porsche_cpo %s page %d: %s", model_range, page, exc
                    )
                    break
                listings = parse_results(html)
                fresh = [l for l in listings if l.source_url not in seen]
                if not fresh:
                    break
                seen.update(l.source_url for l in fresh)
                out.extend(fresh)
        return out
