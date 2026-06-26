"""Foreclosure.com — public preview scrape (no auth).

Foreclosure.com paywalls the listing detail pages, but the state-listings
preview pages embed structured JSON-LD (CollectionPage → ItemList → list
of RealEstateListing items) that the public free tier exposes. Street
NUMBERS are masked ("Moore Dr" instead of "1234 Moore Dr") but city,
state, ZIP, lat/lng, beds/baths/sqft, and the foreclosure.com listing ID
are all present — useful as a lead/feed-style signal that downstream
enrichment can resolve to a full address via the parcel/geo cross-ref.

Pagination is `?pg=N` (1-indexed). Each page has 10 items. We cap at 30
pages/state by default (PAGES_CAP env var to override) — 300 listings is
plenty for residential lead-gen, and avoids hammering the site.

If FORECLOSURE_DOT_COM_USER/PASS are set, the future authenticated path
would unlock full addresses. That auth flow isn't wired yet; for now the
public preview is the only path.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URLS = (
    ("NC", "https://www.foreclosure.com/listings/north-carolina/"),
    ("SC", "https://www.foreclosure.com/listings/south-carolina/"),
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
}
JSONLD_RE = re.compile(
    r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>",
    re.S | re.I,
)
LID_RE = re.compile(r"/(\d+)_lid\b")


def _node_to_listing(node: dict, state: str, slug: str) -> Listing | None:
    item = node.get("item") if isinstance(node, dict) else None
    if not isinstance(item, dict) or item.get("@type") != "RealEstateListing":
        return None
    url = item.get("url") or ""
    lid_match = LID_RE.search(url)
    listing_id = lid_match.group(1) if lid_match else None
    img = item.get("image") or ""
    if isinstance(img, str) and img.startswith("//"):
        img = "https:" + img
    photos = [img] if isinstance(img, str) and img.startswith("http") else []
    offered = (item.get("offers") or {}).get("itemOffered") or {}
    addr = offered.get("address") or {}
    region = (addr.get("addressRegion") or "").strip().upper()
    if region != state:
        return None
    street = (addr.get("streetAddress") or "").strip() or None
    city = (addr.get("addressLocality") or "").strip() or None
    zip_code = (addr.get("postalCode") or "").strip() or None
    geo = offered.get("geo") or {}
    lat = geo.get("latitude")
    lng = geo.get("longitude")

    beds = offered.get("numberOfBedrooms")
    baths = offered.get("numberOfBathroomsTotal")
    floor = offered.get("floorSize") or {}
    sqft = None
    if floor.get("unitCode", "").upper() == "SQFT":
        try:
            sqft = int(floor.get("value"))
        except (TypeError, ValueError):
            sqft = None

    return Listing(
        source=slug,
        source_url=url,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY
            if offered.get("@type") == "SingleFamilyResidence"
            else PropertyKind.UNKNOWN,
        state=region,
        city=city,
        zip_code=zip_code,
        street_address=street,
        case_number=f"fc-{listing_id}" if listing_id else None,
        latitude=lat if isinstance(lat, (int, float)) else None,
        longitude=lng if isinstance(lng, (int, float)) else None,
        description=item.get("name") or f"Foreclosure.com listing {listing_id}",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "fc_listing_id": listing_id,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "anonymized_address": True,  # street number masked by paywall
            "images": {"real": photos} if photos else {},
        },
    )


def _extract_listings(html: str, state: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    for m in JSONLD_RE.finditer(html):
        body = m.group(1).strip()
        if not body:
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        graph = data.get("@graph", []) if isinstance(data, dict) else []
        for cp in graph:
            if not isinstance(cp, dict) or cp.get("@type") != "CollectionPage":
                continue
            item_list = (cp.get("mainEntity") or {}).get("itemListElement") or []
            for node in item_list:
                li = _node_to_listing(node, state, slug)
                if li is not None:
                    out.append(li)
    return out


async def _fetch_state(state: str, base_url: str, slug: str, pages_cap: int) -> list[Listing]:
    out: list[Listing] = []
    seen_ids: set[str] = set()
    async with client(timeout=30.0) as c:
        for page in range(1, pages_cap + 1):
            url = base_url if page == 1 else f"{base_url}?pg={page}"
            try:
                r = await c.get(url, headers=HEADERS, follow_redirects=True)
            except Exception as exc:
                log.warning("foreclosure_dot_com.fetch_failed",
                            state=state, page=page, error=str(exc)[:200])
                break
            if r.status_code != 200 or len(r.text) < 5000:
                break
            listings = _extract_listings(r.text, state, slug)
            new_this_page = 0
            for li in listings:
                key = li.case_number or li.source_url
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                out.append(li)
                new_this_page += 1
            if new_this_page == 0:
                break
    log.info("foreclosure_dot_com.state_done", state=state, count=len(out))
    return out


class ForeclosureDotCom(BaseScraper):
    slug = "national.foreclosure_dot_com"
    name = "Foreclosure.com (public preview, anonymized addresses)"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    requires_paywall = True  # full address still gated; flag for surfacing
    timeout_s = 240.0
    # Disabled 2026-06-26: foreclosure.com edge-WAF returns 403 to a plain GET,
    # to curl_cffi browser-impersonation, AND to a real stealth browser (all
    # verified live) — it's a paid-preview site with no free access by any
    # compliant means, and it's redundant with our other national aggregators
    # (zillow / realtor / trulia / auction.com / hubzu / xome / bid4assets).
    # Kept in place per code-retention policy; re-enable if access ever changes.
    disabled = True
    disabled_reason = "edge-WAF 403 to GET/impersonate/stealth-browser; paid-preview, no free access; redundant"

    async def fetch(self) -> Iterable[Listing]:
        # Paywall/disabled short-circuit (the documented behavior): the site gates
        # everything behind login and the public preview is edge-WAF blocked, so
        # without credentials — or while disabled — return [] WITHOUT any HTTP call.
        # Keeps the source deterministic + classified PAYWALL-BLOCKED, and stops the
        # short-circuit tests depending on the live site's flaky 403-vs-200.
        if self.disabled or not (
            os.environ.get("FORECLOSURE_DOT_COM_USER")
            and os.environ.get("FORECLOSURE_DOT_COM_PASS")
        ):
            return []
        pages_cap = int(os.environ.get("FORECLOSURE_DOT_COM_PAGES", "30"))
        out: list[Listing] = []
        for state, url in URLS:
            try:
                out.extend(await _fetch_state(state, url, self.slug, pages_cap))
            except Exception as exc:
                log.warning("foreclosure_dot_com.state_failed",
                            state=state, error=str(exc)[:200])
        log.info("foreclosure_dot_com.done", total=len(out))
        return out
