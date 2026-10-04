"""LoopNet commercial listings — distressed / auction commercial properties.

LoopNet (loopnet.com) is the largest commercial real estate marketplace. We
scan for listings flagged as "distressed", "auction", "bank-owned", or
"as-is" in our NC/SC footprint. These are motivated-seller commercial leads.

DISABLED 2026-10-01 (national/reo per-source audit): confirmed live, both
ways this module reached LoopNet were dead -- the homepage (and every
per-city URL this module requested) was a hard HTTP 403/404 via curl_cffi
Chrome impersonation. Reconfirmed docs/HERMES.md Section 12's CANT entry.

RE-VERIFIED 2026-10-04 (HERMES extraction-completeness audit, batch 17):
found the real current URL pattern (`/search/commercial-real-estate/
<city>-<state>/for-sale/`, confirmed live via the site's own location
search) but curl_cffi impersonation STILL got a hard 403 against it -- a
real, URL-pattern-independent WAF block. Flagged (not fixed) that a genuine
browser render loaded the same page fine, same shape of problem this
codebase already solves elsewhere (national.auction_dot_com, law_firms.
korn/zacchaeus/mcmichael_taylor_gray) via `requires_render = True` +
Scrapling's StealthyFetcher instead of impersonation.

FIXED 2026-10-04 (same audit, continued -- this pass): re-enabled via the
render-based rewrite flagged above. Live-verified against the real site
(Asheville NC, Greenville SC, Gaffney SC) through a real browser session:
  * The WAF block is specific to curl_cffi/httpx-style impersonation --
    Akamai Bot Manager + mPulse (`akamaiFileId`, `BOOMR`) fingerprints the
    TLS/JS stack, not just headers. A genuine Chromium render (Scrapling
    StealthyFetcher, same as auction_dot_com) loads the search-results page
    cleanly every time, no CAPTCHA, no block.
  * The OLD extraction (DOM `article.placard` card scraping + a free-text
    address-regex fallback over flattened body text) is no longer needed.
    Every search-results page embeds a `application/ld+json` block
    (`mainEntity.itemListElement`, one `RealEstateListing` node per card)
    with STRUCTURED data this module never captured before: the full
    "<street>, <city>, <ST> <zip>" address line, listing price, a photo
    URL, the listing agent's name, and their brokerage -- confirmed present
    on every card across all 3 test cities (23-25 items/page). This is the
    same "prefer embedded structured data over fragile DOM/regex scraping"
    pattern auction_dot_com already uses for its JSON-LD `@graph` index.
  * Extraction-completeness pass (same standard as today's audit): the old
    module captured only street/city/state/zip + a 500-char text excerpt --
    no price reliably, no photo, no broker contact at all. Now captures
    price, photo URL, agent name + brokerage, parsed sqft, parsed building
    type (also used to set property_kind: "Multifamily" -> MULTI_FAMILY,
    "Land" -> LAND), parsed cap rate, and backfills `county` via the same
    `_upstate_city_to_county` gazetteer auction_dot_com uses.
  * AUDITED, NOT FIXED (scoped out, documented rather than silently
    skipped, same call auction_dot_com's own docstring makes for its
    opening_bid/detail-PDF gap): a listing's full narrative description,
    the broker's phone/email, and the additional photo gallery only exist
    on the per-LISTING detail page, which this scraper does not fetch (only
    the city/state search-results pages). Wiring that means a second
    StealthyFetcher render per candidate listing (100+ per run) -- a real
    runtime-cost change, not an oversight, so left as a flagged follow-up.
  * LoopNet DOES expose a native "Distressed Properties" / "Auctions"
    advanced-search checkbox (confirmed live: `advancedCriteria.Distressed`
    / `advancedCriteria.Auction` in the page's Angular filter state), but
    applying it rewrites the URL to an opaque server-side `?sk=<token>`
    search-key with no human-readable query param -- there is no free,
    stable URL we can construct for "distressed only" the way the plain
    `/for-sale/` search URL is stable. Kept the existing keyword-match
    approach (scan name+description for distress language) instead of
    chasing that token, same posture as the rest of this module.

Free, public (no login) via a real browser render. Akamai blocks
impersonation; it does not block a genuine Chromium session.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ..._upstate_city_to_county import upstate_county_for
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://www.loopnet.com"

# Search URLs for NC/SC cities in our footprint. Real current pattern
# confirmed live 2026-10-04: /search/commercial-real-estate/<city>-<state>/
# for-sale/[<page>/] -- the old /<city>-<state>/commercial-real-estate/
# pattern this module used before 404s.
_CITIES = [
    ("asheville-nc", "Asheville", "NC"),
    ("hendersonville-nc", "Hendersonville", "NC"),
    ("spartanburg-sc", "Spartanburg", "SC"),
    ("greenville-sc", "Greenville", "SC"),
    ("gastonia-nc", "Gastonia", "NC"),
    ("shelby-nc", "Shelby", "NC"),
    ("morganton-nc", "Morganton", "NC"),
    ("anderson-sc", "Anderson", "SC"),
    ("gaffney-sc", "Gaffney", "SC"),
    ("rutherfordton-nc", "Rutherfordton", "NC"),
]

# Default page cap per city. LoopNet paginates at /for-sale/<n>/ (confirmed
# live); each extra page is a full extra browser render, so default to the
# first page only (~23-25 listings/city) and let LOOPNET_PAGES raise it.
PAGES_CAP = 1

# Distress keywords in listing names/descriptions.
_DISTRESS_KEYWORDS = (
    "distressed", "auction", "bank-owned", "reo", "as-is", "as is",
    "motivated", "must sell", "short sale", "liquidation", "priced to sell",
    "estate sale", "assignment", "below market",
)

JSONLD_RE = re.compile(
    r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S
)
# "<street>, <city>, <ST> <zip>[-xxxx]"
_NAME_RE = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>.+?),\s*(?P<state>[A-Z]{2})\s+"
    r"(?P<zip>\d{5})(?:-\d{4})?\s*$"
)
# "<id>/" at the end of a /Listing/<slug>/<id>/ detail URL.
_DETAIL_ID_RE = re.compile(r"/Listing/[^/]+/(\d+)/?")
# "7,600 SF Retail Building Offered at ..." / "Land Offered at ..."
_SQFT_TYPE_RE = re.compile(r"^([\d,]+)\s*SF\s+(.+?)\s+Offered\s+at", re.I)
_LAND_RE = re.compile(r"^(Land)\s+Offered\s+at", re.I)
_CAP_RATE_RE = re.compile(r"at\s+a\s+([\d.]+)%\s*Cap\s*Rate", re.I)


def _kind_from_building_type(building_type: str | None) -> PropertyKind:
    if not building_type:
        return PropertyKind.COMMERCIAL
    s = building_type.lower()
    if "multifamily" in s or "apartment" in s:
        return PropertyKind.MULTI_FAMILY
    if s.strip() == "land":
        return PropertyKind.LAND
    return PropertyKind.COMMERCIAL


def _parse_desc(description: str | None) -> tuple[int | None, str | None, float | None]:
    """(sqft, building_type, cap_rate_pct) best-effort from the JSON-LD
    description line, e.g. ``"3,225 SF Retail Building Offered at $4,089,854
    at a 5.50% Cap Rate in Asheville, NC 28806"`` or ``"Land Offered at
    $1,600,000 in Weaverville, NC 28787"``."""
    sqft = building_type = None
    cap_rate = None
    if description:
        m = _SQFT_TYPE_RE.match(description.strip())
        if m:
            try:
                sqft = int(m.group(1).replace(",", ""))
            except ValueError:
                sqft = None
            building_type = m.group(2).strip()
        elif _LAND_RE.match(description.strip()):
            building_type = "Land"
        cm = _CAP_RATE_RE.search(description)
        if cm:
            try:
                cap_rate = float(cm.group(1))
            except ValueError:
                cap_rate = None
    return sqft, building_type, cap_rate


def _node_listing(node: dict, state: str) -> Listing | None:
    """Build a Listing from one JSON-LD ``RealEstateListing`` node, or None
    if it doesn't match our footprint / doesn't carry a usable address."""
    if not isinstance(node, dict):
        return None
    name = node.get("name") or ""
    description = node.get("description") or ""
    url = node.get("url") or ""
    if not name or not url:
        return None

    m = _NAME_RE.match(name.strip())
    if not m:
        return None
    street = m.group("street").strip()
    city = m.group("city").strip()
    addr_state = m.group("state").upper()
    zip_code = m.group("zip")
    if addr_state != state:
        return None

    haystack = f"{name} {description}".lower()
    matched = [kw for kw in _DISTRESS_KEYWORDS if kw in haystack]
    if not matched:
        return None

    idm = _DETAIL_ID_RE.search(url)
    detail_id = idm.group(1) if idm else url

    price = None
    agent = brokerage = None
    offers = node.get("offers")
    offer0 = None
    if isinstance(offers, list) and offers:
        offer0 = offers[0]
    elif isinstance(offers, dict):
        offer0 = offers
    price_raw = None
    if isinstance(offer0, dict):
        price_raw = offer0.get("price")
        try:
            cand = float(str(price_raw).replace(",", "")) if price_raw not in (None, "") else None
        except (TypeError, ValueError):
            cand = None
        # Live-confirmed 2026-10-04: LoopNet's own JSON-LD mangles a
        # price-RANGE listing's offer -- "134 Macedonia Rd, Gaffney, SC"
        # shows "$180,000 - $3,280,000" in its description, but
        # offers[0].price was the literal string "1800003280000" ("180000"
        # + "3280000" concatenated, no separator). Not our parsing bug --
        # the source data itself is garbled for range-priced listings -- so
        # guard against the resulting absurd value rather than publish a
        # nine-figure-wrong opening_bid. $500M is well above any real single
        # NC/SC footprint commercial listing we've seen (max observed here
        # was $8.8M) but comfortably clears legitimate large portfolios.
        price = cand if cand is not None and 0 < cand <= 500_000_000 else None
        offered_by = offer0.get("offeredBy")
        if isinstance(offered_by, dict):
            agent = offered_by.get("name") or None
            works_for = offered_by.get("worksFor")
            if isinstance(works_for, dict):
                brokerage = works_for.get("name") or None

    image = node.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if not isinstance(image, str):
        image = None

    sqft, building_type, cap_rate = _parse_desc(description)
    county = upstate_county_for(city, addr_state)

    return Listing(
        source="national.loopnet",
        source_url=url,
        listing_type=ListingType.DISTRESSED,
        property_kind=_kind_from_building_type(building_type),
        street_address=street,
        city=city,
        county=county,
        state=addr_state,
        zip_code=zip_code,
        opening_bid=price,
        description=description.strip() or f"LoopNet distressed commercial ({city}, {addr_state})",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"loopnet": {
            "detail_id": detail_id,
            "agent": agent,
            "brokerage": brokerage,
            "image": image,
            "sqft": sqft,
            "building_type": building_type,
            "cap_rate_pct": cap_rate,
            "matched_keywords": matched,
            "name_raw": name,
            # Verbatim JSON-LD price string, kept even when `price` above is
            # None because it failed the sanity bound -- an operator opening
            # this row can still see what LoopNet actually sent.
            "price_raw": price_raw,
        }},
    )


def _extract_page(html: str, state: str) -> dict[str, Listing]:
    """All distress-matching NC/SC listings on one rendered search page,
    keyed by detail-id, parsed from the page's own ``application/ld+json``
    ``RealEstateListing`` nodes (richer and far more robust than scraping
    the DOM card markup directly)."""
    out: dict[str, Listing] = {}
    for sm in JSONLD_RE.finditer(html):
        raw = (sm.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        main_entity = data.get("mainEntity")
        if not isinstance(main_entity, dict):
            continue
        items = main_entity.get("itemListElement")
        if not isinstance(items, list):
            continue
        for node in items:
            li = _node_listing(node, state)
            if li is None:
                continue
            key = li.raw["loopnet"]["detail_id"]
            if key not in out:
                out[key] = li
    return out


async def _render(url: str) -> str:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("loopnet.scrapling_missing")
        return ""

    async def page_action(page):
        try:
            await page.wait_for_selector("a[href*='/Listing/']", timeout=30000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=120000,
            page_action=page_action,
        )
    except Exception as exc:
        log.warning("loopnet.fetch_fail", url=url, error=str(exc)[:200])
        return ""
    body = getattr(result, "body", b"")
    html = (
        body.decode("utf-8", errors="replace")
        if isinstance(body, bytes) else str(body or "")
    )
    if not html or len(html) < 5000:
        return ""
    return html


async def _fetch_city(slug: str, city: str, state: str, pages_cap: int) -> list[Listing]:
    out: dict[str, Listing] = {}
    for page in range(1, pages_cap + 1):
        base_url = f"{_BASE}/search/commercial-real-estate/{slug}/for-sale/"
        page_url = base_url if page == 1 else f"{base_url}{page}/"
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
        log.info("loopnet.page_done", city=city, state=state, page=page,
                 found=len(page_rows), new=new_this_page, total=len(out))
        # No new rows -> exhausted this city's result set (or hit the same
        # page LoopNet serves past the end).
        if new_this_page == 0:
            break
    return list(out.values())


class LoopNetScraper(BaseScraper):
    slug = "national.loopnet"
    name = "LoopNet Commercial Distressed Listings"
    category = "marketplace"
    expected_min_count = 0
    requires_apify = False
    # FIX 2026-10-04: switched from curl_cffi impersonation (hard-blocked by
    # Akamai Bot Manager even against the correct URL, see module docstring)
    # to a real render, same convention as national.auction_dot_com and
    # law_firms.{korn,zacchaeus,mcmichael_taylor_gray}. main.py reads this
    # flag in two places that both matter here too: carryover skips replaying
    # stale data for render-required sources, and the run-report buckets a
    # flaky stealth-browser run as an ACKNOWLEDGED failure mode rather than a
    # false REGRESSED alert.
    requires_render = True
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        pages_cap = int(os.environ.get("LOOPNET_PAGES", str(PAGES_CAP)))
        out: list[Listing] = []
        for slug, city, state in _CITIES:
            try:
                listings = await _fetch_city(slug, city, state, pages_cap)
                out.extend(listings)
                self.partial.extend(listings)
                log.info("loopnet.city_done", city=city, state=state,
                         count=len(listings))
            except Exception as exc:
                log.warning("loopnet.city_failed", city=city, state=state,
                            error=str(exc)[:200])
        log.info("loopnet.done", count=len(out), cities=len(_CITIES))
        return out
