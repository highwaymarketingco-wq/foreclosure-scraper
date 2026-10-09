"""tax_lien, NC counties on PTS "Public Web Access" (Randolph, Mecklenburg): does the county's own
bill search still show a delinquent property-tax balance on this parcel?

A tax_lien adapter beside tax_lien_buncombe (the reference), tax_lien_ptscloud, tax_lien_qpaybill,
tax_lien_pickens, tax_lien_itspublic, tax_lien_itsnet and tax_lien_perquimans: same SIGNAL, same
GOVERNS, same verdict meanings, one tax_lien ledger. Top-80 build list 2026-10-09, item 74
(lt_tax_lien) and item 12 (tax_aging_surfaced).

WHY. On the 2026-10-09 reconciled checkpoint Randolph carries 4,128 tax-lien-ad rows
(counties_nc.nc_tax_lien_ads) and Mecklenburg 616 tax-foreclosure rows; the matrix lists both
counties' bill search as free (txpwa.randolphcountync.gov/publicwebaccess,
taxbill.co.mecklenburg.nc.us/publicwebaccess) and no verifier read it. Both are the SELF-HOSTED
classic build of PTS Public Web Access (an ASP.NET WebForms app; not the ncptscloud.com cloud build
tax_lien_ptscloud reads, whose Randolph and Mecklenburg tenants answer HTTP 500).

THE SOURCE (no login, no CAPTCHA, no click-through; read live 2026-10-09):

    GET  {base}/BillSearchResults.aspx?ClickItem=NewSearch    -> the search form (VIEWSTATE)
    POST {base}/BillSearchResults.aspx  lookupCriterion='Parcel Number', txtSearchString=<parcel>,
         taxYear='' (ALL) or one year, btnGo=Go
         -> the results grid: one row per BILL, newest year first, 25 rows a page ("[Page 1 of N]"):
            Bill # (<10 digits>-<year>-<year>-0000-00), Old Bill #, Parcel #, Name, Location (situs),
            Bill Flags (DLQ, ADVERTISED, Enforce Col Eligible, ATT REF, ATT REF IN REM = referred to
            the tax attorney for in rem foreclosure), Current Due (taxes + interest owed today)
Only the first page is read: it holds the newest bills, which are the ones a delinquency decision
needs; a balance on page 1 is a balance, and a paid decision year on page 1 is paid.

VERDICTS (a levy-year Y bill is late once unpaid after the county's due date, tax_calendar):
  confirmed    a late-year bill on the row's own parcel (the grid's Parcel # is the row's parcel
               number) has a Current Due today; the bill owner is not a different person when a
               resolver, not the county's list, attached the parcel (the tax_lien_ptscloud v4 rule).
               The bill flags (DLQ, ADVERTISED, ATT REF IN REM) are evidence.
  stale        no late-year bill is due, the decision year (the row's claimed late year, else the
               newest late year) is billed on the parcel and shows nothing due, and the county's
               address is not another house than the row's: the debt the list named has been paid.
  unconfirmed  no parcel on the row / the parcel has no bill / the decision year is not on page 1 /
               another owner's bills on a resolver-attached parcel / another house's address / the
               site failed (fetch_failed, retried in 6 hours).
  refuted      never (the grid has no payment dates).

Evidence is a whitelist (public ledger): no owner names, no mailing addresses.
"""
from __future__ import annotations

import html as _html
import re
import weakref
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from ... import tax_calendar
from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
SOURCE = "PTS Public Web Access bill search (county portals)"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed", "unreadable_answer")

TIMEOUT_S = 45.0
_NAME = __name__.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class Portal:
    county: str
    base: str                       # .../publicwebaccess, no trailing slash
    blocks: tuple[str, ...] = ()    # raw blocks of the county's list scrapers

    @property
    def form_url(self) -> str:
        return self.base + "/BillSearchResults.aspx?ClickItem=NewSearch"

    @property
    def post_url(self) -> str:
        return self.base + "/BillSearchResults.aspx"


PORTALS: dict[str, Portal] = {
    "Randolph": Portal("Randolph", "https://txpwa.randolphcountync.gov/publicwebaccess",
                       ("nc_tax_lien_ad",)),
    "Mecklenburg": Portal("Mecklenburg", "https://taxbill.co.mecklenburg.nc.us/publicwebaccess",
                          ("mecklenburg_tax_foreclosure", "nc_tax_lien_ad")),
}
_BY_COUNTY = {k.lower(): v for k, v in PORTALS.items()}


def portal_of(row: Any) -> Optional[Portal]:
    return _BY_COUNTY.get(str(tc.g(row, "county") or "").strip().lower())


def _own_block(row: Any, portal: Portal) -> bool:
    raw = tc.raw_of(row)
    return any(isinstance(raw.get(k), dict) for k in portal.blocks)


def applies(row: dict) -> bool:
    if str(tc.g(row, "state") or "").strip().upper() != "NC":
        return False
    portal = portal_of(row)
    if portal is None:
        return False
    return tc.claims_property_tax(row, _own_block(row, portal))


# ---------------------------------------------------------------------------
# the form and the grid (pure, tested on hand-written HTML)
# ---------------------------------------------------------------------------

def build_form(page: str, parcel: str, *, year: str = "ALL") -> dict:
    """The page's own form with the criterion 'Parcel Number', the parcel and the tax year set."""
    data: dict[str, str] = {}
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page or ""):
        data[m.group(1)] = _html.unescape(m.group(2))
    for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*type="text"', page or ""):
        data.setdefault(m.group(1), "")

    def option(name: str, label: str) -> str:
        m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>' % name, page or "", re.S)
        for attrs, lab in re.findall(r'<option([^>]*)>([^<]*)</option>', m.group(1) if m else ""):
            if lab.strip().lower() == label.lower():
                v = re.search(r'value="([^"]*)"', attrs)
                return v.group(1) if v else ""
        return ""

    data["lookupCriterion"] = option("lookupCriterion", "Parcel Number")
    data["taxYear"] = option("taxYear", year)
    data["txtSearchString"] = parcel
    data["btnGo"] = "Go"
    return data


_BILL = re.compile(r"^\d{6,12}-(\d{4})-\d{4}-\d{4}-\d{2}")
_ROWS = re.compile(r"<tr id='dgResults_r_\d+'[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r'<td[^>]*level="\d+_(\d+)"[^>]*>(.*?)</td>', re.S)
_UV = re.compile(r'<td[^>]*\buV="([\d.,]+)"[^>]*level="\d+_7"', re.S)
_PAGES = re.compile(r"\[Page\s+(\d+)\s+of\s+(\d+)\]", re.I)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", s or "")).replace("\xa0", " ")).strip()


def parse_grid(page: str) -> Optional[dict]:
    """{'bills': [{year, bill, parcel, owner, address, flags, due}], 'pages': N} or None when the
    page holds no results grid at all."""
    if "dgResults" not in (page or ""):
        return None
    pm = _PAGES.search(page)
    bills = []
    for rm in _ROWS.finditer(page):
        cells = {int(k): v for k, v in _CELL.findall(rm.group(1))}
        bm = _BILL.match(_text(cells.get(0, "")))
        if not bm:
            continue
        um = _UV.search(rm.group(1))
        due_s = um.group(1) if um else re.sub(r"[^\d.]", "", _text(cells.get(7, "")))
        try:
            due = round(float(due_s.replace(",", "")), 2) if due_s else 0.0
        except ValueError:
            due = 0.0
        bills.append({"year": int(bm.group(1)), "bill": _text(cells[0]), "parcel": _text(cells.get(2, "")),
                      "owner": _text(cells.get(3, "")), "address": _text(cells.get(4, "")),
                      "flags": [f.strip() for f in _text(cells.get(5, "")).split(",") if f.strip()],
                      "due": due})
    return {"bills": bills, "pages": int(pm.group(2)) if pm else 1}


# ---------------------------------------------------------------------------
# fetch (one search per parcel per sweep run)
# ---------------------------------------------------------------------------

_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


class _SiteError(Exception):
    pass


async def _search(client: Any, portal: Portal, parcel: str) -> dict:
    try:
        cache = _RUNS.setdefault(client, {})
    except TypeError:
        cache = {}
    key = (portal.county, tc.alnum(parcel))
    if key in cache:
        return cache[key]
    async with client.form_session() as s:
        r = await s.get(portal.form_url, timeout=TIMEOUT_S)
        if r.status >= 400 or "__VIEWSTATE" not in r.text:
            raise _SiteError(f"form page HTTP {r.status}")
        r2 = await s.post_form(portal.post_url, build_form(r.text, parcel), timeout=TIMEOUT_S)
        if r2.status >= 400:
            raise _SiteError(f"search HTTP {r2.status}")
    grid = parse_grid(r2.text)
    if grid is None:
        if "__VIEWSTATE" not in r2.text:
            raise _SiteError("unreadable answer")
        grid = {"bills": [], "pages": 1}
    cache[key] = grid
    return grid


_KEYS = ("reason", "url", "parcel", "county", "claimed_years", "decision_years", "bills_on_page",
         "pages", "late_years_owed", "total_late_balance", "latest_bill_year", "paid_decision_years",
         "bill_flags", "owner_match", "address_relation", "parcel_from_resolver", "error", "note")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    portal = portal_of(row)
    parcel = str(tc.g(row, "parcel_id") or "").strip()
    ev: dict[str, Any] = {"county": portal.county if portal else None, "parcel": parcel or None,
                          "url": portal.base if portal else None}
    if portal is None:
        return _res("unconfirmed", dict(ev, reason="county_not_configured"))
    if not tc.alnum(parcel) or set(tc.alnum(parcel)) <= {"0"}:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    claimed = sorted(tc.claimed_years_common(row) | tc.source_block_years(row))
    ev["claimed_years"] = claimed
    try:
        grid = await _search(client, portal, parcel)
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return _res("unconfirmed", dict(ev, reason="fetch_failed", error=f"{type(exc).__name__}: {str(exc)[:120]}"))
    want = tc.alnum(parcel)
    bills = [b for b in grid["bills"] if tc.alnum(b["parcel"]) == want]
    ev.update(bills_on_page=len(bills), pages=grid["pages"])
    if not bills:
        return _res("unconfirmed", dict(ev, reason="parcel_not_found"))
    ev["latest_bill_year"] = max(b["year"] for b in bills)
    resolved = tc.parcel_resolved(row)
    ev["parcel_from_resolver"] = resolved or None
    owed: dict[int, float] = {}
    flags: list[str] = []
    for b in bills:
        if b["due"] > 0 and tax_calendar.levy_year_is_delinquent(b["year"], "NC", portal.county, today):
            owed[b["year"]] = round(owed.get(b["year"], 0.0) + b["due"], 2)
            flags += [f for f in b["flags"] if f not in flags]
    pool = [b for b in bills if b["year"] in owed] or [b for b in bills if b["year"] == ev["latest_bill_year"]]
    cat = tc.owner_category(tc.g(row, "owner_name"), [b["owner"] for b in pool])
    ev["owner_match"] = cat
    if owed:
        ev.update(late_years_owed={str(y): v for y, v in sorted(owed.items())},
                  total_late_balance=round(sum(owed.values()), 2), bill_flags=flags)
        if resolved and cat == "different":
            return _res("unconfirmed", dict(ev, reason="owner_differs",
                                            note="a resolver attached this parcel and its bills name another owner"))
        return _res("confirmed", ev)
    claimed_late = [y for y in claimed if tax_calendar.levy_year_is_delinquent(y, "NC", portal.county, today)]
    decision = claimed_late or [tax_calendar.latest_delinquent_levy_year("NC", portal.county, today)]
    ev["decision_years"] = decision
    paid = sorted({b["year"] for b in bills if b["year"] in decision})
    ev["paid_decision_years"] = paid
    if not paid:
        return _res("unconfirmed", dict(ev, reason="decision_year_not_on_page"))
    addrs = [b["address"] for b in bills if b["year"] in paid and b["address"]]
    row_addr = tc.g(row, "street_address")
    if row_addr and addrs and tc.address_query(row_addr):
        ev["address_relation"] = tc.address_relation(row_addr, addrs[-1])
        if tc.other_number_same_street(row_addr, addrs[-1]):
            return _res("unconfirmed", dict(ev, reason="address_parcel_mismatch"))
    return _res("stale", dict(ev, reason="paid_since_list",
                              note="the county's bill search shows the decision year with nothing due"))
