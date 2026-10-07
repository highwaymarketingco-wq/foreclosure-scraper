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

PARCEL RESOLUTION AND RUN COST (2026-10-07). The workbook has no parcel number, and
the board's geocode step (Census batch, 250 rows a chunk, about 1,000 rows per 25 s;
then a 1-per-second tier capped by GEOCODE_BUDGET_S) would see every row. So before a
row is emitted its street is matched, locally and in one pass, against the Mecklenburg
parcel cache (data/parcel_cache/mecklenburg.sqlite, the NC OneMap snapshot
parcel_cache.py already builds; no network). Measured on the live workbooks: 43,355
rows, 41,574 with a house-numbered street, 29,152 (67.2%) resolve to exactly one parcel
in about 2 s, 1,273 match more than one parcel (condos, no unit) and 12,930 match none.
The cache carries no coordinates, so a resolved row still needs a map point.

Defaults, because the geocode cost is not bounded by this module: the scraper is OFF
unless FORECLOSURE_MECKLENBURG_DELINQUENT=1, and when on it emits only parcel-resolved
rows (MECKLENBURG_DELINQUENT_RESOLVED_ONLY=0 adds the unresolved ones). Separately, the
rows carry no sale date, so main.DATELESS_OK_SOURCES needs this slug before any of them
survives the board's active filter.
"""
from __future__ import annotations

import html
import os
import re
import sqlite3
import time
import zipfile
from datetime import datetime
from io import BytesIO
from typing import Any, Iterable

import structlog

from ... import parcel_cache
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
ENV_ON = "FORECLOSURE_MECKLENBURG_DELINQUENT"          # "1" turns the scraper on (default off)
ENV_RESOLVED_ONLY = "MECKLENBURG_DELINQUENT_RESOLVED_ONLY"   # default "1": parcel-resolved rows only

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


_SUFFIX = {"AVENUE": "AV", "AVE": "AV", "STREET": "ST", "ROAD": "RD", "DRIVE": "DR", "LANE": "LN",
           "COURT": "CT", "CIRCLE": "CIR", "CR": "CIR", "PLACE": "PL", "BOULEVARD": "BLVD", "BV": "BLVD",
           "HIGHWAY": "HWY", "PARKWAY": "PKWY", "PY": "PKWY", "TRAIL": "TRL", "TL": "TRL", "TR": "TRL",
           "TERRACE": "TER", "WY": "WAY"}


def street_key(street: str | None) -> str | None:
    """Comparable form of a street line: upper case, no unit, suffixes abbreviated."""
    s = re.sub(r"\s+", " ", (street or "").upper()).strip().split(",")[0].strip()
    if not s:
        return None
    return " ".join(_SUFFIX.get(t, t) for t in s.split())


def street_variants(street: str | None) -> list[str]:
    """The workbook sometimes prints a unit number before the house number
    ('9325 200 EXAMPLE DR'); try the line as printed, then each number alone."""
    k = street_key(street)
    if not k or not re.match(r"^[1-9]\d*\b", k):
        return []
    out = [k]
    t = k.split()
    if len(t) >= 3 and t[0].isdigit() and t[1].isdigit():
        out += [" ".join(t[1:]), " ".join([t[0]] + t[2:])]
    return out


def cache_street_key(address: str | None) -> str | None:
    """Parcel-cache situs ('1511 EXAMPLE AV CHARLOTTE NC', '1000 E EX RD, 203 CHARLOTTE NC')
    -> the same comparable form as street_key()."""
    s = re.sub(r"\s+", " ", (address or "").upper()).strip().split(",")[0].strip()
    s = re.sub(r"\s+NC$", "", s)
    m = _CITY_RE.search(s)
    if m and m.start() > 0:
        s = s[: m.start()]
    return street_key(s)


def resolve_parcels(streets: list[str | None], db_path) -> tuple[list[tuple[str | None, str]], dict]:
    """Match each street to one Mecklenburg parcel id, locally, in one table scan.

    Returns ([(parcel_id or None, status)], stats) with status 'resolved', 'ambiguous',
    'unresolved' or 'no_street'. Only the 8-digit Mecklenburg parcel number is used as
    the id (the cache also stores 13-digit statewide variants of the same parcel)."""
    variants = [street_variants(s) for s in streets]
    need = {v for vs in variants for v in vs}
    index: dict[str, set[str]] = {}
    t0 = time.monotonic()
    if need and db_path and os.path.exists(str(db_path)):
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            for pid, addr in con.execute(
                    "SELECT id, address FROM parcels WHERE address IS NOT NULL AND address != ''"):
                if not pid or len(pid) != 8:
                    continue
                k = cache_street_key(addr)
                if k in need:
                    index.setdefault(k, set()).add(pid)
        finally:
            con.close()
    out: list[tuple[str | None, str]] = []
    for vs in variants:
        if not vs:
            out.append((None, "no_street"))
            continue
        hit: tuple[str | None, str] = (None, "unresolved")
        for v in vs:
            ids = index.get(v)
            if ids and len(ids) == 1:
                hit = (next(iter(ids)), "resolved")
                break
            if ids:
                hit = (None, "ambiguous")
                break
        out.append(hit)
    stats = dict(rows=len(streets), scan_s=round(time.monotonic() - t0, 2),
                 cache_present=bool(db_path and os.path.exists(str(db_path))))
    for _, status in out:
        stats[status] = stats.get(status, 0) + 1
    return out, stats


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
                  meta: dict[str, str | None], now: datetime,
                  parcel: tuple[str | None, str] = (None, "not_attempted"),
                  cache_age_days: float | None = None) -> Listing:
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
        parcel_id=parcel[0],
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
            "parcel_resolution": parcel[1],
            "parcel_resolution_source": "parcel_cache:mecklenburg (street match)",
            "parcel_cache_age_days": round(cache_age_days, 1) if cache_age_days is not None else None,
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
        if os.environ.get(ENV_ON, "0").strip() != "1":
            log.info("mecklenburg_delinquent.off_by_default", enable=f"{ENV_ON}=1")
            return []
        now = datetime.utcnow()
        out: list[Listing] = []
        parsed: list[tuple[dict[str, Any], str, str, dict[str, str | None]]] = []
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
                parsed += [(rec, kind, share_url, meta) for rec in recs]
                log.info("mecklenburg_delinquent.parsed", kind=kind, rows=len(recs),
                         sheet=meta.get("sheet"), created=meta.get("created"))
        db = parcel_cache._db_path("Mecklenburg")
        matches, stats = resolve_parcels([split_address(r[0].get("address"))[0] for r in parsed], db)
        age = parcel_cache.cache_age_days("Mecklenburg")
        resolved_only = os.environ.get(ENV_RESOLVED_ONLY, "1").strip() != "0"
        for (rec, kind, share_url, meta), parcel in zip(parsed, matches):
            if resolved_only and parcel[1] != "resolved":
                continue
            out.append(build_listing(rec, kind=kind, share_url=share_url, meta=meta, now=now,
                                     parcel=parcel, cache_age_days=age))
        log.info("mecklenburg_delinquent.resolved", emitted=len(out), resolved_only=resolved_only,
                 cache_age_days=round(age, 1) if age is not None else None, **stats)
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
        print("tax_year", Counter(b["tax_year"] for b in blocks).most_common(3),
              "resolution", Counter(b["parcel_resolution"] for b in blocks).most_common())
        print("with_street", sum(1 for li in rows if li.street_address),
              "with_city", sum(1 for li in rows if li.city),
              "with_zip", sum(1 for li in rows if li.zip_code),
              "due_ge_1000", sum(1 for b in blocks if b["total_due"] >= 1000),
              "total_due", round(sum(b["total_due"] for b in blocks)))

    asyncio.run(_main())
