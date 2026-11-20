"""code_enforcement, Charleston County SC's own EnerGov history layer
(scrapers/counties_sc/charleston_energov_history.py, source
"counties_sc.charleston_energov_history"): is the row's claimed building-code case still inside
the scraper's own 365-day "treated as open" window as of TODAY?

WHY THIS EXISTS (2026-11-20, round-77 continuation of the SAME "verifier narrower than producer
set" sweep that found elderly_disabled_sc_homestead.py, code_enforcement_gastonia.py,
code_enforcement_spartanburg.py and condemned_gastonia.py the four previous rounds).
counties_sc.charleston_energov_history is a LIVE, wired-in producer (main.py's own
DATELESS_OK_SOURCES list; confirmed live via board_stream.iter_board_rows() on today's board:
2,378 Charleston SC rows total, 1,345 carrying a dict-shaped raw['code_enforcement'] block, 55
of those still reading `code_enforcement_open()==True` today -- EXACTLY the "55 SC Charleston
rows, built-not-verified" count round 76's own commit named). None of the four EXISTING
code_enforcement verifiers recognizes this shape: code_enforcement_adl.py requires
`ce['has_open']` is True (Charleston's block never sets that key at all, only `open_violations`)
AND `ce['source']` to be one of arcgis_distress_layers.py's own Layer slugs (Charleston is a
standalone scraper, not built on that generic registry); code_enforcement_city_open_data.py
requires `CE_SOURCE=="city_open_data"`; code_enforcement_henderson.py and
code_enforcement_gastonia.py are each hardcoded to a different county. So every one of these 55
rows read `built-not-verified (source status unknown)` in gap_matrix.py, the identical bug shape
as all four prior fixes.

THE HOST (re-tested live 2026-11-20, after two straight blocked rounds -- round 75 and round 76
each found gisccapps.charlestoncounty.org completing TCP+TLS in ~0.3-0.5s then returning zero
HTTP bytes until timeout on 3/3 attempts). Today's re-test found it RECOVERED: the layer's own
`?f=json` metadata call succeeded in 0.41s on the first attempt; a `returnCountOnly` query
against energov_history/MapServer/0 answered 387,672 in 0.24s; of 5 back-to-back real
CodeManagement queries (the scraper's own `where=` clause, 1.5s apart) all 5 succeeded in
0.24-0.39s each. (Two isolated reads during this same session's warm-up DID still time out at
25s before succeeding on an immediate retry -- a cold-connection blip, not the sustained
3-for-3 block the two prior rounds measured; a transient-reason / retry path is NOT added here
because this module's per-case `query_one()` failure already answers `unconfirmed`, which the
sweep retries on its own `RETRY_DAYS` cadence regardless.)

THE SOURCE AND THE CHECK. The SAME energov_history/MapServer/0 layer charleston_energov_history.py
itself reads has NO status column (the scraper's own docstring: "the layer carries no case
status" -- every CASENUMBER the county has ever opened stays a real, queryable record forever;
closing a case does not drop it from the feed). So there is nothing to re-check LIVE except the
one fact that actually changes with the calendar: does today still fall inside `OPEN_DAYS` (365,
the scraper's own constant, reused byte-for-byte here) of the case's APPLICATIONDATE? This
module queries the identical layer (`HISTORY`, reused from the scraper) for the row's single
newest claimed case (`violations[0]`, the case the row's own `stale_after` was computed from --
`group_by_property()` sorts each property's code cases newest-first before `to_listing()` ever
writes the list, and the AGGREGATE row goes stale only when its newest case ages out, not when
EVERY individual case does, so re-checking any older claimed case the row carries would answer a
question the row's own overall verdict never asked), scoped to `MODULENAME='CodeManagement'` (the
scraper's own code-case module, so a demolition-permit CASENUMBER sharing a similar format can
never be mismatched in). Found live -> recompute the SAME `stale_after = APPLICATIONDATE +
365 days` arithmetic the scraper itself uses, off the live APPLICATIONDATE rather than the
board's stored one (catching a county-side correction to the filed date, not just a clock tick).

WHICH ROWS (applies). Charleston SC rows whose `source` is
"counties_sc.charleston_energov_history", whose `raw['code_enforcement']` is a dict carrying
THIS source, and for which `signal_freshness.code_enforcement_open()` -- the SAME predicate the
scorer and gap_matrix.py's own "built" count already use -- reads True today: a row whose newest
case has already aged past its own `stale_after` is not a live, open claim gap_matrix would even
count as `built` any more, so there is nothing new for this module to say about it (code_enforcement_
adl.py's own `has_open` gate makes the identical choice for its four county shapes).

VERDICTS (core.py's meanings):
  confirmed    the newest claimed CASENUMBER is still on the live layer, MODULENAME
               'CodeManagement', and its live APPLICATIONDATE keeps it inside the 365-day
               window as of today.
  stale        the case is still on the live layer but its (live) APPLICATIONDATE now falls
               OUTSIDE the 365-day window -- the exact window boundary moved past it since the
               row was scraped, the same aging a closed-case feed would show, just computed by
               date instead of by a status flag this layer never carries.
  refuted      a fresh `MODULENAME='CodeManagement' AND CASENUMBER='<id>'` query returns zero
               features: the case number no longer exists in the county's own history at all
               (a data correction on the county's side since the scrape), the same
               `no_case_on_layer` -> refuted convention code_enforcement_adl.py and
               condemned_spartanburg.py both already use.
  unconfirmed  the service could not be asked (`endpoint_unreachable`, the exact failure mode
               round 75/76 hit and today's re-test did not), the matched record's
               APPLICATIONDATE could not be parsed (`date_unparseable`), or the row carries no
               claimed case id at all (`no_case_ids`, a block that lost its `violations` list on
               a merge).

GOVERNS "code_enforcement:counties_sc.charleston_energov_history", the same per-source qualifier
every other sibling in this family uses (code_enforcement_gastonia.py,
code_enforcement_spartanburg.py): a refuted/stale verdict ends only THIS source's credit on a
merged parcel, never another source's block sharing the same property-keyed ledger entry.

TTL 14 days, retry 3 -- the same cadence code_enforcement_adl.py/_henderson.py/_gastonia.py use
for this identical signal (not Spartanburg's 30/7: that module reuses an assessor CONDITION
rating that only changes on inspection; this one reuses a 365-day CALENDAR window that moves
every day, closer in nature to the active-caseload siblings).

EVIDENCE: the matched CASENUMBER, its live MODULENAME/CASETYPE/APPLICATIONDATE and the recomputed
stale_after -- no field beyond the scraper's own already-privacy-reviewed `HIST_FIELDS` tuple
(no owner, applicant or complainant column; Charleston's EnerGov history layer carries none of
those and the scraper never requests them).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from ...signal_freshness import code_enforcement_open
from ..core import VerificationResult, result
from . import _arcgis_layer as agl

SIGNAL = "code_enforcement"
VERSION = "v1"
TTL_DAYS = 14
RETRY_DAYS = 3
ROW_SOURCE = "counties_sc.charleston_energov_history"
SOURCE = "Charleston County SC ENERGOV history (gisccapps.charlestoncounty.org)"
GOVERNS = (f"code_enforcement:{ROW_SOURCE}",)
_NAME = __name__.rsplit(".", 1)[-1]


def _scraper():
    """scrapers/counties_sc/charleston_energov_history.py, imported on first use (the registry
    imports every verifier; the full scraper/http stack must not load in just to answer
    applies())."""
    from ...scrapers.counties_sc import charleston_energov_history as m
    return m


def _raw(row: dict) -> dict:
    r = row.get("raw")
    return r if isinstance(r, dict) else {}


def _block(row: dict) -> Optional[dict]:
    ce = _raw(row).get("code_enforcement")
    return ce if isinstance(ce, dict) and ce.get("source") == ROW_SOURCE else None


def applies(row: dict) -> bool:
    if row.get("source") != ROW_SOURCE:
        return False
    ce = _block(row)
    if ce is None:
        return False
    return code_enforcement_open(ce, date.today())


def newest_case_id(row: dict) -> Optional[str]:
    """The row's own newest claimed case id (`violations[0]`, the case `stale_after` was
    computed from -- see the module docstring's MATCHING note)."""
    ce = _block(row) or {}
    vs = ce.get("violations")
    if not isinstance(vs, list) or not vs:
        return None
    first = vs[0]
    cid = str(first.get("case_id") or "").strip() if isinstance(first, dict) else ""
    return cid or None


def _esc(v: str) -> str:
    return v.replace("'", "''")


def _res(verdict: str, ev: dict) -> VerificationResult:
    return result(SIGNAL, verdict, ev, source=SOURCE, version=VERSION, verifier=_NAME)


async def verify(row: dict, client, *, today: Optional[date] = None) -> VerificationResult:
    today = today or date.today()
    m = _scraper()
    ev: dict[str, Any] = {}

    case_id = newest_case_id(row)
    if not case_id:
        ev["reason"] = "no_case_ids"
        return _res("unconfirmed", ev)
    ev["matched_case"] = case_id

    where = f"MODULENAME='CodeManagement' AND CASENUMBER='{_esc(case_id)}'"
    feats = await agl.query_one(client, m.HISTORY, where=where, out_fields=",".join(m.HIST_FIELDS))
    if feats is None:
        ev["reason"] = "endpoint_unreachable"
        return _res("unconfirmed", ev)
    if not feats:
        ev["reason"] = "no_case_on_layer"
        return _res("refuted", ev)

    a = feats[0]
    ev["live_module"] = a.get("MODULENAME")
    ev["live_case_type"] = a.get("CASETYPE")
    live_date = agl.epoch_date(a.get("APPLICATIONDATE"))
    ev["live_application_date"] = live_date
    if not live_date:
        ev["reason"] = "date_unparseable"
        return _res("unconfirmed", ev)

    stale_after = date.fromisoformat(live_date) + timedelta(days=m.OPEN_DAYS)
    ev["live_stale_after"] = stale_after.isoformat()
    if stale_after >= today:
        return _res("confirmed", ev)
    ev["reason"] = "aged_past_open_window"
    return _res("stale", ev)
