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
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

import httpx
import structlog

from ...base_scraper import OUTCOME_PARTIAL, BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_nc.nc_its_public_tax"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

PAGE_ROWS = 100
PACE_S = float(os.getenv("ITS_TAX_PACE_S", "1.5"))
YEARS_BACK = int(os.getenv("ITS_TAX_YEARS_BACK", "3"))
MAX_PAGES_PER_YEAR = 400          # a stall guard: Onslow's 2025 is 75 pages
#: seconds one county may spend (all years); a county past it keeps what it read and is reported
#: as truncated in the block (`years_read`), never silently complete
COUNTY_BUDGET_S = float(os.getenv("ITS_TAX_COUNTY_BUDGET_S", "420"))


@dataclass(frozen=True)
class ITSPortal:
    county: str
    base: str                     # .../ITSPublicXX (no trailing slash, no /TaxBillSearch)
    #: Place names that end a situs line, longest first. Graham's situs carries no city.
    cities: tuple[str, ...] = ()
    #: The newer build answers an EMPTY partial and a table HTTP 500 to the JSON model above;
    #: it wants every .search-value field of the page, form-encoded (the same finding as
    #: verification/verifiers/tax_lien_itspublic.Portal.full_model). Top-80 2026-10-09.
    full_model: bool = False


PORTALS: dict[str, ITSPortal] = {
    "Onslow": ITSPortal(
        "Onslow", "https://tax.onslowcountync.gov/ITSPublicON",
        cities=("NORTH TOPSAIL BEACH", "TOPSAIL BEACH", "SNEADS FERRY", "HOLLY RIDGE",
                "MIDWAY PARK", "PINEY GREEN", "MAPLE HILL", "CAMP LEJEUNE", "STUMP SOUND",
                "SURF CITY", "JACKSONVILLE", "SWANSBORO", "RICHLANDS", "MAYSVILLE",
                "HAMPSTEAD", "POLLOCKSVILLE", "WILMINGTON", "BELGRADE", "FOLKSTONE",
                "VERONA", "HUBERT", "COMFORT", "TAR HEEL")),
    "Graham": ITSPortal("Graham", "https://www.bttaxpayerportal.com/ITSPublicGR2.0"),
    # Top-80 build list 2026-10-09 (tax family, 10 NC counties): the same vendor's newer build.
    # Read live 2026-10-09 (one GET + one partial + one table page each). Their column order differs
    # per county, so the grid's own header ids drive the parse (parse_row_cols).
    "Alleghany": ITSPortal("Alleghany", "https://www.bttaxpayerportal.com/ITSPublicAL", full_model=True),
    "Anson": ITSPortal("Anson", "https://www.bttaxpayerportal.com/ITSPublicAN", full_model=True),
    "Caswell": ITSPortal("Caswell", "https://www.bttaxpayerportal.com/ITSPublicCS", full_model=True),
    "Duplin": ITSPortal("Duplin", "https://www.bttaxpayerportal.com/ITSPublicDL", full_model=True),
    "Granville": ITSPortal("Granville", "https://tax.granvillecounty.org/ITSPublic", full_model=True),
    "Harnett": ITSPortal("Harnett", "https://cama.harnett.org/ITSPublicHT", full_model=True),
    "Jones": ITSPortal("Jones", "https://www.bttaxpayerportal.com/ITSPublicJN2.0", full_model=True),
    "Person": ITSPortal("Person", "https://www.bttaxpayerportal.com/ITSPublicPR", full_model=True),
    "Scotland": ITSPortal("Scotland", "https://www.bttaxpayerportal.com/ITSPublicSC", full_model=True),
    "Yadkin": ITSPortal("Yadkin", "https://www.bttaxpayerportal.com/ITSPublicYK", full_model=True),
}

#: Counties on this vendor that cannot be read (verdicts, not gaps; read live 2026-10-09):
#:   Clay, Swain, Surry  the old 1.0 build: a plain form post to /TaxBillSearch/Results that the
#:                       server answers HTTP 500 (no JSON grid exists)
#:   Warren, Gates       the portal answers, but every unpaid-bill search returns 0 records
UNREADABLE_PORTALS = {
    "Clay": "old ITS 1.0 build; results form answers HTTP 500",
    "Swain": "old ITS 1.0 build; results form answers HTTP 500",
    "Surry": "old ITS 1.0 build; results form answers HTTP 500",
    "Warren": "portal answers 0 unpaid bills for every year",
    "Gates": "portal answers 0 unpaid bills for every year",
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


_SEVERITY = {"in_tax_foreclosure": 2, "returned_payment": 1}


def _bill_status(action_cell: str | None) -> str | None:
    """Cell[7] -- the UI's own 'Add to Cart' button on a normal bill, but on
    some bills a status message INSTEAD of the button. Found 2026-10-03
    (HERMES extraction-completeness audit, batch 5): `parse_row` required
    >=7 cells and never looked at cell[7] at all, even though it's the SAME
    row the code already has in hand. Live-sampled 500 current Onslow bills:
    155/500 (31%) carry "This property is currently in Tax Foreclosure.
    Contact the tax office for further information" -- a materially
    stronger, further-along signal than plain delinquency, sitting
    uncaptured on nearly a third of this county's rows. A second, rarer
    message ("There is a returned item on this account...") flags a
    bounced payment -- also real but less severe."""
    text = _text(action_cell or "")
    low = text.lower()
    if "foreclosure" in low:
        return "in_tax_foreclosure"
    if "returned item" in low:
        return "returned_payment"
    return None


def parse_row(row: dict, cities: tuple[str, ...] = ()) -> dict | None:
    """One jqGrid row -> a bill dict, or None for personal property / junk."""
    cell = row.get("cell") or []
    if len(cell) < 7:
        return None
    year, bill = _text(cell[0]), _text(cell[1])
    desc = parse_description(str(cell[4]), bill, cities)
    if desc is None:
        return None
    status = _bill_status(cell[7]) if len(cell) > 7 else None
    return {"year": int(year) if year.isdigit() else None, "bill": bill,
            "account": _text(cell[2]), "owner": _text(cell[3]) or None,
            "original_levy": _money(cell[5]), "balance": _money(cell[6]),
            "status": status, **desc}


_PARCEL_ONLY = re.compile(r"^(?=.*\d)[0-9A-Za-z.\-]{8,24}$")
_TH = re.compile(r"<th[^>]*\bid=\"(\w+)\"", re.I)
_FIELD_IDS = (re.compile(r'class="[^"]*search-value[^"]*"[^>]*\bid="(\w+)"', re.I),
              re.compile(r'\bid="(\w+)"[^>]*class="[^"]*search-value', re.I))


def form_fields(page_html: str) -> list[str]:
    """The ids of the search form's .search-value inputs (the newer build wants all of them)."""
    ids: set[str] = set()
    for rx in _FIELD_IDS:
        ids.update(rx.findall(page_html or ""))
    return sorted(ids)


def search_form(fields: list[str], year: int, page_rows: int) -> dict:
    """The form-encoded model the newer build's page posts: every field present, empty but the
    tax year and the unpaid-bills flag."""
    model = {f: "" for f in fields}
    model.update({"PageSize": str(page_rows), "TaxYear": str(year), "UnpaidBillsOnly": "true",
                  "SortBy": "AccountName1-Asc"})
    if "ParcelSearch" in model:
        model["ParcelSearch"] = "false"
    return model


def grid_columns(partial_html: str) -> list[str]:
    """The result grid's column ids, in cell order (they differ per county)."""
    return _TH.findall(partial_html or "")


def _owner_text(cell: str) -> str | None:
    parts = [_text(p) for p in _BR.split(cell or "")]
    return " ".join(p for p in parts if p) or None


def parse_description_cols(desc_html: str, address: str | None, cities: tuple[str, ...] = ()) -> dict | None:
    """The newer build's Description cell. Two layouts:
      * a grid with an Address column: description = "<parcel>[<br/><alternate id>]"; the situs
        is the Address cell and no acreage is printed;
      * a grid without one: "<parcel><br/><br/><situs><br/><acres AC>" (the parcel line may be
        empty) and real property always ends in an acreage / unit count.
    Personal property says so and is dropped."""
    parts = [_text(p) for p in _BR.split(desc_html or "")]
    parts = [p for p in parts if p]
    if not parts or parts[0].lower().startswith("personal property"):
        return None
    if address is not None:
        parcel, alt = parts[0], (parts[1] if len(parts) > 1 else None)
        situs, acres, unit, qty = address or None, None, None, None
    else:
        m = _ACRES.match(parts[-1])
        alt = None
        if m:
            body = parts[:-1]
            situs = body[-1] if body else None
            parcel = body[0] if len(body) >= 2 else ""
            acres = float(m.group(1)) if m.group(2).upper() == "AC" else None
            unit, qty = m.group(2).upper(), float(m.group(1))
        elif _PARCEL_ONLY.match(parts[0]):
            # Anson prints "<parcel><br/><br/>[<situs>]" with no acreage on some real bills
            parcel, situs, acres, unit, qty = parts[0], (parts[1] if len(parts) > 1 else None), None, None, None
        else:
            return None
    parcel = re.sub(r"\s+", "", parcel or "")
    parcel = parcel if re.search(r"\d", parcel) and len(parcel) <= 24 else None
    if parcel is None and not (situs and _HOUSE.match(situs)):
        return None          # nothing to place the bill on
    return {"parcel": parcel, "alt": alt, "situs_text": situs, "acres": acres, "unit": unit,
            "quantity": qty, **_split_situs(situs, cities)}


def parse_row_cols(row: dict, cols: list[str], cities: tuple[str, ...] = ()) -> dict | None:
    """One jqGrid row of the newer build -> a bill dict (None for personal property / junk).
    `cols` are the grid's own header ids (grid_columns); a cell past them is the status cell."""
    cell = row.get("cell") or []
    idx = {c: i for i, c in enumerate(cols)}

    def g(name: str) -> str:
        i = idx.get(name)
        return cell[i] if i is not None and i < len(cell) else ""

    year, bill = _text(g("TaxYear")), _text(g("BillNumber"))
    if not year.isdigit() or not bill:
        return None
    address = _text(g("Address")) if "Address" in idx else None
    desc = parse_description_cols(g("Description"), address, cities)
    if desc is None:
        return None
    status = _bill_status(cell[len(cols)]) if len(cell) > len(cols) else None
    return {"year": int(year), "bill": bill, "account": _text(g("AccountNumber")),
            "owner": _owner_text(g("AccountName1")), "original_levy": _money(g("OriginalBillAmount")),
            "balance": _money(g("TotalDue")), "status": status, **desc}


def aggregate(county: str, portal: ITSPortal, bills: list[dict], *,
              years_read: list[int] | None = None, truncated: bool = False) -> list[Listing]:
    """One TAX_LIEN lead per parcel; the unpaid years are summed."""
    by_parcel: dict[str, list[dict]] = {}
    for b in bills:
        # a bill with no parcel id (Jones, Person print only a situs) groups by account + situs
        key = b.get("parcel") or f"acct:{b.get('account')}|{b.get('situs_text')}"
        by_parcel.setdefault(key, []).append(b)
    out: list[Listing] = []
    now = datetime.utcnow()
    for key, group in by_parcel.items():
        group.sort(key=lambda b: b["year"] or 0, reverse=True)
        head = group[0]
        parcel = head.get("parcel")
        years = sorted({b["year"] for b in group if b["year"]})
        total = round(sum(b["balance"] or 0 for b in group), 2) or None
        owner = head["owner"]
        # Worst status across this parcel's bills (a multi-year-delinquent
        # parcel can carry a foreclosure flag on one bill and a plain one on
        # another -- take the most severe, not just the newest).
        statuses = [b.get("status") for b in group if b.get("status")]
        worst_status = max(statuses, key=lambda s: _SEVERITY.get(s, 0), default=None)
        block = {
            "county": county, "portal": portal.base, "parcel": parcel,
            "alternate_id": head.get("alt"), "account": head["account"], "owner": owner,
            "situs_text": head.get("situs_text"), "years": years,
            "years_delinquent": len(years), "oldest_year": years[0] if years else None,
            "is_two_year_plus": len(years) >= 2, "total_due": total,
            "original_levy": round(sum(b["original_levy"] or 0 for b in group), 2) or None,
            "bills": [{"year": b["year"], "bill": b["bill"], "balance": b["balance"],
                       "original_levy": b["original_levy"], "status": b.get("status")}
                      for b in group],
            "acres": head.get("acres"), "unit": head.get("unit"),
            "status": worst_status,
            # which delinquent years the county read covered; a truncated read (the county's time
            # budget ran out) can under-count years, so is_two_year_plus False is then only "not seen"
            **({"years_read": years_read, "read_truncated": bool(truncated)} if years_read else {}),
        }
        raw: dict = {"nc_its_public_tax": block,
                     # The shared, published key fullmer_rank reads for delinquency ripeness.
                     "two_year_delinquent": {"is_two_year_plus": len(years) >= 2, "years": len(years),
                                             "oldest_year": years[0] if years else None,
                                             "source": SLUG}}
        if total:
            raw["tax_owed"] = {"balance": total, "kind": "delinquent_tax", "source": SLUG,
                               "year": head["year"], "basis": "own_record"}
        # Same top-level key counties_nc.nc_county_tax_foreclosure already
        # publishes (sold/redeemed/surplus/upset_bid there) -- "in_foreclosure"
        # here means the COUNTY'S OWN system already flags this specific
        # parcel as past plain delinquency, into active in-rem proceedings.
        if worst_status == "in_tax_foreclosure":
            raw["tax_sale_status"] = "in_foreclosure"
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
            description=(
                         ("ACTIVE TAX FORECLOSURE — " if worst_status == "in_tax_foreclosure" else "")
                         + f"Delinquent NC property tax {span} ({len(group)} bill"
                         f"{'s' if len(group) != 1 else ''})"
                         + (f": ${total:,.2f} due" if total else "")
                         + (f" (parcel {parcel})" if parcel else "")),
            foreclosure_process="tax",
            first_seen=now, last_seen=now, raw=raw,
        ))
    return out


# --------------------------------------------------------------------------- the crawl

def _headers(portal: ITSPortal) -> dict:
    origin = re.match(r"^(https?://[^/]+)", portal.base).group(1)
    return {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{portal.base}/TaxBillSearch", "Origin": origin, "Accept": "*/*"}


#: the search form's field ids per portal base, remembered from the page GET (full_model portals)
_FORM_FIELDS: dict[str, list[str]] = {}


async def fetch_year(client: httpx.AsyncClient, portal: ITSPortal, year: int, *,
                     max_rows: int | None = None, deadline: float | None = None) -> tuple[list[dict], dict]:
    """Every unpaid real-property bill of one tax year, paged on the session. `deadline`
    (time.monotonic) stops the paging and marks the year truncated."""
    stats = {"year": year, "pages": 0, "rows": 0, "skipped_non_real": 0, "records": None,
             "truncated": False}
    hdr = _headers(portal)
    page_rows = min(PAGE_ROWS, max_rows) if max_rows else PAGE_ROWS
    cols: list[str] = []
    table = "PayTaxBills"
    if portal.full_model:
        fields = _FORM_FIELDS.get(portal.base)
        if not fields:
            raise RuntimeError(f"{portal.county}: no search form fields read (legacy build?)")
        hdr = {k: v for k, v in hdr.items() if k != "Content-Type"}
        p = await client.post(f"{portal.base}/TaxBillSearch/GetSearchTablePartial/", headers=hdr,
                              data=search_form(fields, year, page_rows))
        p.raise_for_status()
        cols = grid_columns(p.text)
        if not cols or "TaxYear" not in cols:
            raise RuntimeError(f"{portal.county}: no result grid in the search answer")
        table = (re.findall(r'PopulateTable\("([^"]+)"', p.text) or [table])[0]
    else:
        p = await client.post(f"{portal.base}/TaxBillSearch/GetSearchTablePartial", headers=hdr,
                              json={"PageSize": page_rows, "UnpaidBillsOnly": True,
                                    "TaxYear": str(year)})
        p.raise_for_status()
    await asyncio.sleep(PACE_S)
    bills: list[dict] = []
    page = 1
    total_pages = 1
    while page <= min(total_pages, MAX_PAGES_PER_YEAR):
        if portal.full_model:
            d = await client.post(f"{portal.base}/TaxBillSearch/GetSearchTableData", headers=hdr,
                                  data={"Page": str(page), "NumRows": str(page_rows),
                                        "Table": table, "PostData": ""})
        else:
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
            b = parse_row_cols(r, cols, portal.cities) if portal.full_model else parse_row(r, portal.cities)
            if b is None:
                stats["skipped_non_real"] += 1
                continue
            bills.append(b)
        if max_rows and len(bills) >= max_rows:
            break
        page += 1
        if page <= total_pages:
            if deadline is not None and time.monotonic() > deadline:
                stats["truncated"] = True
                break
            await asyncio.sleep(PACE_S)
    return bills, stats


class NcItsPublicTax(BaseScraper):
    slug = SLUG
    name = "NC ITSPublic delinquent property tax (Onslow, Graham + 10 counties of the newer build)"
    category = "county_tax"
    timeout_s = 3300.0
    expected_min_count = 0
    optional = True

    #: A sample run (the ingest script's dry run) caps rows and reads only the newest year.
    limit: int | None = None
    #: per county: delinquent years read, bills kept, truncated flag (run health / audit)
    county_stats: dict

    async def fetch(self) -> Iterable[Listing]:
        only = {c.strip().title() for c in
                (os.getenv("ITS_TAX_COUNTIES") or "").split(",") if c.strip()}
        out: list[Listing] = []
        self.county_stats = {}
        incomplete: list[str] = []     # counties whose newest delinquent year was not read in full
        async with httpx.AsyncClient(headers={"User-Agent": _UA}, timeout=60.0,
                                     follow_redirects=True) as client:
            for county, portal in PORTALS.items():
                if only and county not in only:
                    continue
                deadline = time.monotonic() + COUNTY_BUDGET_S
                read_years: list[int] = []
                truncated = False
                try:
                    r = await client.get(f"{portal.base}/TaxBillSearch")
                    r.raise_for_status()           # the session cookie
                    if portal.full_model:
                        _FORM_FIELDS[portal.base] = form_fields(r.text)
                    await asyncio.sleep(PACE_S)
                    bills: list[dict] = []
                    years = delinquent_years(back=1 if self.limit else None)
                    for y in years:
                        got, st = await fetch_year(client, portal, y, max_rows=self.limit,
                                                   deadline=deadline)
                        bills.extend(got)
                        read_years.append(y)
                        truncated = truncated or st["truncated"]
                        log.info("its_tax.year_done", county=county, **st)
                        self.partial.extend(aggregate(county, portal, got))
                        if self.limit or st["truncated"]:
                            break
                        await asyncio.sleep(PACE_S)
                except Exception as exc:  # noqa: BLE001
                    log.warning("its_tax.county_failed", county=county, error=str(exc)[:160])
                    self.county_stats[county] = {"failed": str(exc)[:120]}
                    incomplete.append(county)
                    continue
                if self.limit:                      # a sample run: a hard cap, not a floor
                    bills = bills[: self.limit]
                if not self.limit and truncated and len(read_years) == 1:
                    incomplete.append(county)      # the newest year itself ran out of time
                leads = aggregate(county, portal, bills, years_read=read_years, truncated=truncated)
                self.county_stats[county] = {"years_read": read_years, "bills": len(bills),
                                             "leads": len(leads), "truncated": truncated}
                log.info("its_tax.county_done", county=county, bills=len(bills), leads=len(leads),
                         truncated=truncated)
                out.extend(leads)
        if incomplete and not self.limit:
            # the screen ledger (screen_ledger.py) counts a run of this source as a screen of every
            # county it covers only when the run is OK: a county that failed or ran out of time
            # on its newest year makes the run PARTIAL, so no county is claimed on a half read
            self.last_outcome = OUTCOME_PARTIAL
            self.last_reason = "counties not read in full: " + ", ".join(sorted(incomplete))
        return out
