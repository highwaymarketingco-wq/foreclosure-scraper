"""Mewborn & DeSelms, Attorneys at Law — Eastern-NC TAX foreclosure sales.

Built 2026-06-26. The firm (Jacksonville, NC; mewbornlaw.biz) is county /
municipal contract counsel that prosecutes in-rem PROPERTY-TAX foreclosures for
units of local government in Eastern NC — chiefly Onslow County (coastal, in
footprint) and Duplin County. Their public "Properties for Sale" page posts the
upcoming tax-foreclosure auctions (address, opening/minimum bid, sale date, and
the courthouse sale location), e.g. an NC Hwy 24 Richlands lot with an opening
bid of $2,683.61 sold at the Onslow County Courthouse.

Listings are tagged ListingType.TAX_SALE so the existing tax-sale enrichment
chain runs (parcel/address -> county GIS backfill, ARV, etc).

coastal_counties=true: Onslow is a deny-listed coastal county that only re-enters
the 18-county footprint through main's source-scoped coastal gate
(COASTAL_COUNTY_SOURCES). This module's lead value IS the coastal county, so its
rows must surface even without near-beach coordinates. To wire that gate, add
"law_firms.mewborn_deselms" to COASTAL_COUNTY_SOURCES in main.py (NOT edited here
per the build rules) so Onslow rows are admitted source-scoped.

ANTI-BOT. The site sits behind Cloudflare and the full-run alarm was "HTTP 403
(blocked/forbidden) from www.mewbornlaw.biz (scraper swallowed the error)".

A 2026-08-02 fix claimed HTTP/2 was the trigger and that the same headers over
HTTP/1.1 return 200. Re-measured, that is NOT what happens: HTTP/1.1 also
answers ``cf-mitigated: challenge`` and 403s, and only succeeded on the 4th
spaced retry. That fix has been REMOVED on compliance grounds — looping until a
Cloudflare challenge relents is working around bot detection, not negotiating a
protocol, and its clear_block_signal() call made a host that had just 403'd
three times report as never blocked (the same silent-failure class that hid the
upset-bid outage).

Current behaviour: ONE honest HTTP/1.1 attempt, then the pre-existing curl_cffi
impersonation and Scrapling render tiers (unchanged, established project-wide).
If every tier fails, fetch() RAISES so safe_run reports BLOCKED rather than
returning [] and hiding the outage as a clean empty — that half of the fix was
correct and is kept. A persistent 403 here should be reported as a wall, not
engineered around.

PAGE SHAPE (live 2026-06-26): a single Divi text block
``div.et_pb_text_inner`` holds an <h1>Properties For Sale</h1> then, per county,
an <h2>"<County> County Tax Foreclosure Sale(s):"</h2> header followed by the
sale content as sibling <p>/<a> nodes until the next <h2>. When a county has no
current auctions the content is literally "No Listings at this time." (both
Onslow and Duplin showed that on 2026-06-26 — a legitimate empty: the endpoint
works and currently has no items). The parser keys off the <h2> county headers
so each row's county is taken from its section, and skips the "No Listings"
placeholder. Sale content (when present) carries the address, the opening bid as
a $-amount, a sale date, and the courthouse name; some notices link to a PDF
notice-of-sale, captured as the row's source_url when available.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable, Optional

import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...document_links import harvest_document_links, stamp_documents
from ...http_client import client, get_text
from ...models import Listing, ListingType, PropertyKind
from ._helpers import ADDR_RE, DATE_RE, ZIP_RE

log = structlog.get_logger()

BASE = "https://www.mewbornlaw.biz"
INDEX_URL = f"{BASE}/properties-for-sale/"

# Eastern-NC counties this firm serves. Onslow is the in-footprint coastal one;
# the others are captured too (county-tagged) in case a row lands there, but the
# in-scope gate keeps only footprint rows.
KNOWN_COUNTIES = ("Onslow", "Duplin", "Jones", "Pender", "Carteret")

# County section header: "Onslow County Tax Foreclosure Sales:" / "Duplin County
# Tax Foreclosure Sale:". Capture the county name.
COUNTY_HEADER_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+)\s+County\s+Tax\s+Foreclosure", re.I
)

# Opening / minimum bid: prefer the labelled phrasing, fall back to a bare $.
BID_RE = re.compile(
    r"(?:opening|minimum|starting)\s*bid[:\s]*\$\s*([\d,]+(?:\.\d{2})?)", re.I
)
BARE_BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")

# Courthouse / sale location, e.g. "Onslow County Courthouse [Door]". The county
# name is a single capitalized word right before "County"; the explicit \b and
# the single-token prefix stop the match from swallowing leading "at the".
COURTHOUSE_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+\s+County\s+Courthouse(?:\s+(?:Door|steps?))?)"
)

# Placeholder text shown when a county has no current auctions.
_NO_LISTINGS_RE = re.compile(r"no\s+listings?\s+at\s+this\s+time", re.I)


def _flatten(text: str) -> str:
    text = re.sub(r"&(?:nbsp|amp|lt|gt|#160);", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _county_from_header(text: str) -> Optional[str]:
    m = COUNTY_HEADER_RE.search(text)
    if not m:
        return None
    c = m.group(1).strip().title()
    for known in KNOWN_COUNTIES:
        if c.lower() == known.lower():
            return known
    return c


def _parse_bid(text: str) -> Optional[float]:
    m = BID_RE.search(text) or BARE_BID_RE.search(text)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    # Tax-foreclosure opening bids are small (back taxes + costs); cap the band
    # to drop phone numbers / fax / year noise that slipped past the $ anchor.
    if v < 10 or v > 5_000_000:
        return None
    return v


def _parse_sale_date(text: str) -> Optional[datetime]:
    m = DATE_RE.search(text)
    if not m:
        return None
    try:
        return dateparser.parse(m.group(0))
    except (ValueError, TypeError, OverflowError):
        return None


def _looks_like_listing(text: str) -> bool:
    """A sale chunk needs a real signal: an address, a $-bid, or a sale date.
    Excludes the 'No Listings at this time.' placeholder and page chrome."""
    if not text or len(text) < 12 or len(text) > 2000:
        return False
    if _NO_LISTINGS_RE.search(text):
        return False
    has_addr = bool(ADDR_RE.search(text))
    has_bid = bool(BARE_BID_RE.search(text))
    has_date = bool(DATE_RE.search(text))
    return has_addr or has_bid or has_date


def _make_listing(
    *, text: str, county: Optional[str], source_url: str, slug: str
) -> Optional[Listing]:
    if not _looks_like_listing(text):
        return None
    addr_m = ADDR_RE.search(text)
    zip_m = ZIP_RE.search(text)
    courthouse_m = COURTHOUSE_RE.search(text)
    courthouse = courthouse_m.group(1).strip() if courthouse_m else None
    # Default the sale location to "<County> County Courthouse" when the row
    # doesn't name one explicitly — these are all courthouse-door tax sales.
    if not courthouse and county:
        courthouse = f"{county} County Courthouse"

    return Listing(
        source=slug,
        source_url=source_url,
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        foreclosure_process="tax",
        state="NC",
        county=county,
        street_address=addr_m.group(1).strip() if addr_m else None,
        zip_code=zip_m.group(1) if zip_m else None,
        sale_date=_parse_sale_date(text),
        sale_location=courthouse,
        opening_bid=_parse_bid(text),
        description=text[:500],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"mewborn_deselms": {"county": county, "row_text": text[:500]}},
    )


def _abs_url(href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"{BASE}{href}"
    return f"{BASE}/{href}"


def _parse_html(html: str, slug: str) -> list[Listing]:
    """Walk the Divi text block: <h2> county headers segment the page; the
    sibling content under each header (until the next <h2>) is that county's
    sale rows. County is taken from the section, so address-only rows still get
    placed. Falls back to whole-body chunking if the container isn't found."""
    out: list[Listing] = []
    seen: set[str] = set()
    if not html or len(html) < 200:
        return out

    tree = HTMLParser(html)

    # Locate the content container(s) that hold the county headers.
    containers = [
        d for d in tree.css("div.et_pb_text_inner")
        if COUNTY_HEADER_RE.search(d.text() or "")
    ]
    if not containers:
        # Fallback: any element holding both the page title and a county header.
        body = tree.body
        if body is not None:
            containers = [body]

    for cont in containers:
        current_county: Optional[str] = None
        for node in cont.iter():
            tag = node.tag
            node_text = _flatten(node.text(separator=" ", strip=True))
            if tag in ("h1", "h2", "h3", "h4"):
                hdr_county = _county_from_header(node_text)
                if hdr_county:
                    current_county = hdr_county
                # An h1 like "Properties For Sale" just resets context.
                elif COUNTY_HEADER_RE.search(node_text) is None and tag == "h1":
                    current_county = None
                continue
            # Non-header content node: try to parse it as a sale row, attributing
            # it to the most recent county header. Prefer a PDF/notice link as
            # the row's source_url when the node contains one.
            if not node_text:
                continue
            row_url = INDEX_URL
            for a in node.css("a[href]"):
                href = a.attributes.get("href") or ""
                if href and any(
                    k in href.lower()
                    for k in (".pdf", "documentcenter", "/wp-content/uploads")
                ):
                    row_url = _abs_url(href)
                    break
            li = _make_listing(
                text=node_text, county=current_county, source_url=row_url, slug=slug
            )
            if li:
                stamp_documents(li, harvest_document_links(node.html or "", base_url=INDEX_URL))
                _add_unique(li, out, seen)

    return out


def _add_unique(li: Listing, out: list, seen: set[str]) -> None:
    key = (
        (li.street_address or "").upper().strip()
        + "|" + (li.county or "").upper().strip()
        + "|" + (str(li.opening_bid) if li.opening_bid else "")
    ).strip("|")
    if not key or key in seen:
        return
    seen.add(key)
    out.append(li)


async def _fetch_index() -> str:
    """Plain HTTP/1.1 first, then the pre-existing impersonate / render tiers.
    Returns "" if every tier fails so safe_run's block signal classifies the run
    instead of crashing."""
    # Tier 0 (single HTTP/1.1 attempt). A previous version looped here up to
    # _H1_ATTEMPTS times against a `cf-mitigated: challenge` 403 and then called
    # clear_block_signal() on the attempt that finally got through. REMOVED on
    # compliance grounds: measured behaviour was 403 on attempts 1-3 and 200 on
    # the 4th, i.e. retry-until-the-challenge-relents, which is working around
    # bot detection rather than negotiating a protocol. clear_block_signal() also
    # made a host that had just 403'd three times report as never blocked, which
    # is the same silent-failure class that hid the upset-bid outage for months.
    # One honest attempt; if Cloudflare challenges it, fall through to the
    # pre-existing tiers and otherwise let the block be reported as a block.
    try:
        async with client(timeout=45.0, http2=False) as c:
            r = await c.get(INDEX_URL)
        if r.status_code == 200 and len(r.text) > 5_000:
            return r.text
        log.info("mewborn.h1_attempt", status=r.status_code, length=len(r.text))
    except Exception as exc:  # noqa: BLE001
        log.info("mewborn.h1_error", error=f"{type(exc).__name__}: {str(exc)[:80]}")

    # Tier 1: curl_cffi real-Chrome fingerprint (live-verified 2026-06-26).
    try:
        html = await get_text(INDEX_URL, timeout=45.0, impersonate=True)
        if html and len(html) > 500:
            return html
    except Exception:
        pass

    # Tier 2: Scrapling StealthyFetcher (camoufox/Playwright stealth).
    try:
        from scrapling.fetchers import StealthyFetcher

        # FORECLOSURE_NO_CF_SOLVE=1 disables Cloudflare/Turnstile SOLVING (compliant run).
        import os as _os
        _solve = _os.environ.get("FORECLOSURE_NO_CF_SOLVE", "").strip().lower() not in ("1", "true", "yes")
        result = await StealthyFetcher.async_fetch(
            INDEX_URL,
            headless=True,
            network_idle=True,
            timeout=120000,
            solve_cloudflare=_solve,
        )
        body = getattr(result, "body", b"")
        if isinstance(body, (bytes, bytearray)):
            return body.decode("utf-8", errors="replace")
        return str(body or "")
    except Exception:
        return ""


class MewbornDeSelms(BaseScraper):
    slug = "law_firms.mewborn_deselms"
    name = "Mewborn & DeSelms (Eastern-NC tax foreclosures)"
    category = "law_firm"
    coastal_counties = True
    requires_render = True  # Cloudflare-fronted; needs impersonate/stealth tier
    # Onslow/Duplin tax-foreclosure auctions are intermittent — the page legitimately
    # shows "No Listings at this time." between sale cycles. 0 is acceptable.
    expected_min_count = 0
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        html = await _fetch_index()
        if not html:
            # Do NOT return [] quietly — that is what turned a hard block into a
            # silent "OK, 0 rows" and hid the outage for two runs. Raising lets
            # safe_run classify it (the 403s already armed the block signal).
            raise RuntimeError(
                f"mewborn_deselms: every fetch tier failed for {INDEX_URL}"
            )
        rows = _parse_html(html, self.slug)
        log.info("mewborn.counts", html_bytes=len(html), rows=len(rows))
        return rows


if __name__ == "__main__":
    # Manual smoke:
    #   uv run python -m foreclosure_scraper.scrapers.law_firms.mewborn_deselms
    import asyncio

    async def _main() -> None:
        s = MewbornDeSelms()
        rows = await s.safe_run()
        print("outcome:", s.last_outcome, "|", s.last_reason)
        print("rows:", len(rows))
        for r in rows[:10]:
            print(
                " -", r.county, "|", r.street_address, "| bid",
                r.opening_bid, "| date", r.sale_date, "| at", r.sale_location,
            )

    asyncio.run(_main())
