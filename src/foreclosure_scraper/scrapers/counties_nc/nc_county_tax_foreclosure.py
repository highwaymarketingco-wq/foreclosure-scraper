"""NC county in-rem tax-foreclosure sale pages (Gaston / McDowell / Rutherford).

Discovered 2026-06-16. NC counties run tax foreclosures as a SEPARATE track
from mortgage foreclosures (which we get via nc_ecourts). Each county posts
its current tax-foreclosure sale + active upset-bid properties on its own
site. These are net-new, county-specific, and carry the court file number,
parcel, current/upset bid, and (sometimes) the street address — distressed
inventory that does NOT surface in the eCourts mortgage pipeline.

Pages are JS-rendered, so we drive them with the free stealth browser and
extract via text regex (low per-county volume makes text extraction robust
across the varied county CMS layouts). In-scope counties only.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# county -> list of tax-foreclosure pages. Gaston's /669 "active" page usually
# has ~1 property; the /671 "Previous Sales" page carries the volume (~70) with
# current bid + upset-bid deadline + sale status. Verified static HTML 2026-06-18.
COUNTY_PAGES: dict[str, list[str]] = {
    "Gaston": [
        "https://www.gastongov.com/669/Tax-Foreclosure-Sales",
        "https://www.gastongov.com/671/Previous-Tax-Foreclosure-Sales",
    ],
    "McDowell": ["https://mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales"],
    "Rutherford": ["https://www.rutherfordcountync.gov/departments/revenue_department_tax_administrator/foreclosure_sale_dates.php"],
}

# Sale-status phrases (priority order). "sold"/"redeemed" = the sale is over →
# not an active opportunity (flag sold_confirmed so the dashboard hides it);
# "upset_bid" = still biddable.
_STATUS_PATTERNS = [
    (r"property\s+sold|sale\s+closed", "sold"),
    (r"redeem", "redeemed"),
    (r"surplus", "surplus"),
    (r"upset\s+bid", "upset_bid"),
]
_UPSET_DEADLINE_RE = re.compile(
    r"last day to upset[^.\n]*?((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4})", re.I)

# NC tax-foreclosure court file numbers: "25 M 388", "26-CVD-178", "24 CVD 67"
_FILE_RE = re.compile(r"\b(\d{2}\s?[- ]?(?:M|CV[D]?)\s?[- ]?\d{2,5})\b", re.I)
_PARCEL_RE = re.compile(r"\b(\d{4,6}[- ]?\d{2}[- ]?\d{2,4}(?:[- ]?\d{2,4})?)\b")
_BID_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
_ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'-]+\b(?:Street|St|Road|Rd|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Court|Ct|Circle|Cir|Way|Place|Pl|Trail|Trl|Boulevard|Blvd|Highway|Hwy)\b\.?)",
    re.I,
)
_DATE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}/\d{1,2}/\d{2,4})", re.I,
)


def parse_text(text: str, county: str, url: str) -> list[Listing]:
    """Split rendered page text into per-property blocks (anchored on the
    court file number) and extract fields. Tax-foreclosure pages list one
    file# per property."""
    out: list[Listing] = []
    # Split into blocks at each file-number occurrence so fields don't bleed
    # across properties.
    matches = list(_FILE_RE.finditer(text))
    if not matches:
        return out
    seen: set[str] = set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(text), start + 600)
        block = text[start:end]
        file_no = re.sub(r"\s+", " ", m.group(1)).strip().upper()
        if file_no in seen:
            continue
        seen.add(file_no)

        addr_m = _ADDR_RE.search(block)
        parcel_m = _PARCEL_RE.search(block)
        # bid: take the largest $ in the block (current bid > deposit)
        bids = [float(b.replace(",", "")) for b in _BID_RE.findall(block)]
        bid = max(bids) if bids else None
        date_m = _DATE_RE.search(block)
        sale_date = None
        if date_m:
            try:
                from dateutil import parser as dp
                sale_date = dp.parse(date_m.group(1))
            except (ValueError, TypeError, OverflowError):
                pass

        # Sale status + upset-bid deadline (esp. the /671 "Previous Sales" page).
        low = block.lower()
        status = next((s for pat, s in _STATUS_PATTERNS if re.search(pat, low)), None)
        upset_deadline = None
        um = _UPSET_DEADLINE_RE.search(block)
        if um:
            try:
                from dateutil import parser as dp
                upset_deadline = dp.parse(um.group(1)).date().isoformat()
            except (ValueError, TypeError, OverflowError):
                pass

        raw: dict = {"nc_county_tax_foreclosure": {"county": county}}
        if status:
            raw["tax_sale_status"] = status
            # A completed/redeemed sale is no longer an opportunity — hide it
            # from the active board (same flag the court sold-filter uses).
            if status in ("sold", "redeemed"):
                raw["sold_confirmed"] = True
        if upset_deadline:
            raw["upset_bid_deadline"] = upset_deadline

        out.append(
            Listing(
                source="counties_nc.nc_county_tax_foreclosure",
                source_url=url,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county=county,
                street_address=(addr_m.group(1).strip() if addr_m else None),
                parcel_id=(parcel_m.group(1).strip() if parcel_m else None),
                case_number=file_no,
                opening_bid=bid,
                sale_date=sale_date,
                description=re.sub(r"\s+", " ", block)[:400],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw=raw,
            )
        )
    return out


async def _render(url: str) -> str:
    from ...render import fetch_rendered
    try:
        return await fetch_rendered(url)
    except Exception:
        return ""


async def _fetch_page(url: str) -> str:
    """Static HTTP first (fast + reliable for CivicPlus pages like Gaston),
    falling back to the stealth browser only if the static fetch yields no
    parseable content (no court file number found)."""
    from ...http_client import get_text
    try:
        html = await get_text(url, headers={"User-Agent": "Mozilla/5.0"})
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        if _FILE_RE.search(text):
            return text
    except Exception:
        pass
    return await _render(url)


class NCCountyTaxForeclosure(BaseScraper):
    slug = "counties_nc.nc_county_tax_foreclosure"
    name = "NC County Tax Foreclosure Sales"
    category = "county_tax"
    expected_min_count = 0  # episodic — counties often have 0 active sales
    requires_render = True
    timeout_s = 300.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[tuple] = set()
        for county, urls in COUNTY_PAGES.items():
            for url in urls:
                text = await _fetch_page(url)
                if not text:
                    continue
                for li in parse_text(text, county, url):
                    key = (li.county, li.case_number)
                    if li.case_number and key in seen:
                        continue
                    seen.add(key)
                    out.append(li)
        return out
