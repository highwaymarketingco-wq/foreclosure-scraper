"""Tests for enrichment_notice_service_defect -- Dirty Deeds Tier B #30.

"Assessor owner-name search used as a notice-defect weapon." Fixtures below are
modeled on real rows pulled live from the board 2026-09-29 (board_stream.
iter_board_rows, read-only scratch probe, not committed) -- same
plaintiff/defendant/description/raw shapes as the actual
public_notices.nc_notices_counties rows for Buncombe 26CV002591-100 (JAMES
DAYTON PLEMMONS) and 26CV004293-100 (DAVID EARL WISE, no resolved address
anywhere on the board today).
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_notice_service_defect import (
    enrich_notice_service_defect,
)
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import RAW_KEEP

_SOP_DESC = (
    "NOTICE OF SERVICE OF PROCESS BY PUBLICATION STATE OF NORTH CAROLINA "
    "BUNCOMBE COUNTY In the General Court of Justice, District Court Division, "
    "26CV002591-100 COUNTY OF BUNCOMBE, a Body Politic and Corp"
)


def _sop_row(defendant, case_number, county="Buncombe", state="NC",
             street_address=None, owner_mailing=None, resolved_from_name=None,
             description=_SOP_DESC, plaintiff="COUNTY OF BUNCOMBE",
             source="public_notices.nc_notices_counties"):
    raw = {}
    if owner_mailing is not None:
        raw["owner_mailing"] = owner_mailing
    if resolved_from_name is not None:
        raw["resolved_from_name"] = resolved_from_name
    return Listing(
        source=source, source_url=f"https://www.ncnotices.com/Details.aspx?ID={case_number}",
        listing_type=ListingType.LIS_PENDENS, state=state, county=county,
        plaintiff=plaintiff, defendant=defendant, owner_name=defendant,
        case_number=case_number, street_address=street_address,
        description=description, raw=raw,
    )


def test_real_case_same_row_owner_mailing_is_flagged():
    # JAMES DAYTON PLEMMONS, Buncombe 26CV002591-100 -- real live board shape:
    # served by publication, but owner_mailing already resolved his own tax
    # mailing address at a nearby address on the same street.
    row = _sop_row(
        "JAMES DAYTON PLEMMONS", "26CV002591-100",
        street_address="101 STATE ST",
        owner_mailing={"mailing": "103 W STATE ST BLACK MTN NC 28711",
                        "absentee": True, "mail_state": "NC", "out_of_state": False},
    )
    stats = enrich_notice_service_defect([row])
    assert stats["tagged"] == 1
    assert stats["same_row_hit"] == 1
    d = row.raw["notice_service_defect"]
    assert d["defendant"] == "JAMES DAYTON PLEMMONS"
    assert d["evidence_source"] == "same_row"
    assert d["resolved_via"] == "owner_mailing"
    assert d["resolved_address"] == "103 W STATE ST BLACK MTN NC 28711"
    assert d["case_number"] == "26CV002591-100"
    assert "publication" in d["service_language_matched"].lower()


def test_sibling_row_with_no_address_of_its_own_is_caught_by_cross_board_scan():
    # The board's merge/dedup sometimes lands the SAME case on two rows: one
    # with the notice text, one with the resolved address (real live shape,
    # same case_number, both public_notices.nc_notices_counties). Neither row
    # alone has both halves; the join must catch it across rows.
    sop_row = _sop_row("JAMES DAYTON PLEMMONS", "26CV002591-100")
    resolved_row = _sop_row(
        "JAMES DAYTON PLEMMONS", "26CV002591-100",
        street_address="101 STATE ST",
        owner_mailing={"mailing": "103 W STATE ST BLACK MTN NC 28711", "absentee": True},
        description="",  # this sibling row carries no notice text itself
    )
    stats = enrich_notice_service_defect([sop_row, resolved_row])
    assert stats["tagged"] == 1
    assert stats["cross_board_hit"] == 1
    assert sop_row.raw["notice_service_defect"]["evidence_source"] == "cross_board"
    assert "notice_service_defect" not in (resolved_row.raw or {})


def test_no_resolved_address_anywhere_leaves_it_untagged():
    # DAVID EARL WISE, Buncombe 26CV004293-100 -- real live board shape: served
    # by publication, no owner_mailing/resolved_from_name/address anywhere on
    # the board yet. Must not fabricate a hit.
    row = _sop_row(
        "DAVID EARL WISE", "26CV004293-100",
        description=(
            "NOTICE OF SERVICE OF PROCESS BY PUBLICATION STATE OF NORTH CAROLINA "
            "BUNCOMBE COUNTY In the General Court of Justice, District Court "
            "Division, 26CV004293-100 COUNTY OF BUNCOMBE, a Body Politic and Corp"
        ),
    )
    stats = enrich_notice_service_defect([row])
    assert stats["tagged"] == 0
    assert stats["no_evidence_yet"] == 1
    assert "notice_service_defect" not in (row.raw or {})


def test_generic_unknown_heirs_defendant_is_excluded():
    # Real live board shape (Carteret 25CV002175-150): the county not knowing
    # WHO an heir is is not a "this real person was locatable" claim.
    row = _sop_row(
        "Any unknown HEIRS", "25CV002175-150", county="Carteret",
        plaintiff="COUNTY OF CARTERET",
        owner_mailing={"mailing": "-", "absentee": False},
        description=(
            "NOTICE OF SERVICE OF PROCESS BY PUBLICATION NORTH CAROLINA CARTERET "
            "COUNTY IN THE GENERAL COURT OF JUSTICE DISTRICT COURT DIVISION FILE "
            "NO. 25CV002175-150 COUNTY OF CARTERET"
        ),
    )
    stats = enrich_notice_service_defect([row])
    assert stats["tagged"] == 0
    assert stats["generic_party_skipped"] == 1
    assert "notice_service_defect" not in (row.raw or {})


def test_favorable_resolved_from_name_counts_as_evidence():
    row = _sop_row(
        "RONALD A. MAXWELL", "26CV003997-100",
        resolved_from_name={
            "queried": True, "county": "Buncombe", "state": "NC",
            "strategy": "gis_owner_name_search", "confidence": "strong",
            "matched_owner": "MAXWELL RONALD A",
        },
    )
    stats = enrich_notice_service_defect([row])
    assert stats["tagged"] == 1
    d = row.raw["notice_service_defect"]
    assert d["resolved_via"] == "resolved_from_name"
    assert d["resolver_confidence"] == "strong"


def test_no_match_resolved_from_name_is_not_evidence():
    # confidence "no_match" means the resolver tried and found nothing -- the
    # opposite of the claim this module makes; must not be read as a hit. Real
    # live board shape (Craven 26CV000728-240 carries this exact confidence,
    # just on a generic-heirs name -- this test uses a real individual name so
    # the no_match path itself is exercised, not shadowed by that guard).
    row = _sop_row(
        "MICHAEL CARLAND RODGERS", "26CV003847-100", county="Buncombe",
        resolved_from_name={
            "queried": True, "county": "Buncombe", "state": "NC",
            "strategy": "gis_owner_name_search", "confidence": "no_match",
            "query_name": "MICHAEL CARLAND RODGERS",
        },
    )
    stats = enrich_notice_service_defect([row])
    assert stats["tagged"] == 0
    assert stats["no_evidence_yet"] == 1


def test_no_gov_plaintiff_is_not_a_tax_foreclosure_shape():
    # A bank/private plaintiff power-of-sale notice is not this module's
    # claim, even if it happened to say "service by publication" somewhere.
    row = _sop_row(
        "JOHN Q PUBLIC", "26SP000123-100", plaintiff="ACME MORTGAGE LLC",
        description="Substitute Trustee sale, service by publication attempted",
    )
    stats = enrich_notice_service_defect([row])
    assert stats["tagged"] == 0
    assert stats["candidate_rows"] == 0


def test_no_publication_language_is_not_tagged():
    row = _sop_row(
        "JOHN Q PUBLIC", "26CV000999-100",
        description="COUNTY OF BUNCOMBE vs JOHN Q PUBLIC, personal service completed",
        owner_mailing={"mailing": "1 MAIN ST ASHEVILLE NC 28801"},
    )
    stats = enrich_notice_service_defect([row])
    assert stats["tagged"] == 0
    assert stats["candidate_rows"] == 0


def test_sc_row_is_skipped_even_with_gov_plaintiff_and_publication_text():
    # SC's tax sale is administrative -- no lawsuit, no service event -- so
    # this module never tags an SC row even if the shape is superficially the
    # same (defense in depth, same style as the state gate in
    # enrichment_divorce_no_subsequent_deed.py).
    row = _sop_row(
        "JANE DOE REAL PERSON", "2026-CP-40-00123", county="Spartanburg",
        state="SC", plaintiff="COUNTY OF SPARTANBURG",
        description="NOTICE OF SERVICE OF PROCESS BY PUBLICATION COUNTY OF SPARTANBURG",
        owner_mailing={"mailing": "9 ELM ST SPARTANBURG SC 29301"},
    )
    stats = enrich_notice_service_defect([row])
    assert stats["tagged"] == 0
    assert stats["sc_skipped"] == 1
    assert "notice_service_defect" not in (row.raw or {})


def test_raw_key_is_registered_in_raw_keep():
    assert "notice_service_defect" in RAW_KEEP
