"""Detail-page enrichers used by scripts/sf_crawl.py.

After Screaming Frog discovers URLs (running on the user's home/office
network, no datacenter-IP blocks), this module fetches each URL — also
from the user's network — and extracts the fields SF wouldn't have given
us without bespoke custom-extraction configs: price, mileage, image,
title-status, location, sometimes VIN.

One enricher per known source. Dispatch is by URL host. Each enricher is
async, takes (url, html) and returns a Listing or None.

The enrichment runs from `sf_crawl.py` which runs on the user's machine,
so curl-cffi works against sites that block our datacenter IP.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from .http_client import fetch_text, fetch_text_stealth
from .models import (
    Listing,
    TitleStatus,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)

log = logging.getLogger("porsche_scraper.sf_enrichers")


# ---------- shared helpers ----------

def _meta(html: str, prop: str) -> str | None:
    m = re.search(
        rf'<meta\s+(?:property|name)="{re.escape(prop)}"\s+content="([^"]*)"',
        html, re.IGNORECASE,
    )
    return m.group(1) if m else None


def _jsonld_blobs(html: str) -> list[dict]:
    out: list[dict] = []
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out


# ---------- per-source enrichers ----------

async def _enrich_cars_com(url: str) -> Listing | None:
    """Detail page embeds the same `data-vehicle-details` JSON the search
    cards do — full record in one attribute.
    """
    try:
        html = await fetch_text(url, timeout=20)
    except Exception:
        html = await fetch_text_stealth(url, timeout=30, fallback_to_render=True)
    m = re.search(r'data-vehicle-details="([^"]+)"', html)
    if not m:
        return None
    import html as html_mod
    raw = html_mod.unescape(m.group(1))
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return _listing_from_cars_com_dict(url, d)


def _listing_from_cars_com_dict(url: str, d: dict) -> Listing:
    year = d.get("year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None
    title = " ".join(filter(None, [
        str(year or ""), d.get("make") or "Porsche", d.get("model") or "", d.get("trim") or ""
    ])).strip()
    seller = d.get("seller") or {}
    listing = Listing(
        source="cars_com",
        source_url=url,
        listing_id=str(d.get("listingId") or ""),
        vin=d.get("vin"),
        title=title,
        year=year,
        model=d.get("model") or None,
        trim=d.get("trim") or None,
        price_usd=parse_price(d.get("price")),
        mileage=parse_miles(d.get("mileage")),
        location=seller.get("zip"),
        photo_url=d.get("primaryThumbnail"),
        title_status=infer_title_status(title),
        seller_type="dealer",
        raw={"cars_com": d},
    )
    listing.drivable = infer_drivable(listing.title, listing.title_status)
    return listing


async def _enrich_bring_a_trailer(url: str) -> Listing | None:
    """BaT detail page: title in h1.post-title, current/sold price in
    .listing-available-info or .info-block, mileage in .essentials.
    """
    html = await fetch_text_stealth(url, timeout=30)
    tree = HTMLParser(html)
    title_node = tree.css_first("h1.post-title") or tree.css_first("h1")
    title = title_node.text(strip=True) if title_node else ""
    if not title or "porsche" not in title.lower():
        return None
    bid_node = tree.css_first(".listing-available-info .info-value") \
        or tree.css_first(".bid-formatted")
    price = parse_price(bid_node.text(strip=True)) if bid_node else None
    sold_node = tree.css_first(".listing-stats-value")
    sold = parse_price(sold_node.text(strip=True)) if sold_node and "Sold" in (sold_node.text() or "") else None
    miles = None
    for li in tree.css(".essentials li, .listing-essentials li"):
        txt = li.text(strip=True)
        if "mile" in txt.lower():
            miles = parse_miles(txt)
            break
    image = _meta(html, "og:image")
    listing = Listing(
        source="bring_a_trailer",
        source_url=url,
        listing_id=url.rstrip("/").rsplit("/", 1)[-1],
        title=title,
        year=parse_year(title),
        current_bid_usd=price if not sold else None,
        price_usd=sold,
        mileage=miles,
        photo_url=image,
        title_status=infer_title_status(title),
        seller_type="auction",
    )
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


async def _enrich_classiccars(url: str) -> Listing | None:
    """ClassicCars uses JSON-LD with @type=Car and a "price" key."""
    html = await fetch_text_stealth(url, timeout=30)
    blobs = _jsonld_blobs(html)
    car = next((b for b in blobs if str(b.get("@type", "")).lower() in ("car", "vehicle", "product")), None)
    if not car:
        return None
    title = car.get("name") or ""
    if "porsche" not in title.lower():
        return None
    offers = car.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    listing = Listing(
        source="classiccars_com",
        source_url=url,
        listing_id=str(car.get("productID") or car.get("mpn") or ""),
        title=title,
        year=parse_year(title),
        model=car.get("model"),
        price_usd=parse_price(offers.get("price") or car.get("price")),
        photo_url=_meta(html, "og:image") or (car.get("image") if isinstance(car.get("image"), str) else None),
        title_status=infer_title_status(title),
        seller_type="private",
    )
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


async def _enrich_copart(url: str) -> Listing | None:
    """Copart lot detail: scrape the visible spans for year+model+bid."""
    html = await fetch_text_stealth(url, timeout=30)
    tree = HTMLParser(html)
    ym_node = tree.css_first("[id*='lotYearMakeModel']") or tree.css_first("h1")
    title = ym_node.text(strip=True) if ym_node else ""
    if "porsche" not in title.lower():
        return None
    if any(em in title.upper() for em in ("MACAN", "PANAMERA")):
        return None
    bid_node = tree.css_first("[class*='current-bid']") or tree.css_first("[id*='currentBid']")
    odo_node = tree.css_first("[class*='odometer']")
    yard_node = tree.css_first("[class*='yard-name']") or tree.css_first("[class*='yardName']")
    title_doc = tree.css_first("[class*='title-document']") or tree.css_first("[id*='titleType']")
    vin_node = tree.css_first("#vinAnchor") or tree.css_first("[class*='vin']")
    listing = Listing(
        source="copart",
        source_url=url,
        listing_id=url.rstrip("/").rsplit("/")[-2] if "/lot/" in url else url.rsplit("/", 1)[-1],
        vin=vin_node.text(strip=True) if vin_node else None,
        title=title,
        year=parse_year(title),
        current_bid_usd=parse_price(bid_node.text(strip=True)) if bid_node else None,
        mileage=parse_miles(odo_node.text(strip=True)) if odo_node else None,
        location=yard_node.text(strip=True) if yard_node else None,
        photo_url=_meta(html, "og:image"),
        title_status=(
            infer_title_status(title_doc.text(strip=True)) if title_doc else TitleStatus.SALVAGE
        ),
        seller_type="salvage_auction",
    )
    if listing.title_status == TitleStatus.UNKNOWN:
        listing.title_status = TitleStatus.SALVAGE
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


async def _enrich_elferspot(url: str) -> Listing | None:
    """Elferspot is "request quote" — no public price. We still record
    title/image/year/model from the slug + og:title.
    """
    html = await fetch_text_stealth(url, timeout=30)
    slug_m = re.search(r"/car/porsche-([a-z0-9-]+?)-((?:19|20)\d{2})-\d+/?", url, re.IGNORECASE)
    if not slug_m:
        return None
    model_slug, year_s = slug_m.group(1), slug_m.group(2)
    if any(t in model_slug.lower() for t in ("macan", "panamera")):
        return None
    title = _meta(html, "og:title") or f"Porsche {model_slug.replace('-', ' ').title()} {year_s}"
    title = title.replace("For sale: ", "").rsplit(" - ", 1)[0]
    listing = Listing(
        source="elferspot",
        source_url=url,
        listing_id=url.rstrip("/").rsplit("-", 1)[-1],
        title=title,
        year=int(year_s),
        model=model_slug.split("-")[0].title(),
        photo_url=_meta(html, "og:image"),
        title_status=infer_title_status(title),
        seller_type="dealer",
    )
    listing.drivable = infer_drivable(title, listing.title_status)
    return listing


async def _enrich_hemmings(url: str) -> Listing | None:
    """Hemmings: JSON-LD Vehicle blob first, fall back to og: tags."""
    html = await fetch_text_stealth(url, timeout=30)
    for b in _jsonld_blobs(html):
        if str(b.get("@type", "")).lower() in ("vehicle", "car", "product"):
            title = b.get("name") or ""
            if "porsche" not in title.lower():
                continue
            offers = b.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            mr = b.get("mileageFromOdometer") or {}
            return Listing(
                source="hemmings",
                source_url=url,
                listing_id=b.get("sku") or b.get("vehicleIdentificationNumber"),
                vin=b.get("vehicleIdentificationNumber"),
                title=title,
                year=int(b["vehicleModelDate"]) if str(b.get("vehicleModelDate") or "").isdigit() else parse_year(title),
                model=b.get("model"),
                price_usd=parse_price(offers.get("price")),
                mileage=parse_miles(mr.get("value")) if isinstance(mr, dict) else None,
                photo_url=_meta(html, "og:image"),
                title_status=infer_title_status(title),
                seller_type="dealer",
            )
    return None


# ---------- dispatch ----------


ENRICHERS: dict[str, Callable] = {
    "www.cars.com":           _enrich_cars_com,
    "cars.com":               _enrich_cars_com,
    "bringatrailer.com":      _enrich_bring_a_trailer,
    "classiccars.com":        _enrich_classiccars,
    "www.copart.com":         _enrich_copart,
    "www.elferspot.com":      _enrich_elferspot,
    "elferspot.com":          _enrich_elferspot,
    "www.hemmings.com":       _enrich_hemmings,
}


def enricher_for(url: str) -> Callable | None:
    host = (urlparse(url).hostname or "").lower()
    return ENRICHERS.get(host)


async def enrich(url: str) -> Listing | None:
    fn = enricher_for(url)
    if not fn:
        return None
    try:
        return await fn(url)
    except Exception as exc:  # noqa: BLE001
        log.info("enrich failed for %s: %s", url, exc)
        return None
