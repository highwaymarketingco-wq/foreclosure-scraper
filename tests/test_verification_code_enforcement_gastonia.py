"""code_enforcement_gastonia.py: the sibling verifier over counties_nc.gastonia_code_enforcement.py's
own CityView feed (source=="gastonia_cityview_locator") -- the SAME bug class as
elderly_disabled_sc_homestead.py's 2026-11-19 fix (a verifier whose scope is narrower than the
real, live, wired producer set): the existing three code_enforcement verifiers (adl,
city_open_data, henderson) never recognized this fourth, distinct source shape, so every Gaston
NC row (789 applicable, 1,516 raw `has_open` rows on the 2026-11-19 board) read as
`built-not-verified` in gap_matrix.py however long the scraper ran.

What this pins:
  * the registry's own contract (signal/ttl/retry/governs);
  * applies(): NC Gaston rows whose block is THIS source and has_open, trailing " county",
    wrong state/county/source/closed all rejected;
  * every verdict against the REAL live `StatusReference?referenceNumber=...` page shape
    (fetched live 2026-11-19 through the real Fetcher for genuine board rows: confirmed (601
    N WELDON ST, a real open Public Nuisance case -- live status text matches
    LocatorResultsPolygon's own `Status` for the same case in the same session), refuted
    (a Vegetation/Weeds-only claim: category_not_distress, never fetched -- no claimed case is
    a distress category so no request is ever made), and stale (an Unauthorized Encampment
    case the city has since closed) all reproduced live; plus the two unconfirmed lanes
    (no_case_ids, case_not_found_on_portal -- the live "Invalid Complaint" page shape) against
    synthetic rows, since neither can be produced from a real current board row by definition;
  * the live-sampled HTML fragments below are trimmed, structurally verbatim excerpts (the
    surrounding ~18 KB / ~9.6 KB of CityView boilerplate is cut, the #status/#description/title
    blocks the verifier actually reads are untouched), the same convention
    tests/test_gastonia_code_enforcement.py already uses for the scraper's own detail-page
    fixtures;
  * only distress-category claimed cases are ever fetched (the economy the module docstring
    claims): a row claiming only non-distress cases makes zero live requests.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import code_enforcement_gastonia as gv

#: live-sampled 2026-11-19, a real OPEN Public Nuisance case (CEPNU20253132, confirmed against
#: the scraper's own bulk LocatorResultsPolygon answer for the same ReferenceNumber in the same
#: session: Status "Abatement" both places)
_DETAIL_OPEN_ABATEMENT = """
<!DOCTYPE html>
<html lang="en"><head><title>Complaint Status  City of Gastonia  - CityView Portal</title></head>
<body>
<h2 class="tabTitle">Complaint Status</h2><p class="tabSubTitle">CEPNU20253132</p>
<div id="blkstatus" class="cv-clear displayField" >
<div class="left1"><label id="l_status" for="status">Status:</label></div>
<div class="right1"><div class="cv-input-wrapper">
<div id="status" class="inputText" data-cy="inp-status">Abatement</div>
</div></div></div>
<div id="blkdescription" class="cv-clear displayField" >
<div class="right1"><div class="cv-input-wrapper">
<div id="description" class="inputText" data-cy="inp-description"></div>
</div></div></div>
</body></html>
"""

#: live-sampled 2026-11-19, a real case the city has since CLOSED (CEENC20231977, Unauthorized
#: Encampment -- confirmed against LocatorResultsPolygon's own "Closed - No Violations")
_DETAIL_CLOSED = """
<!DOCTYPE html>
<html lang="en"><head><title>Complaint Status  City of Gastonia  - CityView Portal</title></head>
<body>
<h2 class="tabTitle">Complaint Status</h2><p class="tabSubTitle">CEENC20231977</p>
<div id="blkstatus" class="cv-clear displayField" >
<div class="left1"><label id="l_status" for="status">Status:</label></div>
<div class="right1"><div class="cv-input-wrapper">
<div id="status" class="inputText" data-cy="inp-status">Closed - No Violations</div>
</div></div></div>
</body></html>
"""

#: live-sampled 2026-11-19: a retired/mistyped ReferenceNumber -- HTTP 200, no #status div at
#: all, a much shorter "Invalid Complaint" page (the clean not-found shape this verifier keys on)
_DETAIL_NOT_FOUND = """
<!DOCTYPE html>
<html lang="en"><head><title>Invalid Complaint

    City of Gastonia
 - CityView Portal</title></head>
<body><h2 class="tabTitle">Invalid Complaint</h2></body></html>
"""

_URL_OPEN = gv.DETAIL_URL.format(ref="CEPNU20253132")
_URL_CLOSED = gv.DETAIL_URL.format(ref="CEENC20231977")
_URL_NOT_FOUND = gv.DETAIL_URL.format(ref="CEZZZZ99999999")

RESP = {_URL_OPEN: _DETAIL_OPEN_ABATEMENT, _URL_CLOSED: _DETAIL_CLOSED,
        _URL_NOT_FOUND: _DETAIL_NOT_FOUND}


def run(coro):
    return asyncio.run(coro)


def _case(case_id: str, violation: str, status: str, open_: bool) -> dict:
    return {"case_id": case_id, "violation": violation, "status": status, "open": open_}


def _row(cases: list, *, state: str = "NC", county: str = "Gaston", has_open: bool = True,
         **kw) -> dict:
    ce = {"county": "Gaston", "city": "Gastonia", "has_open": has_open,
         "violations": cases, "source": gv.CE_SOURCE}
    row = {"state": state, "county": county, "parcel_id": "3546-00-0000", "raw": {"code_enforcement": ce}}
    row.update(kw)
    return row


def _check(row: dict, resp: dict | None = None):
    return run(gv.verify(row, ReplayFetcher(RESP if resp is None else resp)))


# --------------------------------------------------------------------------- #
# contract                                                                    #
# --------------------------------------------------------------------------- #

def test_discovered_with_contract():
    vs = {v.name: v for v in discover()}
    v = vs["code_enforcement_gastonia"]
    assert (v.signal, v.ttl_days, v.retry_days) == ("code_enforcement", 14, 3)
    assert v.governs == (f"code_enforcement:{gv.CE_SOURCE}",)
    assert v.identity == "property"


# --------------------------------------------------------------------------- #
# applies()                                                                   #
# --------------------------------------------------------------------------- #

def test_applies_nc_gaston_this_source_open():
    row = _row([_case("CEPNU20253132", "Public Nuisance", "Abatement", True)])
    assert gv.applies(row)


def test_applies_tolerates_trailing_county_suffix():
    row = _row([_case("CEPNU20253132", "Public Nuisance", "Abatement", True)], county="Gaston County")
    assert gv.applies(row)


def test_applies_rejects_wrong_state_county_source_or_closed():
    base = [_case("CEPNU20253132", "Public Nuisance", "Abatement", True)]
    assert not gv.applies(_row(base, state="SC"))
    assert not gv.applies(_row(base, county="Mecklenburg"))
    assert not gv.applies(_row(base, has_open=False))
    assert not gv.applies({**_row(base), "raw": {"code_enforcement": {"has_open": True,
                                                  "source": "henderson_ordinance_violations_tracking"}}})
    assert not gv.applies({"state": "NC", "county": "Gaston", "raw": None})


# --------------------------------------------------------------------------- #
# verdicts                                                                    #
# --------------------------------------------------------------------------- #

def test_confirmed_when_a_distress_case_is_still_open_live():
    row = _row([_case("CEPNU20253132", "Public Nuisance", "Abatement", True)])
    res = _check(row)
    assert res.verdict == "confirmed"
    assert res.evidence["basis"] == "case_open_on_portal"
    assert res.evidence["cases"][0]["live_status"] == "Abatement"


def test_refuted_when_no_claimed_case_is_a_distress_category():
    """Vegetation/Weeds does not match _SEVERE_RE: has_open counted it toward the board's flag,
    but it never counted toward the scorer's vacancy_adjacent-gated credit -- refuted with zero
    live requests (nothing to fetch: no distress case was ever claimed)."""
    row = _row([_case("CEVEG20262170", "Vegetation/Weeds", "Open", True)])
    res = _check(row, resp={})       # an empty response map: any fetch attempt would KeyError
    assert res.verdict == "refuted"
    assert res.evidence["reason"] == "category_not_distress"
    assert "cases" not in res.evidence


def test_stale_when_the_only_distress_case_has_since_closed():
    row = _row([_case("CEENC20231977", "Unauthorized Encampment", "Closed - No Violations", False)])
    res = _check(row)
    assert res.verdict == "stale"
    assert res.evidence["reason"] == "case_closed"


def test_unconfirmed_no_case_ids():
    row = _row([])
    res = _check(row, resp={})
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_case_ids"


def test_unconfirmed_case_not_found_on_portal():
    row = _row([_case("CEZZZZ99999999", "Public Nuisance", "Open", True)])
    res = _check(row)
    assert res.verdict == "unconfirmed"
    assert res.evidence["reason"] == "case_not_found_on_portal"
    assert res.evidence["cases"][0]["found"] is False


def test_only_distress_cases_are_fetched_never_non_distress_ones():
    """Two claimed cases, one Vegetation/Weeds (non-distress) and one Public Nuisance
    (distress): only the distress one's URL may be answered -- a fetch of the Vegetation one
    would KeyError against this response map, proving it was never asked."""
    row = _row([_case("CEVEG20262170", "Vegetation/Weeds", "Open", True),
               _case("CEPNU20253132", "Public Nuisance", "Abatement", True)])
    res = _check(row, resp={_URL_OPEN: _DETAIL_OPEN_ABATEMENT})
    assert res.verdict == "confirmed"
    assert [c["case_id"] for c in res.evidence["cases"]] == ["CEPNU20253132"]
