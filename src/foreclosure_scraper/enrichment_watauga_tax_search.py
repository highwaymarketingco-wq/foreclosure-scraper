"""Watauga County NC real-estate tax bill search (wataugacounty.org): fetches each parcel's
full multi-year bill history in ONE request and restates it into raw['multi_year_delinquent_tax']
/ raw['two_year_delinquent'] via enrichment_ustaxdata_multiyear_tax.py's own build_block() /
build_two_year_block() -- same bills[] shape (year, status, total_due), same tax_calendar
delinquency rules, so the two sources never disagree about what counts as late.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-11-28.csv). Watauga carried 5 sourced-not-built
cells (multi_year_delinquent_tax, rollback_exposure, tax_aging_surfaced, two_year_delinquent,
atty_tax_verified_confirmed; ~883 NC rows each) against "tax/property card: wataugacounty.org"
-- the county's own "Real Estate Tax Bill Search", open, no login, no CAPTCHA (live-confirmed
2026-11-28). 380 of 883 NC Watauga board rows (43%) carry a parcel_id in the board's own dashed
TMS shape ("NNNN-NN-NNNN-NNN"), which this portal's txtParcel field matches directly --
confirmed live against a real parcel (2848-99-0061-000, owner CASSIDY/STEELE), which returned a
real $5,374.82 balance due for levy year 2026 alongside 4 prior paid years in one response.

THE SITE (ASP.NET WebForms, live-verified 2026-11-28):
    GET  https://wataugacounty.org/App_Pages/Dept/Tax/searchbills.aspx
         -> __VIEWSTATE / __VIEWSTATEGENERATOR / __EVENTVALIDATION (fresh tokens per search;
            this site does not accept a stale/reused VIEWSTATE across requests, live-confirmed).
    POST the same URL. __EVENTTARGET must be set to
         "ctl00$ContentPlaceHolder1$btnSearch" -- the button's OWN name=value pair alone does
         NOT trigger the search (it is wired to WebForm_DoPostBackWithOptions, an __EVENTTARGET
         postback, not a plain HTML submit; confirmed live: a POST with only
         ctl00$ContentPlaceHolder1$btnSearch=Search and no __EVENTTARGET just re-renders the
         blank form). ctl00$ContentPlaceHolder1$txtParcel=<parcel>, every other txt* field
         blank -- INCLUDING txtYear: leaving Year blank returns EVERY year on file in one grid;
         filling it in restricts to that one year (confirmed live both ways; a visible
         "Please enter a valid year" span exists in the markup but is display:none and never
         actually fires for a blank Year on a parcel-based search).
    -> a #ctl00_ContentPlaceHolder1_gvAccount table, one <tr> per bill year, 9 <td> cells:
       [View link, Year, Owner, Owner2, Cust. No., Bill No., Property Location, Parcel No.,
       Total Due]. A blank Total Due cell means $0 owed (that year is paid); a dollar amount
       means that much is still owed -- no separate status flag exists, so delinquency here is
       read directly off the amount, unlike ustaxdata's own status-word bills. Zero matches
       renders one <tr><td colspan="9">...No record found.</td></tr> row instead (both shapes
       live-confirmed 2026-11-28; see tests/test_enrichment_watauga_tax_search.py's fixtures,
       captured verbatim from the real site that day).

VERDICTS: none -- this is a fetch+restate module, not a verifier. It never guesses a bill is
late; it only ever reads the county's own posted dollar amount for a year that's already matured
(tax_calendar's rules, same ones ustaxdata/Gaston/Nash/Sampson already use).

NOT YET DONE (left for the backfill script / a future round, not this module): a standalone
scripts/backfill_watauga_tax_search.py wiring this into patch_existing_rows() against the live
board, matching every other backfill_*.py here. This module is fetch+restate only, live-tested
against one real parcel plus both captured no-record and multi-year fixtures -- not yet run at
scale against the full ~380-parcel Watauga population, so page_delay / rate-limit tuning is
unverified past a handful of manual requests.
"""
from __future__ import annotations

import re
import traceback
from datetime import datetime, timezone
from typing import Iterable, Optional

import structlog

from .enrichment_ustaxdata_multiyear_tax import build_block, build_two_year_block
from .models import Listing

log = structlog.get_logger()

BASE_URL = "https://wataugacounty.org/App_Pages/Dept/Tax/searchbills.aspx"
SRC_KEY = "watauga_delinquent_tax"
RAW_KEY = "multi_year_delinquent_tax"
TWO_YEAR_KEY = "two_year_delinquent"
SOURCE_SLUG = "enrichment_watauga_tax_search"
COUNTY = "Watauga"

# The board's own dashed TMS shape for this county ("2848-99-0061-000"), the only shape this
# portal's txtParcel field is confirmed to match (live-checked 2026-11-28).
_PARCEL_RE = re.compile(r"^\d{4}-\d{2}-\d{4}-\d{3}$")
_HIDDEN_RE = re.compile(r'name="(__VIEWSTATE|__VIEWSTATEGENERATOR|__EVENTVALIDATION)"[^>]*value="([^"]*)"')
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_AMOUNT_RE = re.compile(r"[\d,.]+")


def _already_done(raw) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get(SRC_KEY), dict)


def _eligible(li: Listing) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else None
    return bool(
        (li.state or "").strip().upper() == "NC"
        and (li.county or "").replace(" County", "").strip().lower() == COUNTY.lower()
        and _PARCEL_RE.match((li.parcel_id or "").strip())
        and not _already_done(raw)
    )


def _hidden_fields(html: str) -> dict[str, str]:
    out = {"__VIEWSTATE": "", "__VIEWSTATEGENERATOR": "", "__EVENTVALIDATION": ""}
    for name, val in _HIDDEN_RE.findall(html):
        out[name] = val
    return out


def _parse_bills(html: str) -> list[dict]:
    """Pure: one dict per bill year from a #gvAccount results grid, or [] for the portal's own
    "No record found." sentinel row. Cell text is read by POSITION (index 1 = Year, index 8 =
    Total Due) rather than one long regex over the whole row, so a stray style/class attribute
    on any cell (the Parcel No. cell carries one; the others normally don't) can't break the
    match -- live-verified against both the real multi-year result and the no-record page."""
    bills: list[dict] = []
    for row_html in _ROW_RE.findall(html):
        if "gvAccount" in row_html or "<th" in row_html:
            continue
        cells = [_TAG_RE.sub("", c).strip() for c in _CELL_RE.findall(row_html)]
        if len(cells) != 9 or not cells[1].isdigit():
            continue  # the header row and the "No record found." row both fail this shape
        year = int(cells[1])
        amt_s = _AMOUNT_RE.search(cells[8])
        amt = float(amt_s.group(0).replace(",", "")) if amt_s else 0.0
        bills.append({"year": year, "status": "unpaid" if amt > 0 else "paid",
                      "total_due": amt if amt > 0 else None})
    return bills


def fetch_bills(session, parcel_id: str) -> list[dict]:
    """One live search: GET the form for fresh tokens (this site rejects a stale VIEWSTATE),
    POST the parcel with Year left blank, parse the result. Raises on a network/HTTP failure --
    the caller (enrich_watauga_tax_search) decides how to treat that."""
    html = session.get(BASE_URL, timeout=20).text
    data = {
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$btnSearch",
        "__EVENTARGUMENT": "",
        **_hidden_fields(html),
        "ctl00$ContentPlaceHolder1$txtName": "",
        "ctl00$ContentPlaceHolder1$txtLocation": "",
        "ctl00$ContentPlaceHolder1$txtStreet": "",
        "ctl00$ContentPlaceHolder1$txtParcel": parcel_id,
        "ctl00$ContentPlaceHolder1$txtAcct": "",
        "ctl00$ContentPlaceHolder1$txtBill": "",
        "ctl00$ContentPlaceHolder1$txtYear": "",
    }
    resp = session.post(BASE_URL, data=data, timeout=20)
    return _parse_bills(resp.text)


def enrich_watauga_tax_search(listings: Iterable[Listing], *, session=None,
                              max_rows: Optional[int] = None) -> dict[str, int]:
    """Walk NC Watauga rows with a usable parcel_id, fetch each one's full bill history LIVE
    (one request per row, every year on file), and write raw['watauga_delinquent_tax'] (the
    fetched bills) plus -- reusing enrichment_ustaxdata_multiyear_tax.py's own logic unmodified
    -- raw['multi_year_delinquent_tax'] / raw['two_year_delinquent']."""
    from curl_cffi import requests as creq  # deferred: only this function needs the network dep

    stats = {"eligible": 0, "fetched": 0, "qualified": 0, "two_year_written": 0, "fetch_errors": 0}
    sess = session or creq.Session(impersonate="chrome")
    for li in listings:
        if not _eligible(li):
            continue
        stats["eligible"] += 1
        if max_rows is not None and stats["fetched"] >= max_rows:
            break
        try:
            bills = fetch_bills(sess, li.parcel_id.strip())
        except Exception:  # noqa: BLE001 -- one bad fetch must not kill the run
            stats["fetch_errors"] += 1
            log.error("watauga_tax_search.fetch_failed", parcel_id=li.parcel_id,
                      traceback=traceback.format_exc())
            continue
        stats["fetched"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw[SRC_KEY] = {"bills": bills, "fetched_at": datetime.now(timezone.utc).isoformat()}
        block = build_block(bills, COUNTY)
        if block:
            li.raw[RAW_KEY] = block
            stats["qualified"] += 1
        li.raw[TWO_YEAR_KEY] = build_two_year_block(bills, COUNTY)
        stats["two_year_written"] += 1
    log.info("watauga_tax_search.done", **stats)
    return stats
