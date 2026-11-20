"""vacant_structure (condemned), City of Gastonia's CityView Portal (same producer as
code_enforcement_gastonia.py, source "gastonia_cityview_locator"): does any of the row's claimed
code-enforcement cases still read an "Order to Demolish"/"Order to Vacate" status, OPEN, on the
city's own CityView portal today?

WHY THIS EXISTS (round-75 continuation of the same "verifier narrower than producer set" sweep
that already found elderly_disabled_sc_homestead.py, code_enforcement_gastonia.py and
code_enforcement_spartanburg.py the three prior rounds). counties_nc.gastonia_code_enforcement.py
is live, wired in main.py (FORECLOSURE_GASTONIA_CODE), and current -- confirmed on the real board
2026-11-20: 10 Gaston NC rows carry a bare `raw["condemned"] = True` AND a dict-shaped
`raw["vacancy"] = {"vacant": True, "boarded_up": None, "utility_status": None, "source":
"gastonia_cityview_locator"}`, written by the EXACT SAME branch of the scraper's own
`_to_listing()` that already feeds `code_enforcement_gastonia.py`'s SEPARATE `code_enforcement`
signal (see that scraper's own comment directly above the `raw["condemned"] = True` line: "A
currently-open 'Order to Vacate'/'Order to Demolish' is the city's own condemnation
determination -- stamp the same two keys hendersonville_vacant_structures.py and
charlotte_open_data.py (fof_ordered) already write"). Every registered `vacant_structure`
verifier before this fix (condemned_adl, condemned_charlotte, condemned_greenwood,
condemned_rocky_mount, condemned_spartanburg, vacant_structure_hendersonville) is scoped to a
DIFFERENT producer's shape -- none accepts `row.get("source") == "gastonia_cityview_locator"` or
reads Gastonia's own case-id list -- so gap_matrix.py's 2026-11-20 run carried Gaston NC as a
`vacant_structure` cell (reported under its two surfaced gap_matrix columns, "condemned" and
"vacancy") of class `built-not-verified (source status unknown)`, 10 applicable rows each: real,
current, scraper-built data (the SAME 10 rows `code_enforcement_gastonia.py` already verifies
under the `code_enforcement` signal) that no registered `vacant_structure` verifier's `applies()`
ever recognized.

THE SOURCE AND THE CHECK. The scraper's own condemnation determination is read off the IDENTICAL
live field `code_enforcement_gastonia.py` already re-checks per claimed case -- the case's own
`StatusReference?referenceNumber=...` page's `#status` text (live-confirmed reachable 2026-11-20,
HTTP 200 in ~1-2s, no session cookie needed) -- just matched against the scraper's OWN
`_CONDEMNED_STATUS_RE` ("vacate"/"demolish", case-insensitive; distinct from `_SEVERE_RE`, which
reads the case CATEGORY, not the disposition) instead of `_is_closed`. So this module delegates
the live fetch to `code_enforcement_gastonia`'s own `_check_case`/`claimed_cases` byte-for-byte
rather than re-implementing or re-querying: one request per claimed case answers both signals,
the two verifiers just test a different regex against the SAME fetched status text and file
their own verdict under their own SIGNAL. Unlike `code_enforcement_gastonia.py`, every claimed
case is checked here, never only the distress-category ones -- the scraper's own condemnation
flag is set from ANY open case's STATUS, regardless of its CATEGORY (read the scraper's `fetch`
loop: `if is_open: ... if _CONDEMNED_STATUS_RE.search(status): condemned = True`, unconditioned
on `_SEVERE_RE`).

Live-verified 2026-11-20 against all 10 real Gaston `condemned` rows' own triggering case ids:
every one (CEH20261740, CEH20261868, CEH20250906, CEH20250684, CEH20222525, CEH20230451,
CEH20230452, CEH20230450, CEH20230449, CEH20250531 -- one case the oldest filed 2022) still reads
"Order to Demolish" or "Order to Demolish/Vacate" today, genuinely `confirmed` on all 10.

VERDICTS (core.py's meanings):
  confirmed    at least one claimed case reads back an OPEN status today whose text matches
               `_CONDEMNED_STATUS_RE` (`basis="case_condemned_on_portal"`).
  stale        at least one claimed case's page was read live and none of them is both open and
               condemned-worded any more (`no_longer_condemned`): the order was lifted, the case
               closed, or downgraded to a lesser status (e.g. "Order to Repair" alone, or
               "Notice/Order Sent") since the scrape -- the SAME "found, but the claim no longer
               holds" bucket `condemned_charlotte.py`'s own `no_open_fof_case` uses.
  unconfirmed  no claimed case's page could be fetched or every one came back "Invalid
               Complaint" (`code_enforcement_gastonia._check_case`'s own not-found shape) --
               never `refuted`, the same deliberate bias `code_enforcement_gastonia.py` already
               documents for this exact host/shape ("a false refuted/stale would wrongly end a
               real signal"); or the row carries no case ids at all (`no_case_ids`).

GOVERNS: deliberately omitted, same reasoning as condemned_adl.py's/condemned_charlotte.py's/
condemned_spartanburg.py's own docstrings -- `raw["condemned"]` is a bare flag with no
per-source provenance to clear selectively on a merged parcel; a stale verdict here could
silently clear ANOTHER source's bare `raw["condemned"] = True` on the same property. `applies()`
still scopes itself tightly by `row.get("source")` and the `code_enforcement` block's own
`source`, so it is never asked to answer for a row this producer did not actually write.

PRIVACY. ROW_SUMMARY_EXCLUDE drops owner_name: on these rows it is Gaston County's own
`CURR_NAME1` parcel-layer owner (`gastonia_code_enforcement.resolve_parcels`), the identical
sensitive join `code_enforcement_gastonia.py` already excludes for the same producer's rows.

TTL 14 days, retry 3 -- matches `code_enforcement_gastonia.py`'s own cadence for the SAME
underlying per-case live read (cases move within weeks, not daily).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..core import VerificationResult, result
from . import code_enforcement_gastonia as ceg

SIGNAL = "vacant_structure"
VERSION = "v1"
TTL_DAYS = 14
RETRY_DAYS = 3
ROW_SOURCE = ceg.CE_SOURCE          # "gastonia_cityview_locator"
SOURCE = ceg.SOURCE                 # "City of Gastonia CityView Portal (devsvcs.gastonianc.gov)"
ROW_SUMMARY_EXCLUDE = ("owner_name",)
MAX_CASES_CHECKED = ceg.MAX_CASES_CHECKED

_NAME = __name__.rsplit(".", 1)[-1]


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _ce_block(row: dict) -> Optional[dict]:
    ce = _raw(row).get("code_enforcement")
    return ce if isinstance(ce, dict) and ce.get("source") == ROW_SOURCE else None


def applies(row: dict) -> bool:
    if str(row.get("state") or "").strip().upper() != "NC":
        return False
    county = str(row.get("county") or "").strip().lower()
    if county.endswith(" county"):
        county = county[: -len(" county")]
    if county != "gaston":
        return False
    if _raw(row).get("condemned") is not True:
        return False
    return _ce_block(row) is not None


def is_condemned_status(status: Any) -> bool:
    """The scraper's own `_CONDEMNED_STATUS_RE` ("vacate"/"demolish"), never this module's own
    duplicate pattern -- a future wording change to that regex must change both signals' checks
    at once, never silently diverge."""
    return bool(ceg._scraper()._CONDEMNED_STATUS_RE.search(str(status or "")))


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    # claimed_cases() reads the SAME block applies() already confirmed is this producer's own
    # (ceg.claimed_cases only looks at raw['code_enforcement'], not raw['condemned']/['vacancy'],
    # but every row this module is asked about has already passed applies()'s block-identity gate).
    claimed = ceg.claimed_cases(row)
    ev: dict[str, Any] = {"county": "Gaston", "claimed_case_ids": [c["case_id"] for c in claimed]}
    if not claimed:
        ev["reason"] = "no_case_ids"
        return _res("unconfirmed", ev)

    # every claimed case, never only the distress-category ones: the scraper's own condemned
    # flag is set from ANY open case's STATUS text, unconditioned on the case's CATEGORY.
    checked = []
    for c in claimed[:MAX_CASES_CHECKED]:
        live = await ceg._check_case(c["case_id"], client)
        checked.append({**c, **live})
    ev["cases"] = checked

    condemned_now = [c for c in checked
                     if c.get("found") and c.get("live_open") and is_condemned_status(c.get("live_status"))]
    if condemned_now:
        ev["basis"] = "case_condemned_on_portal"
        return _res("confirmed", ev)

    readable = [c for c in checked if c.get("found")]
    if readable:
        ev["reason"] = "no_longer_condemned"
        return _res("stale", ev)

    if any("error" in c for c in checked):
        ev["reason"] = "cases_unreadable"
    else:
        ev["reason"] = "case_not_found_on_portal"
    return _res("unconfirmed", ev)
