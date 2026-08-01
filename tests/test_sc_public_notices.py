"""SC public-notices parser (scpublicnotices.com grid rows -> typed leads).

`tests/fixtures/sc_public_notices_grid.html` is a verbatim capture of five
`<table class="nested">` result blocks from the live county-filtered grid
(2026-07-31), so the shape assertions here track the real response.
"""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper.scrapers.counties_sc import sc_public_notices as M
from foreclosure_scraper.models import ListingType

_FIXTURE = Path(__file__).parent / "fixtures" / "sc_public_notices_grid.html"
#: The county each fixture block was filtered on, in document order.
_FIXTURE_FILTER_COUNTIES = ["Union", "Union", "Cherokee", "Pickens", "Oconee"]

# A realistic GridView results fragment (two rows: in-scope foreclosure + out-of-scope).
_GRID = """
<table id="ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1">
<tr><td>The Herald-Journal Sunday, June 21, 2026 City: Spartanburg County: Spartanburg</td>
<td>STATE OF SOUTH CAROLINA IN THE COURT OF COMMON PLEAS COUNTY OF SPARTANBURG SUMMONS AND NOTICE
OF FILING OF COMPLAINT (NON-JURY MORTGAGE FORECLOSURE). ACME BANK, Plaintiff, vs JOHN Q DOE, Defendant.
The property located at 123 OAK ST, Spartanburg SC is subject to foreclosure.</td>
<td><input name="x$GridView1$ctl03$btnView2" onclick="javascript:location.href='Details.aspx?SID=abc&amp;ID=626766';"/></td></tr>
<tr><td>The Sumter Item Sunday, June 21, 2026 City: Sumter County: Sumter</td>
<td>NOTICE OF SALE foreclosure in Sumter</td>
<td><input name="x$GridView1$ctl04$btnView2" onclick="javascript:location.href='Details.aspx?SID=abc&amp;ID=626700';"/></td></tr>
</table>
"""

_PROBATE = """
<table id="GridView1"><tr>
<td>The Item Friday, June 19, 2026 City: Union County: Union</td>
<td>NOTICE TO CREDITORS OF THE ESTATE OF MARY R SMITH, deceased. All persons having claims...</td>
<td><input name="x$GridView1$ctl03$btnView2" onclick="location.href='Details.aspx?SID=abc&amp;ID=999';"/></td></tr></table>
"""


def _fixture_rows() -> list[dict]:
    rows = M._parse_results(_FIXTURE.read_text())
    for row, county in zip(rows, _FIXTURE_FILTER_COUNTIES):
        row["filter_county"] = county
    return rows


def _row(county: str, text: str, notice_id: str = "1") -> dict:
    return {"county": county, "city": "", "date_text": "", "publication": "",
            "notice_id": notice_id, "text": text}


# --------------------------------------------------------------- grid parsing
def test_parse_results_extracts_rows():
    rows = M._parse_results(_GRID)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["county"] == "Spartanburg" and r0["city"] == "Spartanburg"
    assert r0["notice_id"] == "626766"
    assert "COMMON PLEAS" in r0["text"]


def test_parses_live_grid_fixture():
    rows = _fixture_rows()
    assert len(rows) == 5
    r0 = rows[0]
    assert r0["notice_id"] == "635353"
    assert r0["publication"] == "Union County News"      # from the bolded <strong>
    assert r0["date_text"] == "Wednesday, July 29, 2026"
    assert r0["county"] == "Union"
    # the "click 'view' to open the full text." trailer is stripped
    assert "click 'view'" not in r0["text"]


def test_all_fixture_rows_carry_county_metadata():
    """A filtered page populates County: on every row; a blank one means the
    filter silently failed and _render_category discards the page."""
    assert all(r["county"] for r in M._parse_results(_FIXTURE.read_text()))


# -------------------------------------------------------------------- typing
def test_in_scope_foreclosure_becomes_listing():
    rows = M._parse_results(_GRID)
    li = M._to_listing(rows[0], "4", "counties_sc.sc_public_notices")
    assert li is not None
    assert li.listing_type is ListingType.LIS_PENDENS   # summons/complaint = pre-foreclosure
    assert li.county == "Spartanburg" and li.state == "SC"
    assert li.defendant and "DOE" in li.defendant.upper()
    assert li.street_address and "OAK ST" in li.street_address.upper()


def test_out_of_scope_county_dropped():
    rows = M._parse_results(_GRID)
    assert M._to_listing(rows[1], "4", "counties_sc.sc_public_notices") is None  # Sumter not in scope


def test_sale_notice_classified_as_sale():
    li = M._to_listing(
        _row("Pickens", "MASTER'S SALE will be sold at public auction the property of X"), "4", "s")
    assert li.listing_type is ListingType.FORECLOSURE_SALE


def test_probate_creditor_notice():
    rows = M._parse_results(_PROBATE)
    li = M._to_listing(rows[0], "30", "s")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["relationship_signal"]["kind"] == "probate"
    assert li.defendant and "SMITH" in li.defendant.upper()


def test_probate_es_docket_captured_and_cp_number_not_mistaken_for_one():
    est = M._to_listing(
        _row("Union", "NOTICE TO CREDITORS Estate: JOHN A DOE Date of Death: March 2, 2026 "
                      "Case Number: 2026ES4200123 Personal Representative: Jane Doe "
                      "100 Elm St, Union SC 29379"), "30", "s")
    assert est.raw["probate"]["es_case_number"] == "2026-ES-42-00123"
    assert est.raw["probate"]["date_of_death"] == "March 2, 2026"
    assert est.raw["probate"]["personal_representative"] == "Jane Doe"
    assert est.street_address is None            # estate notices name no property

    civil = M._to_listing(
        _row("Union", "NOTICE TO CREDITORS OF THE ESTATE OF MARY SMITH, deceased. "
                      "See also 2025-CP-44-00475."), "30", "s")
    assert civil.case_number == "2025-CP-44-00475"
    assert civil.raw["probate"]["es_case_number"] is None


def test_single_estate_notice_parses_every_probate_field():
    """The one-estate-per-notice format (Pickens/Laurens) fits inside the preview."""
    li = M._to_listing(
        _row("Pickens", "Estate: John Robert Ledford Date of Death: 09/09/2025 "
                        "Case #2025ES3900707-2 Personal Representative: Lana Y. Cannon "
                        "1786 Hwy. 63 Homer, GA 30547 Attorney: N/A"), "23", "s")
    p = li.raw["probate"]
    assert li.defendant == "John Robert Ledford"
    assert p["decedent"] == "John Robert Ledford"
    assert p["date_of_death"] == "09/09/2025"
    assert p["personal_representative"] == "Lana Y. Cannon"
    assert p["pr_address"] == "1786 Hwy. 63 Homer, GA 30547"
    assert p["es_case_number"] == "2025-ES-39-00707"


def test_county_rollup_estate_notice_keeps_docket_without_inventing_a_decedent():
    """Spartanburg's Notice-to-Creditors is a roll-up whose decedent names fall
    past the preview cut, and Details.aspx is CAPTCHA-walled. Keep the lead and
    the ES docket; leave the name empty rather than guessing."""
    li = M._to_listing(
        _row("Spartanburg", "Case Number: 2026ES4200586 All persons having claims against the "
                            "following estates MUST file their claims on FORM #371ES with the "
                            "Probate Court of Spartanburg County, the address of which is 180 Magno"),
        "30", "s")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["probate"]["es_case_number"] == "2026-ES-42-00586"
    assert li.defendant is None
    assert li.raw["probate"]["decedent"] is None


def test_tax_categories_split_sale_from_lien():
    sale = _row("Oconee", "DELINQUENT TAX SALE. The following properties will be sold for taxes.")
    lien = _row("Oconee", "Notice of delinquent taxes owed to the county treasurer for 2025.")
    assert M._to_listing(sale, "26", "s").listing_type is ListingType.TAX_SALE
    assert M._to_listing(lien, "22", "s").listing_type is ListingType.TAX_LIEN


def test_mortgage_summons_surfacing_under_tax_category_is_not_a_tax_lien():
    """The 'Tax Sales' keyword bundle carries the bare words 'property' and
    'default', so it returns most of the county's mortgage foreclosures. Typing
    off the category would file them as tax liens."""
    li = M._to_listing(
        _row("Spartanburg", "STATE OF SOUTH CAROLINA COUNTY OF SPARTANBURG IN THE COURT OF "
                            "COMMON PLEAS C/A NO: 2026CP4203047 SUMMONS AND NOTICES (Non-Jury) "
                            "FORECLOSURE OF REAL ESTATE MORTGAGE LAKEVIEW LOAN SERVICING, "
                            "Plaintiff, vs. MICHAEL L LOVETT"), "26", "s")
    assert li.listing_type is ListingType.LIS_PENDENS
    assert li.defendant == "MICHAEL L LOVETT"


def test_estate_notice_under_a_tax_category_still_gets_probate_enrichment():
    """Overlapping keyword bundles mean an estate notice can first surface under
    Tax Sales; the probate signal must follow the refined type, not the category."""
    li = M._to_listing(
        _row("Laurens", "NOTICE TO CREDITORS OF THE ESTATE OF HAROLD B GREER, deceased. "
                        "All persons having claims against this estate..."), "26", "s")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["relationship_signal"]["kind"] == "probate"
    assert li.raw["probate"]["decedent"] == "HAROLD B GREER"
    assert li.foreclosure_process is None       # not a foreclosure or tax track


def test_storage_auction_under_tax_category_dropped():
    assert M._to_listing(
        _row("Spartanburg", "Public Sale Extra Space Storage will hold a public auction to sell "
                            "personal property described below belonging to those individuals "
                            "listed below at 1835 E. Main St"), "26", "s") is None


def test_defendant_survives_middle_initial_and_parenthetical():
    li = M._to_listing(
        _row("Spartanburg", "STATE OF SOUTH CAROLINA COUNTY OF SPARTANBURG IN THE COURT OF "
                            "COMMON PLEAS C.A. No.: 2026-CP-42-02983 AAMG FC Properties, LLC, "
                            "Plaintiff, vs. Betty M. Williams (deceased), any Heirs at Law"),
        "26", "s")
    assert li.plaintiff == "AAMG FC Properties, LLC"
    assert li.defendant == "Betty M. Williams"


def test_public_sale_reading_as_mortgage_foreclosure_is_retyped():
    li = M._to_listing(_row("Laurens", "NOTICE OF SALE by virtue of a decree of foreclosure of the "
                                       "mortgage, the property will be sold at public auction."),
                       "27", "s")
    assert li.listing_type is ListingType.FORECLOSURE_SALE


def test_public_sale_of_real_property_stays_auction():
    li = M._to_listing(
        _row("Laurens", "PUBLIC SALE the County will offer for sale all that certain lot or "
                        "parcel of land containing 2.4 acres"), "27", "s")
    assert li.listing_type is ListingType.AUCTION


def test_public_sale_with_no_property_nexus_dropped():
    assert M._to_listing(
        _row("Laurens", "PUBLIC SALE of surplus county equipment at the maintenance yard."),
        "27", "s") is None


def test_general_civil_litigation_dropped():
    """Class actions and construction-defect impleaders publish summonses that
    look structurally like a foreclosure summons."""
    for text in (
        "STATE OF SOUTH CAROLINA COUNTY OF ANDERSON DEREK WILLIAMS, INDIVIDUALLY, AND ON "
        "BEHALF OF ALL OTHERS SIMILARLY SITUATED, Plaintiffs, vs. LONG HEATING & AIR",
        "STATE OF SOUTH CAROLINA COUNTY OF ANDERSON CIVIL ACTION NO: 2025CP0402216 "
        "THIRD-PARTY SUMMONS TO THIRD-PARTY DEFENDANTS: JOSE FIDEL ESPINAL",
    ):
        assert M._to_listing(_row("Anderson", text), "4", "s") is None, text


# --------------------------------------------------------------- noise gating
def test_personal_property_notices_dropped():
    for text in (
        "Notice of Sale Richard Johnson owner of a 2016 Harley Davidson Vin# 1HD4CR215GC448115",
        "NOTICE OF SALE contents of storage unit A12 at Palmetto Self Storage will be sold",
        "NOTICE OF APPLICATION intends to apply for a permit for the sale of Beer and Wine",
    ):
        assert M._to_listing(_row("Union", text), "27", "s") is None, text


def test_family_court_notice_dropped():
    """The Foreclosures keyword list includes 'judgment', which drags in DSS
    family-court matters — they are not property leads."""
    row = _fixture_rows()[4]
    assert "FAMILY COURT" in row["text"].upper()
    assert M._to_listing(row, "4", "s") is None


# ------------------------------------------------------------- field parsing
def test_sale_notice_fields_from_live_row():
    li = M._to_listing(_fixture_rows()[0], "4", "s")
    assert li.listing_type is ListingType.FORECLOSURE_SALE
    assert li.county == "Union"
    assert li.plaintiff == "PennyMac Loan Services, LLC"
    assert li.defendant == "Jeniya Martin"
    assert li.case_number == "2026-CP-44-00017"
    assert li.sale_date is not None and li.sale_date.date().isoformat() == "2026-08-03"
    assert li.sale_time == "11:00 AM"
    assert li.sale_location == "Union County Courthouse"
    assert li.foreclosure_process == "judicial"


def test_summons_row_keeps_parties_out_of_the_caption():
    """A greedy plaintiff match would otherwise swallow 'COUNTY OF UNION Case No.
    ... AMENDED SUMMONS'."""
    li = M._to_listing(_fixture_rows()[1], "4", "s")
    assert li.listing_type is ListingType.LIS_PENDENS
    assert li.plaintiff == "Founders Federal Credit Union"
    assert li.defendant == "Jessie D. Sanders"      # not truncated at the middle initial
    assert li.case_number == "2025-CP-44-00486"


def test_run_together_case_number_is_normalized():
    li = M._to_listing(_fixture_rows()[3], "4", "s")
    assert li.case_number == "2026-CP-39-00741"     # source reads "C/A NO: 2026CP3900741"
    assert li.plaintiff == "CARRINGTON MORTGAGE SERVICES LLC"
    assert li.defendant == "JAMES CARTER AYERS"


def test_despaced_case_number_still_matches():
    assert M._case_number("DOCKETNO.2024CP100003") == ("2024-CP-10-00003", "10")


def test_filter_county_beats_publication_county():
    """Row County: is the newspaper's county; the filtered county is the
    notice's subject county and must win."""
    row = _fixture_rows()[2]
    assert row["county"] == "Cherokee"
    li = M._to_listing(dict(row, county="Greenville"), "4", "s")
    assert li.county == "Cherokee"
    assert li.raw["public_notice"]["publication_county"] == "Greenville"


def test_county_code_mismatch_recorded_not_silently_applied():
    row = dict(_fixture_rows()[0], filter_county="Laurens")   # case number says Union (44)
    li = M._to_listing(row, "4", "s")
    assert li.county == "Laurens"
    assert li.raw["public_notice"]["county_code_mismatch"] == {
        "assigned": "Laurens", "case_number_implies": "Union"}


def test_parcel_id_requires_a_plausible_tms():
    good = _row("Union", "MASTER'S SALE all that certain lot of real estate, "
                         "TMS No. 7-16-04-012.00, will be sold")
    short = _row("Union", "MASTER'S SALE all that certain lot of real estate, "
                          "Parcel No. 12-3456, will be sold")
    assert M._to_listing(good, "4", "s").parcel_id == "7-16-04-012.00"
    assert M._to_listing(short, "4", "s").parcel_id is None


def test_publication_metadata_recorded():
    li = M._to_listing(_fixture_rows()[0], "4", "s")
    pn = li.raw["public_notice"]
    assert pn["publication"] == "Union County News"
    assert pn["published_date"] == "2026-07-29"
    assert pn["category_label"] == "Foreclosures"
    # Details.aspx is CAPTCHA-walled, so every body here is the grid preview.
    assert pn["text_truncated"] is True


# ---------------------------------------------------- category de-duplication
def test_duplicate_keyword_categories_collapse():
    """'Delinquent Taxes' and 'Tax Sales' currently ship the same canned keyword
    string, so only the first is run."""
    kept = M._distinct_categories({"4": "foreclosure kw", "26": "tax kw", "22": "tax kw",
                                   "27": "public kw", "30": "probate kw", "23": "probate kw"})
    assert kept == ["4", "26", "27", "30"]


def test_unharvested_categories_are_still_run():
    assert M._distinct_categories({"4": "foreclosure kw"}) == list(M._CATEGORIES)


def test_no_keywords_falls_back_to_all_categories():
    assert M._distinct_categories({}) == list(M._CATEGORIES)


def test_every_task_category_is_wired():
    """Foreclosures, Tax Sales, Delinquent Taxes, Public sales, Notice to
    Creditors, Probate Notices — the site's popular-search ids."""
    assert set(M._CATEGORIES) == {"4", "26", "22", "27", "30", "23"}
    assert set(M._COUNTIES) == {c.title() for c in M._IN_SCOPE}
