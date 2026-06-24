"""Pin the NC ROD post-sale recording extraction.

Each vendor module (aumentum / cott / cchs) gained:
  * AUMENTUM_POST_SALE_DOC_TYPES (or vendor-specific equivalent) listing
    the doc-type labels for Trustee's Deed Upon Sale and friends
  * _is_post_sale() predicate
  * discover_recent_sold_recordings() function

The grid parsers also now capture consideration_amount + excise_tax_stamp
columns when the recording table includes them (NC: $1 stamp per $500
of consideration, so stamp × 500 = sold price when consideration isn't
shown directly).

These tests use synthetic HTML matching the actual grid structures
observed locally.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.rod.aumentum import (
    AUMENTUM_POST_SALE_DOC_TYPES,
    _is_nod,
    _is_post_sale,
    _money,
    _parse_grid,
)
from foreclosure_scraper.rod.cchs import (
    POST_SALE_KEYWORDS,
)
from foreclosure_scraper.rod.cchs import _is_post_sale as cchs_is_post_sale
from foreclosure_scraper.rod.cchs import _parse_rows as cchs_parse_rows
from foreclosure_scraper.rod.deed_stamp import sold_price_from_stamp


# ---- aumentum/cott shared post-sale predicate ----

def test_aumentum_recognizes_trustee_deed_variants():
    """Multiple wording variants the parsers see in the wild."""
    for s in (
        "TRUSTEES DEED UPON SALE",
        "TRUSTEE'S DEED UPON SALE",
        "Trustees Deed",
        "SUBSTITUTE TRUSTEES DEED",
        "Substitute Trustee's Deed",
        "FORECLOSURE DEED",
        "DEED UNDER POWER OF SALE",
        "Commissioner's Deed",
    ):
        assert _is_post_sale(s), f"_is_post_sale missed {s!r}"


def test_aumentum_does_not_misfire_on_non_post_sale_docs():
    for s in (
        "DEED OF TRUST",
        "MORTGAGE",
        "RELEASE OF LIEN",
        "WARRANTY DEED",   # ordinary sale, not foreclosure
        "QUITCLAIM DEED",
        "ASSIGNMENT",
    ):
        assert not _is_post_sale(s), f"_is_post_sale false-positive on {s!r}"


def test_pre_sale_docs_still_detected_separately():
    """The NOD predicate still works (regression check that we didn't break
    pre-sale detection while adding post-sale)."""
    assert _is_nod("NOTICE OF SALE") is True
    assert _is_nod("LIS PENDENS") is True
    assert _is_nod("TRUSTEES DEED UPON SALE") is False  # post-sale, not NOD


def test_aumentum_post_sale_doc_types_includes_common_labels():
    must_have = {
        "TRUSTEES DEED UPON SALE",
        "TRUSTEE'S DEED UPON SALE",
        "FORECLOSURE DEED",
        "SUBSTITUTE TRUSTEES DEED",
    }
    assert must_have <= set(AUMENTUM_POST_SALE_DOC_TYPES)


# ---- aumentum grid parses consideration ----

def test_aumentum_grid_parses_consideration_column():
    """When the grid table includes a Consideration column, the value
    flows into RodDoc.consideration_amount."""
    html = """
    <table id="ResultsGrid">
      <tr>
        <th>Record Date</th>
        <th>Doc Type</th>
        <th>Book</th>
        <th>Page</th>
        <th>Grantor</th>
        <th>Grantee</th>
        <th>Instrument</th>
        <th>Consideration</th>
      </tr>
      <tr>
        <td>05/02/2026</td>
        <td>TRUSTEES DEED UPON SALE</td>
        <td>1234</td>
        <td>56</td>
        <td>SMITH JOHN</td>
        <td>ACME LLC</td>
        <td>20260054321</td>
        <td>$48,500.00</td>
      </tr>
    </table>
    """
    docs = _parse_grid(html, "Buncombe", "NC")
    assert len(docs) == 1
    d = docs[0]
    assert d.consideration_amount == 48500.0
    assert "TRUSTEE" in d.doc_type.upper()


def test_aumentum_grid_derives_consideration_from_excise_tax():
    """When ONLY the excise tax / stamp column is shown (not direct
    consideration), recover sold price as stamp × 500."""
    html = """
    <table id="ResultsGrid">
      <tr>
        <th>Record Date</th>
        <th>Doc Type</th>
        <th>Book</th>
        <th>Page</th>
        <th>Grantor</th>
        <th>Grantee</th>
        <th>Instrument</th>
        <th>Excise Tax</th>
      </tr>
      <tr>
        <td>05/02/2026</td>
        <td>TRUSTEES DEED UPON SALE</td>
        <td>1234</td>
        <td>56</td>
        <td>SMITH JOHN</td>
        <td>ACME LLC</td>
        <td>20260054321</td>
        <td>$97.00</td>
      </tr>
    </table>
    """
    docs = _parse_grid(html, "Buncombe", "NC")
    assert len(docs) == 1
    d = docs[0]
    assert d.excise_tax_stamp == 97.0
    assert d.consideration_amount == 48500.0  # 97 × 500


# ---- _money helper ----

def test_money_handles_common_formats():
    assert _money("$45,000.00") == 45000.0
    assert _money("$1,000,000") == 1_000_000.0
    assert _money("48500") == 48500.0
    assert _money("") is None
    assert _money(None) is None


def test_money_rejects_implausible_amounts():
    assert _money("$0") is None  # zero
    assert _money("$99,999,999") is None  # > 50M cap


# ---- CCHS post-sale ----

def test_cchs_recognizes_trustee_deed_variants():
    assert cchs_is_post_sale("Trustee's Deed Upon Sale")
    assert cchs_is_post_sale("FORECLOSURE DEED")
    assert not cchs_is_post_sale("Mortgage")


def test_cchs_post_sale_keywords_include_common():
    assert {"TRUSTEE", "COMMISSIONER"} <= set(POST_SALE_KEYWORDS)


def test_cchs_parses_consideration_from_excise_stamp():
    """CCHS getall XML: <mo> is the NC excise stamp; consideration = stamp * 500."""
    xml = (
        "<SearchResponse><recordcount>1</recordcount>"
        "<r><da>05/02/2026</da><ki>COM/D</ki><bk>1234</bk><pg>56</pg>"
        "<dn>2026004567</dn><or>SMITH</or><or1>JOHN</or1>"
        "<ee>ACME</ee><ee1>LLC</ee1><mo>$97.00</mo><pk>1-99</pk></r>"
        "</SearchResponse>"
    )
    docs = cchs_parse_rows(xml, "NC", "Cleveland", sold=True)
    assert len(docs) == 1
    assert docs[0].excise_tax_stamp == 97.0
    assert docs[0].consideration_amount == 48500.0  # 97 * 500
    assert docs[0].grantor == "SMITH JOHN"


# ---- deed_stamp helper still works ----

def test_deed_stamp_recovers_price_from_text():
    """Reusable helper for free-text recordings (text dumps from
    detail pages, etc.) where the parser only has unstructured text."""
    text = "Trustees Deed Upon Sale dated 05/02/2026 EXCISE TAX: $97.00"
    assert sold_price_from_stamp(text) == 48500.0
