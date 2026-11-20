"""code_enforcement_charleston.py: the sibling verifier over
counties_sc/charleston_energov_history.py's own EnerGov history layer
(source=="counties_sc.charleston_energov_history") -- the SAME bug class as
code_enforcement_gastonia.py's and code_enforcement_spartanburg.py's fixes two rounds earlier (a
verifier whose scope is narrower than the real, live, wired producer set): none of the four
existing code_enforcement verifiers (adl, city_open_data, henderson, gastonia, spartanburg)
recognizes this fifth, distinct shape (a dict with `open_violations`/`stale_after`, never
`has_open`), so every one of the 55 Charleston SC rows `signal_freshness.code_enforcement_open()`
currently reads as still-open (live-counted on the 2026-11-20 board) read as
`built-not-verified` in gap_matrix.py however long the scraper ran.

What this pins:
  * the registry's own contract (signal/ttl/retry/governs);
  * applies(): Charleston rows whose block is THIS source and still open per
    signal_freshness.code_enforcement_open() today; wrong source and an already-aged-out row
    (stale_after in the past) both rejected;
  * every verdict against the real ArcGIS query shape this module builds for the scraper's own
    `HISTORY` layer (MapServer/0/query, MODULENAME='CodeManagement' AND CASENUMBER='<id>'):
    confirmed (a case whose live APPLICATIONDATE keeps it inside the 365-day OPEN_DAYS window),
    stale (a case still on the layer but its live APPLICATIONDATE now falls outside that
    window -- live-reproduced against a real board case, BIS-04-19-01887, filed 2019-04-30 and
    long past its own 2020-04-29 stale_after), refuted (no feature at all for the claimed
    CASENUMBER -- live-reproduced against a fabricated reference), and the three unconfirmed
    lanes (no_case_ids, endpoint_unreachable, date_unparseable);
  * only the row's single NEWEST claimed case is ever queried (the one the row's own aggregate
    `stale_after` was computed from), never every case in `violations`.
"""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import _arcgis_layer as agl
from foreclosure_scraper.verification.verifiers import code_enforcement_charleston as cv

TODAY = date(2026, 11, 20)


def run(coro):
    return asyncio.run(coro)


def _url(case_id: str) -> str:
    from foreclosure_scraper.scrapers.counties_sc import charleston_energov_history as m
    where = f"MODULENAME='CodeManagement' AND CASENUMBER='{case_id}'"
    return agl.query_url(m.HISTORY, {"where": where, "outFields": ",".join(m.HIST_FIELDS),
                                     "returnGeometry": "false", "resultRecordCount": "2000"})


def _feature_json(case_id: str, *, module: str = "CodeManagement",
                  case_type: str = "Building Services", epoch_ms: int) -> str:
    import json
    return json.dumps({"features": [{"attributes": {
        "OBJECTID": 1, "MODULENAME": module, "CASENUMBER": case_id, "CASETYPE": case_type,
        "WORKCLASS": None, "APPLICATIONDATE": epoch_ms}}]})


_EMPTY = '{"features": []}'

#: 2026-11-10 (10 days before TODAY, well inside the 365-day window) and 2019-04-30 (the real
#: board case this module's docstring and the live smoke test both reproduce -- long since aged
#: past its own 2020-04-29 stale_after), as ArcGIS epoch-millisecond values.
_OPEN_CASE, _OPEN_MS = "BIS-11-26-00001", 1794268800000       # 2026-11-10T00:00:00Z
_OLD_CASE, _OLD_MS = "BIS-04-19-01887", 1556582400000         # 2019-04-30T00:00:00Z
_MISSING_CASE = "BIS-00-00-99999"
_BAD_DATE_CASE = "BIS-00-00-00001"

RESP = {
    _url(_OPEN_CASE): _feature_json(_OPEN_CASE, epoch_ms=_OPEN_MS),
    _url(_OLD_CASE): _feature_json(_OLD_CASE, epoch_ms=_OLD_MS),
    _url(_MISSING_CASE): _EMPTY,
    _url(_BAD_DATE_CASE): _feature_json(_BAD_DATE_CASE, epoch_ms=None),
}


def _row(case_id: str, *, stale_after: str = "2027-01-01", open_violations: int = 1) -> dict:
    ce = {"county": "Charleston", "open_violations": open_violations, "total_violations": 1,
         "status_known": False, "stale_after": stale_after, "source": cv.ROW_SOURCE,
         "violations": [{"case_id": case_id, "violation": "Building Services"}]}
    return {"source": cv.ROW_SOURCE, "state": "SC", "county": "Charleston", "raw": {"code_enforcement": ce}}


def _check(row: dict, resp: dict | None = None):
    return run(cv.verify(row, ReplayFetcher(RESP if resp is None else resp), today=TODAY))


# --------------------------------------------------------------------------- #
# contract                                                                    #
# --------------------------------------------------------------------------- #

def test_discovered_with_contract():
    vs = {v.name: v for v in discover()}
    v = vs["code_enforcement_charleston"]
    assert (v.signal, v.ttl_days, v.retry_days) == ("code_enforcement", 14, 3)
    assert v.governs == (f"code_enforcement:{cv.ROW_SOURCE}",)
    assert v.identity == "property"


# --------------------------------------------------------------------------- #
# applies()                                                                   #
# --------------------------------------------------------------------------- #

def test_applies_charleston_this_source_still_open():
    row = _row(_OPEN_CASE, stale_after="2027-11-10")
    assert cv.applies(row)


def test_applies_rejects_wrong_source_or_already_aged_out():
    assert not cv.applies({**_row(_OPEN_CASE), "source": "counties_sc.spartanburg_condemned"})
    row_ce_wrong_source = _row(_OPEN_CASE)
    row_ce_wrong_source["raw"]["code_enforcement"]["source"] = "counties_sc.spartanburg_condemned"
    assert not cv.applies(row_ce_wrong_source)
    # already aged out (stale_after in the past relative to code_enforcement_open's own
    # date.today() call) reads as not-open, so it is no longer a "built" claim to re-check
    aged = _row(_OLD_CASE, stale_after="2020-04-29")
    assert not cv.applies(aged)
    assert not cv.applies({"source": cv.ROW_SOURCE, "raw": None})


# --------------------------------------------------------------------------- #
# verdicts                                                                    #
# --------------------------------------------------------------------------- #

def test_confirmed_when_the_newest_case_is_still_inside_the_open_window_live():
    res = _check(_row(_OPEN_CASE, stale_after="2027-11-10"))
    assert res.verdict == "confirmed"
    assert res.evidence["matched_case"] == _OPEN_CASE
    assert res.evidence["live_application_date"] == "2026-11-10"
    assert res.evidence["live_stale_after"] == "2027-11-10"


def test_stale_when_the_live_application_date_has_aged_past_the_window():
    """Live-reproduced against a real board case: filed 2019-04-30, 365 days later is
    2020-04-29, long before TODAY."""
    res = _check(_row(_OLD_CASE, stale_after="2020-04-29"))
    assert res.verdict == "stale"
    assert res.evidence["reason"] == "aged_past_open_window"
    assert res.evidence["live_stale_after"] == "2020-04-29"


def test_refuted_when_the_case_number_no_longer_exists_on_the_layer():
    res = _check(_row(_MISSING_CASE, stale_after="2027-01-01"))
    assert res.verdict == "refuted"
    assert res.evidence["reason"] == "no_case_on_layer"


def test_unconfirmed_no_case_ids():
    row = _row(_OPEN_CASE)
    row["raw"]["code_enforcement"]["violations"] = []
    res = _check(row, resp={})
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_case_ids"


def test_unconfirmed_endpoint_unreachable():
    res = _check(_row(_OPEN_CASE), resp={})   # no recording at all -> ReplayFetcher LookupError
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "endpoint_unreachable"


def test_unconfirmed_date_unparseable():
    res = _check(_row(_BAD_DATE_CASE, stale_after="2027-01-01"))
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "date_unparseable"


def test_only_the_newest_claimed_case_is_ever_queried():
    """A row claiming two cases: only violations[0] (the newest, the one stale_after was
    computed from) may be fetched -- a request for the second would KeyError against this
    response map, proving it was never asked."""
    ce = _row(_OPEN_CASE, stale_after="2027-11-10")["raw"]["code_enforcement"]
    ce["violations"] = [{"case_id": _OPEN_CASE, "violation": "Building Services"},
                        {"case_id": _OLD_CASE, "violation": "Building Services"}]
    row = {"source": cv.ROW_SOURCE, "raw": {"code_enforcement": ce}}
    res = _check(row, resp={_url(_OPEN_CASE): RESP[_url(_OPEN_CASE)]})
    assert res.verdict == "confirmed"
    assert res.evidence["matched_case"] == _OPEN_CASE
