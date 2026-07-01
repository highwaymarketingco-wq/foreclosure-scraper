"""Unit tests for scripts/parse_nc_ecourts_export.py.

Proves the saved-HTML parser extracts case_number, party names
(plaintiff/defendant), case_type, filing_date, and county from representative
Tyler / Odyssey Portal markup — both a case-detail card layout and a tabular
result-grid layout — and that the dict->Listing adapter carries the right
fields for the name->property resolver. Odyssey markup varies, so the fixtures
use two distinct realistic shapes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

# The parser lives under scripts/ (not an installed package), so load it by path.
_MOD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "parse_nc_ecourts_export.py"
_spec = importlib.util.spec_from_file_location("parse_nc_ecourts_export", _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(mod)


# --------------------------------------------------------------------------- #
# Fixture A — Odyssey "case detail" card layout: label/value pairs in divs.
# --------------------------------------------------------------------------- #
DETAIL_HTML = """
<html><body>
<div class="portal-search-results">
  <div class="caseCard">
    <div class="row"><label class="fieldName">Case Number</label>
        <span class="fieldValue">24CVD001234-590</span></div>
    <div class="row"><label class="fieldName">Case Type</label>
        <span class="fieldValue">Absolute Divorce</span></div>
    <div class="row"><label class="fieldName">File Date</label>
        <span class="fieldValue">03/14/2026</span></div>
    <div class="row"><label class="fieldName">Location</label>
        <span class="fieldValue">Buncombe County District Court</span></div>
    <div class="row"><label class="fieldName">Plaintiff</label>
        <span class="fieldValue">BRANDI CALDWELL</span></div>
    <div class="row"><label class="fieldName">Defendant</label>
        <span class="fieldValue">JEREMIAH CALDWELL</span></div>
  </div>
  <div class="caseCard">
    <div class="row"><label class="fieldName">Case Number</label>
        <span class="fieldValue">25SP000078-100</span></div>
    <div class="row"><label class="fieldName">Case Type</label>
        <span class="fieldValue">Estate</span></div>
    <div class="row"><label class="fieldName">File Date</label>
        <span class="fieldValue">01/07/2026</span></div>
    <div class="row"><label class="fieldName">Location</label>
        <span class="fieldValue">Henderson County</span></div>
    <div class="row"><label class="fieldName">Defendant</label>
        <span class="fieldValue">MARGARET P WHITMIRE</span></div>
    <div class="row"><label class="fieldName">Plaintiff</label>
        <span class="fieldValue">WELLS FARGO BANK NA</span></div>
  </div>
</div>
</body></html>
"""


# --------------------------------------------------------------------------- #
# Fixture B — Odyssey "result grid" layout: an HTML table with a thead.
# --------------------------------------------------------------------------- #
TABLE_HTML = """
<html><body>
<table class="k-grid-table">
  <thead><tr>
    <th>Case Number</th><th>Style / Parties</th>
    <th>Case Type</th><th>File Date</th><th>County</th>
  </tr></thead>
  <tbody>
    <tr>
      <td>2024 CVS 000456</td><td>ACME BANK vs ROBERT E LEE</td>
      <td>Foreclosure</td><td>11/02/2026</td><td>Rutherford</td>
    </tr>
    <tr>
      <td>24CVD002211</td><td>DANA HOLLIFIELD vs MARK HOLLIFIELD</td>
      <td>Child Custody</td><td>05/19/2026</td><td>Cleveland</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


def test_detail_card_extraction():
    recs = mod.parse_nc_ecourts_html(DETAIL_HTML)
    assert len(recs) == 2
    by_case = {r["case_number"]: r for r in recs}

    div = by_case["24CVD001234-590"]
    assert div["case_type"] == "Absolute Divorce"
    assert div["filing_date"] == "03/14/2026"
    assert div["county"] == "Buncombe"  # court suffix stripped
    assert div["plaintiff"] == "BRANDI CALDWELL"
    assert div["defendant"] == "JEREMIAH CALDWELL"
    assert "JEREMIAH CALDWELL" in div["party_names"]

    est = by_case["25SP000078-100"]
    assert est["county"] == "Henderson"
    assert est["defendant"] == "MARGARET P WHITMIRE"
    # The bank plaintiff is an entity -> excluded from resolvable party_names,
    # but the human defendant is kept.
    assert "MARGARET P WHITMIRE" in est["party_names"]
    assert all("WELLS FARGO" not in n for n in est["party_names"])


def test_result_table_extraction():
    recs = mod.parse_nc_ecourts_html(TABLE_HTML)
    assert len(recs) == 2
    by_case = {r["case_number"]: r for r in recs}

    fc = by_case["2024 CVS 000456"]
    assert fc["case_type"] == "Foreclosure"
    assert fc["filing_date"] == "11/02/2026"
    assert fc["county"] == "Rutherford"
    # style "ACME BANK vs ROBERT E LEE" -> plaintiff/defendant split
    assert fc["plaintiff"] == "ACME BANK"
    assert fc["defendant"] == "ROBERT E LEE"
    # entity plaintiff dropped from resolvable party_names, person kept
    assert fc["party_names"] == ["ROBERT E LEE"]

    cc = by_case["24CVD002211"]
    assert cc["county"] == "Cleveland"
    assert cc["defendant"] == "MARK HOLLIFIELD"
    assert set(cc["party_names"]) == {"DANA HOLLIFIELD", "MARK HOLLIFIELD"}


def test_default_county_and_case_type_stamped():
    html = """
    <table><thead><tr><th>Case Number</th><th>Parties</th></tr></thead>
    <tbody><tr><td>24CVD009999</td><td>JOHN A DOE vs JANE B DOE</td></tr></tbody>
    </table>"""
    recs = mod.parse_nc_ecourts_html(html, default_county="Gaston",
                                     default_case_type="Divorce")
    assert len(recs) == 1
    assert recs[0]["county"] == "Gaston"
    assert recs[0]["case_type"] == "Divorce"


def test_text_fallback_when_no_structure():
    # A saved page with no tables/cards — just visible lines. Parser should still
    # recover case# + parties from the raw text sweep.
    html = """<html><body><pre>
    24CVD004242  SARAH LOWE vs DERRICK LOWE  06/01/2026
    (not a case line, should be ignored)
    </pre></body></html>"""
    recs = mod.parse_nc_ecourts_html(html)
    assert len(recs) == 1
    assert recs[0]["case_number"] == "24CVD004242"
    assert set(recs[0]["party_names"]) == {"SARAH LOWE", "DERRICK LOWE"}


def test_estate_single_party_caption():
    # Estate rows have no "vs" — the caption is "In re: Estate of <decedent>".
    # The decedent must still be recovered as the resolvable party.
    html = """
    <table><thead><tr><th>Case Number</th><th>Style</th>
      <th>Case Type</th><th>County</th></tr></thead>
    <tbody>
      <tr><td>25SP000078</td><td>IN RE ESTATE OF MARGARET P WHITMIRE</td>
          <td>Estate</td><td>Henderson</td></tr>
      <tr><td>25E000512</td><td>ROY LEE ADAMS, Deceased</td>
          <td>Estate</td><td>Buncombe</td></tr>
    </tbody></table>"""
    recs = mod.parse_nc_ecourts_html(html)
    assert len(recs) == 2
    by_case = {r["case_number"]: r for r in recs}
    assert by_case["25SP000078"]["party_names"] == ["MARGARET P WHITMIRE"]
    assert by_case["25SP000078"]["defendant"] == "MARGARET P WHITMIRE"
    assert by_case["25E000512"]["party_names"] == ["ROY LEE ADAMS"]


def test_estate_matter_of_caption_stripped():
    # The most common real NC estate / special-proceeding wording nests the
    # decedent under "IN THE MATTER OF THE ESTATE OF ..." — the resolver needs
    # the bare person name, not the whole caption.
    html = """
    <table><thead><tr><th>Case Number</th><th>Style</th>
      <th>Case Type</th><th>County</th></tr></thead>
    <tbody>
      <tr><td>25SP000411</td><td>IN THE MATTER OF THE ESTATE OF HAROLD JENKINS</td>
          <td>Special Proceeding</td><td>Cleveland</td></tr>
      <tr><td>25SP000412</td><td>IN THE MATTER OF THE GUARDIANSHIP OF EDNA MAE POOLE</td>
          <td>Special Proceeding</td><td>Gaston</td></tr>
    </tbody></table>"""
    by_case = {r["case_number"]: r for r in mod.parse_nc_ecourts_html(html)}
    assert by_case["25SP000411"]["defendant"] == "HAROLD JENKINS"
    assert by_case["25SP000412"]["defendant"] == "EDNA MAE POOLE"


def test_estate_prefix_regex_directly():
    strip = lambda s: mod._ESTATE_PREFIX_RE.sub(" ", s).strip()
    assert strip("IN THE MATTER OF THE ESTATE OF HAROLD JENKINS") == "HAROLD JENKINS"
    assert strip("IN RE: ESTATE OF MARGARET P WHITMIRE") == "MARGARET P WHITMIRE"
    assert strip("ESTATE OF ROY LEE ADAMS") == "ROY LEE ADAMS"
    assert strip("IN THE MATTER OF THE GUARDIANSHIP OF EDNA MAE POOLE") == "EDNA MAE POOLE"


def test_source_url_encodes_case_number():
    # A caseNumber with spaces ("2024 CVS 000456") must be percent-encoded so the
    # portal deep-link is a valid URL, not one with raw spaces.
    li = mod.record_to_listing_dict({"defendant": "JANE DOE", "county": "Rutherford",
                                     "case_number": "2024 CVS 000456"})
    assert " " not in li["source_url"]
    assert "caseNumber=2024%20CVS%20000456" in li["source_url"]


def test_empty_input_returns_empty():
    assert mod.parse_nc_ecourts_html("") == []
    assert mod.parse_nc_ecourts_html("   ") == []


def test_dedup_identical_cases():
    doubled = DETAIL_HTML.replace("</div>\n</body>", "</div>\n</body>")  # no-op guard
    # Concatenate the same two cards twice -> should still dedup to 2.
    two = DETAIL_HTML + DETAIL_HTML
    recs = mod.parse_nc_ecourts_html(two)
    assert len(recs) == 2


def test_record_to_listing_adapter():
    recs = mod.parse_nc_ecourts_html(TABLE_HTML)
    fc = next(r for r in recs if r["case_number"] == "2024 CVS 000456")
    li = mod.record_to_listing_dict(fc)
    assert li is not None
    # resolver reads owner_name / defendant / county / listing_type
    assert li["owner_name"] == "ROBERT E LEE"
    assert li["defendant"] == "ROBERT E LEE"
    assert li["plaintiff"] == "ACME BANK"
    assert li["county"] == "Rutherford"
    assert li["state"] == "NC"
    assert li["case_number"] == "2024 CVS 000456"
    assert li["listing_type"] in {"lis_pendens", "unknown"}
    assert li["raw"]["nc_ecourts_manual"]["filing_date"] == "11/02/2026"


def test_listing_dict_validates_as_model():
    # The adapter output must round-trip into the real models.Listing so the
    # merge/resolver step can consume it.
    from foreclosure_scraper.models import Listing

    recs = mod.parse_nc_ecourts_html(DETAIL_HTML)
    div = next(r for r in recs if r["case_number"] == "24CVD001234-590")
    li_dict = mod.record_to_listing_dict(div)
    li = Listing.model_validate(li_dict)
    assert li.owner_name == "JEREMIAH CALDWELL"
    assert li.county == "Buncombe"
    assert li.state == "NC"
    assert li.case_number == "24CVD001234-590"
