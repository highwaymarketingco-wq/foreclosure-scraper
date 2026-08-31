"""Rutherford County NC tax-foreclosure sale calendar — the county's own two
``/foreclosure_information/`` pages.

The Revenue Department / Tax Administrator publishes its live tax-foreclosure
docket across two sibling ``.php`` pages under
``/departments/revenue_department_tax_administrator/foreclosure_information/``:

1. ``in_office_current_and_upcoming_foreclosure_sale_dates.php`` — the parcels
   the county prosecutes IN-HOUSE, as a clean server-rendered HTML ``<table>``:
   Address | Parcel | File # | Tax Value | Sale Date | Opening Bid |
   Property Record Card | Additional Info. Live-verified 2026-08-30: 16 rows,
   each with a street address, one-or-two parcel ids, an ``M``-docket file
   number ("24M251"), a tax value, and a Property-Info link into
   ``lrcpwa.ncptscloud.com``. Sale dates on this page are mostly soft
   ("Summer 2026", "Fall 2026", "tbd") — a real calendar quarter, not yet a
   calendar day — so ``sale_date`` is only set when an actual M/D/Y (or a
   spelled-out month-day-year) is published; the soft text is preserved in
   ``raw``.

2. ``outside_law_(kania_law_firm)_current_and_upcoming_foreclosure_sale_dates.php``
   — the parcels the county farms out to The Kania Law Firm. NOT a table:
   free-text blocks under a "Current Foreclosures" heading, one block per
   parcel, e.g.::

       Abrams, Christeen Logan – (1206540) - 141 Duncan St – File #23516,
       House with 0.51 acres
       25CVD000199-800
       Current Bid: $70,350.00, Amount needed to upset the bid: $73,867.50
       Last day for upset bid: 8/31/2026

   That block carries the OWNER OF RECORD, the parcel id, the situs street, a
   Kania file number, the court case number, the CURRENT BID, the minimum
   needed to upset it, and the LAST DAY TO BID (the upset-bid deadline). Every
   Kania row here is inside an active upset window.

WHY A DEDICATED COUNTY SCRAPER. The board carried 0% foreclosure coverage for
Rutherford. ``national.nc_upset_bids`` also reads these two URLs, but only keeps
rows already in an upset posture and depends on that national module running;
this county-scoped scraper emits the WHOLE published docket (in-office +
outside-counsel) as a first-class ``counties_nc.rutherford_foreclosure`` source.
Overlapping parcels collapse in dedupe (parcel key) and ``Listing.merge``
deep-merges ``raw`` and ``raw["also_seen_in"]``, so running both is additive,
never duplicative.

LISTING TYPE. These are NC in-rem property-tax foreclosures (§105-374), some
prosecuted in-office and some by Kania. ``models.ListingType`` has no plain
``FORECLOSURE`` member; the substantively-correct enum is ``TAX_SALE`` — the
same value ``national.nc_upset_bids`` and ``law_firms.kania`` use for these
exact parcels, so a dedupe merge can never flap the type. ``foreclosure_process``
is set to ``"tax"`` and the upset economics are promoted to first-class
``opening_bid`` / ``upset_bid_deadline`` plus ``raw["rutherford_foreclosure"]``.

DATELESS. Most in-office rows have no scheduled sale day and Kania rows are
carried by an upset deadline rather than a sale date, so
``counties_nc.rutherford_foreclosure`` is registered in
``main.DATELESS_OK_SOURCES`` (otherwise ``_active_only`` would drop every row).

Free, public, no key, no login, no CAPTCHA/WAF bypass — two plain HTTPS GETs of
county-published HTML.
"""
from __future__ import annotations

import datetime
import os
import re
from typing import Iterable, Optional

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_nc.rutherford_foreclosure"

_BASE = (
    "https://www.rutherfordcountync.gov/departments/"
    "revenue_department_tax_administrator/foreclosure_information/"
)
IN_OFFICE_URL = _BASE + "in_office_current_and_upcoming_foreclosure_sale_dates.php"
KANIA_URL = (
    _BASE
    + "outside_law_(kania_law_firm)_current_and_upcoming_foreclosure_sale_dates.php"
)

# Dash variants the county mixes freely: hyphen, en-dash, em-dash.
_DASH = "‐‑‒–—―-"
_MONEY = re.compile(r"([\d,]+(?:\.\d{1,2})?)")
_MDY = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
#: "August 26, 2026" / "Aug 26 2026"
_LONGDATE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    re.I,
)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

#: Kania block header: "Owner Name – (parcel) - 141 Duncan St – File #23516"
_KANIA_HEADER = re.compile(
    r"^(?P<name>.+?)\s*[" + _DASH + r"]\s*"
    r"\(\s*(?P<parcel>[0-9]{3,})\s*\)\s*[" + _DASH + r"]\s*"
    r"(?P<addr>.+?)\s*[" + _DASH + r"]\s*"
    r"File\s*#?\s*(?P<file>[0-9]+)",
    re.I,
)
#: Court case number: "25CVD000199-800", "26CVD000526-800".
_CASE = re.compile(r"\b(\d{2}[A-Z]{2,4}\d{3,}(?:-\d+)?)\b")
_CURRENT_BID = re.compile(r"current\s+bid[:\s]*\$?\s*([\d,]+(?:\.\d{1,2})?)", re.I)
_UPSET_AMT = re.compile(
    r"(?:amount\s+needed\s+to\s+upset\s+the\s+bid)[:\s]*\$?\s*([\d,]+(?:\.\d{1,2})?)",
    re.I,
)
_LAST_DAY = re.compile(
    r"last\s+day\s+for\s+upset\s+bid[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})", re.I
)
#: Rutherford post-office cities, longest-first so "Forest City"/"Lake Lure"
#: win over a bare token when splitting an in-office "street, city" address.
_CITIES: tuple[str, ...] = tuple(sorted(
    (
        "Forest City", "Lake Lure", "Union Mills", "Mill Spring",
        "Chimney Rock", "Rutherfordton", "Ellenboro", "Mooresboro",
        "Spindale", "Henrietta", "Caroleen", "Bostic", "Cliffside",
        "Gilkey", "Harris", "Sunshine", "Golden Valley",
    ),
    key=len, reverse=True,
))


def _money(val: Optional[str]) -> Optional[float]:
    if not val:
        return None
    m = _MONEY.search(str(val))
    if not m:
        return None
    try:
        f = round(float(m.group(1).replace(",", "")), 2)
    except ValueError:
        return None
    return f if f > 0 else None


def _parse_date(text: Optional[str]) -> Optional[datetime.datetime]:
    """Return a datetime only for a concrete calendar day. Soft calendar text
    ('Summer 2026', 'Fall 2026', 'tbd', 'Aug 2026') has no day, so returns None."""
    if not text:
        return None
    s = str(text)
    m = _MDY.search(s)
    if m:
        mo, day, yr = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if yr < 100:
            yr += 2000
        try:
            return datetime.datetime(yr, mo, day)
        except ValueError:
            return None
    m = _LONGDATE.search(s)
    if m:
        mo = _MONTHS.get(m.group(1)[:3].lower())
        if mo:
            try:
                return datetime.datetime(int(m.group(3)), mo, int(m.group(2)))
            except ValueError:
                return None
    return None


def _split_addr(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """'262 Canine Dr, Bostic' -> ('262 Canine Dr', 'Bostic').
    '0 US 64 Hwy, Union Mills, NC' -> ('0 US 64 Hwy', 'Union Mills')."""
    if not raw:
        return None, None
    s = raw.strip()
    # Drop a trailing ", NC" / ", NC 28043"
    s = re.sub(r",?\s*NC(?:\s+\d{5})?\s*$", "", s, flags=re.I).strip().rstrip(",")
    if "," in s:
        street, city = s.rsplit(",", 1)
        street, city = street.strip(), city.strip()
        return (street or None), (city or None)
    # No comma — try to peel a known city off the tail.
    for city in _CITIES:
        if s.lower().endswith(" " + city.lower()):
            street = s[: -(len(city) + 1)].strip()
            if street:
                return street, city
    return (s or None), None


def _first_parcel(raw: Optional[str]) -> tuple[Optional[str], list[str]]:
    """'615595, 1603783' -> ('615595', ['615595','1603783'])."""
    if not raw:
        return None, []
    parts = [p.strip() for p in re.split(r"[,/;]+", raw) if p.strip()]
    return (parts[0] if parts else None), parts


def _header_map(table) -> dict[str, int]:
    head = table.css_first("tr")
    out: dict[str, int] = {}
    if head:
        for i, c in enumerate(head.css("th,td")):
            out[c.text(strip=True).lower()] = i
    return out


def _col(cells: list, hmap: dict[str, int], *names: str) -> Optional[str]:
    for n in names:
        for key, idx in hmap.items():
            if n in key and idx < len(cells):
                v = cells[idx].text(strip=True)
                return v or None
    return None


def _parse_in_office(html: str, now: datetime.datetime) -> list[Listing]:
    tree = HTMLParser(html)
    table = tree.css_first("table")
    if not table:
        return []
    hmap = _header_map(table)
    rows = table.css("tr")
    out: list[Listing] = []
    for tr in rows[1:]:  # skip header
        cells = tr.css("td")
        if not cells or len(cells) < 2:
            continue
        addr_raw = _col(cells, hmap, "address")
        parcel_raw = _col(cells, hmap, "parcel")
        parcel, all_parcels = _first_parcel(parcel_raw)
        if not (addr_raw or parcel):
            continue
        file_no = _col(cells, hmap, "file")
        tax_val = _money(_col(cells, hmap, "tax value", "value"))
        sale_raw = _col(cells, hmap, "sale date", "sale")
        bid_raw = _col(cells, hmap, "opening bid", "bid")
        info = _col(cells, hmap, "additional")
        street, city = _split_addr(addr_raw)
        # Property-record-card link(s), if any.
        card_links: list[str] = []
        for c in cells:
            for a in c.css("a[href]"):
                href = (a.attributes.get("href") or "").strip()
                if href.startswith("http"):
                    card_links.append(href)
        sale_dt = _parse_date(sale_raw)
        no_situs_number = bool(street and street.lstrip().startswith("0 "))

        bits = [
            "Rutherford NC tax foreclosure (in-office)",
            street or addr_raw or "unknown address",
        ]
        if file_no and file_no.lower() != "tbd":
            bits.append(f"File {file_no}")
        if sale_raw and not sale_dt:
            bits.append(f"sale: {sale_raw}")

        out.append(Listing(
            source=SLUG,
            source_url=IN_OFFICE_URL,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county="Rutherford",
            parcel_id=parcel,
            street_address=street,
            city=city,
            sale_date=sale_dt,
            opening_bid=_money(bid_raw),
            tax_value=tax_val,
            case_number=(file_no if file_no and file_no.lower() != "tbd" else None),
            foreclosure_process="tax",
            auction_status="upcoming",
            description=" — ".join(b for b in bits if b)[:300],
            first_seen=now,
            last_seen=now,
            raw={"rutherford_foreclosure": {
                "docket": "in_office",
                "address_raw": addr_raw,
                "parcels": all_parcels,
                "file_number": file_no,
                "tax_value": tax_val,
                "sale_date_raw": sale_raw,
                "opening_bid_raw": bid_raw,
                "additional_info": info,
                "property_record_cards": card_links or None,
                "no_situs_number": no_situs_number,
                "dateless": sale_dt is None,
            }},
        ))
    return out


def _parse_kania(html: str, now: datetime.datetime) -> list[Listing]:
    tree = HTMLParser(html)
    post = tree.css_first("div.post") or tree.css_first("main") or tree.css_first("body")
    if not post:
        return []
    text = post.text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # Group into blocks: a new block starts at each header line. Only consider
    # lines at/after the "Current Foreclosures" marker so nav/boilerplate above
    # can't produce phantom blocks.
    start = 0
    for i, ln in enumerate(lines):
        if re.search(r"current\s+foreclosures", ln, re.I):
            start = i + 1
            break

    blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in lines[start:]:
        if re.search(r"upcoming\s+kania", ln, re.I):
            break  # "Upcoming Kania Law Firm foreclosures" — no parcels below
        if _KANIA_HEADER.match(ln):
            if cur:
                blocks.append(cur)
            cur = [ln]
        elif cur:
            cur.append(ln)
    if cur:
        blocks.append(cur)

    out: list[Listing] = []
    for blk in blocks:
        hm = _KANIA_HEADER.match(blk[0])
        if not hm:
            continue
        name = hm.group("name").strip(" ,")
        parcel = hm.group("parcel").strip()
        addr = hm.group("addr").strip(" ,")
        file_no = hm.group("file").strip()
        body = "\n".join(blk)

        case_m = _CASE.search(body)
        cur_bid = _CURRENT_BID.search(body)
        upset_amt = _UPSET_AMT.search(body)
        last_day = _LAST_DAY.search(body)
        # Property description line (e.g. "House with 0.51 acres") — the line
        # right after the header that isn't the case number / bid / deadline.
        prop_desc = None
        for ln in blk[1:]:
            if (_CASE.fullmatch(ln) or _CURRENT_BID.search(ln)
                    or _LAST_DAY.search(ln) or _UPSET_AMT.search(ln)):
                continue
            prop_desc = ln
            break

        street, city = _split_addr(addr)
        opening = _money(cur_bid.group(1)) if cur_bid else None
        upset_deadline = _parse_date(last_day.group(1)) if last_day else None

        bits = ["Rutherford NC tax foreclosure (Kania Law Firm)", name or addr]
        if opening:
            bits.append(f"current bid ${opening:,.0f}")
        if last_day:
            bits.append(f"upset by {last_day.group(1)}")

        out.append(Listing(
            source=SLUG,
            source_url=KANIA_URL,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county="Rutherford",
            parcel_id=parcel or None,
            street_address=street,
            city=city,
            owner_name=name or None,
            defendant=name or None,
            opening_bid=opening,
            upset_bid_deadline=upset_deadline,
            case_number=(case_m.group(1) if case_m else None),
            foreclosure_process="tax",
            auction_status="upset_period",
            description=" — ".join(b for b in bits if b)[:300],
            first_seen=now,
            last_seen=now,
            raw={"rutherford_foreclosure": {
                "docket": "outside_kania",
                "owner": name or None,
                "address_raw": addr,
                "kania_file_number": file_no,
                "property_description": prop_desc,
                "current_bid": opening,
                "upset_amount_needed": _money(upset_amt.group(1)) if upset_amt else None,
                "last_day_for_upset_bid": last_day.group(1) if last_day else None,
                "case_number": case_m.group(1) if case_m else None,
                "dateless": True,  # carried by upset deadline, not a sale date
            }},
        ))
    return out


class RutherfordForeclosure(BaseScraper):
    slug = SLUG
    name = "Rutherford NC tax-foreclosure sale calendar (in-office + Kania)"
    category = "foreclosure"
    #: Two dozen parcels across both dockets in-season; 0 is legitimate when the
    #: county has cleared the calendar between sale cycles.
    expected_min_count = 0
    requires_apify = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_RUTHERFORD_FCL", "1") == "0":
            log.info("rutherford_foreclosure.disabled_by_env")
            return []

        now = datetime.datetime.utcnow()
        out: list[Listing] = []

        try:
            html = await get_text(IN_OFFICE_URL, timeout=45.0, impersonate=True)
            out.extend(_parse_in_office(html, now))
        except Exception as exc:  # noqa: BLE001
            log.warning("rutherford_foreclosure.in_office_failed", error=str(exc)[:160])

        try:
            html = await get_text(KANIA_URL, timeout=45.0, impersonate=True)
            out.extend(_parse_kania(html, now))
        except Exception as exc:  # noqa: BLE001
            log.warning("rutherford_foreclosure.kania_failed", error=str(exc)[:160])

        log.info("rutherford_foreclosure.done", count=len(out))
        return out
