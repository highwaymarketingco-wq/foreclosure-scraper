"""qPayBill roll: Dillon + Edgefield, the 2 real hits from the 2026-09-23
tax-delinquent gap probe (docs/coverage_gap_build_plan_2026-09-23.md item 6).

docs/completeness_audit_2026-09-23.md section 3 lists 17 SC counties missing the
"tax delinquent" family. Of those, 11 were already in QPAYBILL_SUBS (Abbeville,
Allendale, Barnwell, Calhoun, Chesterfield, Darlington, Lee, Marlboro, McCormick,
Williamsburg, Bamberg) and 2 more (Chester, Fairfield) are covered by the sibling
counties_sc.sc_catalis_delinquent_roll instead. That left 4 genuinely unprobed
counties: Dillon, Dorchester, Edgefield, Greenwood.

LIVE-PROBED 2026-09-23, real network calls against the production endpoints (not
guessed subdomains) -- 2 confirmed hits, 2 confirmed/inconclusive non-hits:

  * Dillon (HIT) -- dilloncountysc.org/departments/treasurer.php links "Online
    Tax Payment Center" directly to
    https://dilloncountysctaxes.qpaybill.com/Taxes/TaxesDefaultType4.aspx#/ .
    GET returned a real __VIEWSTATE-bearing Type4 search form (200, 19,092
    bytes). A live search for prefix "A" returned 23 rows through this
    module's own parse_grid(), including a real multi-year delinquency:
    ABRAHAM HARRY W, ident 138-00-00-047.001, $173.81 unpaid for tax YEAR 2018
    (not merely the current year) -- exactly the two-year-plus signal this
    source exists to surface. Subdomain: "dilloncountysctaxes".

  * Edgefield (HIT) -- edgefieldcounty.sc.gov's own site links an "Online Tax
    Payment Center" at https://edgefieldcountysc.qpaybill.com/ . Same Type4
    form fields present (SearchType/PaidStatus/ddlCriteriaList/ddlYearList/
    txtCriteriaBox/btnSearch, verified by field-name grep on the live page).
    A live search for prefix "A" returned 25 rows via parse_grid(), e.g.
    ABNEY ANNIE T, ident 185-00-01-031-000, $134.02 unpaid 2025. Subdomain:
    "edgefieldcountysc".

  * Dorchester (INCONCLUSIVE, NOT added) -- dorchestercountytaxesonline.com
    embeds a CloudFront/Catalis data GUID (7ab11840-7835-4c82-be08-
    02583566acb3) in its own <link rel="stylesheet" href="https://
    d1ebsyxxbc7tep.cloudfront.net/css/<GUID>/1.css"> tag, the SAME reuse
    pattern that identifies Pickens' known-good GUID
    (c9ab58ea-c187-4c02-ad9d-b18dd6167431) the same way on pickenscountysctax.us.
    But every live POST to that CloudFront distribution's /data/<GUID>/Records
    -- including a control request using PICKENS' OWN already-confirmed-good
    GUID -- came back HTTP 403 "Request blocked" from CloudFront itself during
    this probe, so the block is an infrastructure-side condition of the whole
    distribution from this network path, not evidence Dorchester specifically
    lacks data. Per sc_catalis_delinquent_roll.py's own documented policy
    ("A 403 stops the sweep... never retry or route around it"), this is
    reported as a genuine non-hit for THIS probe rather than wired
    speculatively; a re-probe from a different network path is a legitimate
    follow-up, not a rebuild.

  * Greenwood (CONFIRMED MISS, wrong vendor) -- see qpaybill_delinquent_roll.py's
    own 2026-09-23 docstring note: its tax system is entirely on corebtpay.com
    (Core's egov.com platform), not qPayBill or Catalis.

Both hits were verified with this module's actual parse_grid() against the real
live HTML (not a hand-built fixture) -- see test_dillon_prefix_a_parses_via_
parse_grid / test_edgefield_prefix_a_parses_via_parse_grid below, which embed a
verbatim single <tr> row captured from each county's live response
(dillon_results_A.html / edgefield_results_A.html, prefix "A", 2026-09-23) so the
suite stays deterministic (no live network call in the test itself) while still
proving the real markup shape parses.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import (
    QPAYBILL_SUBS,
    ACCOUNT_ID_ONLY,
    parse_grid,
)

# Real <tr> markup, verbatim, from a live prefix="A" search against
# dilloncountysctaxes.qpaybill.com/Taxes/TaxesDefaultType4.aspx, 2026-09-23.
_DILLON_ROW_A_HTML = (
    "<tr>"
    "<td>000010183</td><td>ABRAHAM HARRY W</td><td>2018</td>"
    "<td>78 PARKWAY       ...</td><td>138-00-00-047.001</td>"
    "<td>RealEstate</td><td>Unpaid</td><td>        </td><td>$173.81</td>"
    '<td><a class="btn btn-primary" '
    'href="TaxesDetailsType4.aspx?receiptNo=000010183&amp;recID=585228421">View</a></td>'
    "<td>"
    '<input type="submit" name="ctl00$MainContent$gvSearchResults$ctl02$AddButton" '
    'value="Add to Cart" id="ctl00_MainContent_gvSearchResults_ctl02_AddButton" '
    'class="btn btn-primary" />'
    "</td>"
    "</tr>"
)

# Real <tr> markup, verbatim, from a live prefix="A" search against
# edgefieldcountysc.qpaybill.com/Taxes/TaxesDefaultType4.aspx, 2026-09-23.
_EDGEFIELD_ROW_A_HTML = (
    "<tr>"
    "<td>000026253</td><td>ABNEY ANNIE T</td><td>2025</td>"
    "<td>E OF THURMOND ST ...</td><td>185-00-01-031-000</td>"
    "<td>RealEstate</td><td>Unpaid</td><td>        </td><td>$134.02</td>"
    '<td><a class="btn btn-primary" '
    'href="TaxesDetailsType4.aspx?receiptNo=000026253&amp;recID=584396061">View</a></td>'
    "<td></td>"
    "</tr>"
)


def test_dillon_and_edgefield_are_in_qpaybill_subs():
    assert QPAYBILL_SUBS.get("Dillon") == "dilloncountysctaxes"
    assert QPAYBILL_SUBS.get("Edgefield") == "edgefieldcountysc"


def test_dillon_and_edgefield_are_not_account_id_only():
    # Both counties' ident column is a real dashed TMS/parcel number (verified
    # live: "138-00-00-047.001", "185-00-01-031-000"), unlike Orangeburg's
    # bare account id -- so they must not be added to ACCOUNT_ID_ONLY.
    assert "Dillon" not in ACCOUNT_ID_ONLY
    assert "Edgefield" not in ACCOUNT_ID_ONLY


def test_dillon_prefix_a_parses_via_parse_grid():
    rows = parse_grid(_DILLON_ROW_A_HTML)
    assert len(rows) == 1
    r = rows[0]
    assert r["owner"] == "ABRAHAM HARRY W"
    assert r["ident"] == "138-00-00-047.001"
    assert r["year"] == "2018"
    assert r["amount"] == 173.81
    assert r["status"] == "Unpaid"
    assert r["detail_href"] == "TaxesDetailsType4.aspx?receiptNo=000010183&recID=585228421"


def test_edgefield_prefix_a_parses_via_parse_grid():
    rows = parse_grid(_EDGEFIELD_ROW_A_HTML)
    assert len(rows) == 1
    r = rows[0]
    assert r["owner"] == "ABNEY ANNIE T"
    assert r["ident"] == "185-00-01-031-000"
    assert r["year"] == "2025"
    assert r["amount"] == 134.02
    assert r["status"] == "Unpaid"


def test_dorchester_and_greenwood_deliberately_absent():
    # See this file's module docstring: Dorchester is inconclusive (CloudFront
    # 403-blocked this probe even against a known-good control GUID) and
    # Greenwood is a confirmed miss (corebtpay.com, a different vendor).
    # Neither should be guessed into QPAYBILL_SUBS without a genuine live hit.
    assert "Dorchester" not in QPAYBILL_SUBS
    assert "Greenwood" not in QPAYBILL_SUBS
