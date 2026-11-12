"""Polk County NC assessor card — public Parcels FeatureServer + per-parcel PDF (no login, no WAF).

Polk has no CAMA/sales JSON layer; the authoritative card is a per-parcel "Property
Record Card" PDF served off the county GIS box. Two steps:

  1) RESOLVE the per-parcel PDF url + TMS from the public hosted Parcels FeatureServer:
       https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/Parcels/FeatureServer/0
     fields: TMS (the county key, e.g. 'S9-G6'), PHYSICAL_STREET_ADDRESS,
             PropertyRecordCard (the PDF url, e.g. http://parcels.polknc.org:8080/S9-G6.pdf)
     We query by li.parcel_id (matched against TMS) first, else by street address.

  2) FETCH the PDF (httpx) and parse with pdfplumber:
       - heated/finished living sqft: "Finished Area: 6,600.00"
       - appraised total:             "TOTAL VALUE 917,185"
       - year built:                  AYB (actual year built)
       - SALES PRICE history block (newest-first as printed), each row after the last
         '|' is:  BOOK PAGE INSTRUMENT  M/D/YYYY  PRICE
         e.g.     381  57  WD  6/09/2010  500,000

The PDF text is heavily letter-spaced ("F i n i s h e d  A r e a"), so labels are
matched against a despaced copy of the text; sale rows are parsed line-by-line.

Live-verified: TMS S9-G6 -> Finished Area 6,600 + most-recent arms-length sale 500,000.
"""
from __future__ import annotations

import io
import re

import pdfplumber

from ..http_client import client
from .base import CardResult, CardSale, money

_BASE = "https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/Parcels/FeatureServer/0/query"
SOURCE_URL = "https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/Parcels/FeatureServer/0"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

COUNTY = ("NC", "Polk")   # auto-discovery key (see enrichment_assessor_card._adapters)

# Instrument/qualification codes that are NOT arms-length sales.
_NON_ARMS_INSTR = {"CMB", "COM", "GFT", "QC", "QCD", "EX", "EXM", "DIV", "TR", "EST", "EAS"}


def _esc(v: str) -> str:
    return v.replace("'", "''")


def _to_int(v) -> int | None:
    try:
        i = int(float(v))
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _date_to_iso(mo: str, da: str, yr: str) -> str | None:
    try:
        return f"{int(yr):04d}-{int(mo):02d}-{int(da):02d}"
    except (TypeError, ValueError):
        return None


async def _query(c, where: str) -> list[dict]:
    params = {"where": where, "outFields": "TMS,PropertyRecordCard,PHYSICAL_STREET_ADDRESS",
              "f": "json"}
    try:
        data = (await c.get(_BASE, params=params)).json()
    except Exception:
        return []
    if not isinstance(data, dict) or data.get("error"):
        return []
    return data.get("features") or []


async def _resolve(c, li) -> dict | None:
    """Return the parcel attributes dict (with TMS + PropertyRecordCard url) or None."""
    feats: list[dict] = []

    # 1) Resolve by parcel_id matched against the county TMS key (e.g. 'S9-G6').
    tms = _clean(getattr(li, "parcel_id", None))
    if tms:
        feats = await _query(c, f"UPPER(TMS)=UPPER('{_esc(tms)}')")

    # 2) Fallback: search by physical street address.
    if not feats:
        addr = _clean(getattr(li, "street_address", None))
        if addr:
            feats = await _query(
                c, f"UPPER(PHYSICAL_STREET_ADDRESS) LIKE UPPER('%{_esc(addr)}%')"
            )

    if not feats:
        return None
    return feats[0].get("attributes") or None


def _parse_pdf(data: bytes) -> tuple[float | None, int | None, float | None, list[CardSale]]:
    """Return (finished_sqft, year_built, total_value, sales[newest-first])."""
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for p in pdf.pages:
                text += (p.extract_text() or "") + "\n"
    except Exception:
        return None, None, None, []

    # Labels on the card are letter-spaced ("F i n i s h e d  A r e a") — match
    # against a fully despaced copy of the document.
    nospace = re.sub(r"\s+", "", text)

    sqft = None
    m = re.search(r"FinishedArea:([\d,]+(?:\.\d+)?)", nospace, re.IGNORECASE)
    if m:
        sqft = money(m.group(1))

    total_value = None
    m = re.search(r"TOTALVALUE([\d,]+(?:\.\d+)?)", nospace, re.IGNORECASE)
    if m:
        total_value = money(m.group(1))

    year_built = None
    m = re.search(r"AYB:?(\d{4})", nospace)   # actual year built
    if m:
        year_built = _to_int(m.group(1))

    sales = _parse_sales(text)
    return sqft, year_built, total_value, sales


def _parse_sales(text: str) -> list[CardSale]:
    """Parse the SALES PRICE history block. Rows are printed newest-first; each sale
    row's tail (after the last '|') is:  BOOK  PAGE  INSTR  M/D/YYYY  PRICE."""
    sales: list[CardSale] = []
    row_re = re.compile(
        r"(?P<book>\d+)\s+(?P<page>\d+)\s+(?P<instr>[A-Z]{1,4})\s+"
        r"(?P<mo>\d{1,2})/(?P<da>\d{1,2})/(?P<yr>\d{4})\s+"
        r"(?P<price>[\d,]+|[A-Z])"
    )
    for line in text.splitlines():
        if "/" not in line:
            continue
        tail = line.rsplit("|", 1)[-1]   # sale columns live after the last pipe
        m = row_re.search(tail)
        if not m:
            continue
        g = m.groupdict()
        # Price column may be a single non-numeric qualifier flag (e.g. 'U' = unqualified);
        # those carry no usable price.
        price = money(g["price"]) if g["price"].replace(",", "").isdigit() else None
        sales.append(CardSale(
            sale_date=_date_to_iso(g["mo"], g["da"], g["yr"]),
            price=price,
            book=_clean(g["book"]),
            page=_clean(g["page"]),
            reason=_clean(g["instr"]),
        ))
    return sales   # already newest-first as printed on the card


async def fetch(li) -> CardResult | None:
    try:
        async with client(timeout=30.0, headers=_UA) as c:
            attrs = await _resolve(c, li)
            if not attrs:
                return None
            pdf_url = _clean(attrs.get("PropertyRecordCard"))
            if not pdf_url or not pdf_url.lower().endswith(".pdf"):
                return None
            try:
                r = await c.get(pdf_url)
                r.raise_for_status()
                pdf_bytes = r.content
            except Exception:
                return None

        sqft, year_built, total_value, sales = _parse_pdf(pdf_bytes)

        res = CardResult(
            source_url=SOURCE_URL,
            living_sqft=sqft,
            living_sqft_is_heated=bool(sqft),   # "Finished Area" = heated/finished
            year_built=year_built,
            market_value=total_value,
        )
        res.sales = sales
        return res if res.has_fill() else None
    except Exception:
        return None
