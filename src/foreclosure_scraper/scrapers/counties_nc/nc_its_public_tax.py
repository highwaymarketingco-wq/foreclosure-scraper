"""NC county delinquent property-tax rolls from the "ITSPublic" tax-bill portals.

Onslow and Graham publish their tax bills through the same vendor application (an ASP.NET
site, `/ITSPublic<XX>/TaxBillSearch`, with a jqGrid results table). It needs no login, no
CAPTCHA and no terms click-through; the search page just sets an ASP.NET session cookie.

    Onslow   https://tax.onslowcountync.gov/ITSPublicON/TaxBillSearch      7,428 unpaid 2025 bills
    Graham   https://www.bttaxpayerportal.com/ITSPublicGR2.0/TaxBillSearch   925 unpaid 2025 bills

(Both counts read live 2026-09-21. Onslow had 1,402 board rows and 14% parcel coverage;
Graham had 14. Jones runs the same product at ITSPublicJN2.0 but returned an empty body and
a 500 in the research pass, so it is not configured.)

THE CALL SEQUENCE (verified live 2026-09-21, six requests over both counties)
    1. GET  {base}/TaxBillSearch                     -> ASP.NET_SessionId cookie
    2. POST {base}/TaxBillSearch/GetSearchTablePartial
            {"PageSize": 100, "UnpaidBillsOnly": true, "TaxYear": "2025"}
            -> an HTML fragment; its real job is to store the search in the SESSION
    3. POST {base}/TaxBillSearch/GetSearchTableData
            {"Page": n, "NumRows": 100, "Table": "PayTaxBills"}
            -> {"total": 75, "numRecords": 7428, "rows": [{"id": "2025/72", "cell": [...]}]}
    NumRows is honoured up to at least 100 (the UI defaults to 25), which turns Onslow's
    298 pages into 75. The search state lives in the session, so pages are requested one
    at a time on one cookie, 1.5 s apart.

A ROW'S CELLS (the header ids in the fragment are TaxYear, BillNumber, AccountNumber,
AccountName1, Description, OriginalBillAmount, TotalDue):
    ["2025", "72", "496055000", "<OWNER>", "<description html>", "2,205.73", "2,387.48", "<button>"]
The description is `<br/>`-separated:
    Onslow  bill# (zero padded) | parcel | situs with city, state, zip | "0.150 AC"
    Graham  parcel | (alternate id) | situs | "0.280 AC"
Real property always ends in an acreage or unit count ("AC", "LT", "UT"); personal property
and vehicles do not, and are dropped (the research note: "Onslow mixes personal property in").

WHAT IS EMITTED
    One TAX_LIEN lead per PARCEL, the unpaid years summed. NC's delinquency date for tax year
    Y is January 6 of Y+1, so the latest delinquent year is (this year - 1); a 2026 bill
    issued this summer is current, not delinquent, and is never requested. Three delinquent
    years are read by default (ITS_TAX_YEARS_BACK). Balance (TotalDue) already includes
    interest. No mailing address is on the list rows; the parcel joins the NC OneMap cache
    (`parno`) for mail and value.

Slug: counties_nc.nc_its_public_tax
Category: county_tax
ListingType: TAX_LIEN (a standing roll; there is no sale date on these rows)
"""
from __future__ import annotations

import asyncio
import html as _html
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_nc.nc_its_public_tax"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

PAGE_ROWS = 100
PACE_S = float(os.getenv("ITS_TAX_PACE_S", "1.5"))
YEARS_BACK = int(os.getenv("ITS_TAX_YEARS_BACK", "3"))
MAX_PAGES_PER_YEAR = 400          # a stall guard: Onslow's 2025 is 75 pages


@dataclass(frozen=True)
class ITSPortal:
    county: str
    base: str                     # .../ITSPublicXX (no trailing slash, no /TaxBillSearch)
    #: Place names that end a situs line, longest first. Graham's situs carries no city.
    cities: tuple[str, ...] = ()


PORTALS: dict[str, ITSPortal] = {
    "Onslow": ITSPortal(
        "Onslow", "https://tax.onslowcountync.gov/ITSPublicON",
        cities=("NORTH TOPSAIL BEACH", "TOPSAIL BEACH", "SNEADS FERRY", "HOLLY RIDGE",
                "MIDWAY PARK", "PINEY GREEN", "MAPLE HILL", "CAMP LEJEUNE", "STUMP SOUND",
                "SURF CITY", "JACKSONVILLE", "SWANSBORO", "RICHLANDS", "MAYSVILLE",
                "HAMPSTEAD", "POLLOCKSVILLE", "WILMINGTON", "BELGRADE", "FOLKSTONE",
                "VERONA", "HUBERT", "COMFORT", "TAR HEEL")),
    "Graham": ITSPortal("Graham", "https://www.bttaxpayerportal.com/ITSPublicGR2.0"),
}


def delinquent_years(today: date | None = None, back: int | None = None) -> list[int]:
    """Tax years that are past their delinquency date, newest first.

    NC: year Y's taxes are delinquent from January 6 of Y+1. In the first five days of a
    year the newest delinquent year is still two back.
    """
    today = today or date.today()
    latest = today.year - 1
    if today.month == 1 and today.day < 6:
        latest -= 1
    n = YEARS_BACK if back is None else back
    return [latest - i for i in range(max(1, n))]


# --------------------------------------------------------------------------- parsing

_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.I)
_ACRES = re.compile(r"^(\d+(?:\.\d+)?)\s*(AC|LT|UT|SF|SQFT)$", re.I)
_ZIP = re.compile(r"\s+(\d{5})(?:-\d{4})?$")
_STATE = re.compile(r"\s+NC$")
_HOUSE = re.compile(r"^\d{1,6}[A-Z]?\s+\S")
_SUFFIX = {"ST", "STREET", "RD", "ROAD", "DR", "DRIVE", "LN", "LANE", "CT", "COURT", "CIR",
           "CIRCLE", "AVE", "AVENUE", "BLVD", "HWY", "HIGHWAY", "WAY", "TRL", "TRAIL", "PL",
           "PLACE", "PKWY", "PARKWAY", "LOOP", "TER", "TERRACE", "CV", "COVE", "RUN", "PT",
           "PIKE", "XING", "SQ", "BND", "PATH", "ROW", "EXT", "ALY", "TRCE", "PASS"}


def _text(cell: str) -> str:
    return " ".join(_html.unescape(_TAG.sub(" ", cell or "")).split())


def _money(v) -> float | None:
    s = re.sub(r"[^\d.]", "", str(v or ""))
    if not s or s == ".":
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def parse_description(desc_html: str, bill_no: str, cities: tuple[str, ...] = ()) -> dict | None:
    """Split a Description cell. None when it is not real property (no acreage / unit
    count on the last line, or no parcel-shaped id)."""
    parts = [_text(p) for p in _BR.split(desc_html or "")]
    # Onslow prefixes the zero-padded bill number; Graham does not.
    if parts and parts[0].isdigit() and bill_no.isdigit() and int(parts[0]) == int(bill_no):
        parts = parts[1:]
    parts = [p for p in parts if p != ""]
    if len(parts) < 2:
        return None
    m = _ACRES.match(parts[-1])
    if not m:
        return None
    parcel = parts[0]
    if not re.search(r"\d", parcel) or len(parcel) > 24 or " " in parcel.strip():
        return None
    body = parts[1:-1]
    alt = body[0] if len(body) >= 2 else None
    situs = body[-1] if body else None
    return {"parcel": parcel, "alt": alt, "situs_text": situs,
            "acres": float(m.group(1)) if m.group(2).upper() == "AC" else None,
            "unit": m.group(2).upper(), "quantity": float(m.group(1)),
            **_split_situs(situs, cities)}


def _split_situs(situs: str | None, cities: tuple[str, ...]) -> dict:
    """'1008 1ST ST SURF CITY NC 28445-8620' -> street, city, zip. The county prints no
    comma between street and city, so the city is matched against the county's own place
    names first and a street suffix second."""
    out = {"street": None, "city": None, "zip": None}
    if not situs:
        return out
    s = situs.strip()
    zm = _ZIP.search(s)
    if zm:
        out["zip"] = zm.group(1)
        s = s[:zm.start()]
    s = _STATE.sub("", s).strip()
    city = None
    for c in sorted(cities, key=len, reverse=True):
        if s.endswith(" " + c) or s == c:
            city = c
            s = s[: len(s) - len(c)].strip()
            break
    if city is None and out["zip"]:
        toks = s.split()
        last_suffix = max((i for i, t in enumerate(toks) if t.upper() in _SUFFIX), default=None)
        if last_suffix is not None and last_suffix < len(toks) - 1:
            city = " ".join(toks[last_suffix + 1:])
            s = " ".join(toks[: last_suffix + 1])
    out["city"] = city.title() if city else None
    out["street"] = s if s and _HOUSE.match(s) else None
    return out


def parse_row(row: dict, cities: tuple[str, ...] = ()) -> dict | None:
    """One jqGrid row -> a bill dict, or None for personal property / junk."""
    cell = row.get("cell") or []
    if len(cell) < 7:
        return None
    year, bill = _text(cell[0]), _text(cell[1])
    desc = parse_description(str(cell[4]), bill, cities)
    if desc is None:
        return None
    return {"year": int(year) if year.isdigit() else None, "bill": bill,
            "account": _text(cell[2]), "owner": _text(cell[3]) or None,
            "original_levy": _money(cell[5]), "balance": _money(cell[6]), **desc}


def aggregate(county: str, portal: ITSPortal, bills: list[dict]) -> list[Listing]:
    """One TAX_LIEN lead per parcel; the unpaid years are summed."""
    by_parcel: dict[str, list[dict]] = {}
    for b in bills:
        by_parcel.setdefault(b["parcel"], []).append(b)
    out: list[Listing] = []
    now = datetime.utcnow()
    for parcel, group in by_parcel.items():
        group.sort(key=lambda b: b["year"] or 0, reverse=True)
        head = group[0]
        years = sorted({b["year"] for b in group if b["year"]})
        total = round(sum(b["balance"] or 0 for b in group), 2) or None
        owner = head["owner"]
        block = {
            "county": county, "portal": portal.base, "parcel": parcel,
            "alternate_id": head.get("alt"), "account": head["account"], "owner": owner,
            "situs_text": head.get("situs_text"), "years": years,
            "years_delinquent": len(years), "oldest_year": years[0] if years else None,
            "is_two_year_plus": len(years) >= 2, "total_due": total,
            "original_levy": round(sum(b["original_levy"] or 0 for b in group), 2) or None,
            "bills": [{"year": b["year"], "bill": b["bill"], "balance": b["balance"],
                       "original_levy": b["original_levy"]} for b in group],
            "acres": head.get("acres"), "unit": head.get("unit"),
        }
        raw: dict = {"nc_its_public_tax": block,
                     # The shared, published key fullmer_rank reads for delinquency ripeness.
                     "two_year_delinquent": {"is_two_year_plus": len(years) >= 2, "years": len(years),
                                             "oldest_year": years[0] if years else None,
                                             "source": SLUG}}
        if total:
            raw["tax_owed"] = {"balance": total, "kind": "delinquent_tax", "source": SLUG,
                               "year": head["year"], "basis": "own_record"}
        span = f"{years[0]}-{years[-1]}" if len(years) > 1 else (str(years[0]) if years else "")
        out.append(Listing(
            source=SLUG,
            source_url=f"{portal.base}/TaxBillSearch",
            listing_type=ListingType.TAX_LIEN,
            property_kind=PropertyKind.UNKNOWN,
            state="NC", county=county,
            parcel_id=parcel,
            owner_name=owner, defendant=owner,
            street_address=head.get("street"),
            city=head.get("city"), zip_code=head.get("zip"),
            legal_description=None if head.get("street") else head.get("situs_text"),
            acreage=head.get("acres"),
            description=(f"Delinquent NC property tax {span} ({len(group)} bill"
                         f"{'s' if len(group) != 1 else ''})"
                         + (f": ${total:,.2f} due" if total else "")
                         + f" (parcel {parcel})"),
            foreclosure_process="tax",
            first_seen=now, last_seen=now, raw=raw,
        ))
    return out


# --------------------------------------------------------------------------- the crawl

def _headers(portal: ITSPortal) -> dict:
    origin = re.match(r"^(https?://[^/]+)", portal.base).group(1)
    return {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{portal.base}/TaxBillSearch", "Origin": origin, "Accept": "*/*"}


async def fetch_year(client: httpx.AsyncClient, portal: ITSPortal, year: int, *,
                     max_rows: int | None = None) -> tuple[list[dict], dict]:
    """Every unpaid real-property bill of one tax year, paged on the session."""
    stats = {"year": year, "pages": 0, "rows": 0, "skipped_non_real": 0, "records": None}
    hdr = _headers(portal)
    page_rows = min(PAGE_ROWS, max_rows) if max_rows else PAGE_ROWS
    p = await client.post(f"{portal.base}/TaxBillSearch/GetSearchTablePartial", headers=hdr,
                          json={"PageSize": page_rows, "UnpaidBillsOnly": True,
                                "TaxYear": str(year)})
    p.raise_for_status()
    await asyncio.sleep(PACE_S)
    bills: list[dict] = []
    page = 1
    total_pages = 1
    while page <= min(total_pages, MAX_PAGES_PER_YEAR):
        d = await client.post(f"{portal.base}/TaxBillSearch/GetSearchTableData", headers=hdr,
                              json={"Page": page, "NumRows": page_rows, "Table": "PayTaxBills"})
        d.raise_for_status()
        try:
            j = d.json()
        except ValueError as exc:
            raise RuntimeError(f"{portal.county} page {page}: not JSON (session lost?)") from exc
        rows = j.get("rows")
        if not isinstance(rows, list):
            raise RuntimeError(f"{portal.county} page {page}: no rows list")
        stats["pages"] += 1
        stats["records"] = j.get("numRecords")
        total_pages = int(j.get("total") or 1)
        for r in rows:
            stats["rows"] += 1
            b = parse_row(r, portal.cities)
            if b is None:
                stats["skipped_non_real"] += 1
                continue
            bills.append(b)
        if max_rows and len(bills) >= max_rows:
            break
        page += 1
        if page <= total_pages:
            await asyncio.sleep(PACE_S)
    return bills, stats


class NcItsPublicTax(BaseScraper):
    slug = SLUG
    name = "NC ITSPublic delinquent property tax (Onslow, Graham)"
    category = "county_tax"
    timeout_s = 1500.0
    expected_min_count = 0
    optional = True

    #: A sample run (the ingest script's dry run) caps rows and reads only the newest year.
    limit: int | None = None

    async def fetch(self) -> Iterable[Listing]:
        only = {c.strip().title() for c in
                (os.getenv("ITS_TAX_COUNTIES") or "").split(",") if c.strip()}
        out: list[Listing] = []
        async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=60.0,
                                     follow_redirects=True) as client:
            for county, portal in PORTALS.items():
                if only and county not in only:
                    continue
                try:
                    r = await client.get(f"{portal.base}/TaxBillSearch")
                    r.raise_for_status()           # the session cookie
                    await asyncio.sleep(PACE_S)
                    bills: list[dict] = []
                    years = delinquent_years(back=1 if self.limit else None)
                    for y in years:
                        got, st = await fetch_year(client, portal, y, max_rows=self.limit)
                        bills.extend(got)
                        log.info("its_tax.year_done", county=county, **st)
                        self.partial.extend(aggregate(county, portal, got))
                        if self.limit:
                            break
                        await asyncio.sleep(PACE_S)
                except Exception as exc:  # noqa: BLE001
                    log.warning("its_tax.county_failed", county=county, error=str(exc)[:160])
                    continue
                if self.limit:                      # a sample run: a hard cap, not a floor
                    bills = bills[: self.limit]
                leads = aggregate(county, portal, bills)
                log.info("its_tax.county_done", county=county, bills=len(bills), leads=len(leads))
                out.extend(leads)
        return out
