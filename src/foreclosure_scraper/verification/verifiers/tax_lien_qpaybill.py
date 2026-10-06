"""tax_lien, SC counties on the qPayBill treasurer portal: is there a real delinquent property-tax
balance on this parcel?

The third tax_lien adapter (the reference is tax_lien_buncombe; docs/HANDOFF.md item 66). Same
SIGNAL, same GOVERNS, same verdict meanings, so its verdicts land in the one tax_lien ledger.

SOURCE. <tenant>.qpaybill.com/Taxes/TaxesDefaultType4.aspx, the county treasurer's own public
payment search (the one counties_sc.qpaybill_delinquent_roll enumerates; the tenant map is that
module's QPAYBILL_SUBS, 29 counties). An ASP.NET WebForms page: no login, no CAPTCHA, a session
cookie and a viewstate. NOT the SC Public Index (that one stays off-limits). The per-parcel
lookup, live-verified 2026-10-06:

    GET  the form                                    -> session cookie + viewstate
    POST __EVENTTARGET=ddlCriteriaList, Map Number   -> the criteria postback (a search posted
                                                        without it answers "No records matched"
                                                        even for a parcel on the roll)
    POST SearchType=Real Estate, Payment Status=All, Year=All, Search By=Map Number, <TMS>
        -> the grid: Notice | Name/Address | Year | Description | Identification No. | Type |
           Status (Unpaid / Paid / Sold at Tax Sale ...) | Payment Date | Amount
           every year on that map number, paid AND unpaid, sorted by identification number then
           year, newest first; 25 rows a page. The search also returns longer numbers that start
           with the same text ("45-338-010" brings "45-338-010.A"), so only rows whose
           identification number equals the one asked for are read.

One session per tenant and search criteria per sweep run (opened on the first row that needs it,
reused, re-opened after 15 minutes), so a parcel costs one request after two per county. Requests are one at a
time per host, paced by the sweep's Fetcher. A tenant that answers an error page
(GenericErrorPage.aspx, Williamsburg's known failure), an HTTP error, or fails twice in a run is
skipped for the rest of the run: its rows answer unconfirmed (tenant_unhealthy), never refuted.

WHICH ROWS. SC rows in a qPayBill county whose tax claim the county record can answer
(verifiers/_tax_common.py: a tax_lien/tax_sale listing type that is not a DEW / DOR lien, a
delinquency flag, or the roll's own qpaybill_roll block for this county). NC rows are never
touched (tax_lien_buncombe / tax_lien_ptscloud).

WHICH PARCEL. The claim's own identification number (the roll block's identification_no) and the
board's parcel_id (Cherokee's 13-digit numeric form re-dashed as enrichment_qpaybill_tax does).
They differ on 3,995 of the roll's own rows (a resolver gave the row another parcel, often by a
road name), so when they differ BOTH are searched:
    both delinquent -> confirmed; neither -> stale/refuted read on the claim's parcel
    one delinquent, the other found and not -> unconfirmed (identity_conflict: which parcel the
        row really is cannot be told here, so nothing is decided and nothing suppressed)
    only one found -> decided on that one
Some tenants' grid identification number is not their Map Number (Horry shows the PIN in the
grid and searches the TMS; Orangeburg shows an account number): when the claim's number finds
nothing, the claim's own bills are read by notice number instead (Search By = Receipt Number,
the block's notice_numbers, newest 2), which answers exactly the claimed bills.

VERDICTS (SC real-property tax is due January 15 of the next year, S.C. Code 12-45-70; unpaid
after it, penalties attach, so a levy-year Y bill is delinquent from January 16 of Y+1; a
deadline on a weekend rolls to Monday):
  confirmed    an Unpaid (or Delinquent / Bankruptcy) row of a delinquent-eligible year with an
               amount, or a Sold-at-Tax-Sale row of one of the last three eligible years (inside
               the 12-month redemption window); see identity_conflict above.
  stale        nothing delinquent today, and the claimed year (else the latest delinquent-eligible
               year) was paid after its deadline: the delinquency was real, paid since.
  refuted      nothing delinquent today and the year(s) checked were paid by the deadline.
  unconfirmed  no identifier, not on the portal, tenant unhealthy, page unreadable, a full page
               that may hide older years, billing ended before the latest eligible levy, no paid
               row to read, identity_conflict; or a refuted/stale answer on a row typed by a DEW /
               DOR lien source (other_lien_listing, see _tax_common).
Evidence (public ledger: a whitelist, no names, no addresses): the portal URL, tenant, the map
numbers searched and what each showed, per-year delinquent amounts, total, years, the
not-yet-delinquent current levy, tax-sale years, claimed years, the paid rows read (payment date,
deadline, late or not), and the county owner vs board owner CATEGORY only.
"""
from __future__ import annotations

import asyncio
import html as _html
import re
import time
import weakref
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Optional

from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
SOURCE = "qpaybill.com"
GOVERNS = ("tax_lien", "tax_sale", "tax_lien_chronic", "recorded_debt:tax")
ROW_SUMMARY_EXCLUDE = ("owner_name",)

ROLL_SLUG = "counties_sc.qpaybill_delinquent_roll"
ROLL_KEY = "qpaybill_roll"
PAGE_CAP = 25
SESSION_MAX_AGE_S = 15 * 60
TENANT_MAX_FAILURES = 2
GET_TIMEOUT_S = 45.0
POST_TIMEOUT_S = 60.0          # Darlington answers slowly but correctly (8028596d)
RECENT_SALE_YEARS = 3          # Sold-at-Tax-Sale rows still inside redemption

_NAME = __name__.rsplit(".", 1)[-1]

_CRITERIA = "ctl00$MainContent$ddlCriteriaList"
_GRID_ID = "ctl00_MainContent_gvSearchResults"
_NO_MATCH = "No records matched"


@lru_cache(maxsize=1)
def tenants() -> dict[str, tuple[str, str]]:
    """{county lowercased: (County, qpaybill subdomain)} from the roll scraper's QPAYBILL_SUBS."""
    from ...scrapers.counties_sc.qpaybill_delinquent_roll import QPAYBILL_SUBS
    return {c.strip().lower(): (c, s) for c, s in QPAYBILL_SUBS.items()}


def form_url(sub: str) -> str:
    return f"https://{sub}.qpaybill.com/Taxes/TaxesDefaultType4.aspx"


# ---------------------------------------------------------------------------
# which rows, which parcels (pure)
# ---------------------------------------------------------------------------

def tenant_of(row: Any) -> Optional[tuple[str, str]]:
    if str(tc.g(row, "state") or "").strip().upper() != "SC":
        return None
    return tenants().get(str(tc.g(row, "county") or "").strip().lower())


def roll_block(row: Any) -> Optional[dict]:
    """The roll's block when it is about this row's county (94 board rows carry another
    county's block after a merge; those are not this row's claim)."""
    b = tc.raw_of(row).get(ROLL_KEY)
    if not isinstance(b, dict) or not b.get("identification_no"):
        return None
    if str(b.get("county") or "").strip().lower() != str(tc.g(row, "county") or "").strip().lower():
        return None
    return b


def applies(row: dict) -> bool:
    return tenant_of(row) is not None and tc.claims_property_tax(row, roll_block(row) is not None)


def board_parcel(row: Any, county: str) -> Optional[str]:
    pid = str(tc.g(row, "parcel_id") or "").strip()
    if not pid:
        return None
    try:
        from ...enrichment_qpaybill_tax import _norm_pid     # Cherokee: 13 digits -> dashed TMS
        pid = _norm_pid("SC", county, pid)
    except Exception:  # noqa: BLE001
        pass
    return pid or None


def subjects(row: Any, county: str) -> list[tuple[str, str]]:
    """[(map number, 'claim' | 'board')]: the claim's own identification number first."""
    blk = roll_block(row)
    out: list[tuple[str, str]] = []
    if blk:
        out.append((str(blk["identification_no"]).strip(), "claim"))
    bp = board_parcel(row, county)
    if bp and all(tc.alnum(bp) != tc.alnum(v) for v, _ in out):
        out.append((bp, "board"))
    return [(v, r) for v, r in out if tc.alnum(v) and set(tc.alnum(v)) != {"0"}]


def claimed_years(row: Any) -> list[int]:
    years = tc.claimed_years_common(row) | tc.source_block_years(row)
    blk = roll_block(row)
    if blk:
        years.update(tc.to_int(y) for y in blk.get("years_unpaid") or [])
    return sorted((y for y in years if 1990 < y < 2100), reverse=True)


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

_HIDDEN = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")


def viewstate(text: str) -> dict:
    out = {}
    for n in _HIDDEN:
        m = re.search(rf'id="{n}"[^>]*value="([^"]*)"', text)
        out[n] = m.group(1) if m else ""
    return out


def _fields(value: str, criteria: str = "Map") -> dict:
    return {"ctl00$MainContent$SearchType": "radRealEstateButton",
            "ctl00$MainContent$PaidStatus": "radAllPaymentsButton",
            "ctl00$MainContent$ddlYearList": "All",
            _CRITERIA: criteria,
            "ctl00$MainContent$txtCriteriaBox": value}


def criteria_data(state: dict, criteria: str = "Map") -> dict:
    return {"__EVENTTARGET": _CRITERIA, "__EVENTARGUMENT": "", "__LASTFOCUS": "", **state,
            **_fields("", criteria)}


def search_data(state: dict, value: str, criteria: str = "Map") -> dict:
    return {"__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "", **state,
            **_fields(value, criteria), "ctl00$MainContent$btnSearch": "Search"}


def _clean(x: str) -> str:
    x = re.sub(r"(?i)<br\s*/?>", "\n", x)
    x = _html.unescape(re.sub(r"<[^>]+>", " ", x))
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", p).strip() for p in x.split("\n")).strip()


def _date(s: str) -> Optional[date]:
    s = (s or "").strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _amount(s: str) -> Optional[float]:
    m = re.search(r"\$?\s*([\d,]+\.\d{2})", s or "")
    return float(m.group(1).replace(",", "")) if m else None


def parse_grid(text: str) -> dict:
    """{'rows': [...], 'no_match': bool, 'grid': bool} from a search answer. Every row, paid or
    not (the roll scraper's parse_grid keeps owed rows only)."""
    no_match = _NO_MATCH in text
    i = text.find(f'id="{_GRID_ID}"')
    if i < 0:
        return {"rows": [], "no_match": no_match, "grid": False}
    j = text.find("</table>", i)          # the pager's own table, if any, comes after the rows
    table = text[i: j if j > 0 else len(text)]
    rows = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", table):
        tds = re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)
        if len(tds) < 9:
            continue
        c = [_clean(t) for t in tds]
        year = tc.to_int(c[2])
        if not 1900 < year < 2100 or not c[4]:
            continue
        rows.append({"notice": c[0] or None, "owner": (c[1].split("\n")[0] or None),
                     "year": year, "ident": c[4], "type": c[5], "status": c[6],
                     "paid_on": _date(c[7]), "amount": _amount(c[8])})
    return {"rows": rows, "no_match": no_match and not rows, "grid": True}


# ---------------------------------------------------------------------------
# the rules (pure)
# ---------------------------------------------------------------------------

def deadline(year: int) -> date:
    """The last day a levy-year bill is paid on time: January 15 of the next year (S.C. Code
    12-45-70), a weekend rolled to Monday."""
    return tc.next_weekday(date(year + 1, 1, 15))


def is_eligible(year: int, today: date) -> bool:
    return today > deadline(year)


def latest_eligible(today: date) -> int:
    return today.year - 1 if is_eligible(today.year - 1, today) else today.year - 2


def _kind(status: str) -> str:
    s = (status or "").strip().lower()
    if "sold" in s:
        return "sold"
    if "unpaid" in s or "delinquent" in s or "bankrupt" in s:
        return "owed"
    if s == "paid" or s.startswith("paid"):
        return "paid"
    return "other"


def select_rows(rows: list[dict], ident: str, notices: Optional[set] = None) -> list[dict]:
    """The rows of exactly this identification number (and, for a receipt search, of exactly
    these notice numbers)."""
    want = tc.alnum(ident)
    out = [r for r in rows if tc.alnum(r["ident"]) == want]
    if notices is not None:
        out = [r for r in out if tc.alnum(r["notice"]) in notices]
    return out


def assess(mine: list[dict], today: date) -> dict:
    """What the portal's rows say about one parcel (or one parcel's claimed bills)."""
    out: dict[str, Any] = {"found": bool(mine), "rows": len(mine)}
    if not mine:
        return out
    last_ok = latest_eligible(today)
    delinquent: dict[int, float] = {}
    current: dict[int, float] = {}
    sold: list[int] = []
    for r in mine:
        k, y, amt = _kind(r["status"]), r["year"], r["amount"] or 0.0
        if k == "owed" and amt > 0:
            if is_eligible(y, today):
                delinquent[y] = round(delinquent.get(y, 0.0) + amt, 2)
            else:
                current[y] = round(current.get(y, 0.0) + amt, 2)
        elif k == "sold":
            sold.append(y)
            if y > last_ok - RECENT_SALE_YEARS and amt > 0:
                delinquent[y] = round(delinquent.get(y, 0.0) + amt, 2)
    out.update(latest_levy_year=max(r["year"] for r in mine),
               delinquent_by_year={str(y): a for y, a in sorted(delinquent.items(), reverse=True)},
               not_yet_delinquent_due={str(y): a for y, a in sorted(current.items(), reverse=True)},
               owners=[r["owner"] for r in sorted(mine, key=lambda r: -r["year"])[:2]])
    if sold:
        out["sold_at_tax_sale_years"] = sorted(set(sold), reverse=True)
    by_year: dict[int, list[dict]] = {}
    for r in mine:
        by_year.setdefault(r["year"], []).append(r)
    out["_by_year"] = by_year
    return out


def page_capped(rows: list[dict], ident: str, capped: bool) -> bool:
    """A full page whose last row is still this parcel may hide its older years on page 2."""
    return bool(capped and rows and tc.alnum(rows[-1]["ident"]) == tc.alnum(ident))


def paid_check(by_year: dict, year: int) -> Optional[dict]:
    """The year's paid rows: late (after the deadline) or on time; None when none is readable."""
    paid = [r for r in by_year.get(year, []) if _kind(r["status"]) == "paid" and r["paid_on"]]
    if not paid:
        return None
    dl = deadline(year)
    last = max(r["paid_on"] for r in paid)
    return {"year": year, "status": "Paid", "paid_on": last.isoformat(), "deadline": dl.isoformat(),
            "paid_late": last > dl}


# ---------------------------------------------------------------------------
# the tenant sessions (one per county and search criteria per sweep run)
# ---------------------------------------------------------------------------

class TenantDown(RuntimeError):
    pass


class _Session:
    def __init__(self) -> None:
        self.cm: Any = None
        self.session: Any = None
        self.state: dict = {}
        self.opened = 0.0


class _Tenant:
    def __init__(self, county: str, sub: str) -> None:
        self.county, self.sub, self.url = county, sub, form_url(sub)
        self.sessions: dict[str, _Session] = {}
        self.failures = 0
        self.dead: Optional[str] = None
        self.lock = asyncio.Lock()
        self.cache: dict[tuple[str, str], dict] = {}


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _tenant(client: Any, county: str, sub: str) -> _Tenant:
    try:
        per_run = _RUNS.setdefault(client, {})
    except TypeError:                                   # not weak-referenceable: no sharing
        per_run = {}
    t = per_run.get(sub)
    if t is None:
        t = per_run[sub] = _Tenant(county, sub)
    return t


def _problem(resp: Any) -> Optional[str]:
    if resp.status >= 400:
        return f"http_{resp.status}"
    if "genericerrorpage" in str(resp.url).lower() or "GenericErrorPage" in resp.text[:20000]:
        return "generic_error_page"
    if "__VIEWSTATE" not in resp.text:
        return "no_form_on_page"
    return None


async def _close(s: _Session) -> None:
    cm, s.cm, s.session = s.cm, None, None
    if cm is not None:
        try:
            await cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


async def _open(t: _Tenant, s: _Session, client: Any, criteria: str) -> None:
    await _close(s)
    s.cm = client.form_session()
    s.session = await s.cm.__aenter__()
    r = await s.session.get(t.url, timeout=GET_TIMEOUT_S)
    if (p := _problem(r)) is not None or _CRITERIA not in r.text:
        raise TenantDown(p or "no_search_form")
    r = await s.session.post_form(t.url, criteria_data(viewstate(r.text), criteria),
                                  timeout=POST_TIMEOUT_S)
    if (p := _problem(r)) is not None:
        raise TenantDown(p)
    s.state = viewstate(r.text)
    s.opened = time.monotonic()


async def search(client: Any, county: str, sub: str, value: str, criteria: str = "Map") -> dict:
    """The grid for one search (cached for the run). Raises TenantDown when the tenant is (or
    just became) unhealthy, another exception for a one-off failure."""
    t = _tenant(client, county, sub)
    async with t.lock:
        key = (criteria, value)
        if key in t.cache:
            return t.cache[key]
        if t.dead:
            raise TenantDown(t.dead)
        s = t.sessions.setdefault(criteria, _Session())
        try:
            if s.session is None or time.monotonic() - s.opened > SESSION_MAX_AGE_S:
                await _open(t, s, client, criteria)
            r = await s.session.post_form(t.url, search_data(s.state, value, criteria),
                                          timeout=POST_TIMEOUT_S)
            if (p := _problem(r)) is not None:
                raise TenantDown(p)
            g = parse_grid(r.text)
            if not g["grid"] and not g["no_match"]:
                raise TenantDown("search_answer_unreadable")
        except Exception as exc:  # noqa: BLE001
            t.failures += 1
            why = f"{type(exc).__name__}: {str(exc)[:120]}"
            if (isinstance(exc, TenantDown) and str(exc) == "generic_error_page") \
                    or t.failures >= TENANT_MAX_FAILURES:
                t.dead = f"{why} ({t.failures} failure(s) this run)"
            await _close(s)                 # a fresh session next time
            raise
        t.failures = 0
        new = viewstate(r.text)
        if new.get("__VIEWSTATE"):
            s.state = new
        out = {"rows": g["rows"], "no_match": g["no_match"], "capped": len(g["rows"]) >= PAGE_CAP}
        t.cache[key] = out
        return out


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "tenant", "county", "searched", "decided_on", "delinquent_parcel",
         "claim_ident",
         "board_parcel", "latest_levy_year", "latest_delinquent_eligible_levy",
         "delinquent_by_year", "total_delinquent", "years_delinquent", "under_500", "de_minimis",
         "not_yet_delinquent_due", "sold_at_tax_sale_years", "claimed_years", "bills_checked",
         "owner_match", "note", "error", "tenant_health", "property_tax_verdict",
         "listing_claim_source")
_SEARCHED_KEYS = ("map_number", "receipt", "role", "found", "rows", "latest_levy_year",
                  "delinquent_by_year", "not_yet_delinquent_due", "sold_at_tax_sale_years",
                  "page_capped")
MAX_RECEIPTS = 2


def public_evidence(ev: dict) -> dict:
    out = tc.pick(ev, _KEYS)
    if isinstance(out.get("searched"), list):
        out["searched"] = [tc.pick(s, _SEARCHED_KEYS) for s in out["searched"]]
    return out


def _res(verdict: str, ev: dict, row: Any = None) -> VerificationResult:
    if verdict in ("refuted", "stale") and row is not None and tc.other_lien_listing(row):
        ev = dict(ev, property_tax_verdict=verdict, reason="other_lien_listing",
                  listing_claim_source=tc.g(row, "source"))
        verdict = "unconfirmed"
    return result(SIGNAL, verdict, public_evidence(ev), source=SOURCE, version=VERSION,
                  verifier=_NAME)


def claim_receipts(row: Any) -> list[str]:
    """The roll block's notice numbers, newest first (the block lists them oldest first)."""
    blk = roll_block(row) or {}
    return [str(n).strip() for n in reversed(blk.get("notice_numbers") or []) if str(n).strip()]


def _decide_paid(a: dict, claimed: list[int], today: date) -> tuple[str, list[dict]]:
    """('stale' | 'refuted' | 'none', checks) on one parcel with nothing delinquent."""
    by_year = a.get("_by_year") or {}
    # the claimed years, then the two latest delinquent-eligible ones (the grid already holds
    # every payment date, so reading more years costs no request)
    order = [y for y in claimed if is_eligible(y, today) and y in by_year]
    for y in sorted((y for y in by_year if is_eligible(y, today)), reverse=True)[:2]:
        if y not in order:
            order.append(y)
    checks = []
    for y in order[:4]:
        c = paid_check(by_year, y)
        if c is None:
            kinds = sorted({r["status"] for r in by_year.get(y, [])})
            checks.append({"year": y, "status": ", ".join(kinds) or None, "paid_late": None})
            continue
        checks.append(c)
        if c["paid_late"]:
            return "stale", checks
    if any(c.get("paid_late") is False for c in checks):
        return "refuted", checks
    return "none", checks


async def _lookup(client: Any, county: str, sub: str, value: str, role: str, today: date,
                  *, criteria: str = "Map", notices: Optional[set] = None) -> dict:
    g = await search(client, county, sub, value, criteria)
    ident = value if criteria == "Map" else None
    if criteria == "Map":
        mine = select_rows(g["rows"], value)
    else:                       # a receipt answers one bill; its row names the claim's ident
        mine = [r for r in g["rows"] if tc.alnum(r["notice"]) in (notices or set())]
    a = assess(mine, today)
    a["role"] = role
    if criteria == "Map":
        a["map_number"] = value
        a["page_capped"] = page_capped(g["rows"], ident or "", g["capped"]) if mine else False
    else:
        a["receipt"] = value
    return a


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    ten = tenant_of(row)
    claimed = claimed_years(row)
    if ten is None:
        return _res("unconfirmed", {"reason": "no_qpaybill_tenant", "claimed_years": claimed})
    county, sub = ten
    url = form_url(sub)
    subs = subjects(row, county)
    blk = roll_block(row)
    claim_ident = (blk or {}).get("identification_no")
    ev: dict[str, Any] = {"url": url, "tenant": sub, "county": county, "claimed_years": claimed,
                          "claim_ident": claim_ident, "board_parcel": board_parcel(row, county)}
    if not subs:
        return _res("unconfirmed", dict(ev, reason="parcel_unresolvable"))

    found: dict[str, dict] = {}
    searched: list[dict] = []
    try:
        for value, role in subs:
            a = await _lookup(client, county, sub, value, role, today)
            searched.append(a)
            if a["found"]:
                found[role] = a
            elif role == "claim":
                # Some tenants' grid identification number is not their Map Number (Horry shows
                # the PIN, searches the TMS): read the claim's own bills by notice number instead.
                for rc in claim_receipts(row)[:MAX_RECEIPTS]:
                    ra = await _lookup(client, county, sub, rc, "claim_receipt", today,
                                       criteria="Receipt", notices={tc.alnum(rc)})
                    searched.append(ra)
                    if ra["found"]:
                        prev = found.get("claim")
                        if prev is None:
                            found["claim"] = dict(ra, via_receipts=True)
                        else:           # merge two receipts of the same claim
                            merged = dict(prev)
                            for k in ("delinquent_by_year", "not_yet_delinquent_due"):
                                merged[k] = {**prev.get(k, {}), **ra.get(k, {})}
                            merged["_by_year"] = {**prev.get("_by_year", {}),
                                                  **ra.get("_by_year", {})}
                            merged["latest_levy_year"] = max(prev["latest_levy_year"],
                                                             ra["latest_levy_year"])
                            found["claim"] = merged
    except TenantDown as exc:
        return _res("unconfirmed", dict(ev, reason="tenant_unhealthy", searched=searched,
                                        tenant_health=str(exc)[:200]))
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", dict(ev, reason="fetch_failed", searched=searched,
                                        error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    ev["searched"] = searched
    if not found:
        return _res("unconfirmed", dict(ev, reason="parcel_not_found"))

    claim, board = found.get("claim"), found.get("board")
    primary = claim or board
    claim_via = "claim_receipts" if (claim or {}).get("via_receipts") else "claim_ident"
    ev["owner_match"] = tc.owner_category(row.get("owner_name"), primary.get("owners") or [])
    dl_claim = bool(claim and claim["delinquent_by_year"])
    dl_board = bool(board and board["delinquent_by_year"])
    if claim is not None and board is not None and dl_claim != dl_board:
        # the source's parcel and the board's parcel disagree: which one the row really is
        # cannot be told from here, so nothing is decided (and nothing suppressed)
        return _res("unconfirmed", dict(ev, reason="identity_conflict",
                                        delinquent_parcel="claim" if dl_claim else "board"))
    if dl_claim or dl_board:
        a = claim if dl_claim else board
        ev.update(decided_on=claim_via if dl_claim else "board_parcel",
                  latest_levy_year=a["latest_levy_year"],
                  delinquent_by_year=a["delinquent_by_year"],
                  not_yet_delinquent_due=a["not_yet_delinquent_due"],
                  sold_at_tax_sale_years=a.get("sold_at_tax_sale_years"))
        ev["total_delinquent"] = tc.money_total(a["delinquent_by_year"])
        ev["years_delinquent"] = len(a["delinquent_by_year"])
        ev["under_500"] = ev["total_delinquent"] < 500
        ev["de_minimis"] = ev["total_delinquent"] < tc.DE_MINIMIS
        return _res("confirmed", ev, row)

    a = primary
    ev.update(decided_on=claim_via if claim else "board_parcel",
              latest_levy_year=a["latest_levy_year"],
              not_yet_delinquent_due=a["not_yet_delinquent_due"],
              sold_at_tax_sale_years=a.get("sold_at_tax_sale_years"),
              delinquent_by_year={}, total_delinquent=0.0, years_delinquent=0)
    if any(s.get("page_capped") for s in searched if s.get("found")):
        return _res("unconfirmed", dict(ev, reason="page_capped"))
    last_ok = latest_eligible(today)
    if not a.get("via_receipts") and a["latest_levy_year"] < last_ok:
        # a receipt answers only the claimed bills, so this history test needs the Map search
        return _res("unconfirmed", dict(ev, reason="parcel_record_ended",
                                        latest_delinquent_eligible_levy=last_ok))
    verdict, checks = _decide_paid(a, claimed, today)
    ev["bills_checked"] = checks
    if verdict == "none":
        return _res("unconfirmed", dict(ev, reason="no_paid_row_to_read"))
    if verdict == "refuted" and a["not_yet_delinquent_due"]:
        ev["note"] = "only the current levy is unpaid; it is not delinquent yet"
    return _res(verdict, ev, row)
