"""OfferUp — investigated 2026-08-12, NOT viable via public HTML. Not wired.

WHY IT LOOKED PROMISING
    OfferUp is a strong private-party bargain pool and its pages server-render a
    `<script id="__NEXT_DATA__">` blob with clean listing JSON (listingId, title,
    price, vehicleMiles, locationName, image). No login, no CAPTCHA.

WHY IT DOES NOT WORK
    Two dead ends, both of which return HTTP 200:

    1. `offerup.com/explore/k/9/<query>` IGNORES the query. Every slug
       (`porsche`, `porsche-911`, `911 porsche`) returns the same 44-tile
       generic Cars & Trucks feed. One fetch happened to be Porsches; the next
       was washing machines and dryers. The keyword does nothing, so the porsche
       filter correctly drops the lot and the source yields 0 — a source that
       returns 0 or laundry appliances is worse than no source.

    2. `offerup.com/search?q=porsche` DOES honour the keyword but SSR-ships only
       two tiles; the rest paginates through a token-gated internal API.

    Reaching real OfferUp Porsche results means reverse-engineering that API
    (auth headers, persisted-query ids), which is a real project and not a
    keyless public fetch. Recorded here so the next pass does not re-discover the
    explore endpoint and mistake its generic feed for a working search.

    The parser below is kept and correct for the ModularFeedTileListing shape,
    so if the API path is ever built it can feed straight into it.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from ..base import BaseScraper
from ..http_client import fetch_text_stealth
from ..models import Listing, infer_drivable, infer_title_status, parse_year

log = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

#: Explore-category slug 9 is Cars & Trucks. One query per model keeps each
#: page focused and dodges the plain-search two-tile ceiling.
_QUERIES = ("porsche-911", "porsche-cayman", "porsche-boxster",
            "porsche-718", "porsche")


def _collect_tiles(node, out: list[dict]) -> None:
    """Recursively harvest every listing tile from the Next.js payload."""
    if isinstance(node, dict):
        if node.get("__typename") == "ModularFeedTileListing" and node.get("listing"):
            out.append(node["listing"])
        for v in node.values():
            _collect_tiles(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_tiles(v, out)


def parse_offerup_html(html: str) -> Iterable[Listing]:
    """Parse one explore page into Listings. Best-effort; skips malformed tiles."""
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return

    tiles: list[dict] = []
    _collect_tiles(data, tiles)

    seen: set[str] = set()
    for t in tiles:
        lid = t.get("listingId")
        if not lid or lid in seen:
            continue
        seen.add(lid)

        title = (t.get("title") or "").strip()
        low = title.lower()
        if "porsche" not in low:
            continue
        if any(em in low for em in ("panamera", "macan")):
            continue

        price_raw = t.get("price")
        try:
            price_val = float(price_raw) if price_raw not in (None, "") else None
        except (TypeError, ValueError):
            price_val = None

        miles = t.get("vehicleMiles")
        img = (t.get("image") or {}).get("url")
        status = infer_title_status(title)
        listing = Listing(
            source="offerup",
            source_url=f"https://offerup.com/item/detail/{lid}",
            listing_id=str(lid),
            title=title,
            year=parse_year(title),
            mileage=int(miles) if isinstance(miles, (int, float)) else None,
            price_usd=price_val,
            location=t.get("locationName"),
            photo_url=img,
            title_status=status,
            seller_type="private",
        )
        listing.drivable = infer_drivable(title, status)
        yield listing


class OfferUpScraper(BaseScraper):
    """Private-party Porsche listings from OfferUp's public explore pages."""

    slug = "offerup"
    name = "OfferUp"
    timeout_s = 180.0

    def __init__(self, *, price_max: int = 40_000, year_min: int = 2014):
        self.price_max = price_max
        self.year_min = year_min

    async def fetch(self) -> list[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for q in _QUERIES:
            url = f"https://offerup.com/explore/k/9/{q}"
            try:
                html = await fetch_text_stealth(url, timeout=60)
            except Exception as exc:  # noqa: BLE001 - one bad query must not kill the rest
                log.warning("offerup query %s failed: %s", q, exc)
                continue
            for li in parse_offerup_html(html):
                if li.listing_id and li.listing_id not in seen:
                    seen.add(li.listing_id)
                    out.append(li)
        log.info("offerup: %d unique listings across %d queries", len(out), len(_QUERIES))
        return out
