"""tax_lien, NC counties on the CLASSIC ITS.NET "PublicAccess" tax-bill search (Iredell, Chowan):
does the county's own bill search still show a delinquent property-tax balance on this parcel?

A tax_lien adapter beside tax_lien_buncombe (the reference), tax_lien_ptscloud, tax_lien_qpaybill,
tax_lien_pickens, tax_lien_itspublic and tax_lien_perquimans: same SIGNAL, same GOVERNS, same
verdict meanings, one tax_lien ledger. Top-80 build list 2026-10-09, item 74 (lt_tax_lien) and
item 12 (tax_aging_surfaced).

WHY. counties_nc.iredell_delinquent_tax (2,360 rows on the 2026-10-09 reconciled checkpoint) turns
the county's advertised-list into tax_lien leads and counties_nc.albemarle_observer_tax_lists
(Chowan, 868) turns a newspaper's list into the same. Both are snapshots; the counties' own bill
searches (taxweb.iredellcountync.gov/PublicAccess, taxonline.chowancountync.email/itsnet) say what
is owed today, and every bill year back to 2001.

THE SOURCE (the CLASSIC ASP.NET WebForms build of ITS.NET, not the "ITSPublic" MVC build that
tax_lien_itspublic reads; no login, no CAPTCHA, no click-through; read live 2026-10-09):

    GET  {base}/TaxBill.aspx                       -> the search form (VIEWSTATE, EVENTVALIDATION)
    POST {base}/TaxBill.aspx  <the form> + parcel + dropdownlistTaxYear + buttonSearch
         -> the same page with a results grid (gridviewSearchResults): Year Bill#, Account#, Owner
            Name, Owner Name2, Orig Levy, Balance, Disc Year, Property ID (<br> alternate id),
            Property Address, one row per BILL (every year, paid ones with balance 0.00)
Iredell's parcel is MAP (4) + BLK (2) + PIN (4) digits and the grid's Property ID is the board's
parcel_id ("3774626057.000"); Chowan has one Parcel field and its Property ID is the board's
12-digit parcel_id. A form session (cookie jar) is opened per search; the form is the page's own,
every field kept, only the parcel and the tax year set.

VERDICTS (a levy-year Y bill is late once unpaid after the county's due date, tax_calendar):
  confirmed    a late-year bill on the row's own parcel (the grid's Property ID is the row's parcel
               number) has a balance today; the bill owner is not a different person when a resolver,
               not the county list, attached the parcel (the tax_lien_ptscloud v4 rule).
  stale        no late-year bill has a balance, the decision year (the row's claimed late year, else
               the newest late year) is billed on the parcel and paid, and the parcel's county address
               is not another house than the row's: the debt the list named has been paid since.
  unconfirmed  no parcel on the row / not shaped like the county's / the parcel has no bill / the
               decision year was not billed on it / the bills are another owner's on a resolver-
               attached parcel / the county address is another house's / the grid is paged / the
               site failed (fetch_failed, retried in 6 hours).
  refuted      never (this grid has no payment dates: "paid on time" cannot be told from "paid late").

Evidence is a whitelist (public ledger): no owner names, no mailing addresses, no account numbers.
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
SOURCE = "ITS.NET classic tax bill search (county portals)"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
priority = tc.flag_priority
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed", "unreadable_answer")

P = "ctl00$contentplaceholdertaxBillSearch$UsercontrolTaxbillSearch$"
TIMEOUT_S = 45.0
_NAME = __name__.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class Portal:
    county: str
    url: str                 # the TaxBill.aspx URL
    kind: str                # "map_blk_pin" (Iredell) or "single" (Chowan)
    #: raw blocks of the county's own list scrapers (a row carrying one claims a delinquency)
    blocks: tuple[str, ...] = ()


PORTALS: dict[str, Portal] = {
    "Iredell": Portal("Iredell", "https://taxweb.iredellcountync.gov/PublicAccess/TaxBill.aspx",
                      "map_blk_pin", ("iredell_delinquent_tax", "nc_tax_lien_ad")),
    "Chowan": Portal("Chowan", "http://taxonline.chowancountync.email/itsnet/TaxBill.aspx",
                     "single", ("albemarle_observer_tax_list", "nc_tax_lien_ad")),
}
_BY_COUNTY = {k.lower(): v for k, v in PORTALS.items()}


# ---------------------------------------------------------------------------
# which rows, which search (pure)
# ---------------------------------------------------------------------------

def portal_of(row: Any) -> Optional[Portal]:
    return _BY_COUNTY.get(str(tc.g(row, "county") or "").strip().lower())


def _own_block(row: Any, portal: Portal) -> bool:
    raw = tc.raw_of(row)
    for k in portal.blocks:
        b = raw.get(k)
        if isinstance(b, dict) and str(b.get("county") or portal.county).strip().lower() == portal.county.lower():
            return True
    return False


def applies(row: dict) -> bool:
    if str(tc.g(row, "state") or "").strip().upper() != "NC":
        return False
    portal = portal_of(row)
    if portal is None:
        return False
    return tc.claims_property_tax(row, _own_block(row, portal))


def search_fields(portal: Portal, parcel: Any) -> Optional[dict]:
    """The form fields that carry the board's parcel number, or None when it is not shaped like
    the county's (Iredell: 10 digits, with or without the '.000' suffix)."""
    s = str(parcel or "").strip()
    if not tc.alnum(s):
        return None
    if portal.kind == "map_blk_pin":
        d = re.sub(r"\D", "", s.split(".", 1)[0])
        if len(d) != 10:
            return None
        return {P + "ctrlParcelNumber$txtMAP": d[:4], P + "ctrlParcelNumber$txtBLK": d[4:6],
                P + "ctrlParcelNumber$txtPIN": d[6:10]}
    return {P + "ctrlParcelNumber$txtParcel": re.sub(r"[^0-9A-Za-z]", "", s)}


# ---------------------------------------------------------------------------
# the form and the grid (pure, tested on hand-written HTML)
# ---------------------------------------------------------------------------

def build_form(page: str, fields: dict, *, all_years: bool = True) -> dict:
    """The page's own form (every hidden, text and select field at its default) with the search
    fields set, the tax year at 'All Years' and the Search button pressed."""
    data: dict[str, str] = {}
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page or ""):
        data[m.group(1)] = _html.unescape(m.group(2))
    for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*type="text"', page or ""):
        data.setdefault(m.group(1), "")
    for m in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', page or "", re.S):
        name, body = m.group(1), m.group(2)
        opts = re.findall(r'<option([^>]*)>([^<]*)</option>', body)
        pick = None
        if all_years and name.endswith("dropdownlistTaxYear"):
            for attrs, label in opts:
                if "all" in label.lower():
                    pick = re.search(r'value="([^"]*)"', attrs)
                    break
        if pick is None:
            for attrs, label in opts:
                if "selected" in attrs:
                    pick = re.search(r'value="([^"]*)"', attrs)
                    break
        if pick is None and opts:
            pick = re.search(r'value="([^"]*)"', opts[0][0])
        data[name] = pick.group(1) if pick else ""
    data.update(fields)
    data["__EVENTTARGET"] = ""
    data["__EVENTARGUMENT"] = ""
    data[P + "buttonSearch"] = "Search"
    return data


_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)


def _text(s: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _money(s: str) -> float:
    try:
        return round(float(re.sub(r"[^\d.\-]", "", s) or 0), 2)
    except ValueError:
        return 0.0


def parse_grid(page: str) -> Optional[dict]:
    """{'bills': [{year, bill, account, owners[], levy, balance, ids[], address}], 'paged': bool}
    from a search-results page, or None when the page holds no results grid."""
    m = re.search(r'<table[^>]*gridviewSearchResults[^>]*>(.*?)</table>', page or "", re.S | re.I)
    if not m:
        return None
    grid = m.group(1)
    bills = []
    for rm in _ROW.finditer(grid):
        cells = [c.group(1) for c in _CELL.finditer(rm.group(1))]
        if len(cells) < 9 or "<th" in rm.group(1).lower():
            continue
        ym = re.match(r"\s*(\d{4})\s+(\S+)", _text(cells[0]))
        if not ym:
            continue
        ids = [x.strip() for x in re.split(r"<br\s*/?>", cells[7], flags=re.I) if _text(x)]
        bills.append({"year": int(ym.group(1)), "bill": ym.group(2), "account": _text(cells[1]),
                      "owners": [x for x in (_text(cells[2]), _text(cells[3])) if x],
                      "levy": _money(_text(cells[4])), "balance": _money(_text(cells[5])),
                      "ids": [_text(x) for x in ids], "address": re.sub(r"\s+", " ", _text(cells[8]))})
    return {"bills": bills, "paged": "Page$" in grid}


# ---------------------------------------------------------------------------
# fetch (one search per parcel per sweep run)
# ---------------------------------------------------------------------------

_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


class _SiteError(Exception):
    pass


async def _search(client: Any, portal: Portal, fields: dict) -> Optional[dict]:
    try:
        cache = _RUNS.setdefault(client, {})
    except TypeError:
        cache = {}
    key = (portal.county, tuple(sorted(fields.items())))
    if key in cache:
        return cache[key]
    async with client.form_session() as s:
        r = await s.get(portal.url, timeout=TIMEOUT_S)
        if r.status >= 400 or "__VIEWSTATE" not in r.text:
            raise _SiteError(f"form page HTTP {r.status}")
        r2 = await s.post_form(portal.url, build_form(r.text, fields), timeout=TIMEOUT_S)
        if r2.status >= 400:
            raise _SiteError(f"search HTTP {r2.status}")
    grid = parse_grid(r2.text)
    if grid is None:
        # a search that matches nothing prints no grid; a page that is not the form is an error
        if "__VIEWSTATE" not in r2.text:
            raise _SiteError("unreadable answer")
        grid = {"bills": [], "paged": False}
    cache[key] = grid
    return grid


_KEYS = ("reason", "url", "parcel", "county", "claimed_years", "decision_years", "bills_on_parcel",
         "late_years_owed", "total_late_balance", "latest_bill_year", "paid_decision_years",
         "owner_match", "address_relation", "parcel_from_resolver", "error", "note")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, tc.pick(ev, _KEYS), source=SOURCE, version=VERSION, verifier=_NAME)


def late_year(y: int, county: str, today: date) -> bool:
    return tax_calendar.levy_year_is_delinquent(y, "NC", county, today)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or datetime.now(timezone.utc).date()
    portal = portal_of(row)
    parcel = str(tc.g(row, "parcel_id") or "").strip()
    ev: dict[str, Any] = {"county": portal.county if portal else None, "parcel": parcel or None,
                          "url": portal.url if portal else None}
    if portal is None:
        return _res("unconfirmed", dict(ev, reason="county_not_configured"))
    fields = search_fields(portal, parcel)
    if fields is None:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    claimed = sorted(tc.claimed_years_common(row) | tc.source_block_years(row))
    ev["claimed_years"] = claimed
    try:
        grid = await _search(client, portal, fields)
    except Exception as exc:  # noqa: BLE001 - every outcome is an answer
        return _res("unconfirmed", dict(ev, reason="fetch_failed", error=f"{type(exc).__name__}: {str(exc)[:120]}"))
    if grid["paged"]:
        return _res("unconfirmed", dict(ev, reason="results_paged"))
    want = tc.alnum(parcel)
    bills = [b for b in grid["bills"] if any(tc.alnum(i) == want for i in b["ids"])]
    ev["bills_on_parcel"] = len(bills)
    if not bills:
        return _res("unconfirmed", dict(ev, reason="parcel_not_found"))
    ev["latest_bill_year"] = max(b["year"] for b in bills)
    resolved = tc.parcel_resolved(row)
    ev["parcel_from_resolver"] = resolved or None
    owed = {}
    for b in bills:
        if b["balance"] > 0 and late_year(b["year"], portal.county, today):
            owed[b["year"]] = round(owed.get(b["year"], 0.0) + b["balance"], 2)
    pool = [b for b in bills if b["year"] in owed] or [b for b in bills if b["year"] == ev["latest_bill_year"]]
    owner = tc.g(row, "owner_name")
    cat = tc.owner_category(owner, [o for b in pool for o in b["owners"]])
    ev["owner_match"] = cat
    if owed:
        ev.update(late_years_owed={str(y): v for y, v in sorted(owed.items())},
                  total_late_balance=round(sum(owed.values()), 2))
        if resolved and cat == "different":
            return _res("unconfirmed", dict(ev, reason="owner_differs",
                                            note="a resolver attached this parcel and its bills name another owner"))
        return _res("confirmed", ev)
    # nothing late is owed: was the decision year billed and paid?
    claimed_late = [y for y in claimed if late_year(y, portal.county, today)]
    decision = claimed_late or [tax_calendar.latest_delinquent_levy_year("NC", portal.county, today)]
    ev["decision_years"] = decision
    paid = sorted({b["year"] for b in bills if b["year"] in decision})
    ev["paid_decision_years"] = paid
    if not paid:
        return _res("unconfirmed", dict(ev, reason="decision_year_not_billed"))
    addrs = [b["address"] for b in bills if b["year"] in paid and b["address"]]
    row_addr = tc.g(row, "street_address")
    if row_addr and addrs and tc.address_query(row_addr):
        rel = tc.address_relation(row_addr, addrs[-1])
        ev["address_relation"] = rel
        if tc.other_number_same_street(row_addr, addrs[-1]):
            return _res("unconfirmed", dict(ev, reason="address_parcel_mismatch"))
    return _res("stale", dict(ev, reason="paid_since_list",
                              note="the county's bill search shows the decision year paid"))
