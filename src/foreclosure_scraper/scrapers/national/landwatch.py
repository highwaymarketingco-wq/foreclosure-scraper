"""LandWatch.com land listings for NC + SC core counties.

LandWatch is part of the Land.com network (LandWatch, LandAndFarm, Land.com).
All three sites are behind Akamai WAF — plain httpx gets 403. Scrapling's
StealthyFetcher bypasses the gate and returns full HTML with embedded JSON-LD
structured data (schema.org CollectionPage → ItemList → RealEstateListing).

Each listing item contains:
  name, description, url, image,
  contentLocation.address.{streetAddress, addressLocality, addressRegion, postalCode},
  offers.{price, priceCurrency, offeredBy.{name, telephone, worksFor.name}}

Robots.txt (archived): User-agent: * Allow: /  (GPTBot disallowed only).
25 listings per page; we paginate up to MAX_PAGES per county.
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

MAX_PAGES = 10  # safety cap; most counties have 2-5 pages
# FOUND 2026-10-04 (HERMES extraction-completeness audit, batch 17): the
# 2026-10-01 note below ("offeredBy never carries a telephone field at all
# anymore") only checked the SEARCH-RESULTS page's JSON-LD. Each listing's
# own DETAIL page (same Land.com-network markup as the sibling
# national.landandfarm, confirmed live on landwatch.com too) carries a
# SEPARATE, richer JSON-LD block with a REAL seller.telephone, the full
# untruncated description, a real datePosted, and a structured
# additionalProperty list. Also confirmed live: unlike the search-results
# page (Akamai-gated, needs StealthyFetcher), the DETAIL page is reachable
# via plain curl_cffi impersonation -- no expensive headless render needed
# for this enrichment. Bounded per county to keep one run's extra request
# count and wall-clock reasonable.
DETAIL_FETCH_CAP_PER_COUNTY = 10

# FOUND 2026-10-13 (source-completeness audit, Pattern B): every JSON-LD
# block on a detail page (Residence / Product / RealEstateListing+Product /
# BreadcrumbList -- confirmed live, all 4 of them, on 3 separate current
# listings) carries only the ONE main photo; widening the JSON-LD selector
# finds nothing extra. The REAL gallery (16-18 photos on the 2 Spartanburg
# listings checked, plus a shared-network Buncombe listing with 38) lives in
# a completely separate, non-JSON-LD blob: a <script type="application/json"
# id="__SERVER_STATE__"> SSR state dump at
# propertyDetailPage.propertyData.imageDocumentIds (a flat list of numeric
# document IDs) -- same Land.com-network markup as the sibling
# national.landandfarm, confirmed live on landwatch.com too. Confirmed live
# via curl_cffi impersonation: a non-main document ID from that list
# resolves to a genuine distinct image/jpeg at the same CDN host+path
# pattern already used for the one captured photo (settings.servers.Image +
# "/resizedimages/394/0/h/80/1-<id>"). Capped at a sane count (matches
# national/freddie_homesteps.py's precedent) rather than keeping all
# 16-38 -- this is a lead-gen board, not a photo viewer.
GALLERY_PHOTO_CAP = 8

# Core counties — NC (16) + SC (10)
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
    """Returns list of (county_slug, state, search_url)."""
    urls = []
    for county, state in _COUNTY_TO_STATE.items():
        state_slug = "north-carolina" if state == "NC" else "south-carolina"
        url = f"https://www.landwatch.com/{state_slug}-land-for-sale/{county}-county"
        urls.append((county, state, url))
    return urls


def _extract_listings(html: str, slug: str) -> list[Listing]:
    """Parse JSON-LD CollectionPage → ItemList from LandWatch HTML."""
    out: list[Listing] = []
    tree = HTMLParser(html)

    # The JSON-LD is in a <script> tag (not always type=application/ld+json
    # on LandWatch — sometimes it's a plain script). Find the big one with
    # mainEntity / itemListElement.
    for script_node in tree.css("script"):
        text = script_node.text()
        if not text or len(text) < 5000:
            continue
        if "mainEntity" not in text or "itemListElement" not in text:
            continue
        # Extract the JSON object
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
        break  # only one CollectionPage script per page
    return out


def _parse_item(item: dict, slug: str) -> Listing | None:
    url = (item.get("url") or "").strip()
    if not url:
        return None
    name = (item.get("name") or "").strip()
    desc = (item.get("description") or "").strip() or None

    # Address
    place = item.get("contentLocation") or {}
    addr = place.get("address") or {}
    street = (addr.get("streetAddress") or "").strip() or None
    city = (addr.get("addressLocality") or "").strip() or None
    state = (addr.get("addressRegion") or "").strip().upper() or None
    if state and len(state) > 2:
        state = state[:2]
    zip_code = (str(addr.get("postalCode") or "").strip())[:5] or None

    # Price
    offers = item.get("offers") or {}
    price = offers.get("price")
    if isinstance(price, str):
        try:
            price = float(price.replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            price = None
    elif not isinstance(price, (int, float)):
        price = None

    # Contact info
    offered_by = offers.get("offeredBy") or {}
    agent_name = (offered_by.get("name") or "").strip() or None
    agent_phone = (offered_by.get("telephone") or "").strip() or None
    brokerage = ((offered_by.get("worksFor") or {}).get("name") or "").strip() or None
    # Found 2026-10-01 (national/reo per-source audit): confirmed live,
    # offeredBy never carries a telephone field at all anymore (not blank --
    # absent), but DOES carry a profile URL (e.g.
    # landwatch.com/profile/billy-may/332405) that was never captured. Costs
    # nothing to keep (already in the fetched JSON-LD, no extra request) and
    # gives a human operator a clickable path to the agent's own contact
    # info when agent_phone comes back empty.
    agent_profile_url = (offered_by.get("url") or "").strip() or None

    # Image
    image = (item.get("image") or "").strip() or None
    photos = [image] if image and image.startswith("http") else []

    # Extract acreage from name or description
    acreage = _extract_acres(name, desc)

    # County from URL or name
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
            "landwatch": {
                "title": name,
                "agent_name": agent_name,
                "agent_phone": agent_phone,
                "agent_profile_url": agent_profile_url,
                "brokerage": brokerage,
                "listing_id": _extract_pid(url),
            },
            "images": {"real": photos} if photos else {},
        },
    )


_ACRES_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:acres?|ac\.?)", re.I)
_PID_RE = re.compile(r"/pid/(\d+)")


def _extract_acres(name: str, desc: str | None) -> float | None:
    text = f"{name} {desc or ''}"
    m = _ACRES_RE.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except (ValueError, TypeError):
            pass
    return None


def _extract_pid(url: str) -> str | None:
    m = _PID_RE.search(url)
    return m.group(1) if m else None


def _extract_county(url: str, name: str) -> str | None:
    # URL pattern: /{county}-county-{state}-...-for-sale/pid/...
    m = re.search(r"/([a-z]+)-county-", url, re.I)
    if m:
        return m.group(1).title()
    # Try from name: "Fairview, Buncombe County, NC ..."
    m = re.search(r",\s*([A-Z][a-z]+)\s+County", name)
    if m:
        return m.group(1)
    return None


def _extract_json_objects(html: str, marker: str) -> list[dict]:
    """Return every top-level JSON object embedded in a <script> tag whose
    raw text contains `marker`, using brace-depth matching (same technique
    `_extract_listings` already uses for the search page's CollectionPage
    block) -- a detail page embeds SEVERAL separate JSON-LD <script> tags,
    so this returns all matches rather than stopping at the first."""
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


def _extract_gallery_photos(html: str) -> list[str]:
    """Pull the FULL photo gallery off a listing's detail page.

    See GALLERY_PHOTO_CAP's module-level comment for the live confirmation:
    every JSON-LD block on the page carries only the single main photo --
    the real gallery lives in the <script type="application/json"
    id="__SERVER_STATE__"> SSR state blob instead, NOT in JSON-LD at all."""
    tree = HTMLParser(html)
    node = tree.css_first('script#__SERVER_STATE__')
    if node is None:
        return []
    text = node.text()
    if not text:
        return []
    try:
        state = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(state, dict):
        return []
    property_data = (
        (state.get("propertyDetailPage") or {}).get("propertyData") or {}
    )
    doc_ids = property_data.get("imageDocumentIds")
    if not isinstance(doc_ids, list) or not doc_ids:
        return []
    server = (
        (state.get("settings") or {}).get("servers") or {}
    ).get("Image") or "https://assets.landwatch.com"
    out: list[str] = []
    seen: set[str] = set()
    for doc_id in doc_ids:
        url = f"{server}/resizedimages/394/0/h/80/1-{doc_id}"
        if url not in seen:
            seen.add(url)
            out.append(url)
        if len(out) >= GALLERY_PHOTO_CAP:
            break
    return out


def _parse_detail_extras(html: str) -> dict:
    """Pull the richer fields off a listing's own detail page: a real agent
    phone (seller.telephone -- the search page never carries this, see
    DETAIL_FETCH_CAP_PER_COUNTY's module-level comment), the full
    untruncated description, datePosted, the structured additionalProperty
    list, and the full photo gallery (see GALLERY_PHOTO_CAP's comment --
    lives outside JSON-LD, so this is independent of the loop below ever
    matching)."""
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
    try:
        photos = _extract_gallery_photos(html)
    except Exception:
        photos = []
    if photos:
        extras["photos"] = photos
    return extras


async def _fetch_detail_extras(url: str) -> dict:
    """Best-effort fetch of one listing's detail page. Never raises --
    callers must treat this as pure enrichment, not load-bearing."""
    try:
        html = await get_text_impersonate(url, timeout=25.0)
        return _parse_detail_extras(html) if html else {}
    except Exception as exc:
        log.debug("landwatch.detail_fetch_failed", url=url, error=str(exc)[:160])
        return {}


def _apply_detail_extras(li: Listing, extras: dict) -> None:
    if not extras:
        return
    ns = li.raw.setdefault("landwatch", {})
    if not ns.get("agent_phone") and extras.get("agent_phone"):
        ns["agent_phone"] = extras["agent_phone"]
    if extras.get("date_posted"):
        ns["date_posted"] = extras["date_posted"]
    if extras.get("additional_properties"):
        ns["additional_properties"] = extras["additional_properties"]
    if extras.get("full_description") and len(extras["full_description"]) > len(li.description or ""):
        li.description = extras["full_description"][:2000]
    photos = extras.get("photos")
    if photos:
        have = li.raw.setdefault("images", {}).setdefault("real", [])
        for p in photos:
            if p not in have:
                have.append(p)
        if len(have) > GALLERY_PHOTO_CAP:
            del have[GALLERY_PHOTO_CAP:]


async def _fetch_county(
    county: str, state: str, base_url: str, slug: str
) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("landwatch.scrapling_missing")
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
                "landwatch.fetch_fail",
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
            "landwatch.page_done",
            county=county,
            page=page,
            found=len(listings),
            new=new,
        )
    return out


class LandWatch(BaseScraper):
    slug = "national.landwatch"
    name = "LandWatch.com (NC + SC land listings)"
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
                    "landwatch.county_failed",
                    county=county,
                    error=str(exc)[:200],
                )
                continue
            for li in rows:
                if li.source_url not in seen:
                    seen.add(li.source_url)
                    out.append(li)
            log.info(
                "landwatch.county_done", county=county, count=len(rows)
            )
        log.info("landwatch.done", total=len(out))
        return out