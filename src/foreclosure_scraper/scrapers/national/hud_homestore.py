"""HUD HomeStore — federal REO listings via direct Scrapling stealth scrape.

Earlier version used Apify (martc03/hud-foreclosures actor). New version
hits hudhomestore.gov directly via Scrapling, parsing the available_prop
hidden input that contains the full property list as JSON.

Free, no Apify dependency.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from html import unescape
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


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
    if "manufactured" in s or "mobile" in s:
        return PropertyKind.MOBILE
    return PropertyKind.UNKNOWN


async def _fetch_state(state: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("hud.scrapling_missing")
        return []

    url = f"https://www.hudhomestore.gov/searchresult?stateCode={state}"

    async def page_action(page):
        try:
            await page.wait_for_selector("#available_prop, [name='available_prop']", timeout=30000)
            # Wait additional time for the hidden input to be populated
            await page.wait_for_timeout(3000)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=120000,
            page_action=page_action,
        )
    except Exception as exc:
        log.warning("hud.fetch_fail", state=state, error=str(exc)[:200])
        return []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 5000:
        return []

    out: list[Listing] = []

    # Try the available_prop hidden input first
    m = re.search(
        r'(?:id|name)=["\']available_prop["\'][^>]+value=["\']([^"\']*)["\']',
        html, re.S,
    )
    if not m:
        m = re.search(
            r'value=["\']([^"\']*)["\'][^>]+(?:id|name)=["\']available_prop["\']',
            html, re.S,
        )
    if m:
        raw_val = unescape(m.group(1))
        if raw_val and raw_val not in ("null", "[]", "", "0"):
            try:
                data = json.loads(raw_val)
                if isinstance(data, list):
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        addr = (item.get("Address") or item.get("address")
                                or item.get("PropertyStreetAddress") or "")
                        if not addr:
                            continue
                        case = item.get("CaseNumber") or item.get("caseNumber")
                        out.append(
                            Listing(
                                source="national.hud_homestore",
                                source_url=(
                                    f"https://www.hudhomestore.gov/Listing/PropertyDetails?"
                                    f"caseNumber={case}" if case else
                                    "https://www.hudhomestore.gov/"
                                ),
                                listing_type=ListingType.REO,
                                property_kind=_kind(item.get("PropertyType") or item.get("propertyType")),
                                street_address=str(addr).strip(),
                                city=item.get("City") or item.get("city"),
                                state=item.get("State") or item.get("state") or state,
                                zip_code=str(item.get("Zip") or item.get("zipCode") or "")[:5] or None,
                                county=(item.get("County") or "").replace(" County", "") or None,
                                case_number=str(case) if case else None,
                                opening_bid=item.get("ListPrice") or item.get("listPrice"),
                                bedrooms=item.get("Bedrooms") or item.get("bedrooms"),
                                bathrooms=item.get("Bathrooms") or item.get("bathrooms"),
                                living_sqft=item.get("LivingArea") or item.get("squareFeet"),
                                year_built=item.get("YearBuilt") or item.get("yearBuilt"),
                                first_seen=datetime.utcnow(),
                                last_seen=datetime.utcnow(),
                                raw={"hud": item},
                            )
                        )
            except (ValueError, KeyError):
                pass

    return out


class HudHomeStore(BaseScraper):
    slug = "national.hud_homestore"
    name = "HUD HomeStore (REO)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False  # Now Scrapling-based
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("NC", "SC"):
            try:
                listings = await _fetch_state(state)
                out.extend(listings)
                log.info("hud.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("hud.state_failed", state=state, error=str(exc)[:200])
        return out
