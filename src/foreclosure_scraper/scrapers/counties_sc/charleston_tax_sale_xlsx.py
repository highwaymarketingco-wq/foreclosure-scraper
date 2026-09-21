"""Charleston County SC tax-sale listing, read from the county's published spreadsheets.

WHY A SECOND CHARLESTON TAX SCRAPER
    counties_sc.charleston_delinquent_tax reads the same list from a PDF with pdfplumber. The
    county also posts it as .xlsx, which is the machine-readable form, and the research pass
    (docs/county_breadth_research_2026-09-21.md) measured the difference: the sheet holds 2,416
    real-property rows, the PDF reader parsed 834 in August and the board carries 1,125.
    Both write the same parcel key (the 10-digit PIN), so a row present in both merges on the
    board instead of doubling. This scraper does not replace the PDF one.

THE FILES (read live 2026-09-21, HTTP 200, 221 KB and 134 KB)
    https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/RP-Tax-Sale-Listing.xlsx
    https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/MH-Tax-Sale-Listing.xlsx
    linked from https://www.charlestoncounty.gov/departments/delinquent-tax/ .

    Row 0 is a title cell that carries the sale date ("... the day of the tax sale, Monday,
    November 9, 2026"), row 1 is the header, the data follows.
      RP  PIN | CLASS CODE | OWNER | SITUS ADDRESS | CITY | TAG | ACREAGE | TOTAL DUE | APPRAISAL
      MH  PIN | TAG | OWNER 1 | OWNER 2 | DESCRIPTION | SITUS ADDRESS | CITY | APPRAISAL | TOTAL DUE
    (RP 2,416 rows, MH 1,224 rows.) Columns are bound by header name, so a reordering does not
    misread money as acreage.

PRIVACY
    The workbook holds owner names. It is downloaded into memory, parsed, and dropped: nothing
    is written to disk by this module and nothing from a sheet is stored in the repository.

WHAT IS EMITTED
    A row is TAX_SALE with the sale date from the title cell (a real, dated sale), or TAX_LIEN
    if the title carries no date. `opening_bid` is TOTAL DUE, which the county says excludes
    current-year taxes, so it is a floor. Mobile homes are PropertyKind.MOBILE.

Free, no login, no CAPTCHA, ordinary GET.
Slug: counties_sc.charleston_tax_sale_xlsx
Category: county_tax
ListingType: TAX_SALE (dated) / TAX_LIEN (undated)
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

SLUG = "counties_sc.charleston_tax_sale_xlsx"
LANDING = "https://www.charlestoncounty.gov/departments/delinquent-tax/"
FALLBACK_XLSX = (
    "https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/RP-Tax-Sale-Listing.xlsx",
    "https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/MH-Tax-Sale-Listing.xlsx",
)

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_SALE_DATE = re.compile(
    r"(?:tax\s+sale[^.]{0,40}?,\s*)?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(20\d{2})", re.I)
_HOUSE = re.compile(r"^\d{1,6}[A-Z]?\s+\S")
_RP_PIN = re.compile(r"^\d{8,12}$")
_MH_PIN = re.compile(r"^MH\d{4,}$", re.I)

_KIND_BY_CLASS = (
    ("sfr", PropertyKind.SINGLE_FAMILY), ("dup", PropertyKind.MULTI_FAMILY),
    ("tri", PropertyKind.MULTI_FAMILY), ("apt", PropertyKind.MULTI_FAMILY),
    ("condo", PropertyKind.CONDO), ("comm", PropertyKind.COMMERCIAL),
    ("vac", PropertyKind.LAND), ("lot", PropertyKind.LAND),
    ("undevelop", PropertyKind.LAND), ("road", PropertyKind.LAND), ("mh", PropertyKind.MOBILE),
)


def _kind(classcd: str, is_mh: bool) -> PropertyKind:
    if is_mh:
        return PropertyKind.MOBILE
    low = (classcd or "").lower()
    for needle, kind in _KIND_BY_CLASS:
        if needle in low:
            return kind
    return PropertyKind.UNKNOWN


def _money(v: str) -> float | None:
    s = re.sub(r"[^\d.]", "", v or "")
    if not s or s == ".":
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _clean(v: str | None) -> str | None:
    out = " ".join((v or "").split())
    return out or None


def sale_date_from_title(rows: list[list[str]]) -> datetime | None:
    """The sale date sits in the free-text title cell above the header."""
    for row in rows[:3]:
        for c in row:
            m = _SALE_DATE.search(" ".join((c or "").split()))
            if m:
                try:
                    return datetime(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
                except (ValueError, KeyError):
                    return None
    return None


def parse_workbook(data: bytes, source_url: str, *, is_mh: bool | None = None) -> list[Listing]:
    """One Listing per PIN row of a Charleston RP or MH tax-sale workbook."""
    rows = read_rows(data)
    hit = header_index(rows, ("pin", "owner"))
    if hit is None:
        raise ValueError("no header row with PIN and OWNER in the first 30 rows")
    hdr_i, cols = hit
    if is_mh is None:
        is_mh = "mh-tax" in source_url.lower()

    def col(*names: str) -> int | None:
        for n in names:
            if n in cols:
                return cols[n]
        for n in names:
            for k, v in cols.items():
                if n in k:
                    return v
        return None

    c_pin = col("pin")
    c_o1 = col("owner 1", "owner")
    c_o2 = col("owner 2")
    c_situs = col("situs address", "situs")
    c_city = col("city")
    c_class = col("class code")
    c_tag = col("tag")
    c_acre = col("acreage")
    c_due = col("total due")
    c_appr = col("appraisal")
    c_desc = col("description")

    sale = sale_date_from_title(rows)
    now = datetime.utcnow()
    out: list[Listing] = []
    seen: set[str] = set()
    for row in rows[hdr_i + 1:]:
        pin = re.sub(r"\s+", "", cell(row, c_pin))
        if not (_RP_PIN.match(pin) or _MH_PIN.match(pin)):
            continue
        if pin in seen:
            continue
        seen.add(pin)
        row_mh = is_mh or bool(_MH_PIN.match(pin))
        owner = " ".join(x for x in (_clean(cell(row, c_o1)), _clean(cell(row, c_o2))) if x) or None
        situs = _clean(cell(row, c_situs))
        city = _clean(cell(row, c_city))
        classcd = _clean(cell(row, c_class))
        total_due = _money(cell(row, c_due))
        appraisal = _money(cell(row, c_appr))
        acreage = _money(cell(row, c_acre))
        mh_desc = _clean(cell(row, c_desc)) if row_mh else None
        street = situs if (situs and _HOUSE.match(situs)) else None
        # Same raw KEY as the PDF scraper (counties_sc.charleston_delinquent_tax) and the same
        # field names for the shared ones, on purpose: it is the same county list, the two merge
        # on the PIN, and web_artifact.RAW_KEEP already publishes this key. A new key name would
        # be dropped at publish until someone added it to that allowlist.
        block = {
            "pin": pin, "kind": "mobile_home" if row_mh else "real_property",
            "owner": owner, "total_due": total_due, "appraisal": appraisal, "acreage": acreage,
            "classcd": classcd, "tag": _clean(cell(row, c_tag)), "situs_text": situs,
            "mh_description": mh_desc, "dateless": sale is None,
            "sale_date": sale.date().isoformat() if sale else None,
            "list_xlsx": source_url,
        }
        raw: dict = {"charleston_delinquent_tax": block}
        if total_due:
            raw["tax_owed"] = {"balance": total_due, "kind": "delinquent_tax", "source": SLUG,
                               "year": sale.year - 1 if sale else None, "basis": "own_record"}
        bits = [f"Charleston SC tax-sale parcel (PIN {pin})"]
        if classcd:
            bits.append(classcd)
        if mh_desc:
            bits.append(mh_desc)
        if total_due is not None:
            bits.append(f"delinquent ${total_due:,.2f}")
        out.append(Listing(
            source=SLUG,
            source_url=source_url,
            listing_type=ListingType.TAX_SALE if sale else ListingType.TAX_LIEN,
            property_kind=_kind(classcd or "", row_mh),
            state="SC", county="Charleston",
            street_address=street,
            legal_description=None if street else situs,
            city=city,
            parcel_id=pin,
            owner_name=owner, defendant=owner,
            opening_bid=total_due,
            market_value=appraisal,
            acreage=acreage,
            sale_date=sale,
            foreclosure_process="tax",
            description=" | ".join(bits)[:300],
            first_seen=now, last_seen=now, raw=raw,
        ))
    return out


def discover_urls(html: str) -> list[str]:
    """The RP and MH .xlsx links from the landing page, in that order."""
    found = re.findall(r'href=["\']([^"\']+tax_sale/(?:RP|MH)-Tax-Sale-Listing\.xlsx[^"\']*)["\']',
                       html or "", re.I)
    urls: list[str] = []
    for h in found:
        u = urljoin(LANDING, h.replace("&amp;", "&"))
        if u not in urls:
            urls.append(u)
    return sorted(urls, key=lambda u: 0 if "/RP-" in u else 1)


class CharlestonTaxSaleXlsx(BaseScraper):
    slug = SLUG
    name = "Charleston County SC tax-sale listing (RP + MH .xlsx)"
    category = "county_tax"
    timeout_s = 240.0
    expected_min_count = 0
    optional = True

    #: A sample run (the ingest script's dry run) keeps the first N rows.
    limit: int | None = None

    async def fetch(self) -> Iterable[Listing]:
        urls: list[str] = []
        try:
            html = await get_text(LANDING, headers={"User-Agent": "Mozilla/5.0"}, timeout=45.0)
            urls = discover_urls(html)
        except Exception as exc:  # noqa: BLE001
            log.warning("charleston_xlsx.landing_fail", error=str(exc)[:160])
        for u in FALLBACK_XLSX:
            if u.split("?", 1)[0] not in [x.split("?", 1)[0] for x in urls]:
                urls.append(u)
        out: list[Listing] = []
        seen: set[str] = set()
        for url in urls:
            try:
                data = await get_bytes(url, timeout=120.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("charleston_xlsx.fetch_fail", url=url, error=str(exc)[:160])
                continue
            try:
                rows = parse_workbook(data, url)
            except Exception as exc:  # noqa: BLE001
                log.warning("charleston_xlsx.parse_fail", url=url, error=str(exc)[:160])
                continue
            for li in rows:
                if li.parcel_id in seen:
                    continue
                seen.add(li.parcel_id)
                out.append(li)
                if self.limit and len(out) >= self.limit:
                    break
            log.info("charleston_xlsx.parsed", url=url, rows=len(rows))
            if self.limit and len(out) >= self.limit:
                break
        return out
