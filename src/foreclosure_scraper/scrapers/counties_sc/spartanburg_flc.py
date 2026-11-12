"""Spartanburg County SC Forfeited Land Commission — Tax Sale Properties available
for assignment (county DocumentCenter PDF).

The FLC holds parcels struck to the county at past delinquent-tax sales; this list
is the standing assignable-surplus inventory (item #, best-known address + owner,
TMS map number, total tax due = the amount to assign it). A distressed/below-market
acquisition lane the generic ``sc_flc`` page-scrape does not parse.

Verified live 2026-06-27: https://www.spartanburgcounty.gov/DocumentCenter/View/104130
(application/pdf, ~133KB) parses to rows like
  "04995  1575 FARLEY AVE. EXT.  KALU, ORJI UZOR  6-18-07-092.00  $130,122.55".
DATELESS standing inventory (no sale-date window). Free, plain HTTP, no login/JS.

NOTE: DocumentCenter View IDs rotate when the county posts a new list; if this 404s
or yields 0 rows, refresh the View ID from spartanburgcounty.gov/216/Tax-Collector.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PDF_URL = "https://www.spartanburgcounty.gov/DocumentCenter/View/104130"

# item#  |  address + owner blob  |  TMS (d-dd-dd-ddd.dd)  |  $ total tax due
_ROW = re.compile(
    r"^(\d{4,6})\s+(.+?)\s+(\d-\d{2}-\d{2}-\d{3}\.\d{2})\s+\$?\s*([\d,]+\.\d{2})\s*$"
)
# owner name = trailing "SURNAME, FIRST ..." (addresses rarely contain a comma)
_OWNER = re.compile(r"([A-Z][A-Za-z'.\-]+,\s+.+)$")

# Street-suffix anchor: when the owner is a multi-word company name ("MARCLAR
# INVESTMENT, LLC", "WK PEBBLES, LLC"), _OWNER's single-word-before-the-comma
# match only grabs the LAST company word ("INVESTMENT", "PEBBLES") and leaves
# the first word(s) ("MARCLAR", "WK") misattributed to the address — found
# live 2026-10-01. Anchoring on the LAST street-suffix token instead (the
# address always ends in one; the owner text never contains one) correctly
# keeps the whole company name together. Tried first; falls back to _OWNER
# for the (more common) plain "LASTNAME, FIRST" person-owner rows it already
# handles correctly.
_ADDR_SUFFIX_ANCHOR = re.compile(
    r"\b(?:ST|STREET|RD|ROAD|DR|DRIVE|LN|LANE|CT|COURT|BLVD|BOULEVARD|HWY|"
    r"HIGHWAY|AVE|AVENUE|CIR|CIRCLE|WAY|PL|PLACE|TRL|TRAIL|PKWY|PARKWAY|TER|"
    r"TERRACE|EXT|EXTENSION|LOOP|BND|BEND|XING|CROSSING|PATH|ROW)\.?(?=\s)"
)


def _money(s: str) -> float | None:
    try:
        f = float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def parse_flc_pdf(pdf_bytes: bytes) -> list[Listing]:
    import pdfplumber  # local import keeps module import cheap
    out: list[Listing] = []
    seen: set[str] = set()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                m = _ROW.match(line.strip())
                if not m:
                    continue
                item, blob, tms, amt = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
                if tms in seen:
                    continue
                seen.add(tms)
                owner = address = None
                # Try the street-suffix anchor first (keeps a multi-word
                # company name like "MARCLAR INVESTMENT, LLC" intact; see the
                # _ADDR_SUFFIX_ANCHOR comment). Only trust it when a comma
                # follows somewhere after the suffix (confirms the remainder
                # really is "<owner>, <rest>" and not a coincidental match).
                anchor_end = None
                for sm in _ADDR_SUFFIX_ANCHOR.finditer(blob):
                    if "," in blob[sm.end():]:
                        anchor_end = sm.end()
                om = _OWNER.search(blob)
                if anchor_end is not None:
                    address = blob[:anchor_end].strip() or None
                    owner = blob[anchor_end:].strip().lstrip(".").strip() or None
                    situs = address
                elif om:
                    owner = om.group(1).strip()
                    address = blob[: om.start()].strip() or None
                    # A clean owner-comma split means `address` IS the situs
                    # text, house-number-led or not: Spartanburg's FLC list
                    # carries plenty of real situs with no house number at all
                    # (e.g. "S. GRIFFIN MILL CT.", "W.O. EZELL BLVD" — both
                    # confirmed live 2026-10-01). The old code required a
                    # leading digit here and silently nulled both of these out.
                    situs = address
                else:
                    # No clean comma split: `blob` is the WHOLE owner+address
                    # text with no reliable boundary, so only trust it as a
                    # situs when it happens to be house-number-led (the one
                    # shape we can tell apart from a bare owner name with no
                    # comma at all).
                    address = blob
                    situs = address if address and re.match(r"^\d", address) else None
                out.append(Listing(
                    source="counties_sc.spartanburg_flc",
                    source_url=PDF_URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Spartanburg",
                    parcel_id=tms,
                    street_address=situs,
                    opening_bid=_money(amt),
                    owner_name=owner,
                    defendant=owner,
                    foreclosure_process="tax",
                    description=f"Spartanburg FLC assignable surplus (item {item}) — {blob}",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"spartanburg_flc": {
                        "item": item, "tms": tms, "owner": owner,
                        "total_tax_due": _money(amt),
                    }},
                ))
    return out


class SpartanburgFLC(BaseScraper):
    slug = "counties_sc.spartanburg_flc"
    name = "Spartanburg SC Forfeited Land Commission (tax-sale surplus PDF)"
    category = "county_tax"
    expected_min_count = 0   # list size varies; an empty/replaced PDF is data reality
    timeout_s = 90.0

    async def fetch(self) -> Iterable[Listing]:
        try:
            pdf = await get_bytes(PDF_URL, timeout=60.0)
        except Exception:
            log.warning("spartanburg_flc.fetch_failed", exc_info=True)
            return []
        if not pdf or pdf[:4] != b"%PDF":
            log.warning("spartanburg_flc.not_pdf", head=pdf[:8] if pdf else None)
            return []
        return parse_flc_pdf(pdf)
