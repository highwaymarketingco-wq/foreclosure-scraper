"""Logan 'The Lookup' ROD adapter parser + NC scraper classification."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.rod import logan
from foreclosure_scraper.scrapers.counties_nc.nc_rod_logan import (
    _classify, _resolve_defendant, _to_listing,
)
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.rod.models import RodDoc

_FIXTURE = """
<a href="javascript: loadDetailsScreen('2026002775');" id="link_2026002775"> 06/12/2026&nbsp; </a></td>
<td class="summary" id="2026002775">DOC 1191  835 &nbsp; </td>
<td class="summary" id="2026002775">TR/D&nbsp;</td>
<td class="summary" id="2026002775">CONNESTEE FALLS LT:112&nbsp;</td>
<td class="summary" id="2026002775">GRANTOR&nbsp;</td>
<td class="summary" id="2026002775">FEHSENFELD CAROLYN C TR&nbsp;</td>
<td class="summary" id="2026002775">ACME BANK NA&nbsp;</td>
"""


def test_parse_records():
    docs = logan._parse_records(_FIXTURE, "NC", "Transylvania")
    assert len(docs) == 1
    d = docs[0]
    assert d.doc_type == "TR/D"
    assert d.recorded_date == datetime(2026, 6, 12)
    assert d.book == "1191" and d.page == "835"
    assert d.grantor == "FEHSENFELD CAROLYN C TR"   # party_type GRANTOR -> searched
    assert d.grantee == "ACME BANK NA"
    assert d.instrument_no == "2026002775"
    assert "CONNESTEE" in d.notes


def test_parse_grantee_party_flips_sides():
    fx = _FIXTURE.replace("GRANTOR&nbsp;", "GRANTEE&nbsp;")
    d = logan._parse_records(fx, "NC", "Transylvania")[0]
    assert d.grantee == "FEHSENFELD CAROLYN C TR"   # searched is now grantee
    assert d.grantor == "ACME BANK NA"


def test_classify():
    assert _classify("FCL")[0] is ListingType.LIS_PENDENS
    assert _classify("S/TR")[0] is ListingType.LIS_PENDENS
    assert _classify("TR/D")[0] is ListingType.FORECLOSURE_SALE
    assert _classify("SHF/D")[0] is ListingType.FORECLOSURE_SALE
    assert _classify("D/DIST")[0] is ListingType.PROBATE_NOTICE
    assert _classify("LIEN")[0] is ListingType.TAX_LIEN
    assert _classify("JUDGMENT")[0] is ListingType.TAX_LIEN
    assert _classify("DEED") is None
    assert _classify("MTG") is None


def test_to_listing_probate_tags_signal():
    doc = RodDoc(county="Transylvania", state="NC", doc_type="D/DIST",
                 grantor="SMITH ESTATE", instrument_no="2026000001",
                 notes="LOT 1", recorded_date=datetime(2026, 6, 1))
    li = _to_listing(doc, "counties_nc.nc_rod_logan", "http://x")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["relationship_signal"]["kind"] == "probate"
    assert li.defendant == "SMITH ESTATE" and li.county == "Transylvania"


def test_to_listing_skips_non_distress():
    doc = RodDoc(county="Transylvania", state="NC", doc_type="DEED", grantor="X")
    assert _to_listing(doc, "s", "u") is None


def test_logan_counties_are_the_three_working_nc():
    assert set(logan.LOGAN_COUNTIES) == {("NC", "Transylvania"), ("NC", "McDowell"), ("NC", "Mitchell")}


def test_split_book_page_preserves_alpha_suffix():
    # Spartanburg books carry a letter suffix searched as "149-D" — must NOT drop the D.
    assert logan._split_book_page("149-D 567") == ("149-D", "567")
    assert logan._split_book_page("149D 567") == ("149-D", "567")  # normalized to dashed form
    assert logan._split_book_page("Book 149-D Pg 567") == ("149-D", "567")


def test_split_book_page_plain_numeric():
    assert logan._split_book_page("4821 1203") == ("4821", "1203")
    assert logan._split_book_page("") == (None, None)
    assert logan._split_book_page("no digits here") == (None, None)


# --------------------------------------------------------------------------- multi-party rows
#
# Live-captured 2026-10-01 against search.mcdowelldeeds.com: a real "it"
# (instrument-type) sweep renders ONE ROW PER PARTY, not one row per
# document, and repeats the SAME instrument id across all of them. Each such
# row carries 5 "summary" cells (Book Info, Doc Type, Legal, Party Type,
# Name), not the 6-cell single-row shape the original parser assumed.

def _row(inst: str, date: str, book_info: str, doc_type: str, legal: str,
         party_type: str, name: str) -> str:
    return (
        f'<a href="javascript: loadDetailsScreen(\'{inst}\');" id="link_{inst}">'
        f' {date}&nbsp; </a></td>\n'
        f'<td class="summary" id="{inst}">{book_info}&nbsp;</td>\n'
        f'<td class="summary" id="{inst}">{doc_type}&nbsp;</td>\n'
        f'<td class="summary" id="{inst}">{legal}&nbsp;</td>\n'
        f'<td class="summary" id="{inst}">{party_type}&nbsp;</td>\n'
        f'<td class="summary" id="{inst}">{name}&nbsp;</td>\n'
    )


# The exact McDowell JGMT shape: 9 distinct parties (incl. a named estate and
# "THE UNKNOWN HEIRS OF...") spread across 18 rows (grantor/grantee pair per
# party) all sharing instrument 2026003832.
_MULTI_PARTY_FIXTURE = "".join(
    _row("2026003832", "08/05/2026", "CRP 1547  326", "JGMT",
         "PD:DEFAULT JUDGEMENT ORDER", role, name)
    for name in (
        "COMPUTERSHARE TRUST COMPANY, N.A. TR", "GOTT MARK D.", "NBE ASSET TRUST",
        "ROBINSON MAXINE SOUTHER EST", "ROBINSON OLIVIA BROOKE", "ROBINSON TINA MCCRAW",
        "THE UNKNOWN HEIRS OF MAXINE SOUTHER ROBINSON", "TURNER ASHLEY ROBINSON",
        "TURNER KELVIN",
    )
    for role in ("GRANTOR", "GRANTEE")
)


def test_multi_party_instrument_keeps_every_party_as_one_document():
    """The old parser collapsed this into ONE Listing carrying only the
    first-seen name (and a corrupted 'reverse party' bled in from the next
    row's book-info). It must now be ONE RodDoc with every real party kept."""
    docs = logan._parse_records(_MULTI_PARTY_FIXTURE, "NC", "McDowell")
    assert len(docs) == 1
    d = docs[0]
    assert d.instrument_no == "2026003832"
    assert d.doc_type == "JGMT"
    assert d.book == "1547" and d.page == "326"
    assert d.recorded_date == datetime(2026, 8, 5)
    for name in (
        "GOTT MARK D.", "ROBINSON MAXINE SOUTHER EST", "ROBINSON OLIVIA BROOKE",
        "ROBINSON TINA MCCRAW", "THE UNKNOWN HEIRS OF MAXINE SOUTHER ROBINSON",
        "TURNER ASHLEY ROBINSON", "TURNER KELVIN", "COMPUTERSHARE TRUST COMPANY, N.A. TR",
        "NBE ASSET TRUST",
    ):
        assert name in d.grantor, f"{name!r} missing from grantor"
    assert d.raw["logan"]["grantors"].count("GOTT MARK D.") == 1  # deduped, not 18x


def test_multi_party_instrument_separates_grantor_and_grantee_roles():
    docs = logan._parse_records(_MULTI_PARTY_FIXTURE, "NC", "McDowell")
    d = docs[0]
    # Each name appears once as GRANTOR and once as GRANTEE in this fixture
    # (mirrors the live page); both sides end up populated.
    assert "GOTT MARK D." in d.grantor
    assert "GOTT MARK D." in d.grantee


def test_second_heir_on_a_two_grantor_row_is_not_dropped():
    """The simpler, more common real-world shape: an FCL naming 2 co-grantors
    (live-confirmed on McDowell instrument 2026003264 — a husband/wife style
    pair alongside a trustee and an HOA, all filed as GRANTOR-role rows)."""
    fx = "".join(
        _row("2026003264", "07/20/2026", "CRP 1544  239", "FCL",
             "PD:NOTICE OF FORECLOSURE OF CLAIM OF LIEN", "GRANTOR", name)
        for name in ("AHUATL TERESA RUEDA", "TORRES HERNAN ANUATL")
    ) + _row("2026003264", "07/20/2026", "CRP 1544  239", "FCL",
             "PD:NOTICE OF FORECLOSURE OF CLAIM OF LIEN", "GRANTEE", "NC-SDS, LLC")
    docs = logan._parse_records(fx, "NC", "McDowell")
    assert len(docs) == 1
    d = docs[0]
    assert "AHUATL TERESA RUEDA" in d.grantor
    assert "TORRES HERNAN ANUATL" in d.grantor, "second co-grantor must not be dropped"
    assert d.grantee == "NC-SDS, LLC"


# --------------------------------------------------------------------------- _resolve_defendant

def test_resolve_defendant_keeps_both_real_co_grantors_on_a_pre_code():
    """FCL (lis-pendens-class): two real owners + a trustee + an HOA all filed
    as GRANTOR-role names, one GRANTEE buyer entity. Both real owners must
    survive; the institutional names must not mask them."""
    doc = RodDoc(
        county="McDowell", state="NC", doc_type="FCL",
        grantor="AHUATL TERESA RUEDA; KARRENSTEIN & LOVE, PLLC TR; "
                "PLJ PROPERTY OWNERS ASSOCIATION, INC.; TORRES HERNAN ANUATL",
        grantee="NC-SDS, LLC",
    )
    out = _resolve_defendant(doc)
    assert "AHUATL TERESA RUEDA" in out
    assert "TORRES HERNAN ANUATL" in out
    assert "PLJ PROPERTY OWNERS ASSOCIATION, INC." not in out, (
        "one institutional co-party must not reject the whole joined string"
    )
    assert "NC-SDS, LLC" not in out


def test_resolve_defendant_probate_keeps_heir_designation_names():
    """Probate/lien codes must NOT institutional-filter -- 'THE UNKNOWN HEIRS
    OF ...' contains stopword tokens ('the', 'of') that would otherwise look
    institutional, and a decedent '... EST' name must survive too."""
    doc = RodDoc(
        county="McDowell", state="NC", doc_type="JGMT",
        grantor="GOTT MARK D.; ROBINSON MAXINE SOUTHER EST; "
                "THE UNKNOWN HEIRS OF MAXINE SOUTHER ROBINSON; TURNER KELVIN",
    )
    out = _resolve_defendant(doc)
    assert "THE UNKNOWN HEIRS OF MAXINE SOUTHER ROBINSON" in out
    assert "ROBINSON MAXINE SOUTHER EST" in out
    assert "GOTT MARK D." in out
    assert "TURNER KELVIN" in out


def test_resolve_defendant_all_institutional_pre_code_returns_none():
    doc = RodDoc(county="McDowell", state="NC", doc_type="S/TR",
                 grantor="ACME BANK NA", grantee="SOME TRUST SERVICES LLC")
    assert _resolve_defendant(doc) is None


def test_multi_party_jgmt_to_listing_defendant_has_all_heirs():
    """End-to-end: parse the real multi-row HTML, then run it through
    _to_listing and confirm the published defendant carries every heir."""
    docs = logan._parse_records(_MULTI_PARTY_FIXTURE, "NC", "McDowell")
    li = _to_listing(docs[0], "counties_nc.nc_rod_logan", "http://x")
    assert li is not None
    assert li.listing_type == ListingType.TAX_LIEN  # JGMT classifies as a lien
    for name in ("GOTT MARK D.", "ROBINSON MAXINE SOUTHER EST",
                 "THE UNKNOWN HEIRS OF MAXINE SOUTHER ROBINSON", "TURNER KELVIN"):
        assert name in li.defendant


def test_single_row_instrument_unaffected_by_multi_row_handling():
    """A page mixing a normal single-row instrument with a multi-row one must
    still parse the single-row instrument exactly as before."""
    fx = _FIXTURE + _MULTI_PARTY_FIXTURE
    docs = logan._parse_records(fx, "NC", "Transylvania")
    assert len(docs) == 2
    single = next(d for d in docs if d.instrument_no == "2026002775")
    assert single.grantor == "FEHSENFELD CAROLYN C TR"
    assert single.grantee == "ACME BANK NA"


# --------------------------------------------------------------------------- XRef + document image
#
# Live-captured 2026-10-03 against search.transylvaniadeeds.com /
# search.mcdowelldeeds.com / search.mitchelldeeds.com: every row carries two
# MORE columns after the 6 `class="summary"` cells this parser used to stop
# at -- "XRef" (the underlying instrument this one refers to, e.g. the Deed
# of Trust a Notice of Sale forecloses on) and "Image?" (a free
# view_image.php?key=<hex>&type=pdf/tif link to the actual recorded document
# image). Neither carries a `class="summary"` attribute so the old
# `_ROW_CELL_RE` never saw them at all.

_FIXTURE_WITH_DOCS = """
<a href="javascript: loadDetailsScreen('2026003956');" onclick="changeColor('link_2026003956');" id="link_2026003956"> 08/07/2026&nbsp; </a></td>
<td class="summary" id="2026003956">DOC 1199  498 &nbsp; </td>
<td class="summary" id="2026003956">S/TR&nbsp;</td>
<td class="summary" id="2026003956">PD:APPOINTMENT OF SUBSTITUTE TRUSTEE&nbsp;</td>
<td class="summary" id="2026003956">GRANTOR&nbsp;</td>
<td class="summary" id="2026003956">ENGLISH EDWIN STUART JR.&nbsp;</td>
<td class="summary" id="2026003956">PNC BANK, NATIONAL ASSOCIATION&nbsp;</td>
<td><a href="javascript:loadDetailsScreen('2013001844');" style="color:#0033FF;">D/T
650 325 (1)</a></td>
<td><a id='0' onclick='linkColorChange(0)' href='view_image.php?key=b1b8057d90d945b06f28a7319d59820e&type=tif' target='_blank'>TIFF</a><br><a class='imageLinkColorChange' href='view_image.php?key=b1b8057d90d945b06f28a7319d59820e&type=pdf' target='_blank'>PDF</a>&nbsp;</td>
"""


def test_xref_and_image_key_are_captured():
    docs = logan._parse_records(_FIXTURE_WITH_DOCS, "NC", "Transylvania")
    assert len(docs) == 1
    d = docs[0]
    assert d.raw["logan"]["image_key"] == "b1b8057d90d945b06f28a7319d59820e"
    assert d.raw["logan"]["xref_instrument_no"] == "2013001844"
    assert d.raw["logan"]["xref"] == "D/T 650 325 (1)"


def test_row_without_trailing_columns_leaves_xref_and_image_key_none():
    """The plain single-row fixture (no XRef/Image markup) must not error and
    must simply carry None, not crash or fabricate a value."""
    docs = logan._parse_records(_FIXTURE, "NC", "Transylvania")
    d = docs[0]
    assert d.raw["logan"]["image_key"] is None
    assert d.raw["logan"]["xref"] is None


def test_multi_row_instrument_takes_xref_and_image_key_once_not_duplicated():
    """A multi-row (one-party-per-row) instrument repeats the same XRef/Image
    markup on every row; must be captured once per instrument, not per row,
    and must not raise on the 5-cell shape."""
    fx = _MULTI_PARTY_FIXTURE.replace(
        "&nbsp;</td>\n",
        "&nbsp;</td>\n<td><a href=\"javascript:loadDetailsScreen('2020000111');\">"
        "DEED 500 100 (4)</a></td>\n<td><a href='view_image.php?key=deadbeef00"
        "&type=pdf'>PDF</a></td>\n",
    )
    docs = logan._parse_records(fx, "NC", "McDowell")
    assert len(docs) == 1
    d = docs[0]
    assert d.raw["logan"]["image_key"] == "deadbeef00"
    assert d.raw["logan"]["xref_instrument_no"] == "2020000111"


def test_to_listing_surfaces_xref_and_image_key_with_session_caveat():
    """End-to-end: the published Listing's raw['rod'] must carry both new
    fields, wired through nc_rod_logan.py's _to_listing."""
    docs = logan._parse_records(_FIXTURE_WITH_DOCS, "NC", "Transylvania")
    li = _to_listing(docs[0], "counties_nc.nc_rod_logan", "http://x")
    assert li is not None
    assert li.raw["rod"]["image_key"] == "b1b8057d90d945b06f28a7319d59820e"
    assert li.raw["rod"]["xref"] == "D/T 650 325 (1)"
    assert li.raw["rod"]["xref_instrument_no"] == "2013001844"
