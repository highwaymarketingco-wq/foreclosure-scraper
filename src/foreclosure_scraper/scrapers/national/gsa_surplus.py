"""GSA "Assets identified for accelerated disposition" — federal real
property GSA is actively trying to sell/dispose of.

Rewritten 2026-09-15 (national.* zero-row audit): the old target URL
(gsa.gov/real-estate/real-estate-listings) is a hard 404 today, and the
loose regex-over-whatever-blocks-matched extraction it used was the same
risky "grab any address/state pattern anywhere on the page" shape that
turned into a garbage emitter elsewhere in this project (see
docs/WEEKEND_LOOP_QUEUE.md). Neither survives contact with the real page.

The real page is a clean, server-rendered USWDS card list at:
  https://www.gsa.gov/real-estate/real-property-disposition/assets-identified-for-accelerated-disposition

Each property is one `<li class="usa-card ... js-filterable" data-state='"XX"'>`
with a real per-card `data-state` attribute (not inferred from nearby text),
a `<h3>` name, a maps-linked address `<a>`, a Type/Rentable-Area line, and a
`<ul class="usa-collection__meta">` with a "Date listed: M/D/YYYY" tag and,
when the deal has closed, a second tag ("SOLD"/"DISPOSED"/"UNDER CONTRACT").

Free, public, no login.
Slug: national.gsa_surplus
Category: reo
ListingType: REO
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SALES_URL = (
    "https://www.gsa.gov/real-estate/real-property-disposition/"
    "assets-identified-for-accelerated-disposition"
)

_TARGET_STATES = {"NC", "SC"}
# GSA's own closed-deal tags -- same vocabulary TERMINAL_AUCTION_STATUSES
# already recognizes elsewhere ("sold", "disposed").
_CLOSED_TAGS = {"SOLD", "DISPOSED", "UNDER CONTRACT"}

_AREA_RE = re.compile(r"([\d,]+)\s*ft", re.I)
_DATE_RE = re.compile(r"Date listed:\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)


def _unquote(v: str | None) -> str:
    """The data-state attribute's raw value is a JSON-quoted string
    ('"SC"') because the source HTML embeds a JS literal — strip the
    literal quote characters."""
    return (v or "").strip().strip('"')


def _parse_card(card, source_url: str) -> Listing | None:
    state = _unquote(card.attributes.get("data-state")).upper()
    if state not in _TARGET_STATES:
        return None

    tags = [t.text(strip=True) for t in card.css("ul.usa-collection__meta li")]
    if any(t.upper() in _CLOSED_TAGS for t in tags):
        return None  # already sold/disposed/under contract — not actionable

    name_el = card.css_first("h3.usa-card__heading")
    name = name_el.text(strip=True) if name_el else None

    addr_el = card.css_first("a.usa-link--external")
    full_addr = addr_el.text(strip=True) if addr_el else None
    maps_url = addr_el.attributes.get("href") if addr_el else None
    if not full_addr:
        return None

    # "315 S. McDuffie St, Anderson, SC 29624" -> street / city / zip
    m = re.match(r"^(.*?),\s*([^,]+?),\s*[A-Z]{2}\s+(\d{5})", full_addr)
    street = m.group(1).strip() if m else full_addr
    city = m.group(2).strip() if m else None
    zip_code = m.group(3) if m else None

    body_text = card.css_first("div.usa-card__body")
    body_text = body_text.text(separator=" ") if body_text else ""
    type_m = re.search(r"Type:\s*([^\n]+?)(?:Rentable Area|Garage Rentable Area|Area:)", body_text)
    prop_type = type_m.group(1).strip() if type_m else None
    area_m = _AREA_RE.search(body_text)
    area_sqft = None
    if area_m:
        try:
            area_sqft = float(area_m.group(1).replace(",", ""))
        except ValueError:
            pass

    date_m = _DATE_RE.search(body_text)

    return Listing(
        source="national.gsa_surplus",
        source_url=maps_url or source_url,
        listing_type=ListingType.REO,
        property_kind=PropertyKind.UNKNOWN,
        street_address=street or None,
        city=city,
        state=state,
        zip_code=zip_code,
        living_sqft=area_sqft,
        description=f"GSA accelerated disposition — {name or 'federal property'}"
                    + (f" ({prop_type})" if prop_type else ""),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"gsa_surplus": {"name": name, "type": prop_type,
                              "date_listed": date_m.group(1) if date_m else None,
                              "maps_url": maps_url}},
        # No sale_date: this is a negotiated disposition, not a scheduled
        # auction -- "Date listed" is when GSA started marketing it, not a
        # sale date. Dateless by nature; see DATELESS_OK_SOURCES.
    )


class GSASurplus(BaseScraper):
    slug = "national.gsa_surplus"
    name = "GSA Assets Identified for Accelerated Disposition"
    category = "reo"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(SALES_URL, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("gsa_surplus.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 500:
            return out

        tree = HTMLParser(html)
        for card in tree.css("li.usa-card"):
            li = _parse_card(card, SALES_URL)
            if li:
                out.append(li)

        log.info("gsa_surplus.fetch_done", count=len(out))
        return out
