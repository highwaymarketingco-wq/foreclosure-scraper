"""IRS Treasury auction scraper — seized real property sales.

Source: https://www.irsauctions.gov/auction/items
Each listing links to /ad/<slug> detail pages with address, minimum bid, etc.

As of 2026-08-20: 18 active auctions, 0 in NC/SC. Scraper will catch new ones
dynamically when they appear.

REWRITTEN 2026-10-04 (national.* extraction-completeness audit, batch 16).
Live-verified against the one real NC auction currently posted (Henderson,
NC — "Half interest in a house and acreage!!!") and found the old code was
missing almost everything actually on the page:

1. **`opening_bid` was None on every single row, ever.** The old regex
   required a literal "$" before the amount, but the live detail page
   never prints one — "Minimum Bid" is rendered as
   bare `81,480.00` text (the "$" the live site shows is CSS-generated, not
   in the HTML/text at all). The real machine-readable value sits in a
   `content="81480.00"` attribute on the same div
   (`field--name-field-minimum-bid .field__item[content]`), confirmed live —
   now read directly from there, with the old $-regex kept as a last-resort
   fallback for any future page shape.
2. **County resolution used a tiny 7-8-city hardcoded dict** (not even
   containing "henderson") instead of the REAL county name that is always
   printed in the page's own Legal Description ("...Henderson Township,
   **Vance County**, North Carolina... Vance County Registry") — a far more
   reliable signal than guessing from an ambiguous city name (Henderson,
   NC the CITY is in Vance County; Henderson COUNTY, NC is a different
   place entirely with seat Hendersonville). Now parsed directly from the
   page text via a "<Name> County" pattern, falling back to the old
   city-dict only if no county is ever mentioned.
3. **Owner/debtor name never captured** — the Notice text always states
   "...seized for nonpayment of internal revenue taxes due from <Name>."
   (live-confirmed: "Willie J. Sessions"), a real identity signal this
   scraper threw away entirely.
4. **Full property specs never captured** — total/living sqft, bed/bath
   count, year built, lot acreage, and PARCEL NUMBER(S) are all stated in
   plain English in the "Asset Description" field (e.g. "4,234 (2,604
   living) sq. ft. 4 bedroom/3.5 bathroom Single Family Residence built in
   1987 situated on 5.01 acres ... (Parcel No. 0209 02027)") — none of this
   reached the Listing; property_kind stayed UNKNOWN on every row.
5. **Government contact (name/phone/email) never captured** — every ad has
   a "Contact Information" block naming the IRS Property Appraisal &
   Liquidation Specialist running THAT sale, with a direct phone and email
   (live: "Paul Reed", "770-826-1271", "paul.reed@irs.gov") — real, free
   contactability for whoever is working this lead, same mission as
   HERMES sec 9's contactability ceiling.
6. **Linked PDFs never captured** — every ad links a signed "Notice of
   Encumbrances", "Order of Sale/Notice of Sale", and "Mail-in Bid Form"
   PDF (confirmed live, real small PDFs under /sites/default/files/).
   `document_links.harvest_document_links()` can't be reused as-is here —
   its href regex requires a QUOTED attribute value and this Drupal/USWDS
   theme renders many attributes unquoted (`href=/sites/default/files/...`)
   — so PDFs are pulled directly from the already-parsed selectolax tree
   (which normalizes quoting) and handed to `stamp_documents()` instead.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog
from curl_cffi import requests as cf
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...document_links import stamp_documents
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE_URL = "https://www.irsauctions.gov"
ITEMS_URL = f"{BASE_URL}/auction/items"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# State -> county mapping
NC_CITIES = {
    "charlotte": "Mecklenburg", "raleigh": "Wake", "asheville": "Buncombe",
    "wilmington": "New Hanover", "fayetteville": "Cumberland",
    "greensboro": "Guilford", "durham": "Durham", "winston": "Forsyth",
}
SC_CITIES = {
    "spartanburg": "Spartanburg", "greenville": "Greenville",
    "columbia": "Richland", "charleston": "Charleston",
    "anderson": "Anderson", "florence": "Florence", "aiken": "Aiken",
}


def _extract_state(text: str) -> str | None:
    """Try to find a US state abbreviation in text."""
    states = [
        "NC", "SC", "VA", "GA", "TN", "FL", "AL", "MS", "LA", "AR",
        "TX", "OK", "NM", "AZ", "CA", "OR", "WA", "CO", "NY", "PA",
        "OH", "IL", "IN", "MI", "WI", "MN", "IA", "MO", "KY", "WV",
        "MD", "DE", "NJ", "CT", "RI", "MA", "VT", "NH", "ME", "MT",
        "ID", "WY", "UT", "NV", "HI", "AK", "ND", "SD", "NE", "KS",
    ]
    for s in states:
        m = re.search(r'\b' + s + r'\b', text)
        if m:
            return s
    # Also check state names
    state_names = {
        "North Carolina": "NC", "South Carolina": "SC", "Virginia": "VA",
        "Georgia": "GA", "Tennessee": "TN", "Florida": "FL",
    }
    for name, abbr in state_names.items():
        if name.lower() in text.lower():
            return abbr
    return None


def _extract_city(text: str, state: str) -> str | None:
    """Try to extract city before state."""
    m = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*' + state, text)
    if m:
        return m.group(1).strip()
    return None


# "...Henderson Township, Vance County, North Carolina..." / "Vance County
# Registry" -- the real county NAME is always printed in a US legal
# description. Far more reliable than guessing from a city name.
_COUNTY_RE = re.compile(r"\b([A-Z][a-zA-Z]+)\s+County\b")


def _extract_county_from_text(text: str) -> str | None:
    """The most-mentioned '<Name> County' token in the page text, or None."""
    hits = _COUNTY_RE.findall(text or "")
    if not hits:
        return None
    # Most legal descriptions repeat the real county (e.g. "...County,..."
    # and "...County Registry") more than any incidental mention, so the
    # most-frequent hit is the real one.
    counts: dict[str, int] = {}
    for h in hits:
        counts[h] = counts.get(h, 0) + 1
    return max(counts, key=lambda k: counts[k])


# "...seized for nonpayment of internal revenue taxes due from Willie J.
# Sessions. The property will be sold at public auction..." -- the IRS's
# own standard statutory notice phrasing (IRC section 6331/6335) names the
# debtor. Anchored on the next sentence ("The property will be sold") so a
# middle-initial period ("J.") inside the name doesn't truncate the match --
# a plain "stop at the first period" regex cuts "Willie J. Sessions" down
# to just "Willie J" (confirmed live). Falls back to the simpler
# first-period cut for any notice that doesn't use that exact next sentence.
_OWNER_RE = re.compile(r"due from\s+(.+?)\.\s+The property will be sold", re.I)
_OWNER_FALLBACK_RE = re.compile(r"due from\s+([A-Z][^.]{2,80}?)\.", re.I)


def _extract_owner_name(text: str) -> str | None:
    text = text or ""
    m = _OWNER_RE.search(text)
    if m:
        return m.group(1).strip()
    m = _OWNER_FALLBACK_RE.search(text)
    return m.group(1).strip() if m else None


# "4,234 (2,604 living) sq. ft. 4 bedroom/3.5 bathroom Single Family
# Residence built in 1987 situated on 5.01 acres ... (Parcel No. 0209 02027)"
_SQFT_BOTH_RE = re.compile(r"([\d,]+)\s*\(([\d,]+)\s*living\)\s*sq\.?\s*ft", re.I)
_SQFT_ONE_RE = re.compile(r"([\d,]+)\s*sq\.?\s*ft", re.I)
_BEDBATH_RE = re.compile(r"(\d+)\s*bedroom\s*/\s*(\d+(?:\.\d+)?)\s*bathroom", re.I)
_BUILT_RE = re.compile(r"built in\s+(\d{4})", re.I)
_ACRES_RE = re.compile(r"([\d.]+)\s*acres", re.I)
# "(Parcel No. 0209 02027)" -- the parcel number itself is often two
# whitespace-separated groups of digits; a bare \w+ stops at the first
# space and truncates it (confirmed live: captured "0209" instead of
# "0209 02027"). Anchor on the closing paren the live notices always use
# right after the number; fall back to a looser match with no paren.
_PARCEL_RE = re.compile(r"Parcel No\.?\s*([\w]+(?:\s[\w]+)?)\s*\)", re.I)
_PARCEL_FALLBACK_RE = re.compile(r"Parcel No\.?\s*([\w-]+)", re.I)
_KIND_WORDS = (
    ("mobile home", PropertyKind.MOBILE), ("manufactured home", PropertyKind.MOBILE),
    ("single family", PropertyKind.SINGLE_FAMILY), ("condominium", PropertyKind.CONDO),
    ("townhouse", PropertyKind.TOWNHOUSE), ("duplex", PropertyKind.MULTI_FAMILY),
    ("multi-family", PropertyKind.MULTI_FAMILY), ("vacant land", PropertyKind.LAND),
    ("residential land", PropertyKind.LAND), ("commercial", PropertyKind.COMMERCIAL),
)


def _extract_property_specs(text: str) -> dict:
    """Best-effort structured specs out of the free-text Asset Description."""
    text = text or ""
    out: dict = {}
    m2 = _SQFT_BOTH_RE.search(text)
    if m2:
        try:
            out["total_sqft"] = float(m2.group(1).replace(",", ""))
            out["living_sqft"] = float(m2.group(2).replace(",", ""))
        except ValueError:
            pass
    elif (m1 := _SQFT_ONE_RE.search(text)):
        try:
            out["total_sqft"] = float(m1.group(1).replace(",", ""))
        except ValueError:
            pass
    bb = _BEDBATH_RE.search(text)
    if bb:
        try:
            out["bedrooms"] = float(bb.group(1))
            out["bathrooms"] = float(bb.group(2))
        except ValueError:
            pass
    yb = _BUILT_RE.search(text)
    if yb:
        out["year_built"] = int(yb.group(1))
    ac = _ACRES_RE.search(text)
    if ac:
        try:
            out["acreage"] = float(ac.group(1))
        except ValueError:
            pass
    out["parcel_ids"] = _PARCEL_RE.findall(text) or _PARCEL_FALLBACK_RE.findall(text)
    low = text.lower()
    for word, kind in _KIND_WORDS:
        if word in low:
            out["property_kind"] = kind
            break
    return out


def _extract_minimum_bid(atree: HTMLParser, full_text: str) -> float | None:
    """Prefer the clean machine-readable `content="..."` attribute Drupal
    renders on the Minimum Bid field; fall back to a $-prefixed amount
    anywhere in the page text (covers any page shape that DOES print a
    literal "$", which the one live example this was built against does
    not)."""
    node = atree.css_first('[class*="field--name-field-minimum-bid"] [content]')
    if node is not None:
        try:
            v = float(node.attributes.get("content") or "")
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    m = re.search(r"\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)", full_text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _extract_contact(atree: HTMLParser) -> dict:
    """The per-ad IRS Property Appraisal & Liquidation Specialist contact
    block — real, free name/phone/email for whoever is running THIS sale."""
    out: dict = {}
    block = atree.css_first('[class*="field--name-field-contact-information"]')
    if block is not None:
        name_el = block.css_first(".given-name")
        if name_el is not None:
            out["name"] = name_el.text(strip=True) or None
        org_el = block.css_first(".organization")
        if org_el is not None:
            out["organization"] = org_el.text(strip=True) or None
        mailto = block.css_first('a[href^="mailto:"]')
        if mailto is not None:
            href = (mailto.attributes.get("href") or "")[7:]
            out["email"] = href.split("?", 1)[0].strip() or None
    phone_el = atree.css_first('[class*="field--name-field-contact-phone"] .field__item')
    if phone_el is not None:
        out["phone"] = phone_el.text(strip=True) or None
    return {k: v for k, v in out.items() if v}


def _extract_pdf_links(atree: HTMLParser, base_url: str) -> list[str]:
    """Signed Notice-of-Sale / Order-of-Sale / Mail-in-Bid-Form PDFs linked
    off the detail page. Pulled from the PARSED tree (not a regex over raw
    HTML like document_links.harvest_document_links()) because this
    Drupal/USWDS theme renders many attributes unquoted
    (`href=/sites/default/files/...`), which that helper's quote-requiring
    regex misses entirely; selectolax normalizes quoting away."""
    out: list[str] = []
    for a in atree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if href.lower().endswith(".pdf"):
            out.append(urljoin(base_url, href))
    return out


def _extract_address_block(atree: HTMLParser) -> tuple[str | None, str | None, str | None, str | None]:
    """The clean 'Asset Address' field (street / "City, ZIP STATE" / country)
    -- more reliable than scanning the whole page's free text for a street
    pattern that may also match the Sale Location or an unrelated address."""
    addr_el = atree.css_first('[class*="field--name-field-property-address"] address')
    if addr_el is None:
        return None, None, None, None
    lines = [l.strip() for l in addr_el.text(separator="\n").split("\n") if l.strip()]
    if not lines:
        return None, None, None, None
    street = lines[0] or None
    city = zip_code = state = None
    if len(lines) > 1:
        # "Henderson, 27537 NC" -- city, ZIP STATE (note the unusual order).
        m = re.match(r"^(.*?),\s*(\d{5})\s+([A-Z]{2})$", lines[1])
        if m:
            city, zip_code, state = m.group(1).strip(), m.group(2), m.group(3)
    return street, city, state, zip_code


def _fetch_irs_sync() -> list[Listing]:
    """Fully synchronous by design (curl_cffi's `cf.get` blocks) -- called via
    asyncio.to_thread from IRSTreasuryAuctions.fetch(), never awaited directly.

    2026-09-24: this used to be declared `async def` with zero actual `await`
    points despite looping `cf.get(...)` once per /ad/ link with NO rate-limit
    sleep between iterations at all (unlike national.foreclosure_dot_com's
    similarly-blocking loop, which at least paces itself with time.sleep). A
    coroutine with no await points can't be preempted by asyncio.wait_for, so
    if the ad count ever grows past the ~18 seen 2026-08-20 or the site slows
    down, this would freeze the ENTIRE event loop -- not just this scraper's
    own timeout_s=60 -- for as long as the loop takes, exactly like the bug
    just found and fixed in counties_sc.zombie_properties (confirmed live:
    that one froze every sibling scraper for 41m50s). Moving the whole
    synchronous body to a worker thread keeps the event loop free for every
    other concurrent scraper regardless of how many ads show up or how slow
    irsauctions.gov gets."""
    out: list[Listing] = []
    try:
        r = cf.get(ITEMS_URL, impersonate="chrome", timeout=15, headers=HEADERS)
    except Exception as exc:
        log.warning("irs.fetch_fail", error=str(exc)[:200])
        return out

    if r.status_code != 200 or len(r.text) < 1000:
        log.warning("irs.bad_response", status=r.status_code, size=len(r.text))
        return out

    tree = HTMLParser(r.text)

    # Find property listing links — each /ad/<slug>
    ad_links = set()
    for node in tree.css("a[href^='/ad/']"):
        href = node.attributes.get("href", "")
        if href and href != "/ad/":
            ad_links.add(href)

    log.info("irs.found_ads", count=len(ad_links))

    for ad_path in ad_links:
        ad_url = BASE_URL + ad_path
        try:
            ar = cf.get(ad_url, impersonate="chrome", timeout=15, headers=HEADERS)
        except Exception:
            continue

        if ar.status_code != 200:
            continue

        atree = HTMLParser(ar.text)

        # Extract all text content to find state
        full_text = atree.body.text() if atree.body else ar.text
        state = _extract_state(full_text)
        if not state:
            continue

        # Filter NC + SC only
        if state not in ("NC", "SC"):
            continue

        # Prefer the clean structured "Asset Address" field; fall back to
        # scanning the whole page's free text for a street-looking token.
        street, addr_city, addr_state, zip_code = _extract_address_block(atree)
        city = addr_city or _extract_city(full_text, state)
        if not street:
            addr_m = re.search(
                r'\b\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+'
                r'(?:St|Ave|Dr|Rd|Blvd|Ln|Way|Ct|Cir|Hwy|Pkwy)\b',
                full_text,
            )
            street = addr_m.group(0) if addr_m else None

        # The real county NAME is always printed in the legal description
        # ("...Vance County Registry") -- far more reliable than guessing
        # from a city name (which the old NC_CITIES/SC_CITIES dicts did,
        # and which is wrong for a city like Henderson whose COUNTY is a
        # different place with a similar name). Only fall back to the tiny
        # hardcoded dict when the page never names a county at all.
        county = _extract_county_from_text(full_text)
        county_source = "legal_description"
        if not county:
            county_source = "city_lookup"
            if state == "NC" and city:
                county = NC_CITIES.get(city.lower())
            elif state == "SC" and city:
                county = SC_CITIES.get(city.lower())

        min_bid = _extract_minimum_bid(atree, full_text)
        owner_name = _extract_owner_name(full_text)
        specs = _extract_property_specs(full_text)
        contact = _extract_contact(atree)
        pdf_links = _extract_pdf_links(atree, ad_url)

        legal_el = atree.css_first('[class*="field--name-field-legal-description"] .field__item')
        legal_description = legal_el.text(strip=True) if legal_el is not None else None

        # Title from page
        title_node = atree.css_first("h1")
        title = title_node.text().strip() if title_node else ad_path

        parcel_ids = specs.get("parcel_ids") or []

        li = Listing(
            source="national.irs_treasury",
            source_url=ad_url,
            listing_type=ListingType.AUCTION,
            property_kind=specs.get("property_kind", PropertyKind.UNKNOWN),
            state=state,
            county=county,
            street_address=street,
            city=city,
            zip_code=zip_code,
            owner_name=owner_name,
            parcel_id=parcel_ids[0] if parcel_ids else None,
            legal_description=legal_description,
            living_sqft=specs.get("living_sqft") or specs.get("total_sqft"),
            bedrooms=specs.get("bedrooms"),
            bathrooms=specs.get("bathrooms"),
            year_built=specs.get("year_built"),
            acreage=specs.get("acreage"),
            opening_bid=min_bid,
            description=title,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"irs_treasury": {
                "url": ad_url,
                "title": title,
                "min_bid": min_bid,
                "owner_name": owner_name,
                "parcel_ids": parcel_ids,
                "total_sqft": specs.get("total_sqft"),
                "county_source": county_source,
                "contact": contact or None,
            }},
        )
        if pdf_links:
            stamp_documents(li, pdf_links)
        out.append(li)

    log.info("irs.parse_done", total=len(out))
    return out


class IRSTreasuryAuctions(BaseScraper):
    slug = "national.irs_treasury"
    name = "IRS Treasury Seized Property Auctions"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        return await asyncio.to_thread(_fetch_irs_sync)
