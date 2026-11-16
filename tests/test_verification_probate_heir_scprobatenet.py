"""probate_heir (verification/verifiers/probate_heir_scprobatenet.py): southcarolinaprobate.net
cases/licenses re-queried by their own case/license number (made-up fixtures, no network).

What these pin:
  * registration: shares the `probate_heir` signal with probate_heir_buncombe.py, scoped to
    counties_sc.sc_probate_net rows only -- never a Buncombe row, never a row of another SC
    probate producer (sc_public_notices, column_legal_notices, ...);
  * applies(): source, a real case_number, a record_kind sc_probate_net.COUNTIES actually has a
    dropdown for (probate everywhere in COUNTIES; marriage only where a Marriage variant exists);
  * the live ASP.NET postback shape: the county-select form, then the case-number-search form
    (tbCaseNumber filled, every name field left blank) -- built from whatever hidden fields the
    PRIOR response actually carried, not duplicated by hand;
  * verdicts: confirmed (found, not Closed / a license found at all), stale (found, Closed),
    unconfirmed (not found again, or any fetch/session failure) -- never refuted;
  * is_closed() agrees with sc_probate_net.is_current()'s own "starts with closed" rule;
  * case_identity is case-shaped (IDENTITY = "case"): the same case/license + county always
    resolves to the same id regardless of which property a later enricher ties it to; two
    different case numbers never collide; no name, ever, in the published evidence.
  * marriage records parse off the cgvMarriage grid under the Marriage dropdown, never cgvCases.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher, form_key
from foreclosure_scraper.verification.verifiers import probate_heir_scprobatenet as P
from foreclosure_scraper.scrapers.counties_sc.sc_probate_net import BASE_URL, PRE, _hidden_fields

SEARCH_HTML = """<html><body><form>
<input type="hidden" name="__VIEWSTATE" value="VS1" />
<input type="hidden" name="__EVENTVALIDATION" value="EV1" />
</form></body></html>"""

COUNTY_SELECTED_HTML = """<html><body><form>
<input type="hidden" name="__VIEWSTATE" value="VS2" />
<input type="hidden" name="__EVENTVALIDATION" value="EV2" />
</form></body></html>"""

NO_RECORDS_HTML = """<html><body>
<table id="ctl00_ContentPlaceHolder1_cgvCases"><tr><td>No records matching your criteria were found.</td></tr></table>
</body></html>"""

NO_RECORDS_MARRIAGE_HTML = """<html><body>
<table id="ctl00_ContentPlaceHolder1_cgvMarriage"><tr><td>No records matching your criteria were found.</td></tr></table>
</body></html>"""


def _probate_grid(case_number: str, status: str, decedent: str = "SAMPLE ALPHA") -> str:
    return f"""<html><body>
<table id="ctl00_ContentPlaceHolder1_cgvCases">
<tr><th>Expand</th><th>Case#</th><th>Case Name</th><th>Party</th><th>Type</th>
    <th>Filing Date</th><th>County</th><th>Appt Date</th><th>Status</th></tr>
<tr><td></td><td>{case_number}</td><td>{decedent}</td><td>SAMPLE REP</td><td>Estate</td>
    <td>01/02/2020</td><td>Charleston</td><td>02/03/2020</td><td>{status}</td></tr>
</table>
</body></html>"""


def _marriage_grid(license_number: str, couple: str = "SAMPLE ONE/SAMPLE TWO") -> str:
    return f"""<html><body>
<table id="ctl00_ContentPlaceHolder1_cgvMarriage">
<tr><th>Expand</th><th>License#</th><th>Names</th><th>Appl Date</th><th>Marriage Date</th></tr>
<tr><td></td><td>{license_number}</td><td>{couple}</td><td>01/05/2019</td><td>01/20/2019</td></tr>
</table>
</body></html>"""


def _row(**kw) -> dict:
    row = {"state": "SC", "county": "Charleston", "source": P.SC_PROBATE_NET_SOURCE,
           "case_number": "2019ES1001293", "owner_name": "SAMPLE ALPHA",
           "raw": {"sc_probate_net": {"record_kind": "probate", "decedent": "SAMPLE ALPHA",
                                      "status": "Opened"}}}
    raw = kw.pop("raw", None)
    row.update(kw)
    if raw:
        row["raw"].update(raw)
    return row


def _responses(dropdown_value: str, case_number: str, result_html: str,
               search_page: str = SEARCH_HTML, county_page: str = COUNTY_SELECTED_HTML) -> dict:
    """The exact {url|form_key: body} map ReplayFetcher needs for one full 2-postback round
    trip, built the SAME way the module itself builds each step's form body -- never a
    hand-copied duplicate of that logic."""
    county_form = P._county_select_form(_hidden_fields(search_page), dropdown_value)
    search_form = P._case_number_search_form(_hidden_fields(county_page), dropdown_value, case_number)
    return {
        BASE_URL: search_page,
        form_key(BASE_URL, county_form): county_page,
        form_key(BASE_URL, search_form): result_html,
    }


def _run(row, responses):
    return asyncio.run(P.verify(row, ReplayFetcher(responses)))


def test_registered_and_scoped():
    reg = {x.name: x for x in registry.discover()}
    v = reg["probate_heir_scprobatenet"]
    assert v.signal == "probate_heir" and v.ttl_days == 30
    assert v.governs == ("probate_notice",)
    assert v.identity == "case"
    # shares the signal with the Buncombe module, disjoint applies()
    buncombe = reg["probate_heir_buncombe"]
    assert buncombe.signal == v.signal and buncombe.name != v.name

    assert P.applies(_row())
    assert not P.applies(_row(source="counties_sc.sc_public_notices"))   # a different producer
    assert not P.applies(_row(case_number=""))
    assert not P.applies(_row(raw={"sc_probate_net": {"record_kind": None}}))
    assert not P.applies(_row(raw={"sc_probate_net": {}}))               # record_kind missing
    # marriage applies only where COUNTIES actually has a Marriage dropdown entry
    assert P.applies(_row(county="York", case_number="2025000001",
                          raw={"sc_probate_net": {"record_kind": "marriage"}}))
    assert not P.applies(_row(county="Colleton", case_number="2025000001",
                              raw={"sc_probate_net": {"record_kind": "marriage"}}))
    assert P.applies(_row(county="Colleton", raw={"sc_probate_net": {"record_kind": "probate"}}))


def test_is_closed_matches_the_producers_own_rule():
    assert P.is_closed("Closed")
    assert P.is_closed("  closed - final  ".strip())
    assert P.is_closed("CLOSED")
    assert not P.is_closed("Opened")
    assert not P.is_closed("RE Reopen")
    assert not P.is_closed(None)
    assert not P.is_closed("")


def test_case_identity_is_case_shaped_never_a_name():
    a = P.case_identity(_row())
    b = P.case_identity(_row(owner_name="A TOTALLY DIFFERENT NAME", county="Charleston"))
    assert a == b                                   # same case+county -> same identity
    c = P.case_identity(_row(case_number="2019ES1099999"))
    assert c != a                                   # a different case number -> a different id
    assert P.case_identity(_row(raw={"sc_probate_net": {"record_kind": "marriage"}})) != a


def test_open_case_found_again_is_confirmed():
    responses = _responses("Charleston Probate", "2019ES1001293",
                           _probate_grid("2019ES1001293", "Opened"))
    r = _run(_row(), responses)
    assert r.verdict == "confirmed" and r.evidence["reason"] == "case_open"
    assert r.evidence["status_today"] == "Opened"
    assert "SAMPLE" not in str(r.evidence)


def test_closed_case_is_stale():
    responses = _responses("Charleston Probate", "2019ES1001293",
                           _probate_grid("2019ES1001293", "Closed"))
    r = _run(_row(), responses)
    assert r.verdict == "stale" and r.evidence["reason"] == "case_closed"


def test_case_not_found_again_is_unconfirmed_never_refuted():
    responses = _responses("Charleston Probate", "2019ES1001293", NO_RECORDS_HTML)
    r = _run(_row(), responses)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "case_not_found_again"


def test_wrong_county_dropdown_would_also_read_as_not_found():
    # a sanity companion to the live cross-county probe this module's docstring cites: the SAME
    # "no records matching" shape is what a mismatched dropdown returns, and this module never
    # treats it as anything stronger than unconfirmed.
    responses = _responses("Dorchester Probate", "2019ES1001293", NO_RECORDS_HTML)
    r = _run(_row(county="Dorchester"), responses)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "case_not_found_again"


def test_marriage_license_found_again_is_confirmed_no_status_concept():
    row = _row(case_number="2019004337",
              raw={"sc_probate_net": {"record_kind": "marriage"}})
    responses = _responses("Charleston Marriage", "2019004337",
                           _marriage_grid("2019004337"))
    r = _run(row, responses)
    assert r.verdict == "confirmed" and r.evidence["reason"] == "license_found_again"
    assert "status_today" not in r.evidence


def test_marriage_license_not_found_again_is_unconfirmed():
    row = _row(case_number="2019004337",
              raw={"sc_probate_net": {"record_kind": "marriage"}})
    responses = _responses("Charleston Marriage", "2019004337", NO_RECORDS_MARRIAGE_HTML)
    r = _run(row, responses)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "case_not_found_again"


def test_fetch_failure_is_unconfirmed_and_transient():
    r = _run(_row(), {})   # ReplayFetcher with no recordings at all -> LookupError on the GET
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "fetch_failed"
    assert "fetch_failed" in P.TRANSIENT_REASONS


def test_http_error_status_is_fetch_failed_not_case_not_found():
    r = _run(_row(), {BASE_URL: {"status": 503, "url": BASE_URL, "text": "Service Unavailable"}})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "fetch_failed"


def test_york_probate_real_case_number_roundtrip_shape():
    """A second real county/dropdown pair (not just Charleston), confirming the dropdown
    resolution and form-building generalize -- live-sourced case number, made-up status."""
    row = _row(county="York", case_number="2025ES4601611")
    responses = _responses("York Probate", "2025ES4601611",
                           _probate_grid("2025ES4601611", "RE Reopen", decedent="SAMPLE BETA"))
    r = _run(row, responses)
    assert r.verdict == "confirmed" and r.evidence["status_today"] == "RE Reopen"
