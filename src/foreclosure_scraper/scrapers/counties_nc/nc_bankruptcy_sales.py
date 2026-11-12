"""NC Bankruptcy Court — Public Sales Notices.

The NC Eastern and Middle Bankruptcy Court districts publish public
sale notices at:
  - nceb.uscourts.gov/Public-Sales-Notice (Eastern District)
  - ncmb.uscourts.gov/public-sales (Middle District)

These are bankruptcy trustee sales — properties being liquidated through
Chapter 7/13 bankruptcy proceedings.  The debtor is being forced to sell
real property to satisfy creditors.

We already cover bankruptcy filings via CourtListener, but this captures
the actual SALE notices — properties that have moved from filing to
liquidation, which is a later-stage distress signal.

Page shape (verified live 2026-10-01): the real content on both district
sites is a short list, grouped by month, of exactly ONE link per sale:

    <p><a href="/sites/nceb/files/sale_20261021_Crabtree_Family_Moving_LLC.pdf">
      October 21, 2026 - Crabtree Family Moving, LLC</a></p>

There is no address, case number, or dollar amount on the index page at
all — those live inside the linked PDF notice, so this scraper's only job
is to lift (sale_date, debtor, pdf_url) per link and WIRE THE PDF via
stamp_documents() so enrich_doc_ocr can read the address/amount/case
number out of the actual notice.

FIXED 2026-10-01 (national-auction-tier audit, batch 4): the previous
version regex-scanned <table> rows (there are none on either site) and,
finding nothing, fell back to scanning every <li> on the page for
bankruptcy-flavored keywords ("case", "trustee", ...) — which matched the
SITE NAVIGATION menu ("Trustee Contact List", "Case Info Case
Assignments", "Public Interest Cases", ...) and emitted those nav links
as fake BANKRUPTCY listings with no address/debtor/date/amount at all.
Live-verified: all 7 rows it used to produce were fabricated nav chrome.
The Middle District site's genuine empty state is the literal sentence
"No public sales are listed at this time." — a real, expected ZERO, not
an error to paper over with nav-menu rows.

Free, public, no login.
Slug: counties_nc.nc_bankruptcy_sales
Category: bankruptcy
ListingType: BANKRUPTCY
"""
from __future__ import annotations

import html as html_lib
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...document_links import stamp_documents
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URLS = [
    ("Eastern", "https://www.nceb.uscourts.gov/Public-Sales-Notice"),
    ("Middle", "https://www.ncmb.uscourts.gov/public-sales"),
]

# One sale notice = one <a> whose href is a PDF and whose link text is
# "<Month> <Day>[,] <Year> - <Debtor name>". This shape does not occur in
# either site's nav/menu chrome, so it cannot false-positive on nav links
# the way the old <li>-keyword fallback did.
_SALE_LINK_RE = re.compile(
    r'<a\s+href="([^"]+\.pdf)"[^>]*>\s*'
    r'([A-Za-z]+\s+\d{1,2},?\s*\d{4})\s*-\s*'
    r'([^<]+?)\s*</a>',
    re.I,
)

_NO_SALES_RE = re.compile(r"no public sales", re.I)


def _parse_sale_date(raw: str) -> datetime | None:
    cleaned = re.sub(r"\s+", " ", raw).strip()
    for fmt in ("%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def parse_district_html(html: str, district: str, url: str) -> list[Listing]:
    """Pure parse: district index HTML -> Listings. No network. Returns []
    on a genuine zero (including the Middle District's literal "no public
    sales" empty state) as well as on an unrecognized page shape — this
    function never fabricates a row from nav/menu chrome."""
    out: list[Listing] = []
    if not html or len(html) < 200:
        return out

    matches = list(_SALE_LINK_RE.finditer(html))
    if not matches:
        if _NO_SALES_RE.search(html):
            log.info("nc_bankruptcy_sales.zero_expected", district=district)
        else:
            log.warning("nc_bankruptcy_sales.no_matches_unexpected", district=district,
                        size=len(html))
        return out

    for m in matches:
        pdf_href, date_raw, debtor_raw = m.groups()
        pdf_url = urljoin(url, pdf_href)
        debtor = html_lib.unescape(debtor_raw).strip().strip(",")
        sale_date = _parse_sale_date(html_lib.unescape(date_raw))

        li = Listing(
            source="counties_nc.nc_bankruptcy_sales",
            source_url=pdf_url,
            listing_type=ListingType.BANKRUPTCY,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county=f"{district} District",
            defendant=debtor or None,
            sale_date=sale_date,
            description=(
                f"NC Bankruptcy Court ({district} District) public sale — {debtor}"
                if debtor else f"NC Bankruptcy Court ({district} District) public sale"
            ),
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"nc_bankruptcy_sales": {
                "district": district,
                "debtor": debtor or None,
                "sale_date_raw": date_raw.strip(),
                "pdf_url": pdf_url,
                "index_url": url,
            }},
        )
        stamp_documents(li, [pdf_url])
        out.append(li)
    return out


class NCBankruptcySales(BaseScraper):
    slug = "counties_nc.nc_bankruptcy_sales"
    name = "NC Bankruptcy Court Public Sales Notices"
    category = "bankruptcy"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for district, url in URLS:
            try:
                html = await get_text(url, impersonate=True, timeout=40.0)
            except Exception as exc:
                log.warning("nc_bankruptcy_sales.fetch_fail", district=district, error=str(exc)[:160])
                continue
            out.extend(parse_district_html(html, district, url))

        log.info("nc_bankruptcy_sales.done", count=len(out))
        return out
