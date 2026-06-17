"""First Citizens Bank — bank-direct REO (OREO) listings.

Discovered 2026-06-16. First Citizens (Raleigh NC HQ, huge NC/SC footprint)
publishes its bank-owned real estate PUBLICLY at firstcitizens.com/real-estate
to avoid broker commissions — a clean HTML table (Location | Price | Type |
Description | Broker). This is genuine bank-direct REO, the category most
banks gate behind agent logins; First Citizens is the rare one that posts it
openly. The page 403s to plain HTTP (Akamai) but renders via the local
stealth browser.

We keep only NC/SC rows (parsed from the Location cell) — the bank lists
multi-state inventory.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URL = "https://www.firstcitizens.com/real-estate"

# "7120 Myrtle Grove Rd, Wilmington, NC 28412"
_LOC_RE = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>[A-Za-z .'-]+?),\s*(?P<state>NC|SC)\s*(?P<zip>\d{5})?",
)
_TYPE_MAP = {
    "vacant land": PropertyKind.LAND,
    "land": PropertyKind.LAND,
    "commercial": PropertyKind.COMMERCIAL,
    "residential": PropertyKind.SINGLE_FAMILY,
    "single family": PropertyKind.SINGLE_FAMILY,
    "multi": PropertyKind.MULTI_FAMILY,
}


def _money(s: str) -> float | None:
    m = re.search(r"\$\s?([\d,]+(?:\.\d{2})?)", s or "")
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
        return v if v > 0 else None
    except ValueError:
        return None


def parse(html: str) -> list[Listing]:
    """Parse the First Citizens REO table, keeping NC/SC rows."""
    out: list[Listing] = []
    tree = HTMLParser(html)
    for table in tree.css("table"):
        rows = table.css("tr")
        if len(rows) < 2:
            continue
        header = [re.sub(r"\s+", " ", c.text()).strip().lower() for c in rows[0].css("th,td")]
        if "location" not in header or "broker" not in header:
            continue
        idx = {h: i for i, h in enumerate(header)}
        for tr in rows[1:]:
            # Location is a row-header <th>; the rest are <td> — read both.
            cells = [re.sub(r"\s+", " ", c.text()).strip() for c in tr.css("th,td")]
            if len(cells) < len(header):
                continue
            loc = cells[idx.get("location", 0)]
            lm = _LOC_RE.match(loc)
            if not lm:
                continue  # not NC/SC (or unparseable) — skip
            state = lm.group("state")
            ptype = cells[idx["type"]] if "type" in idx else ""
            desc = cells[idx["description"]] if "description" in idx else ""
            price = _money(cells[idx["price"]]) if "price" in idx else None
            broker = cells[idx["broker"]] if "broker" in idx else ""

            kind = PropertyKind.UNKNOWN
            for k, v in _TYPE_MAP.items():
                if k in ptype.lower():
                    kind = v
                    break

            out.append(
                Listing(
                    source="national.first_citizens_reo",
                    source_url=URL,
                    listing_type=ListingType.REO,
                    property_kind=kind,
                    state=state,
                    street_address=lm.group("street").strip(),
                    city=lm.group("city").strip(),
                    zip_code=lm.group("zip"),
                    opening_bid=price,
                    description=(f"{ptype}: {desc}".strip(": ") or None),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"first_citizens_reo": {"broker": broker, "type": ptype}},
                )
            )
    return out


async def _render_html(url: str) -> str:
    """Return rendered HTML (not text) — we need the table markup."""
    import asyncio

    def _sync() -> str:
        try:
            from scrapling.fetchers import StealthyFetcher
            page = StealthyFetcher.fetch(url, headless=True, timeout=45000, network_idle=True)
            return page.html_content or ""
        except Exception:
            return ""
    return await asyncio.to_thread(_sync)


class FirstCitizensREO(BaseScraper):
    slug = "national.first_citizens_reo"
    name = "First Citizens Bank REO (NC/SC)"
    category = "bank_reo"
    expected_min_count = 0
    requires_render = True
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        html = await _render_html(URL)
        if not html:
            return []
        return parse(html)
