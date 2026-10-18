"""tax_lien, Rowan County NC: is there a real delinquent property-tax balance on this parcel,
read live from the county's own tax-bill search?

A tax_lien adapter beside tax_lien_buncombe (the reference), tax_lien_ptscloud, tax_lien_qpaybill,
tax_lien_itspublic, tax_lien_munis and tax_lien_york: same SIGNAL, same GOVERNS, same verdict
meanings, one tax_lien ledger.

WHY IT EXISTS. Rowan (2,699 claim rows from scrapers/counties_nc/rowan_delinquent_tax.py, the
county's own annual delinquent-taxpayer spreadsheet -- a snapshot, not a live balance) was one of
the 5 counties [[project_tax_claim_no_checker_gap_2026-10-17]] found with no registered tax_lien
verifier at all. An EARLIER same-night attempt noted this county's live tax site as an "ASP.NET
event-validation issue" and moved on rather than guess -- that was a false negative: the actual
blocker was a WRONG URL (POSTing to the pre-redirect `/commonsearch.aspx` 404s; the real endpoint
is `/search/commonsearch.aspx`, reached only via following the homepage's redirect). Once that was
found, the WebForms postback itself (VIEWSTATE/EVENTVALIDATION extracted from a GET and echoed
back on the POST, the standard pattern) worked on the first real try.

THE SITE: tax.rowancountync.gov, a Tyler Technologies "iasWorld" public CAMA/tax search (<meta
name='Copyright' content='Tyler Technologies Inc, Akanda Solutions, LLC'>, <meta name='Description'
content='iasWorld'>) -- a DIFFERENT Tyler product from Munis (tax_lien_munis.py) and unrelated to
ItsPublic (tax_lien_itspublic.py); no sibling verifier handles this platform shape yet. No login,
no CAPTCHA, no click-through disclaimer on the search page itself (tax_lien_munis.py's own
docstring notes iasWorld sites CAN be click-through-gated, e.g. New Hanover's assessment site --
Rowan's is not; live-checked 2026-10-18, not assumed from the platform name alone).

THE CALLS (read from the page's own form, live-verified 2026-10-18):
    GET  {SEARCH_URL}
         -> an ASP.NET WebForms page: __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION
    POST {SEARCH_URL}  {..., inpParid: <board parcel_id>, hdListType: 'realprop', ...}
         -> an HTML results grid (one row per matching parcel; inpParid matches by PREFIX, not
            exact -- "379" alone matched 32 rows live -- so a result is kept only when its own
            Parcel ID column is an exact alnum match of the row's parcel_id). Each row carries an
            onclick `selectSearchRow('../Datalets/Datalet.aspx?sIndex=N&idx=M')`: sIndex is the
            whole result set's id (constant per search), idx is the row's 1-based position --
            together they are this search's only durable handle on one specific parcel's detail
            page, good only within the same cookie session. The grid's own columns, in order:
            Parcel ID, Owner Name, Account #, Parcel Address, TaxYr (the newest levy year, not a
            balance).
    GET  {BASE}/Datalets/Datalet.aspx?mode=tax_bills_int&sIndex=<N>&idx=<M>
         -> the parcel's own "Tax Bills" tab (no mode= is the SAME page: it is iasWorld's own
            default tab for a just-searched parcel, confirmed live): a table of
            {Year, Original Bill, Bill Adjustment, Total Paid, Discount, Interest, Amount Due,
            July Due, Aug Due}, one row per levy year, as far back as the county keeps it
            (6 years live on the test parcel, 2021-2026) -- Amount Due is what is owed on that
            year'y bill TODAY, already netting payments/adjustments/interest; a negative Total
            Paid is simply this table's sign convention for a payment (not a credit).

VERDICTS (a levy-year Y bill is late once unpaid on January 6 of Y+1, G.S. 105-360;
tax_calendar.delinquent_after):
  confirmed    a late levy year's row has Amount Due > 0 on the row's own exact parcel.
  stale        nothing late is owed on the parcel today, and at least one levy year the BOARD's
               own claim named (claimed_years: the roll block's own tax_year/years_unpaid) now
               shows Amount Due == 0 in this table -- the claim was true, and the bill this
               table tracks today says it no longer is.
  refuted      never. This table has no payment-DATE column (unlike tax_lien_itspublic's
               ViewTaxBill "Last Payment Date"), so there is no way to tell a bill paid before
               its delinquency date from one paid after it; the distinction this signal would
               need to answer "refuted" instead of "stale" is not data this source exposes.
               Documented the same way tax_lien_york.py documents its own "refuted: never".
  unconfirmed  no parcel on the row, the live site could not be reached, the row's exact parcel
               was not found in a search, more than one result matched the exact parcel string
               (should not happen -- PINs are unique -- kept as a defensive, never-guess fallback),
               the detail page carried no bill table at all, or none of the board's claimed years
               could be confirmed resolved (nothing late today, but the specific claimed year was
               never found $0 in this table either -- e.g. it predates the table's own window).

tax_lien_chronic is never computed here (this table has no late-payment-date history to judge
a chronic-delinquency claim from, the same reason "refuted" is never produced): governs_for
(_tax_common.governs_for) only ever strips tax_lien_chronic from GOVERNS when a chronic_claim
evidence key is present and resolved "not_confirmed" -- since this verifier never sets that key,
a refuted/stale verdict here never touches another source's chronic-delinquency signal.

Evidence is a whitelist (public ledger): no owner names, no mailing addresses, no account numbers.
"""
from __future__ import annotations

import re
import time
import weakref
from datetime import date
from typing import Any, Optional

from ... import tax_calendar
from ..core import VerificationResult, result
from . import _tax_common as tc

SIGNAL = "tax_lien"
VERSION = "v1"
TTL_DAYS = 30
RETRY_DAYS = 7
SOURCE = "tax.rowancountync.gov (iasWorld)"
GOVERNS = tc.GOVERNS
governs_for = tc.governs_for
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed", "portal_unhealthy")

SOURCE_SLUG = "counties_nc.rowan_delinquent_tax"
BASE = "https://tax.rowancountync.gov"
SEARCH_URL = f"{BASE}/search/commonsearch.aspx?mode=realprop"

MAX_FAILURES = 2
SESSION_MAX_AGE_S = 15 * 60
TIMEOUT_S = 40.0

_NAME = __name__.rsplit(".", 1)[-1]


def applies(row: dict) -> bool:
    return (str(row.get("state") or "").strip().upper() == "NC"
            and str(row.get("county") or "").strip().lower() == "rowan"
            and str(row.get("source") or "") == SOURCE_SLUG
            and tc.claims_property_tax(row, False))


def claimed_years(row: Any) -> list[int]:
    return sorted(tc.claimed_years_common(row) | tc.source_block_years(row), reverse=True)


# ---------------------------------------------------------------------------
# parsing (pure)
# ---------------------------------------------------------------------------

_HIDDEN_NAMES = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")
_HIDDEN_RE = {n: re.compile(rf"(?:id|name)=['\"]{n}['\"][^>]*value=['\"]([^'\"]*)['\"]")
             for n in _HIDDEN_NAMES}
_ROW_MARK = re.compile(r"selectSearchRow\('\.\./Datalets/Datalet\.aspx\?sIndex=(\d+)&idx=(\d+)'\)\"")
_ROW_CELL = re.compile(r"margin-left:3px;'>([^<]*)</div>")
_BILL_CELL = re.compile(r"class=.DataletData.>([^<]*)</td>")
_YEAR = re.compile(r"^\d{4}$")


def _money(v: Any) -> float:
    s = re.sub(r"[^\d.\-]", "", str(v or ""))
    if not s or s in (".", "-"):
        return 0.0
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def hidden_fields(html: str) -> dict[str, str]:
    return {n: (m.group(1) if (m := rx.search(html)) else "") for n, rx in _HIDDEN_RE.items()}


def search_form(hidden: dict[str, str], parid: str) -> dict[str, str]:
    form = dict(hidden)
    form.update({
        "PageNum": "1", "SortDir": "", "PageSize": "25",
        "hdAction": "", "hdIndex": "", "sIndex": "",
        "hdListType": "realprop", "hdJur": "", "hdSelectAllChecked": "0",
        "inpParid": parid, "inpNo": "", "inpStreet": "", "inpZip": "",
        "inpOwner1": "", "inpOwnerNo": "", "inpBook": "", "inpBookPage": "",
        "hdTaxYear": "", "mode": "realprop", "mask": "", "param1": "", "searchimmediate": "0",
        "__EVENTTARGET": "", "__EVENTARGUMENT": "",
    })
    return form


def parse_results(html: str) -> list[dict]:
    """One dict per result row: sIndex, idx (the Datalet detail page's own handle, valid only in
    this session), parcel_id, owner, account, address, tax_year (the grid's own 5 text columns,
    in their live-confirmed order). inpParid matches by prefix: a caller filters to the row whose
    parcel_id is an exact match of the one searched."""
    marks = list(_ROW_MARK.finditer(html))
    out = []
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(html)
        cells = _ROW_CELL.findall(html[start:end])[:5]
        if len(cells) < 5:
            continue
        out.append({"sIndex": m.group(1), "idx": m.group(2), "parcel_id": cells[0],
                    "owner": cells[1], "account": cells[2], "address": cells[3],
                    "tax_year": cells[4]})
    return out


def parse_bills(html: str) -> Optional[list[dict]]:
    """[{year, original_bill, bill_adjustment, total_paid, discount, interest, amount_due,
    july_due, aug_due}] from the TAX_BILLS_INT datalet, oldest-levy-first as the page prints it;
    None when the datalet itself is not on the page (a bad sIndex/idx, or a session that expired
    between the search and this fetch)."""
    i = html.find("name='TAX_BILLS_INT'")
    if i < 0:
        return None
    cells = _BILL_CELL.findall(html[i:i + 20000])
    rows = []
    for k in range(0, len(cells) - 8, 9):
        chunk = cells[k:k + 9]
        if not _YEAR.match(chunk[0].strip()):
            # the first non-year row is the table's own "Total:" line (live-confirmed: it is
            # always immediately after the last year row) -- stop there, since cells past it
            # belong to other, unrelated DataletData widgets further down the same page, not
            # this table (a blind length-bounded window cannot tell them apart otherwise)
            break
        rows.append({"year": int(chunk[0]), "original_bill": _money(chunk[1]),
                     "bill_adjustment": _money(chunk[2]), "total_paid": _money(chunk[3]),
                     "discount": _money(chunk[4]), "interest": _money(chunk[5]),
                     "amount_due": _money(chunk[6])})
    return rows


# ---------------------------------------------------------------------------
# fetching (one session per run, one request at a time, politeness via the Fetcher's own pacing)
# ---------------------------------------------------------------------------

class PortalDown(RuntimeError):
    pass


class _State:
    def __init__(self) -> None:
        self.cm: Any = None
        self.session: Any = None
        self.opened = 0.0
        self.hidden: dict[str, str] = {}
        self.failures = 0
        self.dead: Optional[str] = None


_RUNS: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def _run(client: Any) -> dict:
    try:
        return _RUNS.setdefault(client, {"cache": {}, "state": _State()})
    except TypeError:                                   # not weak-referenceable: no sharing
        return {"cache": {}, "state": _State()}


async def _close(st: _State) -> None:
    cm, st.cm, st.session = st.cm, None, None
    if cm is not None:
        try:
            await cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


async def _session(client: Any) -> tuple[Any, dict]:
    st = _run(client)["state"]
    if st.dead:
        raise PortalDown(st.dead)
    if st.session is None or time.monotonic() - st.opened > SESSION_MAX_AGE_S:
        await _close(st)
        cm = client.form_session()
        s = await cm.__aenter__()
        r = await s.get(SEARCH_URL, timeout=TIMEOUT_S)
        if r.status != 200:
            await cm.__aexit__(None, None, None)
            raise RuntimeError(f"search page HTTP {r.status}")
        st.cm, st.session, st.opened, st.hidden = cm, s, time.monotonic(), hidden_fields(r.text)
    return st.session, st.hidden


def _failed(client: Any, why: str) -> None:
    st = _run(client)["state"]
    st.failures += 1
    st.session = None
    if st.failures >= MAX_FAILURES:
        st.dead = f"{st.failures} failures in a row this run, last {why}"[:200]


def _ok(client: Any) -> None:
    _run(client)["state"].failures = 0


async def search(client: Any, parid: str) -> list[dict]:
    """Every result row for one parcel-id search, cached per run. Raises PortalDown once the
    site has failed MAX_FAILURES times in a row this run; any other failure raises and leaves the
    circuit open for the next call to count."""
    run = _run(client)
    ck = ("search", parid)
    if ck in run["cache"]:
        return run["cache"][ck]
    try:
        s, hidden = await _session(client)
        r = await s.post_form(SEARCH_URL, search_form(hidden, parid),
                              headers={"Referer": SEARCH_URL}, timeout=TIMEOUT_S)
        if r.status != 200:
            raise RuntimeError(f"search HTTP {r.status}")
        rows = parse_results(r.text)
        fresh = hidden_fields(r.text)
        if fresh.get("__VIEWSTATE"):            # else the page carried no new one: keep the old
            run["state"].hidden = fresh
    except PortalDown:
        raise
    except Exception as exc:  # noqa: BLE001
        _failed(client, f"{type(exc).__name__}: {str(exc)[:120]}")
        raise
    _ok(client)
    run["cache"][ck] = rows
    return rows


async def detail(client: Any, sIndex: str, idx: str) -> Optional[list[dict]]:
    """The bill table for one search result's (sIndex, idx), cached per run. Never counts
    against the portal's health (a session that expired between the search and this call must
    not take the whole run down)."""
    run = _run(client)
    ck = ("detail", sIndex, idx)
    if ck in run["cache"]:
        return run["cache"][ck]
    s, _hidden = await _session(client)
    url = f"{BASE}/Datalets/Datalet.aspx?mode=tax_bills_int&sIndex={sIndex}&idx={idx}"
    r = await s.get(url, timeout=TIMEOUT_S)
    if r.status != 200:
        raise RuntimeError(f"detail HTTP {r.status}")
    bills = parse_bills(r.text)
    run["cache"][ck] = bills
    return bills


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

_KEYS = ("reason", "url", "tax_parcel", "searched", "latest_levy_year", "delinquent_by_year",
         "total_delinquent", "years_delinquent", "not_yet_delinquent_due", "claimed_years",
         "owner_match", "error", "portal_health", "resolved_claimed_years")


def public_evidence(ev: dict) -> dict:
    return tc.pick(ev, _KEYS)


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, public_evidence(ev), source=SOURCE, version=VERSION,
                  verifier=_NAME)


async def verify(row: dict, client: Any, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    claimed = claimed_years(row)
    ev: dict[str, Any] = {"url": SEARCH_URL, "claimed_years": claimed}
    pid = str(tc.g(row, "parcel_id") or "").strip()
    if not pid:
        return _res("unconfirmed", dict(ev, reason="no_parcel"))
    norm = tc.alnum(pid)

    try:
        found = await search(client, pid)
    except PortalDown as exc:
        return _res("unconfirmed", dict(ev, reason="portal_unhealthy", portal_health=str(exc)[:200]))
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                        error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    ev["searched"] = [{"by": "inpParid", "results": len(found)}]
    matches = [r for r in found if tc.alnum(r["parcel_id"]) == norm]
    if not matches:
        return _res("unconfirmed", dict(ev, reason="parcel_not_found"))
    if len(matches) > 1:
        return _res("unconfirmed", dict(ev, reason="ambiguous_parcel"))
    match = matches[0]
    ev["tax_parcel"] = match["parcel_id"]

    try:
        bills = await detail(client, match["sIndex"], match["idx"])
    except Exception as exc:  # noqa: BLE001
        return _res("unconfirmed", dict(ev, reason="fetch_failed",
                                        error=f"{type(exc).__name__}: {str(exc)[:160]}"))
    if not bills:
        return _res("unconfirmed", dict(ev, reason="no_bills"))

    ev["latest_levy_year"] = max(b["year"] for b in bills)
    ev["owner_match"] = tc.owner_category(row.get("owner_name"), [match["owner"]])
    delinquent: dict[str, float] = {}
    current: dict[str, float] = {}
    resolved_claimed: list[int] = []
    for b in bills:
        due = b["amount_due"] or 0.0
        late = tax_calendar.levy_year_is_delinquent(b["year"], "NC", "Rowan", today)
        if due > 0 and late:
            delinquent[str(b["year"])] = round(due, 2)
        elif due > 0:
            current[str(b["year"])] = round(due, 2)
        elif b["year"] in claimed:
            resolved_claimed.append(b["year"])

    if current:
        ev["not_yet_delinquent_due"] = current
    if delinquent:
        ev["delinquent_by_year"] = delinquent
        ev["total_delinquent"] = tc.money_total(delinquent)
        ev["years_delinquent"] = len(delinquent)
        return _res("confirmed", ev)
    if resolved_claimed:
        ev["resolved_claimed_years"] = sorted(resolved_claimed, reverse=True)
        return _res("stale", ev)
    return _res("unconfirmed", dict(ev, reason="claimed_year_not_in_bill_history"))
