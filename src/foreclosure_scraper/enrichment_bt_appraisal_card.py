"""BT TaxPayer Portal appraisal cards — heated sqft + recorded sale price, 14 NC counties.

WHY THIS EXISTS
    The sqft->ARV gap is the oldest open item in this project: single-family heated sqft
    sits at 13% coverage, ARV is capped to MEDIUM confidence without it, and ~38% of rows
    were waiting on a paid Zillow-FACTS enricher. These counties publish the assessor's
    full appraisal card as a free PDF, keyed on the parcel number.

    Verified live 2026-09-11, McDowell parcel 0668-00-82-0841:
        HEATED AREA              2,100
        TOTAL APPRAISED VALUE  261,870
        Bedrooms/Bathrooms       4/2/0
        SALES DATA   deed 01342/0402, 2021, WD, $229,000

    The sale price matters separately: `project_rod_document_images` records that the
    ASSESSOR has the sale price while the ROD index does not, and this is the assessor's
    own card.

EVERY TENANT CODE WAS VERIFIED AGAINST THE COUNTY IT CLAIMS TO BE
    The portal is multi-tenant: /ITSPublic<CODE>/. A source sweep proposed 19 counties.
    Fetching each landing page and reading the county name off it found:

        14 correct   -- the page names the expected county
         5 dead      -- Craven(CR), Graham(GR2), Jones(JN2), Surry(SU), Gates(GA)
                        return 142-1,244 byte stubs with no county name
         1 WRONG     -- ITSPublicMA was proposed for MARTIN; the page says PERSON COUNTY

    Wiring that last one would have filed Person County appraisals against Martin County
    parcels and nothing would have failed. It is the same shape as the code-enforcement
    endpoint that turned out to be the City of Yucaipa, California. Only verified codes
    are in TENANTS below; adding one means fetching its landing page and reading the
    county name off it first.

Free, public, no login. One request per parcel, so it is bounded and opt-in.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
from typing import Iterable

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

BASE = "https://www.bttaxpayerportal.com"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

#: county -> tenant code. EVERY ONE verified 2026-09-11 by fetching
#: /ITSPublic<CODE>/ and reading the county name printed on the page.
TENANTS: dict[str, str] = {
    "Alleghany": "AL", "Anson": "AN", "Carteret": "CE", "Caswell": "CS",
    "Clay": "CL", "Duplin": "DL", "Martin": "MT", "McDowell": "MD",
    "Moore": "MO", "Person": "PR", "Scotland": "SC", "Swain": "SW",
    "Warren": "WN", "Yadkin": "YK",
}

#: Proposed by the sweep and REJECTED, kept so nobody re-adds them without checking.
REJECTED_TENANTS = {
    "Craven": "CR — 142B stub, no county name",
    "Graham": "GR2 — 1,244B stub, no county name",
    "Jones": "JN2 — 1,244B stub, no county name",
    "Surry": "SU — 142B stub, no county name",
    "Gates": "GA — 1,244B stub, no county name",
    "Martin(MA)": "MA — the page says PERSON COUNTY, not Martin",
}

MAX_CARDS = int(os.getenv("BT_CARD_MAX", "300"))
_CONCURRENCY = int(os.getenv("BT_CARD_CONCURRENCY", "3"))
_TAX_YEAR = os.getenv("BT_CARD_TAX_YEAR", "2027")

_HEATED_RE = re.compile(r"HEATED AREA\s+([\d,]+)", re.I)
_APPRAISED_RE = re.compile(r"TOTAL APPRAISED VALUE[^\d]{0,40}([\d,]+)", re.I)
_BEDBATH_RE = re.compile(r"Bedrooms/Bathrooms[^\d]{0,40}(\d+)/(\d+)/(\d+)", re.I)
_YEAR_RE = re.compile(r"\bAYB\s+(\d{4})", re.I)
#: SALES DATA, as pypdf actually extracts it: every field on ITS OWN LINE, in the order
#: BOOK PAGE MO YR TYPE Q/U V/I PRICE. A single-line row regex matches stray
#: combinations instead -- it first returned $20,000/2008 for a card whose real sale is
#: $229,000/2021.
_SALE_ROW_RE = re.compile(
    r"(\d{4,6})\s*\n\s*(\d{3,5})\s*\n\s*(\d{1,2})\s*\n\s*(\d{4})\s*\n\s*"
    r"([A-Z]{2})\s*\n\s*([A-Z])\s*\n\s*([VI])\s*\n\s*([\d,]+)")


def _num(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


#: Case-insensitive lookup. `"McDowell".title()` is `"Mcdowell"` -- Python lowercases
#: after the first letter -- so a .title() lookup silently missed McDowell, which is a
#: FOOTPRINT county and the one this was first tested against.
_TENANTS_CI = {k.lower(): v for k, v in TENANTS.items()}


def card_url(county: str, parcel_id: str, tax_year: str = _TAX_YEAR) -> str | None:
    """The card URL, or None when the county is not a verified tenant."""
    code = _TENANTS_CI.get((county or "").strip().lower())
    if not code:
        return None
    pid = re.sub(r"[^0-9A-Za-z]", "", parcel_id or "")
    if not pid:
        return None
    return f"{BASE}/ITSPublic{code}/AppraisalCard.aspx?id={pid}%2f{tax_year}"


def parse_card(pdf_bytes: bytes) -> dict:
    """Fields off one appraisal-card PDF. Returns {} when it is not a real card."""
    if not pdf_bytes or pdf_bytes[:4] != b"%PDF":
        return {}
    try:
        from pypdf import PdfReader
        text = "\n".join((p.extract_text() or "")
                         for p in PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:  # noqa: BLE001
        return {}
    return parse_card_text(text)


def parse_card_text(text: str) -> dict:
    t = re.sub(r"[ \t]+", " ", text or "")
    if "HEATED AREA" not in t.upper() and "APPRAISED VALUE" not in t.upper():
        return {}
    out: dict = {}
    m = _HEATED_RE.search(t)
    if m:
        out["heated_sqft"] = _num(m.group(1))
    m = _APPRAISED_RE.search(t)
    if m:
        out["appraised_value"] = _num(m.group(1))
    m = _BEDBATH_RE.search(t)
    if m:
        out["bedrooms"], out["bathrooms"], out["half_baths"] = (
            int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _YEAR_RE.search(t)
    if m:
        out["year_built"] = int(m.group(1))
    sales = []
    for bk, pg, mo, yr, typ, qu, vi, price in _SALE_ROW_RE.findall(text or ""):
        pr = _num(price)
        if not pr or pr < 100:          # $0 rows are family/estate transfers, not sales
            continue
        sales.append({"deed_book": bk, "deed_page": pg, "month": int(mo),
                      "year": int(yr), "instrument": typ,
                      "qu_code": qu.upper(), "improved": vi.upper() == "I",
                      "price": pr})
    if sales:
        sales.sort(key=lambda s: (s["year"], s["month"]), reverse=True)
        out["sales"] = sales
        # PICK THE MOST RECENT SALE OF AN IMPROVED PARCEL, not the most recent "Q".
        # Measured on McDowell 0668-00-82-0841: the 2021 sale of the house for $229,000
        # is flagged Q/U = "X", while the only "Q" row is a $20,000 transfer from 2008.
        # Preferring Q therefore picked a 13-year-old figure a tenth of the real value,
        # and that number would have gone straight into ARV. V/I is the reliable column:
        # I = improved (there is a house on it), V = vacant land.
        improved = [x for x in sales if x["improved"]]
        best = (improved or sales)[0]
        out["last_sale_price"] = best["price"]
        out["last_sale_year"] = best["year"]
        out["last_sale_improved"] = best["improved"]
        out["last_sale_qu_code"] = best["qu_code"]
    return {k: v for k, v in out.items() if v not in (None, "", [])}


async def enrich_bt_appraisal_card(listings: Iterable[Listing]) -> dict:
    """Fill heated sqft / appraised value / last sale on rows in the 14 tenant counties."""
    targets = [li for li in listings
               if li.parcel_id and card_url(li.county or "", li.parcel_id)
               and not li.living_sqft]
    stats = {"eligible": len(targets), "fetched": 0, "parsed": 0, "errors": 0,
             "filled_sqft": 0, "filled_sale": 0, "filled_value": 0, "not_a_card": 0}
    if not targets:
        return stats
    targets = targets[:MAX_CARDS]
    sem = asyncio.Semaphore(_CONCURRENCY)

    async with httpx.AsyncClient(timeout=45.0, headers={"User-Agent": _UA},
                                 follow_redirects=True) as c:
        async def one(li: Listing) -> None:
            url = card_url(li.county or "", li.parcel_id)
            async with sem:
                try:
                    r = await c.get(url)
                    r.raise_for_status()
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
                    return
                await asyncio.sleep(0.4)
            stats["fetched"] += 1
            got = parse_card(r.content)
            if not got:
                stats["not_a_card"] += 1
                return
            stats["parsed"] += 1
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["bt_appraisal_card"] = {**got, "card_url": url}
            if got.get("heated_sqft") and not li.living_sqft:
                li.living_sqft = got["heated_sqft"]
                stats["filled_sqft"] += 1
            if got.get("appraised_value") and not li.tax_value:
                li.tax_value = got["appraised_value"]
                stats["filled_value"] += 1
            if got.get("last_sale_price"):
                g = li.raw.setdefault("gis", {})
                ls = g.setdefault("last_sale", {})
                if not ls.get("amount"):
                    ls["amount"] = got["last_sale_price"]
                    ls["year"] = got.get("last_sale_year")
                    stats["filled_sale"] += 1

        await asyncio.gather(*(one(li) for li in targets))
    log.info("bt_card.done", **stats)
    return stats
