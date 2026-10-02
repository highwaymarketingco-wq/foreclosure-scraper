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

FIXED 2026-10-01 (batch-5 extraction-completeness audit): the accordion row
links each Tax ID# to its own Account.asp detail page -- already used as
source_url, but never actually fetched. That detail page (confirmed live)
carries the owner name(s) (often multiple heirs -- a strong motivated-seller
signal the accordion never shows at all), the owner's mailing address
(separate from the property address when absentee), heated square footage,
acreage, zoning, land class, and the county's assessed land+building value.
This is exactly the project's #1 documented ceiling (contactability /
owner-mailing-address) plus the CAMA-specs gap (HERMES Section 9), sitting
one hop away on a page this scraper already links to but never reads. Fixed
by best-effort fetching each Account.asp page and promoting these fields
(same raw['owner_mailing'] shape enrichment_owner_mailing.py itself writes,
so a listing this scraper already resolved is correctly skipped by that
enricher's has_mailing() gate instead of being re-resolved over GIS).

Free, public, no login.
Slug: counties_nc.wake_tax_foreclosure
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import asyncio
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


# --- Account.asp detail-page extraction -------------------------------------
# Classic-ASP, table-based markup (no semantic classes). Every single-value
# field shares one shape: "<label></FONT></TD> ... <DIV ALIGN=right>(optional
# empty FONT)<B><FONT ...>VALUE</FONT></B>(/DIV)</TD>". `.*?` (not `[^<]*`) on
# the value group because at least one real field (Land Class, "R-<10-HS")
# contains a literal unescaped "<" in the source HTML -- a `[^<]*` capture
# would silently truncate at it.
def _account_field(html: str, label: str) -> str | None:
    m = re.search(
        re.escape(label) + r"</FONT></TD>\s*<TD[^>]*>(?:<DIV[^>]*>)?"
        r"(?:<FONT[^>]*></FONT>)?<B><FONT[^>]*>(.*?)</FONT></B>(?:</DIV>)?</TD>",
        html, re.I | re.S,
    )
    if not m:
        return None
    val = re.sub(r"&nbsp;", " ", m.group(1))
    val = re.sub(r"\s+", " ", val).strip()
    return val or None


def _account_money(html: str, label: str) -> float | None:
    v = _account_field(html, label)
    if not v:
        return None
    try:
        return float(v.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _account_block_lines(html: str, start_label: str, end_label: str) -> list[str]:
    """Owner / mailing-address / property-location-address are each a run of
    sibling `<TR>` rows (one name or address line per row) between two known
    section labels, not a single-value field. Return the cleaned, non-empty
    `<B><FONT>` line values in that span, in document order."""
    start = html.find(start_label)
    if start == -1:
        return []
    end = html.find(end_label, start)
    chunk = html[start:end] if end != -1 else html[start:start + 2000]
    lines = re.findall(r"<B>\s*<FONT[^>]*>(.*?)</FONT>\s*</B>", chunk, re.I | re.S)
    out = []
    for raw_line in lines:
        v = re.sub(r"&nbsp;", " ", raw_line)
        v = re.sub(r"\s+", " ", v).strip()
        if v:
            out.append(v)
    return out


#: Account.asp fetches are cheap (one tiny classic-ASP page per property) and
#: this source typically has only a handful of active foreclosures at once,
#: but still bounded so a future bulk relist can't blow up the run.
_MAX_DETAIL_FETCH = 60


async def _enrich_from_account_page(li: Listing) -> None:
    """Best-effort fetch this property's own Account.asp detail page and
    promote owner / mailing / CAMA-spec fields the accordion list never
    carries at all. Never raises -- a failure just leaves the row as the
    accordion alone produced it."""
    try:
        html = await get_text(li.source_url, impersonate=True, timeout=30.0)
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        log.info("wake_tax.account_fetch_failed", url=li.source_url, error=str(exc)[:160])
        return
    if not html or "Property Owner" not in html:
        return

    owners = _account_block_lines(html, "Property Owner", "Owner's Mailing Address")
    # Drop the page's own boilerplate aside, not a real owner line.
    owners = [o for o in owners if "deeds link" not in o.lower()]
    mailing_lines = _account_block_lines(html, "Owner's Mailing Address", "Property Location Address")
    situs_lines = _account_block_lines(html, "Property Location Address", "Administrative Data")

    owner = "; ".join(owners) or None
    mailing = ", ".join(mailing_lines) or None
    situs = ", ".join(situs_lines) or None

    acreage_s = _account_field(html, "Acreage")
    zoning = _account_field(html, "Zoning")
    land_class = _account_field(html, "Land Class")
    heated_area_s = _account_field(html, "Heated Area")
    deed_date = _account_field(html, "Deed Date")
    book_page = _account_field(html, "Book &amp; Page") or _account_field(html, "Book & Page")
    land_value = _account_money(html, "Land Value Assessed")
    bldg_value = _account_money(html, "Bldg. Value Assessed")
    total_value = _account_money(html, "Total Value Assessed*") or _account_money(html, "Total Value Assessed")

    if owner and not li.owner_name:
        li.owner_name = owner
    if zoning and not li.zoning:
        li.zoning = zoning
    if acreage_s:
        try:
            if not li.acreage:
                li.acreage = float(acreage_s)
        except ValueError:
            pass
    if heated_area_s:
        try:
            sqft = float(heated_area_s.replace(",", ""))
            if sqft and not li.living_sqft:
                li.living_sqft = sqft
        except ValueError:
            pass
    if total_value:
        if not li.assessed_value:
            li.assessed_value = total_value
        if not li.market_value:
            li.market_value = total_value

    # Mailing-address block in the exact shape enrichment_owner_mailing.py's
    # own has_mailing()/is_target() gate checks for, so a property this
    # scraper already resolved from the primary source is correctly skipped
    # by that enricher instead of being re-resolved (and possibly missed)
    # over county GIS.
    if owner or mailing:
        mail_state = None
        if mailing:
            sm = re.search(r"\b([A-Z]{2})\s+\d{5}", mailing)
            mail_state = sm.group(1) if sm else None
        absentee = bool(mailing and situs and mailing.replace(" ", "").upper()
                        != situs.replace(" ", "").upper())
        li.raw["owner_mailing"] = {
            "owner": owner,
            "mailing": mailing,
            "situs": situs,
            "parcel_id": li.parcel_id,
            "mail_state": mail_state,
            "absentee": absentee,
            "out_of_state": bool(mail_state and li.state and mail_state != li.state),
            "source": "wake_account_detail",
        }

    li.raw.setdefault("wake_tax_foreclosure", {}).update({
        "owners": owners,
        "mailing_address": mailing,
        "property_location_address": situs,
        "acreage": acreage_s,
        "zoning": zoning,
        "land_class": land_class,
        "heated_area_sqft": heated_area_s,
        "deed_date": deed_date,
        "book_page": book_page,
        "land_value_assessed": land_value,
        "bldg_value_assessed": bldg_value,
        "total_value_assessed": total_value,
    })


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

        if out:
            await asyncio.gather(
                *(_enrich_from_account_page(li) for li in out[:_MAX_DETAIL_FETCH]),
                return_exceptions=True,
            )

        log.info("wake_tax.done", count=len(out),
                 with_owner=sum(1 for li in out if li.owner_name))
        return out
