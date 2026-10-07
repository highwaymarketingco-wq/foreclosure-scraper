"""Mecklenburg County NC advertisement of unpaid tax liens (NCGS 105-369), as XLSX.

Source
------
https://tax.mecknc.gov/Delinquent-Taxpayer-Lists links four files hosted on the
county's Widen asset library (mecknc.widen.net). Two of them are the statutory
advertisement of unpaid taxes that are liens on real property:

    Delinquent Individual Taxpayers  https://mecknc.widen.net/s/vb8vhrwvtm/ind_taxbills_advertisement
    Delinquent Business Taxpayers    https://mecknc.widen.net/s/slsnqr9prl/busoth_taxbills_advertisement

Each share page is a PDF viewer whose own "Download" link (``/content/<id>/original/
<name>.xlsx?...&download=true``) serves the ORIGINAL workbook, so the rows come
straight from the spreadsheet with no PDF parsing. Read live 2026-10-07: the
individual workbook (sheet ``IND_ADVERTISEMENT_REGULAR_03-12``, workbook created
2026-03-12) holds 28,515 rows of four columns -- taxpayer name, property address,
"$", amount; the business workbook (``BUS_ADVERTISEMENT_REGULAR_03-12``) holds
14,840 more in the same shape. Together: 43,355 rows, tax year 2025, $35.5M due,
9,058 rows at $1,000 or more.
The addresses are property locations, not mailing addresses (22,819 Charlotte, the
rest Huntersville, Cornelius, Matthews, Mint Hill, Pineville, Davidson or
unincorporated "MECKLENBURG"; only a handful carry a ZIP outside the county).
Individual-list amounts: median $155, 6,464 rows at $1,000 or more, about $20.0M.

The other two files on the page are not read here: "Top 100 Delinquent Taxpayers"
(monthly, mixed real and business personal property) and the 1,087-page
"Delinquent Taxpayer Publication" PDF (all delinquent bills, mostly personal
property) that docs/county_breadth_research_2026-09-21.md looked at.

Why it matters: Mecklenburg is the largest county in NC and had no tax-delinquency
source in the repo. A 105-369 advertisement is the legal notice that a tax lien is
about to be enforced; it is the earliest county-wide tax-distress list there is.
There is no parcel number in the file, so rows carry the situs and the downstream
resolver joins them to parcels. Rows are kept whatever the amount ("rank, don't
filter"); ``total_due`` lets scoring sort the large balances to the top.

Access: open, no login, no CAPTCHA (the Widen share page and the original file are
public links the county publishes). Four GETs per run. Nothing is written to disk.

Gate with FORECLOSURE_MECKLENBURG_DELINQUENT=0 to skip.
"""
from __future__ import annotations

import html
import os
import re
import zipfile
from datetime import datetime
from io import BytesIO
from typing import Any, Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from .._xlsx_stdlib import read_rows

log = structlog.get_logger()

INDEX_PAGE = "https://tax.mecknc.gov/Delinquent-Taxpayer-Lists"
WIDEN_HOST = "https://mecknc.widen.net"
#: (list kind, Widen share URL). The share URLs are what the county links from
#: INDEX_PAGE; the download path inside each share page changes when the county
#: uploads a new year's file, so it is read fresh every run.
LISTS: tuple[tuple[str, str], ...] = (
    ("individual", f"{WIDEN_HOST}/s/vb8vhrwvtm/ind_taxbills_advertisement"),
    ("business", f"{WIDEN_HOST}/s/slsnqr9prl/busoth_taxbills_advertisement"),
)
ENV_OFF = "FORECLOSURE_MECKLENBURG_DELINQUENT"

_DOWNLOAD_RE = re.compile(r'href="(/content/[^"]+?\.xlsx\?[^"]*download=true)"', re.I)

#: Postal cities that appear at the end of the address column, longest first so
#: "MINT HILL" wins over a shorter token. "MECKLENBURG" marks unincorporated land
#: (no postal city), so it is stripped and the city left blank.
_CITIES = ("HUNTERSVILLE", "MECKLENBURG", "CHARLOTTE", "CORNELIUS", "MATTHEWS",
           "MINT HILL", "PINEVILLE", "DAVIDSON", "STALLINGS", "CONCORD",
           "HARRISBURG", "INDIAN TRAIL")
_CITY_RE = re.compile(r"\s+(" + "|".join(sorted((re.escape(c) for c in _CITIES),
                                                key=len, reverse=True)) + r")\s*$", re.I)
_STATE_ZIP_RE = re.compile(r"\s+(?:NC|SC)\s+(\d{5})(?:-\d{4})?\s*$", re.I)
_MONEY_RE = re.compile(r"^\$?\s*-?[\d,]+(?:\.\d+)?$")


def download_path(share_html: str) -> str | None:
    """The workbook's own download link from a Widen share page, or None."""
    m = _DOWNLOAD_RE.search(share_html or "")
    return html.unescape(m.group(1)) if m else None


def split_address(text: str | None) -> tuple[str | None, str | None, str | None]:
    """'1511 ODESSA AV CHARLOTTE NC 28216' -> ('1511 ODESSA AV', 'CHARLOTTE', '28216').

    Trailing 'NC 28xxx' is optional in the file; so is the city. 'MECKLENBURG' is the
    file's word for unincorporated land and becomes city None."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return None, None, None
    zip_code = None
    m = _STATE_ZIP_RE.search(s)
    if m:
        zip_code = m.group(1)
        s = s[: m.start()].strip()
    city = None
    m = _CITY_RE.search(s)
    if m and m.start() > 0:
        city = m.group(1).upper()
        s = s[: m.start()].strip()
        if city == "MECKLENBURG":
            city = None
    if zip_code == "00000":
        zip_code = None
    return (s or None), city, zip_code


def _money(v: Any) -> float | None:
    t = str(v or "").strip()
    if not t or not _MONEY_RE.match(t):
        return None
    try:
        f = float(t.replace("$", "").replace(",", "").strip())
    except ValueError:
        return None
    return f if f > 0 else None


def workbook_meta(data: bytes) -> dict[str, str | None]:
    """First sheet name and the workbook's created date (docProps/core.xml)."""
    out: dict[str, str | None] = {"sheet": None, "created": None}
    try:
        zf = zipfile.ZipFile(BytesIO(data))
        if "xl/workbook.xml" in zf.namelist():
            m = re.search(rb'<sheet[^>]*\bname="([^"]+)"', zf.read("xl/workbook.xml"))
            out["sheet"] = html.unescape(m.group(1).decode("utf-8", "replace")) if m else None
        if "docProps/core.xml" in zf.namelist():
            m = re.search(rb"<dcterms:created[^>]*>([^<]+)<", zf.read("docProps/core.xml"))
            out["created"] = m.group(1).decode()[:10] if m else None
    except (zipfile.BadZipFile, KeyError):
        pass
    return out


def parse_rows(rows: list[list[str]]) -> list[dict[str, Any]]:
    """Workbook rows -> [{owner, address, total_due}]. Header and blank rows drop out
    because they carry no amount."""
    out: list[dict[str, Any]] = []
    for r in rows:
        cells = [str(c or "").strip() for c in r]
        if len(cells) < 2:
            continue
        owner = re.sub(r"\s+", " ", cells[0]).strip()
        address = re.sub(r"\s+", " ", cells[1]).strip()
        amount = None
        for c in reversed(cells[2:]):
            amount = _money(c)
            if amount is not None:
                break
        if not owner or amount is None:
            continue
        out.append({"owner": owner, "address": address or None, "total_due": amount})
    return out


def build_listing(rec: dict[str, Any], *, kind: str, share_url: str,
                  meta: dict[str, str | None], now: datetime) -> Listing:
    street, city, zip_code = split_address(rec.get("address"))
    amt = rec["total_due"]
    created = meta.get("created")
    tax_year = None
    if created and re.match(r"^\d{4}-", created):
        # The 105-369 advertisement runs in spring for the PRIOR year's unpaid bills.
        tax_year = int(created[:4]) - 1
    owner = rec["owner"]
    return Listing(
        source=MecklenburgDelinquentTax.slug,
        source_url=share_url,
        listing_type=ListingType.TAX_LIEN,
        property_kind=PropertyKind.UNKNOWN,
        owner_name=owner,
        defendant=owner,
        street_address=street,
        city=city,
        zip_code=zip_code,
        state="NC",
        county="Mecklenburg",
        foreclosure_process="tax",
        description=(f"Mecklenburg NC advertisement of unpaid tax liens (NCGS 105-369, "
                     f"{kind} list): ${amt:,.2f} owed")[:300],
        first_seen=now,
        last_seen=now,
        raw={"mecklenburg_delinquent_tax": {
            "county": "Mecklenburg",
            "list": kind,
            "total_due": amt,
            "tax_year": tax_year,
            "address_as_listed": rec.get("address"),
            "advertisement_sheet": meta.get("sheet"),
            "file_created": created,
            "index_page": INDEX_PAGE,
            "signal": "tax_lien_advertisement",
        }},
    )


class MecklenburgDelinquentTax(BaseScraper):
    slug = "counties_nc.mecklenburg_delinquent_tax"
    name = "Mecklenburg County (NC) Advertisement of Unpaid Tax Liens (XLSX)"
    category = "tax_delinquent"
    timeout_s = 240.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("mecklenburg_delinquent.disabled")
            return []
        now = datetime.utcnow()
        out: list[Listing] = []
        async with client(timeout=90.0) as http:
            for kind, share_url in LISTS:
                try:
                    page = await http.get(share_url)
                except Exception as exc:  # noqa: BLE001
                    log.warning("mecklenburg_delinquent.share_failed", kind=kind, error=str(exc)[:160])
                    continue
                if page.status_code != 200:
                    log.warning("mecklenburg_delinquent.share_status", kind=kind, status=page.status_code)
                    continue
                path = download_path(page.text)
                if not path:
                    log.warning("mecklenburg_delinquent.no_download_link", kind=kind)
                    continue
                try:
                    resp = await http.get(WIDEN_HOST + path)
                except Exception as exc:  # noqa: BLE001
                    log.warning("mecklenburg_delinquent.download_failed", kind=kind, error=str(exc)[:160])
                    continue
                if resp.status_code != 200 or resp.content[:2] != b"PK":
                    log.warning("mecklenburg_delinquent.not_xlsx", kind=kind, status=resp.status_code)
                    continue
                meta = workbook_meta(resp.content)
                recs = parse_rows(read_rows(resp.content))
                for rec in recs:
                    out.append(build_listing(rec, kind=kind, share_url=share_url, meta=meta, now=now))
                log.info("mecklenburg_delinquent.parsed", kind=kind, rows=len(recs),
                         sheet=meta.get("sheet"), created=meta.get("created"))
        return out


if __name__ == "__main__":
    import asyncio
    from collections import Counter

    async def _main() -> None:
        s = MecklenburgDelinquentTax()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        blocks = [li.raw["mecklenburg_delinquent_tax"] for li in rows]
        print(Counter(b["list"] for b in blocks).most_common())
        print("tax_year", Counter(b["tax_year"] for b in blocks).most_common(3))
        print("with_street", sum(1 for li in rows if li.street_address),
              "with_city", sum(1 for li in rows if li.city),
              "with_zip", sum(1 for li in rows if li.zip_code),
              "due_ge_1000", sum(1 for b in blocks if b["total_due"] >= 1000),
              "total_due", round(sum(b["total_due"] for b in blocks)))

    asyncio.run(_main())
