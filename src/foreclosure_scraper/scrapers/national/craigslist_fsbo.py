"""Craigslist FSBO (for-sale-by-owner real estate) — motivated-seller lead SOURCE.

Owners listing directly (no agent) are often time-pressured / distressed = a pre-foreclosure
motivated-seller signal. Craigslist's HTML is JS-hydrated (no listings in the raw page), but
its SAPI JSON endpoint returns them: `sapi.craigslist.org/web/v8/postings/search/full`. Each
item is a compact array carrying posting-id + price + lat/lng — a complete lead skeleton the
engine's geo→parcel→owner→value chain fills out downstream.

Compliance note: pure public HTTP via the same JSON the site's own front-end calls (no login,
no CAPTCHA). FRAGILE by nature — Craigslist rate-limits/IP-bans heavy scraping and can change
the SAPI shape; this pulls one page per region (~50-60 items) at low volume. If a region's
items ever come back malformed, it degrades to 0 for that region, never raises.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger(__name__)

# CL host -> numeric areaId (verified 2026-08-16 against in-footprint coords)
AREAS = {
    "asheville.craigslist.org": 171,
    "charlotte.craigslist.org": 41,
    "greenville.craigslist.org": 253,
    "hickory.craigslist.org": 462,
    "myrtlebeach.craigslist.org": 254,
}
# WNC + Upstate/coastal SC bounding box — CL regions spill into GA/TN/VA, so clip to footprint.
_LAT_MIN, _LAT_MAX = 32.0, 36.7
_LNG_MIN, _LNG_MAX = -84.4, -78.0
_SAPI = ("https://sapi.craigslist.org/web/v8/postings/search/full"
         "?batch={area}-0-360-0-0&cc=US&lang=en&searchPath=reo")


def _parse_coord(v):
    """'1:1~35.2584~-83.3411' -> (35.2584, -83.3411) or (None, None)."""
    try:
        parts = str(v).split("~")
        return float(parts[1]), float(parts[2])
    except (ValueError, IndexError, TypeError):
        return None, None


def _listing_from_item(item, host: str, min_posting_id: int) -> Listing | None:
    # SAPI item = [deltaId, _, catId, price, "1:N~lat~lng", code, ...tagged subarrays..., title, ...]
    # The real posting id is delta-encoded: minPostingId + item[0]. The URL slug is the
    # [6, "<slug>"] subarray; the bare string after the subarrays is the title.
    if not isinstance(item, list) or len(item) < 6 or not isinstance(item[0], int):
        return None
    price = item[3] if isinstance(item[3], (int, float)) and item[3] else None
    lat, lng = _parse_coord(item[4])
    if lat is None or not (_LAT_MIN <= lat <= _LAT_MAX and _LNG_MIN <= lng <= _LNG_MAX):
        return None
    pid = min_posting_id + item[0]
    slug = next((s[1] for s in item if isinstance(s, list) and len(s) >= 2 and s[0] == 6
                 and isinstance(s[1], str)), "x")
    title = next((x for x in item[6:] if isinstance(x, str)), "")
    # NC/SC border runs ~lat 35.0 in the west; good-enough first cut, downstream county GIS corrects it.
    state = "SC" if lat < 35.0 else "NC"
    url = f"https://{host}/reo/d/{slug}/{pid}.html"
    now = datetime.utcnow()
    return Listing(
        source="national.craigslist_fsbo",
        source_url=url,
        listing_type=ListingType.DISTRESSED,     # FSBO = motivated-seller / pre-foreclosure signal
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        latitude=lat,
        longitude=lng,
        description=(f"Craigslist FSBO ({host.split('.')[0]}): {title[:120]}"
                     + (f" — asking ${price:,.0f}" if price else "")),
        first_seen=now,
        last_seen=now,
        raw={"craigslist": {"posting_id": pid, "list_price": price, "region": host,
                            "title": title[:200]}},
    )


class CraigslistFSBO(BaseScraper):
    slug = "national.craigslist_fsbo"
    name = "Craigslist FSBO (NC/SC real estate by owner)"
    category = "fsbo"
    requires_apify = False
    requires_render = False
    expected_min_count = 0     # volume varies; a quiet region legitimately returns few
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set = set()
        for host, area in AREAS.items():
            try:
                import json
                data = (json.loads(await get_text(_SAPI.format(area=area), timeout=25,
                                                  impersonate=True)).get("data")) or {}
                items = data.get("items") or []
                min_pid = (data.get("decode") or {}).get("minPostingId")
            except Exception as e:  # noqa: BLE001 — one region's blip must not kill the rest
                log.warning("craigslist_fsbo.region_err", host=host, err=str(e)[:80])
                continue
            if not isinstance(min_pid, int):
                continue   # can't build valid URLs without the delta base — skip region
            for it in items:
                li = _listing_from_item(it, host, min_pid)
                if li and li.raw["craigslist"]["posting_id"] not in seen:
                    seen.add(li.raw["craigslist"]["posting_id"])
                    out.append(li)
        log.info("craigslist_fsbo.done", found=len(out))
        return out
