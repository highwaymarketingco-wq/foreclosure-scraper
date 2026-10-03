"""Sheriff sale listings — Brunswick NC, Charleston SC, Cleveland NC.

Sheriff sales are judicial foreclosure auctions conducted by the county
sheriff's office. In NC the power-of-sale foreclosure is non-judicial, so
sheriff sales here are primarily SC (Charleston is a judicial-foreclosure
state) plus NC tax-foreclosure sheriffs that publish auction lists.

Sources (free, no auth):
  - Brunswick County NC Sheriff: brunswicksheriff.com/resources/auctions
  - Charleston County SC Sheriff: charlestoncounty.org/departments/sheriff/pending-sales.php
  - Cleveland County NC Sheriff: sheriffclevelandcounty.com

These sites publish plain HTML tables / PDFs of upcoming sales. We parse
the HTML tables defensively — county sites change layout frequently and
without notice, so every field is best-effort: a missing column degrades
to None rather than crashing the whole run. PDFs (when the listing page
links to one) are noted in raw but not OCR'd here — the doc-OCR
enrichment handles those downstream.

Robots.txt is checked per host; if disallowed, that county is skipped
(fail-closed compliance — never query a robots-banned path).

Listing type: SHERIFF_SALE.

CONFIRMED-LIVE FALSE-POSITIVE BUG, FOUND AND FIXED 2026-10-01 (the "silent
success" failure mode CLAUDE.md warns about: a believable, non-zero count
that is simply wrong). `_fetch_county`'s sub-page crawl decided whether to
follow a link by checking `("sale", "auction", "foreclosure", "pending",
"sheriff") in href.lower()` against the FULL href -- but every single page
on sheriffclevelandcounty.com contains "sheriff" as a substring of its own
HOSTNAME, so that check matched literally every link on the site (verified
live: 60 unrelated URLs matched on one page, including a LinkedIn
share-article link for an unrelated felony drug-arrest press release, the
Facebook page, an App Store listing, concealed-carry-permit and funeral-
escort forms). The generic text-block fallback parser then ran over
"careers", "crimestoppers", "missing-persons", "fallen-heroes", and
"sex-offender-registry" and pattern-matched the department's own street
address and random digits out of unrelated boilerplate as if they were
sale listings. Live result before the fix: 6 fabricated "Cleveland County"
Listings, none of them real. The county's ACTUAL, correctly-published state
(verified live via its own PDF, `.../uploads/2025/05/No-Public-Auction-8.5-
x-11-in.pdf`, which says literally "NO PUBLIC AUCTION at this time") is
ZERO -- `expected_min_count = 0` already allows for this, so the right fix
is to stop fabricating rows, not to find something to report.

Fixed two ways: (1) the sub-page keyword check now runs against the URL
PATH only (host stripped) and skips non-HTML file extensions (pdf/jpg/png/
...), so it can no longer match on the domain name itself; (2) the
free-text fallback parser in all three county parsers now also requires an
explicit sale-context phrase (_SALE_CONTEXT_RE: "sheriff sale", "public
auction", "execution sale", "foreclosure sale", "notice of sale", "pending
sale(s)") inside the same text block before treating an address/case-number
match as a real listing, so an unrelated page with a stray address or
docket-shaped number can no longer manufacture a fake sale.

CONFIRMED-LIVE FALSE-NEGATIVE, PARTIALLY FIXED 2026-10-02 (`lt_sheriff_sale`
zero-gap breadth audit: the board carries only 1 row board-wide for this
listing type, and that single row is ITSELF a leftover of the 2026-10-01 bug
above -- `street_address="311 E. Marion Street"`, no case number, no sale
date, i.e. Cleveland's own department address fabricated before the fix
existed, never cleaned up since no full pipeline run has completed since;
the true current real count of sheriff_sale leads on the board is 0, not 1).
While live-checking whether a genuinely working source was being
mis-filtered, found one real false negative: Brunswick County NC's current
page (brunswicksheriff.com/resources/auctions, fetched live 2026-10-02)
carries a real posting -- "FILE# 19 CVS 004029-640 ... SHERIFF'S AUCTION
7/17/2026 (POSTPONED TO 7/31/26)" -- with a real civil case number, but
`_parse_brunswick` returned ZERO listings against this exact live page
because `_SALE_CONTEXT_RE` (added the day before) required the word "sale",
and Brunswick's own site calls its postings "Sheriff's Auctions" throughout,
never "sheriff's sale". Added `sheriff'?s?\\s+auction` as its own
alternative (not loosened to bare "auction", which is exactly what let the
original false positive through) -- this widens recall for any page that
puts the sale-context phrase and the address/case number in the SAME text
block, which is the shape this module's own test fixtures use.

NOT YET FIXED, same investigation, scoped but intentionally not attempted
here (would touch all three parsers' shared per-element loop, a bigger and
riskier change than this pass's mandate): Brunswick's THIS SPECIFIC live
posting still parses to 0 listings even after the regex widening above,
because its real markup splits the case number and the "Sheriff's Auction"
phrase into separate sibling `<p>` tags inside the same `div.entry-content`
(`<p>FILE# 19 CVS 004029-640</p>` ... `<p><a>SHERIFF'S AUCTION ...</a></p>`),
and the fallback parser only ever evaluates one CSS-matched element's own
text at a time -- it never joins sibling paragraphs into one block. Fixing
that needs grouping consecutive sibling `<p>` text within the same parent
before applying `_SALE_CONTEXT_RE`/address/case extraction, which changes
the false-positive surface this module's whole fix history is about, so it
deserves its own dedicated pass with fresh fixtures, not a rider on this one.

This is a narrow fix to a narrow genuine legal category, not a bucket-
reclassification bug: see `distress_score.py` / the per-county sheriff
scrapers' own docstrings (Anderson, Barnwell) for why real SHERIFF_SALE
volume is and should stay small in NC/SC -- most mortgage foreclosures here
run through a trustee (NC) or Master-in-Equity (SC), not the literal
Sheriff's Office -- so this fix widens recall for the genuinely-narrow
category rather than feeding it from a different, larger bucket.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urljoin

import httpx
import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# (state, county, label, base_url, search_path)
SOURCES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "NC", "Brunswick", "Brunswick County Sheriff",
        "https://www.brunswicksheriff.com",
        "/resources/auctions",
    ),
    (
        "SC", "Charleston", "Charleston County Sheriff",
        "https://www.charlestoncounty.org",
        "/departments/sheriff/pending-sales.php",
    ),
    (
        "NC", "Cleveland", "Cleveland County Sheriff",
        "https://www.sheriffclevelandcounty.com",
        "/",
    ),
)

# --- helpers ---------------------------------------------------------------

_PRICE_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d{2})?)")
_DATE_RE = re.compile(
    r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s*\d{4}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b)",
    re.I,
)
_CASE_RE = re.compile(
    r"\b(\d{2,4}[\s\-]?[A-Z]{1,4}[\s\-]?\d{2,6})\b", re.I,
)
_ADDR_RE = re.compile(
    r"\d+\s+[A-Z][\w .'#-]+"
    r"(?:\s+(?:St|Street|Rd|Road|Dr|Drive|Ave|Avenue|Ln|Lane|Ct|Court|"
    r"Blvd|Boulevard|Hwy|Highway|Pl|Place|Way|Cir|Circle|Trl|Trail|"
    r"Pkwy|Parkway|Ter|Terrace))\b\.?",
    re.I,
)
_UPSET_BID_RE = re.compile(r"upset\s+bid", re.I)
#: Required before the free-text fallback parser will treat an address/
#: case-number match as a real sale listing — see the module docstring's
#: 2026-10-01 false-positive writeup for why this guard exists.
#:
#: 2026-10-02 FALSE-NEGATIVE FOUND LIVE (zero-gap column-breadth audit of
#: `lt_sheriff_sale`, 1/148 counties): this guard required the literal word
#: "sale" in the same text block, but Brunswick County NC's OWN real,
#: currently-live page (brunswicksheriff.com/resources/auctions, confirmed
#: live 2026-10-02) titles its postings "SHERIFF'S AUCTION", never "sheriff's
#: sale" -- e.g. a real, current posting reading "FILE# 19 CVS 004029-640 ...
#: SHERIFF'S AUCTION 7/17/2026 (POSTPONED TO 7/31/26)" has a real case number
#: but was silently dropped: `_parse_brunswick` on that exact live page
#: returns 0 listings today. `sheriff'?s?\s+auction` added below so the same
#: department's own preferred term is recognized without loosening the guard
#: to bare "auction" (which is what let the original false positive through).
#: Apostrophe class covers both the plain ASCII "'" and the curly Unicode
#: right single quote (U+2019) that selectolax's text() returns once a page's
#: literal "&#8217;"/"&rsquo;" entity is decoded -- Brunswick's and Cleveland's
#: real live pages both use the curly form throughout ("Sheriff’s Auctions"),
#: so a straight-quote-only pattern silently never matches real text at all
#: (found live 2026-10-02 fixing the sibling false-negative below).
_APOS = "['’]?"
_SALE_CONTEXT_RE = re.compile(
    r"sheriff" + _APOS + r"s?\s+sale|sheriff" + _APOS + r"s?\s+auction|public\s+auction|"
    r"execution\s+sale|foreclosure\s+sale|notice\s+of\s+sale|pending\s+sales?|civil\s+sale",
    re.I,
)
#: File extensions that are never worth HTML-parsing as a sub-page (a PDF
#: fed through HTMLParser produces no real rows, just wasted fetches).
_NON_HTML_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".doc", ".docx", ".xls", ".xlsx")


def _parse_money(text: str | None) -> float | None:
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    # Try several known formats
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
    # Regex fallback for embedded dates
    m = _DATE_RE.search(text)
    if m:
        s = m.group(1)
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


def _extract_case_number(text: str) -> str | None:
    m = _CASE_RE.search(text or "")
    return m.group(1).strip() if m else None


def _extract_address(text: str) -> str | None:
    m = _ADDR_RE.search(text or "")
    return m.group().strip().rstrip(".") if m else None


async def _robots_allows(host: str, path: str) -> bool:
    """Check robots.txt for `*` group. Fails OPEN (allows) if unreachable —
    these county sites generally have no robots restrictions, and a transient
    DNS failure shouldn't wall off public auction data."""
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


async def _fetch_html(url: str, timeout: float = 30.0) -> str:
    """Fetch HTML with the shared client + browser-like headers."""
    from ...http_client import client
    async with client(timeout=timeout) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.text


def _parse_table_rows(tree: HTMLParser) -> list[dict[str, str]]:
    """Extract all <tr> rows from tables on the page, returning a list of
    dicts mapping lowercased header -> cell text. Falls back to positional
    columns if no <th> headers are found."""
    rows: list[dict[str, str]] = []

    tables = tree.css("table")
    for table in tables:
        # Determine headers
        headers: list[str] = []
        thead = table.css_first("thead")
        if thead is not None:
            for th in thead.css("th"):
                headers.append(th.text(strip=True).lower())
        if not headers:
            first_row = table.css_first("tr")
            if first_row is not None:
                ths = first_row.css("th")
                if ths:
                    headers = [th.text(strip=True).lower() for th in ths]

        for tr in table.css("tr"):
            cells = tr.css("td")
            if not cells:
                continue
            if headers and len(cells) >= 2:
                row: dict[str, str] = {}
                for i, td in enumerate(cells):
                    key = headers[i] if i < len(headers) else f"col_{i}"
                    row[key] = td.text(strip=True)
                if any(v.strip() for v in row.values()):
                    rows.append(row)
            else:
                # Positional fallback
                vals = [td.text(strip=True) for td in cells]
                if any(v.strip() for v in vals):
                    row = {f"col_{i}": v for i, v in enumerate(vals)}
                    rows.append(row)
    return rows


def _row_to_listing(
    row: dict[str, str],
    state: str,
    county: str,
    source_url: str,
    sale_date_raw: str | None,
    defendant_raw: str | None,
    address_raw: str | None,
    case_raw: str | None,
    bid_raw: str | None,
    description_raw: str | None,
) -> Listing | None:
    """Build a Listing from parsed row data. All fields best-effort."""

    # Try to find values in the row dict by common header names
    def _find(keys: tuple[str, ...]) -> str | None:
        for k in keys:
            for rk, rv in row.items():
                if k in rk and rv.strip():
                    return rv.strip()
        return None

    case_number = case_raw or _find(
        ("case", "file", "docket", "civil", "col_0")
    )
    defendant = defendant_raw or _find(
        ("defendant", "debtor", "owner", "party", "respondent")
    )
    address = address_raw or _find(
        ("address", "property", "location", "premises", "parcel")
    )
    sale_date_text = sale_date_raw or _find(
        ("sale date", "date", "auction date", "sale")
    )
    bid_text = bid_raw or _find(
        ("bid", "opening", "minimum", "price", "amount")
    )
    # Promote plaintiff (foreclosing creditor) + judgment amount from the row.
    plaintiff = _find(
        ("plaintiff", "creditor", "lienholder", "petitioner", "mortgagee")
    )
    judgment_text = _find(
        ("judgment", "debt", "amount owed", "judgment amount", "balance due")
    )
    judgment_amount = _parse_money(judgment_text)

    # If we still don't have an address, try regex on all cell text
    if not address:
        blob = " ".join(row.values())
        address = _extract_address(blob)
    if not case_number:
        blob = " ".join(row.values())
        case_number = _extract_case_number(blob)

    sale_date = _parse_date(sale_date_text)
    opening_bid = _parse_money(bid_text)

    # Upset-bid deadline (NC power-of-sale). _UPSET_BID_RE was dead code. When
    # the row mentions an upset bid, take a date near the phrase; otherwise
    # fall back to the 10-day statutory window off the sale date.
    upset_bid_deadline = None
    row_blob = " ".join(row.values())
    um = _UPSET_BID_RE.search(row_blob)
    if um:
        upset_bid_deadline = _parse_date(row_blob[um.end():um.end() + 80])
        if upset_bid_deadline is None and sale_date is not None:
            upset_bid_deadline = sale_date + timedelta(days=10)

    # Need at least an address OR case number to be useful
    if not address and not case_number:
        return None

    description_parts = []
    if description_raw:
        description_parts.append(description_raw)
    if defendant:
        description_parts.append(f"Defendant: {defendant}")
    if bid_text:
        description_parts.append(f"Opening bid: {bid_text}")

    return Listing(
        source="national.sheriff_sales",
        source_url=source_url,
        listing_type=ListingType.SHERIFF_SALE,
        property_kind=PropertyKind.UNKNOWN,
        street_address=address,
        county=county,
        state=state,
        case_number=case_number,
        defendant=defendant,
        plaintiff=plaintiff,
        judgment_amount=judgment_amount,
        upset_bid_deadline=upset_bid_deadline,
        sale_date=sale_date,
        opening_bid=opening_bid,
        sale_location=f"{county} County Sheriff's Office",
        description=" | ".join(description_parts) if description_parts else None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "sheriff_sale": {
                "county": county,
                "state": state,
                "sale_date_raw": sale_date_text,
                "bid_raw": bid_text,
                "judgment_raw": judgment_text,
                "full_row": row,
            },
        },
    )


def _parse_brunswick(html: str, source_url: str) -> list[Listing]:
    """Brunswick NC sheriff — HTML tables or list items with auction data."""
    tree = HTMLParser(html)
    out: list[Listing] = []

    rows = _parse_table_rows(tree)
    for row in rows:
        li = _row_to_listing(
            row, "NC", "Brunswick", source_url,
            sale_date_raw=None, defendant_raw=None,
            address_raw=None, case_raw=None,
            bid_raw=None, description_raw=None,
        )
        if li:
            out.append(li)

    # Also check for list-based layouts (<li> or <div> with auction text)
    if not out:
        for el in tree.css("li, div.entry, div.auction, div.content p"):
            text = el.text(strip=True)
            if not text or len(text) < 15:
                continue
            # 2026-10-01: require explicit sale-context phrasing in the same
            # text block -- see module docstring's false-positive writeup.
            if not _SALE_CONTEXT_RE.search(text):
                continue
            addr = _extract_address(text)
            case = _extract_case_number(text)
            if not addr and not case:
                continue
            sale_date = _parse_date(text)
            bid = _parse_money(text)
            # Try to extract defendant from common label patterns
            defendant = None
            dm = re.search(r"(?:defendant|debtor|owner)\s*:?\s*(.+?)(?:\n|;|\||$)",
                           text, re.I)
            if dm:
                defendant = dm.group(1).strip()

            li = Listing(
                source="national.sheriff_sales",
                source_url=source_url,
                listing_type=ListingType.SHERIFF_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr,
                county="Brunswick",
                state="NC",
                case_number=case,
                defendant=defendant,
                sale_date=sale_date,
                opening_bid=bid,
                sale_location="Brunswick County Sheriff's Office",
                description=text[:500] if text else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sheriff_sale": {"county": "Brunswick", "state": "NC",
                                      "text_block": text[:500]}},
            )
            out.append(li)

    return out


def _parse_charleston(html: str, source_url: str) -> list[Listing]:
    """Charleston SC sheriff pending sales — typically an HTML table."""
    tree = HTMLParser(html)
    out: list[Listing] = []

    rows = _parse_table_rows(tree)
    for row in rows:
        li = _row_to_listing(
            row, "SC", "Charleston", source_url,
            sale_date_raw=None, defendant_raw=None,
            address_raw=None, case_raw=None,
            bid_raw=None, description_raw=None,
        )
        if li:
            out.append(li)

    # Fallback: parse <p> or <div> blocks that contain sale info
    if not out:
        for el in tree.css("p, div.sale, div.listing, div.content div"):
            text = el.text(strip=True)
            if not text or len(text) < 20:
                continue
            # 2026-10-01: require explicit sale-context phrasing in the same
            # text block -- see module docstring's false-positive writeup.
            if not _SALE_CONTEXT_RE.search(text):
                continue
            addr = _extract_address(text)
            case = _extract_case_number(text)
            if not addr and not case:
                continue
            sale_date = _parse_date(text)
            bid = _parse_money(text)
            defendant = None
            dm = re.search(
                r"(?:defendant|debtor|owner|judgment\s+debtor)\s*:?\s*(.+?)(?:\n|;|\||$)",
                text, re.I,
            )
            if dm:
                defendant = dm.group(1).strip()

            li = Listing(
                source="national.sheriff_sales",
                source_url=source_url,
                listing_type=ListingType.SHERIFF_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr,
                county="Charleston",
                state="SC",
                case_number=case,
                defendant=defendant,
                sale_date=sale_date,
                opening_bid=bid,
                sale_location="Charleston County Sheriff's Office",
                description=text[:500] if text else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sheriff_sale": {"county": "Charleston", "state": "SC",
                                      "text_block": text[:500]}},
            )
            out.append(li)

    return out


def _parse_cleveland(html: str, source_url: str) -> list[Listing]:
    """Cleveland NC sheriff — HTML tables or list items."""
    tree = HTMLParser(html)
    out: list[Listing] = []

    rows = _parse_table_rows(tree)
    for row in rows:
        li = _row_to_listing(
            row, "NC", "Cleveland", source_url,
            sale_date_raw=None, defendant_raw=None,
            address_raw=None, case_raw=None,
            bid_raw=None, description_raw=None,
        )
        if li:
            out.append(li)

    # Fallback: scan all text blocks
    if not out:
        for el in tree.css("p, li, div.entry, div.auction, div.content div, article"):
            text = el.text(strip=True)
            if not text or len(text) < 15:
                continue
            # 2026-10-01: require explicit sale-context phrasing in the same
            # text block -- see module docstring's false-positive writeup.
            if not _SALE_CONTEXT_RE.search(text):
                continue
            addr = _extract_address(text)
            case = _extract_case_number(text)
            if not addr and not case:
                continue
            sale_date = _parse_date(text)
            bid = _parse_money(text)
            defendant = None
            dm = re.search(
                r"(?:defendant|debtor|owner)\s*:?\s*(.+?)(?:\n|;|\||$)",
                text, re.I,
            )
            if dm:
                defendant = dm.group(1).strip()

            li = Listing(
                source="national.sheriff_sales",
                source_url=source_url,
                listing_type=ListingType.SHERIFF_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr,
                county="Cleveland",
                state="NC",
                case_number=case,
                defendant=defendant,
                sale_date=sale_date,
                opening_bid=bid,
                sale_location="Cleveland County Sheriff's Office",
                description=text[:500] if text else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sheriff_sale": {"county": "Cleveland", "state": "NC",
                                      "text_block": text[:500]}},
            )
            out.append(li)

    return out


_PARSERS = {
    "Brunswick": _parse_brunswick,
    "Charleston": _parse_charleston,
    "Cleveland": _parse_cleveland,
}


async def _fetch_county(
    state: str, county: str, label: str,
    base_url: str, search_path: str,
) -> list[Listing]:
    host = httpx.URL(base_url).host
    if not await _robots_allows(host, search_path):
        log.info("sheriff_sales.robots_skip", county=county, host=host)
        return []

    url = urljoin(base_url, search_path)
    try:
        html = await _fetch_html(url, timeout=30.0)
    except Exception as exc:
        log.warning("sheriff_sales.fetch_fail", county=county, url=url,
                    error=str(exc)[:200])
        return []

    if not html or len(html) < 200:
        log.info("sheriff_sales.empty_html", county=county, url=url)
        return []

    # Also follow links to sub-pages that may contain sale listings.
    # BUG FIXED 2026-10-01: this used to check the keyword list against the
    # FULL href, but every page on e.g. sheriffclevelandcounty.com contains
    # "sheriff" as a substring of its own hostname -- that matched literally
    # every link on the site (see module docstring). Check the PATH only
    # (host stripped) and skip non-HTML files (a PDF fed through HTMLParser
    # yields nothing real and is a wasted fetch).
    tree = HTMLParser(html)
    sub_urls: list[str] = [url]
    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "")
        if not href:
            continue
        full = urljoin(base_url, href)
        try:
            path_lower = httpx.URL(full).path.lower()
        except Exception:
            continue
        if path_lower.endswith(_NON_HTML_EXT):
            continue
        if any(kw in path_lower for kw in
               ("sale", "auction", "foreclosure", "pending", "civil")):
            if full not in sub_urls:
                sub_urls.append(full)

    parser = _PARSERS.get(county)
    if parser is None:
        log.warning("sheriff_sales.no_parser", county=county)
        return []

    out: list[Listing] = []
    seen_urls: set[str] = set()
    for page_url in sub_urls[:6]:  # cap at 6 pages to stay polite
        if page_url != url:
            try:
                html = await _fetch_html(page_url, timeout=30.0)
            except Exception as exc:
                log.debug("sheriff_sales.subpage_fail", url=page_url,
                          error=str(exc)[:120])
                continue
            if not html or len(html) < 200:
                continue
        listings = parser(html, page_url)
        for li in listings:
            if li.source_url not in seen_urls:
                seen_urls.add(li.source_url)
                out.append(li)
        if listings:
            log.info("sheriff_sales.page_done", county=county,
                     url=page_url, count=len(listings))

    log.info("sheriff_sales.county_done", county=county, state=state,
             total=len(out))
    return out


class SheriffSales(BaseScraper):
    slug = "national.sheriff_sales"
    name = "Sheriff Sales (Brunswick NC, Charleston SC, Cleveland NC)"
    category = "sheriff_sale"
    expected_min_count = 0
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state, county, label, base_url, search_path in SOURCES:
            try:
                listings = await _fetch_county(
                    state, county, label, base_url, search_path,
                )
                out.extend(listings)
            except Exception as exc:
                log.warning("sheriff_sales.county_failed", county=county,
                            state=state, error=str(exc)[:200])
        return out
