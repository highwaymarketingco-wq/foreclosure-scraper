"""Hubzu (REO + foreclosure auctions) via the public JSON endpoint.

The old assumption — that listings only load via an authenticated XHR after JS —
is false. `GET /portal/auctions?state={ST}&pageSize=200` returns the full result
set as JSON (data.srpTupples[]) with no auth, no cookie, no render. Each tuple
carries a clean address (propAddress: street/city/county/state/zip), category
(FORECLOSURE / REO), starting + current bid, beds/baths/sqft/lot, lat/lng, and
the auction end date. 100% free; the pipeline's scope filter keeps in-county rows.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType

log = structlog.get_logger()

API = "https://www.hubzu.com/portal/auctions?state={state}&pageSize=200"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.hubzu.com/",
}
_TYPE = {"REO": ListingType.REO, "FORECLOSURE": ListingType.FORECLOSURE_SALE,
         "NON_REO": ListingType.AUCTION}


def _money(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _date(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _parse_item(item: dict, state: str) -> Listing | None:
    pa = item.get("propAddress") or {}
    street = f"{(pa.get('streetNumber') or '').strip()} {(pa.get('streetName') or '').strip()}".strip()
    url = item.get("listingUrl") or ""
    if not street or not url:
        return None
    cat = (item.get("propertyCategory") or "").strip().upper()
    return Listing(
        source="national.hubzu",
        source_url=f"https://www.hubzu.com{url}",
        listing_type=_TYPE.get(cat, ListingType.AUCTION),
        state=(pa.get("state") or state).strip()[:2].upper(),
        county=(pa.get("county") or "").strip().title() or None,
        city=(pa.get("city") or "").strip() or None,
        zip_code=(pa.get("zip") or "").strip()[:5] or None,
        street_address=street,
        opening_bid=_money(item.get("startingBid")) or _money(item.get("currentBid")),
        bedrooms=item.get("bedCount") or None,
        bathrooms=item.get("bathCount") or None,
        living_sqft=_money(item.get("size")),
        lot_size_sqft=_money(item.get("lotSize")),
        latitude=item.get("lat") or None,
        longitude=item.get("lng") or None,
        sale_date=_date(item.get("listingEndDate")),
        raw={"hubzu": {"category": cat, "subtype": item.get("propertySubType"),
                       "listing_id": item.get("listingId"), "current_bid": item.get("currentBid"),
                       "status": item.get("listingStatus")}},
    )


class Hubzu(BaseScraper):
    slug = "national.hubzu"
    name = "Hubzu (REO + foreclosure auctions, free JSON)"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        async with client(timeout=30.0, headers=_HEADERS) as c:
            for st in ("NC", "SC"):
                try:
                    r = await c.get(API.format(state=st), follow_redirects=True)
                except Exception as exc:  # noqa: BLE001
                    log.warning("hubzu.fetch_failed", state=st, error=str(exc)[:160])
                    continue
                if r.status_code != 200:
                    log.warning("hubzu.bad_status", state=st, status=r.status_code)
                    continue
                try:
                    tuples = (r.json().get("data") or {}).get("srpTupples") or []
                except (ValueError, AttributeError):
                    log.warning("hubzu.json_failed", state=st)
                    continue
                n = 0
                for item in tuples:
                    li = _parse_item(item, st)
                    if not li:
                        continue
                    key = (li.raw.get("hubzu") or {}).get("listing_id") or li.source_url
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(li)
                    n += 1
                log.info("hubzu.state_done", state=st, count=n)
        log.info("hubzu.done", count=len(out))
        return out
