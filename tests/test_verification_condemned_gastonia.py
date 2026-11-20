"""condemned_gastonia.py: the sibling vacant_structure verifier over
counties_nc.gastonia_code_enforcement.py's own CityView feed (source=="gastonia_cityview_locator")
-- the SAME bug class as code_enforcement_gastonia.py's 2026-11-19 fix and
code_enforcement_spartanburg.py's, just on the SIBLING vacant_structure signal (raw["condemned"]
/ raw["vacancy"], not raw["code_enforcement"]) fed by the identical producer: the six existing
vacant_structure verifiers (adl, charlotte, greenwood, rocky_mount, spartanburg, hendersonville)
never recognized this source shape, so every Gaston NC `condemned`/`vacancy` row (10 applicable
on the 2026-11-20 board, the SAME 10 rows code_enforcement_gastonia.py already verifies under
the sibling signal) read as `built-not-verified` in gap_matrix.py however long the scraper ran.

What this pins:
  * the registry's own contract (signal/ttl/retry), GOVERNS deliberately empty;
  * applies(): NC Gaston rows with a bare raw["condemned"]=True AND this producer's own
    code_enforcement block (source gate), trailing " county", wrong state/county/source/missing-
    flag all rejected;
  * confirmed against the REAL live StatusReference page shape for a real board case id
    (CEH20222525, live-fetched 2026-11-20: "Order to Demolish", filed 2022, still open today);
  * stale and the two unconfirmed lanes against synthetic rows (a closed/downgraded case cannot
    be produced from a real CURRENT board row claiming condemned=True by definition -- the
    producer only ever sets that flag from a status that, at scrape time, read as open and
    condemned-worded);
  * every claimed case is checked, never only distress-category ones -- the opposite economy
    from code_enforcement_gastonia.py, because the scraper's own condemned flag is set from ANY
    open case's STATUS regardless of its CATEGORY.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import code_enforcement_gastonia as ceg
from foreclosure_scraper.verification.verifiers import condemned_gastonia as gv

#: live-fetched 2026-11-20, a real Gaston board row's own condemned-triggering case (filed 2022,
#: still "Order to Demolish" today -- confirmed against this exact CityView host)
_DETAIL_DEMOLISH = """
<!DOCTYPE html>
<html lang="en"><head><title>Complaint Status  City of Gastonia  - CityView Portal</title></head>
<body>
<h2 class="tabTitle">Complaint Status</h2><p class="tabSubTitle">CEH20222525</p>
<div id="blkstatus" class="cv-clear displayField" >
<div class="left1"><label id="l_status" for="status">Status:</label></div>
<div class="right1"><div class="cv-input-wrapper">
<div id="status" class="inputText" data-cy="inp-status">Order to Demolish</div>
</div></div></div>
</body></html>
"""

#: same shape code_enforcement_gastonia.py's own test fixtures use: a case the city has since
#: closed (no longer open, so never condemned-live regardless of wording)
_DETAIL_CLOSED = """
<!DOCTYPE html>
<html lang="en"><head><title>Complaint Status  City of Gastonia  - CityView Portal</title></head>
<body>
<h2 class="tabTitle">Complaint Status</h2><p class="tabSubTitle">CEH20230451</p>
<div id="blkstatus" class="cv-clear displayField" >
<div class="left1"><label id="l_status" for="status">Status:</label></div>
<div class="right1"><div class="cv-input-wrapper">
<div id="status" class="inputText" data-cy="inp-status">Closed</div>
</div></div></div>
</body></html>
"""

#: a currently-open case whose order was downgraded (repair alone, never "vacate"/"demolish") --
#: still open, still a real code case, but no longer a condemnation determination
_DETAIL_REPAIR_ONLY = """
<!DOCTYPE html>
<html lang="en"><head><title>Complaint Status  City of Gastonia  - CityView Portal</title></head>
<body>
<h2 class="tabTitle">Complaint Status</h2><p class="tabSubTitle">CEH20230452</p>
<div id="blkstatus" class="cv-clear displayField" >
<div class="left1"><label id="l_status" for="status">Status:</label></div>
<div class="right1"><div class="cv-input-wrapper">
<div id="status" class="inputText" data-cy="inp-status">Order to Repair</div>
</div></div></div>
</body></html>
"""

#: the same "Invalid Complaint" not-found shape code_enforcement_gastonia.py's own tests pin
_DETAIL_NOT_FOUND = """
<!DOCTYPE html>
<html lang="en"><head><title>Invalid Complaint

    City of Gastonia
 - CityView Portal</title></head>
<body><h2 class="tabTitle">Invalid Complaint</h2></body></html>
"""

_URL_DEMOLISH = ceg.DETAIL_URL.format(ref="CEH20222525")
_URL_CLOSED = ceg.DETAIL_URL.format(ref="CEH20230451")
_URL_REPAIR_ONLY = ceg.DETAIL_URL.format(ref="CEH20230452")
_URL_NOT_FOUND = ceg.DETAIL_URL.format(ref="CEZZZZ99999999")

RESP = {_URL_DEMOLISH: _DETAIL_DEMOLISH, _URL_CLOSED: _DETAIL_CLOSED,
        _URL_REPAIR_ONLY: _DETAIL_REPAIR_ONLY, _URL_NOT_FOUND: _DETAIL_NOT_FOUND}


def run(coro):
    return asyncio.run(coro)


def _case(case_id: str, violation: str, status: str, open_: bool) -> dict:
    return {"case_id": case_id, "violation": violation, "status": status, "open": open_}


def _row(cases: list, *, state: str = "NC", county: str = "Gaston", condemned: bool = True,
         ce_source: str = ceg.CE_SOURCE, **kw) -> dict:
    ce = {"county": "Gaston", "city": "Gastonia", "has_open": True, "violations": cases,
         "source": ce_source}
    raw: dict = {"code_enforcement": ce}
    if condemned:
        raw["condemned"] = True
        raw["vacancy"] = {"vacant": True, "boarded_up": None, "utility_status": None,
                          "source": ce_source}
    row = {"state": state, "county": county, "parcel_id": "3546-00-0000", "raw": raw}
    row.update(kw)
    return row


def _check(row: dict, resp: dict | None = None):
    return run(gv.verify(row, ReplayFetcher(RESP if resp is None else resp)))


# --------------------------------------------------------------------------- #
# contract                                                                    #
# --------------------------------------------------------------------------- #

def test_discovered_with_contract():
    vs = {v.name: v for v in discover()}
    v = vs["condemned_gastonia"]
    assert (v.signal, v.ttl_days, v.retry_days) == ("vacant_structure", 14, 3)
    assert v.governs == ()
    assert v.identity == "property"


# --------------------------------------------------------------------------- #
# applies()                                                                   #
# --------------------------------------------------------------------------- #

def test_applies_nc_gaston_condemned_this_source():
    row = _row([_case("CEH20222525", "Housing", "Order to Demolish", True)])
    assert gv.applies(row)


def test_applies_tolerates_trailing_county_suffix():
    row = _row([_case("CEH20222525", "Housing", "Order to Demolish", True)], county="Gaston County")
    assert gv.applies(row)


def test_applies_rejects_wrong_state_county_source_or_missing_flag():
    base = [_case("CEH20222525", "Housing", "Order to Demolish", True)]
    assert not gv.applies(_row(base, state="SC"))
    assert not gv.applies(_row(base, county="Mecklenburg"))
    assert not gv.applies(_row(base, condemned=False))
    assert not gv.applies(_row(base, ce_source="henderson_ordinance_violations_tracking"))
    assert not gv.applies({"state": "NC", "county": "Gaston", "raw": None})
    # condemned=True with NO matching code_enforcement block at all (a merge artifact)
    assert not gv.applies({"state": "NC", "county": "Gaston", "raw": {"condemned": True}})


# --------------------------------------------------------------------------- #
# verdicts                                                                    #
# --------------------------------------------------------------------------- #

def test_confirmed_when_a_claimed_case_still_reads_condemned_and_open_live():
    row = _row([_case("CEH20222525", "Housing", "Order to Demolish", True)])
    res = _check(row)
    assert res.verdict == "confirmed"
    assert res.evidence["basis"] == "case_condemned_on_portal"
    assert res.evidence["cases"][0]["live_status"] == "Order to Demolish"


def test_stale_when_the_only_claimed_case_has_since_closed():
    row = _row([_case("CEH20230451", "Housing", "Order to Demolish", True)])
    res = _check(row, resp={_URL_CLOSED: _DETAIL_CLOSED})
    assert res.verdict == "stale"
    assert res.evidence["reason"] == "no_longer_condemned"


def test_stale_when_the_order_was_downgraded_to_repair_only():
    """Still open, still a real code case -- but 'Order to Repair' alone is NOT a condemnation
    determination (the scraper's own _CONDEMNED_STATUS_RE never matches it): no longer
    condemned live, even though the underlying code_enforcement case remains open."""
    row = _row([_case("CEH20230452", "Housing", "Order to Demolish", True)])
    res = _check(row, resp={_URL_REPAIR_ONLY: _DETAIL_REPAIR_ONLY})
    assert res.verdict == "stale"
    assert res.evidence["cases"][0]["live_open"] is True
    assert res.evidence["cases"][0]["live_status"] == "Order to Repair"


def test_unconfirmed_no_case_ids():
    row = _row([])
    res = _check(row, resp={})
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_case_ids"


def test_unconfirmed_case_not_found_on_portal():
    row = _row([_case("CEZZZZ99999999", "Housing", "Order to Demolish", True)])
    res = _check(row)
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "case_not_found_on_portal"
    assert res.evidence["cases"][0]["found"] is False


def test_every_claimed_case_checked_not_only_distress_category():
    """Unlike code_enforcement_gastonia.py, a non-distress-category case (Vegetation/Weeds,
    never matched by _SEVERE_RE) is still fetched here -- the condemned flag is keyed on STATUS,
    not CATEGORY, so both claimed cases must be answered or this raises LookupError."""
    row = _row([_case("CEVEG20262170", "Vegetation/Weeds", "Order to Repair", True),
               _case("CEH20222525", "Housing", "Order to Demolish", True)])
    url_veg = ceg.DETAIL_URL.format(ref="CEVEG20262170")
    res = _check(row, resp={url_veg: _DETAIL_REPAIR_ONLY, _URL_DEMOLISH: _DETAIL_DEMOLISH})
    assert res.verdict == "confirmed"
    assert {c["case_id"] for c in res.evidence["cases"]} == {"CEVEG20262170", "CEH20222525"}
