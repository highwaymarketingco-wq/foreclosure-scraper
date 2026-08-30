"""Estate sale company listings from estatesales.net and estatesale.com.

Estate liquidation events often indicate that a property is being sold —
either the owner has died (probate) or is downsizing/relocating. These
listings provide the event address and dates, which we cross-reference
against tax records to identify properties being liquidated.

Sources (free, no auth):
  - estatesales.net  — search by zip code, returns JSON + HTML
  - estatesale.com   — search by location, HTML listings

We search by zip code for our footprint cities:
  - Asheville NC 28801 (Buncombe)
  - Hendersonville NC 28792 (Henderson)
  - Shelby NC 28150 (Cleveland)
  - Gastonia NC 28052 (Gaston)
  - Spartanburg SC 29302 (Spartanburg)
  - Greenville SC 29601 (was in footprint historically)
  - Charlotte NC 28202 (Gastonia/Cleveland corridor)

Extract: event title, address, dates, company name, description.
Listing type: ESTATE_LEAD (property may be in probate or motivated sale).
source: "national.estate_sales"

Robots.txt checked per host; fail-closed if disallowed.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin, quote_plus

import httpx
import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# (zip_code, city, state, county)
SEARCH_ZIPS: tuple[tuple[str, str, str, str], ...] = (
    ("28801", "Asheville", "NC", "Buncombe"),
    ("28792", "Hendersonville", "NC", "Henderson"),
    ("28150", "Shelby", "NC", "Cleveland"),
    ("28052", "Gastonia", "NC", "Gaston"),
    ("29302", "Spartanburg", "SC", "Spartanburg"),
    ("29601", "Greenville", "SC", "Greenville"),
    ("28202", "Charlotte", "NC", "Mecklenburg"),
)

ESTATESALES_NET_BASE = "https://www.estatesales.net"
ESTATESALE_COM_BASE = "https://www.estatesale.com"

ADDR_RE = re.compile(
    r"\d+\s+[A-Z][\w .'#-]+"
    r"(?:\s+(?:St|Street|Rd|Road|Dr|Drive|Ave|Avenue|Ln|Lane|Ct|Court|"
    r"Blvd|Boulevard|Hwy|Highway|Pl|Place|Way|Cir|Circle|Trl|Trail|"
    r"Pkwy|Parkway|Ter|Terrace))\b\.?",
    re.I,
)
DATE_RE = re.compile(
    r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}"
    r"(?:\s*[-–to]+\s*\d{1,2})?,?\s*\d{4}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b)",
    re.I,
)


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    for fmt in (
        "%B %d, %Y", "%b %d, %Y",
        "%B %d %Y", "%b %d %Y",
        "%m/%d/%Y", "%m/%d/%y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    m = DATE_RE.search(text)
    if m:
        s = m.group(1)
        # Handle date ranges like "Jul 15-17, 2026" — take first date
        s = re.split(r"[-–to]+", s)[0].strip()
        for fmt in (
            "%B %d, %Y", "%b %d, %Y",
            "%B %d %Y", "%b %d %Y",
            "%m/%d/%Y", "%m/%d/%y",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


async def _robots_allows(host: str, path: str) -> bool:
    """Check robots.txt. Fails OPEN if unreachable."""
    robots_url = f"https://{host}/robots.txt"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(robots_url)
            if r.status_code != 200:
                return True
            body = r.text or ""
    except Exception:
        return True

    ua_star = False
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            ua_star = value == "*"
        elif ua_star and field == "disallow":
            if value and (path == value or path.startswith(value)):
                return False
    return True


async def _fetch_text(url: str, timeout: float = 20.0,
                      headers: dict | None = None) -> str:
    from ...http_client import client
    h = {"Accept": "text/html,application/json,*/*"}
    if headers:
        h.update(headers)
    async with client(timeout=timeout, headers=h) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.text


# --- schema.org JSON-LD SaleEvent ------------------------------------------

def _saleevent_to_listing(node: dict, source_url: str, city: str, state: str,
                          county: str, source_site: str) -> Listing | None:
    """Build a Listing from a schema.org SaleEvent JSON-LD node.

    Captures organizer.telephone/url (contactability the HTML cards lack),
    endDate, and — when location is a Place — its address.streetAddress.
    """
    if not isinstance(node, dict):
        return None
    name = node.get("name") or ""
    url = node.get("url") or source_url
    if isinstance(url, str) and not url.startswith("http"):
        url = urljoin(ESTATESALES_NET_BASE, url)

    organizer = node.get("organizer")
    if not isinstance(organizer, dict):
        organizer = {}
    org_name = organizer.get("name") or None
    org_phone = organizer.get("telephone") or None
    org_url = organizer.get("url") or None

    street = None
    ev_city, ev_state, ev_zip = city, state, None
    location = node.get("location")
    if isinstance(location, dict):
        loc_type = location.get("@type")
        loc_types = loc_type if isinstance(loc_type, list) else [loc_type]
        addr = location.get("address")
        if "Place" in loc_types or addr is not None:
            if isinstance(addr, dict):
                street = addr.get("streetAddress") or None
                ev_city = addr.get("addressLocality") or city
                ev_state = addr.get("addressRegion") or state
                ev_zip = addr.get("postalCode") or None
            elif isinstance(addr, str):
                street = addr or None

    start_date = node.get("startDate")
    end_date = node.get("endDate")
    sale_date = _parse_date(start_date) if isinstance(start_date, str) else None
    description = node.get("description") or ""

    if not street and not name:
        return None

    return Listing(
        source="national.estate_sales",
        source_url=url,
        listing_type=ListingType.ESTATE_LEAD,
        property_kind=PropertyKind.UNKNOWN,
        street_address=street,
        city=ev_city,
        state=ev_state,
        zip_code=ev_zip,
        county=county,
        sale_date=sale_date,
        trustee=org_name,  # company/organizer name stored in trustee field
        description=(f"{name} | {description}"[:500] if description else name[:500]) or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "estate_sales": {
                "source_site": source_site,
                "title": name,
                "company": org_name,
                "organizer_phone": org_phone,
                "organizer_url": org_url,
                "start_date": start_date,
                "end_date": end_date,
            },
        },
    )


def _parse_jsonld_sale_events(html: str, source_url: str, city: str, state: str,
                              county: str, source_site: str) -> list[Listing]:
    """Parse schema.org SaleEvent blocks from <script type=application/ld+json>.

    The prior JSON gate keyed on window.__INITIAL_STATE__ markers
    ('saleEvents'/'events'), so the ld+json SaleEvent blocks estatesales.net
    actually emits were never parsed. Detects @type=='SaleEvent' nodes (incl.
    inside @graph arrays) and maps organizer/location/dates."""
    out: list[Listing] = []
    tree = HTMLParser(html)
    for script in tree.css('script[type="application/ld+json"]'):
        txt = script.text()
        if not txt or "SaleEvent" not in txt:
            continue
        try:
            data = json.loads(txt)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        nodes: list[dict] = []

        def _collect(obj):
            if isinstance(obj, list):
                for x in obj:
                    _collect(x)
            elif isinstance(obj, dict):
                if isinstance(obj.get("@graph"), list):
                    _collect(obj["@graph"])
                nodes.append(obj)

        _collect(data)
        for node in nodes:
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if "SaleEvent" not in types:
                continue
            li = _saleevent_to_listing(node, source_url, city, state, county,
                                       source_site)
            if li:
                out.append(li)
    return out


# --- estatesales.net -------------------------------------------------------

def _parse_estatesales_net(html: str, source_url: str,
                           city: str, state: str,
                           county: str) -> list[Listing]:
    """Parse estatesales.net search results. The site returns HTML with
    event cards, and sometimes embedded JSON. We handle both."""
    tree = HTMLParser(html)
    out: list[Listing] = []

    # schema.org SaleEvent JSON-LD (organizer phone/url, endDate, Place address)
    out.extend(_parse_jsonld_sale_events(
        html, source_url, city, state, county, "estatesales.net"))

    # Try embedded JSON first (more structured)
    for script in tree.css("script"):
        text = script.text()
        if '"saleEvents"' not in text and '"events"' not in text:
            continue
        # Find JSON-like structures
        try:
            # Try to find a JSON blob
            json_match = re.search(
                r'(?:window\.\w+\s*=\s*|__INITIAL_STATE__\s*=\s*)(\{.+?\});',
                text, re.S,
            )
            if json_match:
                data = json.loads(json_match.group(1))
                events = (
                    data.get("saleEvents")
                    or data.get("events")
                    or data.get("sales")
                    or []
                )
                if isinstance(events, list):
                    for ev in events:
                        li = _estatesales_net_json_to_listing(
                            ev, source_url, city, state, county,
                        )
                        if li:
                            out.append(li)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # HTML card parsing
    # estatesales.net uses .sale-row__details for listing cards (Angular SPA)
    for card in tree.css(
        "div.sale-row__details, div.sale-card, div.event-card, div.listing-item, "
        "article.sale, li.sale-item, div.es-item, "
        "div[data-sale-id], div[class*='sale']"
    ):
        li = _parse_estatesales_net_card(card, source_url, city, state, county)
        if li:
            out.append(li)

    # Fallback: look for any div/article with address-like content
    if not out:
        for el in tree.css("div.card, article, li.media, div.result"):
            text = el.text(strip=True)
            if not text or len(text) < 20:
                continue
            addr = ADDR_RE.search(text)
            if not addr:
                continue
            # Extract link
            a = el.css_first("a[href]")
            url = source_url
            if a is not None:
                href = a.attributes.get("href", "")
                if href:
                    url = urljoin(ESTATESALES_NET_BASE, href)
            title = a.text(strip=True) if a is not None else "Estate Sale"

            li = Listing(
                source="national.estate_sales",
                source_url=url,
                listing_type=ListingType.ESTATE_LEAD,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr.group().strip(),
                city=city,
                state=state,
                county=county,
                sale_date=_parse_date(text),
                description=text[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "estate_sales": {
                        "source_site": "estatesales.net",
                        "text_block": text[:500],
                    },
                },
            )
            out.append(li)

    return out


def _estatesales_net_json_to_listing(
    ev: dict, source_url: str,
    city: str, state: str, county: str,
) -> Listing | None:
    """Convert an estatesales.net JSON event to a Listing."""
    if not isinstance(ev, dict):
        return None

    title = ev.get("title") or ev.get("name") or ""
    url = ev.get("url") or ev.get("detailUrl") or source_url
    if not url.startswith("http"):
        url = urljoin(ESTATESALES_NET_BASE, url)

    address = (
        ev.get("address")
        or ev.get("streetAddress")
        or ev.get("location", {}).get("address")
        or ""
    )
    company = (
        ev.get("companyName")
        or ev.get("company", {}).get("name")
        or ev.get("organizer")
        or ""
    )

    # Date handling
    date_str = ev.get("startDate") or ev.get("dateStart") or ev.get("date")
    sale_date = _parse_date(date_str) if isinstance(date_str, str) else None

    description = ev.get("description") or ev.get("summary") or ""

    # Full address components
    ev_city = ev.get("city") or city
    ev_state = ev.get("state") or state
    ev_zip = ev.get("zip") or ev.get("zipCode")

    if not address and not title:
        return None

    return Listing(
        source="national.estate_sales",
        source_url=url,
        listing_type=ListingType.ESTATE_LEAD,
        property_kind=PropertyKind.UNKNOWN,
        street_address=address or None,
        city=ev_city,
        state=ev_state,
        zip_code=ev_zip,
        county=county,
        sale_date=sale_date,
        trustee=company or None,  # company name stored in trustee field
        description=f"{title} | {description}"[:500] if description else title[:500],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "estate_sales": {
                "source_site": "estatesales.net",
                "title": title,
                "company": company,
                "dates_raw": date_str,
                "description": description[:300],
            },
        },
    )


def _parse_estatesales_net_card(card, source_url: str,
                                city: str, state: str,
                                county: str) -> Listing | None:
    """Parse a single estatesales.net HTML card element."""
    # Title + link
    a = card.css_first("a[href]")
    title = ""
    url = source_url
    if a is not None:
        href = a.attributes.get("href", "")
        if href:
            url = urljoin(ESTATESALES_NET_BASE, href)
        title = a.text(strip=True) or a.attributes.get("title", "")

    # Title from heading if link text is empty
    if not title:
        for sel in ("h2", "h3", "h4", ".title", ".sale-title"):
            n = card.css_first(sel)
            if n is not None:
                title = n.text(strip=True)
                break

    # Address
    address = None
    for sel in (".address", ".location", ".sale-address", "[class*='address']"):
        n = card.css_first(sel)
        if n is not None:
            addr_text = n.text(strip=True)
            if addr_text:
                address = addr_text
                break
    if not address:
        blob = card.text()
        m = ADDR_RE.search(blob)
        if m:
            address = m.group().strip()

    # Dates
    date_text = None
    for sel in (".dates", ".sale-dates", ".date", "[class*='date']"):
        n = card.css_first(sel)
        if n is not None:
            date_text = n.text(strip=True)
            if date_text:
                break

    sale_date = _parse_date(date_text)

    # Company name
    company = None
    for sel in (".company", ".company-name", ".organizer", "[class*='company']"):
        n = card.css_first(sel)
        if n is not None:
            company = n.text(strip=True)
            if company:
                break

    if not title and not address:
        return None

    return Listing(
        source="national.estate_sales",
        source_url=url,
        listing_type=ListingType.ESTATE_LEAD,
        property_kind=PropertyKind.UNKNOWN,
        street_address=address,
        city=city,
        state=state,
        county=county,
        sale_date=sale_date,
        trustee=company,
        description=f"{title} | {date_text or ''}".strip(" |")[:500] or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "estate_sales": {
                "source_site": "estatesales.net",
                "title": title,
                "company": company,
                "dates_raw": date_text,
            },
        },
    )


# --- estatesale.com --------------------------------------------------------

def _parse_estatesale_com(html: str, source_url: str,
                          city: str, state: str,
                          county: str) -> list[Listing]:
    """Parse estatesale.com search results."""
    tree = HTMLParser(html)
    out: list[Listing] = []

    # schema.org SaleEvent JSON-LD (organizer phone/url, endDate, Place address)
    out.extend(_parse_jsonld_sale_events(
        html, source_url, city, state, county, "estatesale.com"))

    for card in tree.css(
        "div.sale-listing, div.listing, div.event, "
        "article.sale, li.sale-item, div.card, "
        "div[class*='sale'], div[class*='listing']"
    ):
        a = card.css_first("a[href]")
        title = ""
        url = source_url
        if a is not None:
            href = a.attributes.get("href", "")
            if href:
                url = urljoin(ESTATESALE_COM_BASE, href)
            title = a.text(strip=True) or a.attributes.get("title", "")

        if not title:
            for sel in ("h2", "h3", "h4", ".title", ".sale-title", ".name"):
                n = card.css_first(sel)
                if n is not None:
                    title = n.text(strip=True)
                    break

        address = None
        for sel in (".address", ".location", ".addr", "[class*='address']"):
            n = card.css_first(sel)
            if n is not None:
                address = n.text(strip=True)
                if address:
                    break
        if not address:
            blob = card.text()
            m = ADDR_RE.search(blob)
            if m:
                address = m.group().strip()

        date_text = None
        for sel in (".dates", ".date", ".when", "[class*='date']"):
            n = card.css_first(sel)
            if n is not None:
                date_text = n.text(strip=True)
                if date_text:
                    break

        company = None
        for sel in (".company", ".company-name", ".organizer", "[class*='company']"):
            n = card.css_first(sel)
            if n is not None:
                company = n.text(strip=True)
                if company:
                    break

        if not title and not address:
            continue

        sale_date = _parse_date(date_text)

        out.append(Listing(
            source="national.estate_sales",
            source_url=url,
            listing_type=ListingType.ESTATE_LEAD,
            property_kind=PropertyKind.UNKNOWN,
            street_address=address,
            city=city,
            state=state,
            county=county,
            sale_date=sale_date,
            trustee=company,
            description=f"{title} | {date_text or ''}".strip(" |")[:500] or None,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={
                "estate_sales": {
                    "source_site": "estatesale.com",
                    "title": title,
                    "company": company,
                    "dates_raw": date_text,
                },
            },
        ))

    # Fallback: scan all text blocks
    if not out:
        for el in tree.css("div.card, article, li, p"):
            text = el.text(strip=True)
            if not text or len(text) < 20:
                continue
            addr = ADDR_RE.search(text)
            if not addr:
                continue
            a = el.css_first("a[href]")
            url = source_url
            if a is not None:
                href = a.attributes.get("href", "")
                if href:
                    url = urljoin(ESTATESALE_COM_BASE, href)
            title = a.text(strip=True) if a is not None else "Estate Sale"

            out.append(Listing(
                source="national.estate_sales",
                source_url=url,
                listing_type=ListingType.ESTATE_LEAD,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr.group().strip(),
                city=city,
                state=state,
                county=county,
                sale_date=_parse_date(text),
                description=text[:500],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "estate_sales": {
                        "source_site": "estatesale.com",
                        "text_block": text[:500],
                    },
                },
            ))

    return out


async def _fetch_estatesales_net(zip_code: str, city: str, state: str,
                                 county: str) -> list[Listing]:
    """Search estatesales.net by zip code."""
    host = "www.estatesales.net"
    search_path = f"/estate-sales/{zip_code}.html"
    if not await _robots_allows(host, search_path):
        log.info("estate_sales.net_robots_skip")
        return []

    url = f"{ESTATESALES_NET_BASE}/{state}/{city}/"
    try:
        html = await _fetch_text(url, timeout=20.0)
    except Exception as exc:
        log.warning("estate_sales.net_fail", zip=zip_code, error=str(exc)[:200])
        return []

    if not html or len(html) < 200:
        return []

    return _parse_estatesales_net(html, url, city, state, county)


async def _fetch_estatesale_com(zip_code: str, city: str, state: str,
                                county: str) -> list[Listing]:
    """Search estatesale.com by zip code."""
    host = "www.estatesale.com"
    search_path = f"/search"
    if not await _robots_allows(host, search_path):
        log.info("estate_sales.com_robots_skip")
        return []

    url = f"{ESTATESALE_COM_BASE}/search?zip={zip_code}&radius=25"
    try:
        html = await _fetch_text(url, timeout=20.0)
    except Exception as exc:
        log.warning("estate_sales.com_fail", zip=zip_code, error=str(exc)[:200])
        return []

    if not html or len(html) < 200:
        return []

    return _parse_estatesale_com(html, url, city, state, county)


class EstateSales(BaseScraper):
    slug = "national.estate_sales"
    name = "Estate Sales (estatesales.net + estatesale.com)"
    category = "estate_sale"
    expected_min_count = 0
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for zip_code, city, state, county in SEARCH_ZIPS:
            try:
                listings = await _fetch_estatesales_net(
                    zip_code, city, state, county,
                )
                out.extend(listings)
                log.info("estate_sales.net_done", zip=zip_code,
                         count=len(listings))
            except Exception as exc:
                log.warning("estate_sales.net_failed", zip=zip_code,
                            error=str(exc)[:200])

            try:
                listings = await _fetch_estatesale_com(
                    zip_code, city, state, county,
                )
                out.extend(listings)
                log.info("estate_sales.com_done", zip=zip_code,
                         count=len(listings))
            except Exception as exc:
                log.warning("estate_sales.com_failed", zip=zip_code,
                            error=str(exc)[:200])

        # Dedupe by source_url
        seen: set[str] = set()
        deduped: list[Listing] = []
        for li in out:
            if li.source_url in seen:
                continue
            seen.add(li.source_url)
            deduped.append(li)

        return deduped
