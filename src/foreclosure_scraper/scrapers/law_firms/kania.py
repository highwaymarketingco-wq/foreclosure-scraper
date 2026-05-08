"""Kania Law Firm — NC tax foreclosure auctions across western NC counties.

The Kania Law Firm (Asheville, NC; kanialawfirm.com) handles tax-foreclosure
sales for 20+ NC counties — the largest single source of tax-sale listings
in the western half of the state. Their /tax-foreclosures/ section
publishes a daily-updated list of upcoming auctions with parcel,
opening bid, county, and sale date.

Site sits behind Cloudflare; plain httpx returns 503. We use Scrapling
StealthyFetcher (camoufox/Playwright stealth) which gets past Cloudflare's
JS challenge.

Parser strategy (run all paths, dedupe results — Kania varies layouts
across sub-pages):

  Path A: <table> rows (classic auction-list format)
  Path B: <article>/<div>/<li> card layouts (Avada/Divi themes)
  Path C: <a> anchor lists (each link = one property detail page)
  Path D: text-block fallback via parse_blocks (handles plain HTML)
  Path E: per-county sub-pages (kanialawfirm.com/tax-foreclosures/buncombe-county/)
  Path F: pagination follow (?paged=2, /page/2/)

Listings are tagged ListingType.TAX_SALE so the existing tax-sale
enrichment chain runs (parcel→address backfill via county GIS, etc).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind
from ._helpers import (
    ADDR_RE,
    COUNTY_RE,
    DATE_RE,
    PARCEL_RE,
    ZIP_RE,
    parse_blocks,
)


INDEX_URLS = (
    "https://kanialawfirm.com/tax-foreclosures/tax-foreclosure-sales/",
    "https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/",
    "https://kanialawfirm.com/tax-foreclosures/foreclosures/",
    "https://kanialawfirm.com/tax-foreclosures/",
)

# Western-NC counties Kania has historically represented. Used both as
# a county-name filter and (with slugified variants) as candidate
# per-county sub-page URLs.
KNOWN_KANIA_COUNTIES = (
    "Avery", "Buncombe", "Burke", "Caldwell", "Cherokee", "Clay",
    "Cleveland", "Gaston", "Graham", "Haywood", "Henderson", "Jackson",
    "Lincoln", "Macon", "Madison", "Mcdowell", "Mitchell", "Polk",
    "Rutherford", "Swain", "Transylvania", "Watauga", "Yancey",
    "Mecklenburg",
)


def _per_county_urls() -> tuple[str, ...]:
    """Build candidate per-county sub-page URLs. Kania often uses
    `/tax-foreclosures-charlotte/` for Mecklenburg or `/buncombe-county/`
    for Buncombe. Try both shapes."""
    out: list[str] = []
    for c in KNOWN_KANIA_COUNTIES:
        slug = c.lower().replace(" ", "-")
        out.extend([
            f"https://kanialawfirm.com/tax-foreclosures/{slug}/",
            f"https://kanialawfirm.com/tax-foreclosures/{slug}-county/",
            f"https://kanialawfirm.com/tax-foreclosures-{slug}/foreclosures/",
        ])
    return tuple(out)


# Opening bid: "$12,345.67" or "Minimum bid: $X" / "Opening bid: $X"
BID_RE = re.compile(
    r"(?:opening|minimum|starting)?\s*bid[:\s]*\$\s*([\d,]+(?:\.\d{2})?)",
    re.I,
)
BARE_BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
KANIA_CASE_RE = re.compile(r"\b(\d{2,4}[\s\-]?(?:CVS|SP|CV)[\s\-]?\d+)\b", re.I)
# Loose parcel-id detector — Kania uses both NC PIN format
# (XXXX-XX-XXXX) and county-specific TMS / parcel codes.
LOOSE_PARCEL_RE = re.compile(
    r"\b(?:parcel|pin|tms|tax\s*map)\b[:\#\s]*([A-Z0-9\-\.]{5,20})", re.I
)


def _flatten(text: str) -> str:
    text = re.sub(r"&(?:nbsp|amp|lt|gt|times);", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _county_from_text(text: str) -> Optional[str]:
    m = COUNTY_RE.search(text)
    if m:
        c = m.group(1).strip()
        for known in KNOWN_KANIA_COUNTIES:
            if c.lower() == known.lower():
                return known
        return c
    for known in KNOWN_KANIA_COUNTIES:
        if re.search(rf"\b{re.escape(known)}\b", text, re.I):
            return known
    return None


def _looks_like_listing(text: str) -> bool:
    """Heuristic: a chunk of text is a listing if it has at least 2 of:
    (parcel/case/PIN, $-amount, address, county-name, date).

    This is intentionally loose — Kania's HTML across counties is
    inconsistent, so we'd rather over-match in the parser and let the
    downstream filter chain (county scope, _active_only) drop bad rows.
    """
    if not text or len(text) < 30:
        return False
    has_money = bool(BARE_BID_RE.search(text))
    has_parcel = bool(PARCEL_RE.search(text) or LOOSE_PARCEL_RE.search(text))
    has_case = bool(KANIA_CASE_RE.search(text))
    has_addr = bool(ADDR_RE.search(text))
    has_county = bool(_county_from_text(text))
    has_date = bool(DATE_RE.search(text))
    score = sum([has_money, has_parcel, has_case, has_addr, has_county, has_date])
    return score >= 2


def _parse_chunk(text: str, source_url: str, slug: str) -> Optional[Listing]:
    """Try to parse a free-form chunk of text as a single listing."""
    if not _looks_like_listing(text):
        return None

    addr_m = ADDR_RE.search(text)
    parcel_m = PARCEL_RE.search(text) or LOOSE_PARCEL_RE.search(text)
    case_m = KANIA_CASE_RE.search(text)
    date_m = DATE_RE.search(text)
    zip_m = ZIP_RE.search(text)

    sale_date = None
    if date_m:
        try:
            from dateutil import parser as dateparser
            sale_date = dateparser.parse(date_m.group(0))
        except (ValueError, TypeError):
            pass

    # Bid: prefer 'opening/minimum bid: $X' phrasing; fall back to bare $
    bid: Optional[float] = None
    bid_m = BID_RE.search(text)
    if not bid_m:
        bid_m = BARE_BID_RE.search(text)
    if bid_m:
        try:
            bid = float(bid_m.group(1).replace(",", ""))
        except ValueError:
            pass
        if bid is not None and (bid < 10 or bid > 5_000_000):
            bid = None

    return Listing(
        source=slug,
        source_url=source_url,
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=_county_from_text(text),
        street_address=addr_m.group(1) if addr_m else None,
        zip_code=zip_m.group(1) if zip_m else None,
        parcel_id=(parcel_m.group(1) if parcel_m else None) if parcel_m else None,
        sale_date=sale_date,
        case_number=case_m.group(1).strip() if case_m else None,
        opening_bid=bid,
        description=text[:500],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"kania": {"row_text": text[:500], "source_url": source_url}},
    )


def _parse_html(html: str, source_url: str, slug: str) -> list[Listing]:
    """Run all parser paths, dedupe, return aggregated results."""
    out: list[Listing] = []
    seen: set[str] = set()
    if not html or len(html) < 200:
        return out

    tree = HTMLParser(html)

    # Path A: table rows
    for table in tree.css("table"):
        for row in table.css("tr"):
            # selectolax's default text() concatenates cell contents
            # without a separator — pass " " so PARCEL_RE / ADDR_RE
            # don't smash adjacent cells together.
            text = _flatten(row.text(separator=" "))
            li = _parse_chunk(text, source_url, slug)
            if li:
                _add_unique(li, out, seen)

    # Path B: card containers (cover Avada / Divi / Bootstrap themes).
    # Skip if Path A already found rows — avoids double-counting when
    # the same data appears inside both <table> and <div.entry-content>.
    if not out:
        card_selectors = (
            "article", "li.foreclosure-item", "li.property", "li.listing",
            "div.listing", "div.property", "div.property-card",
            "div.foreclosure-item", "div.tax-foreclosure", "div.fl-row",
            "div.elementor-widget-container", "div.card", "div.entry-content",
            "div.wp-block-group", "div.ct-section",
        )
        for sel in card_selectors:
            for node in tree.css(sel):
                text = _flatten(node.text(separator=" "))
                li = _parse_chunk(text, source_url, slug)
                if li:
                    _add_unique(li, out, seen)

    # Path C: anchor lists — only if Paths A+B didn't find anything
    if not out:
        for a in tree.css("a[href]"):
            text = _flatten(a.text(separator=" "))
            if not _looks_like_listing(text):
                continue
            href = a.attributes.get("href") or ""
            detail_url = href if href.startswith("http") else (
                f"https://kanialawfirm.com{href}" if href.startswith("/") else source_url
            )
            li = _parse_chunk(text, detail_url, slug)
            if li:
                _add_unique(li, out, seen)

    # Path D: text-block fallback — only if structured paths failed
    if not out:
        body = tree.body
        if body:
            text = body.text(separator="\n")
            for li in parse_blocks(text, source_slug=slug, source_url=source_url):
                li.state = "NC"
                li.listing_type = ListingType.TAX_SALE
                if not li.county:
                    li.county = _county_from_text(li.description or "")
                _add_unique(li, out, seen)

    # Path E: free-form chunks split by double-newline (catches plain
    # WordPress text content with sale info inline).
    if not out:
        big_text = tree.text(separator="\n") if tree.body else ""
        for chunk in re.split(r"\n\s*\n", big_text):
            li = _parse_chunk(_flatten(chunk), source_url, slug)
            if li:
                _add_unique(li, out, seen)

    return out


def _add_unique(li: Listing, out: list, seen: set[str]) -> None:
    key = (
        (li.parcel_id or "").upper().strip()
        + "|" + (li.case_number or "").upper().strip()
        + "|" + (li.street_address or "").upper().strip()
        + "|" + (li.county or "").upper().strip()
    )
    key_clean = key.strip("|")
    if not key_clean or key_clean in seen:
        return
    seen.add(key_clean)
    out.append(li)


def _extract_pagination_urls(html: str, current_url: str) -> list[str]:
    """Find paged result URLs (?paged=N, /page/N/, etc.)."""
    if not html:
        return []
    tree = HTMLParser(html)
    out: list[str] = []
    seen_pages: set[str] = set()
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if not href:
            continue
        if not (re.search(r"[?&]paged?=\d+", href) or re.search(r"/page/\d+/", href)):
            continue
        full = href if href.startswith("http") else (
            f"https://kanialawfirm.com{href}" if href.startswith("/") else current_url
        )
        if full in seen_pages or full == current_url:
            continue
        seen_pages.add(full)
        out.append(full)
    return out[:10]  # cap pagination depth at 10 pages


async def _fetch_with_fallback(url: str) -> Optional[str]:
    """Try plain httpx first; on 5xx fall back to Scrapling stealth.
    Most production runs will land on Scrapling because Kania's
    Cloudflare blocks plain httpx."""
    try:
        return await get_text(url, timeout=30.0)
    except Exception:
        pass
    try:
        from scrapling.fetchers import StealthyFetcher
        result = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=90000,
        )
        body = getattr(result, "body", b"")
        if isinstance(body, (bytes, bytearray)):
            return body.decode("utf-8", errors="replace")
        return str(body or "")
    except Exception:
        return None


class KaniaLawFirm(BaseScraper):
    slug = "law_firms.kania"
    name = "Kania Law Firm (NC tax foreclosures)"
    category = "law_firm"
    expected_min_count = 1
    timeout_s = 600.0  # ~50 URLs (4 indexes + ~24 county subs + paged) at ~10s each via Scrapling
    requires_render = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_keys: set[str] = set()
        urls_to_visit: list[str] = list(INDEX_URLS) + list(_per_county_urls())
        visited: set[str] = set()

        # Process up to N URLs; pagination from index pages adds to queue.
        max_urls = 60
        while urls_to_visit and len(visited) < max_urls:
            url = urls_to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)
            html = await _fetch_with_fallback(url)
            if not html:
                continue
            for li in _parse_html(html, url, self.slug):
                _add_unique(li, out, seen_keys)
            # Add paged URLs to queue (only from the main indexes — skip
            # pagination on per-county sub-pages to avoid combinatorial blowup)
            if url in INDEX_URLS:
                for paged in _extract_pagination_urls(html, url):
                    if paged not in visited:
                        urls_to_visit.append(paged)
        return out
