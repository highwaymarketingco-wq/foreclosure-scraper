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
# Label-anchored parcel id: both live formats print "Parcel: <id>" /
# "Parcel(s): <id>" verbatim right next to the number, which _PARCEL_RE's
# generic dash-grouped pattern never matches for Gaston's plain numeric ids
# ("Parcel: 139329" -- 6 digits, no dashes -- every Gaston row's parcel_id was
# silently None before this). Tried first; _PARCEL_RE is the fallback for
# pages that print a dashed PIN without the word "Parcel" nearby.
_PARCEL_LABEL_RE = re.compile(r"\bParcel(?:\(s\))?:\s*(\d[\d\-]{2,14})", re.I)
_BID_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")
_ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'-]+\b(?:Street|St|Road|Rd|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Court|Ct|Circle|Cir|Way|Place|Pl|Trail|Trl|Boulevard|Blvd|Highway|Hwy|"
    r"Parkway|Pkwy|Loop|Terrace|Ter|Cove|Cv|Run|Trace|Trce)\b\.?)",
    re.I,
)
# The strongest "a new record starts here" anchors across the two live
# layouts: Gaston opens each record with "Owner: <name>"; Rutherford opens
# with "In-Rem Foreclosure" / "Parcel(s):". Used to trim the BACKWARD half of
# a block so it stops at the start of THIS record rather than reaching back
# into the PRECEDING record's own trailing fields (see the Rutherford
# comment below parse_text).
_RECORD_START_RE = re.compile(r"\bOwner:|\bIn-Rem Foreclosure\b|\bParcel\(s\):", re.I)
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
        # The block spans the FULL gap on both sides of this case match (back
        # to the previous case's end, forward to the next case's start), not
        # just forward from this match. Gaston's real page puts the owner /
        # parcel / address / bid / upset-deadline BEFORE "File Number: <case>"
        # (the case number is the LAST thing in its own record, and the next
        # record's fields start immediately after) -- live-confirmed
        # 2026-10-01 by reading the raw page text directly. The old
        # forward-only block (start = m.start()) grabbed the NEXT record's
        # owner/parcel/address instead and labeled it with THIS case number:
        # e.g. "File Number: 25 M 414" was paired with Heirs of Mary Suzanne
        # K. Ledford / parcel 119763 / 2956 Union Rd, which actually belongs
        # to the FOLLOWING case "25 M 415" -- every Gaston row was off by one.
        # Searching the wider two-sided block still returns the correct
        # (leftmost) match for county layouts that put fields AFTER the case
        # number instead (Rutherford opens each record with "In-Rem
        # Foreclosure Parcel(s): ..." BEFORE its own case mark, then prints
        # its address/bid AFTER it), because regex .search() takes the first
        # hit in text order and this record's own trailing fields sit before
        # the NEXT case's leading parcel text.
        start = matches[i - 1].end() if i > 0 else max(0, m.start() - 600)
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(text), m.end() + 600)
        # Trim the backward half to the LAST "new record starts here" anchor
        # in that span, if any. Without this, the backward span for a
        # case-LEADING page (Rutherford) runs all the way back to the
        # PREVIOUS case's end, which still contains the previous record's own
        # trailing address/bid (nothing marks where that record's data stops
        # and this one's leading "In-Rem Foreclosure Parcel(s):" begins) --
        # live-confirmed: case 23 M 265's block picked up case 23 M 258's own
        # "0 Pinnacle Parkway" / $22,531.21 instead of its real "145 Boiler
        # Rd" / $19,845.00. Trimming to the last anchor leaves only "In-Rem
        # Foreclosure Parcel(s): 1613770..." in the backward span (no address
        # there), so the address/bid search correctly falls through to this
        # record's own forward half instead. Gaston is unaffected: its anchor
        # is "Owner:", which already sits at the true start of its own
        # backward-owned data, so trimming to it changes nothing there.
        back_text = text[start:m.start()]
        anchors = list(_RECORD_START_RE.finditer(back_text))
        if anchors:
            start = start + anchors[-1].start()
        # The case number's OWN text is excluded from the search block: a
        # file number like "23 M 265" starts with "digit digit space
        # UPPERCASE-letter", which is exactly what _ADDR_RE looks for, so
        # leaving it in let the address match swallow the case number itself
        # plus everything up to the next real street suffix ("23 M 265   145
        # Boiler Rd" came back as one fabricated "address" on Rutherford
        # before this fix).
        block = text[start:m.start()] + " " + text[m.end():end]
        file_no = re.sub(r"\s+", " ", m.group(1)).strip().upper()
        if file_no in seen:
            continue
        seen.add(file_no)

        addr_m = _ADDR_RE.search(block)
        parcel_m = _PARCEL_LABEL_RE.search(block) or _PARCEL_RE.search(block)
        # bid: take the largest $ figure, but ONLY from the backward half
        # (this record's own trailing fields, Gaston-style) when it has any,
        # falling back to the forward half (this record's own leading fields,
        # Rutherford-style) otherwise. A flat max() over the whole two-sided
        # block would reach past this record into the NEXT one's own (often
        # larger) current-bid figure whenever the two records sit back to
        # back with no gap -- live-confirmed: case 24 M 867's own upset bid is
        # $52,500, but a block-wide max() picked up the following record's
        # $88,200 current bid instead. addr/parcel/date don't need this split
        # because .search() already returns the leftmost (backward-first)
        # match on its own.
        back_bids = [float(b.replace(",", "")) for b in _BID_RE.findall(text[start:m.start()])]
        fwd_bids = [float(b.replace(",", "")) for b in _BID_RE.findall(text[m.end():end])]
        bids = back_bids or fwd_bids
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
        upset_deadline_dt = None
        um = _UPSET_DEADLINE_RE.search(block)
        if um:
            try:
                from dateutil import parser as dp
                upset_deadline_dt = dp.parse(um.group(1))
                upset_deadline = upset_deadline_dt.date().isoformat()
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
                upset_bid_deadline=upset_deadline_dt,
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
