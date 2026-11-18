"""tax_lien_polk: Polk County NC's own per-record taxdetail.php?id=N page, re-fetched through
the sweep's Fetcher and parsed with polk_tax.py's own EXISTING, already-unit-tested
`_parse_detail_html` (unedited -- see that verifier module's own docstring).

The three real "not a real record" HTML captures and the real id=120/$879.25 unpaid-parcel
capture below are copied verbatim from tests/test_polk_tax_detail_enrichment.py's own
2026-10-13 live captures (same source of truth; not re-derived). The zero-balance,
small-balance and missing-Total-Due variants are SYNTHETIC: this codebase has never captured a
live Polk record that reads $0.00/"Paid" (every live sample seen so far was Unpaid), so they are
built by editing the one real capture's own Total Due cell only -- same shape, a different
dollar figure -- not a claim that the county's own "Paid" rendering has been seen live.
"""
from __future__ import annotations

import asyncio
import re

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import tax_lien_polk as V

_BASE = "https://cms.revize.com/revize/apps/polkcounty"


def _url(detail_id: str) -> str:
    return f"{_BASE}/taxdetail.php?id={detail_id}"


def run(coro):
    return asyncio.run(coro)


# --- real captures (verbatim from tests/test_polk_tax_detail_enrichment.py, 2026-10-13) ----

# id=120: real, live-captured unpaid real-estate parcel, $879.25 Total Due, Parcel Number P118-20.
_HTML_UNPAID_WITH_PARCEL = """
<div style="width:100%;">
    <table style="border: solid 2px #003A00; font-weight: bold; width: 300px;" cellpadding="3" cellspacing="0">
         <tbody>
              <tr>
                   <td>Status:</td>
                   <td>
                                                               Unpaid  <!-- Add CSS -->
                                                     </td>
              </tr>
              <tr>
                   <td>Total Due:</td>
                   <td>$879.25</td>
              </tr>
              <tr>
                   <td> Collection Status:</td>
                   <td>
                                         </td>
              </tr>
         </tbody>
    </table>
    <table style="border: 0; font-size: .9em; margin: 20px 0;" cellpadding="0" cellspacing="0">
         <tbody>
              <tr>
                   <td style="width: 33%;">
                        <table cellpadding="5" cellspacing="0">
                             <tbody>
                                  <tr>
                                       <td style="width: 140px;"> Owner Name: </td>
                                       <td>
                                           SKIPPER RONALD E / SKIPPER TERESA E                                       </td>
                                  </tr>
                                  <tr>
                                       <td style="width: 140px;">Owner ID:</td>
                                       <td>10172</td>
                                  </tr>
                                  <tr>
                                       <td>Tax Receipt Number:</td>
                                       <td>724192</td>
                                  </tr>
                                  <tr>
                                       <td>Bill Number:</td>
                                       <td>617163</td>
                                  </tr>
                                  <tr>
                                       <td>Parcel Number:</td>
                                       <td>P118-20</td>
                                  </tr>
                                  <tr>
                                      <td>Mailing Address:</td>
                                      <td>938 GREEN CREEK DR <br>COLUMBUS, NC 28722</td>
                                  <tr>
                                       <td>District:</td>
                                       <td>005</td>
                                  </tr>                  <tr>
                                  <tr>
                                       <td>Type:</td>
                                       <td>
                                           Property                                       </td>
                                  </tr>
                                  <tr>
                                       <td>Description:</td>
                                       <td>938 GREEN CREEK RD</td>
                                  </tr>
                             </tbody>
                        </table>
                   </td>
                   <td style="width: 33%;">
                        <table cellpadding="5" cellspacing="0">
                             <tbody>
                                  <tr>
                                       <td>Assessed Value:</td>
                                       <td>233981</td>
                                  </tr>
                                  <tr>
                                       <td>Base Amount:</td>
                                       <td>$879.25</td>
                                  </tr>
                                  <tr>
                                       <td>Charges:</td>
                                       <td>
                                       $0.00                                       </td>
                                  </tr>
                             </tbody></table>
                   </td>
        </tr>
    </tbody></table>
</div>
"""

# id=0, captured verbatim.
_HTML_NO_RECORD_REQUESTED = (
    '<b><font color="red"> No Tax Record was requested. Try Searching again '
    '!!! </font></b><form action="searchingtaxrecord.php" method="post">...</form>'
)

# a negative/non-numeric/nonexistent id, captured verbatim.
_HTML_SQL_LEAK = "select count(*) recordcount from tax_data where id=999999"

# id=5000, one of three live attempts (the other two 200'd on retry), trimmed real capture.
_HTML_CLOUDFLARE_CHALLENGE = (
    '<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>'
    '<meta http-equiv="content-security-policy" content="default-src \'none\'; '
    "script-src 'nonce-mQyTkGPizOmwJg2SWa2dn1' 'unsafe-eval' "
    'https://challenges.cloudflare.com"></head><body>'
    '<div class="main-wrapper" role="main"></div></body></html>'
)


def _with_total_due(html: str, new: str) -> str:
    """The real id=120 capture with its Total Due cell's dollar figure replaced -- same shape,
    a different amount (module docstring: synthetic, not a second live capture)."""
    out, n = re.subn(r"(Total Due:</td>\s*<td>)\$879\.25(</td>)", rf"\g<1>{new}\g<2>", html)
    assert n == 1, "fixture's Total Due cell shape changed; fix the regex above"
    return out


_HTML_PAID_ZERO = _with_total_due(_HTML_UNPAID_WITH_PARCEL, "$0.00")
_HTML_SMALL_BALANCE = _with_total_due(_HTML_UNPAID_WITH_PARCEL, "$12.50")
# simulate a real record with no readable Total Due at all (the label itself renamed, so
# _DETAIL_FIELD_RE["total_due"] cannot match it, while "owner name:" -- the parser's own
# real-record gate -- is still present)
_HTML_NO_TOTAL_DUE_FIELD = _HTML_UNPAID_WITH_PARCEL.replace("Total Due:", "Total Due Removed:")


def _row(*, state="NC", county="Polk", source=V.SOURCE_SLUG, detail_id="120",
         parcel_id=None, block_extra=None) -> dict:
    blk = {"detail_id": detail_id, "tax_year": "2026", "description": "938 GREEN CREEK RD",
          "type": "Property"}
    if block_extra:
        blk.update(block_extra)
    raw = {"polk_tax_search": blk} if detail_id is not None else {}
    return {"state": state, "county": county, "source": source, "parcel_id": parcel_id,
           "raw": raw}


def _auction_row() -> dict:
    """A Kania auction-page row: same source, but the OTHER block (raw.polk_tax), no detail_id
    at all -- the 64% this verifier's own module docstring declares out of scope."""
    return {"state": "NC", "county": "Polk", "source": V.SOURCE_SLUG, "parcel_id": "P65-38",
           "raw": {"polk_tax": {"parcel": "P65-38", "opening_bid": 500.0, "cancelled": False}}}


def _check(row: dict, responses: dict):
    return run(V.verify(row, ReplayFetcher(responses)))


# --------------------------------------------------------------------------- contract

def test_discovered_with_contract():
    vs = {v.name: v for v in registry.discover()}
    assert "tax_lien_polk" in vs, "tax_lien_polk.py must pass registry.from_module's contract"
    v = vs["tax_lien_polk"]
    assert (v.signal, v.ttl_days, v.retry_days) == ("tax_lien", 14, 7)
    assert v.governs == V.GOVERNS
    assert v.transient_reasons == ("fetch_failed",)


# --------------------------------------------------------------------------- applies()

def test_applies_true_for_polk_row_with_detail_id():
    assert V.applies(_row())


def test_applies_false_wrong_state_or_county():
    assert not V.applies(_row(state="SC"))
    assert not V.applies(_row(county="Rutherford"))


def test_applies_false_wrong_source():
    assert not V.applies(_row(source="counties_nc.polk_tax_auction_other"))


def test_applies_false_auction_row_with_no_detail_id():
    assert not V.applies(_auction_row())


def test_applies_false_non_numeric_detail_id():
    assert not V.applies(_row(detail_id="abc"))


def test_detail_id_of_matches_applies():
    assert V.detail_id_of(_row(detail_id="120")) == "120"
    assert V.detail_id_of(_auction_row()) is None


# --------------------------------------------------------------------------- verify(): confirmed

def test_confirmed_real_unpaid_record():
    row = _row(detail_id="120")
    r = _check(row, {_url("120"): _HTML_UNPAID_WITH_PARCEL})
    assert r.verdict == "confirmed"
    assert r.evidence["total_due"] == 879.25
    assert r.evidence["parcel_number"] == "P118-20"
    assert r.evidence["status"] == "Unpaid"
    assert r.evidence["balance_under_25"] is False
    assert r.evidence["url"] == _url("120")


def test_confirmed_small_balance_flagged_de_minimis():
    row = _row(detail_id="120")
    r = _check(row, {_url("120"): _HTML_SMALL_BALANCE})
    assert r.verdict == "confirmed"
    assert r.evidence["total_due"] == 12.50
    assert r.evidence["balance_under_25"] is True


def test_confirmed_binds_when_row_already_carries_the_same_parcel():
    row = _row(detail_id="120", parcel_id="P118-20")
    r = _check(row, {_url("120"): _HTML_UNPAID_WITH_PARCEL})
    assert r.verdict == "confirmed"


# --------------------------------------------------------------------------- verify(): stale

def test_stale_zero_balance():
    row = _row(detail_id="120")
    r = _check(row, {_url("120"): _HTML_PAID_ZERO})
    assert r.verdict == "stale"
    assert r.evidence["reason"] == "paid_since_snapshot"
    assert r.evidence["total_due"] == 0.0


# --------------------------------------------------------------------------- verify(): unconfirmed

def test_unconfirmed_no_detail_id_on_row():
    r = _check(_auction_row(), {})
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "no_detail_id"


def test_unconfirmed_no_record_requested_id_zero_shape():
    row = _row(detail_id="0")
    r = _check(row, {_url("0"): _HTML_NO_RECORD_REQUESTED})
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "record_not_found"


def test_unconfirmed_sql_leak_shape():
    row = _row(detail_id="999999")
    r = _check(row, {_url("999999"): _HTML_SQL_LEAK})
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "record_not_found"


def test_unconfirmed_cloudflare_challenge_shape():
    row = _row(detail_id="5000")
    r = _check(row, {_url("5000"): _HTML_CLOUDFLARE_CHALLENGE})
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "record_not_found"


def test_unconfirmed_fetch_failed_on_network_error():
    row = _row(detail_id="120")
    r = _check(row, {_url("120"): RuntimeError("connection reset")})
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "fetch_failed"


def test_unconfirmed_fetch_failed_on_missing_recording():
    """ReplayFetcher raises LookupError for a URL with no recording -- verify() must turn that
    into unconfirmed/fetch_failed like any other fetch failure, never propagate it."""
    row = _row(detail_id="120")
    r = _check(row, {})
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "fetch_failed"


def test_unconfirmed_id_mismatch_when_row_carries_a_different_parcel():
    row = _row(detail_id="120", parcel_id="Z999-99")
    r = _check(row, {_url("120"): _HTML_UNPAID_WITH_PARCEL})
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "id_mismatch"


def test_unconfirmed_no_amount_on_record():
    row = _row(detail_id="120")
    r = _check(row, {_url("120"): _HTML_NO_TOTAL_DUE_FIELD})
    assert r.verdict == "unconfirmed"
    assert r.evidence["reason"] == "no_amount_on_record"
    assert "total_due" not in r.evidence


# --------------------------------------------------------------------------- never refuted / public evidence

def test_never_refuted_and_evidence_is_whitelisted():
    cases = [
        (_row(detail_id="120"), {_url("120"): _HTML_UNPAID_WITH_PARCEL}),
        (_row(detail_id="120"), {_url("120"): _HTML_PAID_ZERO}),
        (_row(detail_id="0"), {_url("0"): _HTML_NO_RECORD_REQUESTED}),
        (_row(detail_id="120", parcel_id="Z999-99"), {_url("120"): _HTML_UNPAID_WITH_PARCEL}),
    ]
    for row, responses in cases:
        r = _check(row, responses)
        assert r.verdict != "refuted"
        assert set(r.evidence) <= set(V._KEYS)
        # the ledger is public: no owner/mailing/receipt/owner-id text anywhere in evidence
        blob = str(r.evidence)
        assert "SKIPPER" not in blob and "724192" not in blob and "10172" not in blob
