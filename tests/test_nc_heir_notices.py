"""NC quiet-title / heir-naming notices (scrapers/public_notices/nc_heir_notices.py). All fixtures
are made up: names, parcels and case numbers do not exist."""
from __future__ import annotations

import asyncio
import time

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.public_notices import nc_heir_notices as m

QUIET_TITLE = (
    "NOTICE TO UNKNOWN HEIRS AND UNLOCATEABLE HEIRS  OF ADA TESTWORTH AKA ADA BELLE  "
    "This Notice is to inform all unknown and Unlocatable Heirs of Ada Testworth AKA Ada Belle, "
    "deceased late of Johnston County North Carolina of the Hearing to consider the Quiet Title "
    "Action under Johnston County File No: 25SP000999-500 regarding the real property, Parcel "
    "Identification Number 12-M-11-099-B. The hearing will be held on November 12, 2026 at 11:00 AM "
    "before the Johnston County Clerk of Superior Court. This is the 3rd day of September, 2026 "
    "Pat Lawyer Attorney for Petitioner 555-0100 The Example Times September 9, 16, 23, 2026")

TAX_FORECLOSURE = (
    "STATE OF NORTH CAROLINA COUNTY OF ROBESON COUNTY OF ROBESON, a political Subdivision of the "
    "State of North Carolina; VS. Plaintiff, HEIRS OF SAM EXAMPLETON (DECEASED: 07/13/2023),) "
    "TESS SAMPLE (DECEASED: 10/10/2005), ) IN THE GENERAL COURT OF JUSTICE DISTRICT COURT DIVISION "
    "NOTICE If they be deceased then their legal representatives, heirs and assigns; Defendants. "
    "Pursuant to the requirements of G.S. 105-375(c)(4)b, notice is hereby given to: HEIRS OF SAM "
    "EXAMPLETON (DECEASED: 07/13/2023), TESS SAMPLE (DECEASED: 10/10/2005) AND If they be deceased "
    "then their legal representatives, heirs and assigns; that a judgment of foreclosure will be "
    "docketed against the property described below PROPERTY DESCRIPTION Parcel #99100100301 Example "
    "Township, 1.0 acre ad valorem taxes")

LENDER_QUIET_TITLE = (
    "NOTICE OF SERVICE OF PROCESS BY PUBLICATION STATE OF NORTH CAROLINA SCOTLAND COUNTY IN THE "
    "SUPERIOR COURT FILE NO. 26CV000001-820 IN RE: EXAMPLE LOAN SERVICES, LLC, Plaintiff, vs. "
    "JANE ROE and JOHN ROE, Defendants. relief for declaratory judgment/quiet title, declaration "
    "of the validity of the deed of trust")

ORDINARY_FORECLOSURE = (
    "NOTICE OF FORECLOSURE SALE Under and by virtue of a deed of trust, Wake County 25SP001234-910. "
    "The deed of trust binds the heirs and assigns of the grantor. Substitute Trustee Example PLLC")


def test_quiet_title_hearing_notice_names_decedent_parcel_and_case():
    p = m.parse_nc_heir_notice(QUIET_TITLE, "Johnston")
    assert p["is_quiet_title"] is True and p["kind"] == "quiet_title"
    assert p["case_number"] == "25SP000999-500"
    assert p["county"] == "Johnston"
    assert p["parcel_id"] == "12-M-11-099-B"
    assert p["decedents"] == ["ADA TESTWORTH"]
    assert p["hearing_date"] == "2026-11-12"
    assert p["unknown_heirs"] is True
    assert m.emits_lead(p)


def test_tax_foreclosure_heirs_caption_lists_every_decedent_with_dates_of_death():
    p = m.parse_nc_heir_notice(TAX_FORECLOSURE, "Robeson")
    assert p["kind"] == "tax_foreclosure_heirs" and p["is_quiet_title"] is False
    assert p["decedents"] == ["SAM EXAMPLETON", "TESS SAMPLE"]
    assert p["died"] == ["2023-07-13", "2005-10-10"]
    assert p["county"] == "Robeson" and p["parcel_id"] == "99100100301"
    assert p["plaintiff"] == "County of Robeson"
    assert p["statute"] == "G.S. 105-375"


def test_lender_quiet_title_against_living_defendants_is_counted_but_not_a_lead():
    p = m.parse_nc_heir_notice(LENDER_QUIET_TITLE, "Scotland")
    assert p["is_quiet_title"] is True
    assert not p.get("decedents") and not p.get("parcel_id")
    assert not m.emits_lead(p)


def test_boilerplate_heirs_and_assigns_is_not_an_heir_notice():
    assert m.parse_nc_heir_notice(ORDINARY_FORECLOSURE, "Wake") is None
    assert m.parse_nc_heir_notice("", None) is None
    assert m.parse_nc_heir_notice(None, None) is None


def test_name_fragments_and_boilerplate_words_are_not_names():
    text = ("NOTICE heirs of Patrick V. Example, deceased, and Defendants TO appear. Parcel # 1234567 "
            "Wake County 26SP000001-910")
    p = m.parse_nc_heir_notice(text, "Wake")
    assert p["decedents"] == ["Patrick V. Example"]
    assert m._name("Defendants TO") is None and m._name("Single") is None
    assert m._drop_prefix_names(["Dottie L", "Dottie L. Vain"]) == ["Dottie L. Vain"]


def test_republished_notices_collapse_to_one_lead():
    p1 = m.parse_nc_heir_notice(QUIET_TITLE, "Johnston")
    p2 = m.parse_nc_heir_notice(QUIET_TITLE, "Johnston")
    assert m.dedupe_key(p1) == m.dedupe_key(p2)
    assert m.dedupe_key({"parcel_id": "9", "county": "Wake"}) != m.dedupe_key({"parcel_id": "8", "county": "Wake"})


def test_county_comes_from_the_caption_not_the_newspaper_tag():
    # Column tags a notice by the paper: a Robeson notice carried under an Anson tag stays Robeson
    p = m.parse_nc_heir_notice(TAX_FORECLOSURE, "Anson")
    assert p["county"] == "Robeson"
    assert m.county_of("no county named here", "Anson") == "Anson"
    assert m.county_of("no county named here", "Atlantis") is None


def test_listing_for_builds_a_probate_notice_with_the_sc_compatible_block():
    s = m.NcHeirNotices()
    item = {"id": "abc", "text": QUIET_TITLE, "county": "Johnston", "noticetype": "",
            "publishedtimestamp": int(time.time() * 1000), "pdfurl": "https://example.test/n.pdf",
            "newspapername": "The Example Times"}
    li = s.listing_for(item)
    assert li.listing_type == ListingType.PROBATE_NOTICE and li.state == "NC" and li.county == "Johnston"
    assert li.owner_name == "Ada Testworth" and li.defendant == "Ada Testworth"
    assert li.parcel_id == "12-M-11-099-B" and li.case_number == "25SP000999-500"
    hp = li.raw["heir_naming_publication"]
    assert hp["is_quiet_title"] is True and hp["decedents"] == ["ADA TESTWORTH"]
    assert li.raw["documents"] == ["https://example.test/n.pdf"]
    assert s.listing_for({"id": "x", "text": LENDER_QUIET_TITLE, "county": "Scotland"}) is None


def test_fetch_dedupes_republications_and_queries_each_term(monkeypatch):
    calls = []

    async def fake_query(c, search, from_ms, to_ms, depth=0):
        calls.append(search)
        now = int(time.time() * 1000)
        return [{"id": f"{search}-{i}", "text": QUIET_TITLE, "county": "Johnston", "publishedtimestamp": now}
                for i in range(2)] + [{"id": "tf", "text": TAX_FORECLOSURE, "county": "Robeson",
                                       "publishedtimestamp": now}]

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(m, "_query", fake_query)
    monkeypatch.setattr(m, "client", lambda **kw: _C())
    rows = list(asyncio.run(m.NcHeirNotices().fetch()))
    assert sorted(calls) == sorted(m.QUERIES)
    assert len(rows) == 2                      # one quiet-title case, one tax-foreclosure caption


def test_column_county_list_is_a_subset_of_nc_and_leaves_25_without_a_paper():
    from foreclosure_scraper.validation import NC_COUNTIES
    assert set(m.COLUMN_NC_COUNTIES) <= set(NC_COUNTIES)
    assert len(m.COLUMN_NC_COUNTIES) == 75 and len(set(NC_COUNTIES) - set(m.COLUMN_NC_COUNTIES)) == 25


def test_screen_ledger_credits_the_75_counties_for_both_columns():
    from foreclosure_scraper import screen_ledger as SL
    scr = [s for s in SL.DECLARED if s.slug == "public_notices.nc_heir_notices"]
    assert len(scr) == 1
    assert set(scr[0].columns) == {"heir_naming_publication", "quiet_title"}
    cov = scr[0].coverage()
    assert ("NC", "Johnston") in cov and ("NC", "Alleghany") not in cov and len(cov) == 75
