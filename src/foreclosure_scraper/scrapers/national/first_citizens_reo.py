"""First Citizens Bank — bank-direct REO (OREO) listings.

Discovered 2026-06-16. First Citizens (Raleigh NC HQ, huge NC/SC footprint)
publishes its bank-owned real estate PUBLICLY at firstcitizens.com/real-estate
to avoid broker commissions — a clean HTML table (Location | Price | Type |
Description | Broker). This is genuine bank-direct REO, the category most
banks gate behind agent logins; First Citizens is the rare one that posts it
openly.

FOUND 2026-10-04 (national.* extraction-completeness audit, batch 16): the
rendered page's table is populated from the page's OWN AEM data attribute,
``data-real-estate-url="/real-estate/_jcr_content/.../realestate.default.json"``
-- a free, public, no-auth JSON endpoint with the SAME 26 rows the rendered
table shows, already pre-split into clean `city`/`state`/`propertyType`/
`phone`/`email` fields (live-confirmed: no more HTML-flattened "Rob
Cuccinello239-537-5533" text to split, no mailto:/tel: href workaround
needed). This is now the PRIMARY path — curl-cffi impersonation alone is
enough (confirmed live: plain `curl_cffi.requests.get(impersonate="chrome")`
returns the JSON directly), no headless-browser render required at all. The
original render+HTML-table `parse()` is kept as a fallback for resilience if
this JSON path ever a) 404s or b) changes shape.

ALSO FOUND the same day: no row from this scraper, on EITHER path, has ever
carried a `county` -- confirmed via code inspection, no `county=` kwarg
anywhere. `main._countyless_national()` drops ANY `national.*` row with no
county outright, so every genuinely in-footprint listing this source has
ever produced (if any) would have been silently dropped at the very last
stage, with the row otherwise looking completely correct. Fixed by
resolving county from the clean city/state via the same upstate/coastal
gazetteer helpers `national.gsa_surplus` / `national.hud_reac_inspection`
already use, on both the JSON and the HTML-fallback path.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable

import structlog
from curl_cffi import requests as cf
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ..._coastal_city_to_county import coastal_county_for
from ..._upstate_city_to_county import upstate_county_for
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URL = "https://www.firstcitizens.com/real-estate"
JSON_URL = (
    "https://www.firstcitizens.com/real-estate/_jcr_content/root/"
    "globalLayoutContainer/globalLayoutContainer-parsys/layout_container/"
    "col1/realestate.default.json"
)

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


def _county_for(city: str | None, state: str) -> str | None:
    """In-footprint county for a city (upstate/WNC gazetteer, then
    coastal) -- a bank-wide national feed has no county of its own, and
    without one `main._countyless_national()` drops the row outright
    regardless of how correct everything else on it is."""
    if not city:
        return None
    return upstate_county_for(city, state) or coastal_county_for(city, state)


def _kind_for(ptype: str) -> PropertyKind:
    low = (ptype or "").lower()
    for k, v in _TYPE_MAP.items():
        if k in low:
            return v
    return PropertyKind.UNKNOWN


def parse_json(text: str) -> list[Listing]:
    """Parse the free, public, no-auth JSON feed the page's own AEM
    component reads from -- clean city/state/propertyType/phone/email
    fields, no HTML-table cell-flattening to work around. Primary path;
    see module docstring."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    rows = data.get("realEstateData") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []

    out: list[Listing] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        state = (row.get("state") or "").strip().upper()
        if state not in ("NC", "SC"):
            continue
        city = (row.get("city") or "").strip() or None
        full_addr = (row.get("propertyAddress") or "").strip()
        lm = _LOC_RE.match(full_addr)
        street = lm.group("street").strip() if lm else full_addr or None
        zip_code = lm.group("zip") if lm else None
        ptype = row.get("propertyType") or ""
        price_raw = row.get("price") or ""
        broker = (row.get("broker") or "").strip() or None
        broker_email = (row.get("email") or "").strip() or None
        broker_phone = (row.get("phone") or "").strip() or None

        out.append(
            Listing(
                source="national.first_citizens_reo",
                source_url=URL,
                listing_type=ListingType.REO,
                property_kind=_kind_for(ptype),
                state=state,
                county=_county_for(city, state),
                street_address=street,
                city=city,
                zip_code=zip_code,
                opening_bid=_money(price_raw),
                description=(f"{ptype}: {row.get('description') or ''}".strip(": ") or None),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"first_citizens_reo": {
                    "broker": broker, "type": ptype,
                    "broker_email": broker_email,
                    "broker_phone": broker_phone,
                    "price_text": price_raw or None,
                }},
            )
        )
    return out


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
            # Found 2026-10-01 (national/reo per-source audit): the broker
            # cell's live markup is two separate anchors --
            # <a href="mailto:...">Name</a><br><a href="tel:+1...">phone</a>
            # -- that .text() flattens with NO separator ("Rob
            # Cuccinello239-537-5533"), and the mailto: address (a free,
            # direct contact channel -- HERMES's whole mission is finding a
            # free way to reach the owner/broker) was dropped on the floor
            # entirely. Pulled straight from the href attributes instead of
            # the flattened display text, which also sidesteps that text's
            # aria-label-driven digit spacing ("2 3 9. 5 3 7. 5 5 3 3.").
            broker_cell = tr.css("th,td")[idx["broker"]] if "broker" in idx else None
            broker_email = broker_phone = None
            if broker_cell is not None:
                mailto = broker_cell.css_first("a[href^='mailto:']")
                if mailto is not None:
                    broker_email = (mailto.attributes.get("href") or "")[7:].strip() or None
                tel = broker_cell.css_first("a[href^='tel:']")
                if tel is not None:
                    broker_phone = (tel.attributes.get("href") or "")[4:].strip() or None

            city = lm.group("city").strip()

            out.append(
                Listing(
                    source="national.first_citizens_reo",
                    source_url=URL,
                    listing_type=ListingType.REO,
                    property_kind=_kind_for(ptype),
                    state=state,
                    # Found 2026-10-04 (national.* extraction-completeness
                    # audit, batch 16): no row from this scraper, on
                    # either path, has ever carried a county.
                    # main._countyless_national() drops ANY national.*
                    # row with no county outright -- see module docstring.
                    county=_county_for(city, state),
                    street_address=lm.group("street").strip(),
                    city=city,
                    zip_code=lm.group("zip"),
                    opening_bid=price,
                    description=(f"{ptype}: {desc}".strip(": ") or None),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"first_citizens_reo": {
                        "broker": broker, "type": ptype,
                        "broker_email": broker_email,
                        "broker_phone": broker_phone,
                    }},
                )
            )
    return out


async def _fetch_json_text(url: str) -> str:
    """The free, public JSON feed -- curl-cffi impersonation alone is
    enough (confirmed live 2026-10-04), no headless browser needed."""
    import asyncio

    def _sync() -> str:
        try:
            r = cf.get(url, impersonate="chrome", timeout=20)
            if r.status_code == 200 and len(r.text) > 20:
                return r.text
        except Exception as exc:
            log.warning("first_citizens_reo.json_fetch_failed", error=str(exc)[:160])
        return ""
    return await asyncio.to_thread(_sync)


async def _render_html(url: str) -> str:
    """Return rendered HTML (not text) — we need the table markup.
    Fallback path only (see module docstring) -- the JSON feed is primary."""
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
    # requires_render stays True even though the JSON primary path needs no
    # browser: the fallback path still does, and this flag governs how a
    # bad run on THIS source is classified/treated for stale-carryover.
    requires_render = True
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        text = await _fetch_json_text(JSON_URL)
        if text:
            out = parse_json(text)
            if out or '"realEstateData"' in text:
                # Either real rows, or a confirmed-empty-but-real feed
                # (genuinely 0 current NC/SC listings) -- either way the
                # JSON path answered, so don't also pay for a browser render.
                return out
        # JSON path failed or returned something unrecognizable -- fall
        # back to the original render+HTML-table path.
        html = await _render_html(URL)
        if not html:
            return []
        return parse(html)
