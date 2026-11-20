"""code_enforcement, Gaston County NC (City of Gastonia): is any of the row's claimed
code-enforcement cases, of a genuinely distress category, still OPEN on the city's own CityView
portal today?

WHY THIS EXISTS (same bug class as elderly_disabled's 2026-11-19 SC-homestead fix, and the bug
class gap_matrix.py's own docstring names for heir_roll.py's HEIR_SOURCE: a verifier whose scope
is narrower than the real producer set). `code_enforcement` already has three verifiers --
code_enforcement_adl.py (any arcgis_distress_layers.py Layer whose process=="code_enforcement"),
code_enforcement_city_open_data.py (CE_SOURCE=="city_open_data", enrichment_code_enforcement.py's
municipal feeds), code_enforcement_henderson.py (Henderson County's own OVT ArcGIS layer) -- but
counties_nc.gastonia_code_enforcement.py (wired in main.py, FORECLOSURE_GASTONIA_CODE, live and
current: a fresh live crawl 2026-11-19 of its real CityView Locator endpoint returned 2026
case numbers) writes `raw['code_enforcement']['source'] = "gastonia_cityview_locator"`, a
fourth, distinct shape none of the three recognize: not an arcgis_distress_layers Layer (its
source is CityView's own ASP.NET endpoints, not ArcGIS REST), not CE_SOURCE=="city_open_data",
and not Henderson's county. gap_matrix's `docs/gap_matrix/gap_list_*.csv` (2026-11-19 run, before
this fix) carried Gaston NC as a `code_enforcement` cell of class `built-not-verified (source
status unknown)`, 789 applicable rows (1,516 raw `has_open` rows on the live board the same day)
-- real, current, scraper-built data that no registered verifier's `applies()` ever recognized.
Fixed the SAME way as elderly_disabled_sc_homestead.py: a new sibling module, the existing three
verifiers untouched.

THE SOURCE (live-checked 2026-11-19). `devsvcs.gastonianc.gov` (the scraper's own `BASE`), City of
Gastonia's CityView Portal, anonymous, no login, no CAPTCHA:
  GET  /CodeEnforcement/StatusReference?referenceNumber=<ReferenceNumber>
       the case's own public status page -- confirmed live, NO session cookie needed (unlike the
       scraper's bulk `LocatorResultsPolygon` spatial query, which DOES need the Locator page's
       ASP.NET session handshake first; this single-case detail page does not). A real case's
       page (18.8 KB) carries a `<div id="status" ... data-cy="inp-status">` with the CURRENT
       disposition text verbatim (live-confirmed: an open case read back "Notice/Order Sent", a
       closed one read back "Closed", matching `LocatorResultsPolygon`'s `Status` field for the
       same ReferenceNumber in the same live session). A retired/mistyped reference number comes
       back HTTP 200 but a much shorter (9.6 KB) "Invalid Complaint" page with NO `#status` div --
       a clean, distinguishable "not found" answer, not a parse failure.
  The page has NO field for the violation CATEGORY (`ApplicationTypeDescription`) -- only
  `#status`, `#description` (free-text narrative) and `#locality` (live-sampled empty on every
  case checked). Re-deriving the category live would need the scraper's own whole-city recursive
  quad-tree `LocatorResultsPolygon` crawl (PAGE_CAP=1000, ~60-100 requests, the scraper's own
  documented cost) -- this verifier does not pay that cost. It trusts the board's OWN claimed
  category (`violation`, the scraper's `ApplicationTypeDescription` at scrape time, moments
  before writing the row, off the SAME authoritative CityView feed), the same way every other
  verifier in this repo trusts a static identity fact (a case's filed category, a bill's levy
  year) it does not independently re-derive -- only the STATUS, the fact that actually moves week
  to week, is re-checked live, per case, every verify().

WHICH ROWS (applies). NC Gaston rows whose raw['code_enforcement'] is Gastonia's own block
(source "gastonia_cityview_locator") claiming an open case.

MATCHING. One request per claimed case whose stored category is a distress one (usually one;
`cases[:8]` caps the board's own list, and the scraper counts ANY open case toward `has_open`
regardless of category, so most rows claim only 1-2 of a distress type). A non-distress claimed
case (Zoning-equivalent here: everything `_SEVERE_RE` does not match) is never fetched -- its
live status cannot change the verdict either way, the same economy elderly_disabled applies
("a row whose board parcel's layer record shows the relief is one layer query").

VERDICTS (core.py's meanings):
  confirmed    at least one claimed distress-category case reads back an OPEN status today
               (`gastonia_code_enforcement._is_closed` on the live `#status` text).
  refuted      NONE of the row's claimed cases is a distress category (`category_not_distress`):
               the claim counted toward `has_open` but never toward the scorer's
               `vacancy_adjacent`-gated credit (signal_freshness.code_enforcement_open) -- the
               property fact was never there to confirm or lose.
  stale        at least one distress-category case was read live and every one read is now
               CLOSED (`case_closed`): the case resolved since the scrape.
  unconfirmed  a distress-category case's page could not be fetched (`cases_unreadable`) or came
               back "Invalid Complaint" (`case_not_found_on_portal`) and no OTHER distress case
               confirmed or closed the claim; or the row carries no case ids at all
               (`no_case_ids`, a row whose block lost its `violations` list on a merge).

GOVERNS "code_enforcement:gastonia_cityview_locator", the same per-source qualifier
code_enforcement_henderson.py uses (distress_score._collect / enrichment_lead_signals'
core.qualifiers): a refuted/stale verdict ends ONLY this source's credit on the parcel, never
another merged source's (the Hendersonville register, a Spartanburg condemnation) sharing the
same property-keyed ledger entry.

PRIVACY. The ledger is a committed file in a public repo. ROW_SUMMARY_EXCLUDE drops owner_name:
on these rows it is Gaston County's own `CURR_NAME1` parcel-layer owner
(`gastonia_code_enforcement.resolve_parcels`), the same sensitive join Henderson's verifier
already excludes for its county's rows.

TTL 14 days, retry 3 (Henderson's own cadence for this signal: cases move within weeks, a
15-day notice, an owner resolving it).
"""
from __future__ import annotations

import html as _html
import re
from datetime import date
from typing import Any, Optional
from urllib.parse import quote

from ..core import VerificationResult, result

SIGNAL = "code_enforcement"
VERSION = "v1"
TTL_DAYS = 14
RETRY_DAYS = 3
CE_SOURCE = "gastonia_cityview_locator"
SOURCE = "City of Gastonia CityView Portal (devsvcs.gastonianc.gov)"
GOVERNS = (f"code_enforcement:{CE_SOURCE}",)
ROW_SUMMARY_EXCLUDE = ("owner_name",)

_NAME = __name__.rsplit(".", 1)[-1]

#: the case's own public status page -- no session cookie needed (live-confirmed 2026-11-19),
#: unlike the scraper's bulk LocatorResultsPolygon spatial query
DETAIL_URL = "https://devsvcs.gastonianc.gov/CodeEnforcement/StatusReference?referenceNumber={ref}"
#: live-confirmed shape: `<div id="status" class="inputText" data-cy="inp-status">TEXT</div>`
_STATUS_RE = re.compile(r'id="status"[^>]*>([^<]*)</div>', re.I)
#: a retired/mistyped reference number's page title (live-confirmed, HTTP 200, no #status div)
_NOT_FOUND_MARKER = "Invalid Complaint"
MAX_CASES_CHECKED = 8     # the board's own list cap (gastonia_code_enforcement's `cases[:8]`)


def _scraper():
    """counties_nc.gastonia_code_enforcement, imported on first use (the registry imports every
    verifier; the scraper's httpx/tenacity stack must not load in just to answer applies())."""
    from ...scrapers.counties_nc import gastonia_code_enforcement
    return gastonia_code_enforcement


def is_distress(violation: Any) -> bool:
    return bool(_scraper()._SEVERE_RE.search(str(violation or "")))


# ---------------------------------------------------------------------------
# which rows
# ---------------------------------------------------------------------------

def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _block(row: dict) -> Optional[dict]:
    ce = _raw(row).get("code_enforcement")
    return ce if isinstance(ce, dict) and ce.get("source") == CE_SOURCE else None


def applies(row: dict) -> bool:
    if str(row.get("state") or "").strip().upper() != "NC":
        return False
    county = str(row.get("county") or "").strip().lower()
    if county.endswith(" county"):
        county = county[: -len(" county")]
    if county != "gaston":
        return False
    ce = _block(row)
    return bool(ce and ce.get("has_open"))


def claimed_cases(row: dict) -> list[dict]:
    """The row's own case list ({"case_id", "violation", "claimed_status", "claimed_open"}),
    de-duplicated by case id, at most MAX_CASES_CHECKED (the board's own cap)."""
    ce = _block(row) or {}
    out: list[dict] = []
    seen: set[str] = set()
    for v in ce.get("violations") or []:
        if not isinstance(v, dict):
            continue
        cid = str(v.get("case_id") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append({"case_id": cid, "violation": v.get("violation"),
                    "claimed_status": v.get("status"), "claimed_open": bool(v.get("open"))})
        if len(out) >= MAX_CASES_CHECKED:
            break
    return out


# ---------------------------------------------------------------------------
# the live per-case check
# ---------------------------------------------------------------------------

def parse_status_page(text: str) -> Optional[str]:
    """The case's current disposition text from its StatusReference page, or None for an
    "Invalid Complaint" (not-found) page or one with no #status div at all."""
    if _NOT_FOUND_MARKER in text:
        return None
    m = _STATUS_RE.search(text)
    return _html.unescape(m.group(1)).strip() if m else None


async def _check_case(case_id: str, client) -> dict:
    """{"found": bool, "live_status": str | None, "live_open": bool} or {"found": False,
    "error": str} on a fetch failure. Never raises."""
    url = DETAIL_URL.format(ref=quote(case_id, safe=""))
    try:
        text = await client.get_text(url)
    except Exception as exc:  # noqa: BLE001
        return {"found": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    status = parse_status_page(text)
    if status is None:
        return {"found": False}
    return {"found": True, "live_status": status, "live_open": not _scraper()._is_closed(status)}


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    claimed = claimed_cases(row)
    ev: dict[str, Any] = {"county": "Gaston",
                          "claimed_case_ids": [c["case_id"] for c in claimed]}
    if not claimed:
        ev["reason"] = "no_case_ids"
        return _res("unconfirmed", ev)

    distress_claimed = [c for c in claimed if is_distress(c["violation"])]
    ev["claimed_distress_types"] = sorted({c["violation"] for c in distress_claimed if c["violation"]})
    if not distress_claimed:
        # has_open counted ANY open case toward the board's flag, but none of the row's claimed
        # cases is a category the scorer's vacancy_adjacent gate ever credited (never-distress,
        # Henderson's own "category_not_distress" shape) -- nothing to confirm or lose live.
        ev["reason"] = "category_not_distress"
        return _res("refuted", ev)

    # one request per distress-category claimed case (never the non-distress ones: their live
    # status cannot change this verdict either way)
    checked = []
    for c in distress_claimed:
        live = await _check_case(c["case_id"], client)
        checked.append({**c, **live})
    ev["cases"] = checked

    open_now = [c for c in checked if c.get("found") and c.get("live_open")]
    if open_now:
        ev["basis"] = "case_open_on_portal"
        return _res("confirmed", ev)

    readable_closed = [c for c in checked if c.get("found") and not c.get("live_open")]
    unreadable = [c for c in checked if not c.get("found")]
    if readable_closed and not unreadable:
        ev["reason"] = "case_closed"
        return _res("stale", ev)
    if any("error" in c for c in unreadable):
        ev["reason"] = "cases_unreadable"
    else:
        ev["reason"] = "case_not_found_on_portal"
    if readable_closed:
        # at least one distress case is confirmed closed; the rest just could not be read --
        # still unconfirmed (a different unread case might be open today), never refuted
        ev["reason"] = "mixed_unresolved"
    return _res("unconfirmed", ev)
