"""Address synthesis never takes a court, clerk or attorney office named in a notice as the
property's address (2026-10-06).

THE BUG THIS PINS (replay of main.run()'s second dedupe on the 10/5 checkpoint)
    Column's SC probate notices are address-less by design. The final synthesis pass took the
    first address-shaped string of the notice text, and in a Florence "Notice to Creditors" that is
    the probate court: "... file their claims ... with the Probate Court of FLORENCE County, The
    Honorable <judge>, the address of which is 181 N IRBY ST, STE 1300 FLORENCE SC 29501". Every
    Florence estate then read '181 N IRBY ST'; a published copy also had the parcel cache resolve
    that to the county's own building (parcel 9016701008, owner COUNTY OF FLORENCE) and a geocode
    of the courthouse. dedupe() merged 11 different estates on it (same real house number).

Notice text is the real structure from that checkpoint; decedent and judge names are replaced.
"""
from __future__ import annotations

from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.enrichment_address_final import (
    _repeated_notice_addresses, _synth_for_listing, enrich_with_address_synthesis,
    office_address_at, ADDR_RE,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def florence(decedent: str, case: str) -> str:
    return (f"NOTICE TO CREDITORS IN THE PROBATE COURT STATE OF SOUTH CAROLINA COUNTY OF: FLORENCE "
            f"CASE NUMBER: {case} IN THE MATTER OF: {decedent} (Decedent) *NOTICE TO CREDITORS OF "
            "ESTATES All persons having claims against the following estates MUST file their "
            "claims on FORM #371PC with the Probate Court of FLORENCE County, The Honorable JOHN Q "
            "JUDGE, JR., the address of which is 181 N IRBY ST, STE 1300 FLORENCE SC 29501, within "
            "eight (8) months after the date of the first publication of this Notice")


ESTATES = [("JANE ANN DOE", "2026ES2109725"), ("RICHARD ROE", "2026ES2109726"),
           ("MAREN P SAMPLE", "2026ES2109604"), ("GLENNA B TESTER", "2026ES2109570"),
           ("SUMMER K EXAMPLE", "2026ES2109562")]


def _notice(n, decedent, case, *, county="Florence", state="SC", desc=None, **kw):
    return Listing(source="counties.column_legal_notices",
                   source_url=f"https://example.test/column#{n}",
                   listing_type=ListingType.PROBATE_NOTICE, property_kind=PropertyKind.UNKNOWN,
                   state=state, county=county, owner_name=decedent, defendant=decedent,
                   case_number=case, description=(desc or florence(decedent, case))[:500],
                   raw={f"_rid_{n}": 1, **kw.pop("raw", {})}, **kw)


def test_the_court_named_in_the_notice_is_an_office():
    t = florence(*ESTATES[0])
    m = ADDR_RE.search(t)
    assert m.group(1) == "181 N IRBY ST"
    assert office_address_at(t, m.start(1), m.end(1))


def test_synthesis_skips_the_court_address():
    li = _notice(1, *ESTATES[0])
    assert _synth_for_listing(li) == "JANE ANN DOE — 2026ES2109725"


def test_five_florence_estates_stay_five_rows():
    rows = [_notice(i, d, c) for i, (d, c) in enumerate(ESTATES)]
    enrich_with_address_synthesis(rows)
    assert not any("IRBY" in (li.street_address or "") for li in rows)
    assert len(dedupe(rows)) == 5


def test_a_published_copy_carrying_the_court_address_is_repaired():
    """The 10/5 published row: synthesized '181 N IRBY ST', resolved to the county building's
    parcel by the parcel cache, geocoded to the courthouse."""
    d, c = ESTATES[0]
    pub = _notice(9, d, c, street_address="181 N IRBY ST", parcel_id="9016701008",
                  latitude=34.199201364212, longitude=-79.768402599928,
                  raw={"geo_imprecise": "census_geocode",
                       "parcel_from_address": {"source": "parcel_cache_situs_address",
                                               "matched_situs": "181 N IRBY ST",
                                               "cache_owner": "COUNTY OF FLORENCE",
                                               "cache_ids": ["9016701008"]}})
    others = [_notice(i, d2, c2) for i, (d2, c2) in enumerate(ESTATES[1:], 1)]
    rows = [pub] + others
    enrich_with_address_synthesis(rows)
    assert pub.street_address == "JANE ANN DOE — 2026ES2109725"
    assert pub.parcel_id is None and pub.latitude is None and pub.longitude is None
    assert pub.raw["parcel_from_address"]["withdrawn_parcel"] == "9016701008"
    assert pub.raw["address_not_property"]["address"] == "181 N IRBY ST"
    assert pub.raw["address_not_property"]["reason"] == "office_named_in_notice"
    assert "geo_imprecise" not in pub.raw
    assert len(dedupe(rows)) == 5
    # the fresh copy of the same estate still finds it (case number)
    rows.append(_notice(20, d, c))
    enrich_with_address_synthesis(rows)
    assert len(dedupe(rows)) == 5


def test_an_address_in_three_unrelated_notices_of_one_county_is_not_a_property():
    """No office cue at all, just the same firm address at the foot of three estates' notices."""
    desc = ("Estate of {d}. All persons having claims should present them to Smith Jones, "
            "100 W Main St, Gaffney SC by the date below.")
    rows = [_notice(i, d, c, county="Cherokee", desc=desc.format(d=d))
            for i, (d, c) in enumerate(ESTATES[:3])]
    assert _repeated_notice_addresses(rows) == {("SC", "cherokee", "100 w main st"): 3}
    enrich_with_address_synthesis(rows)
    assert not any((li.street_address or "").startswith("100 ") for li in rows)
    # two notices are not enough to call it an office
    two = [_notice(i, d, c, county="Cherokee", desc=desc.format(d=d))
           for i, (d, c) in enumerate(ESTATES[:2])]
    enrich_with_address_synthesis(two)
    assert all(li.street_address == "100 W Main St" for li in two)


def test_the_same_notice_republished_counts_once():
    d, c = ESTATES[0]
    desc = f"Estate of {d}. Claims to Smith Jones, 100 W Main St, Gaffney SC."
    rows = [_notice(i, d, c, county="Cherokee", desc=desc) for i in range(4)]
    assert _repeated_notice_addresses(rows) == {}


def test_the_decedents_own_address_is_still_taken():
    """NC estate notices name the decedent's residence ('late of'), which is the property."""
    desc = ("NOTICE TO CREDITORS AND DEBTORS OF JANE DOE Richard Roe, having qualified as Executor "
            "of the Estate of JANE DOE, late of 48 Homes Drive, Southport, NC 28461, this is to "
            "notify all persons")
    li = _notice(1, "JANE DOE", None, state="NC", county="Brunswick", desc=desc)
    assert _synth_for_listing(li) == "48 Homes Drive"


def test_a_property_address_in_a_notice_is_still_taken():
    desc = ("NOTICE OF FORECLOSURE SALE 26SP009932-110 Under the power of sale in a Deed of Trust "
            "by JANE DOE the Substitute Trustee will sell at the courthouse door the property "
            "located at 77 Hill St, Shelby NC")
    li = Listing(source="public_notices.nc_notices_counties", source_url="https://example.test/1",
                 listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Cleveland",
                 description=desc, raw={})
    assert _synth_for_listing(li) == "77 Hill St"


def test_an_address_written_from_a_parcel_record_is_left_alone():
    d, c = ESTATES[0]
    li = _notice(1, d, c, street_address="181 N IRBY ST",
                 raw={"situs_address_source": "parcel_cache:exact"})
    enrich_with_address_synthesis([li])
    assert li.street_address == "181 N IRBY ST"
