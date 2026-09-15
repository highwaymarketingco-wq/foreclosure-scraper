"""Wake County NC - Tax Foreclosure properties.

Wake County publishes tax foreclosure properties at wake.gov as an
accordion, one item per municipality (Angier, Apex, Cary, ... Raleigh,
Wake Forest, ...). Each accordion body holds either "None at this time"
or one <p> per property in a fixed label:value shape:

    <p>Tax ID#: <a href="...Account.asp?id=NNNNNNN">NNNNNNN</a>
       Amount due: $X,XXX.XX*<br>
       Property Address: ADDR<br>
       Date of First Action: DATE<br>
       Date Judgment Filed with Courts: DATE<br>
       Date of Sale: DATE (or "To Be Announced")</p>

FOUND 2026-09-15 (background triage agent, this codebase's zero-row-
scraper audit; confirmed live by hand before rewriting): the ORIGINAL
version of this module assumed a plain HTML <table> and never matched
this accordion structure -- 0 rows, always, regardless of what the page
actually had. It also carried `active_months=(1..8)`, so even a correct
parser would have gone dormant every September-December -- live-checked
2026-09-15 (September) and Raleigh's accordion has 4 real properties, one
with a genuine scheduled sale "September 9, 2026 @ 10:00 a.m.". Tax
foreclosure judgments and sales happen year-round; the gate was simply
wrong. Removed.

Most properties carry "Date of Sale: To Be Announced" (a judgment has
been entered but no auction date set yet) -- a freshly-filed-but-
undated status, same shape as sc_public_index_lis_pendens and the other
DATELESS_OK_SOURCES entries for "filed but no sale date yet is a real
early-warning signal, not a data gap." This source needs that same
whitelist entry (see main.py) or every TBA row gets dropped.

Free, public, no login.
Slug: counties_nc.wake_tax_foreclosure
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.wake.gov/departments-government/tax-administration/real-estate/foreclosures"

_ACCORDION_ITEM_RE = re.compile(
    r'<div class="accordion-item">\s*<h3[^>]*>\s*(?P<muni>.*?)\s*<i[^>]*>.*?</h3>'
    r'\s*<div class="body">(?P<body>.*?)</div>\s*</div>\s*</div>',
    re.I | re.S,
)
_PROPERTY_RE = re.compile(
    r'<p>\s*Tax ID#:\s*(?:&nbsp;)?<a[^>]*>(?P<tax_id>\d+)</a>\s*(?:&nbsp;)?'
    r'Amount due:\s*\$(?P<amount>[\d,]+\.\d+)\*?\s*<br\s*/?>\s*'
    r'Property Address:\s*(?P<address>.*?)\s*<br\s*/?>\s*'
    r'Date of First Action:\s*(?P<first_action>.*?)\s*<br\s*/?>\s*'
    r'Date Judgment Filed with Courts:\s*(?P<judgment_date>.*?)\s*<br\s*/?>\s*'
    r'Date of Sale:\s*(?P<sale_date>.*?)\s*</p>',
    re.I | re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = _TAG_RE.sub("", text or "")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def _parse_sale_date(text: str) -> datetime | None:
    text = _clean(text)
    if not text or "announce" in text.lower() or "tbd" in text.lower():
        return None
    m = re.search(r"([A-Za-z]+ \d{1,2},? \d{4})", text)
    if not m:
        return None
    for fmt in ("%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(m.group(1).replace(",", ""), fmt.replace(",", ""))
        except ValueError:
            continue
    return None


class WakeTaxForeclosure(BaseScraper):
    slug = "counties_nc.wake_tax_foreclosure"
    name = "Wake County NC Tax Foreclosures"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("wake_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        now = datetime.utcnow()
        for item in _ACCORDION_ITEM_RE.finditer(html):
            municipality = _clean(item.group("muni"))
            body = item.group("body")
            for prop in _PROPERTY_RE.finditer(body):
                tax_id = prop.group("tax_id")
                try:
                    amount = float(prop.group("amount").replace(",", ""))
                except ValueError:
                    amount = None
                address = _clean(prop.group("address"))
                sale_date = _parse_sale_date(prop.group("sale_date"))
                out.append(Listing(
                    source=self.slug,
                    source_url=f"https://services.wake.gov/realestate/Account.asp?id={tax_id}",
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Wake",
                    parcel_id=tax_id,
                    street_address=address or None,
                    judgment_amount=amount,
                    sale_date=sale_date,
                    description=(f"Wake County tax foreclosure ({municipality}): "
                                 f"${amount:,.2f} judgment" if amount else
                                 f"Wake County tax foreclosure ({municipality})"),
                    first_seen=now,
                    last_seen=now,
                    raw={"wake_tax_foreclosure": {
                        "municipality": municipality,
                        "tax_id": tax_id,
                        "amount_due": amount,
                        "date_of_first_action": _clean(prop.group("first_action")),
                        "date_judgment_filed": _clean(prop.group("judgment_date")),
                        "sale_date_raw": _clean(prop.group("sale_date")),
                    }},
                ))

        log.info("wake_tax.done", count=len(out))
        return out
