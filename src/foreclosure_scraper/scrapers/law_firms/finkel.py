"""Finkel Law Firm (SC) — monthly PDF parser.

This is a judicial-sale RESULTS report, not just an upcoming-sale calendar:
each record carries BOTH a "Bid Amount" (an advance minimum, often blank)
and a separate "Sale Amount" + "Sold To" (the actual hammer price and the
winner — either "Plaintiff <name>", meaning the lender took the property
back with no outside bid, or "Third Party <name>", a real investor
purchase).

FIX 2026-10-04: the original parser used pypdf's linear `extract_text()`,
whose reading order for this form-style PDF does not follow the visual
layout — live-verified it place the "Sale Amount" value where "Bid Amount"
visually sits, so the code grabbed the first bare number after the docket
line and called it `opening_bid`. On every live record checked this was
actually the SALE amount, not the bid: e.g. the Union County row's real
Bid Amount is $71,400.00 and its real (and different) Sale Amount is
$93,000 sold to a third party, but the old code reported `opening_bid =
93000` and surfaced no sold-to / sale-amount data at all. Switched to
pdfplumber, whose position-aware `extract_text()` keeps this report's
labels and values in the PDF's true reading order (confirmed by grouping
words by y-coordinate — the result matches the label order exactly), and
parse with a label-anchored regex instead of a positional line scan. Now
`opening_bid` maps to the real Bid Amount field, and the real Sale Amount /
Sold To land in `raw["actual_sold_price"]` / `raw["sold_to"]` (the first
project-wide convention for sale price, the second new this fix, both
registered in `web_artifact.RAW_KEEP`).

Live-verified 2026-10-04: both finkellaw.com and finkellawcharleston.com
serve the IDENTICAL file (same MD5 with a cache-busting query string), and
its own newest record dates are 05/06/2025 — the live finkellaw.com site
redesigned since and no longer publishes a foreclosure-sales listing page
at all (practice-areas page only mentions foreclosure under "Business
Litigation" prose, no roster). This file is genuinely stale/orphaned, not
a scraper bug on our side; kept live (not disabled) since the asset still
returns real, parseable historical sale results and the engine's own rule
is "re-verify live, don't assume dead forever" — if the firm resumes
publishing, this fix is already in place.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import get_bytes
from ...models import Listing, ListingType, PropertyKind

PDF_URLS = (
    "https://www.finkellaw.com/images/Webs.pdf",
    "https://www.finkellawcharleston.com/images/Webs.pdf",
)

# Label-anchored, position-correct record parser. Each record is exactly
# this sequence of labels (confirmed live by grouping pdfplumber words by
# y-coordinate); `.*?` + DOTALL lets a field's value wrap across the PDF's
# own line breaks (Sale Location and Defendants routinely do).
#
# At least one real court location's canned Sale Location text (the
# Lexington County Judicial Center entry, live-verified 2026-10-04) is long
# enough to physically overlap a separate COVID-era courthouse disclaimer
# text box in the ORIGINAL PDF, so the two run together character-for-
# character in extraction order and spill INTO the Docket Number / Plaintiff
# rows for that one record -- a genuine source-side rendering defect, not an
# artifact of pypdf vs pdfplumber (both show the same interleaving). Docket
# Number and Plaintiff are captured broadly here, then cleaned in `_parse()`
# with a strict docket-pattern search and a first-line-only split so that
# contamination trailing them never reaches `case_number`/`plaintiff`
# (both load-bearing for dedupe and downstream matching); Sale Time/Location
# are left best-effort free text since they are not.
_RECORD_RE = re.compile(
    r"County:\s*(?P<county>.*?)\s*Sale Date:\s*(?P<sale_date>.*?)\s*"
    r"Sale Time:\s*(?P<sale_time>.*?)\s*Sale Location:\s*(?P<sale_location>.*?)\s*"
    r"Docket Number:\s*(?P<docket_raw>.*?)\s*Plaintiff:\s*(?P<plaintiff_raw>.*?)\s*"
    r"Defendants:\s*(?P<defendants>.*?)\s*Property Address:\s*(?P<address>.*?)\s*"
    r"Bid Amount:\s*(?P<bid>.*?)\s*Sale Amount:\s*(?P<sale_amount>.*?)\s*"
    r"Sold To:\s*(?P<sold_to>.*?)(?=County:|\Z)",
    re.S,
)
_DOCKET_RE = re.compile(r"\b(\d{4}CP\d{6,9})\b")
_ADDR_RE = re.compile(r"^(.+?),\s*([A-Za-z .'-]+),\s*SC\s+(\d{5})")
_MONEY_RE = re.compile(r"[\d,]+(?:\.\d{2})?")


def _extract_pdf_text(data: bytes) -> str:
    """Position-aware extraction. pypdf's linear text jumbles this report's
    field order (see module docstring); pdfplumber's layout-aware
    `extract_text()` keeps labels and values in true visual reading order."""
    try:
        import pdfplumber
    except ImportError:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text(layout=False) or "") for p in pdf.pages)
    except Exception:
        return ""


def _clean(raw: str | None) -> str | None:
    if not raw:
        return None
    text = re.sub(r"\s+", " ", raw).strip()
    return text or None


def _money(raw: str | None) -> float | None:
    """Dollar amount, or None. Blank field (no digits at all) is unknown."""
    text = _clean(raw)
    if not text:
        return None
    m = _MONEY_RE.search(text)
    if not m:
        return None
    try:
        val = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return val or None


def _parse_sold_to(raw: str | None) -> dict | None:
    """"Plaintiff <name>" (lender took it back, no outside bid) or
    "Third Party <name>" (a real investor purchase) -- a materially
    different distress signal than a bare dollar amount alone."""
    text = _clean(raw)
    if not text:
        return None
    lower = text.lower()
    if lower.startswith("plaintiff"):
        return {"type": "plaintiff", "name": text[len("plaintiff"):].strip() or None}
    if lower.startswith("third party"):
        return {"type": "third_party", "name": text[len("third party"):].strip() or None}
    return {"type": "unknown", "name": text}


def _parse(text: str, source_url: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    for m in _RECORD_RE.finditer(text):
        # Strict pattern search, not a straight clean of the captured span --
        # see the module/regex docstring on why that span can carry trailing
        # disclaimer-text contamination for at least one real court location.
        docket_m = _DOCKET_RE.search(m.group("docket_raw") or "")
        docket = docket_m.group(1) if docket_m else None
        address_raw = _clean(m.group("address"))
        if not docket or not address_raw:
            continue

        addr_m = _ADDR_RE.match(address_raw)
        if not addr_m:
            continue
        street, city, zip_code = addr_m.group(1).strip(), addr_m.group(2).strip(), addr_m.group(3)

        county = _clean(m.group("county"))
        sale_date_raw = _clean(m.group("sale_date"))
        sale_date = None
        if sale_date_raw:
            try:
                sale_date = dateparser.parse(sale_date_raw, fuzzy=True)
            except (ValueError, TypeError, OverflowError):
                sale_date = None

        sale_time = _clean(m.group("sale_time"))
        sale_location = _clean(m.group("sale_location"))
        # First line only, same contamination guard as docket: a plaintiff
        # name never legitimately wraps in this report, so anything past
        # the first line is trailing disclaimer spillover, not more name.
        plaintiff = _clean((m.group("plaintiff_raw") or "").split("\n")[0])
        defendants_raw = _clean(m.group("defendants"))
        defendant = re.sub(r"^v\.\s*", "", defendants_raw)[:300] if defendants_raw else None

        opening_bid = _money(m.group("bid"))          # advance minimum, often blank
        sale_amount = _money(m.group("sale_amount"))  # actual hammer price
        sold_to = _parse_sold_to(m.group("sold_to"))  # plaintiff / third-party winner

        listing = Listing(
            source=slug,
            source_url=source_url,
            listing_type=ListingType.FORECLOSURE_SALE,
            property_kind=PropertyKind.UNKNOWN,
            street_address=street,
            city=city or None,
            state="SC",
            zip_code=zip_code,
            county=county,
            sale_date=sale_date,
            sale_time=sale_time,
            sale_location=sale_location,
            case_number=docket,
            opening_bid=opening_bid,
            plaintiff=plaintiff,
            defendant=defendant,
            trustee="Finkel Law Firm",
            description=(sale_location or "")[:500] or None,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        if sale_amount is not None:
            listing.raw["actual_sold_price"] = sale_amount
        if sold_to is not None:
            listing.raw["sold_to"] = sold_to
        out.append(listing)
    return out


class Finkel(BaseScraper):
    slug = "law_firms.finkel"
    name = "Finkel Law Firm"
    category = "law_firm"
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url in PDF_URLS:
            try:
                data = await get_bytes(url, timeout=60.0, impersonate=True)
            except Exception:
                continue
            text = _extract_pdf_text(data)
            if not text:
                continue
            out.extend(_parse(text, url, self.slug))
        return out
