"""probate_heir (verification/verifiers/probate_heir_greenville.py): Greenville County SC probate
cases (appsas400 portal) re-queried by their own case number (fixture markup copied from a real
live fetch 2026-11-16, no network in this test).

What these pin:
  * registration: shares the `probate_heir` signal with probate_heir_scprobatenet.py/
    probate_heir_buncombe.py, scoped to counties_sc.greenville_probate rows only -- never a row
    of another producer;
  * applies(): source, a real case_number, record_kind == "probate" (this producer has no
    marriage branch at all, unlike sc_probate_net);
  * the live mechanism: a plain query-string GET to SearchDetails.aspx?CaseNumber=... (no
    VIEWSTATE/postback dance), reusing greenville_probate._parse_detail() itself rather than a
    re-implementation;
  * is_closed() agrees with greenville_probate.is_current()'s own inlined "closed_date present"
    rule;
  * verdicts: confirmed (found, no Closed Date), stale (found, Closed Date present), unconfirmed
    (not found again, or any fetch/parse problem) -- never refuted;
  * case_identity is case-shaped (IDENTITY = "case"): the same case + county always resolves to
    the same id regardless of which property a later enricher ties it to; no name, ever, in the
    published evidence.
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlencode

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import probate_heir_greenville as P
from foreclosure_scraper.scrapers.counties_sc.greenville_probate import DETAIL_URL

# Markup shape copied from a real live fetch of SearchDetails.aspx?CaseNumber=2020ES23016822
# (2026-11-16) -- the heading table, the real data table, and the "Parties Involved" heading
# table are all real `class="altDetailsTable"` elements on the live page; only the sample values
# are swapped out below.
_HEADING_TABLE = """<table class="altDetailsTable" style="width: 100%;">
<tr><th class="heading"><h2><span>Case Details ({case_number})</span></h2></th></tr>
</table>"""

_PARTIES_HEADING_TABLE = """<table class="altDetailsTable" style="width: 100%;">
<tr><th class="heading"><h2>Parties Involved&nbsp;(<span>{n}</span>)</h2></th></tr>
</table>"""


def _found_html(case_number: str, status: str, closed_date: str = "",
                decedent: str = "SAMPLE, ALPHA", pr_name: str = "SAMPLE, REP") -> str:
    parties_rows = ""
    n = 0
    if pr_name:
        n = 1
        parties_rows = f"""
<table cellspacing="0" cellpadding="3" class="altDetailsTable">
<tr><th>Name:</th><td>{pr_name}</td></tr>
<tr><th>Party Type:</th><td>Personal Representative</td></tr>
<tr><th>Address:</th><td>PO BOX 1 ANYTOWN SC 29601</td></tr>
</table>"""
    return f"""<html><body>
{_HEADING_TABLE.format(case_number=case_number)}
<table cellspacing="0" cellpadding="3" class="altDetailsTable">
<tr><th>Name:</th><td>{decedent}</td></tr>
<tr><th>Party Type:</th><td>Deceased Person</td></tr>
<tr><th>Address:</th><td>123 SAMPLE RD ANYTOWN SC 29601</td></tr>
<tr><th>Date of Death:</th><td>7/20/2020</td></tr>
<tr><th>Status:</th><td>{status}</td></tr>
<tr><th>Case Type:</th><td>Estate</td></tr>
<tr><th>File Date:</th><td>12/5/2025</td></tr>
<tr><th>Closed Date:</th><td>{closed_date}</td></tr>
</table>
{_PARTIES_HEADING_TABLE.format(n=n)}
{parties_rows}
</body></html>"""


def _not_found_html(case_number: str) -> str:
    # The exact real "no record" shape (live-confirmed 2026-11-16): the heading table still
    # echoes the case number back, the data table between it and the Parties heading is
    # completely empty (zero <tr> rows), and Parties Involved shows 0.
    return f"""<html><body>
{_HEADING_TABLE.format(case_number=case_number)}
<table cellspacing="0" cellpadding="3" class="altDetailsTable">
</table>
{_PARTIES_HEADING_TABLE.format(n="")}
</body></html>"""


def _row(**kw) -> dict:
    row = {"state": "SC", "county": "Greenville", "source": P.GREENVILLE_PROBATE_SOURCE,
           "case_number": "2020ES23016822", "owner_name": "SAMPLE, ALPHA",
           "raw": {"greenville_probate": {"record_kind": "probate", "decedent": "SAMPLE, ALPHA",
                                          "status": "Subsequent Admin"}}}
    raw = kw.pop("raw", None)
    row.update(kw)
    if raw:
        row["raw"].update(raw)
    return row


def _url(case_number: str) -> str:
    return f"{DETAIL_URL}?{urlencode({'CaseNumber': case_number})}"


def _run(row, responses):
    return asyncio.run(P.verify(row, ReplayFetcher(responses)))


def test_registered_and_scoped():
    reg = {x.name: x for x in registry.discover()}
    v = reg["probate_heir_greenville"]
    assert v.signal == "probate_heir" and v.ttl_days == 30
    assert v.governs == ("probate_notice",)
    assert v.identity == "case"
    # shares the signal with the sibling SC probate modules, disjoint applies()
    sib = reg["probate_heir_scprobatenet"]
    assert sib.signal == v.signal and sib.name != v.name

    assert P.applies(_row())
    assert not P.applies(_row(source="counties_sc.sc_public_notices"))   # a different producer
    assert not P.applies(_row(case_number=""))
    assert not P.applies(_row(raw={"greenville_probate": {"record_kind": None}}))
    assert not P.applies(_row(raw={"greenville_probate": {}}))            # record_kind missing
    # this producer has no marriage branch at all -- only "probate" is ever a valid record_kind
    assert not P.applies(_row(raw={"greenville_probate": {"record_kind": "marriage"}}))


def test_is_closed_matches_the_producers_own_rule():
    assert P.is_closed({"closed_date": "8/10/2026"})
    assert P.is_closed({"closed_date": "  8/10/2026  "})
    assert not P.is_closed({"closed_date": ""})
    assert not P.is_closed({"closed_date": None})
    assert not P.is_closed({})


def test_case_identity_is_case_shaped_never_a_name():
    a = P.case_identity(_row())
    b = P.case_identity(_row(owner_name="A TOTALLY DIFFERENT NAME"))
    assert a == b                                   # same case+county -> same identity
    c = P.case_identity(_row(case_number="2020ES23099999"))
    assert c != a                                   # a different case number -> a different id
    d = P.case_identity(_row(county="Spartanburg"))
    assert d != a                                   # a different county -> a different id (never guessed)


def test_open_case_found_again_is_confirmed():
    case_number = "2020ES23016822"
    responses = {_url(case_number): _found_html(case_number, "Subsequent Admin", closed_date="")}
    r = _run(_row(case_number=case_number), responses)
    assert r.verdict == "confirmed" and r.evidence["reason"] == "case_open"
    assert r.evidence["status_today"] == "Subsequent Admin"
    assert "SAMPLE" not in str(r.evidence)           # no decedent name ever published


def test_closed_case_is_stale():
    case_number = "2020ES23016822"
    responses = {_url(case_number): _found_html(case_number, "Subsequent Admin",
                                                 closed_date="8/10/2026")}
    r = _run(_row(case_number=case_number), responses)
    assert r.verdict == "stale" and r.evidence["reason"] == "case_closed"
    assert r.evidence["closed_date_today"] == "8/10/2026"


def test_case_not_found_again_is_unconfirmed_never_refuted():
    case_number = "2020ES23016822"
    responses = {_url(case_number): _not_found_html(case_number)}
    r = _run(_row(case_number=case_number), responses)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "case_not_found_again"


def test_fabricated_case_number_real_not_found_shape():
    """The exact byte-for-byte real page shape a made-up case number returns, live-confirmed
    2026-11-16 (ZZZFAKE999999): an empty data table, Parties Involved (0) -- never an error
    page, never a different HTTP status."""
    case_number = "ZZZFAKE999999"
    responses = {_url(case_number): _not_found_html(case_number)}
    r = _run(_row(case_number=case_number), responses)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "case_not_found_again"


def test_fetch_failure_is_unconfirmed_and_transient():
    r = _run(_row(), {})   # ReplayFetcher with no recordings at all -> LookupError on the GET
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "fetch_failed"
    assert "fetch_failed" in P.TRANSIENT_REASONS


def test_http_error_status_is_fetch_failed_not_case_not_found():
    # ReplayFetcher.get_text() (unlike form_session()'s FormResponse) has no status concept of
    # its own -- it serves exactly what http_client.get_text would surface for a real 4xx/5xx:
    # an exception out of the GET itself (raise_for_status under the hood), recorded here as a
    # BaseException value per ReplayFetcher's own contract.
    case_number = "2020ES23016822"
    r = _run(_row(case_number=case_number),
            {_url(case_number): RuntimeError("http_503_service_unavailable")})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "fetch_failed"


def test_no_case_number_is_unconfirmed():
    row = _row()
    row["case_number"] = ""
    r = _run(row, {})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "no_case_number"


def test_second_real_case_number_roundtrip_shape():
    """A second real, live-sourced case number (not just the first), confirming the parse/verdict
    logic generalizes -- made-up status/closed_date, real case-number shape."""
    case_number = "2026ES2300708"
    responses = {_url(case_number): _found_html(case_number, "Will Filed w/ 306ES",
                                                 closed_date="5/5/2026", decedent="SAMPLE, BETA")}
    r = _run(_row(case_number=case_number), responses)
    assert r.verdict == "stale" and r.evidence["status_today"] == "Will Filed w/ 306ES"
