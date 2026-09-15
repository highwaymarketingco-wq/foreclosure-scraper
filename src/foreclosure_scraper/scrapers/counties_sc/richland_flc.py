"""Richland County SC Forfeited Land Commission (FLC) owned-property list.

Richland (Columbia, the state capital — SC's 2nd-largest county by
population) had exactly ONE board row before this scraper (a single
`counties.column_legal_notices` hit), despite a well-organized county site
with dedicated Tax-Sale, Forfeited-Land, and Master-in-Equity-Foreclosure
pages. Investigated all three live 2026-09-14:

  - Master-in-Equity Foreclosure Sales page: procedure text only, no linked
    roster of upcoming sales.
  - Tax-Sale page: links to richlandmaps.com/apps/delinquent, a Leaflet/
    WMS/UTFGrid "RCGeo Tax Sale Parcel Viewer" map app (found real backend
    endpoints in its JS: apps/api/RCGeoSearchData.php, a WMS tile layer, a
    per-tile UTFGrid hover-info plugin) -- genuinely promising (WMS is a
    documented, if verbose, protocol) but this is a map-first tool with no
    obvious bulk "list everything currently delinquent" endpoint found in a
    first pass. Left for a dedicated follow-up, not abandoned.
  - Forfeited-Land-Available page: links a live, current .xlsx
    (copy-of-flc-owned-property-8-5-2026.xlsx, dated ~5 weeks before this
    was written) -- THIS is what this scraper reads. Small (3 parcels as of
    2026-09-14: FLC inventory is inherently small/rolling), but real, free,
    and the same lead shape as counties_sc.horry_flc / counties_sc.sc_flc
    (county-held tax-sale-struck parcels, assignable over the counter).

FILE LAYOUT (live-verified 2026-09-14): single sheet, header row
"TAX MAP# | OWNER NAME | LOCATION | OPENING BID", 3 data rows, one stray
trailing cell (a lone number in column A with nothing else — a file
artifact, not a record: skipped because it has no owner/location/bid).
TAX MAP# carries a trailing hyphen exactly as published (e.g.
"01000-03-38-") -- kept verbatim rather than stripped, since that IS the
county's own parcel-number format for this file.

Downloaded via curl_cffi Chrome impersonation directly (not http_client's
get_bytes, which has no impersonation escalation and gets a flat 403 from
this WAF-fronted domain — the same domain's HTML pages already needed
get_text's impersonate=True to load at all).

xlsx parsing: no openpyxl dependency (same approach as horry_flc.py / HUD
Section-8 scraper) -- a .xlsx is a zip of XML, streamed with the stdlib
xml.etree.ElementTree.iterparse.

DATELESS: FLC parcels sell over-the-counter on a rolling basis, no auction
date. In main.py's DATELESS_OK_SOURCES.

Free, no login, no CAPTCHA/WAF bypass (impersonation only).
Slug: counties_sc.richland_flc
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import re
import zipfile
from datetime import datetime
from io import BytesIO
from typing import Iterable
from xml.etree.ElementTree import iterparse

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.richlandcountysc.gov/Property-Business/Taxes/Delinquent-Taxes/Forfeited-Land-Available"
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL_RE = re.compile(r"([A-Z]+)\d+")
_MONEY = re.compile(r"[\d,]+\.?\d*")


def _col_to_idx(cell_ref: str) -> int:
    m = _COL_RE.match(cell_ref or "A1")
    letters = m.group(1) if m else "A"
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
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
    sheet_name = next(
        (n for n in zf.namelist()
         if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")), None)
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
                    col = _col_to_idx(el.get("r"))
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
            elif tag == _NS + "row" and ev == "end":
                rows.append(cur)
                el.clear()
    return rows


def parse_flc_xlsx(data: bytes) -> list[dict]:
    """Parse the TAX MAP# | OWNER NAME | LOCATION | OPENING BID rows.

    Returns records only for rows carrying all four fields — the header row,
    title row, and any stray trailing artifact cell are naturally excluded.
    """
    zf = zipfile.ZipFile(BytesIO(data))
    sst = _read_shared_strings(zf)
    rows = _read_sheet_rows(zf, sst)

    records: list[dict] = []
    for row in rows:
        parcel = (row.get(0) or "").strip()
        owner = (row.get(1) or "").strip()
        location = (row.get(2) or "").strip()
        bid_raw = row.get(3)
        if not (parcel and owner and location and bid_raw is not None):
            continue
        if parcel.strip().upper() == "TAX MAP#":  # header row
            continue
        m = _MONEY.search(str(bid_raw))
        if not m:
            continue
        try:
            bid = float(m.group(0).replace(",", ""))
        except ValueError:
            continue
        records.append({"parcel": parcel, "owner": owner, "location": location, "opening_bid": bid})
    return records


class RichlandFLC(BaseScraper):
    slug = "counties_sc.richland_flc"
    name = "Richland County SC Forfeited Land Commission"
    category = "county_tax"
    timeout_s = 60.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("richland_flc.fetch_fail", error=str(exc)[:160])
            return out
        if not html:
            return out

        doc_url = None
        for m in re.finditer(r'href="([^"]*flc[^"]*\.xlsx)"', html, re.I):
            doc_url = m.group(1)
            break
        if not doc_url:
            log.warning("richland_flc.no_xlsx_link_found")
            return out
        if not doc_url.startswith("http"):
            doc_url = "https://www.richlandcountysc.gov" + doc_url

        try:
            from curl_cffi.requests import AsyncSession
            async with AsyncSession() as s:
                r = await s.get(doc_url, impersonate="chrome", timeout=40)
                r.raise_for_status()
                data = r.content
        except Exception as exc:
            log.warning("richland_flc.download_fail", url=doc_url, error=str(exc)[:160])
            return out

        try:
            records = parse_flc_xlsx(data)
        except Exception as exc:
            log.warning("richland_flc.parse_fail", error=str(exc)[:160])
            return out

        now = datetime.utcnow()
        for rec in records:
            out.append(Listing(
                source=self.slug,
                source_url=doc_url,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Richland",
                parcel_id=rec["parcel"],
                owner_name=rec["owner"],
                defendant=rec["owner"],
                street_address=rec["location"],
                opening_bid=rec["opening_bid"],
                description=(f"Richland County FLC-owned parcel {rec['parcel']} at "
                             f"{rec['location']}, opening bid ${rec['opening_bid']:,.2f}"),
                first_seen=now,
                last_seen=now,
                raw={"richland_flc": {"opening_bid": rec["opening_bid"]}},
            ))

        log.info("richland_flc.done", count=len(out))
        return out
