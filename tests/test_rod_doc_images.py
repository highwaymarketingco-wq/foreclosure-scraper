"""Tests for rod/doc_images — the robots gate, vendor parsers and image
normalization that gate recorded-principal OCR.

Fixtures are REAL responses saved live 2026-08-03/04:
  * rod_logan_transylvania_dt_rows.html — three D/T instruments trimmed out of a
    search.transylvaniadeeds.com `searchType=it` results page (one joint note
    with five party groups, one with six, one single-party LLC).
  * rod_cchs_burke_name_rows.xml — the `<r>` rows a us5 CCHS name search returns
    for BRANCH DAVID in Burke NC.

No network: every test reads a fixture or a literal robots body.
"""
from pathlib import Path

import pytest

from foreclosure_scraper.rod import doc_images as di

FIX = Path(__file__).parent / "fixtures"
LOGAN_HTML = (FIX / "rod_logan_transylvania_dt_rows.html").read_text()
CCHS_XML = (FIX / "rod_cchs_burke_name_rows.xml").read_text()

# The byte-exact robots.txt every i3 Verticals / Logan `*deeds.com` tenant
# served on 2026-08-03 (Spartanburg, Laurens, McDowell, Mitchell).
LOGAN_ROBOTS = "# Only allow the front page to be indexed.\nUser-agent: *\nAllow: /$\nDisallow: /"
CCHS_US4_ROBOTS = "User-agent: *\nDisallow: /\n#Directories\nDisallow: /ProcessedImages/"


# --- robots gate -------------------------------------------------------------
def test_anchored_allow_covers_only_the_bare_root():
    """`Allow: /$` + `Disallow: /` allows the front page and NOTHING else — the
    exact vendor pattern that walls Spartanburg/Laurens/McDowell/Mitchell."""
    assert di.path_disallowed(LOGAN_ROBOTS, "/") is False
    assert di.path_disallowed(LOGAN_ROBOTS, "/view_image.php") is True
    assert di.path_disallowed(LOGAN_ROBOTS, "/content.php") is True
    assert di.path_disallowed(LOGAN_ROBOTS, "/index.php") is True


def test_us4_cchs_is_disallowed():
    assert di.path_disallowed(CCHS_US4_ROBOTS, "/HendersonNCNW/GenerateSingleImageForPrint.asp") is True


def test_absent_robots_means_allowed():
    """RFC 9309: no robots.txt (or an empty one) imposes no restriction."""
    assert di.path_disallowed("", "/anything") is False


def test_more_specific_allow_beats_disallow():
    body = "User-agent: *\nDisallow: /\nAllow: /public/"
    assert di.path_disallowed(body, "/public/doc.pdf") is False
    assert di.path_disallowed(body, "/private/doc.pdf") is True


def test_other_user_agent_group_is_ignored():
    body = "User-agent: Googlebot\nDisallow: /\n\nUser-agent: *\nAllow: /"
    assert di.path_disallowed(body, "/view_image.php") is False


@pytest.mark.asyncio
async def test_ensure_allowed_uses_cached_body(monkeypatch):
    calls = []

    async def _fake_body(origin):
        calls.append(origin)
        return LOGAN_ROBOTS

    monkeypatch.setattr(di, "_robots_body", _fake_body)
    assert await di.ensure_allowed("https://search.spartanburgdeeds.com/view_image.php") is False
    assert await di.ensure_allowed("https://search.spartanburgdeeds.com/") is True
    assert calls == ["https://search.spartanburgdeeds.com"] * 2


def test_no_env_bypass_for_the_robots_gate():
    """Regression guard: rod/kofile.py ships a KOFILE_IGNORE_ROBOTS escape
    hatch. This module must NOT — a Disallow is the site owner's answer."""
    src = Path(di.__file__).read_text()
    assert "IGNORE_ROBOTS" not in src
    assert "getenv" not in src and "environ" not in src


# --- county registry integrity ----------------------------------------------
def test_registry_only_contains_free_and_robots_clean_counties():
    for key in di.DOC_IMAGE_COUNTIES:
        verdict, _ = di.COUNTY_IMAGE_STATUS[key]
        assert verdict == "free", f"{key} is registered but graded {verdict}"


def test_walled_and_paywalled_counties_are_not_registered():
    for key, (verdict, _) in di.COUNTY_IMAGE_STATUS.items():
        if verdict != "free":
            assert key not in di.DOC_IMAGE_COUNTIES, f"{key} ({verdict}) must not be registered"


def test_spartanburg_and_laurens_are_recorded_as_robots_walls():
    assert di.COUNTY_IMAGE_STATUS[("SC", "Spartanburg")][0] == "robots_disallow"
    assert di.COUNTY_IMAGE_STATUS[("SC", "Laurens")][0] == "robots_disallow"
    assert di.COUNTY_IMAGE_STATUS[("NC", "Buncombe")][0] == "paywalled"


# --- doc-type classification -------------------------------------------------
def test_deed_of_trust_variants_are_notes():
    for t in ("D/T", "DT", "MTG", "MORTGAGE", "DEED OF TRUST", "Security Deed"):
        assert di.is_dot_type(t) is True, t


def test_satisfactions_and_conveyances_are_not_notes():
    for t in ("MORTGAGE SATISFACTION", "M/SAT", "M/ASSGN", "RELEASE",
              "TR/D", "TRUSTEES DEED", "FORECLOSURE DEED", "TAX DEED",
              "COMMISSIONERS DEED", "DEED"):
        assert di.is_dot_type(t) is False, t


def test_trd_is_excluded_because_it_is_a_trustees_deed():
    """Live-caught on Burke bk2847/pg826: `TR/D` OCR'd to $170,640 with
    doc_type 'trustees_deed'. That figure is the auction SALE PRICE — feeding it
    to the equity engine as a principal inverts the answer."""
    assert di.is_dot_type("TR/D") is False
    assert "TR/D" not in di._LOGAN_DOT_CODES


def test_ocr_backstop_rejects_conveyances_but_passes_unknown():
    assert di.ocr_is_note({"doc_type": "deed_of_trust"}) is True
    assert di.ocr_is_note({"doc_type": "trustees_deed"}) is False
    assert di.ocr_is_note({"doc_type": "tax_deed"}) is False
    assert di.ocr_is_note({"doc_type": None}) is True      # unknown -> index already filtered
    assert di.ocr_is_note(None) is False


# --- Logan records-grid parser ----------------------------------------------
def test_logan_parses_dot_rows_with_image_keys():
    rows = di.parse_logan_dot_rows(LOGAN_HTML, "NC", "Transylvania")
    assert len(rows) == 3
    for d in rows:
        assert d.doc_type == "D/T"
        assert d.recorded_date is not None
        assert d.book and d.page
        assert d.raw["image_key"] and len(d.raw["image_key"]) == 32


def test_logan_variable_party_stride_keeps_real_names():
    """Logan repeats the cell block once per indexed party and the block WIDTH
    varies by tenant (5 cells here, 6 on Spartanburg). A fixed [:6] slice read
    the next party's Book-Info cell as this row's party name, producing grantors
    literally named 'DOC 1193 195'."""
    rows = di.parse_logan_dot_rows(LOGAN_HTML, "NC", "Transylvania")
    for d in rows:
        assert d.grantor, "grantor must not be empty"
        assert not d.grantor.startswith("DOC "), d.grantor


def test_logan_keeps_every_co_borrower_on_a_joint_note():
    rows = di.parse_logan_dot_rows(LOGAN_HTML, "NC", "Transylvania")
    joint = [d for d in rows if ";" in (d.grantor or "")]
    assert joint, "fixture includes a joint note"
    assert len(joint[0].raw["grantor_list"]) >= 2


def test_party_groups_detects_stride():
    assert di._party_groups(["B", "T", "L", "P", "N1", "B", "T", "L", "P", "N2"]) == [
        ["B", "T", "L", "P", "N1"], ["B", "T", "L", "P", "N2"]]
    assert di._party_groups(["B", "T", "L", "P", "N1"]) == [["B", "T", "L", "P", "N1"]]
    assert di._party_groups([]) == []


def test_surname_index_finds_a_co_borrower_with_a_different_surname():
    docs = di.parse_logan_dot_rows(LOGAN_HTML, "NC", "Transylvania")
    idx = di.index_by_surname(docs)
    # every indexed party surname resolves back to at least one doc
    assert idx
    for surname, hits in idx.items():
        assert surname == surname.upper() and hits


def test_rank_dot_docs_prefers_owner_then_newest():
    docs = di.parse_logan_dot_rows(LOGAN_HTML, "NC", "Transylvania")
    idx = di.index_by_surname(docs)
    burns = di.rank_dot_docs(idx.get("BURNS") or [], "BURNS", "MIKE")
    assert burns and "BURNS" in (burns[0].grantor or "")


# --- CCHS row parsing --------------------------------------------------------
def test_cchs_fixture_carries_dot_rows_with_an_image_flag():
    import re
    recs = re.findall(r"<r>(.*?)</r>", CCHS_XML, re.S)
    assert recs
    from foreclosure_scraper.rod.cchs import _field
    dots = [r for r in recs if di.is_dot_type(_field(r, "ki")) and _field(r, "im").upper() == "I"]
    assert dots, "fixture must contain at least one imaged deed of trust"
    d = dots[0]
    assert _field(d, "bk") and _field(d, "pg") and _field(d, "da")


def test_cchs_trustees_deed_rows_are_filtered_out():
    import re
    from foreclosure_scraper.rod.cchs import _field
    recs = re.findall(r"<r>(.*?)</r>", CCHS_XML, re.S)
    for r in recs:
        if _field(r, "ki").upper() == "TR/D":
            assert di.is_dot_type("TR/D") is False


# --- image normalization -----------------------------------------------------
def test_pdf_passes_through():
    assert di.to_ocr_ready(b"%PDF-1.4 junk", "application/pdf") == (b"%PDF-1.4 junk", "application/pdf")


def test_pdf_detected_by_magic_even_with_a_wrong_mime():
    data, mime = di.to_ocr_ready(b"%PDF-1.7 x", "application/octet-stream")
    assert mime == "application/pdf"


def test_tiff_is_converted_to_png_because_gemini_rejects_tiff():
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, format="TIFF")
    out = di.to_ocr_ready(buf.getvalue(), "image/tiff")
    assert out is not None
    data, mime = out
    assert mime == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n"


def test_unusable_bytes_return_none():
    assert di.to_ocr_ready(b"", "application/pdf") is None
    assert di.to_ocr_ready(b"not an image", "application/x-msdownload") is None


def test_pdf_rasterizes_to_png_for_the_non_gemini_fallback():
    """Gemini is the only free backend that takes application/pdf. When its keys
    are quota-exhausted (live-caught 2026-08-04: 108 downloaded documents, 0
    OCR'd) page 1 must still be readable by GitHub Models / Groq."""
    import io
    from PIL import Image
    from pypdf import PdfWriter
    # Build a real one-page PDF via Pillow so the fixture needs no network.
    buf = io.BytesIO()
    Image.new("RGB", (612, 792), "white").save(buf, format="PDF")
    w = PdfWriter()
    w.append(io.BytesIO(buf.getvalue()))
    out = io.BytesIO()
    w.write(out)
    got = di.rasterize_pdf_page1(out.getvalue(), resolution=50)
    assert got is not None
    data, mime = got
    assert mime == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n"


def test_rasterize_rejects_non_pdf_bytes():
    assert di.rasterize_pdf_page1(b"\x89PNG\r\n\x1a\n") is None
    assert di.rasterize_pdf_page1(b"") is None


# --- name handling -----------------------------------------------------------
def test_name_parts_handles_both_orders():
    assert di.name_parts("SMITH, JOHN A") == ("SMITH", "JOHN")
    assert di.name_parts("Hartsock David &") == ("HARTSOCK", "DAVID")
    assert di.name_parts("PJP PROPERTY, LLC") == ("PJP PROPERTY", "LLC")
    assert di.name_parts("") == ("", "")


@pytest.mark.asyncio
async def test_owner_dot_documents_returns_empty_for_unregistered_county():
    assert await di.owner_dot_documents("SC", "Spartanburg", "SMITH, JOHN") == []
    assert await di.owner_dot_documents("NC", "Buncombe", "SMITH, JOHN") == []
    assert await di.owner_dot_documents("NC", "Burke", "") == []
