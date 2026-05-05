"""USDA Rural Development resale properties — federal REO source.

USDA RD lists single-family + multi-family + farm/ranch properties
foreclosed by Rural Development. Free, no auth, plain HTML.

Endpoints (verified 2026-05):
  * SFH:  https://www.resales.usda.gov/resales/public/searchSFH?state=NC
  * MFH:  https://www.resales.usda.gov/resales/public/searchMFH?state=NC
  * FSA:  https://www.resales.usda.gov/resales/public/searchFSA?state=NC

Volume is small (typically 0-10 per state) but the listings are
high-quality and clean: USDA RD pre-vets title before listing, so
they're closer to retail-ready than sheriff sales.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


_STATES = ("NC", "SC")
_BASE = "https://www.resales.usda.gov/resales/public"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
_ADDR_RE = re.compile(
    r"^\s*(\d{1,5}\s+[A-Z][\w .'\-]+?)\s*,\s*([A-Z][\w .'\-]+?)\s*,\s*([A-Z]{2})\s*(\d{5})?",
    re.M,
)


async def _fetch_state(state: str, kind: str = "SFH") -> list[Listing]:
    """Pull one state's listings from the named endpoint."""
    url = f"{_BASE}/search{kind}?state={state}"
    async with client(timeout=30.0) as c:
        try:
            r = await c.get(url, headers=_HEADERS)
        except Exception as exc:
            log.warning("usda_rd.fetch_failed", state=state, kind=kind,
                        error=str(exc)[:200])
            return []
    if r.status_code != 200 or len(r.text) < 1000:
        return []

    tree = HTMLParser(r.text)
    out: list[Listing] = []
    seen: set[str] = set()

    # USDA's listing format puts each property in a <tr> or detail block.
    # We anchor on detail-page anchors which are the most reliable signal.
    detail_anchors = tree.css(
        "a[href*='detail'], a[href*='property'], a[href*='resales/public/detail']"
    )
    for a in detail_anchors:
        href = a.attributes.get("href", "")
        if not href:
            continue
        # Walk up to the row/card containing this anchor for context
        node = a
        block_text = ""
        for _ in range(6):
            parent = node.parent
            if parent is None:
                break
            txt = parent.text(separator=" ")
            if len(txt) > 80:
                block_text = txt
                break
            node = parent
        if not block_text:
            block_text = a.text() or ""

        # Address pattern: "123 Main St, Some City, NC 27606"
        addr_m = _ADDR_RE.search(block_text)
        if not addr_m:
            continue
        street, city, st, zip_code = addr_m.groups()
        if st not in _STATES:
            continue
        # Price (best-effort; USDA shows asking on the search page sometimes)
        price = None
        pm = _PRICE_RE.search(block_text)
        if pm:
            try:
                price = float(pm.group(1).replace(",", ""))
            except ValueError:
                price = None

        full_url = href if href.startswith("http") else f"{_BASE}/{href.lstrip('/')}"
        if full_url in seen:
            continue
        seen.add(full_url)

        kind_map = {
            "SFH": PropertyKind.SINGLE_FAMILY,
            "MFH": PropertyKind.MULTI_FAMILY,
            "FSA": PropertyKind.LAND,
        }
        out.append(Listing(
            source="reo.usda_rd",
            source_url=full_url,
            listing_type=ListingType.REO,
            property_kind=kind_map.get(kind, PropertyKind.UNKNOWN),
            state=st,
            street_address=street.strip(),
            city=city.strip(),
            zip_code=zip_code or None,
            opening_bid=price,
            description=f"USDA Rural Development {kind} REO ({state})",
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"usda_rd": {"kind": kind, "block": block_text[:500]}},
        ))
    log.info("usda_rd.state_done", state=state, kind=kind, count=len(out))
    return out


class USDARuralDevelopment(BaseScraper):
    slug = "reo.usda_rd"
    name = "USDA Rural Development REO (NC + SC)"
    category = "federal_reo"
    expected_min_count = 0  # Often 0 in either state
    requires_apify = False
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in _STATES:
            for kind in ("SFH", "MFH", "FSA"):
                try:
                    out.extend(await _fetch_state(state, kind))
                except Exception as exc:
                    log.warning("usda_rd.state_failed", state=state, kind=kind,
                                error=str(exc)[:200])
        log.info("usda_rd.done", total=len(out))
        return out
