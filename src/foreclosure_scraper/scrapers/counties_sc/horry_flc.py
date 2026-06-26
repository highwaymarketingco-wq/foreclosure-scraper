"""Horry County SC Forfeited Land Commission (FLC) list — published .xlsx.

Horry (coastal — the Grand Strand: Myrtle Beach / North Myrtle Beach / Conway)
publishes its annual FLC inventory as an Excel file linked from
horrycountysc.gov/boards-and-commissions/forfeited-land-commission/. Each year's
"YYYY FLC LIST" is a county-hosted .xlsx (free, no key, no login, no bypass) that
lists every forfeited parcel available for over-the-counter FLC purchase, with
PIN, taxpayer, situs address, market value, tax owed, and minimum bid.

These are quitclaim-only, no-title-search parcels the county took at tax sale and
now resells at the floor (delinquent tax + costs) — prime cheap distressed
inventory. Horry is out of the strict 18-county upstate footprint but rides the
orchestrator's oceanfront re-pass (it always emits a street address), so coastal
Grand Strand parcels enter scope the same way the other coastal sources do.

FILE LAYOUT (live-verified 2026-06-26 against 2025-flc-list-42126.xlsx):
  Single worksheet, two sections, each with its OWN header row:
    * "REAL ESTATE" section  — header at one row, then land/real-property rows.
    * "MOBILE HOMES ONLY (LAND NOT INCLUDED)" section — header, then MH rows
      whose PIN is a 998…/997… mobile-home account and whose DESCRIPTON carries
      the home dimensions + underlying real parcel ("12 x 60 78 COLO/36607040008").
  Header columns: PIN | ITEM # | TAXPAYER | NEW OWNER | DESCRIPTON |
    POSSIBLE SITUS ADDRESS | MARKET IMP | TAX OWED AT TIME OF SALE |
    MINIMUM BID | BIDS RECEIVED | LAST DAY TO BID | DATE REDEMPTION ENDS
  Section-title rows ("2025 FLC LIST", "REAL ESTATE", "MOBILE HOMES ONLY …") and
  trailing blank rows are skipped — a real row has a numeric PIN + an item #.

DATELESS: the FLC list carries NO auction/sale date — FLC parcels sell
over-the-counter on a rolling basis until redeemed. We DO capture the Excel
"DATE REDEMPTION ENDS" serial as redemption_deadline (and "LAST DAY TO BID" when
present), but there is no sale_date to emit. Noted here per the build brief.

xlsx parsing: openpyxl is NOT a project dependency. A .xlsx is a zip of XML, so
we stream sharedStrings + the single worksheet with the stdlib
``xml.etree.ElementTree.iterparse`` (same approach as the HUD Section-8 scraper).
The vendored _vendor/xls reader is for legacy BIFF8 .xls only; these files are
modern PK-zip .xlsx, so it does not apply.

Free, no auth, no Apify, no CAPTCHA/WAF — a plain HTTPS download of a
county-hosted Excel file plus an HTML scrape to discover the current year's link.
"""
from __future__ import annotations

import datetime
import re
import zipfile
from io import BytesIO
from typing import Any, Iterable
from xml.etree.ElementTree import iterparse

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = (
    "https://www.horrycountysc.gov/boards-and-commissions/"
    "forfeited-land-commission/"
)
# Known-good fallback if the page scrape can't find a current-year link.
_FALLBACK_XLSX = (
    "https://www.horrycountysc.gov/media/om1d2bwo/2025-flc-list-42126.xlsx"
)

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL_RE = re.compile(r"([A-Z]+)")
_MONEY = re.compile(r"-?[\d,]+(?:\.\d+)?")
# Excel 1900 date system epoch (the 1900-leap-year bug means serial 0 is
# 1899-12-30, so serial N -> epoch + N days lands on the right calendar date).
_EXCEL_EPOCH = datetime.date(1899, 12, 30)

# A real PIN is the all-digit Horry parcel/account number. Mobile-home accounts
# start 998/997; real-estate PINs are the standard map number. The section-title
# and header rows never carry an all-digit PIN, which is how we skip them.
_PIN_RE = re.compile(r"^\d{6,}$")
# Trailing ", City, SC 29577" tail of a situs address -> city / zip.
_CITY_ST_ZIP = re.compile(
    r",?\s*([A-Za-z .'\-]+?),?\s+SC\s*(\d{5})?\s*$", re.I
)


def _col_to_idx(cell_ref: str) -> int:
    """'AB12' -> 27 (0-based column index)."""
    letters = _COL_RE.match(cell_ref).group(1)  # type: ignore[union-attr]
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _money(val: Any) -> float | None:
    if val is None:
        return None
    m = _MONEY.search(str(val))
    if not m:
        return None
    try:
        return round(float(m.group(0).replace(",", "")), 2)
    except ValueError:
        return None


def _excel_serial_to_dt(val: Any) -> datetime.datetime | None:
    """Convert an Excel 1900-system date serial to a datetime (date at midnight).

    The FLC sheet stores 'DATE REDEMPTION ENDS' / 'LAST DAY TO BID' as bare
    serials (e.g. 46358 -> 2026-12-02). Non-numeric cells like 'BIDDING CLOSED'
    return None.
    """
    if val is None or str(val).strip() == "":
        return None
    try:
        serial = float(str(val).strip())
    except ValueError:
        return None
    if serial <= 0 or serial > 200000:  # sanity bound
        return None
    d = _EXCEL_EPOCH + datetime.timedelta(days=int(serial))
    return datetime.datetime(d.year, d.month, d.day)


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    """Stream xl/sharedStrings.xml -> ordered list of strings."""
    out: list[str] = []
    if "xl/sharedStrings.xml" not in zf.namelist():
        return out
    with zf.open("xl/sharedStrings.xml") as fh:
        cur: list[str] = []
        in_si = False
        for ev, el in iterparse(fh, events=("start", "end")):
            if el.tag == _NS + "si":
                if ev == "start":
                    cur = []
                    in_si = True
                else:
                    out.append("".join(cur))
                    in_si = False
                    el.clear()
            elif el.tag == _NS + "t" and ev == "end" and in_si:
                cur.append(el.text or "")
    return out


def _read_sheet_rows(zf: zipfile.ZipFile, sst: list[str]) -> list[dict[int, str]]:
    """Stream the first worksheet -> list of {col_idx: value} dicts, row order."""
    sheet_name = next(
        (n for n in zf.namelist()
         if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")),
        None,
    )
    if not sheet_name:
        return []
    rows: list[dict[int, str]] = []
    with zf.open(sheet_name) as fh:
        cur: dict[int, str] = {}
        col = -1
        ctype = None
        vbuf: list[str] = []
        for ev, el in iterparse(fh, events=("start", "end")):
            tag = el.tag
            if tag == _NS + "row" and ev == "start":
                cur = {}
            elif tag == _NS + "c":
                if ev == "start":
                    col = _col_to_idx(el.get("r") or "A1")
                    ctype = el.get("t")
                    vbuf = []
                else:
                    val = "".join(vbuf)
                    if ctype == "s" and val != "":
                        try:
                            val = sst[int(val)]
                        except (ValueError, IndexError):
                            pass
                    if val != "":
                        cur[col] = val
                    el.clear()
            elif tag == _NS + "v" and ev == "end":
                vbuf.append(el.text or "")
            elif tag == _NS + "is" and ev == "end":
                # inline string fallback (rare): grab any <t> text under <is>
                txt = "".join(t.text or "" for t in el.iter(_NS + "t"))
                if txt:
                    cur[col] = txt
                el.clear()
            elif tag == _NS + "row" and ev == "end":
                rows.append(cur)
                el.clear()
    return rows


# Canonical header tokens -> the field we map them to. The two sections use
# 'DESCRIPTON' vs 'DESCRIPTION' (county typo), so match on a substring.
def _header_map(row: dict[int, str]) -> dict[str, int] | None:
    """If this row is a header row (has a PIN + ITEM # column), return a
    {field: col_idx} map; else None."""
    found: dict[str, int] = {}
    for idx, raw in row.items():
        lab = (raw or "").strip().lower()
        if lab == "pin":
            found["pin"] = idx
        elif "item" in lab:
            found["item"] = idx
        elif "taxpayer" in lab:
            found["taxpayer"] = idx
        elif "new owner" in lab:
            found["new_owner"] = idx
        elif lab.startswith("descript"):
            found["desc"] = idx
        elif "situs" in lab or "address" in lab:
            found["situs"] = idx
        elif "market" in lab:
            found["market"] = idx
        elif "tax owed" in lab:
            found["tax_owed"] = idx
        elif "minimum bid" in lab:
            found["min_bid"] = idx
        elif "last day" in lab:
            found["last_bid"] = idx
        elif "redemption" in lab:
            found["redemption"] = idx
    return found if ("pin" in found and "item" in found) else None


def _split_situs(situs: str) -> tuple[str | None, str | None, str | None]:
    """'4711 EYERLY ST, North Myrtle Beach, SC 29582' ->
    (street, city, zip). Leaves 'TBD …' rows (unaddressed land) with a None
    street so they still emit but carry the legal description instead."""
    s = (situs or "").strip().rstrip(",").strip()
    if not s:
        return None, None, None
    city = zipc = None
    m = _CITY_ST_ZIP.search(s)
    if m:
        city = (m.group(1) or "").strip().title() or None
        zipc = m.group(2)
        s = s[: m.start()].rstrip().rstrip(",").strip()
    street = s or None
    # 'TBD …' = no real situs number yet (raw land); keep it as description-ish
    # but don't treat the literal 'TBD ...' as a street address.
    if street and re.match(r"(?i)^tbd\b", street):
        return None, city, zipc
    return street, city, zipc


def _discover_xlsx_url(html: str) -> str:
    """Find the newest 'YYYY FLC LIST' .xlsx link on the FLC page.

    Prefer the highest year label so the scraper auto-advances when the county
    posts the next annual list; fall back to the known-good 2025 URL.
    """
    tree = HTMLParser(html)
    best_year = -1
    best_href = ""
    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "") or ""
        if ".xlsx" not in href.lower():
            continue
        label = (a.text(strip=True) or "")
        blob = (label + " " + href).lower()
        if "flc" not in blob:
            continue
        ym = re.search(r"(20\d{2})", label) or re.search(r"(20\d{2})", href)
        year = int(ym.group(1)) if ym else 0
        if year > best_year:
            best_year, best_href = year, href
    if best_href:
        if best_href.startswith("/"):
            best_href = "https://www.horrycountysc.gov" + best_href
        return best_href
    return _FALLBACK_XLSX


def _parse_listings(data: bytes, slug: str, source_url: str) -> list[Listing]:
    zf = zipfile.ZipFile(BytesIO(data))
    sst = _read_shared_strings(zf)
    rows = _read_sheet_rows(zf, sst)

    out: list[Listing] = []
    cols: dict[str, int] | None = None
    is_mobile = False
    now = datetime.datetime.utcnow()

    for row in rows:
        # A header row resets the active column map for the section that follows.
        hdr = _header_map(row)
        if hdr is not None:
            cols = hdr
            continue
        # Section-title row (single cell like 'MOBILE HOMES ONLY ...') flips the
        # property-kind for the rows that follow it.
        joined = " ".join((row.get(i) or "") for i in sorted(row)).strip()
        if "mobile home" in joined.lower():
            is_mobile = True
            continue
        if "real estate" in joined.lower():
            is_mobile = False
            continue
        if cols is None:
            continue

        pin = (row.get(cols["pin"]) or "").strip()
        item = (row.get(cols.get("item", -1)) or "").strip()
        # Real data rows have an all-digit PIN. Anything else (blank rows,
        # section titles, the '2025 FLC LIST' banner) is skipped.
        if not _PIN_RE.match(pin):
            continue
        if not item:
            continue

        taxpayer = (row.get(cols.get("taxpayer", -1)) or "").strip() or None
        new_owner = (row.get(cols.get("new_owner", -1)) or "").strip() or None
        desc = (row.get(cols.get("desc", -1)) or "").strip() or None
        situs = (row.get(cols.get("situs", -1)) or "").strip()
        street, city, zipc = _split_situs(situs)

        market = _money(row.get(cols.get("market", -1)))
        tax_owed = _money(row.get(cols.get("tax_owed", -1)))
        min_bid = _money(row.get(cols.get("min_bid", -1)))
        redemption = _excel_serial_to_dt(row.get(cols.get("redemption", -1)))
        last_bid = _excel_serial_to_dt(row.get(cols.get("last_bid", -1)))

        kind = PropertyKind.MOBILE if is_mobile else PropertyKind.UNKNOWN
        # Mobile-home rows carry the underlying real parcel after a '/' in the
        # description ("12 x 60 78 COLO/36607040008") — surface it.
        underlying_parcel = None
        if is_mobile and desc and "/" in desc:
            tail = desc.rsplit("/", 1)[-1].strip()
            if tail.isdigit():
                underlying_parcel = tail

        bits = [f"Horry FLC item {item}"]
        if desc:
            bits.append(desc)
        description = " — ".join(bits)[:300]

        out.append(Listing(
            source=slug,
            source_url=source_url,
            listing_type=ListingType.TAX_SALE,
            property_kind=kind,
            state="SC",
            county="Horry",
            parcel_id=pin,
            street_address=street,
            city=city,
            zip_code=zipc,
            legal_description=desc,
            defendant=taxpayer,
            owner_name=new_owner or taxpayer,
            opening_bid=min_bid,
            tax_value=market,
            judgment_amount=tax_owed,
            redemption_deadline=redemption,
            upset_bid_deadline=last_bid,
            foreclosure_process="tax",
            description=description,
            first_seen=now,
            last_seen=now,
            raw={"horry_flc": {
                "item": item,
                "pin": pin,
                "taxpayer": taxpayer,
                "new_owner": new_owner,
                "market_improvement_value": market,
                "tax_owed_at_sale": tax_owed,
                "minimum_bid": min_bid,
                "underlying_parcel": underlying_parcel,
                "mobile_home": is_mobile,
                "situs_raw": situs or None,
                "source": "forfeited_land_commission",
                "dateless": True,  # FLC list carries no sale date (rolling OTC)
            }},
        ))
    return out


class HorryFLC(BaseScraper):
    slug = "counties_sc.horry_flc"
    name = "Horry SC Forfeited Land Commission list (county .xlsx)"
    category = "county_tax"
    expected_min_count = 0  # annual list; can be empty if a year is unposted
    requires_apify = False
    timeout_s = 90.0

    async def fetch(self) -> Iterable[Listing]:
        # Discover the current year's .xlsx from the FLC page; fall back to the
        # known-good 2025 URL if the page scrape comes up empty.
        xlsx_url = _FALLBACK_XLSX
        try:
            html = await get_text(PAGE_URL, timeout=45.0)
            xlsx_url = _discover_xlsx_url(html)
        except Exception as exc:  # noqa: BLE001
            log.warning("horry_flc.page_fetch_failed", error=str(exc)[:160])

        try:
            data = await get_bytes(xlsx_url, timeout=90.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("horry_flc.xlsx_fetch_failed", url=xlsx_url, error=str(exc)[:160])
            return []

        if not data[:2] == b"PK":  # not a zip/.xlsx
            log.warning("horry_flc.not_xlsx", url=xlsx_url, head=data[:8].hex())
            return []

        try:
            out = _parse_listings(data, self.slug, xlsx_url)
        except Exception as exc:  # noqa: BLE001
            log.warning("horry_flc.parse_failed", error=str(exc)[:160])
            return []

        log.info("horry_flc.done", count=len(out), url=xlsx_url)
        return out
