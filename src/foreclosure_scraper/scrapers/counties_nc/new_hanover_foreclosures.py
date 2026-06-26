"""New Hanover County (NC) tax-foreclosure sale list.

Source (verified live 2026-06-26): https://www.nhcgov.com/345/Foreclosures —
a plain HTTP GET, no login. New Hanover County's in-rem property-tax
foreclosures are administered by the Kania Law Firm, P.A. (Asheville) and the
county republishes the current sale list on its own CivicPlus page.

Page shape (verified live 2026-06-26): each property is ONE ``<ul>`` whose
``<li>`` children carry the structured fields, e.g.::

    <ul>
      <li>Parcel Numbers: R08818-001-002-000, R08818-001-004-000, & R08818-001-005-000</li>
      <li>Civil Number: 23CVS000524-640</li>
      <li>Sale Date: May 22, 2026</li>
      <li>Approximate Opening Bid: ... contact Kania Law Firm, P.A. ...</li>
      <li>View the 600 Rocky Mount Avenue property card - R08818-001-002-000 .</li>
      <li>View the 604 Tarboro Avenue property card - R08818-001-004-000 .</li>
      <li>View the 600 Tarboro Avenue property card - R08818-001-005-000 .</li>
    </ul>

A property can carry one OR several parcels + addresses (a single tax case
foreclosing several adjoining parcels). We anchor a listing on the ``<ul>``
that contains a "Civil Number:" line, then pull the first parcel as
``parcel_id`` and the first address as ``street_address`` (the canonical
single-row identity), while stuffing the FULL parcel + address lists into
``raw`` so nothing is lost.

DEDUPE INTENT: these are Kania-administered properties that also surface in
``law_firms.kania``. We make sure ``parcel_id`` (R-format) and ``case_number``
(the civil case number) are populated so the pipeline's parcel-first
``Listing.dedupe_key`` (``parcel:{state}:{county}:{parcel}``) collapses the
same property across the two sources. See the module REPORT for the caveat on
whether the Kania scraper actually emits a matching parcel/county for these
rows.

Free + compliant: a single plain HTTP GET of a public county page (browser UA),
no login / CAPTCHA / WAF defeat.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_nc.new_hanover_foreclosures"
PAGE_URL = "https://www.nhcgov.com/345/Foreclosures"
COUNTY = "New Hanover"
STATE = "NC"

# R-format New Hanover parcel: R08818-001-002-000 (a leading R then 5 digits and
# dash-separated groups). Kept loose on group count to survive minor formatting.
_PARCEL_RE = re.compile(r"\bR\d{4,6}(?:-\d{2,3})+\b", re.I)
# Civil / case number, e.g. "23CVS000524-640" or "25CV004024-640".
_CASE_RE = re.compile(r"\b(\d{2,4}\s?CV[A-Z]?\s?\d+(?:-\d+)?)\b", re.I)
# A date like "May 22, 2026" or "5/22/2026".
_DATE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4})",
    re.I,
)
# Street address out of a "View the <ADDRESS> property card ..." line.
_VIEW_ADDR_RE = re.compile(
    r"View the\s+(.+?)\s+property card", re.I
)


def _parse_date(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    m = _DATE_RE.search(s)
    if not m:
        return None
    try:
        return dateparser.parse(m.group(1))
    except (ValueError, TypeError, OverflowError):
        return None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("​", " ")).strip()


def parse(html: str, page_url: str = PAGE_URL) -> list[Listing]:
    """Parse the New Hanover foreclosures page into one Listing per property.

    Each property is a ``<ul>`` containing a "Civil Number:" ``<li>``. We
    iterate those ``<ul>`` blocks, pull parcel(s) / case / sale-date / address
    (es), and emit one Listing keyed on the first parcel + the case number.
    """
    out: list[Listing] = []
    seen: set[str] = set()
    tree = HTMLParser(html)

    for ul in tree.css("ul"):
        block = _clean(ul.text(separator=" "))
        if "civil number" not in block.lower():
            continue

        # --- per-<li> field extraction -------------------------------------
        parcels: list[str] = []
        addresses: list[str] = []
        case_number: Optional[str] = None
        sale_date: Optional[datetime] = None
        sale_date_text: Optional[str] = None

        for li in ul.css("li"):
            line = _clean(li.text(separator=" "))
            if not line:
                continue
            low = line.lower()

            # Address lines: "View the <ADDRESS> property card[ - <PARCEL>] ."
            vm = _VIEW_ADDR_RE.search(line)
            if vm:
                addr = vm.group(1).strip().rstrip(".").strip()
                # Drop a trailing "- R08818-001-002-000" if it leaked into the
                # captured group (the regex stops at "property card", so this is
                # belt-and-suspenders).
                addr = re.sub(r"\s*-\s*R\d.*$", "", addr, flags=re.I).strip()
                if addr and addr not in addresses:
                    addresses.append(addr)
                continue

            # Parcel line(s): "Parcel Number(s): R..., R..., & R..."
            if "parcel number" in low:
                for pm in _PARCEL_RE.finditer(line):
                    p = pm.group(0).upper()
                    if p not in parcels:
                        parcels.append(p)
                continue

            # Civil/case line.
            if "civil number" in low and case_number is None:
                cm = _CASE_RE.search(line)
                if cm:
                    case_number = cm.group(1).upper().replace(" ", "")
                continue

            # Sale date line.
            if "sale date" in low and sale_date is None:
                sale_date_text = line
                sale_date = _parse_date(line)
                continue

        # Fallbacks: scan the whole block for anything a per-li pass missed
        # (defensive against future markup shuffles).
        if not parcels:
            for pm in _PARCEL_RE.finditer(block):
                p = pm.group(0).upper()
                if p not in parcels:
                    parcels.append(p)
        if case_number is None:
            cm = _CASE_RE.search(block)
            if cm:
                case_number = cm.group(1).upper().replace(" ", "")
        if sale_date is None:
            sale_date = _parse_date(block)

        # A genuine listing needs at least a parcel or a case number.
        if not (parcels or case_number):
            continue

        parcel_id = parcels[0] if parcels else None
        street_address = addresses[0] if addresses else None

        key = f"{(parcel_id or '').upper()}|{(case_number or '').upper()}"
        if key in seen:
            continue
        seen.add(key)

        addr_label = street_address or (parcel_id or case_number or "property")
        out.append(
            Listing(
                source=SLUG,
                source_url=page_url,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state=STATE,
                county=COUNTY,
                street_address=street_address,
                parcel_id=parcel_id,
                case_number=case_number,
                sale_date=sale_date,
                foreclosure_process="tax",
                auction_status="active",
                trustee="Kania Law Firm, P.A.",
                description=(
                    f"New Hanover County tax-foreclosure sale (Kania Law Firm) — {addr_label}"
                )[:400],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "new_hanover_foreclosures": {
                        "county": COUNTY,
                        "all_parcels": parcels,
                        "all_addresses": addresses,
                        "civil_number": case_number,
                        "sale_date_text": sale_date_text,
                        "administrator": "Kania Law Firm, P.A.",
                    }
                },
            )
        )

    return out


class NewHanoverForeclosures(BaseScraper):
    slug = SLUG
    name = "New Hanover County (NC) Tax Foreclosures (Kania)"
    category = "county_tax"
    # County tax-foreclosure sale lists are episodic — a quiet cycle can show 0
    # active sales.
    expected_min_count = 0
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        # CivicPlus (nhcgov.com) answers plain httpx but sometimes fingerprint-
        # gates; impersonate=True transparently escalates to the curl-cffi
        # Chrome tier if a plain GET is blocked. A browser-like UA only.
        html = await get_text(
            PAGE_URL,
            impersonate=True,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=self.timeout_s,
        )
        rows = parse(html, PAGE_URL)
        log.info("new_hanover_foreclosures.parsed", rows=len(rows))
        return rows


# Allow running this module directly for quick iteration:
#   uv run python -m foreclosure_scraper.scrapers.counties_nc.new_hanover_foreclosures
if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        scraper = NewHanoverForeclosures()
        results = await scraper.safe_run()
        print(f"parsed: {len(results)}  outcome={scraper.last_outcome}")
        for x in results:
            print(
                f"  addr={x.street_address!r} parcel={x.parcel_id} "
                f"case={x.case_number} sale_date={x.sale_date} "
                f"all_parcels={x.raw.get('new_hanover_foreclosures', {}).get('all_parcels')}"
            )

    asyncio.run(_main())
