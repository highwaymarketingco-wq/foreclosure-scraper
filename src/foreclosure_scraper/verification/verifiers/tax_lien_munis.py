"""tax_lien, NC counties whose tax bills are on Tyler's Munis "Citizen Self Service" real-estate
search: is there a real delinquent property-tax balance on this parcel?

A tax_lien adapter beside tax_lien_buncombe (the reference), tax_lien_ptscloud,
tax_lien_qpaybill and tax_lien_itspublic: same SIGNAL, same GOVERNS, same verdict meanings, one
tax_lien ledger.

WHY IT EXISTS (2026-10-08). New Hanover carried 1,286 board rows flagged "tax delinquent 2+ years
and $500 or more" and none had been checked: no verifier knew the county's tax site, and the
county roll the scraper read (a DocumentCenter CSV) now answers 404. The county's assessment site
(etax.nhcgov.com, iasWorld behind a click-through disclaimer) has no bill or payment data. The
bills are on the county's Munis self-service site, a public search with no login (the "Log In"
link is optional, for a taxpayer's own account), no CAPTCHA and no terms page:

    New Hanover  https://newhanovercountynccss.munisselfservice.com/citizens/RealEstate/Default.aspx

THE BOARD'S NEW HANOVER FLAG (measured on the 2026-10-07 board, read-only): 1,209 of the 1,286
flagged rows carry a roll block (raw['nc_county_csv_delinquent_tax']) whose county_id is ANOTHER
parcel: one block ($4,150.31, 2016-2025, one parcel) is copied onto 1,198 rows and another
($110.44) onto 936. The flag on those rows is that other parcel's debt. So this verifier judges the
ROW'S OWN parcel and never takes claimed years from a block of another parcel (evidence
claim_block_other_parcel); the block fan-out itself is a pipeline defect, reported, not fixed here.

THE CALLS (live-verified 2026-10-08, ASP.NET WebForms, one cookie session):
    GET  {base}/citizens/RealEstate/Default.aspx?mode=new        the search form (view state)
    POST the same URL with ...ParcelIDTextBox=<parcel>, ...Button1=Search
         -> ParcelBrowse.aspx: BillsGridView, one row per bill of every year (Property Address,
            Unit, Owner, Parcel ID, Tax Year, Bill Type, a View Bill postback). A partial id lists
            every parcel that starts with it, so rows are kept only for the exact parcel id; no
            match is a grid with no rows.
    POST ParcelBrowse.aspx with __EVENTTARGET=<the row's ViewBillLinkButton>
         -> ViewBill.aspx: Bill Year, Bill, Owner, Parcel ID, the installment table (Pay By,
            Amount, Payments/Credits, Balance, Interest, Due; TOTAL row) and a message naming
            "Prior ... unpaid bills" / "newer unpaid bill(s)" of the parcel.
    GET  ViewPayments.aspx (after a bill view) -> the bill's activity: Payment / Adjustment / Fee
            rows with their posted dates (the "Paid By" column is never read).
The search state lives in the session: one row's calls run one after another on one cookie.

VERDICTS (a levy-year Y bill is late once unpaid on January 6 of Y+1, G.S. 105-360;
tax_calendar.delinquent_after; the county's own "Pay By" date is recorded, never used to call a
payment on time that the statute calls late):
  confirmed    a regular real-estate bill of a late levy year with an amount due today on the row's
               own parcel (its exact number, a number no resolver attached, or the address the
               bills carry), the owner agreeing or the number exact (tax_lien_ptscloud v4 rules).
  stale        nothing late is owed, the parcel carries the row's address (or the row has no
               house-numbered address and the number is the row's own), and a claimed year, the
               latest late year, or a bill already late when the board first saw the row has a
               Payment posted on or after its delinquency date.
  refuted      as stale, but those bills were paid before their delinquency date.
  unconfirmed  no parcel id, parcel not found, fetch failure, portal unhealthy, billing ended
               before the latest late levy, a bill with no payment (released), the parcel's
               address is another property's (address_parcel_mismatch: v1 does not follow an
               address to another parcel), the bills' owner differs and the number is not exact,
               the older unpaid bills could not all be read for the total (never refuted).

HOW MANY PAGES. The grid has no balances, so balances come from bill views, newest late year first.
A view's message says whether OLDER unpaid bills exist, which ends the walk early: a paid latest
late bill with no older unpaid one means nothing late is owed. At most MAX_VIEWS bill views and
MAX_PAYMENT_PAGES payment pages per row (decision years first, then the history from levy 2019:
_tax_common, TWO CLAIMS); a history cut short is history_complete false (chronic_claim unknown, so
governs_for keeps tax_lien_chronic).

Evidence is a whitelist (public ledger): no owner names, no payer names, no bill reference numbers.
"""
from __future__ import annotations

import html as _html
import re
import time
import weakref
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

from ... import tax_calendar
from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
SOURCE = "munisselfservice.com"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
ROW_SUMMARY_EXCLUDE = ("owner_name",)
#: unconfirmed reasons about the portal's health at check time, not the row (registry, optional)
TRANSIENT_REASONS = ("fetch_failed", "portal_unhealthy", "unreadable_answer", "bill_page_unreadable")


@dataclass(frozen=True)
class Portal:
    county: str
    base: str                      # https://<tenant>.munisselfservice.com


PORTALS: dict[str, Portal] = {
    "New Hanover": Portal("New Hanover", "https://newhanovercountynccss.munisselfservice.com"),
}
_BY_COUNTY = {k.lower(): v for k, v in PORTALS.items()}

ROLL_KEY = "nc_county_csv_delinquent_tax"
PTS_ROLL_SLUG = "counties_nc.nc_ptscloud_delinquent_tax"

FORM = "/citizens/RealEstate/Default.aspx?mode=new"
BROWSE = "/citizens/RealEstate/ParcelBrowse.aspx"
PAYMENTS = "/citizens/RealEstate/ViewPayments.aspx"
_CTRL = "ctl00$ctl00$PrimaryPlaceHolder$ContentPlaceHolderMain$Control$"
_SEARCH_FIELDS = ("AddressSearchFieldLayout$ctl01$StreetNumberTextBox",
                  "StreetNameSearchFieldLayout$ctl01$AddressTextBox",
                  "OwnerSearchFieldLayout$ctl01$OwnerNameTextBox",
                  "BillNumberSearchFieldLayoutItem$ctl01$BillNumberTextBox",
                  "FiscalYearLayoutItem$ctl01$YearSearchTextBox")
PARCEL_FIELD = _CTRL + "ParcelIdSearchFieldLayout$ctl01$ParcelIDTextBox"
SEARCH_BUTTON = _CTRL + "FormLayoutItem7$ctl01$Button1"

MAX_VIEWS = 6
MAX_PAYMENT_PAGES = 4
MAX_BILL_CHECKS = 2
PORTAL_MAX_FAILURES = 2
SESSION_MAX_AGE_S = 15 * 60
TIMEOUT_S = 60.0

_NAME = __name__.rsplit(".", 1)[-1]


# ---------------------------------------------------------------------------
# which rows, which parcel (pure)
# ---------------------------------------------------------------------------

def portal_of(row: Any) -> Optional[Portal]:
    return _BY_COUNTY.get(str(tc.g(row, "county") or "").strip().lower())


def roll_block(row: Any) -> Optional[dict]:
    b = tc.raw_of(row).get(ROLL_KEY)
    return b if isinstance(b, dict) else None


def own_block(row: Any) -> Optional[dict]:
    """The county roll's block when it is about the ROW'S parcel (county_id equals parcel_id)."""
    b = roll_block(row)
    if b is None:
        return None
    k = tc.alnum(b.get("county_id"))
    return b if k and k == tc.alnum(tc.g(row, "parcel_id")) else None


def applies(row: dict) -> bool:
    if str(row.get("state") or "").strip().upper() != "NC":
        return False
    if portal_of(row) is None or str(row.get("source") or "") == PTS_ROLL_SLUG:
        return False
    return tc.claims_property_tax(row, roll_block(row) is not None)


_UNDASHED = re.compile(r"^([A-Z]{1,2}\d{4,5})(\d{3})(\d{3})([0-9A-Z]{3})$")


def search_id(parcel: Any) -> str:
    """The parcel id as the portal's Parcel ID search wants it: New Hanover's "R09999-001-002-000".
    The board also carries it with the dashes dropped ("R09999001002000", 568 rows on 2026-10-07),
    which the portal does not find; those are dashed again. Anything else is passed as it is."""
    s = str(parcel or "").strip().upper()
    m = _UNDASHED.match(s)
    return "-".join(m.groups()) if m else s


def claimed_years(row: Any) -> list[int]:
    """Levy years the row's OWN claim names. A roll block of another parcel (module doc) names
    that parcel's years, and the derived blocks (tax_owed, tax_aging_surfaced,
    two_year_delinquent) were built from it: none of them is a claim about this parcel."""
    blk = roll_block(row)
    if blk is not None and own_block(row) is None:
        return []
    years = tc.claimed_years_common(row) | tc.source_block_years(row)
    if blk is not None:
        for y in blk.get("bill_years") or []:
            years.add(tc.to_int(y))
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")


def _text(s: Any) -> str:
    return " ".join(_html.unescape(_TAG.sub(" ", str(s or ""))).split())


def _attrs(tag: str) -> dict:
    return {k.lower(): _html.unescape(v) for k, v in re.findall(r'([A-Za-z_:$-]+)\s*=\s*"([^"]*)"', tag)}


def hidden_fields(page: str) -> dict:
    """Every hidden input of a WebForms page (view state, event validation ...)."""
    out = {}
    for tag in re.findall(r"<input[^>]*>", page or "", re.I):
        a = _attrs(tag)
        if a.get("type", "").lower() == "hidden" and a.get("name"):
            out[a["name"]] = a.get("value", "")
    return out


def search_form(form_page: str, parcel: str) -> dict:
    """The POST body of a Parcel ID search from the search form page."""
    f = hidden_fields(form_page)
    for k in _SEARCH_FIELDS:
        f[_CTRL + k] = ""
    f[PARCEL_FIELD] = parcel
    f[SEARCH_BUTTON] = "Search"
    return f


def view_form(browse_page: str, target: str) -> dict:
    """The POST body of a View Bill postback from the browse page."""
    f = hidden_fields(browse_page)
    f["__EVENTTARGET"] = target
    f["__EVENTARGUMENT"] = ""
    return f


def _money(v: Any) -> Optional[float]:
    s = re.sub(r"[^\d.\-]", "", str(v or ""))
    if not s or s in (".", "-"):
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _date(v: Any) -> Optional[date]:
    s = str(v or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


_TARGET = re.compile(r"__doPostBack\(&#39;([^&]*ViewBillLinkButton)&#39;|__doPostBack\('([^']*ViewBillLinkButton)'")


def parse_grid(page: str) -> Optional[list[dict]]:
    """The bills of a ParcelBrowse page, or None when the page holds no bills grid."""
    i = (page or "").find("BillsGridView")
    if i < 0:
        return None
    start = page.rfind("<table", 0, i)
    grid = page[start:page.find("</table>", i) + 8]
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", grid, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 6:
            continue
        m = _TARGET.search(tr)
        year = tc.to_int(_text(tds[4]))
        if not m or not 1900 < year < 2100:
            continue
        out.append({"address": _text(tds[0]) or None, "unit": _text(tds[1]) or None,
                    "owner": _text(tds[2]) or None, "parcel": _text(tds[3]), "year": year,
                    "type": _text(tds[5]).upper(), "target": m.group(1) or m.group(2)})
    return out


def _span(page: str, suffix: str) -> Optional[str]:
    m = re.search(r'id="[^"]*' + re.escape(suffix) + r'"[^>]*>([^<]*)<', page or "")
    return _text(m.group(1)) if m else None


def parse_bill(page: str) -> Optional[dict]:
    """A ViewBill page: year, bill, owner, parcel, the TOTAL row, Pay By, the unpaid-bills message."""
    year = tc.to_int(_span(page, "ViewBill1_FiscalYearLabel"))
    if not 1900 < year < 2100:
        return None
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page[page.find("BillDetailsUpdatePanel"):], re.S):
        tds = [_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if tds:
            rows.append(tds)
    total = next((r for r in rows if r and r[0].upper() == "TOTAL"), None)
    if total is None or len(total) < 6:
        return None
    pay_by = next((_date(r[1]) for r in rows if len(r) >= 7 and r[0].isdigit()), None)
    amount, credits, balance, interest, due = (_money(x) for x in total[1:6])
    msg = _text(re.search(r'BlockageMessageParagraph"[^>]*>(.*?)</p>', page, re.S).group(1)) \
        if re.search(r'BlockageMessageParagraph"[^>]*>(.*?)</p>', page, re.S) else ""
    low = msg.lower()
    return {"year": year, "bill": _span(page, "ViewBill1_BillNumberLabel"),
            "owner": _span(page, "ViewBill1_OwnerLabel") or None,
            "parcel": _span(page, "ViewBill1_CategoryLabel"),
            "amount": amount, "credits": credits, "balance": balance or 0.0,
            "interest": interest or 0.0, "due": due or 0.0,
            "pay_by": pay_by.isoformat() if pay_by else None,
            "prior_unpaid": "unpaid" in low and "prior" in low,
            "newer_unpaid": "unpaid" in low and "newer" in low}


def parse_payments(page: str) -> Optional[list[dict]]:
    """The activity rows of a ViewPayments page: [{type, posted, amount}] (Paid By is never read),
    or None when the page holds no activity table."""
    i = (page or "").find(">Activity<")
    if i < 0:
        return None
    table = page[page.rfind("<table", 0, i):page.find("</table>", i)]
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        tds = [_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) < 3:
            continue
        posted = _date(tds[1])
        if posted is None:
            continue
        out.append({"type": tds[0], "posted": posted.isoformat(), "amount": _money(tds[-1])})
    return out


def payment_check(year: int, county: str, activity: list[dict], pay_by: Optional[str] = None) -> dict:
    """Late-payment evidence of a paid bill: paid late when a Payment is posted on or after the
    bill's delinquency date. That date is the statute's (tax_calendar, NC: January 6 of Y+1),
    moved later only when the county's own Pay By date on the bill is later (New Hanover rolls a
    weekend deadline to the Monday: Pay By 1/6/2025 for levy 2024, 1/7/2019 for levy 2018; a
    payment that day is on time by the county's own record). A Pay By earlier than the statute
    is ignored."""
    begin = tax_calendar.delinquent_after(year, "NC", county)
    pb = _date(pay_by) if pay_by and "/" in str(pay_by) else (date.fromisoformat(pay_by) if pay_by else None)
    if pb is not None and pb >= begin:
        begin = pb + timedelta(days=1)
    pays = sorted(a["posted"] for a in activity if a["type"].strip().lower() == "payment")
    late = [d for d in pays if date.fromisoformat(d) >= begin]
    out: dict[str, Any] = {"paid_on": pays[-1] if pays else None, "delinquent_from": begin.isoformat(),
                           "paid_late": bool(late)}
    if pb is not None:
        out["pay_by"] = pb.isoformat()
    if late:
        out.update(late_payment_dates=late[:4], last_late_payment_on=late[-1])
    if not pays:
        out["no_payment_on_bill"] = True
    return out


# ---------------------------------------------------------------------------
# fetching (one session per portal per run, cache, health)
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


class _State:
    def __init__(self) -> None:
        self.cm: Any = None
        self.session: Any = None
        self.opened = 0.0
        self.failures = 0
        self.dead: Optional[str] = None
        self.parcel: Optional[str] = None      # the parcel whose search the session holds
        self.browse: Optional[str] = None
        self.browse_url: Optional[str] = None
        self.selected: Optional[tuple] = None  # the bill ViewPayments would show (the last viewed)


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _run(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {"cache": {}, "portals": {}})
    except TypeError:
        return {"cache": {}, "portals": {}}


def _state(client: Any, portal: Portal) -> _State:
    return _run(client)["portals"].setdefault(portal.county, _State())


async def _session(client: Any, portal: Portal) -> Any:
    st = _state(client, portal)
    if st.dead:
        raise PortalDown(st.dead)
    if st.session is None or time.monotonic() - st.opened > SESSION_MAX_AGE_S:
        if st.cm is not None:
            try:
                await st.cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        cm = client.form_session()
        st.session = await cm.__aenter__()
        st.cm, st.opened, st.parcel, st.selected = cm, time.monotonic(), None, None
    return st.session


def _failed(client: Any, portal: Portal, why: str) -> None:
    st = _state(client, portal)
    st.failures += 1
    st.session, st.parcel, st.selected = None, None, None
    if st.failures >= PORTAL_MAX_FAILURES:
        st.dead = f"{st.failures} failures in a row this run, last {why}"[:200]


async def search(client: Any, portal: Portal, parcel: str) -> list[dict]:
    """The bills of exactly this parcel (all years), and the session left on its browse page."""
    st = _state(client, portal)
    try:
        s = await _session(client, portal)
        r = await s.get(portal.base + FORM, timeout=TIMEOUT_S)
        if r.status != 200 or PARCEL_FIELD.replace("$", "_") not in r.text.replace("$", "_"):
            raise RuntimeError(f"search form HTTP {r.status}")
        r = await s.post_form(portal.base + FORM, search_form(r.text, parcel), timeout=TIMEOUT_S)
        if r.status != 200:
            raise RuntimeError(f"search HTTP {r.status}")
        grid = parse_grid(r.text)
        if grid is None:
            raise ValueError("no bills grid on the answer")
    except PortalDown:
        raise
    except Exception as exc:  # noqa: BLE001
        _failed(client, portal, f"{type(exc).__name__}: {str(exc)[:120]}")
        raise
    st.failures = 0
    st.parcel, st.browse, st.browse_url = parcel, r.text, (r.url or portal.base + BROWSE)
    want = tc.alnum(parcel)
    return [b for b in grid if tc.alnum(b["parcel"]) == want]


async def view(client: Any, portal: Portal, parcel: str, bill: dict) -> dict:
    """One bill's page (cached per run); re-runs the parcel search when the session moved on."""
    run = _run(client)
    ck = ("bill", portal.county, tc.alnum(parcel), bill["year"], bill["target"])
    if ck in run["cache"]:
        return run["cache"][ck]
    st = _state(client, portal)
    if st.parcel != parcel or st.session is None:
        await search(client, portal, parcel)
    s = await _session(client, portal)
    r = await s.post_form(st.browse_url, view_form(st.browse, bill["target"]), timeout=TIMEOUT_S)
    page = parse_bill(r.text) if r.status == 200 else None
    if page is None:
        st.parcel = None                     # the session is somewhere else now
        raise ValueError(f"bill page unreadable (HTTP {r.status})")
    run["cache"][ck] = page
    st.selected = ck                         # ViewPayments shows the last bill viewed
    return page


async def payments(client: Any, portal: Portal, parcel: str, bill: dict) -> list[dict]:
    """The activity of one bill (cached per run): its view selects it, then ViewPayments."""
    run = _run(client)
    ck = ("pay", portal.county, tc.alnum(parcel), bill["year"], bill["target"])
    if ck in run["cache"]:
        return run["cache"][ck]
    st = _state(client, portal)
    vk = ("bill", portal.county, tc.alnum(parcel), bill["year"], bill["target"])
    if st.selected != vk or st.parcel != parcel:
        run["cache"].pop(vk, None)
        await view(client, portal, parcel, bill)
    s = await _session(client, portal)
    r = await s.get(portal.base + PAYMENTS, timeout=TIMEOUT_S)
    act = parse_payments(r.text) if r.status == 200 else None
    if act is None:
        raise ValueError(f"payments page unreadable (HTTP {r.status})")
    run["cache"][ck] = act
    return act


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "county", "tax_parcel", "board_parcel", "claim_block_other_parcel",
         "latest_levy_year", "latest_delinquent_eligible_levy", "delinquent_by_year",
         "total_delinquent", "total_complete", "years_delinquent", "under_500", "de_minimis",
         "claimed_years", "bills_checked", "bills_viewed", "owner_match",
         "note", "error", "portal_health", "address_relation", "address_binding",
         "history_from_levy", "history_bills_read", "history_complete", "late_levy_years",
         "late_payment_dates", "chronic_claim", "current_claim_basis", "tax_parcel_row_own",
         "owner_corroborated_by")


def public_evidence(ev: dict) -> dict:
    return tc.pick(ev, _KEYS)


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, public_evidence(ev), source=SOURCE, version=VERSION,
                  verifier=_NAME)


def _regular(b: dict) -> bool:
    return "REAL ESTATE" in b["type"] and "DISCOVER" not in b["type"]


def _current_address(bills: list[dict]) -> Optional[str]:
    if not bills:
        return None
    top = max(b["year"] for b in bills)
    return next((b["address"] for b in bills if b["year"] == top and b.get("address")), None)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    portal = portal_of(row)
    claimed = claimed_years(row)
    ev: dict[str, Any] = {"county": portal.county if portal else row.get("county"),
                          "board_parcel": row.get("parcel_id"), "claimed_years": claimed}
    if roll_block(row) is not None and own_block(row) is None:
        ev["claim_block_other_parcel"] = True
    if portal is None:
        return _res("unconfirmed", dict(ev, reason="no_portal"))
    ev["url"] = portal.base + FORM.split("?")[0]
    parcel = str(row.get("parcel_id") or "").strip()
    if not tc.alnum(parcel) or set(tc.alnum(parcel)) <= {"0"}:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))
    parcel = search_id(parcel)
    try:
        bills = await search(client, portal, parcel)
    except PortalDown as exc:
        return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200]))
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                        error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    bills = [b for b in bills if "REAL ESTATE" in b["type"]]
    if not bills:
        return _res("unconfirmed", dict(ev, reason="parcel_not_found"))
    ev["tax_parcel"] = bills[0]["parcel"]
    exact = not tc.parcel_resolved(row)
    ev["tax_parcel_row_own"] = True
    try:
        return await _decide(row, client, portal, parcel, bills, claimed, today, ev, exact)
    except PortalDown as exc:
        return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200]))


async def _decide(row: dict, client, portal: Portal, parcel: str, bills: list[dict],
                  claimed: list[int], today: date, ev: dict, exact: bool) -> VerificationResult:
    county = portal.county
    newest = max(b["year"] for b in bills)
    ev["latest_levy_year"] = newest
    last_ok = tax_calendar.latest_delinquent_levy_year("NC", county, today)
    late = sorted((b for b in bills if _regular(b)
                   and tax_calendar.levy_year_is_delinquent(b["year"], "NC", county, today)),
                  key=lambda b: -b["year"])

    # the address the parcel carries today (the newest year's bill) against the row's
    addr = row.get("street_address")
    county_addr = _current_address(bills)
    rel = (tc.address_relation(addr, county_addr) if tc.address_query(addr) else "unknown")
    if tc.address_query(addr):
        ev["address_relation"] = rel

    # balances: views from the newest late year down while older unpaid bills exist
    delinquent: dict[int, float] = {}
    owed_owners: list[Any] = []
    viewed: dict[int, dict] = {}
    complete_total = True
    views = 0
    for b in late:
        if views >= MAX_VIEWS:
            complete_total = False
            break
        try:
            page = await view(client, portal, parcel, b)
        except PortalDown:
            raise
        except Exception as exc:  # noqa: BLE001
            if not viewed:
                return _res("unconfirmed", dict(ev, reason="bill_page_unreadable",
                                                error=f"{type(exc).__name__}: {str(exc)[:120]}"))
            complete_total = False
            break
        views += 1
        viewed[b["year"]] = page
        if page["due"] > 0:
            delinquent[b["year"]] = round(delinquent.get(b["year"], 0.0) + page["due"], 2)
            owed_owners.append(page["owner"])
        if not page["prior_unpaid"]:
            break                           # no older unpaid bill: the rest are paid
    ev["bills_viewed"] = views
    latest_owner = next((b["owner"] for b in sorted(bills, key=lambda b: -b["year"]) if b.get("owner")), None)
    ev["owner_match"] = tc.owner_category(row.get("owner_name"), [latest_owner, *owed_owners])
    ev["delinquent_by_year"] = {str(y): a for y, a in sorted(delinquent.items(), reverse=True)}
    ev["total_delinquent"] = tc.money_total(delinquent)
    ev["years_delinquent"] = len(delinquent)
    if delinquent and not complete_total:
        ev["total_complete"] = False

    if delinquent:
        # the row's own parcel number binds `confirmed` whatever address the county printed; a
        # resolver's parcel needs the row's address on the bills
        if exact:
            _bind = "parcel_number"
        elif rel == "match":
            _bind = "bill_address"
        else:
            return _res("unconfirmed", dict(ev, reason="address_parcel_mismatch"
                                            if rel == "conflict" else "parcel_unbound"))
        ev["address_binding"] = _bind
        ev["under_500"] = ev["total_delinquent"] < 500
        ev["de_minimis"] = ev["total_delinquent"] < tc.DE_MINIMIS
        cat = ev.get("owner_match")
        if cat not in (None, "same"):
            if not exact:
                return _res("unconfirmed", dict(ev, reason="bill_owner_differs" if cat == "different"
                                                else "bill_owner_partial"))
            ev["owner_corroborated_by"] = "pin_exact"
        return _res("confirmed", ev)
    if late and not viewed:
        return _res("unconfirmed", dict(ev, reason="bill_page_unreadable"))
    if not complete_total:
        return _res("unconfirmed", dict(ev, reason="older_bills_unread"))

    # nothing late is owed: stale / refuted need the parcel to be the row's property
    if rel == "match":
        ev["address_binding"] = "bill_address"
    elif rel == "unknown" and exact and not tc.address_query(addr):
        ev["address_binding"] = "no_row_address"
    elif rel == "unknown" and exact:
        ev["address_binding"] = "unverified"
    else:
        return _res("unconfirmed", dict(ev, reason="address_parcel_mismatch" if rel == "conflict"
                                        else "parcel_unbound"))
    if newest < last_ok or not late:
        return _res("unconfirmed", dict(ev, reason="parcel_record_ended",
                                        latest_delinquent_eligible_levy=last_ok))
    if any(p.get("newer_unpaid") for p in viewed.values()):
        ev["note"] = "a newer bill is unpaid; it is not late yet"

    by_year = {}
    for b in late:
        by_year.setdefault(b["year"], b)
    order = [y for y in claimed if y in by_year]
    for y in sorted(by_year, reverse=True)[:2]:
        if y not in order:
            order.append(y)
    decision = order[:MAX_BILL_CHECKS]
    claimed_set = set(claimed)
    extra = sorted((y for y in by_year if y not in decision
                    and (y >= tc.HISTORY_FROM_LEVY or y in claimed_set)), reverse=True)
    todo = (decision + extra)[:MAX_PAYMENT_PAGES]
    truncated = len(decision) + len(extra) > len(todo)
    checked = []
    for y in todo:
        b = by_year[y]
        try:
            page = viewed.get(y) or await view(client, portal, parcel, b)
            act = await payments(client, portal, parcel, b)
        except PortalDown:
            raise
        except Exception as exc:  # noqa: BLE001
            checked.append({"year": y, "error": f"{type(exc).__name__}: {str(exc)[:100]}"})
            continue
        checked.append({"year": y, **payment_check(y, county, act, page.get("pay_by"))})
    ok = [c for c in checked if "error" not in c]
    late_years = {c["year"]: c for c in ok if c["paid_late"]}
    complete = not truncated and len(ok) == len(checked)
    ev["bills_checked"] = checked
    ev.update(history_from_levy=tc.HISTORY_FROM_LEVY, history_bills_read=len(ok),
              history_complete=complete, late_levy_years=sorted(late_years),
              late_payment_dates={str(y): late_years[y]["late_payment_dates"] for y in sorted(late_years)},
              chronic_claim=tc.history_claims(late_years, complete))
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
    ev["current_claim_basis"] = ("claimed_years_on_time" if claimed_set & set(decision)
                                 else "latest_year_on_time")
    return _res("refuted", ev)
