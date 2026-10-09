"""LandAndFarm.com land listings for NC + SC core counties.

LandAndFarm is part of the Land.com network alongside LandWatch and Land.com.
Like LandWatch, it is Akamai-protected and requires Scrapling StealthyFetcher.
The page structure is identical: JSON-LD CollectionPage → ItemList with
RealEstateListing items containing name, address, price, and agent contact info.

URL pattern: /search/{state}/{county}-county-land-for-sale/
Robots.txt (archived): User-agent: * Allow: /  (GPTBot disallowed only).
25 listings per page; paginated with ?page=N.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text_impersonate
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

MAX_PAGES = 10
# FOUND 2026-10-04 (HERMES extraction-completeness audit, batch 17): the
# 2026-10-01 note below ("offeredBy never carries a telephone field at all
# anymore") only checked the SEARCH-RESULTS page's JSON-LD. Each listing's
# own DETAIL page carries a SEPARATE, richer JSON-LD block
# (type=["RealEstateListing","Product"], @id ending "#listingdetailpage")
# with a REAL seller.telephone, the full untruncated description (the
# search page's description is cut off mid-sentence at ~250 chars), a real
# datePosted, and a structured additionalProperty list (Acreage/Activities/
# Lot Description/Present Use/Proposed Use) -- confirmed live on a real
# current Buncombe listing: phone "(828) 555-0756", present/proposed use
# values like "Residential Single"/"Commercial". Also confirmed live: unlike
# the search-results page (Akamai-gated, needs StealthyFetcher), the DETAIL
# page is reachable via plain curl_cffi impersonation -- no expensive
# headless render needed for this enrichment. Bounded per county (not
# exhaustive) to keep one run's extra request count and wall-clock
# reasonable; this is sampling-depth value-add, not a basic-coverage gap.
DETAIL_FETCH_CAP_PER_COUNTY = 10

NC_COUNTIES = [
    "buncombe", "henderson", "cleveland", "gaston", "rutherford", "polk",
    "transylvania", "mcdowell", "lincoln", "mitchell", "burke", "brunswick",
    "pender", "onslow", "carteret", "dare",
]
SC_COUNTIES = [
    "spartanburg", "anderson", "pickens", "oconee", "cherokee", "union",
    "laurens", "charleston", "georgetown", "horry",
]

_COUNTY_TO_STATE: dict[str, str] = {}
for c in NC_COUNTIES:
    _COUNTY_TO_STATE[c] = "NC"
for c in SC_COUNTIES:
    _COUNTY_TO_STATE[c] = "SC"


def _build_urls() -> list[tuple[str, str, str]]:
    urls = []
    for county, state in _COUNTY_TO_STATE.items():
        state_slug = "north-carolina" if state == "NC" else "south-carolina"
        url = f"https://www.landandfarm.com/search/{state_slug}/{county}-county-land-for-sale/"
        urls.append((county, state, url))
    return urls


_ACRES_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:acres?|ac\.?)", re.I)


def _extract_acres(name: str, desc: str | None) -> float | None:
    text = f"{name} {desc or ''}"
    m = _ACRES_RE.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except (ValueError, TypeError):
            pass
    return None


def _extract_listing_id(url: str) -> str | None:
    m = re.search(r"/property/[^/]*-(\d+)/?", url)
    return m.group(1) if m else None


def _extract_county(url: str, name: str) -> str | None:
    m = re.search(r"/([a-z]+)-county-", url, re.I)
    if m:
        return m.group(1).title()
    m = re.search(r",\s*([A-Z][a-z]+)\s+County", name)
    if m:
        return m.group(1)
    return None


def _extract_listings(html: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    tree = HTMLParser(html)

    for script_node in tree.css("script"):
        text = script_node.text()
        if not text or len(text) < 5000:
            continue
        if "mainEntity" not in text or "itemListElement" not in text:
            continue
        start = text.find("{")
        if start < 0:
            continue
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            if depth == 0:
                end = i + 1
                break
        try:
            data = json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            continue
        me = data.get("mainEntity") or {}
        items = me.get("itemListElement") or []
        if not isinstance(items, list):
            continue
        for entry in items:
            if not isinstance(entry, dict):
                continue
            item = entry.get("item") or {}
            li = _parse_item(item, slug)
            if li:
                out.append(li)
        break
    return out


def _parse_item(item: dict, slug: str) -> Listing | None:
    url = (item.get("url") or "").strip()
    if not url:
        return None
    name = (item.get("name") or "").strip()
    desc = (item.get("description") or "").strip() or None

    place = item.get("contentLocation") or {}
    addr = place.get("address") or {}
    street = (addr.get("streetAddress") or "").strip() or None
    city = (addr.get("addressLocality") or "").strip() or None
    state = (addr.get("addressRegion") or "").strip().upper() or None
    if state and len(state) > 2:
        state = state[:2]
    zip_code = (str(addr.get("postalCode") or "").strip())[:5] or None

    offers = item.get("offers") or {}
    price = offers.get("price")
    if isinstance(price, str):
        try:
            price = float(price.replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            price = None
    elif not isinstance(price, (int, float)):
        price = None

    offered_by = offers.get("offeredBy") or {}
    agent_name = (offered_by.get("name") or "").strip() or None
    agent_phone = (offered_by.get("telephone") or "").strip() or None
    brokerage = ((offered_by.get("worksFor") or {}).get("name") or "").strip() or None
    # Found 2026-10-01 (national/reo per-source audit): confirmed live,
    # offeredBy never carries a telephone field at all anymore (not blank --
    # absent), but DOES carry a profile URL that was never captured. Costs
    # nothing to keep (already in the fetched JSON-LD, no extra request) and
    # gives a human operator a clickable path to the agent's own contact
    # info when agent_phone comes back empty.
    agent_profile_url = (offered_by.get("url") or "").strip() or None

    image = (item.get("image") or "").strip() or None
    photos = [image] if image and image.startswith("http") else []

    acreage = _extract_acres(name, desc)
    county = _extract_county(url, name)

    return Listing(
        source=slug,
        source_url=url,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.LAND,
        street_address=street,
        city=city,
        state=state,
        zip_code=zip_code,
        county=county,
        opening_bid=float(price) if price else None,
        acreage=acreage,
        description=(desc or name)[:500],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "landandfarm": {
                "title": name,
                "agent_name": agent_name,
                "agent_phone": agent_phone,
                "agent_profile_url": agent_profile_url,
                "brokerage": brokerage,
                "listing_id": _extract_listing_id(url),
            },
            "images": {"real": photos} if photos else {},
        },
    )


def _extract_json_objects(html: str, marker: str) -> list[dict]:
    """Return every top-level JSON object embedded in a <script> tag whose
    raw text contains `marker`, using brace-depth matching (same technique
    `_extract_listings` already uses for the search page's CollectionPage
    block) -- a detail page embeds SEVERAL separate JSON-LD <script> tags
    (Residence / Product / RealEstateListing), so this returns all matches
    rather than stopping at the first."""
    out: list[dict] = []
    tree = HTMLParser(html)
    for script_node in tree.css("script"):
        text = script_node.text()
        if not text or marker not in text:
            continue
        start = text.find("{")
        if start < 0:
            continue
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            if depth == 0:
                end = i + 1
                break
        try:
            out.append(json.loads(text[start:end]))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def _parse_detail_extras(html: str) -> dict:
    """Pull the richer fields off a listing's own detail page: a real agent
    phone (seller.telephone -- the search page never carries this, see
    DETAIL_FETCH_CAP_PER_COUNTY's module-level comment), the full
    untruncated description, datePosted, and the structured
    additionalProperty list (Acreage/Activities/Lot Description/Present
    Use/Proposed Use)."""
    extras: dict = {}
    for obj in _extract_json_objects(html, "#listingdetailpage"):
        if "RealEstateListing" not in str(obj.get("@type", "")):
            continue
        desc = (obj.get("description") or "").strip()
        if desc:
            extras["full_description"] = desc
        if obj.get("datePosted"):
            extras["date_posted"] = obj["datePosted"]
        seller = ((obj.get("offers") or {}).get("seller")) or {}
        phone = (seller.get("telephone") or "").strip()
        if phone:
            extras["agent_phone"] = phone
        main_entity = obj.get("mainEntity") or {}
        props = main_entity.get("additionalProperty") or []
        if isinstance(props, list) and props:
            parsed = {}
            for p in props:
                if isinstance(p, dict) and p.get("name"):
                    parsed[p["name"]] = p.get("value")
            if parsed:
                extras["additional_properties"] = parsed
        break
    return extras


async def _fetch_detail_extras(url: str) -> dict:
    """Best-effort fetch of one listing's detail page. Never raises --
    callers must treat this as pure enrichment, not load-bearing."""
    try:
        html = await get_text_impersonate(url, timeout=25.0)
        return _parse_detail_extras(html) if html else {}
    except Exception as exc:
        log.debug("landandfarm.detail_fetch_failed", url=url, error=str(exc)[:160])
        return {}


def _apply_detail_extras(li: Listing, extras: dict) -> None:
    if not extras:
        return
    ns = li.raw.setdefault("landandfarm", {})
    if not ns.get("agent_phone") and extras.get("agent_phone"):
        ns["agent_phone"] = extras["agent_phone"]
    if extras.get("date_posted"):
        ns["date_posted"] = extras["date_posted"]
    if extras.get("additional_properties"):
        ns["additional_properties"] = extras["additional_properties"]
    if extras.get("full_description") and len(extras["full_description"]) > len(li.description or ""):
        li.description = extras["full_description"][:2000]


async def _fetch_county(
    county: str, state: str, base_url: str, slug: str
) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("landandfarm.scrapling_missing")
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    detail_fetches_done = 0
    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            result = await StealthyFetcher.async_fetch(
                url,
                headless=True,
                network_idle=False,
                timeout=60000,
                solve_cloudflare=False,
            )
        except Exception as exc:
            log.warning(
                "landandfarm.fetch_fail",
                county=county,
                page=page,
                error=str(exc)[:200],
            )
            break
        body = getattr(result, "body", b"")
        html = (
            body.decode("utf-8", errors="replace")
            if isinstance(body, bytes)
            else str(body or "")
        )
        if not html or len(html) < 5000:
            break
        listings = _extract_listings(html, slug)
        if not listings:
            break
        new = 0
        for li in listings:
            if li.source_url not in seen:
                seen.add(li.source_url)
                out.append(li)
                new += 1
                if detail_fetches_done < DETAIL_FETCH_CAP_PER_COUNTY:
                    extras = await _fetch_detail_extras(li.source_url)
                    _apply_detail_extras(li, extras)
                    detail_fetches_done += 1
        if new == 0:
            break
        log.info(
            "landandfarm.page_done",
            county=county,
            page=page,
            found=len(listings),
            new=new,
        )
    return out


class LandAndFarm(BaseScraper):
    slug = "national.landandfarm"
    name = "LandAndFarm.com (NC + SC land listings)"
    category = "national_land_listing"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        # Bank rows as they are collected: if the soft timeout fires,
        # base_scraper ships self.partial instead of discarding the run.
        out = self.partial
        seen: set[str] = set()
        for county, state, url in _build_urls():
            try:
                rows = await _fetch_county(county, state, url, self.slug)
            except Exception as exc:
                log.warning(
                    "landandfarm.county_failed",
                    county=county,
                    error=str(exc)[:200],
                )
                continue
            for li in rows:
                if li.source_url not in seen:
                    seen.add(li.source_url)
                    out.append(li)
            log.info(
                "landandfarm.county_done", county=county, count=len(rows)
            )
        log.info("landandfarm.done", total=len(out))
        return out