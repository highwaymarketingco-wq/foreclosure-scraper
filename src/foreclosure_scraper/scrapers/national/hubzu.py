"""Hubzu (REO + foreclosure auctions) via the public JSON endpoint.

The old assumption — that listings only load via an authenticated XHR after JS —
is false. `GET /portal/auctions?state={ST}&pageSize=200` returns the full result
set as JSON (data.srpTupples[]) with no auth, no cookie, no render. Each tuple
carries a clean address (propAddress: street/city/county/state/zip), category
(FORECLOSURE / REO), starting + current bid, beds/baths/sqft/lot, lat/lng, and
the auction end date. 100% free; the pipeline's scope filter keeps in-county rows.

ADDED 2026-10-13 (source-completeness audit, Pattern B — "national
real-estate-listing scrapers keep one photo when the API has many"): the
search tuple's own `imageUrl`/`photoCount` already hinted at more (a
`photoCount` of 5 while only 1 photo was ever kept), and live-checking
confirmed it — each listing's React detail page is a client-rendered SPA
shell with no server HTML to scrape, but it calls a second free, no-auth
JSON endpoint for its own data: `GET /portal/property/getNewPdpDetails/
<propertyId>` (propertyId = the leading digits of the search tuple's
`listingId`, e.g. "9321811956" out of "9321811956AUCN7" — the `AUCN<n>`
suffix is an auction-round tag the detail endpoint 404s on). Its
`propertyDetails.imageDetails[]` carries the full gallery. Live-sampled 4
current NC listings 2026-10-13: photoCount 2/5/5/15 each matched the
detail endpoint's real image count exactly (2, 5, 5, 15 images) -- a
real, previously-uncaptured gallery, same miss class as freddie_homesteps/
hud_homestore's own 2026-10-04 fixes. Mirrors their pattern: fetch each
listing's detail resource (budgeted, self.partial-sunk so a timeout cut-off
still ships the already-parsed rows), dedupe, cap at GALLERY_CAP.
"""
from __future__ import annotations

import re
import time
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


def _photo_url(v) -> str | None:
    """The JSON's imageUrl is protocol-relative ("//image-prod.hubzu.com/...")
    -- found 2026-10-01 (national/reo per-source audit): the API response
    already carries a real per-property photo (confirmed live, photoCount
    matches a working image URL) plus the listing agent/broker name, and
    neither was captured, same miss class already fixed today in
    national.gsa_surplus / servicelink_auction / tranzon_auctions."""
    s = (v or "").strip()
    if not s:
        return None
    if s.startswith("//"):
        return f"https:{s}"
    if s.startswith("http"):
        return s
    return None


#: Per-listing gallery detail endpoint -- see module docstring addendum
#: (2026-10-13). No auth, no cookie; same free-JSON posture as the search API.
DETAIL_API = "https://www.hubzu.com/portal/property/getNewPdpDetails/{property_id}"
#: Live-confirmed real galleries run 2-15 photos (2026-10-13 sample); cap
#: mirrors freddie_homesteps's own GALLERY_CAP of 8.
GALLERY_CAP = 8
#: Share of timeout_s the per-listing gallery calls may use, split evenly across the
#: states. The list-page rows are handed to the scraper's partial list before any
#: detail call, so a cut-off still ships them (mirrors freddie_homesteps /
#: hud_homestore / usda_properties's own DETAIL_BUDGET_SHARE pattern).
DETAIL_BUDGET_SHARE = 0.8

_PROPERTY_ID_RE = re.compile(r"^(\d+)")


def _property_id(listing_id) -> str | None:
    """The search tuple's `listingId` is e.g. "9321811956AUCN7" -- the leading
    digits are the real property id the getNewPdpDetails endpoint takes; the
    trailing "AUCN<n>" auction-round tag makes that endpoint 404. Confirmed
    live 2026-10-13 against multiple current NC listings."""
    s = str(listing_id or "").strip()
    m = _PROPERTY_ID_RE.match(s)
    return m.group(1) if m else None


def _gallery_photos(detail: dict) -> list[str]:
    """The full photo gallery from a getNewPdpDetails response. The search
    endpoint's own `imageUrl` is only ever the first/default image
    (`defaultImage: true` on that same entry here); `imageDetails[]` is the
    real gallery, confirmed live 2026-10-13 to match each listing's own
    `photoCount` exactly."""
    images = ((detail or {}).get("propertyDetails") or {}).get("imageDetails") or []
    out: list[str] = []
    for img in images:
        if not isinstance(img, dict):
            continue
        url = _photo_url(img.get("imageStoragePath"))
        if url and url not in out:
            out.append(url)
    return out[:GALLERY_CAP]


def _parse_item(item: dict, state: str) -> Listing | None:
    pa = item.get("propAddress") or {}
    street = f"{(pa.get('streetNumber') or '').strip()} {(pa.get('streetName') or '').strip()}".strip()
    url = item.get("listingUrl") or ""
    if not street or not url:
        return None
    cat = (item.get("propertyCategory") or "").strip().upper()
    photo = _photo_url(item.get("imageUrl"))
    li = Listing(
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
        # listingPrice is the site's own marketed/list price -- a distinct
        # valuation signal from startingBid (the auction opening bid), NOT
        # a duplicate. Found 2026-10-04 (national.* extraction-completeness
        # audit, batch 16): live-sampled 132 current NC+SC rows, 42 (32%)
        # carry a non-empty listingPrice, and it differs from startingBid
        # on 41 of those 42 -- real data, never captured before. Mapped to
        # market_value (the convention this project's county-assessor
        # scrapers already use for a vendor-stated valuation, distinct
        # from the bid itself).
        market_value=_money(item.get("listingPrice")),
        raw={"hubzu": {"category": cat, "subtype": item.get("propertySubType"),
                       "listing_id": item.get("listingId"), "current_bid": item.get("currentBid"),
                       "status": item.get("listingStatus"),
                       "broker": (item.get("agentCompanyName") or "").strip() or None,
                       "photo_count": item.get("photoCount"),
                       "listing_price": _money(item.get("listingPrice")),
                       # Real Y/N signal on whether the property is
                       # currently occupied -- found in the same audit,
                       # never captured before (useful REO context: an
                       # occupied former-owner property vs. a vacant one).
                       "occupancy_status": (item.get("occupancyStatus") or "").strip() or None}},
    )
    if photo:
        li.raw["images"] = {"real": [photo]}
    return li


class Hubzu(BaseScraper):
    slug = "national.hubzu"
    name = "Hubzu (REO + foreclosure auctions, free JSON)"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    # 60 s until 2026-10-13. Added the per-listing gallery call below (see module
    # docstring): NC+SC together run ~140 listings, one extra request each, spaced
    # by the shared client's per-host throttle (~1s/request) -- that alone is
    # ~140s, past the old 60s. 240 s mirrors usda_properties's own budget for a
    # similarly sized (~112-request) per-listing detail fan-out; the budget below
    # stops the gallery calls in time regardless, and every list-page row is in
    # self.partial before its gallery call, so a cut-off still ships them (with
    # just their single already-known photo).
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        start, budget = time.monotonic(), self.timeout_s * DETAIL_BUDGET_SHARE
        states = ("NC", "SC")
        async with client(timeout=30.0, headers=_HEADERS) as c:
            for i, st in enumerate(states):
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
                state_listings: list[Listing] = []
                for item in tuples:
                    li = _parse_item(item, st)
                    if not li:
                        continue
                    key = (li.raw.get("hubzu") or {}).get("listing_id") or li.source_url
                    if key in seen:
                        continue
                    seen.add(key)
                    state_listings.append(li)
                # Ship the list-page rows now -- a timeout during the gallery
                # calls below still salvages these via self.partial.
                self.partial.extend(state_listings)
                out.extend(state_listings)
                log.info("hubzu.state_done", state=st, count=len(state_listings))

                # Per-listing full-gallery enrichment (see module docstring
                # addendum, 2026-10-13): the search tuple only ever carries one
                # photo; the free getNewPdpDetails JSON endpoint has the rest.
                deadline = start + budget * (i + 1) / len(states)
                n_done = 0
                for li in state_listings:
                    if time.monotonic() > deadline:
                        log.info("hubzu.gallery_budget_spent", state=st,
                                 fetched=n_done, skipped=len(state_listings) - n_done)
                        break
                    n_done += 1
                    pid = _property_id((li.raw.get("hubzu") or {}).get("listing_id"))
                    if not pid:
                        continue
                    try:
                        dr = await c.get(DETAIL_API.format(property_id=pid))
                    except Exception as exc:  # noqa: BLE001
                        log.warning("hubzu.detail_fetch_failed", listing_id=pid,
                                    error=str(exc)[:160])
                        continue
                    if dr.status_code != 200:
                        continue
                    try:
                        detail = dr.json()
                    except ValueError:
                        continue
                    photos = _gallery_photos(detail)
                    if not photos:
                        continue
                    have = li.raw.setdefault("images", {}).setdefault("real", [])
                    for p in photos:
                        if p not in have:
                            have.append(p)
                    if len(have) > GALLERY_CAP:
                        del have[GALLERY_CAP:]
        log.info("hubzu.done", count=len(out))
        return out
