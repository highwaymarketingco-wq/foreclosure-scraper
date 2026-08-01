"""ncnotices.com county-scoped parser (NC Press Association grid -> typed leads).

The fixture is REAL grid HTML captured live 2026-07-31 with the 11 footprint
counties ticked, trimmed to one row per parse branch plus one out-of-footprint
row. Every assertion below is about a row that actually published.
"""
from __future__ import annotations

import asyncio
import pathlib

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.public_notices import _press_assoc as pa
from foreclosure_scraper.scrapers.public_notices import nc_notices_counties as M

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "ncnotices_county_grid.html"
_SLUG = "public_notices.nc_notices_counties"

# The flat single-<tr>-per-result shape the helper must also accept.
_FLAT = """
<table id="GridView1">
<tr><td>The Herald Friday, July 31, 2026 City: Marion County: McDowell</td>
<td>NOTICE OF FORECLOSURE SALE 26SP000012-560 Under and by virtue of the power of sale
contained in a Deed of Trust executed by JOHN Q PUBLIC, dated May 1, 2019 and recorded in
Book 1234 at Page 56 in the McDowell County Registry. The property at 118 Sycamore Lane
(PIN 1697-32-4455) will be sold at public auction on September 9, 2026.</td>
<td><input onclick="javascript:location.href='Details.aspx?SID=abc&amp;ID=777001';return false;"/></td>
</tr></table>
"""


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return pa.parse_grid(_FIXTURE.read_text())


@pytest.fixture(scope="module")
def listings(rows) -> list:
    return [li for li in (M._to_listing(r, _SLUG) for r in rows) if li]


# ---------------------------------------------------------------- helper ---

def test_parse_grid_reads_every_row(rows):
    assert len(rows) == 7
    first = rows[0]
    assert first["notice_id"].isdigit()
    assert first["publication"] == "Beacon Tribune"
    assert first["date_text"] == "Thursday, July 30, 2026"
    assert first["published_at"].date().isoformat() == "2026-07-30"
    assert "click 'view' to open the full text" not in first["text"]


def test_parse_grid_accepts_the_flat_row_shape():
    rows = pa.parse_grid(_FLAT)
    assert len(rows) == 1
    assert rows[0]["notice_id"] == "777001"
    assert rows[0]["county_meta"] == "McDowell"
    assert rows[0]["city_meta"] == "Marion"


def test_pager_labels():
    html = _FIXTURE.read_text()
    assert pa.total_pages(html) == 5
    assert pa.current_page(html) == 1
    assert pa.total_pages("<div>no pager</div>") is None


def test_parse_date_handles_platform_formats():
    assert pa.parse_date("Thursday, July 30, 2026").month == 7
    assert pa.parse_date("7/30/2026").day == 30
    assert pa.parse_date("nonsense") is None


# -------------------------------------------------------- county routing ---

def test_subject_county_beats_publication_county(listings):
    """A Buncombe paper carries Henderson County foreclosures — the notice body
    wins over the grid's County: field, which is the PUBLISHER's county."""
    harvie = next(li for li in listings if li.defendant == "KAREN HARVIE")
    assert harvie.county == "Henderson"
    source_row = next(r for r in pa.parse_grid(_FIXTURE.read_text())
                      if "KAREN HARVIE" in r["text"])
    assert source_row["county_meta"] == "Buncombe"


def test_publication_county_is_the_fallback(listings):
    """The NCGS 105-369 ad names a municipality, not a county — fall back to
    the publishing paper's county (Flat Rock is in Henderson)."""
    ad = next(li for li in listings if li.listing_type is ListingType.TAX_LIEN)
    assert ad.county == "Henderson"


def test_out_of_footprint_row_is_dropped(rows):
    columbus = next(r for r in rows if r["county_meta"] == "Columbus")
    assert M._to_listing(columbus, _SLUG) is None


def test_every_listing_is_in_footprint_and_nc(listings):
    assert listings
    assert {li.county for li in listings} <= set(M.FOOTPRINT)
    assert {li.state for li in listings} == {"NC"}


# ------------------------------------------------------- classification ----

def test_classification_covers_all_three_categories(listings):
    by_type = {li.listing_type for li in listings}
    assert ListingType.FORECLOSURE_SALE in by_type   # substitute trustee sale
    assert ListingType.TAX_SALE in by_type           # county-plaintiff tax sale
    assert ListingType.TAX_LIEN in by_type           # NCGS 105-369 advertisement
    assert ListingType.PROBATE_NOTICE in by_type     # NCGS 28A-14-1 creditors
    assert ListingType.LIS_PENDENS in by_type        # action filed, no sale yet


def test_county_as_plaintiff_is_tagged_as_a_tax_action(listings):
    """'COUNTY OF BUNCOMBE, a Body Politic and Corporate, Plaintiff' is the NC
    in-rem tax-foreclosure caption — it must not fall through to a plain
    power-of-sale foreclosure."""
    tax = [li for li in listings if li.foreclosure_process == "tax"]
    assert len(tax) == 3
    assert all(li.listing_type in (ListingType.TAX_SALE, ListingType.TAX_LIEN,
                                   ListingType.LIS_PENDENS) for li in tax)
    sale = next(li for li in listings if li.listing_type is ListingType.TAX_SALE)
    assert sale.plaintiff and "Buncombe" in sale.plaintiff
    assert sale.defendant == "Roger Lunsford"


def test_plaintiff_does_not_swallow_the_caption_boilerplate():
    """Real Rutherford text. A permissive "anything before Plaintiff" pattern
    returned the whole caption; only the party may come back."""
    text = ("IN THE GENERAL COURT OF JUSTICE SUPERIOR COURT DIVISION BEFORE THE CLERK "
            "26 M 110 NOTICE OF DOCKETING TAX FORECLOSURE JUDGMENT STATE OF NORTH "
            "CAROLINA COUNTY OF RUTHERFORD RUTHERFORD COUNTY, Plaintiff, Vs. Larry "
            "Douglas, Jerome Douglas, Coretta Patricia Robinson Defendant(s) Pursuant to")
    m = M._PLAINTIFF_RE.search(text)
    assert m and M._tidy_name(m.group(1)) == "RUTHERFORD COUNTY"
    # Joint government plaintiffs stay intact.
    joint = ("FILE NO. 25 CVD 861 CITY OF MARION and MCDOWELL COUNTY, Plaintiffs, "
             "vs. JOHN GREGORY CLAYTON, ET AL., Defendants")
    m = M._PLAINTIFF_RE.search(joint)
    assert m and M._tidy_name(m.group(1)) == "CITY OF MARION and MCDOWELL COUNTY"


def test_power_of_sale_process_on_deed_of_trust_foreclosures(listings):
    saxe = next(li for li in listings if li.defendant and "Saxe" in li.defendant)
    assert saxe.listing_type is ListingType.FORECLOSURE_SALE
    assert saxe.foreclosure_process == "power_of_sale"


def test_non_lead_notices_are_dropped():
    for noise in (
        "NOTICE OF PUBLIC HEARING Notice is hereby given that the Buncombe County "
        "Board of Adjustment will hold a regular meeting on Wednesday.",
        "T & T MINI STORAGE will offer for sale the following units in Burke County.",
    ):
        assert M._classify(noise) is None


# ------------------------------------------------------------- fields ------

def test_estate_notice_carries_the_decedent_and_probate_signal(listings):
    estate = next(li for li in listings if li.listing_type is ListingType.PROBATE_NOTICE)
    assert estate.defendant == "Wanda Faye Wilson"
    assert estate.owner_name == "Wanda Faye Wilson"
    assert estate.raw["probate"]["decedent"] == "Wanda Faye Wilson"
    assert estate.raw["relationship_signal"]["kind"] == "probate"
    assert estate.street_address is None   # an estate notice names no property
    assert estate.sale_date is None


def test_case_numbers_are_captured(listings):
    cases = {li.case_number for li in listings if li.case_number}
    assert {"26SP000066-440", "26CV003253-100", "22CVD003028-100",
            "26SP000128-440"} <= cases


def test_deed_of_trust_book_page_is_captured_for_rod_lookup(listings):
    harvie = next(li for li in listings if li.defendant == "KAREN HARVIE")
    assert harvie.raw["public_notice"]["deed_of_trust"] == {"book": "2910", "page": "550"}


def test_source_url_points_at_the_notice(listings):
    for li in listings:
        assert li.source_url.startswith("https://www.ncnotices.com/Details.aspx?ID=")
        assert li.source_url.rsplit("=", 1)[1].isdigit()


def test_raw_flags_the_preview_as_truncated(listings):
    """The full body is reCAPTCHA-gated, so downstream must know these fields
    come from a ~300-char preview and are not authoritative-complete."""
    for li in listings:
        assert li.raw["public_notice"]["preview_truncated"] is True
        assert li.raw["public_notice"]["site"] == "ncnotices.com"


def test_publication_date_is_kept_both_raw_and_machine_readable(listings):
    harvie = next(li for li in listings if li.defendant == "KAREN HARVIE")
    pn = harvie.raw["public_notice"]
    assert pn["publication"] == "Beacon Tribune"
    assert pn["publication_date"] == "Thursday, July 30, 2026"
    assert pn["published_at"].startswith("2026-07-30")
    # The publisher's county is retained even when the subject county differs.
    assert pn["publication_county"] == "Buncombe" and harvie.county == "Henderson"


def test_address_parcel_and_sale_date_parse_when_present():
    """Rarely survives truncation live, but must work when the text has them."""
    row = pa.parse_grid(_FLAT)[0]
    li = M._to_listing(row, _SLUG)
    assert li is not None
    assert li.county == "McDowell"
    assert li.street_address == "118 Sycamore Lane"
    assert li.parcel_id == "1697-32-4455"
    assert li.sale_date is not None and li.sale_date.date().isoformat() == "2026-09-09"
    assert li.defendant == "JOHN Q PUBLIC"


# --------------------------------------------------------------- fetch -----

def test_fetch_dedupes_by_notice_id_across_pages(monkeypatch):
    """The same notice appears under more than one keyword; a lead must be
    emitted once."""
    html = _FIXTURE.read_text()

    async def _fake_render():
        return [html, html, html]

    monkeypatch.setattr(M, "_render_queries", _fake_render)
    out = asyncio.run(M.NCNoticesCounties().fetch())
    assert len(out) == 6   # 7 fixture rows, 1 out-of-footprint
    assert len({li.source_url for li in out}) == 6


def test_fetch_survives_a_render_that_returns_nothing(monkeypatch):
    async def _fake_render():
        return []

    monkeypatch.setattr(M, "_render_queries", _fake_render)
    assert list(asyncio.run(M.NCNoticesCounties().fetch())) == []


def test_scraper_is_registered_and_shaped_like_its_siblings():
    from foreclosure_scraper.scrapers._registry import discover

    cls = next(c for c in discover() if c.slug == _SLUG)
    assert cls.category == "public_notices"
    assert cls.timeout_s >= 600      # 11 county postbacks + 4 paged queries
    assert cls.expected_min_count == 0
