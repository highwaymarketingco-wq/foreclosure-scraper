"""tax_lien, NC counties whose tax bills are on the BT / ITS "ITSPublic" tax-bill portal: is there a
real delinquent property-tax balance on this parcel?

A tax_lien adapter beside tax_lien_buncombe (the reference), tax_lien_ptscloud and
tax_lien_qpaybill: same SIGNAL, same GOVERNS, same verdict meanings, one tax_lien ledger.

WHY IT EXISTS (2026-10-08). The board's "tax delinquent 2+ years and $500 or more" flag was checked
on 0 of 372 Onslow rows and 0 of 197 Graham rows: no verifier knew these counties' tax site. Both
publish their bills through the same vendor application, which the roll scraper
(scrapers/counties_nc/nc_its_public_tax.py) already reads for the unpaid list. No login, no
CAPTCHA, no terms click-through; the search page only sets an ASP.NET session cookie.

    Onslow   https://tax.onslowcountync.gov/ITSPublicON/TaxBillSearch
    Graham   https://www.bttaxpayerportal.com/ITSPublicGR2.0/TaxBillSearch

NOT covered: Gates (bttaxpayerportal.com/ITSPublicGT, an older 1.0.1 build): every search
(parcel, bill number, a common surname) answered zero records on 2026-10-08, so it cannot decide
anything. Other ITSPublic counties (Person, ...) are one PORTALS entry each once their search is
checked live.

ADDED 2026-10-09 (audit tax_checkers_2; same verdict rules, nothing changes for Onslow / Graham):
    Transylvania  https://tax.transylvaniacounty.org/TaxBillSearch     board parcel = ParcelNumber
    Catawba       https://taxbill.catawbacountync.gov/ITSPublicCT       board PIN = AlternateParcelIdentifier
Both run a newer build that answers an EMPTY partial (and the table HTTP 500) unless the posted
model carries every .search-value field of the form (Portal.full_model; the table post then also
sends PostData). Transylvania prints a map reference between the parcel and the situs
("T452 00068A 01 MS.00": Portal.map_ref), its board rows carry 8511-59-1029-000 or the 13-digit
form (Portal.parcel_alnum) and its own roll block raw.transylvania_tax (parcel, account_number;
"Escrow :" where a business bill has no parcel: a placeholder). Catawba has no account search,
prints the PIN with a 0000 pad (3741171043520000 is PIN 374117104352: Portal.pin_pad), no acreage
on bills before levy 2025 (Portal.real_without_units: a bill naming a parcel that is not
"Personal Property"), and its advertisement PDF's id (raw.nc_county_pdf_delinquent_tax.county_id,
4,994 of 5,245 Catawba claim rows have no parcel_id) is the REID/LRK, zero-padded to 7 digits in
the ParcelNumber field (Roll.pad). A county roll's numbers are the row's own only on the roll's own
row (Roll.slug). A roll row with no parcel whose account answers only Personal Property bills is
unconfirmed, reason personal_property_only (Transylvania's roll lists business personal property
with parcel "Escrow :" on 163 board rows: not a real-property claim).

THE CALLS (read from the portal's own scripts, live-verified 2026-10-08; form-encoded posts bind
like the page's JSON posts):
    GET  {base}/TaxBillSearch                                  -> ASP.NET_SessionId cookie
    POST {base}/TaxBillSearch/GetSearchTablePartial/  {PageSize, <field>: <value>,
         UnpaidBillsOnly: false}                              -> HTML; stores the search in the
                                                                 session and names its table
                                                                 (PopulateTable("PayTaxBills", ...))
    POST {base}/TaxBillSearch/GetSearchTableData  {Page, NumRows, Table}
         -> {"total", "numRecords", "rows": [{"id": "2025/1278", "cell": [year, bill, account,
            owner, description html, original levy, balance, action html]}]}  every year, paid
            ones with balance 0.00
    POST {base}/TaxBillSearch/ViewTaxBill  {taxYear, billNumber}
         -> HTML: "Current Balance", "Last Payment Date", "Parcel Id", "Alternate Parcel ID#" ...
The description cell is <br>-separated: Onslow "<parcel id> | <map number> | <situs, city, NC,
zip> | 0.840 AC", Graham "<parcel> | <alternate id> | <situs> | 0.280 AC". Real property ends in an
acreage or unit count; a bill without one (personal property, a supplemental bill) is dropped.
The board's Onslow parcel_id is the MAP NUMBER (the portal's Alternate Parcel ID), Graham's is the
parcel number: PORTALS names the search field per county.

VERDICTS (a levy-year Y bill is late once unpaid on January 6 of Y+1, G.S. 105-360;
tax_calendar.delinquent_after):
  confirmed    a real-property bill of a late levy year with a balance today, on the row's own
               parcel (its number exactly, or the parcel that carries the row's address), with the
               owner agreeing or the parcel number exact (the tax_lien_ptscloud v4 rules).
  stale        nothing late is owed, the parcel carries the row's address (or the row has no
               house-numbered address and the parcel number is the row's own), and a claimed year,
               the latest late year, or a bill already late when the board first saw the row was
               paid on or after its delinquency date ("Last Payment Date").
  refuted      as stale, but those bills were paid before their delinquency date.
  unconfirmed  county not configured, no parcel, not found, fetch failure, portal unhealthy, the
               parcel's billing ended before the latest late levy, a bill with no payment date
               (released, adjusted to zero), the parcel's address is another property's and nothing
               ties the row to it (address_parcel_mismatch, address_not_found, ambiguous_account,
               roll_block_unbound), the bills' owner differs and the number is not exact.

WHICH PARCEL, AND THE OWNER (the tax_lien_ptscloud v4 / _tax_common rules, one to one). A parcel is
the row's when its number is one the ROW carries (the board parcel_id; the roll block's parcel and
alternate id on the roll's own row) or when its CURRENT situs (the newest tax year's bills) carries
the row's address. An exact number binds `confirmed` whatever address the county printed; stale and
refuted always need the address (or a row with no house-numbered address and the row's own
number). When the parcel names another address, the address is searched (FormattedPropertyAddress,
house number and street name): exactly one other parcel carrying it is followed only with proof the
row's parcel is wrong (_tax_common.account_choice), else ambiguous_account. A differing or partial
owner on the late bills / the latest bill is unconfirmed unless the parcel number is exact.

TWO CLAIMS (_tax_common, TWO CLAIMS). When nothing late is owed, the paid bills of the decision
years and the history from levy 2019 (at most MAX_HISTORY_VIEWS bill views) are read; evidence
records late_levy_years and chronic_claim, and governs_for keeps tax_lien_chronic when the history
confirms it or could not be read in full.

Evidence is a whitelist (public ledger): no owner names, no account numbers, no mailing addresses.

FETCHING. One cookie session per portal per run (reopened after SESSION_MAX_AGE_S), one request at
a time (the sweep's Fetcher paces each host), every search and bill view cached for the run; a
portal that fails PORTAL_MAX_FAILURES times in a row is skipped for the rest of the run
(unconfirmed portal_unhealthy, never refuted).
"""
from __future__ import annotations

import html as _html
import json
import re
import time
import weakref
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from ... import tax_calendar
from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
SOURCE = "itspublic"
GOVERNS = tc.GOVERNS          # tax_lien:property_tax, tax_sale:property_tax, ... (_tax_common)
governs_for = tc.governs_for  # per record: a confirmed chronic claim keeps tax_lien_chronic
ROW_SUMMARY_EXCLUDE = ("owner_name",)
#: unconfirmed reasons about the portal's health at check time, not the row (registry, optional)
TRANSIENT_REASONS = ("fetch_failed", "portal_unhealthy", "unreadable_answer",
                     "address_search_failed", "address_parcel_fetch_failed")


ROLL_KEY = "nc_its_public_tax"
ROLL_SLUG = "counties_nc.nc_its_public_tax"


@dataclass(frozen=True)
class Roll:
    """A county roll whose block a board row may carry (raw[key]) and how its numbers search the
    portal. Its numbers are the row's own (exact) only on the roll's OWN row (source == slug): a
    block merged into another source's row is a claim about the block's parcel, not the row's."""
    key: str                                   # raw block key
    slug: str                                  # the roll's own board source
    parcel_keys: tuple[str, ...] = ("parcel", "alternate_id")   # block fields naming the parcel
    search_keys: tuple[str, ...] = ("parcel",)  # those of them searched, in order
    parcel_field: Optional[str] = None         # search field for them (None: the portal's)
    pad: int = 0                               # zero-pad an all-digit block parcel to this width
    account_key: Optional[str] = "account"     # block field naming the taxpayer account


#: the ITSPublic roll scraper's own block (Onslow, Graham)
ITS_ROLL = Roll(ROLL_KEY, ROLL_SLUG)
#: tax_lien_itspublic v1 (2026-10-09): Transylvania's own roll scraper reads the same vendor
TRANSYLVANIA_ROLL = Roll("transylvania_tax", "counties_nc.transylvania_delinquent_tax",
                         parcel_keys=("parcel",), search_keys=("parcel",),
                         account_key="account_number")
#: Catawba's advertisement PDF: its id is the REID/LRK (the portal's ParcelNumber, 7 digits
#: zero-padded: PDF 27012 -> 0027012, live 2026-10-09), not an account number
CATAWBA_PDF_ROLL = Roll("nc_county_pdf_delinquent_tax", "counties_nc.nc_county_pdf_delinquent_tax",
                        parcel_keys=("county_id",), search_keys=("county_id",),
                        parcel_field="ParcelNumber", pad=7, account_key=None)


@dataclass(frozen=True)
class Portal:
    county: str
    base: str                      # .../ITSPublicXX, no trailing slash
    parcel_field: str              # the search field that takes the BOARD's parcel id
    address_search: bool = True    # the form offers FormattedPropertyAddress
    #: place names that end a situs line ("105 FOX LN HUBERT NC 28539"), longest first
    cities: tuple[str, ...] = ()
    rolls: tuple[Roll, ...] = (ITS_ROLL,)
    #: the build needs every .search-value field in the posted model, else the partial answers an
    #: empty body and the table HTTP 500 (Transylvania, Catawba; live 2026-10-09)
    full_model: bool = False
    #: extra .search-value fields of that model (Catawba: AlternateParcelIdentifier)
    model_fields: tuple[str, ...] = ()
    account_search: bool = True    # the form offers AccountNumber
    #: a bill whose description has no acreage is still real property when it names a parcel and
    #: is not "Personal Property" (Catawba prints no acreage on bills before levy 2025)
    real_without_units: bool = False
    #: a description part that is a map reference, not the situs (Transylvania prints
    #: "T452 00068A 01 MS.00" between the parcel and the situs)
    map_ref: Optional[str] = None
    #: the bill's parcel id is the board's PIN plus this zero pad (Catawba: 3741171043520000 is
    #: PIN 374117104352): the unpadded form is added to the bill's ids
    pin_pad: str = ""
    #: search the board parcel as [0-9A-Z] only (Transylvania boards carry 8511-59-1029-000)
    parcel_alnum: bool = False


PORTALS: dict[str, Portal] = {
    "Onslow": Portal(
        "Onslow", "https://tax.onslowcountync.gov/ITSPublicON", "AlternateParcelIdentifier",
        cities=("NORTH TOPSAIL BEACH", "TOPSAIL BEACH", "SNEADS FERRY", "HOLLY RIDGE",
                "MIDWAY PARK", "PINEY GREEN", "MAPLE HILL", "CAMP LEJEUNE", "STUMP SOUND",
                "SURF CITY", "JACKSONVILLE", "SWANSBORO", "RICHLANDS", "MAYSVILLE", "HAMPSTEAD",
                "POLLOCKSVILLE", "WILMINGTON", "BELGRADE", "FOLKSTONE", "VERONA", "HUBERT",
                "COMFORT", "TAR HEEL")),
    "Graham": Portal("Graham", "https://www.bttaxpayerportal.com/ITSPublicGR2.0", "ParcelNumber"),
    "Transylvania": Portal(
        "Transylvania", "https://tax.transylvaniacounty.org", "ParcelNumber",
        rolls=(ITS_ROLL, TRANSYLVANIA_ROLL), full_model=True, map_ref=r"\bMS\.\d+$",
        parcel_alnum=True),
    "Catawba": Portal(
        "Catawba", "https://taxbill.catawbacountync.gov/ITSPublicCT", "AlternateParcelIdentifier",
        cities=("SHERRILLS FORD", "LONG VIEW", "CLAREMONT", "CONOVER", "HICKORY", "MAIDEN",
                "NEWTON", "CATAWBA", "TERRELL", "VALE"),
        rolls=(ITS_ROLL, CATAWBA_PDF_ROLL), full_model=True,
        model_fields=("AlternateParcelIdentifier",), account_search=False,
        real_without_units=True, pin_pad="0000", parcel_alnum=True),
}
_BY_COUNTY = {k.lower(): v for k, v in PORTALS.items()}
#: a PTS Cloud roll row geocoded into one of these counties is tax_lien_ptscloud's (its claim is
#: about a parcel of the PTS tenant's county)
PTS_ROLL_SLUG = "counties_nc.nc_ptscloud_delinquent_tax"

NUM_ROWS = 100
MAX_PAGES = 2
MAX_SEARCHES = 2
MAX_ADDRESS_CANDIDATES = 3
MAX_BILL_CHECKS = 2
MAX_HISTORY_VIEWS = 8          # bill views for the decision years plus the history, per parcel
PORTAL_MAX_FAILURES = 2
SESSION_MAX_AGE_S = 15 * 60
TIMEOUT_S = 40.0

_NAME = __name__.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# which rows, which portal, which parcel (pure)
# ---------------------------------------------------------------------------

def portal_of(row: Any) -> Optional[Portal]:
    return _BY_COUNTY.get(str(tc.g(row, "county") or "").strip().lower())


def roll_of(row: Any) -> Optional[tuple[Roll, dict]]:
    """(roll, block) of the first of the row's portal's rolls whose block the row carries for the
    row's own county (a block naming no county is taken as the row's)."""
    portal = portal_of(row)
    raw = tc.raw_of(row)
    county = str(tc.g(row, "county") or "").strip().lower()
    for roll in (portal.rolls if portal else (ITS_ROLL,)):
        b = raw.get(roll.key)
        if isinstance(b, dict) and str(b.get("county") or county).strip().lower() == county:
            return roll, b
    return None


def roll_block(row: Any) -> Optional[dict]:
    """The block of the row's county roll (roll_of) when it is for the row's own county."""
    rb = roll_of(row)
    return rb[1] if rb else None


def _own_roll(row: Any) -> Optional[tuple[Roll, dict]]:
    """roll_of(row) when the row IS that roll's row (its numbers are the row's own)."""
    rb = roll_of(row)
    return rb if rb and tc.g(row, "source") == rb[0].slug else None


def applies(row: dict) -> bool:
    if str(row.get("state") or "").strip().upper() != "NC":
        return False
    if portal_of(row) is None or str(row.get("source") or "") == PTS_ROLL_SLUG:
        return False
    return tc.claims_property_tax(row, roll_block(row) is not None)


def _key(p: Any) -> str:
    """alnum identifier of a parcel number, '' for a placeholder (empty, all zeros, no digit at
    all: Transylvania's roll prints "Escrow :" where a business bill has no parcel)."""
    k = tc.alnum(p)
    return "" if not k or set(k) <= {"0"} or not re.search(r"\d", k) else k


def _roll_parcels(roll: Roll, blk: dict, keys: Optional[tuple[str, ...]] = None) -> list[str]:
    out = []
    for f in (roll.parcel_keys if keys is None else keys):
        v = str(blk.get(f) or "").strip()
        if roll.pad and v.isdigit() and len(v) < roll.pad:
            v = v.zfill(roll.pad)
        if _key(v):
            out.append(v)
    return out


def row_parcel_ids(row: Any) -> tuple[frozenset, frozenset]:
    """(own, exact) parcel numbers of the row (tax_lien_ptscloud.row_parcel_ids' rule): the board
    parcel_id, and on the roll's OWN row the block's parcel and alternate id. exact drops the
    numbers a resolver attached (a guess, not corroboration)."""
    own: set[str] = set()
    exact: set[str] = set()
    resolved = tc.parcel_resolved(row)

    def add(num: Any, exact_ok: bool) -> None:
        k = _key(num)
        if k:
            own.add(k)
            if exact_ok:
                exact.add(k)

    add(tc.g(row, "parcel_id"), not resolved)
    rb = _own_roll(row)
    if rb is not None:
        for v in _roll_parcels(*rb):
            add(v, True)
    return frozenset(own), frozenset(exact)


def searches(row: Any, portal: Portal) -> list[tuple[str, str, str]]:
    """[(field, value, where it came from)], best first, distinct: the board parcel in the
    county's board-parcel field, then the roll block's parcel, then the block's account (an
    account holds every parcel of a taxpayer: its bills are filtered by the row's numbers)."""
    out: list[tuple[str, str, str]] = []
    pid = str(tc.g(row, "parcel_id") or "").strip()
    if _key(pid):
        out.append((portal.parcel_field, tc.alnum(pid) if portal.parcel_alnum else pid,
                    "board_parcel"))
    rb = _own_roll(row)
    if rb is not None:
        roll, blk = rb
        for p in _roll_parcels(roll, blk, roll.search_keys):
            out.append((roll.parcel_field or portal.parcel_field,
                        tc.alnum(p) if portal.parcel_alnum else p, "roll_block"))
        acct = str(blk.get(roll.account_key) or "").strip() if roll.account_key else ""
        if _key(acct) and portal.account_search:
            out.append(("AccountNumber", acct, "roll_account"))
    seen, keep = set(), []
    for f, v, src in out:
        k = (f, tc.alnum(v))
        if k in seen:
            continue
        seen.add(k)
        keep.append((f, v, src))
    return keep


def claimed_years(row: Any) -> list[int]:
    years = tc.claimed_years_common(row) | tc.source_block_years(row)
    blk = roll_block(row)
    if blk is not None:
        for y in blk.get("years") or []:
            years.add(tc.to_int(y))
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.I)
_UNITS = re.compile(r"^\d+(?:\.\d+)?\s*(AC|LT|UT|SF|SQFT)$", re.I)
_ID = re.compile(r"^[0-9A-Z][0-9A-Z.\-]*$")
_ZIP = re.compile(r"\s+\d{5}(?:-\d{4})?$")
_STATE = re.compile(r"\s+NC$")
_STREET_SUFFIX = frozenset({"ST", "STREET", "RD", "ROAD", "DR", "DRIVE", "LN", "LANE", "CT", "COURT",
                            "CIR", "CIRCLE", "AVE", "AVENUE", "BLVD", "HWY", "HIGHWAY", "WAY", "TRL",
                            "TRAIL", "PL", "PLACE", "PKWY", "PARKWAY", "LOOP", "TER", "TERRACE", "CV",
                            "COVE", "RUN", "PT", "PIKE", "XING", "SQ", "BND", "PATH", "ROW", "EXT",
                            "ALY", "TRCE", "PASS"})


def _text(cell: Any) -> str:
    return " ".join(_html.unescape(_TAG.sub(" ", str(cell or ""))).split())


def _money(v: Any) -> Optional[float]:
    s = re.sub(r"[^\d.\-]", "", str(v or ""))
    if not s or s in (".", "-"):
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


_PERSONAL = re.compile(r"^personal\s+property\b", re.I)


def parse_description(desc_html: Any, portal: Optional[Portal] = None) -> dict:
    """{"ids": [...], "situs": str | None, "real": bool} from a description cell. The portal's
    quirks (Portal: real_without_units, map_ref, pin_pad) apply when it is given."""
    parts = [_text(p) for p in _BR.split(str(desc_html or ""))]
    parts = [p for p in parts if p]
    units = bool(parts) and bool(_UNITS.match(parts[-1]))
    body = parts[:-1] if units else parts
    map_ref = re.compile(portal.map_ref, re.I) if portal is not None and portal.map_ref else None
    ids: list[str] = []
    situs = None
    for p in body:
        if " " not in p and re.search(r"\d", p) and _ID.match(p.upper()) and len(p) <= 24:
            ids.append(p)
        elif map_ref is not None and map_ref.search(p):
            continue
        elif situs is None and re.search(r"[A-Za-z]", p):
            situs = p
    real = units
    if not real and portal is not None and portal.real_without_units:
        real = bool(ids) and bool(parts) and not _PERSONAL.match(parts[0])
    if portal is not None and portal.pin_pad:
        n = len(portal.pin_pad)
        for i in list(ids):
            if i.isdigit() and len(i) >= 10 + n and i.endswith(portal.pin_pad) and i[:-n] not in ids:
                ids.append(i[:-n])
    return {"ids": ids, "situs": situs, "real": real}


def situs_street(situs: Optional[str], cities: tuple[str, ...] = ()) -> Optional[str]:
    """'105 FOX LN HUBERT NC 28539-4513' -> '105 FOX LN': the zip, the state and the county's own
    place name (else the words after the last street suffix) are cut off; the county prints no
    comma between the street and the city."""
    if not situs:
        return None
    s = _ZIP.sub("", situs.strip().upper())
    s = _STATE.sub("", s).strip()
    for c in sorted(cities, key=len, reverse=True):
        if s.endswith(" " + c):
            return s[: len(s) - len(c)].strip() or None
    toks = s.split()
    last = max((i for i, t in enumerate(toks) if t in _STREET_SUFFIX and i > 0), default=None)
    if last is not None and last < len(toks) - 1 and (s != situs.strip().upper()):
        return " ".join(toks[: last + 1])
    return s or None


def parse_rows(payload: Any, portal: Optional[Portal] = None) -> list[dict]:
    """The bills of a GetSearchTableData answer (real property only), newest first."""
    out = []
    for r in (payload.get("rows") if isinstance(payload, dict) else None) or []:
        cell = r.get("cell") if isinstance(r, dict) else None
        if not isinstance(cell, list) or len(cell) < 7:
            continue
        year = tc.to_int(_text(cell[0]))
        if not 1900 < year < 2100:
            continue
        d = parse_description(cell[4], portal)
        if not d["real"] or not d["ids"]:
            continue
        action = _text(cell[7]) if len(cell) > 7 else ""
        out.append({"year": year, "bill": _text(cell[1]), "owner": _text(cell[3]) or None,
                    "ids": d["ids"], "situs": d["situs"], "original": _money(cell[5]),
                    "balance": _money(cell[6]) or 0.0,
                    "in_tax_foreclosure": "foreclosure" in action.lower()})
    out.sort(key=lambda b: (-b["year"], b["bill"]))
    return out


_LABEL = re.compile(r'info-row-label">\s*([^<]+?)\s*:\s*</div>\s*<div[^>]*info-row-text[^>]*>([^<]*)</div>',
                    re.I)


def parse_view(text: str) -> dict:
    """The label/value pairs of a ViewTaxBill page ({'Current Balance': '0.00', ...})."""
    return {_html.unescape(k).strip(): _html.unescape(v).strip() for k, v in _LABEL.findall(text or "")}


def _date(v: Any) -> Optional[date]:
    s = str(v or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def paid_late(view: dict, year: int, county: str) -> dict:
    """Late-payment evidence of one paid bill from its ViewTaxBill page: paid late when the Last
    Payment Date is on or after the levy year's delinquency date (tax_calendar, NC: Jan 6 of
    Y+1)."""
    begin = tax_calendar.delinquent_after(year, "NC", county)
    last = _date(view.get("Last Payment Date"))
    bal = _money(view.get("Current Balance"))
    out: dict[str, Any] = {"paid_on": last.isoformat() if last else None,
                           "delinquent_from": begin.isoformat(), "paid_late": bool(last and last >= begin)}
    if bal:
        out["balance_on_bill_page"] = bal
    if last is None:
        out["no_payment_on_bill"] = True
    elif out["paid_late"]:
        out["last_late_payment_on"] = last.isoformat()
        out["late_payment_dates"] = [last.isoformat()]
    return out


# ---------------------------------------------------------------------------
# fetching (one session per portal per run, cache, health)
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


class _PortalState:
    def __init__(self) -> None:
        self.cm: Any = None
        self.session: Any = None
        self.opened = 0.0
        self.failures = 0
        self.dead: Optional[str] = None


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _run(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {"cache": {}, "portals": {}})
    except TypeError:                                   # not weak-referenceable: no sharing
        return {"cache": {}, "portals": {}}


def _headers(portal: Portal) -> dict:
    origin = re.match(r"^(https?://[^/]+)", portal.base).group(1)
    return {"X-Requested-With": "XMLHttpRequest", "Referer": f"{portal.base}/TaxBillSearch",
            "Origin": origin}


async def _close(st: _PortalState) -> None:
    cm, st.cm, st.session = st.cm, None, None
    if cm is not None:
        try:
            await cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


async def _session(client: Any, portal: Portal) -> Any:
    st = _run(client)["portals"].setdefault(portal.county, _PortalState())
    if st.dead:
        raise PortalDown(st.dead)
    if st.session is None or time.monotonic() - st.opened > SESSION_MAX_AGE_S:
        await _close(st)
        cm = client.form_session()
        s = await cm.__aenter__()
        r = await s.get(f"{portal.base}/TaxBillSearch", timeout=TIMEOUT_S)
        if r.status != 200:
            await cm.__aexit__(None, None, None)
            raise RuntimeError(f"search page HTTP {r.status}")
        st.cm, st.session, st.opened = cm, s, time.monotonic()
    return st.session


def _failed(client: Any, portal: Portal, why: str) -> None:
    st = _run(client)["portals"].setdefault(portal.county, _PortalState())
    st.failures += 1
    st.session = None                       # the next call opens a fresh session
    if st.failures >= PORTAL_MAX_FAILURES:
        st.dead = f"{st.failures} failures in a row this run, last {why}"[:200]


def _ok(client: Any, portal: Portal) -> None:
    _run(client)["portals"].setdefault(portal.county, _PortalState()).failures = 0


def search_model(portal: Portal, field: str, value: str) -> dict:
    """The search-input model posted to GetSearchTablePartial: the field and the paid-bills flag
    (Onslow, Graham), or every .search-value field of the form with only `field` filled
    (Portal.full_model: Transylvania, Catawba answer an empty body to anything less)."""
    if not portal.full_model:
        model = {"PageSize": "50", field: value, "UnpaidBillsOnly": "false"}
        if field == "ParcelNumber":
            model["ParcelSearch"] = "false"
        return model
    model = {"PageSize": "50", "OwnerLastName": "", "OwnerFirstName": "", "ParcelNumber": "",
             "ParcelSearch": "false", "TaxYear": "", "BillNumber": "", "UnpaidBillsOnly": "false",
             "FormattedPropertyAddress": "", "SortBy": "AccountName1-Asc"}
    if portal.account_search:
        model["AccountNumber"] = ""
    for f in portal.model_fields:
        model[f] = ""
    model[field] = value
    return model


async def search(client: Any, portal: Portal, field: str, value: str) -> list[dict]:
    """Every real-property bill the portal returns for one search (all years), cached per run."""
    run = _run(client)
    ck = ("search", portal.county, field, value)
    if ck in run["cache"]:
        return run["cache"][ck]
    try:
        s = await _session(client, portal)
        hdr = _headers(portal)
        model = search_model(portal, field, value)
        r = await s.post_form(f"{portal.base}/TaxBillSearch/GetSearchTablePartial/", model,
                              headers=hdr, timeout=TIMEOUT_S)
        if r.status != 200:
            raise RuntimeError(f"search HTTP {r.status}")
        table = (re.findall(r'PopulateTable\("([^"]+)"', r.text) or ["PayTaxBills"])[0]
        bills: list[dict] = []
        other = 0
        for page in range(1, MAX_PAGES + 1):
            form = {"Page": str(page), "NumRows": str(NUM_ROWS), "Table": table}
            if portal.full_model:
                form["PostData"] = ""
            d = await s.post_form(f"{portal.base}/TaxBillSearch/GetSearchTableData", form,
                                  headers=hdr, timeout=TIMEOUT_S)
            if d.status != 200:
                raise RuntimeError(f"table HTTP {d.status}")
            payload = json.loads(d.text)
            if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
                raise ValueError("not a result table")
            got = parse_rows(payload, portal)
            other += len(payload["rows"]) - len(got)
            bills += got
            if page >= tc.to_int(payload.get("total")) or not payload["rows"]:
                break
    except PortalDown:
        raise
    except Exception as exc:  # noqa: BLE001
        _failed(client, portal, f"{type(exc).__name__}: {str(exc)[:120]}")
        raise
    _ok(client, portal)
    run["cache"][ck] = bills
    run["cache"][("other",) + ck] = other
    return bills


def other_bills(client: Any, portal: Portal, field: str, value: str) -> int:
    """How many bills a cached search answered that are not real property (personal property,
    supplemental bills): 0 when the search was not made."""
    return int(_run(client)["cache"].get(("other", "search", portal.county, field, value)) or 0)


async def view(client: Any, portal: Portal, year: int, bill: str) -> dict:
    """The ViewTaxBill label/values of one bill, cached per run. Never counts against the portal's
    health (an old bill the county purged must not take the county out of the run)."""
    run = _run(client)
    ck = ("view", portal.county, year, bill)
    if ck in run["cache"]:
        return run["cache"][ck]
    s = await _session(client, portal)
    r = await s.post_form(f"{portal.base}/TaxBillSearch/ViewTaxBill",
                          {"taxYear": str(year), "billNumber": str(bill)},
                          headers=_headers(portal), timeout=TIMEOUT_S)
    if r.status != 200:
        raise RuntimeError(f"bill page HTTP {r.status}")
    v = parse_view(r.text)
    if "Current Balance" not in v:
        raise ValueError("not a bill page")
    run["cache"][ck] = v
    return v


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "county", "tax_parcel", "tax_parcel_from", "board_parcel", "searched",
         "latest_levy_year", "latest_delinquent_eligible_levy", "delinquent_by_year",
         "total_delinquent", "years_delinquent", "under_500", "de_minimis", "not_yet_delinquent_due",
         "flags", "claimed_years", "bills_checked", "owner_match", "note", "error", "portal_health",
         "address_relation", "address_binding", "address_matches", "address_pins",
         "followed_from_parcel", "followed_because", "address_owner_match", "history_from_levy",
         "history_bills_read", "history_complete", "late_levy_years", "late_payment_dates",
         "chronic_claim", "current_claim_basis", "tax_parcel_row_own", "owner_corroborated_by")


def public_evidence(ev: dict) -> dict:
    return tc.pick(ev, _KEYS)


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, public_evidence(ev), source=SOURCE, version=VERSION,
                  verifier=_NAME)


def bills_of(bills: list[dict], parcel_key: str) -> list[dict]:
    return [b for b in bills if parcel_key in {tc.alnum(i) for i in b["ids"]}]


def _parcel_key_of(bill: dict, wanted: frozenset) -> str:
    """The id of a bill that is one of `wanted`, else its first id."""
    keys = [tc.alnum(i) for i in bill["ids"]]
    for k in keys:
        if k in wanted:
            return k
    return keys[0] if keys else ""


def _addresses(bills: list[dict], portal: Portal) -> list[str]:
    """The parcel's CURRENT situs street(s): those on its newest tax year's bills."""
    if not bills:
        return []
    top = max(b["year"] for b in bills)
    return list(dict.fromkeys(s for b in bills if b["year"] == top
                              for s in [situs_street(b.get("situs"), portal.cities)] if s))


def _set_binding(ev: dict, how: str) -> None:
    if "followed_from_parcel" not in ev:
        ev["address_binding"] = how


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    portal = portal_of(row)
    claimed = claimed_years(row)
    ev: dict[str, Any] = {"county": (portal.county if portal else row.get("county")),
                          "board_parcel": row.get("parcel_id"), "claimed_years": claimed}
    if portal is None:
        return _res("unconfirmed", dict(ev, reason="no_portal"))
    ev["url"] = f"{portal.base}/TaxBillSearch"
    plan = searches(row, portal)
    own, exact = row_parcel_ids(row)
    if not plan:
        if not (portal.address_search and tc.address_query(row.get("street_address"))):
            return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
        # no parcel number at all: the parcel that carries the row's address, if exactly one
        return await _by_address(row, client, portal, claimed, today, ev, own, exact)

    bills: list[dict] = []
    searched = []
    for field, value, src in plan[:MAX_SEARCHES]:
        try:
            found = await search(client, portal, field, value)
        except PortalDown as exc:
            return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200]))
        except Exception as exc:  # noqa: BLE001
            return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                            error=f"{type(exc).__name__}: {str(exc)[:160]}"))
        want = own | {tc.alnum(value)} if field != "AccountNumber" else own
        mine = [b for b in found if want & {tc.alnum(i) for i in b["ids"]}]
        searched.append({"by": field, "from": src, "bills": len(mine)})
        if mine:
            key = _parcel_key_of(mine[0], frozenset(want))
            bills = bills_of(mine, key)
            ev.update(tax_parcel=next((i for i in mine[0]["ids"] if tc.alnum(i) == key), key),
                      tax_parcel_from=src)
            break
    ev["searched"] = searched
    if not bills:
        if not own and any(other_bills(client, portal, f, v) for f, v, _ in plan[:MAX_SEARCHES]):
            # the roll row names no parcel and its account holds only personal-property bills
            # (Transylvania's roll lists business personal property with parcel "Escrow :")
            return _res("unconfirmed", dict(ev, reason="personal_property_only"))
        return _res("unconfirmed", dict(ev, reason="parcel_not_found"))
    return await _decide(row, client, portal, bills, claimed, today, ev, can_follow=True,
                         own=own, exact=exact)


async def _by_address(row: dict, client, portal: Portal, claimed: list[int], today: date,
                      ev: dict, own: frozenset, exact: frozenset) -> VerificationResult:
    query = tc.address_query(row.get("street_address"))
    try:
        found = await search(client, portal, "FormattedPropertyAddress", query)
    except PortalDown as exc:
        return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200]))
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                        error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    carry = await _carriers(row, client, portal, found)
    ev["searched"] = [{"by": "FormattedPropertyAddress", "from": "row_address", "bills": len(found)}]
    ev["address_matches"] = len(carry)
    if len(carry) != 1:
        return _res("unconfirmed", dict(ev, reason="address_not_found" if not carry
                                        else "address_parcel_mismatch"))
    key, pbills = next(iter(carry.items()))
    ev.update(tax_parcel=key, tax_parcel_from="address_search")
    _set_binding(ev, "address_search")
    return await _decide(row, client, portal, pbills, claimed, today, ev, can_follow=False,
                         own=own, exact=exact, bound=True)


async def _carriers(row: dict, client, portal: Portal, found: list[dict],
                    exclude: frozenset = frozenset()) -> dict[str, list[dict]]:
    """{parcel key: its bills} of the parcels in an address-search answer whose CURRENT situs
    carries the row's address (each candidate's own bills are read: the answer holds only the
    bills whose text matched)."""
    addr = row.get("street_address")
    cands: list[str] = []
    for b in found:
        if tc.address_relation(addr, situs_street(b.get("situs"), portal.cities)) != "match":
            continue
        k = tc.alnum(b["ids"][0])
        if k and not (exclude & {tc.alnum(i) for i in b["ids"]}) and k not in cands:
            cands.append(k)
    out: dict[str, list[dict]] = {}
    for k in cands[:MAX_ADDRESS_CANDIDATES]:
        first = next(b["ids"][0] for b in found if tc.alnum(b["ids"][0]) == k)
        pb = bills_of(await search(client, portal, "ParcelNumber", first), k)
        if any(tc.address_relation(addr, a) == "match" for a in _addresses(pb, portal)):
            out[k] = pb
    return out


async def _bind(row: dict, client, portal: Portal, parcel_key: str, bills: list[dict], ev: dict,
                *, can_follow: bool, own: bool) -> tuple[str, Any]:
    """("ok", None), ("follow", (key, bills)) or ("unconfirmed", reason): tax_lien_ptscloud._bind's
    rule on this portal."""
    query = tc.address_query(row.get("street_address"))
    if query is None:
        if not own:
            return "unconfirmed", "roll_block_unbound"
        _set_binding(ev, "no_row_address")
        return "ok", None
    addr = row.get("street_address")
    rels = {tc.address_relation(addr, a) for a in _addresses(bills, portal)}
    rel = "match" if "match" in rels else "conflict" if "conflict" in rels else "unknown"
    ev["address_relation"] = rel
    if rel == "match":
        _set_binding(ev, "bill_address")
        return "ok", None
    if not portal.address_search:
        if rel == "conflict" or not own:
            return "unconfirmed", "address_parcel_mismatch" if rel == "conflict" else "roll_block_unbound"
        _set_binding(ev, "unverified")
        return "ok", None
    try:
        found = await search(client, portal, "FormattedPropertyAddress", query)
        mine = frozenset(tc.alnum(i) for b in bills for i in b["ids"]) | {parcel_key}
        carry = await _carriers(row, client, portal, found, exclude=mine)
    except PortalDown:
        return "unconfirmed", "portal_unhealthy"
    except Exception as exc:  # noqa: BLE001
        ev["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return "unconfirmed", "address_search_failed"
    ev["address_matches"] = len(carry)
    if carry:
        if can_follow and len(carry) == 1:
            return "follow", next(iter(carry.items()))
        ev["address_pins"] = sorted(carry)[:4]
        return "unconfirmed", "address_parcel_mismatch"
    if rel == "conflict":
        return "unconfirmed", "address_not_found"
    if not own:
        return "unconfirmed", "roll_block_unbound"
    _set_binding(ev, "unverified")
    return "ok", None


def owner_gate(ev: dict, parcel_key: str, exact: frozenset) -> Optional[str]:
    cat = ev.get("owner_match")
    if cat in (None, "same"):
        return None
    if parcel_key in exact:
        ev["owner_corroborated_by"] = "pin_exact"
        return None
    return "bill_owner_differs" if cat == "different" else "bill_owner_partial"


async def _decide(row: dict, client, portal: Portal, bills: list[dict], claimed: list[int],
                  today: date, ev: dict, *, can_follow: bool, own: frozenset = frozenset(),
                  exact: frozenset = frozenset(), bound: bool = False) -> VerificationResult:
    county = portal.county
    latest = bills[0]
    parcel_key = tc.alnum(ev.get("tax_parcel") or "")
    ev["latest_levy_year"] = latest["year"]
    delinquent: dict[int, float] = {}
    current: dict[int, float] = {}
    flags: set[str] = set()
    owed_owners: list[Any] = []
    for b in bills:
        if b["balance"] <= 0:
            continue
        if tax_calendar.levy_year_is_delinquent(b["year"], "NC", county, today):
            delinquent[b["year"]] = round(delinquent.get(b["year"], 0.0) + b["balance"], 2)
            owed_owners.append(b["owner"])
            if b["in_tax_foreclosure"]:
                flags.add("in_tax_foreclosure")
        else:
            current[b["year"]] = round(current.get(b["year"], 0.0) + b["balance"], 2)
    ev["owner_match"] = tc.owner_category(row.get("owner_name"), [latest["owner"], *owed_owners])
    ev["delinquent_by_year"] = {str(y): a for y, a in sorted(delinquent.items(), reverse=True)}
    ev["total_delinquent"] = tc.money_total(delinquent)
    ev["years_delinquent"] = len(delinquent)
    ev["not_yet_delinquent_due"] = {str(y): a for y, a in sorted(current.items(), reverse=True)}
    if flags:
        ev["flags"] = sorted(flags)
    ev["tax_parcel_row_own"] = parcel_key in own

    if bound:
        action, what = "ok", None
    elif delinquent and parcel_key in exact:
        # the row's own parcel NUMBER: the bills are the row's whatever address the county printed
        if tc.address_query(row.get("street_address")):
            rels = {tc.address_relation(row.get("street_address"), a) for a in _addresses(bills, portal)}
            ev["address_relation"] = ("match" if "match" in rels else "conflict"
                                      if "conflict" in rels else "unknown")
        _set_binding(ev, "parcel_number")
        action, what = "ok", None
    else:
        action, what = await _bind(row, client, portal, parcel_key, bills, ev,
                                   can_follow=can_follow, own=ev["tax_parcel_row_own"])
    if action == "follow":
        key2, bills2 = what
        owner_addr = tc.owner_category(row.get("owner_name"), [bills2[0]["owner"]])
        if not tc.needs_proof(row.get("street_address"), _addresses(bills, portal)):
            choice, why = "follow", "parcel_names_no_usable_address"
        else:
            choice, why = tc.account_choice(
                own_retired=False,
                resolved=tc.parcel_resolved(row) and ev.get("tax_parcel_from") == "board_parcel",
                own_owner=ev.get("owner_match"), address_owner=owner_addr)
        if choice == "ambiguous":
            return _res("unconfirmed", dict(ev, reason=why, address_pins=[key2],
                                            address_owner_match=owner_addr))
        ev2 = {k: ev.get(k) for k in ("county", "board_parcel", "claimed_years", "url", "searched")}
        ev2.update(tax_parcel=next((i for i in bills2[0]["ids"] if tc.alnum(i) == key2), key2),
                   tax_parcel_from="address_search", followed_from_parcel=ev.get("tax_parcel"),
                   address_binding="followed", followed_because=why)
        return await _decide(row, client, portal, bills2, claimed, today, ev2, can_follow=False,
                             own=own, exact=exact, bound=True)
    if action == "unconfirmed":
        return _res("unconfirmed", dict(ev, reason=what))

    if delinquent:
        ev["under_500"] = ev["total_delinquent"] < 500
        ev["de_minimis"] = ev["total_delinquent"] < tc.DE_MINIMIS
        why_not = owner_gate(ev, parcel_key, exact)
        if why_not:
            return _res("unconfirmed", dict(ev, reason=why_not))
        return _res("confirmed", ev)

    # nothing late is owed and the parcel is the row's: stale / refuted / unconfirmed from history
    last_ok = tax_calendar.latest_delinquent_levy_year("NC", county, today)
    if latest["year"] < last_ok:
        return _res("unconfirmed", dict(ev, reason="parcel_record_ended",
                                        latest_delinquent_eligible_levy=last_ok))
    paid: dict[int, dict] = {}
    for b in bills:
        if not tax_calendar.levy_year_is_delinquent(b["year"], "NC", county, today):
            continue
        if b["year"] not in paid or (b["original"] or 0) > (paid[b["year"]]["original"] or 0):
            paid[b["year"]] = b
    order = [y for y in claimed if y in paid]
    for y in sorted(paid, reverse=True)[:2]:
        if y not in order:
            order.append(y)
    decision = order[:MAX_BILL_CHECKS]
    claimed_set = set(claimed)
    extra = sorted((y for y in paid if y not in decision
                    and (y >= tc.HISTORY_FROM_LEVY or y in claimed_set)), reverse=True)
    todo = (decision + extra)[:MAX_HISTORY_VIEWS]
    truncated = len(decision) + len(extra) > len(todo)
    checked = []
    for y in todo:
        b = paid[y]
        try:
            v = await view(client, portal, y, b["bill"])
        except PortalDown as exc:
            return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200]))
        except Exception as exc:  # noqa: BLE001
            checked.append({"year": y, "bill": b["bill"], "error": f"{type(exc).__name__}: {str(exc)[:100]}"})
            continue
        checked.append({"year": y, "bill": b["bill"], **paid_late(v, y, county)})
    ok = [c for c in checked if "error" not in c]
    late_years = {c["year"]: c for c in ok if c["paid_late"]}
    complete = not truncated and len(ok) == len(checked)
    ev["bills_checked"] = checked
    ev.update(history_from_levy=tc.HISTORY_FROM_LEVY, history_bills_read=len(ok),
              history_complete=complete, late_levy_years=sorted(late_years),
              late_payment_dates={str(y): late_years[y]["late_payment_dates"] for y in sorted(late_years)},
              chronic_claim=tc.history_claims(late_years, complete))
    if any(c.get("balance_on_bill_page") for c in ok):
        return _res("unconfirmed", dict(ev, reason="bill_page_disagrees"))
    first_seen = tc.first_seen_date(row)
    dchecks = checked[:len(decision)]
    claimed_late = sorted(c["year"] for c in ok if c["paid_late"] and c["year"] in claimed_set)
    decision_late = sorted(c["year"] for c in dchecks if c.get("paid_late"))
    seen_late = sorted(c["year"] for c in ok if c["paid_late"] and tc.paid_after_seen(
        first_seen, date.fromisoformat(c["delinquent_from"]), c.get("last_late_payment_on")))
    if claimed_late or decision_late or seen_late:
        ev["current_claim_basis"] = ("claimed_year_paid_late" if claimed_late
                                     else "latest_year_paid_late" if decision_late
                                     else "paid_late_after_first_seen")
        return _res("stale", ev)
    if not checked:
        return _res("unconfirmed", dict(ev, reason="no_paid_bill_to_check"))
    if all("error" in c for c in dchecks):
        return _res("unconfirmed", dict(ev, reason="bill_details_unreadable"))
    if any(c.get("no_payment_on_bill") for c in dchecks):
        return _res("unconfirmed", dict(ev, reason="no_payment_on_bill"))
    if current:
        ev["note"] = "only the current levy is unpaid; it is not delinquent yet"
    ev["current_claim_basis"] = ("claimed_years_on_time" if claimed_set & set(decision)
                                 else "latest_year_on_time")
    return _res("refuted", ev)
