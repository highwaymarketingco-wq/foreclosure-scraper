"""Dare County NC tax certification lookup (tax.darecountync.gov/taxcert.php): fetches a
parcel's full multi-year bill history in ONE plain GET (no session, no VIEWSTATE -- simpler
than Watauga's portal) and restates it into raw['multi_year_delinquent_tax'] /
raw['two_year_delinquent'] via enrichment_ustaxdata_multiyear_tax.py's own build_block() /
build_two_year_block(), same as enrichment_watauga_tax_search.py.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-11-28.csv). Dare carried 4 sourced-not-built
cells (multi_year_delinquent_tax, rollback_exposure, tax_aging_surfaced, atty_tax_verified_
confirmed; ~879 NC rows each) against "tax/property card: tax.darecountync.gov".

ONLY A SUBSET IS COVERED, ON PURPOSE -- READ BEFORE EXTENDING. Dare runs TWO parallel parcel
identifiers: a 9-digit "tax parcel number" (what this portal's own search wants, e.g.
"014822090") and a 12-digit dashed "PIN#" (e.g. "054913-14-4650", stripped "054913144650" --
what the county's GIS/assessment system and, apparently, THIS BOARD'S OWN SCRAPER store as
parcel_id for most Dare rows). Measured 2026-11-28 against the live board: of 368 NC Dare rows
carrying a parcel_id, only 50 (14%) are already in the plain 9-digit shape this portal accepts
directly; 310 (84%) carry the 12-digit PIN shape, which this portal's search does NOT accept
(live-confirmed: a 12-digit value here returns the same "CONTACT TAX OFFICE... FOR
CERTIFICATION" no-record sentinel as any other unrecognized string). NO live PIN -> tax-parcel-
number crosswalk was found or attempted this round (the GIS portal at maps.darecountync.gov
takes a parcel param in its URL the same shape this module searches by, suggesting it is PIN-
aware, but a real crosswalk call was not built or tested) -- _eligible() below gates on the
9-digit shape specifically so this module only ever touches rows it can actually search, rather
than silently no-op'ing on the other 84%. Closing that majority needs the crosswalk step first;
flagging it here rather than letting a future round assume this module already covers it.

THE SITE (live-verified 2026-11-28): GET https://tax.darecountync.gov/taxcert.php?parcel=<9-
digit>, no session, no POST, no form tokens of any kind -- the simplest of the tax portals
built against on this project so far. Response is a single HTML <table>, one <tr> per bill
year: [Listed Owner, Year, Bill Ref, Orig Amt, Adj Amt, Orig Pd, Activity Date, Int Pd/Refund,
UnPd Bal, Int Due, Taxes Due]. A paid year has Orig Pd == Orig Amt (adjusted) and a populated
Activity Date; an unpaid year has Orig Pd=0.00, no Activity Date, and Taxes Due > 0 -- read
directly off Taxes Due (the final column, principal + interest), the same "read the county's
own posted total" convention enrichment_watauga_tax_search.py uses for Watauga's Total Due.
A parcel with no record on file renders a short "CONTACT TAX OFFICE ... FOR CERTIFICATION"
message instead of a table (live-confirmed both shapes 2026-11-28; see tests/fixtures/
dare_taxcert_*.html, captured verbatim from the real site that day).

VERDICTS: none -- fetch+restate only, not a verifier, same stance as Watauga's module.
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

BASE_URL = "https://tax.darecountync.gov/taxcert.php"
SRC_KEY = "dare_delinquent_tax"
RAW_KEY = "multi_year_delinquent_tax"
TWO_YEAR_KEY = "two_year_delinquent"
SOURCE_SLUG = "enrichment_dare_tax_search"
COUNTY = "Dare"

# ONLY the plain 9-digit tax-parcel-number shape -- the 12-digit PIN shape the board mostly
# carries for Dare is NOT accepted by this portal's search (see module docstring).
_PARCEL_RE = re.compile(r"^\d{9}$")
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


def _parse_bills(html: str) -> list[dict]:
    """Pure: one dict per bill year from the taxcert table, or [] for the portal's own
    "CONTACT TAX OFFICE" no-record sentinel. Cell text read by position (index 1 = Year,
    index 10 = Taxes Due) so a stray attribute on any one cell can't break the match."""
    bills: list[dict] = []
    for row_html in _ROW_RE.findall(html):
        cells = [_TAG_RE.sub("", c).strip() for c in _CELL_RE.findall(row_html)]
        if len(cells) != 11 or not cells[1].isdigit():
            continue  # the header row and the no-record page both fail this shape
        year = int(cells[1])
        amt_s = _AMOUNT_RE.search(cells[10])
        amt = float(amt_s.group(0).replace(",", "")) if amt_s else 0.0
        bills.append({"year": year, "status": "unpaid" if amt > 0 else "paid",
                      "total_due": amt if amt > 0 else None})
    return bills


def fetch_bills(session, parcel_id: str) -> list[dict]:
    """One live GET, no session state needed across calls (unlike Watauga's VIEWSTATE dance).
    Raises on a network/HTTP failure -- the caller (enrich_dare_tax_search) decides how to
    treat that."""
    resp = session.get(BASE_URL, params={"parcel": parcel_id}, timeout=20)
    return _parse_bills(resp.text)


def enrich_dare_tax_search(listings: Iterable[Listing], *, session=None,
                           max_rows: Optional[int] = None) -> dict[str, int]:
    """Walk NC Dare rows with a 9-digit (tax-parcel-number-shaped) parcel_id, fetch each one's
    full bill history LIVE, and write raw['dare_delinquent_tax'] (the fetched bills) plus --
    reusing enrichment_ustaxdata_multiyear_tax.py's own logic unmodified -- raw['multi_year_
    delinquent_tax'] / raw['two_year_delinquent']. Rows with a 12-digit PIN-shaped parcel_id
    (the Dare majority) are simply not eligible -- see module docstring."""
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
            log.error("dare_tax_search.fetch_failed", parcel_id=li.parcel_id,
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
    log.info("dare_tax_search.done", **stats)
    return stats
