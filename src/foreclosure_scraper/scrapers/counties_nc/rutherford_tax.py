"""Rutherford County NC delinquent property-tax roll — the county's own TR-452
"Delinquent Bills Report w/ Parcel Id" Excel export.

WHAT THIS SLUG USED TO BE, AND WHY IT WAS REPLACED
--------------------------------------------------
Until now this scraper read
``/departments/revenue_department_tax_administrator/foreclosure_sale_dates.php``
and split it on the retired ``***…`` block separator. Probed live 2026-08-03 the
page still returns HTTP 200 and still parses (11 blocks), which is worse than a
clean zero: it is a FROZEN MIRROR. Every sale date on it is 12/19/2024 or
12/23/2024 and the parcels are the 2024 in-rem docket. The county moved its live
foreclosure calendar to ``/foreclosure_information/`` in 2025, where the in-office
list is now a real HTML table (2026 dates, ``tbd`` bids) and the outside-counsel
list is a text page carrying owner names. So the old target was emitting stale
2024 sale_dates onto the board for parcels that have since sold.

Both live ``/foreclosure_information/`` pages are ALREADY read by
``scrapers/national/nc_upset_bids.py`` (``COUNTY_UPSET_PAGES``): 26 Rutherford
rows on 2026-08-03, with current bid, upset deadline and owner of record. Adding
a second reader for them would just duplicate rows into dedupe. So this slug is
repointed at the one Rutherford tax surface nc_upset_bids does NOT cover: the
whole delinquent universe, not the ~two dozen parcels already in a sale posture.

WHAT IT IS NOW
--------------
The Revenue Department's index page links a county-hosted Excel export titled
"2025 Delinquent Tax Bills as of 2/1/2026" — NCPTS report TR-452, "Delinquent
Bills Report w/ Parcel Id", Source Type ``REI`` (real estate only), Tax Year
2025. Live-verified 2026-08-03: 9,337 delinquent bills over 9,328 parcels,
$5,639,937.64 owed, every row carrying bill #, taxpayer name, parcel id, amount
due, and (61.4% of rows) the situs address.

That is the NCGS 105-369 population — the pool every future tax foreclosure is
drawn from — a year or more ahead of the sale calendar, with a real
taxes-OWED dollar figure attached. Amount owed is promoted to first-class
``judgment_amount`` (same convention as ``counties_sc.horry_flc``) and also kept
in ``raw['rutherford_tax']['amount_owed']``, which ``enrichment_tax_owed``
normalizes into ``raw['tax_owed']``.

LINK DISCOVERY, AND THE ``<base href>`` TRAP
--------------------------------------------
The .xlsx URL is scraped off the index page, never guessed — the filename
carries a cache-buster (``?t=202602011040510``) that changes every time the
county re-posts. The trap: the anchor's href is the bare filename
``TR-452 Delinquent Bills Report w Parcel Id.xlsx?t=…`` but the page declares
``<base href="https://www.rutherfordcountync.gov/" />``, so it resolves against
the SITE ROOT, not the department directory. Resolving it the obvious way
(relative to the page path) yields a 302 to ``cms6.revize.com`` and then a hard
404. Root-relative + percent-encoded spaces returns the real 1.3 MB workbook.

FILE LAYOUT (live-verified 2026-08-03)
--------------------------------------
Single worksheet. Rows 0-9 are the report banner + parameter block
("Source Type: REI", "Tax Year: 2025", "Data as of: …"), row 10 is the header,
data starts at row 12, and the sheet ends with ``Subtotal``/``Total`` rows that
must be dropped or they land as a $5.6M phantom lead.
Columns (0-based): 0 Bill # | 6 Taxpayer Name | 11 Bill Description |
16 Parcel Id | 18 Amount Due | 20 Source Type.
"Bill Description" is EITHER a situs address ("297 E MAIN ST FOREST CITY, NC
28043") or a legal description ("B I COTTON MILLS LO176 SE2 PL6-59"). A leading
``0`` house number means the parcel has no assigned situs number (unimproved) —
kept as the street with a ``no_situs_number`` flag rather than discarded, since
the parcel id still resolves it through GIS.

DATELESS: a delinquent bill has no sale date. ``counties_nc.rutherford_tax`` is
already in ``main.DATELESS_OK_SOURCES``, so no orchestrator change is needed.

SEE ALSO ``counties_nc.rutherford_wildfire_tax`` — the county's Sturgis/Avalon
tax-search API, which carries the same population back ten tax years plus owner
mailing addresses and ADVERTISED / OUTSIDE-LAW-FIRM status flags. That host
publishes ``Disallow: /``, so it is robots-walled and gated off; this Excel
export is the robots-clean, county-hosted surface that actually runs.

xlsx parsing: openpyxl is NOT a project dependency. A .xlsx is a zip of XML, so
the sheet is streamed with the stdlib ``xml.etree.ElementTree.iterparse`` — the
same approach as ``counties_sc.horry_flc`` and
``national.hud_section8_contracts``, kept local so the scraper stays
self-contained.

Free, public, no key, no login, no CAPTCHA/WAF bypass — an HTML scrape to find
the link plus a plain HTTPS download of a county-published Excel file.
"""
from __future__ import annotations

import datetime
import re
import zipfile
from io import BytesIO
from typing import Any, Iterable
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from xml.etree.ElementTree import iterparse

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_nc.rutherford_tax"

PAGE_URL = (
    "https://www.rutherfordcountync.gov/departments/"
    "revenue_department_tax_administrator/index.php"
)
SITE_ROOT = "https://www.rutherfordcountync.gov/"
#: Known-good fallback if the page scrape can't find the link. Cache-buster
#: omitted deliberately — the bare path serves the current file.
_FALLBACK_XLSX = SITE_ROOT + quote("TR-452 Delinquent Bills Report w Parcel Id.xlsx")

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL_RE = re.compile(r"([A-Z]+)")
_MONEY = re.compile(r"-?[\d,]+(?:\.\d+)?")

# Column indexes on the TR-452 sheet (stable across re-runs of the NCPTS report).
COL_BILL = 0
COL_TAXPAYER = 6
COL_DESC = 11
COL_PARCEL = 16
COL_AMOUNT = 18
COL_SOURCE_TYPE = 20

#: A real data row's Bill # is "0000000003-2025-2025-0000-00-REG". The banner,
#: parameter, header, Subtotal and Total rows never match, which is how they are
#: dropped without depending on row numbers.
_BILL_RE = re.compile(r"^\d{8,12}-\d{4}-\d{4}-\d{4}-\d{2}")

#: "… CITY, NC 28139" tail. State is always NC on this roll (5,734/5,734 rows).
#: The comma is optional because ``rutherford_wildfire`` reuses this splitter and
#: the Sturgis SitusAddress line omits it ("0 GLEN RIDGE TRL LAKE LURE NC 28746").
_ADDR_TAIL_RE = re.compile(r"^(?P<pre>.+?),?\s*NC\s*(?P<zip>\d{5})\s*$", re.I)

#: Post-office cities appearing on the roll, live-derived from all 5,734
#: addressed rows on 2026-08-03 (100% match). There is no comma between street
#: and city, so the city has to be recognised by name; longest-first so
#: "FOREST CITY" wins over a bare token and "LAKE LURE" isn't split.
_CITIES: tuple[str, ...] = tuple(sorted(
    (
        "FOREST CITY", "LAKE LURE", "UNION MILLS", "MILL SPRING",
        "CHIMNEY ROCK", "BLACK MOUNTAIN", "RUTHERFORDTON", "ELLENBORO",
        "MOORESBORO", "SPINDALE", "HENRIETTA", "CAROLEEN", "BOSTIC",
        "CASAR", "CLIFFSIDE", "MARION", "HENDERSONVILLE",
    ),
    key=len,
    reverse=True,
))

_TAX_YEAR_RE = re.compile(r"^\s*Tax Year:\s*$", re.I)
_DATA_AS_OF_RE = re.compile(r"Data as of:\s*(.+)$", re.I)


def _col_to_idx(cell_ref: str) -> int:
    """'AB12' -> 27 (0-based column index)."""
    m = _COL_RE.match(cell_ref)
    letters = m.group(1) if m else "A"
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
        f = round(float(m.group(0).replace(",", "")), 2)
    except ValueError:
        return None
    return f if f > 0 else None


def _clean(s: Any) -> str | None:
    """Strip the trailing padding NCPTS leaves on every text cell."""
    out = (str(s) if s is not None else "").strip()
    return out or None


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
    """Stream the first worksheet -> list of {col_idx: value}, in row order."""
    sheet_name = next(
        (n for n in sorted(zf.namelist())
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
                txt = "".join(t.text or "" for t in el.iter(_NS + "t"))
                if txt:
                    cur[col] = txt
                el.clear()
            elif tag == _NS + "row" and ev == "end":
                rows.append(cur)
                el.clear()
    return rows


def _split_situs(desc: str) -> tuple[str | None, str | None, str | None, str | None]:
    """'297 E MAIN ST FOREST CITY, NC 28043' -> (street, city, zip, None).

    A description that isn't an address ('B I COTTON MILLS LO176 SE2 PL6-59')
    comes back as (None, None, None, legal_description) so the lead still lands
    and still resolves through its parcel id.
    """
    s = (desc or "").strip()
    if not s:
        return None, None, None, None
    m = _ADDR_TAIL_RE.match(s)
    if not m:
        return None, None, None, s
    pre = m.group("pre").strip()
    # NCPTS writes 00000 when the bill has no zip on file — a placeholder, not a
    # zip. Letting it through would poison the addr+zip dedupe key.
    zipc = m.group("zip") if m.group("zip") != "00000" else None
    up = pre.upper()
    for city in _CITIES:
        if up.endswith(" " + city):
            street = pre[: -(len(city) + 1)].strip()
            if street:
                return street, city.title(), zipc, None
            break
    # Address-shaped but no recognised city: keep the whole thing as the street
    # rather than guessing a split, and keep the zip (which is unambiguous).
    return pre, None, zipc, None


def _report_meta(rows: list[dict[int, str]]) -> dict[str, str | None]:
    """Pull tax year + 'data as of' out of the TR-452 banner/parameter block."""
    meta: dict[str, str | None] = {"tax_year": None, "data_as_of": None}
    for row in rows[:12]:
        for idx in sorted(row):
            cell = (row.get(idx) or "").strip()
            if _TAX_YEAR_RE.match(cell):
                nxt = next((row[k] for k in sorted(row) if k > idx), "")
                meta["tax_year"] = (nxt or "").strip() or None
            m = _DATA_AS_OF_RE.search(cell)
            if m:
                meta["data_as_of"] = m.group(1).strip() or None
    return meta


def _parse_listings(data: bytes, slug: str, source_url: str) -> list[Listing]:
    zf = zipfile.ZipFile(BytesIO(data))
    sst = _read_shared_strings(zf)
    rows = _read_sheet_rows(zf, sst)
    meta = _report_meta(rows)

    # Aggregate by parcel: a handful of parcels carry more than one delinquent
    # bill (supplemental/deferred), and the board keys on parcel, so sum the
    # amounts into a single lead instead of emitting colliding duplicates.
    agg: dict[str, dict[str, Any]] = {}
    for row in rows:
        bill = (row.get(COL_BILL) or "").strip()
        if not _BILL_RE.match(bill):
            continue  # banner / params / header / Subtotal / Total / blank
        src_type = (row.get(COL_SOURCE_TYPE) or "").strip().upper()
        if src_type and src_type != "REI":
            continue  # real estate only; IND/BUS aren't real property
        parcel = (row.get(COL_PARCEL) or "").strip()
        if not parcel:
            continue
        owed = _money(row.get(COL_AMOUNT))
        if not owed:
            continue
        a = agg.setdefault(parcel, {"owed": 0.0, "bills": [], "row": row})
        a["owed"] += owed
        a["bills"].append(bill)
        # Prefer the richest description (an address beats a legal description).
        if _ADDR_TAIL_RE.match((row.get(COL_DESC) or "").strip()):
            a["row"] = row

    out: list[Listing] = []
    now = datetime.datetime.utcnow()
    for parcel, a in agg.items():
        row = a["row"]
        owed = round(a["owed"], 2)
        taxpayer = _clean(row.get(COL_TAXPAYER))
        desc_raw = (row.get(COL_DESC) or "").strip()
        street, city, zipc, legal = _split_situs(desc_raw)
        no_situs_number = bool(street and street.startswith("0 "))

        bits = [taxpayer or "Unknown owner",
                f"Rutherford NC delinquent tax ${owed:,.0f} owed",
                f"parcel {parcel}"]
        if meta.get("tax_year"):
            bits.append(f"TY{meta['tax_year']}")

        out.append(Listing(
            source=slug,
            source_url=source_url,
            listing_type=ListingType.TAX_LIEN,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county="Rutherford",
            parcel_id=parcel,
            street_address=street,
            city=city,
            zip_code=zipc,
            legal_description=legal,
            owner_name=taxpayer,
            defendant=taxpayer,
            # Amount owed as a first-class field (same convention as
            # counties_sc.horry_flc). NOT opening_bid — nothing is for sale yet,
            # and a bogus opening_bid would feed _flip_candidate.
            judgment_amount=owed,
            foreclosure_process="tax",
            description=" — ".join(bits)[:300],
            first_seen=now,
            last_seen=now,
            raw={"rutherford_tax": {
                "report": "TR-452 Delinquent Bills Report w/ Parcel Id",
                "parcel": parcel,
                "taxpayer": taxpayer,
                # back-tax OWED (summed across bills) -> tax_owed, NOT value
                "amount_owed": owed,
                "bill_numbers": sorted(set(a["bills"]))[:10],
                "bill_count": len(a["bills"]),
                "tax_year": meta.get("tax_year"),
                "data_as_of": meta.get("data_as_of"),
                "bill_description_raw": desc_raw or None,
                "no_situs_number": no_situs_number,
                "source_type": "REI",
                "dateless": True,  # a delinquent bill has no sale date
            }},
        ))
    return out


def _encode_spaces(url: str) -> str:
    """Percent-encode literal spaces in the PATH, leaving the query intact."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, quote(p.path, safe="/%"), p.query, p.fragment))


def _discover_xlsx_url(html: str, page_url: str = PAGE_URL) -> str:
    """Find the TR-452 delinquent-bills .xlsx link on the Revenue Dept page.

    Resolves against the page's ``<base href>`` when present — Revize declares
    ``<base href="https://www.rutherfordcountync.gov/" />``, so the bare
    filename in the anchor is SITE-ROOT relative, not department relative.
    Falls back to the known-good root path.
    """
    tree = HTMLParser(html)
    base_el = tree.css_first("base[href]")
    base = (base_el.attributes.get("href") if base_el else None) or page_url

    best = ""
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if ".xlsx" not in href.lower():
            continue
        blob = (href + " " + (a.text(strip=True) or "")).lower()
        if "tr-452" in blob or "delinquent" in blob:
            best = href
            break
    if not best:
        return _FALLBACK_XLSX
    return _encode_spaces(urljoin(base, best))


class RutherfordDelinquentTax(BaseScraper):
    slug = SLUG
    name = "Rutherford NC delinquent tax roll (county TR-452 .xlsx)"
    category = "county_tax"
    #: ~9.3k rows when posted. A drop below this after a good run means the
    #: county swapped/pulled the file or the sheet layout moved.
    expected_min_count = 100
    requires_apify = False
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        xlsx_url = _FALLBACK_XLSX
        try:
            html = await get_text(PAGE_URL, timeout=45.0)
            xlsx_url = _discover_xlsx_url(html)
        except Exception as exc:  # noqa: BLE001
            log.warning("rutherford_tax.page_fetch_failed", error=str(exc)[:160])

        try:
            data = await get_bytes(xlsx_url, timeout=120.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("rutherford_tax.xlsx_fetch_failed",
                        url=xlsx_url, error=str(exc)[:160])
            return []

        if data[:2] != b"PK":  # a 302-to-404 HTML body, not a workbook
            log.warning("rutherford_tax.not_xlsx", url=xlsx_url,
                        head=data[:8].hex(), bytes=len(data))
            return []

        try:
            out = _parse_listings(data, self.slug, xlsx_url)
        except Exception as exc:  # noqa: BLE001
            log.warning("rutherford_tax.parse_failed", error=str(exc)[:160])
            return []

        total = round(sum(li.judgment_amount or 0.0 for li in out), 2)
        log.info("rutherford_tax.done", count=len(out),
                 total_owed=total, url=xlsx_url)
        return out
