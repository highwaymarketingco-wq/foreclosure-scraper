"""court_signals audit 2026-10-09, coordinator decisions (made-up rows):

1. An NC Judgment Search claim of lien is its own type and signal (lien_claim), a transcript of
   judgment a judgment lien; only a lis pendens stays lis_pendens (scraper + the tail's retype of
   carried rows, enrichment_court_owner_verify.retype_court_lien).
2. An estate notice binds to a parcel only when the decedent (or the personal representative, on a
   property that is not the representative's own printed address) agrees with an owner of record by
   name; otherwise it is kept as an unbound county-level lead.
3. A bankruptcy filing binds to a parcel only when a debtor agrees with an owner of record that is
   not the case name copied.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.enrichment_court_owner_verify import (
    bankruptcy_binding,
    enrich_court_owner_verify,
    estate_binding,
    names_agree,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import _hit_to_listing


# ---- 1. the scraper and the retype ---------------------------------------------------------------

def _hit(cause):
    od = (datetime.utcnow() - timedelta(days=30)).isoformat()
    return {"caseNumber": "26M000001-350", "orderedDate": od, "judgmentType": "Recorded",
            "civilJudgmentStatus": "Active", "caseCategoryKey": "CV", "caseID": 1, "judgmentId": 2,
            "causeOfActionDesc": cause, "location": "Gaston District Court",
            "debtors": [{"name": "Doe, John"}], "creditors": [{"name": "Example Builders LLC"}]}


def test_scraper_types_claims_of_lien_as_lien_claim():
    for cause in ("CV - Claim of Lien", "CV - Lien"):
        li = _hit_to_listing(_hit(cause), "counties_nc.nc_ecourts_lis_pendens")
        assert li.listing_type == ListingType.LIEN_CLAIM
        assert li.raw["nc_ecourts"]["signal"] == "lien_claim"


def test_scraper_types_a_transcript_as_a_judgment_lien_and_keeps_lis_pendens():
    li = _hit_to_listing(_hit("CV - Transcript of Judgment"), "counties_nc.nc_ecourts_lis_pendens")
    assert li.listing_type == ListingType.DISTRESSED and li.raw["nc_ecourts"]["signal"] == "judgment_lien"
    for cause in ("CV - Lis Pendens", "CV - Condemnation"):
        li = _hit_to_listing(_hit(cause), "counties_nc.nc_ecourts_lis_pendens")
        assert li.listing_type == ListingType.LIS_PENDENS and "signal" not in li.raw["nc_ecourts"]


def _carried(cause, source="nc_ecourts_judgments"):
    return Listing(source=source, source_url="https://example.test/ec",
                   listing_type=ListingType.LIS_PENDENS, property_kind=PropertyKind.UNKNOWN,
                   state="NC", county="Gaston", case_number="25M000001-350", defendant="Doe, John",
                   owner_name="DOE JOHN", parcel_id="1234567890",
                   raw={"nc_ecourts": {"cause_of_action": cause, "civil_judgment_status": "Active"}})


def test_carried_rows_are_retyped_and_kept():
    rows = [_carried("CV - Claim of Lien"), _carried("CV - Transcript of Judgment"),
            _carried("CV - Lis Pendens")]
    s = enrich_court_owner_verify(rows)
    assert [r.listing_type for r in rows] == [ListingType.LIEN_CLAIM, ListingType.DISTRESSED,
                                             ListingType.LIS_PENDENS]
    assert rows[0].raw["retyped"]["from"] == "lis_pendens" and rows[0].parcel_id == "1234567890"
    assert s["retyped_lien_claim"] == 1 and s["retyped_judgment_lien"] == 1


# ---- the name rule ---------------------------------------------------------------------------------

def test_names_agree():
    assert names_agree("Jane Q. Doe", "DOE JANE Q")
    assert names_agree("DOE, JANE", "Jane Doe")
    assert names_agree("Jane Doe", "DOE JANE HEIRS; DOE JOHN")
    assert not names_agree("Jane Ann Doe", "DOE JANE L")            # middle initials conflict
    assert not names_agree("Mary Doe", "DOE JANE")                  # same surname, other person
    assert not names_agree("Jane Doe", "ROE JANE")
    assert names_agree("Example Holdings LLC", "EXAMPLE HOLDINGS LLC")


# ---- 2. estate notices ---------------------------------------------------------------------------

def _notice(owner, *, decedent="Jane Q. Doe", rep=None, rep_address=None, lt=ListingType.PROBATE_NOTICE,
            source="public_notices.example_notices", **raw_extra):
    raw = {"probate": {"decedent": decedent, "personal_representative": rep, "pr_address": rep_address},
           "gis": {"owner": owner}, "tax_owed": {"balance": 900.0}, **raw_extra}
    return Listing(source=source, source_url="https://example.test/n", listing_type=lt,
                   property_kind=PropertyKind.UNKNOWN, state="SC", county="Pickens",
                   parcel_id="5000-00-00-0001", street_address="12 Example Rd", owner_name=owner, raw=raw)


def test_estate_notice_on_the_decedents_parcel_stays():
    li = _notice("DOE JANE Q")
    assert estate_binding(li) == ("bound", "decedent_is_owner")
    enrich_court_owner_verify([li])
    assert li.parcel_id and "estate_unbound" not in li.raw


def test_estate_notice_on_the_representatives_own_house_is_unbound():
    li = _notice("ROE RICHARD", rep="Richard Roe", rep_address="12 Example Road")
    assert estate_binding(li) == ("unbound", "representative_own_address")
    s = enrich_court_owner_verify([li])
    assert li.parcel_id is None and li.street_address is None
    assert li.raw["estate_unbound"]["reason"] == "representative_own_address"
    assert "tax_owed" not in li.raw and "tax_owed" in li.raw["unbound_property_blocks"]
    assert li.raw["probate"]["decedent"] == "Jane Q. Doe"           # the notice itself is kept
    assert s["estate_unbound"] == 1


def test_representative_on_title_elsewhere_stays():
    li = _notice("ROE RICHARD", rep="Richard Roe", rep_address="77 Other St")
    assert estate_binding(li) == ("bound", "representative_on_title")


def test_estate_notice_on_a_strangers_parcel_is_unbound():
    li = _notice("SMITH ALPHA")
    assert estate_binding(li) == ("unbound", "decedent_not_owner_of_record")


def test_a_notice_merged_onto_another_sources_row_leaves_the_row():
    li = _notice("SMITH ALPHA", lt=ListingType.TAX_LIEN, source="counties_sc.example_tax",
                 relationship_signal={"kind": "probate", "keyword": "public_notice"})
    s = enrich_court_owner_verify([li])
    assert s["estate_block_unbound"] == 1
    assert "probate" not in li.raw and li.raw["probate_unbound"]["decedent"] == "Jane Q. Doe"
    assert "relationship_signal" not in li.raw
    assert li.parcel_id == "5000-00-00-0001" and "tax_owed" in li.raw   # the tax row is untouched


def test_heir_roll_rows_are_not_this_rules():
    li = _notice("SMITH ALPHA", source="counties_nc.nc_heir_estate_parcels", lt=ListingType.ESTATE_LEAD)
    assert estate_binding(li) is None


# ---- 3. bankruptcy filings -------------------------------------------------------------------------

def _filing(case_name, owner, roll_owner):
    return Listing(source="national.courtlistener_bankruptcy", source_url="https://example.test/d",
                   listing_type=ListingType.BANKRUPTCY, property_kind=PropertyKind.UNKNOWN,
                   state="NC", county="Gaston", parcel_id="1234567890", street_address="12 Example Rd",
                   owner_name=owner, defendant=case_name,
                   raw={"courtlistener": {"case_name": case_name}, "gis": {"owner": roll_owner}})


def test_a_debtor_who_owns_the_parcel_stays():
    li = _filing("Jane Q. Doe", "DOE JANE Q", "DOE JANE Q")
    assert bankruptcy_binding(li) == ("bound", "debtor_is_owner")


def test_a_same_surname_stranger_is_unbound():
    li = _filing("Mary Ann Doe and John Doe", "DOE ALPHA", "DOE ALPHA")
    assert bankruptcy_binding(li) == ("unbound", "debtor_not_owner_of_record")
    s = enrich_court_owner_verify([li])
    assert li.parcel_id is None and li.raw["bankruptcy_unbound_property"]["reason"] == "debtor_not_owner_of_record"
    assert s["bankruptcy_unbound"] == 1


def test_a_case_name_copied_into_owner_name_is_not_an_owner_of_record():
    li = _filing("Jane Q. Doe", "Jane Q. Doe", "ROE RICHARD")
    assert bankruptcy_binding(li) == ("unbound", "debtor_not_owner_of_record")
