"""Horry County SC delinquent-tax list, read from the treasurer's weekly spreadsheet.

THE FILE (read live 2026-09-21: HTTP 200, 296 KB, 4,952 rows)
    https://www.horrycountysc.gov/media/b5af14ce/delinquent-list-on-website-081926.xlsx
    linked from https://www.horrycountysc.gov/departments/treasurer/delinquent-tax/ .
    The filename carries the update date (MMDDYY) and the list is refreshed weekly, so the
    current link is read from the treasurer page on every run; the dated URL above is only a
    fallback.

    Row 0   "2026 DELINQUENT TAX SALE LIST AS OF 08/19/2026 (WILL BE UPDATED WEEKLY)"
    Row 1   "ALL ITEMS ON THIS LIST WILL NOT BE SOLD, TAXPAYERS HAVE UNTIL 5:00 PM, MONDAY,
             NOVEMBER 30, 2026 TO PAY 2025 DELINQUENT TAXES"
    Row 2   Item Number | PIN | Owner Name | New Owner Name | Description
    Rows    "00004" | "39307010208" | "<OWNER>" | "" | "ROYALE PALMS HPR PH I     UNIT 301"

WHAT THIS ADDS, HONESTLY
    The sheet has no amount and no situs. The board already carries about 2,460 Horry rows from
    the qPayBill roll with the balance, so this list is not a source of money. What it adds is
    (a) the set of parcels the treasurer is actually carrying to the sale, which is a stronger
    statement than "owes something", (b) `New Owner Name` on about 400 rows, i.e. the property
    changed hands after the tax year, so the person holding it is not the person billed,
    (c) the legal description, and (d) parcels the qPayBill roll misses. The parcel joins
    the Horry situs overlay in parcel_cache for the address.

    The sale itself is NOT dated on the sheet: 5:00 PM on Monday November 30 is the last moment
    to pay, so the row is TAX_LIEN (a standing delinquency) with the pay-by deadline in raw,
    not a TAX_SALE with a made-up sale date.

PRIVACY
    Owner names are held in memory only. Nothing from the sheet is written to disk.

RE-VERIFIED LIVE 2026-10-04 (extraction-completeness audit): live-fetched
the current list (081926 edition, 4,952 rows, AS OF 08/19/2026) and the
treasurer landing page. Confirmed all 5 real columns (Item Number, PIN,
Owner Name, New Owner Name, Description) are already captured and the
landing page links no other .xlsx/.pdf/.csv besides this one file -- the
"no amount, no situs" limitation stated above is still an honest description
of the sheet, not a parsing gap.

Free, no login, no CAPTCHA, ordinary GET.
Slug: counties_sc.horry_delinquent_xlsx
Category: county_tax
ListingType: TAX_LIEN
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind
from .._xlsx_stdlib import cell, header_index, read_rows

log = structlog.get_logger()

SLUG = "counties_sc.horry_delinquent_xlsx"
LANDING = "https://www.horrycountysc.gov/departments/treasurer/delinquent-tax/"
FALLBACK_XLSX = "https://www.horrycountysc.gov/media/b5af14ce/delinquent-list-on-website-081926.xlsx"

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_AS_OF = re.compile(r"AS OF\s+(\d{1,2})/(\d{1,2})/(\d{4})", re.I)
_PAY_BY = re.compile(
    r"UNTIL\s+[\d:]+\s*[AP]M,?\s+(?:[A-Z]+DAY,?\s+)?([A-Z]+)\s+(\d{1,2}),?\s+(20\d{2})\s+TO\s+PAY"
    r"\s+(20\d{2})", re.I)
#: "2026 REAL ESTATE DELINQUENT TAX SALE LIST AS OF 10/05/2026" -- the October 2026
#: editions split the list into a real-estate and a mobile-home workbook and dropped the
#: "TO PAY 2025" line, so the year the title states is the SALE's year, kept as such.
_LIST_TITLE = re.compile(r"\b(20\d{2})\s+(?:(REAL ESTATE|MOBILE HOME)\s+)?DELINQUENT TAX SALE LIST", re.I)
_PIN = re.compile(r"^\d{9,13}$")
#: A mobile-home line: "14X66 81 FLIN STK#132021" or "32700000023  14X66 ...".
_MH_DESC = re.compile(r"\b\d{2}\s?X\s?\d{2}\b|STK#", re.I)
_LAND_PARCEL = re.compile(r"^(\d{9,13})\b")


def _date(y: int, mo: int, d: int) -> datetime | None:
    try:
        return datetime(y, mo, d)
    except ValueError:
        return None


def header_facts(rows: list[list[str]]) -> dict:
    """As-of date, pay-by deadline and tax year from the two title rows."""
    facts: dict = {"as_of": None, "pay_by": None, "tax_year": None,
                   "sale_list_year": None, "list_kind": None}
    for row in rows[:4]:
        text = " ".join(" ".join(c for c in row if c).split())
        m = _LIST_TITLE.search(text)
        if m and facts["sale_list_year"] is None:
            facts["sale_list_year"] = int(m.group(1))
            if m.group(2):
                facts["list_kind"] = m.group(2).lower().replace(" ", "_")
        m = _AS_OF.search(text)
        if m:
            facts["as_of"] = _date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        m = _PAY_BY.search(text)
        if m:
            mon = _MONTHS.get(m.group(1).lower())
            if mon:
                facts["pay_by"] = _date(int(m.group(3)), mon, int(m.group(2)))
            facts["tax_year"] = int(m.group(4))
    return facts


def parse_workbook(data: bytes, source_url: str) -> list[Listing]:
    rows = read_rows(data)
    hit = header_index(rows, ("pin", "owner name"))
    if hit is None:
        raise ValueError("no header row with PIN and Owner Name in the first 30 rows")
    hdr_i, cols = hit
    c_item = cols.get("item number")
    c_pin = cols["pin"]
    c_owner = cols["owner name"]
    c_new = cols.get("new owner name")
    c_desc = cols.get("description")
    # "FLC Bid Amount" (added to the sheet with the October 2026 editions, filled on every
    # row): the Forfeited Land Commission's bid, i.e. the taxes, penalties and costs a
    # buyer must cover. The first dollar figure this source has ever carried.
    c_flc = cols.get("flc bid amount")
    facts = header_facts(rows)
    now = datetime.utcnow()
    out: list[Listing] = []
    seen: set[str] = set()
    for row in rows[hdr_i + 1:]:
        pin = re.sub(r"\s+", "", cell(row, c_pin))
        if not _PIN.match(pin) or pin in seen:
            continue
        seen.add(pin)
        billed = " ".join(cell(row, c_owner).split()) or None
        new_owner = " ".join(cell(row, c_new).split()) or None
        desc = " ".join(cell(row, c_desc).split()) or None
        is_mh = bool(desc and _MH_DESC.search(desc)) or pin.startswith("998")
        land = _LAND_PARCEL.match(desc or "")
        # The person who holds it now leads when the sheet says the owner changed.
        owner = new_owner or billed
        flc_bid = _money(cell(row, c_flc)) if c_flc is not None else None
        block = {
            "pin": pin, "item_number": cell(row, c_item) or None,
            "billed_owner": billed, "new_owner": new_owner, "legal_description": desc,
            "land_parcel": land.group(1) if (is_mh and land) else None,
            "tax_year": facts["tax_year"],
            "as_of": facts["as_of"].date().isoformat() if facts["as_of"] else None,
            "pay_by_deadline": facts["pay_by"].date().isoformat() if facts["pay_by"] else None,
            "list_url": source_url, "amount_on_sheet": flc_bid is not None,
            "flc_bid_amount": flc_bid,
            "sale_list_year": facts["sale_list_year"],
            "list_kind": facts["list_kind"],
        }
        out.append(Listing(
            source=SLUG,
            source_url=source_url,
            listing_type=ListingType.TAX_LIEN,        # no sale date is printed on the sheet
            property_kind=PropertyKind.MOBILE if is_mh else PropertyKind.UNKNOWN,
            state="SC", county="Horry",
            parcel_id=pin,
            owner_name=owner, defendant=owner,
            legal_description=desc,
            opening_bid=flc_bid,
            foreclosure_process="tax",
            description=(f"Horry SC delinquent tax list {facts['tax_year'] or ''} (PIN {pin})"
                         + (f", pay by {facts['pay_by'].date().isoformat()}" if facts["pay_by"] else "")
                         + (", owner changed since billing" if new_owner else "")),
            first_seen=now, last_seen=now,
            raw={"horry_delinquent_xlsx": block},
        ))
    return out


def _money(v: str) -> float | None:
    s = re.sub(r"[$,\s]", "", v or "")
    try:
        return round(float(s), 2) if s else None
    except ValueError:
        return None


def _stamp(h: str) -> str:
    """YYYYMMDD from the file name's MMDDYY or MMDDYYYY stamp ('' when there is none).

    The October 2026 real-estate file is stamped MMDDYYYY ('10052026'); reading only the
    last six digits of that gave '052026' -> May 2020, which sorted it below the mobile-home
    file, so the real-estate list (2,720 PINs) was never fetched."""
    m = re.search(r"(\d{2})(\d{2})(\d{4}|\d{2})\.xlsx", h)
    if not m:
        return ""
    yr = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
    return f"{yr}{m.group(1)}{m.group(2)}"


def _kind(h: str) -> str:
    low = h.lower()
    if "mobile-home" in low or "mobile_home" in low:
        return "mobile_home"
    if "real-estate" in low or "real_estate" in low:
        return "real_estate"
    return "combined"


def discover_urls(html: str) -> list[str]:
    """Every current delinquent-list .xlsx on the treasurer page: the newest of each kind.

    Since October 2026 the page links TWO workbooks (real estate, mobile homes); the
    scraper used to take one file, so it kept only whichever sorted first. An older
    single 'combined' file is dropped once a newer per-kind edition is posted."""
    hrefs = re.findall(r'href=["\']([^"\']*delinquent-list[^"\']*\.xlsx[^"\']*)["\']', html or "", re.I)
    newest: dict[str, str] = {}
    for h in hrefs:
        k = _kind(h)
        if k not in newest or _stamp(h) > _stamp(newest[k]):
            newest[k] = h
    split = [newest[k] for k in ("real_estate", "mobile_home") if k in newest]
    if "combined" in newest and (not split or _stamp(newest["combined"]) > max(map(_stamp, split))):
        split.insert(0, newest["combined"])
    return [urljoin(LANDING, h.replace("&amp;", "&")) for h in split]


def discover_url(html: str) -> str | None:
    """The first (newest real-estate, else newest) delinquent-list .xlsx on the page."""
    urls = discover_urls(html)
    return urls[0] if urls else None


class HorryDelinquentXlsx(BaseScraper):
    slug = SLUG
    name = "Horry County SC delinquent tax list (treasurer .xlsx)"
    category = "county_tax"
    timeout_s = 180.0
    expected_min_count = 0
    optional = True

    limit: int | None = None

    async def fetch(self) -> Iterable[Listing]:
        urls: list[str] = []
        try:
            html = await get_text(LANDING, headers={"User-Agent": "Mozilla/5.0"}, timeout=45.0)
            urls = discover_urls(html)
        except Exception as exc:  # noqa: BLE001
            log.warning("horry_xlsx.landing_fail", error=str(exc)[:160])
        urls = urls or [FALLBACK_XLSX]
        out: list[Listing] = []
        seen: set[str] = set()
        for url in urls:                      # sequential: one host, one request at a time
            try:
                data = await get_bytes(url, timeout=120.0)
                rows = parse_workbook(data, url)
            except Exception as exc:  # noqa: BLE001 - one bad workbook must not cost the other
                log.warning("horry_xlsx.fetch_fail", url=url, error=str(exc)[:160])
                continue
            log.info("horry_xlsx.parsed", url=url, rows=len(rows))
            for li in rows:
                if li.parcel_id not in seen:
                    seen.add(li.parcel_id)
                    out.append(li)
        return out[: self.limit] if self.limit else out
