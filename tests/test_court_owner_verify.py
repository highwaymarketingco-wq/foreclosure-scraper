"""enrichment_court_owner_verify.py — wrong-PARCEL guard for court-sourced leads, plus the
stale-flag-on-merge fix (2026-10-03).

Original mechanism (pre-existing, covered here for the first time — this module had zero
dedicated tests before): a CourtListener / lis_pendens / bankruptcy lead carries a real docket
`defendant`; if the GIS-resolved `owner_name` doesn't contain the defendant's surname at all, the
geo-snap almost certainly attached the WRONG parcel. On a clear mismatch the function strips the
mis-attached property fields, reverts owner_name to the docket defendant, and records
raw['owner_mismatch'] = {defendant_surname, snapped_owner}.

STALE-FLAG-ON-MERGE bug fixed in this commit, live-verified on the real board (see module
docstring): Listing.merge() is fill-only (models.py) — it never overwrites a non-falsy field, so a
listing this function already flagged+stripped while it WAS court-sourced can later merge with an
unrelated non-court record for the "same" property (matched by address once parcel_id was cleared)
and keep BOTH the non-court record's own owner_name/defendant/listing_type/source (none of them
were falsy, so merge never touched them) AND the orphaned raw['owner_mismatch'] key from the old
court-side raw (raw is deep-merged, so no key is ever dropped by a merge). Live example: a row
published as tax_lien/counties_generic.arcgis_distress.buncombe_unpaid_bills with
owner_name == defendant == "BUCKNER (LE), CHRISTOPHER" still carried
owner_mismatch={"defendant_surname": "craft", "snapped_owner": "VALDEZ MELISSA KATRINA;VALDEZ JOE"}
— two people unrelated to the row's current identity, still surfaced verbatim as a MEDIUM red flag
by scripts/build_red_flags.py. Fix: once a listing no longer qualifies as court-sourced, the
function now clears ITS OWN flag shape (2 keys, no 'source') instead of silently skipping the row.
promote_ptscloud_block.py's Henderson PTS flag (3 keys, always carries 'source') is a separate,
still-valid mechanism and must never be touched by this clearing logic.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_court_owner_verify import (
    _def_surname,
    enrich_court_owner_verify,
)
from foreclosure_scraper.models import Listing, ListingType


def _li(*, source="national.courtlistener.scrape", listing_type=ListingType.LIS_PENDENS,
        owner_name="INMAN, ROBERT", defendant="Roger Leonard Mason", raw=None, **extra):
    return Listing(source=source, source_url="http://x", listing_type=listing_type,
                   owner_name=owner_name, defendant=defendant, raw=raw or {}, **extra)


# --------------------------------------------------------------------------------- surname parsing

def test_def_surname_last_first_comma():
    assert _def_surname("Williams, Joseph") == "williams"


def test_def_surname_first_middle_last():
    assert _def_surname("Roger Leonard Mason Jr") == "mason"


def test_def_surname_empty_when_undeterminable():
    assert _def_surname("") == ""
    assert _def_surname("LLC Trust") == ""  # pure suffix/entity tokens -> nothing left


# --------------------------------------------------------------------------------- gating

def test_non_court_source_and_type_never_checked():
    li = _li(source="counties_nc.gaston_vacant", listing_type=ListingType.DISTRESSED,
              owner_name="SMITH, JOHN", defendant="Totally Different Person")
    stats = enrich_court_owner_verify([li])
    assert stats["checked"] == 0
    assert stats["mismatch"] == 0
    assert li.raw.get("owner_mismatch") is None
    assert li.owner_name == "SMITH, JOHN"  # untouched


def test_bankruptcy_listing_type_is_gated_even_with_other_source():
    li = _li(source="counties_sc.some_scraper", listing_type=ListingType.BANKRUPTCY,
              owner_name="INMAN, ROBERT", defendant="Roger Leonard Mason")
    stats = enrich_court_owner_verify([li])
    assert stats["checked"] == 1
    assert stats["mismatch"] == 1


# --------------------------------------------------------------------------------- match / no-op

def test_surname_present_is_left_alone():
    li = _li(owner_name="MASON, ROGER L", defendant="Roger Leonard Mason")
    stats = enrich_court_owner_verify([li])
    assert stats["checked"] == 1
    assert stats["mismatch"] == 0
    assert stats["stripped"] == 0
    assert li.owner_name == "MASON, ROGER L"
    assert "owner_mismatch" not in li.raw


def test_missing_owner_or_defendant_is_skipped_not_checked():
    li = _li(owner_name=None, defendant="Roger Leonard Mason")
    stats = enrich_court_owner_verify([li])
    assert stats["checked"] == 0
    li2 = _li(owner_name="INMAN, ROBERT", defendant=None)
    stats2 = enrich_court_owner_verify([li2])
    assert stats2["checked"] == 0


# --------------------------------------------------------------------------------- mismatch / strip

def test_mismatch_strips_property_and_reverts_owner_name():
    li = _li(owner_name="INMAN, ROBERT", defendant="Roger Leonard Mason",
             parcel_id="123", street_address="1 Atlas Ct", market_value=200000.0,
             assessed_value=180000.0, living_sqft=1500,
             raw={"gis": {"owner": "INMAN, ROBERT", "last_sale": "2020-01-01"}})
    stats = enrich_court_owner_verify([li])
    assert stats["checked"] == 1
    assert stats["mismatch"] == 1
    assert stats["stripped"] == 1
    assert li.owner_name == "Roger Leonard Mason"
    assert li.parcel_id is None
    assert li.street_address is None
    assert li.market_value is None
    assert li.assessed_value is None
    assert li.living_sqft is None
    assert li.raw["owner_mismatch"] == {"defendant_surname": "mason", "snapped_owner": "INMAN, ROBERT"}
    assert "court_owner_mismatch" in li.raw["qa_flags"]
    assert "owner" not in li.raw["gis"]
    assert "last_sale" not in li.raw["gis"]


def test_mismatch_falls_back_to_raw_gis_owner_when_owner_name_blank():
    li = _li(owner_name=None, defendant="Roger Leonard Mason",
              raw={"gis": {"owner": "INMAN, ROBERT"}})
    stats = enrich_court_owner_verify([li])
    assert stats["checked"] == 1
    assert stats["mismatch"] == 1
    assert li.raw["owner_mismatch"]["snapped_owner"] == "INMAN, ROBERT"


# --------------------------------------------------------------------------------- stale-flag-on-merge fix

def test_stale_own_flag_cleared_once_listing_merges_out_of_court_status():
    """The exact live-confirmed shape: a listing this function already flagged+stripped while it
    WAS court-sourced later presents as a plain tax_lien row (merge kept the tax side's own
    owner_name/defendant/listing_type/source, all non-falsy) but still carries the orphaned flag."""
    li = _li(source="counties_generic.arcgis_distress.buncombe_unpaid_bills",
             listing_type=ListingType.TAX_LIEN,
             owner_name="BUCKNER (LE), CHRISTOPHER", defendant="BUCKNER (LE), CHRISTOPHER",
             raw={"owner_mismatch": {"defendant_surname": "craft",
                                      "snapped_owner": "VALDEZ MELISSA KATRINA;VALDEZ JOE"},
                  "qa_flags": ["court_owner_mismatch", "some_other_flag"]})
    stats = enrich_court_owner_verify([li])
    assert stats["stale_cleared"] == 1
    assert "owner_mismatch" not in li.raw
    assert "court_owner_mismatch" not in li.raw["qa_flags"]
    assert "some_other_flag" in li.raw["qa_flags"]  # unrelated flags survive
    # current identity (tax lien's own fields) is completely untouched
    assert li.owner_name == "BUCKNER (LE), CHRISTOPHER"
    assert li.defendant == "BUCKNER (LE), CHRISTOPHER"


def test_ptscloud_flag_never_cleared_by_this_function():
    """promote_ptscloud_block.py's Henderson flag always carries a 'source' key and is a separate,
    still-valid mechanism -- must survive untouched on a non-court row."""
    li = _li(source="counties_generic.state_contamination.nc_ust_incidents",
             listing_type=ListingType.DISTRESSED,
             owner_name="PIT STOP 64", defendant="PIT STOP 64",
             raw={"owner_mismatch": {"defendant_surname": "goad",
                                      "snapped_owner": "BANNER, STEPHANIE L",
                                      "source": "nc_ptscloud_delinquent_tax"},
                  "qa_flags": ["court_owner_mismatch"]})
    stats = enrich_court_owner_verify([li])
    assert stats["stale_cleared"] == 0
    assert li.raw["owner_mismatch"]["source"] == "nc_ptscloud_delinquent_tax"
    assert "court_owner_mismatch" in li.raw["qa_flags"]


def test_no_stale_flag_present_on_non_court_row_is_a_quiet_noop():
    li = _li(source="counties_nc.gaston_vacant", listing_type=ListingType.DISTRESSED,
              owner_name="SMITH, JOHN", defendant="SMITH, JOHN", raw={})
    stats = enrich_court_owner_verify([li])
    assert stats["stale_cleared"] == 0
    assert "owner_mismatch" not in li.raw


def test_still_court_sourced_row_with_own_flag_is_revalidated_not_cleared():
    """A row that IS still court-sourced goes through the normal checked/mismatch path, never the
    stale-clear path, even if it already carries our own flag from a prior run."""
    li = _li(owner_name="INMAN, ROBERT", defendant="Roger Leonard Mason",
             raw={"owner_mismatch": {"defendant_surname": "mason", "snapped_owner": "INMAN, ROBERT"}})
    stats = enrich_court_owner_verify([li])
    assert stats["stale_cleared"] == 0
    assert stats["checked"] == 1
    assert stats["mismatch"] == 1  # recomputed fresh, still a real mismatch
