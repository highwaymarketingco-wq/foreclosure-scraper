"""SC quiet-tax-title constructive-service heir-naming publication.

Dirty Deeds Tier B #26 (docs/dirty_deeds_synthesis_2026-09-10.md): "Newspaper
legal-notice feed: creditor notices, and constructive-service publications in
quiet title and partition that name the heirs the plaintiff could not find."

Creditor notices (G.S. 28A-14-1 / SC Notice to Creditors) were already fully
built before this task -- both column_legal_notices.py's NC_ESTATE_TYPES lane
and public_notices/nc_notices_counties.py's `_PROBATE_RE` already emit
PROBATE_NOTICE leads from them. The gap closed here is the OTHER half: a
sub-type of Column's SC "Estate (Probate) Filings" noticetype is not an
ordinary Notice to Creditors at all but a tax-deed holder's S.C. Code Ann.
SS 15-11-10 to -50 action "to quiet tax title" against a deceased former
owner's heirs, constructively served because not every heir could be located.
The caption individually names every heir the plaintiff COULD identify
(exactly "somebody else's paid-for heir search, published") before falling
back to a generic "unknown Heirs-at-Law ... John Doe and Mary Roe" catch-all
for the rest.

Confirmed live 2026-09-29 against the real Column API (keyless, already
integrated -- see column_legal_notices.py's module docstring): 2 unique cases
(6 republished rows) across a 200-day, 15-county SC footprint scan. Rare, but
real, parseable, and free. The two fixtures below are the verbatim OCR body
text of those two real notices (Pickens County / Redrock Capital, LLC v.
Estate of Lonella B. McCracken et al., case 2026-CP-39-00250; Horry County /
LB Park, LLC v. Estate of Sadie L. Rush et al., case 2026-CP-26-04023).
"""
from pathlib import Path

from foreclosure_scraper.scrapers.newspapers import column_legal_notices as C

FIXTURES = Path(__file__).parent / "fixtures"
MCCRACKEN = (FIXTURES / "column_sc_quiet_title_pickens_mccracken.txt").read_text()
RUSH = (FIXTURES / "column_sc_quiet_title_horry_rush.txt").read_text()

ORDINARY_NOTICE_TO_CREDITORS = """
STATE OF SOUTH CAROLINA COUNTY OF ANDERSON IN THE PROBATE COURT
NOTICE TO CREDITORS Estate: John Q. Public Case Number: 2026-ES-04-00123
Date of Death: January 5, 2026
All persons having claims against the estate of the above named decedent are
required to present them within eight months.
Personal Representative: Jane Public Address: 123 Main St, Anderson, SC 29621
"""


def test_ordinary_notice_to_creditors_is_not_misclassified_as_quiet_title():
    # The common case under this SAME Column noticetype must return None, not
    # a false-positive quiet-title block.
    assert C._parse_sc_quiet_title(ORDINARY_NOTICE_TO_CREDITORS) is None


def test_mccracken_quiet_title_detected_with_case_and_plaintiff():
    r = C._parse_sc_quiet_title(MCCRACKEN)
    assert r is not None
    assert r["is_quiet_title"] is True
    assert r["case_number"] == "2026-CP-39-00250"
    assert r["plaintiff"] == "Redrock Capital, LLC"


def test_mccracken_property_address_and_parcel_extracted():
    r = C._parse_sc_quiet_title(MCCRACKEN)
    assert r["street_address"] == "101 South Fifth Street"
    assert r["county"] == "Pickens"
    assert r["parcel_id"] == "5019-15-63-3697"


def test_mccracken_both_co_owner_decedents_captured():
    # The property had two now-deceased co-owners (mother/son); both estates'
    # heirs are named as defendants, not just the first.
    r = C._parse_sc_quiet_title(MCCRACKEN)
    assert r["decedents"] == ["Lonella B. McCracken", "George Allen McCracken"]


def test_mccracken_named_heirs_extracted_without_institutional_codefendants():
    # The caption interleaves real heir names with a bank, a finance company
    # and a city as co-defendants -- only the person names must survive.
    r = C._parse_sc_quiet_title(MCCRACKEN)
    assert r["named_heirs"] == [
        "Linda Lister", "Brenda Waters", "Pamela Ann Anderson",
        "Veronica Wimpey", "Renee Elswick", "Junia Marie Johnson",
        "Steven D. Thomas", "April L. Barry",
    ]
    for institutional in ("Truist Bank", "Prime Acceptance Corp", "the City of Easley"):
        assert institutional not in r["named_heirs"]


def test_rush_quiet_title_heirs_include_a_jr_suffix():
    r = C._parse_sc_quiet_title(RUSH)
    assert r is not None
    assert r["case_number"] == "2026-CP-26-04023"
    assert r["plaintiff"] == "LB Park, LLC"
    assert r["street_address"] == "201 Long Avenue"
    assert r["county"] == "Horry"
    assert r["parcel_id"] == "339.08.01.0012"
    assert r["decedents"] == ["Sadie L. Rush"]
    assert r["named_heirs"] == ["Joseph Robert Rush, Jr", "Parks Edward Rush", "Robert R. Rush"]
    # A federal agency, a state agency and a hospital also appear as
    # co-defendants in this caption; none of them are heirs.
    for institutional in ("Conway Hospital", "Synchrony Bank", "Internal Revenue Service",
                          "South Carolina Department of Revenue"):
        assert institutional not in r["named_heirs"]


def test_sc_probate_listing_backfills_address_and_plaintiff_from_quiet_title():
    # This lane is address-less by design for an ordinary probate notice (the
    # owner-to-GIS enricher backfills downstream); a quiet-title notice is the
    # one sub-type that already carries a real address, parcel and plaintiff,
    # which must reach the Listing itself, not just raw.
    scraper = C.ColumnLegalNotices()
    it = {
        "id": "test-mccracken-0",
        "text": MCCRACKEN,
        "pdfurl": None,
        "publishedtimestamp": 1735689600000,
        "newspapername": "Test Paper",
        "filer": None,
        "noticetype": "Estate (Probate) Filings",
    }
    li = scraper._sc_probate_listing(it, "Pickens")
    assert li is not None
    assert li.street_address == "101 South Fifth Street"
    assert li.parcel_id == "5019-15-63-3697"
    assert li.plaintiff == "Redrock Capital, LLC"
    assert li.case_number == "2026-CP-39-00250"
    assert li.owner_name == "Lonella B. McCracken"
    assert li.county == "Pickens"
    assert "heir_naming_publication" in li.raw
    assert li.raw["heir_naming_publication"]["named_heirs"][0] == "Linda Lister"


def test_sc_probate_listing_ordinary_notice_has_no_heir_naming_publication_key():
    # An ordinary notice-to-creditors row must NOT carry the new raw key at
    # all (absence, not an empty/None value) -- downstream code that checks
    # `if raw.get("heir_naming_publication")` must see nothing for the
    # common case.
    scraper = C.ColumnLegalNotices()
    it = {
        "id": "test-ordinary-0",
        "text": ORDINARY_NOTICE_TO_CREDITORS,
        "pdfurl": None,
        "publishedtimestamp": 1735689600000,
        "newspapername": "Test Paper",
        "filer": None,
        "noticetype": "Estate (Probate) Filings",
    }
    li = scraper._sc_probate_listing(it, "Anderson")
    assert li is not None
    assert "heir_naming_publication" not in li.raw
    assert li.street_address is None
