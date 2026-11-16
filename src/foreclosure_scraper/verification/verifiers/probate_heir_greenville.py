"""probate_heir, Greenville County SC (appsas400 AS/400 web portal): is the probate estate the
board's greenville_probate lead was built from still open at its source, or has it since closed
(the estate settled) or vanished from the index (a stale scrape)?

THE CLAIM. counties_sc.greenville_probate (greenvillecounty.org's own AS/400 probate search --
Greenville does NOT feed southcarolinaprobate.net; see sc_probate_net.py's and greenville_probate.
py's own module docstrings) emits one Listing per PROBATE estate case it finds sweeping common
surnames (raw.greenville_probate: record_kind is always "probate" -- this producer has no
marriage branch at all -- case_type/case_subtype, file_date, date_of_death, pr_appointed_date,
closed_date, status, personal_representative, parties). A probate lead is a classic motivated-
seller signal (heirs liquidate to avoid carrying costs or split an estate) only while the case is
unsettled: once the court's own record shows a Closed Date, the heirs have likely already
settled/distributed/sold and the lead is stale, not false -- the case was real, it just is not
live any more. Same shape as probate_heir_scprobatenet.py's own claim for the sibling
southcarolinaprobate.net sites, just a different county portal.

THE SOURCE. The SAME portal, re-queried by the row's own case number through
``SearchDetails.aspx?CaseNumber=<case#>`` (greenville_probate.DETAIL_URL) -- a PLAIN query-string
GET, no VIEWSTATE/postback dance, no form session needed (confirmed live 2026-11-16: the exact
same path and params the producer's own `_fetch_detail()` uses, re-run here against TWO real
case numbers pulled straight off today's board -- 2020ES23016822 parsed back byte-identical to
its own board row, closed_date "8/10/2026" included -- plus one fabricated case number, which
comes back as an empty `{'parties': []}` dict (no altDetailsTable on the page at all), never an
error page or a different shape). No login, no CAPTCHA wall, no block page: a bare `curl` with no
cookie jar and no browser fingerprint got a normal 200 both times (one redirect hop to an opaque
`?q=<token>` URL, auto-chased; the page also loads an Incapsula resource script async in its
footer, but that is a passive bot-telemetry tag, not a challenge -- it never altered the status
code or withheld the real body on either request). greenville_probate.py's own module docstring
already confirms this is a free, public, unwalled county portal (it corrects an earlier, wrong
"no online portal" claim). The SAME parser the
producer itself uses (`_parse_detail`) is imported and reused here, never re-implemented, so the
two modules can never disagree about what a page means.

VERDICTS (core.py's meanings):
  confirmed    the case is found again under its own case number, and its Closed Date is empty
               (case_open): the estate is still open/unsettled, the lead is live.
  stale        the case is still on the index but now carries a Closed Date (case_closed): real
               when the row was built, not live any more.
  refuted      never. A case number this SAME portal originally returned is not positive evidence
               the claim is FALSE merely because a re-search comes back empty -- only that the
               re-search may have hit a scrape-time artifact or a transient site hiccup. Identical
               stance to probate_heir_scprobatenet.py's own case_not_found_again/unconfirmed (and
               heir_roll.py's parcel_not_found/unconfirmed): never refuted.
  unconfirmed  the case is not found again (case_not_found_again -- the detail page has no
               altDetailsTable / no decedent name at all, confirmed live above to be the real
               "not found" shape, not an error page), or a fetch/parse problem (fetch_failed,
               retried in 6h per TRANSIENT_REASONS).
  wall         never: a plain unauthenticated GET, confirmed live above.

NOT COVERED, CHECKED LIVE, NOT GUESSED (2026-11-16 sibling sweep of the same 2026-11-16
atty_probate_case built-not-verified audit probate_heir_scprobatenet.py's own docstring ran: of
the 19 counties that audit left untouched, a fresh board_stream.iter_board_rows() sample --
filtered through scripts/gap_matrix.probate_case_present(), the column's REAL hit predicate, not
the gap_list CSV's own `source` column, which can be the county's registered matrix URL rather
than the producer that actually wrote the row -- found Greenville's own 38 probate_case_present
hits are themselves split: 1 from counties_sc.sc_public_notices (CAPTCHA-walled at its Details.
aspx page, per that module's own docstring -- not reachable this pass) and 38 (all but that one)
from counties_sc.greenville_probate, THIS module's own producer -- confirmed exclusively via
raw.greenville_probate's presence, never guessed from the county name. The other 18 of those 19
counties (Sumter/Marlboro/Florence/Aiken/Georgetown/Oconee/Newberry/Calhoun/Greenwood/Richland/
Cherokee/Beaufort/Marion/Jasper/McCormick/Darlington/Hampton/NC New Hanover) are fed by entirely
different producers -- sc_public_notices, column_legal_notices, publicnoticesc_estates,
qpaybill_delinquent_roll, sc_rod_walled, arcgis_distress -- each its own vendor and claim shape,
not touched by this file. (One of those, sc_probate_notices.gaffneyledger, is Cherokee's actual
dominant producer at 335 rows -- the single largest county by hit-row count of any of the 19 --
but it carries no live per-case status field to re-check at all, only a published newspaper
notice body, a structurally different claim than "is this court case still open"; left for a
separate pass, not bundled in here unverified, the same deferral discipline this column's own
gap_matrix.py Spec comment already applies to column_legal_notices.)

GOVERNS (per record): "probate_notice" (the listing_type / scorer signal greenville_probate's own
row carries; distress_score._LISTING_TYPE_SIGNAL).

IDENTITY: "case" (case_identity). The claim is about the COURT CASE, not the property it may
later, separately, carry -- same reasoning as probate_heir_scprobatenet.py's own IDENTITY choice
(most rows have no parcel_id when scraped; a later owner->GIS backfill is a separate, uncertain
pipeline). Two rows the enricher later ties to the same case share one verdict; a case split
across two parcels is two entries.

PRIVACY (public ledger): evidence holds the case number, county, and status text; never the
decedent's name. ROW_SUMMARY_EXCLUDE drops owner_name.
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

from ..core import VerificationResult, case_id, result
from ...scrapers.counties_sc.greenville_probate import DETAIL_URL, _parse_detail

SIGNAL = "probate_heir"
VERSION = "v1"
TTL_DAYS = 30          # a case's status changes on the court's own schedule, not daily
RETRY_DAYS = 7
SOURCE = "greenvillecounty.org appsas400 probate portal (re-queried by its own CaseNumber)"
GOVERNS: tuple[str, ...] = ("probate_notice",)
IDENTITY = "case"      # one verdict per case and property (case_identity), not per property
ROW_SUMMARY_EXCLUDE = ("owner_name",)
TRANSIENT_REASONS = ("fetch_failed",)

GREENVILLE_PROBATE_SOURCE = "counties_sc.greenville_probate"
_NAME = __name__.rsplit(".", 1)[-1]


def _get(row: Any, k: str) -> Any:
    return row.get(k) if isinstance(row, dict) else getattr(row, k, None)


def _raw(row: Any) -> dict:
    r = _get(row, "raw")
    return r if isinstance(r, dict) else {}


def _greenville_probate_block(row: Any) -> dict:
    b = _raw(row).get("greenville_probate")
    return b if isinstance(b, dict) else {}


def is_closed(detail: dict) -> bool:
    """The SAME 'closed' test greenville_probate.is_current() inlines at scrape time (a non-empty
    Closed Date) -- kept word for word so the two modules never disagree about what a closed
    estate is. Unlike is_current(), this never applies an age cutoff: that is a scrape-time
    retention choice, not part of what 'closed' means."""
    return bool((detail.get("closed_date") or "").strip())


def applies(row: dict) -> bool:
    if str(_get(row, "source") or "") != GREENVILLE_PROBATE_SOURCE:
        return False
    if not str(_get(row, "case_number") or "").strip():
        return False
    return _greenville_probate_block(row).get("record_kind") == "probate"


def case_identity(row: Any) -> Optional[str]:
    return case_id("grvprob", _get(row, "county"), _get(row, "case_number"))


def priority(row: Any) -> int:
    return 0


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client) -> VerificationResult:
    case_number = str(_get(row, "case_number") or "").strip()
    ev: dict = {"county": str(_get(row, "county") or "").strip(), "case_number": case_number}
    if not case_number:
        ev["reason"] = "no_case_number"
        return _res("unconfirmed", ev)
    url = f"{DETAIL_URL}?{urlencode({'CaseNumber': case_number})}"
    try:
        html = await client.get_text(url)
    except Exception as exc:  # noqa: BLE001 - a fetch problem, never a verdict on the row
        ev.update(reason="fetch_failed", detail=f"{type(exc).__name__}: {str(exc)[:120]}")
        return _res("unconfirmed", ev)
    try:
        detail = _parse_detail(html)
    except Exception as exc:  # noqa: BLE001 - an unparseable page is a fetch problem, not evidence
        ev.update(reason="fetch_failed", detail=f"parse: {type(exc).__name__}: {str(exc)[:120]}")
        return _res("unconfirmed", ev)
    if not str(detail.get("name") or "").strip():
        ev["reason"] = "case_not_found_again"
        return _res("unconfirmed", ev)
    status = detail.get("status") or None
    closed_date = detail.get("closed_date") or None
    ev["status_today"] = status
    ev["closed_date_today"] = closed_date
    if is_closed(detail):
        ev["reason"] = "case_closed"
        return _res("stale", ev)
    ev["reason"] = "case_open"
    return _res("confirmed", ev)
