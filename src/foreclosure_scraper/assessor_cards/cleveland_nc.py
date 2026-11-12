"""Cleveland County NC assessor card — WebGIS (Hurt & Proffitt) static PropertyCard.

Public, no login, no render. The PropertyCard.php page is a server-rendered
fixed-width text dump inside <pre> blocks and carries EVERYTHING we need:
heated living sqft, year built, beds/baths, appraised market value, and a full
SALES HISTORY block (deed book/page, date, instrument, disqualified flag,
amount, deed name).

Card endpoint, keyed by the WebGIS pid (the county's internal sequence number,
a small integer like 62352 — NOT the 10-digit PIN):
  GET https://www.webgis.net/nc/cleveland/PropertyCard.php?pid={PID}

  ... PARCEL ID.. 62352 ... DEED YEAR/BOOK/PAGE.. 2025 1960 1674 ...
  --- SALES HISTORY ---
  DEED BK/PAGE  SALE DATE  SALES INSTRUMENT DISQUALIFIED  SALE AMOUNT ...
    1960  1674  11/12/2025 DEED          RELATIVES/RELAT    57,500 ... KALE DAVID ANTHONY
  ...
   MAIN FIN AREA.. 942.00 ... ACT/EFF YR/AGE.. 2013 2014 ...  #BED: 2  #BTH: 1.0
  --FMV... MA NEWHO NEWHO MARKET ADJ  110.00 x  167,027

pid RESOLUTION: the WebGIS pid is the internal seqnum, not the PIN. We use
li.parcel_id when it already looks like a WebGIS pid (a short bare integer).
The WebGIS address search is an ArcGIS JS SPA with no clean static address->pid
endpoint, so an address-only lead (no usable pid) returns None gracefully.

The DISQUALIFIED column is mapped into CardSale.reason so the base picker auto-
skips non-arms-length transfers (RELATIVES/RELAT -> contains "relat"; the family
filter in base catches it; ADDITION PARCEL / SPLIT / PARENT carry no SALE AMOUNT
so they're dropped on the <$1000 floor anyway).
"""
from __future__ import annotations

import re

from ..http_client import client
from .base import CardResult, CardSale, money

CARD_URL = "https://www.webgis.net/nc/cleveland/PropertyCard.php"
HISTORY_URL = "https://www.webgis.net/nc/cleveland/ParcelHistory.php"
SOURCE_URL = "https://www.webgis.net/nc/cleveland/"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/126"}

COUNTY = ("NC", "Cleveland")   # auto-discovery key (see enrichment_assessor_card._adapters)

# Pull all <pre>...</pre> text out of the rendered card (page1 has the data we need).
_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.IGNORECASE | re.DOTALL)
# A valid card has a real parcel id line; "No parcel specified." pages don't.
_PARCEL_RE = re.compile(r"PARCEL ID\.+\s*(\S+)")
# Heated/finished area on the major improvement.
_MAINFIN_RE = re.compile(r"MAIN FIN AREA\.+\s*([\d,]+(?:\.\d+)?)")
# Actual year built (first 4-digit year in the ACT/EFF YR/AGE triple).
_ACTYR_RE = re.compile(r"ACT/EFF YR/AGE\.+\s*(\d{4})")
_BED_RE = re.compile(r"#BED:\s*([\d.]+)")
# Full + half baths.
_BTH_RE = re.compile(r"#BTH:\s*([\d.]+)")
_HBTH_RE = re.compile(r"#HBTH:\s*([\d.]+)")
# Final market value line: "--FMV... MA NEWHO NEWHO MARKET ADJ  110.00 x  167,027"
_FMV_RE = re.compile(r"--FMV\.+.*?x\s+([\d,]+)", re.DOTALL)

# One sales-history row. Columns are space-aligned, not delimited, so we match
# from the front: book page | M/D/YYYY | INSTRUMENT text | DISQUALIFIED text |
# optional SALE AMOUNT | optional STAMP AMOUNT | DEED NAME.
#   1960  1674 11/12/2025  DEED          RELATIVES/RELAT   57,500   115.00  KALE DAVID ANTHONY
_SALE_ROW_RE = re.compile(
    r"^\s*(?P<book>[A-Z0-9]+)\s+(?P<page>[A-Z0-9]+)\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+"
    r"(?P<rest>.+?)\s*$"
)


def _webgis_pid(li) -> str | None:
    """The WebGIS pid is the county's internal seqnum (a short bare integer).

    li.parcel_id is the only field that can carry it. If parcel_id is already a
    short all-digit value we treat it as the pid; longer/dashed/dotted PINs are
    NOT WebGIS pids, so we can't resolve those statically -> None (caller None).
    """
    raw = (getattr(li, "parcel_id", "") or "").strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    # WebGIS seqnums are small (maxlength=6 on the search box; allow a little
    # headroom). A 10+ digit PIN or a dashed/dotted PIN is NOT a WebGIS pid.
    if digits and 1 <= len(digits) <= 7:
        return digits
    return None


def _mdY_to_iso(s: str) -> str | None:
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", (s or "").strip())
    if not m:
        return None
    mo, da, yr = m.groups()
    return f"{yr}-{int(mo):02d}-{int(da):02d}"


def _to_int(v) -> int | None:
    try:
        n = int(float(v))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _to_float(v) -> float | None:
    try:
        f = float(v)
        return f if f >= 0 else None
    except (TypeError, ValueError):
        return None


def _parse_sales(text: str) -> list[CardSale]:
    """Parse the SALES HISTORY block. Rows are already newest-... actually the
    card lists them newest-first; we preserve that order (base wants newest-first).
    """
    # Isolate the SALES HISTORY section so we don't accidentally match land/improv lines.
    start = text.find("SALES HISTORY")
    if start == -1:
        return []
    tail = text[start:]
    end = re.search(r"-{6,}\s+LAND SEGMENTS", tail)
    block = tail[: end.start()] if end else tail

    sales: list[CardSale] = []
    for line in block.splitlines():
        m = _SALE_ROW_RE.match(line)
        if not m:
            continue
        gd = m.groupdict()
        iso = _mdY_to_iso(gd["date"])
        if not iso:
            continue
        rest = gd["rest"]
        # Find the SALE AMOUNT: first number with a comma or >=4 digits that isn't
        # a small stamp value. The amount precedes STAMP AMOUNT (which has a .dd).
        # Grab all numeric tokens; the first integer-style number is the sale amount.
        price = None
        amt_match = re.search(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d{4,})(?:\.\d+)?(?![\d])", rest)
        if amt_match:
            price = money(amt_match.group(1))
        # Split `rest` into columns on runs of 2+ spaces (the card is space-aligned).
        cols = [c for c in re.split(r"\s{2,}", rest.strip()) if c]
        # grantee = the DEED NAME = the trailing alphabetic column.
        grantee = None
        if cols and re.search(r"[A-Za-z]", cols[-1]) and not re.fullmatch(
            r"[\d,.\s]+", cols[-1]
        ):
            grantee = cols[-1].strip()
        # reason = INSTRUMENT + DISQUALIFIED descriptors (the text before the first
        # money token). Used by base's non-arms-length filter.
        if amt_match:
            reason = rest[: amt_match.start()].strip()
        else:
            # No money token: reason is everything except the trailing deed name.
            reason = rest
            if grantee:
                reason = rest[: rest.rfind(grantee)]
        reason = re.sub(r"\s{2,}", " ", reason).strip() or None
        sales.append(CardSale(
            sale_date=iso,
            price=price,
            book=gd["book"].strip() or None,
            page=gd["page"].strip() or None,
            reason=reason,
            grantee=grantee,
        ))
    return sales


def _parse_card(html: str) -> CardResult | None:
    pres = _PRE_RE.findall(html or "")
    if not pres:
        return None
    text = "\n".join(pres)
    # Decode the couple HTML entities the card emits (&amp;) so names/reasons are clean.
    text = text.replace("&amp;", "&")
    if not _PARCEL_RE.search(text):
        return None  # "No parcel specified." page

    sqft = None
    m = _MAINFIN_RE.search(text)
    if m:
        sqft = money(m.group(1))

    year_built = None
    m = _ACTYR_RE.search(text)
    if m:
        year_built = _to_int(m.group(1))

    bedrooms = None
    m = _BED_RE.search(text)
    if m:
        bedrooms = _to_float(m.group(1))

    bathrooms = None
    m = _BTH_RE.search(text)
    if m:
        full = _to_float(m.group(1)) or 0.0
        half = 0.0
        hm = _HBTH_RE.search(text)
        if hm:
            half = _to_float(hm.group(1)) or 0.0
        bathrooms = (full + 0.5 * half) or None

    market_value = None
    m = _FMV_RE.search(text)
    if m:
        market_value = money(m.group(1))

    res = CardResult(
        source_url=SOURCE_URL,
        living_sqft=sqft,
        living_sqft_is_heated=bool(sqft),   # MAIN FIN AREA = heated/finished area
        year_built=year_built,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        market_value=market_value,
    )
    res.sales = _parse_sales(text)
    return res


async def fetch(li) -> CardResult | None:
    try:
        pid = _webgis_pid(li)
        if not pid:
            # Address-only lead: WebGIS search is a JS SPA with no static
            # address->pid endpoint, so we can't resolve it for free. Bail safely.
            return None
        async with client(timeout=30.0, headers=_UA) as c:
            try:
                r = await c.get(CARD_URL, params={"pid": pid})
            except Exception:
                return None
            res = _parse_card(r.text)
        if res is None:
            return None
        return res if res.has_fill() else None
    except Exception:
        return None
