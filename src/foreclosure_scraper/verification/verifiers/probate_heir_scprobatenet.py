"""probate_heir, SC (southcarolinaprobate.net courts): is the probate case / marriage-license
record the board's sc_probate_net lead was built from still open at its source, or has it since
closed (the estate settled) or vanished from the index (a stale scrape)?

THE CLAIM. counties_sc.sc_probate_net (southcarolinaprobate.net, a shared ASP.NET WebForms index a
handful of SC probate courts publish their docket to) emits one Listing per PROBATE estate case or
MARRIAGE license it finds sweeping common surnames per county (raw.sc_probate_net: record_kind
"probate" / "marriage", case_number/license_number is the row's own case_number, and -- probate
only -- the status the scraper read at scrape time, "Opened" / "RE Reopen" / "Closed" / ...; a
marriage license carries no status at all). A probate lead is a classic motivated-seller signal
(heirs liquidate to avoid carrying costs or split an estate) only while the case is unsettled: once
the court's own record shows it Closed, the heirs have likely already settled/distributed/sold and
the lead is stale, not false -- the case was real, it just is not live any more.

THE SOURCE. The SAME site, re-queried by the row's own county+marriage-flag dropdown
(scrapers.counties_sc.sc_probate_net.COUNTIES -- a case lives in ONE county's docket on this shared
index; live-confirmed 2026-11-16 the dropdown genuinely scopes the search server-side: a real case/
license number returns the grid's own "no records matching" sentinel under the WRONG county's
dropdown) and its own case/license number, via the SAME search form's tbCaseNumber field the
scraper itself never fills in (sc_probate_net.py always searches by surname and leaves
tbCaseNumber empty, so this exact field was never exercised anywhere in this codebase before
today). Live-confirmed 2026-11-16 it is a real, exact filter: a fabricated case number returns
"no records matching"; the row's own real case number returns exactly that one case, scoped to
the right county and probate/marriage grid (tested both ways, including cross-county: York's real
case number under the Dorchester dropdown returns 0 rows). Two or three requests per row (GET +
county-select postback + case-number-search postback) -- the identical ASP.NET VIEWSTATE dance
sc_probate_net.py's own `_search_county()` performs -- through client.form_session() (a cookie
session; the same shape foreclosure_rod_buncombe.py already uses for a different ASP.NET WebForms
index) instead of the scraper's own bare httpx.AsyncClient.

VERDICTS (core.py's meanings):
  confirmed    the case/license is still on the court's own index under the row's own case
               number, and -- a probate case -- its status is not Closed (is_closed(), reusing
               sc_probate_net.is_current()'s own "closed" test word for word so the two modules
               never disagree about what "closed" means): the estate is still open/unsettled, the
               lead is live (case_open). A marriage license carries no status to call stale by, so
               found-again is the most this source can ever say about one (license_found_again).
  stale        the case is still on the index but its status today reads Closed: real when the
               row was built, not live any more (case_closed).
  refuted      never. A case number this SAME aggregator originally returned is not positive
               evidence the claim is FALSE merely because a re-search misses it -- only that the
               re-search may have hit a scrape-time artifact or a transient site hiccup (see
               unconfirmed/case_not_found_again below); the identical stance heir_roll.py takes on
               a parcel id that is not on the layer today (unconfirmed/parcel_not_found, never
               refuted).
  unconfirmed  the case/license is not found again under its own county + record kind
               (case_not_found_again), or a fetch/session/parse problem (fetch_failed, retried in
               6h per TRANSIENT_REASONS).
  wall         never: the search form is open, no login, no CAPTCHA (sc_probate_net.py's own
               module docstring).

NOT COVERED, CHECKED LIVE, NOT GUESSED (2026-11-16 county_signal_coverage audit of that day's 22
atty_probate_case built-not-verified cells, scripts/gap_matrix.py's own gap_list CSV plus a direct
board_stream.iter_board_rows() read, never load_board()): only 3 of those 22 counties' hit rows are
actually sourced=counties_sc.sc_probate_net at all -- Charleston (386 rows), Dorchester (101),
York (19). The other 19 (Sumter, Marlboro, Florence, Aiken, Georgetown, Oconee, Newberry,
Greenville, Calhoun, Greenwood, Richland, Cherokee, Beaufort, Marion, Jasper, McCormick,
Darlington, Hampton, NC New Hanover) are fed by entirely different producers -- sc_public_notices,
column_legal_notices, publicnoticesc_estates, qpaybill_delinquent_roll, greenville_probate,
sc_rod_walled, arcgis_distress -- each its own vendor, its own claim shape (a notice body, a tax
roll, a ROD image), not a sc_probate_net row at all and not touched by this file. The matrix's own
`probate.url` for several of them (e.g. Sumter, Marlboro) happens to read "southcarolinaprobate.
net" too -- that is the county's REGISTERED authoritative probate-court source in docs/
county_records, independent of which producer actually wrote that county's board rows, and must
not be read as "sc_probate_net.py covers this county": confirmed live it currently does not
(sc_probate_net.py's own COUNTIES tuple does not even query Sumter, Marlboro, Florence, Aiken, or
Richland today).

GOVERNS (per record): "probate_notice" (the listing_type / scorer signal sc_probate_net's own row
carries; distress_score._LISTING_TYPE_SIGNAL).

IDENTITY: "case" (case_identity). The claim is about the COURT CASE/license, not the property it
may later, separately, carry: most sc_probate_net rows have no parcel_id at all when scraped (the
module's own docstring: "backfilled to a property by the downstream owner->GIS enricher"), and
that backfill is an independent, uncertain pipeline. Two rows the enricher later ties to the same
case share one verdict; a case split across two parcels is two entries -- the same CASE IDENTITY
shape bankruptcy_stay.py and jail_booking.py already use.

PRIVACY (public ledger): evidence holds the case/license number, county, record kind, status text
and request count; never the decedent/couple's name. ROW_SUMMARY_EXCLUDE drops owner_name.
"""
from __future__ import annotations

from typing import Any, Optional

from ..core import VerificationResult, case_id, result
from ...scrapers.counties_sc.sc_probate_net import (
    BASE_URL, COUNTIES, PRE, _hidden_fields, _parse_marriage, _parse_probate,
)

SIGNAL = "probate_heir"
VERSION = "v1"
TTL_DAYS = 30          # a case's status changes on the court's own schedule, not daily
RETRY_DAYS = 7
SOURCE = "southcarolinaprobate.net (re-queried by the form's own case/license-number field)"
GOVERNS: tuple[str, ...] = ("probate_notice",)
IDENTITY = "case"      # one verdict per case/license and property (case_identity), not per property
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed",)

SC_PROBATE_NET_SOURCE = "counties_sc.sc_probate_net"
_NAME = __name__.rsplit(".", 1)[-1]

#: (display_county, is_marriage) -> the dropdown value that selects it, read directly off the
#: producer's OWN registry (never a second hand-maintained copy) -- a county sc_probate_net.py
#: adds or drops later needs no edit here, the same "resolve against the producer's own registry,
#: don't duplicate it" rule heir_roll.py's _sc_cache_cfg already follows for parcel_cache.
_DROPDOWN: dict[tuple[str, bool], str] = {(co, m): dv for dv, co, st, m in COUNTIES}


def _get(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def _raw(row: Any) -> dict:
    r = _get(row, "raw")
    return r if isinstance(r, dict) else {}


def _sc_probate_net_block(row: Any) -> dict:
    b = _raw(row).get("sc_probate_net")
    return b if isinstance(b, dict) else {}


def is_closed(status: Any) -> bool:
    """The SAME 'closed' test sc_probate_net.is_current() uses at scrape time to decide whether
    to keep a row at all -- kept word for word so the two modules never disagree about what a
    closed estate is."""
    return str(status or "").strip().lower().startswith("closed")


def applies(row: dict) -> bool:
    if str(_get(row, "source") or "") != SC_PROBATE_NET_SOURCE:
        return False
    if not str(_get(row, "case_number") or "").strip():
        return False
    kind = _sc_probate_net_block(row).get("record_kind")
    if kind not in ("probate", "marriage"):
        return False
    co = str(_get(row, "county") or "").strip()
    return (co, kind == "marriage") in _DROPDOWN


def case_identity(row: Any) -> Optional[str]:
    b = _sc_probate_net_block(row)
    return case_id("scprobnet", _get(row, "county"), b.get("record_kind"), _get(row, "case_number"))


def priority(row: Any) -> int:
    return 0


class _HttpError(Exception):
    pass


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


def _county_select_form(fields: dict, dropdown_value: str) -> dict:
    """The county-change postback body: the page's own hidden fields plus the 3 that select
    `dropdown_value` (sc_probate_net._search_county()'s step 2, unchanged)."""
    form = dict(fields)
    form["__EVENTTARGET"] = PRE + "ddlCounties"
    form["__EVENTARGUMENT"] = ""
    form[PRE + "ddlCounties"] = dropdown_value
    form[PRE + "rblPartyType"] = "0"
    return form


def _case_number_search_form(fields: dict, dropdown_value: str, case_number: str) -> dict:
    """The search postback body: sc_probate_net._search_county()'s own step-3 shape, with
    tbCaseNumber filled and every name field left empty instead of the other way around."""
    form = dict(fields)
    form["__EVENTTARGET"] = PRE + "btnSearch"
    form["__EVENTARGUMENT"] = ""
    form[PRE + "ddlCounties"] = dropdown_value
    form[PRE + "tbLastName"] = ""
    form[PRE + "tbFirstName"] = ""
    form[PRE + "tbMiddleName"] = ""
    form[PRE + "tbCaseNumber"] = case_number
    form[PRE + "rblPartyType"] = "0"
    return form


async def _search_case_number(session: Any, dropdown_value: str, case_number: str) -> str:
    """The identical 2-postback ASP.NET dance sc_probate_net.py's own `_search_county()` performs
    (GET for hidden fields -> county-select postback -> search postback), through a form_session
    (cookie jar handled for us) instead of a bare httpx.AsyncClient, searching the form's own
    tbCaseNumber field instead of tbLastName -- see this module's own docstring for why that field
    is trusted here (live-confirmed 2026-11-16, never exercised anywhere in this codebase before).
    No pager follow-up: a case/license number search answers at most one case, never a multi-page
    surname sweep."""
    r0 = await session.get(BASE_URL)
    if r0.status >= 400:
        raise _HttpError(f"http_{r0.status}_on_get")
    r1 = await session.post_form(BASE_URL, _county_select_form(_hidden_fields(r0.text), dropdown_value))
    if r1.status >= 400:
        raise _HttpError(f"http_{r1.status}_on_county_select")
    r2 = await session.post_form(
        BASE_URL, _case_number_search_form(_hidden_fields(r1.text), dropdown_value, case_number))
    if r2.status >= 400:
        raise _HttpError(f"http_{r2.status}_on_search")
    return r2.text


async def verify(row: dict, client) -> VerificationResult:
    co = str(_get(row, "county") or "").strip()
    case_number = str(_get(row, "case_number") or "").strip()
    b = _sc_probate_net_block(row)
    kind = b.get("record_kind")
    marriage = kind == "marriage"
    ev: dict = {"county": co, "case_number": case_number, "record_kind": kind}
    dropdown = _DROPDOWN.get((co, marriage))
    if not dropdown or not case_number:
        ev["reason"] = "no_dropdown_or_case_number"
        return _res("unconfirmed", ev)
    try:
        async with client.form_session() as s:
            html = await _search_case_number(s, dropdown, case_number)
    except Exception as exc:  # noqa: BLE001 - a session/network problem, never a verdict on the row
        ev.update(reason="fetch_failed", detail=f"{type(exc).__name__}: {str(exc)[:120]}")
        return _res("unconfirmed", ev)
    parse = _parse_marriage if marriage else _parse_probate
    try:
        found = parse(html, co, str(_get(row, "state") or "SC"))
    except Exception as exc:  # noqa: BLE001 - an unparseable page is a fetch problem, not evidence
        ev.update(reason="fetch_failed", detail=f"parse: {type(exc).__name__}: {str(exc)[:120]}")
        return _res("unconfirmed", ev)
    match = next((li for li in found if li.case_number == case_number), None)
    if match is None:
        ev["reason"] = "case_not_found_again"
        return _res("unconfirmed", ev)
    if marriage:
        ev["reason"] = "license_found_again"
        return _res("confirmed", ev)
    status = (match.raw.get("sc_probate_net") or {}).get("status")
    ev["status_today"] = status
    if is_closed(status):
        ev["reason"] = "case_closed"
        return _res("stale", ev)
    ev["reason"] = "case_open"
    return _res("confirmed", ev)
