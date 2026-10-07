"""ncnotices.com title-clearing lanes: partition, quiet title, unknown heirs (2026-10-07).

Hand-written notice previews with made-up parties and case numbers, in the grid-row
shape `_press_assoc.parse_grid` produces (see tests/test_nc_notices_counties.py).
"""
from __future__ import annotations

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.public_notices import nc_notices_counties as M

_SLUG = "public_notices.nc_notices_counties"


def _row(text, county="Buncombe", nid="900001"):
    return {"notice_id": nid, "publication": "Sample Weekly", "date_text": "Wednesday, October 1, 2026",
            "published_at": None, "county_meta": county, "city_meta": "Asheville", "text": text}


QUIET_TITLE = ("STATE OF NORTH CAROLINA COUNTY OF BUNCOMBE IN THE GENERAL COURT OF JUSTICE "
               "SUPERIOR COURT DIVISION 26CVS009001-100 SAMPLE LAND COMPANY, LLC, Plaintiff, vs. "
               "The Unknown Heirs at Law of Jonah Q. Testperson, deceased, Defendants. NOTICE OF "
               "SERVICE OF PROCESS BY PUBLICATION. Take notice that a pleading seeking relief "
               "against you has been filed in the above action to quiet title to real property")
PARTITION = ("STATE OF NORTH CAROLINA COUNTY OF HENDERSON BEFORE THE CLERK 26SP000901-440 IN THE "
             "MATTER OF THE PARTITION OF REAL PROPERTY OF Mary Example, Petitioner, v. Robert "
             "Example and the unknown heirs of Ada Example, Respondents. NOTICE OF SERVICE BY "
             "PUBLICATION. A petition for partition by sale has been filed")
HEIRS_ONLY = ("STATE OF NORTH CAROLINA COUNTY OF POLK 26CVD000902-750 To: All persons claiming "
              "an interest in the lands of Placeholder Fiction, deceased, including his heirs at law. "
              "TAKE NOTICE that a pleading has been filed")
TAX_WITH_HEIRS = ("COUNTY OF RUTHERFORD, Plaintiff vs. the unknown heirs of Lee Sample, Defendants. "
                  "NOTICE OF SERVICE OF PROCESS BY PUBLICATION in an action to foreclose the "
                  "lien for delinquent taxes 26CVD000903-800")


def test_quiet_title_is_a_lis_pendens_naming_the_decedent_owner():
    li = M._to_listing(_row(QUIET_TITLE), _SLUG)
    assert li is not None
    assert li.listing_type == ListingType.LIS_PENDENS
    assert li.county == "Buncombe" and li.case_number == "26CVS009001-100"
    assert li.owner_name == "Jonah Q. Testperson"
    ta = li.raw["public_notice"]["title_action"]
    assert ta == {"kind": "quiet_title", "unknown_heirs": True, "decedent": "Jonah Q. Testperson"}
    assert li.raw["public_notice"]["kind"] == "quiet_title"


def test_partition_carries_the_partition_relationship_signal():
    li = M._to_listing(_row(PARTITION, county="Henderson", nid="900002"), _SLUG)
    assert li.listing_type == ListingType.LIS_PENDENS
    assert li.county == "Henderson"
    assert li.raw["public_notice"]["title_action"]["kind"] == "partition"
    assert li.raw["relationship_signal"]["kind"] == "partition"
    assert li.owner_name == "Ada Example"
    names = [s[0] for s in ds._signals_for(li)]
    assert "partition" in names and "lis_pendens" in names


def test_all_persons_claiming_counts_as_an_heirs_notice():
    li = M._to_listing(_row(HEIRS_ONLY, county="Polk", nid="900003"), _SLUG)
    assert li.listing_type == ListingType.LIS_PENDENS
    assert li.raw["public_notice"]["title_action"]["kind"] == "heirs"


def test_tax_suit_keeps_its_tax_classification_but_records_the_heirs():
    li = M._to_listing(_row(TAX_WITH_HEIRS, county="Rutherford", nid="900004"), _SLUG)
    assert li.raw["public_notice"]["kind"] == "tax_foreclosure"
    ta = li.raw["public_notice"]["title_action"]
    assert ta["kind"] == "heirs" and ta["decedent"] == "Lee Sample"


def test_rows_survive_scope_and_the_active_filter():
    li = M._to_listing(_row(QUIET_TITLE), _SLUG)
    assert main._in_scope(li)
    assert main._active_only(li, 120)


def test_new_queries_are_wired_and_mode_toggles_once():
    kws = [q[0] for q in M._QUERIES]
    for k in ("partition", "quiet title", "unknown heirs", "heirs at law"):
        assert k in kws
    modes = [q[1] for q in M._QUERIES]
    assert modes == sorted(modes, key=lambda m: m != "AND"), "all AND queries before the EXACT block"


def test_ordinary_notices_are_still_not_leads():
    assert M.title_action("Office partition wall bids due Friday at the county") is None
    assert M._classify("NOTICE OF PUBLIC HEARING on the budget") is None
