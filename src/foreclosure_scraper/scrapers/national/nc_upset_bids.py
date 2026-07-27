"""NC upset bid listings — 10-day upset bid period after foreclosure sale.

In NC, after a foreclosure sale under power of sale, there is a statutory
10-day "upset bid" period during which any qualified bidder may submit a
higher bid (at least 5% above the last bid). The clerk of court in each
county posts these upset bid opportunities. If no upset bid is filed
within 10 days, the sale becomes final.

This scraper checks county clerk of court pages for upset bid postings:

  - Buncombe:   buncombecounty.org/clerk
  - Henderson:  hendersoncountync.gov/clerk
  - Cleveland:  clevelandcounty.com
  - Gaston:     gastoncountync.gov

These clerk pages link to upset bid notices, sale reports, or schedules
that list the properties currently in the upset bid window. We extract:
  - case number
  - property address
  - sale date (the original sale that triggered the upset period)
  - upset bid deadline (sale_date + 10 days, unless explicitly stated)

Listing type: SHERIFF_SALE (closest fit — upset bids are part of the NC
foreclosure auction process overseen by the clerk, not a separate
ListingType. Tagged as SHERIFF_SALE for dashboard grouping with other
sheriff/clerk auction sales).

Robots.txt checked per host; fail-closed if disallowed.
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

# NC upset bid period is 10 days from the sale (N.C. Gen. Stat. § 45-21.27)
UPSET_BID_DAYS = 10

# (county, base_url, search_path, link_keywords)
SOURCES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "Buncombe",
        "https://taxforeclosures.buncombenc.gov",
        "/",
        ("upset", "bid", "sale", "foreclosure", "report", "bidding", "window"),
    ),
    (
        "Henderson",
        "https://www.hendersoncountync.gov",
        "/clerk",
        ("upset", "bid", "sale", "foreclosure", "report"),
    ),
    (
        "Cleveland",
        "https://www.clevelandcounty.com",
        "/",
        ("upset", "bid", "sale", "foreclosure", "clerk", "court"),
    ),
    (
        "Gaston",
        "https://www.gastoncountync.gov",
        "/government/county_departments/clerk_of_court",
        ("upset", "bid", "sale", "foreclosure", "report"),
    ),
)

# --- regex helpers ---------------------------------------------------------

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
_DATE_RE = re.compile(
    r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s*\d{4}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b)",
    re.I,
)
_PRICE_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d{2})?)")


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


def _extract_case(text: str) -> str | None:
    m = _CASE_RE.search(text or "")
    return m.group(1).strip() if m else None


def _extract_address(text: str) -> str | None:
    m = _ADDR_RE.search(text or "")
    return m.group().strip().rstrip(".") if m else None


def _extract_date(text: str) -> datetime | None:
    return _parse_date(text)


async def _robots_allows(host: str, path: str) -> bool:
    """Check robots.txt for the `*` group. Fails OPEN if unreachable —
    county clerk sites generally allow public access to court records."""
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
    from ...http_client import client
    async with client(timeout=timeout) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.text


def _find_upset_bid_links(tree: HTMLParser, base_url: str,
                          keywords: tuple[str, ...]) -> list[str]:
    """Find links on the clerk page that likely lead to upset bid postings."""
    urls: list[str] = []
    seen: set[str] = set()
    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "")
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        link_text = (a.text(strip=True) or "").lower()
        href_lower = href.lower()
        # Match if the link text or href contains any keyword
        if any(kw in link_text or kw in href_lower for kw in keywords):
            full = urljoin(base_url, href)
            if full not in seen and full.startswith("http"):
                seen.add(full)
                urls.append(full)
    return urls


def _parse_upset_bid_page(html: str, source_url: str,
                          county: str) -> list[Listing]:
    """Parse a single page for upset bid entries. Handles table-based and
    text-block-based layouts defensively."""
    tree = HTMLParser(html)
    out: list[Listing] = []

    # --- Table-based layout ---
    for table in tree.css("table"):
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
            if not cells or len(cells) < 2:
                continue
            cell_texts = [td.text(strip=True) for td in cells]
            blob = " ".join(cell_texts)

            case_number = _extract_case(blob)
            address = _extract_address(blob)

            # Try to match by header
            sale_date_text = None
            bid_deadline_text = None
            if headers:
                for i, h in enumerate(headers):
                    if i >= len(cell_texts):
                        break
                    if any(k in h for k in ("sale date", "date of sale", "sale")):
                        sale_date_text = cell_texts[i]
                    elif any(k in h for k in ("deadline", "upset", "expires", "due")):
                        bid_deadline_text = cell_texts[i]
                    elif any(k in h for k in ("case", "file", "docket")):
                        if not case_number:
                            case_number = cell_texts[i].strip()
                    elif any(k in h for k in ("address", "property", "location")):
                        if not address:
                            address = cell_texts[i].strip()

            # Fallback regex
            if not case_number:
                case_number = _extract_case(blob)
            if not address:
                address = _extract_address(blob)
            if not sale_date_text:
                dates = _DATE_RE.findall(blob)
                if dates:
                    sale_date_text = dates[0]

            sale_date = _parse_date(sale_date_text)

            # Upset bid deadline: explicit first, else sale_date + 10 days
            upset_deadline = _parse_date(bid_deadline_text)
            if not upset_deadline and sale_date:
                upset_deadline = sale_date + timedelta(days=UPSET_BID_DAYS)

            # Need at least case number or address
            if not case_number and not address:
                continue

            out.append(Listing(
                source="national.nc_upset_bids",
                source_url=source_url,
                listing_type=ListingType.SHERIFF_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=address,
                county=county,
                state="NC",
                case_number=case_number,
                sale_date=sale_date,
                upset_bid_deadline=upset_deadline,
                foreclosure_process="power_of_sale",
                sale_location=f"{county} County Clerk of Court",
                description=blob[:500] if blob else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "nc_upset_bids": {
                        "county": county,
                        "sale_date_raw": sale_date_text,
                        "deadline_raw": bid_deadline_text,
                        "deadline_source": "explicit" if bid_deadline_text else "computed",
                        "full_row": cell_texts,
                    },
                },
            ))

    # --- Text-block layout (no tables) ---
    if not out:
        for el in tree.css("p, li, div.entry, div.listing, div.content, article"):
            text = el.text(strip=True)
            if not text or len(text) < 15:
                continue
            # Only process blocks that look like upset bid entries
            if not any(kw in text.lower() for kw in
                       ("upset", "bid", "sale", "foreclosure", "case")):
                continue

            case_number = _extract_case(text)
            address = _extract_address(text)
            if not case_number and not address:
                continue

            sale_date = _extract_date(text)
            upset_deadline = sale_date + timedelta(days=UPSET_BID_DAYS) if sale_date else None

            out.append(Listing(
                source="national.nc_upset_bids",
                source_url=source_url,
                listing_type=ListingType.SHERIFF_SALE,
                property_kind=PropertyKind.UNKNOWN,
                street_address=address,
                county=county,
                state="NC",
                case_number=case_number,
                sale_date=sale_date,
                upset_bid_deadline=upset_deadline,
                foreclosure_process="power_of_sale",
                sale_location=f"{county} County Clerk of Court",
                description=text[:500] if text else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "nc_upset_bids": {
                        "county": county,
                        "text_block": text[:500],
                        "deadline_source": "computed" if sale_date else "unknown",
                    },
                },
            ))

    return out


async def _fetch_county(county: str, base_url: str,
                        search_path: str,
                        keywords: tuple[str, ...]) -> list[Listing]:
    host = httpx.URL(base_url).host
    if not await _robots_allows(host, search_path):
        log.info("nc_upset_bids.robots_skip", county=county, host=host)
        return []

    url = urljoin(base_url, search_path)
    try:
        html = await _fetch_html(url, timeout=30.0)
    except Exception as exc:
        log.warning("nc_upset_bids.fetch_fail", county=county, url=url,
                    error=str(exc)[:200])
        return []

    if not html or len(html) < 200:
        log.info("nc_upset_bids.empty_html", county=county, url=url)
        return []

    tree = HTMLParser(html)

    # Find sub-page links that likely contain upset bid data
    sub_urls = _find_upset_bid_links(tree, base_url, keywords)
    # Always include the main page itself
    all_urls = [url] + sub_urls[:8]  # cap at 8 sub-pages

    out: list[Listing] = []
    seen_keys: set[tuple[str, str]] = set()
    for page_url in all_urls:
        if page_url != url:
            try:
                page_html = await _fetch_html(page_url, timeout=30.0)
            except Exception as exc:
                log.debug("nc_upset_bids.subpage_fail", url=page_url,
                          error=str(exc)[:120])
                continue
            if not page_html or len(page_html) < 200:
                continue
        else:
            page_html = html

        listings = _parse_upset_bid_page(page_html, page_url, county)
        for li in listings:
            # Dedupe by case_number + address
            key = (li.case_number or "", li.street_address or "")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(li)

        if listings:
            log.info("nc_upset_bids.page_done", county=county,
                     url=page_url, count=len(listings))

    log.info("nc_upset_bids.county_done", county=county, total=len(out))
    return out


class NCUpsetBids(BaseScraper):
    slug = "national.nc_upset_bids"
    name = "NC Upset Bid Listings (Buncombe, Henderson, Cleveland, Gaston)"
    category = "upset_bid"
    expected_min_count = 0
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for county, base_url, search_path, keywords in SOURCES:
            try:
                listings = await _fetch_county(
                    county, base_url, search_path, keywords,
                )
                out.extend(listings)
            except Exception as exc:
                log.warning("nc_upset_bids.county_failed", county=county,
                            error=str(exc)[:200])
        return out
