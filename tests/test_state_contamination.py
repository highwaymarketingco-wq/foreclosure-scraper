"""State contamination registries.

A property with a confirmed petroleum release or a recorded land-use
restriction is genuinely hard to sell. These are statewide files, which is what
the counties publishing nothing locally need — Mitchell, Polk and McDowell all
appear here.
"""
from __future__ import annotations

import foreclosure_scraper.scrapers.counties_generic.state_contamination as S


def test_county_column_is_matched_by_prefix_not_equality():
    """NC DEQ stores County truncated to FIVE characters ('BUNCO', 'HENDE').
    An exact-match IN() over full names returns 481 rows; prefix matching
    returns 4,468 — the same data, 9x more of it."""
    ust = next(r for r in S.REGISTRIES if r.slug == "nc_ust_incidents")
    assert "LIKE" in ust.where and "BUNCO%" in ust.where
    assert "IN (" not in ust.where


def test_the_transylvania_typo_is_included():
    """The LUR registry spells it 'Transylvanis' on two Ecusta Mill records,
    both carrying usable deed references. Omitting the typo drops them."""
    assert "TRANSYLVANIS" in S.NC_FULL
    lur = next(r for r in S.REGISTRIES if r.slug == "nc_land_use_restrictions")
    assert "TRANSYLVANIS" in lur.where


def test_truncated_counties_expand_to_canonical_spelling():
    """Downstream joins and the scope filter match on the county string, so
    'Mcdowell' from .title() would silently fail to match 'McDowell'."""
    assert S._county_of("MCDOW") == "McDowell"
    assert S._county_of("BUNCO") == "Buncombe"
    assert S._county_of("Transylvanis") == "Transylvania"
    assert S._county_of("HENDE") == "Henderson"
    assert S._county_of("") is None


def test_every_registry_requests_explicit_fields():
    for r in S.REGISTRIES:
        assert r.fields and "*" not in r.fields, r.slug


def test_a_row_without_an_address_is_dropped():
    reg = S.REGISTRIES[0]
    assert S._to_listing({"County": "BUNCO", "IncidentName": "X"}, reg) is None


def test_placeholder_values_are_not_treated_as_data():
    """Deed_Bk is the literal string 'NA' on 434 of 550 LUR rows."""
    for junk in ("NA", "N/A", "none", "NULL", "unknown", "", "   "):
        assert S._clean(junk) is None
    assert S._clean(" 679 Ridge Road ") == "679 Ridge Road"


def test_a_real_ust_row_maps():
    reg = next(r for r in S.REGISTRIES if r.slug == "nc_ust_incidents")
    li = S._to_listing({"IncidentNumber": "12345", "IncidentName": "asbury residence",
                        "Address": "15 Beaver Valley Road", "CityTown": "Asheville",
                        "County": "BUNCO", "ZipCode": "28805",
                        "CurrStatus": "OPEN"}, reg)
    assert li.county == "Buncombe" and li.state == "NC"
    assert li.street_address == "15 Beaver Valley Road"
    assert li.owner_name == "asbury residence"
    assert li.foreclosure_process == "contamination"


def test_dam_uses_its_own_coordinate_not_the_owner_mailing_address():
    """2026-09-30 fix: ADDR_LINE1/2 + CITY/STATE/ZIP on this layer are the DAM
    OWNER'S MAILING address (e.g. a property-owners-association's out-of-state
    office), not the dam's location -- confirmed via a real record ("Betty Kay
    Lake Dam", Transylvania County, mailing address in Decatur, GA). Feeding that
    mailing block into street_address (as this scraper used to) meant the
    Census-geocode backfill geocoded the OWNER's address and placed the dam
    hundreds of miles from its true (correctly-labeled) county. This layer also
    publishes the dam's own LATITUDE/LONGITUDE and a real id (NID_ID) -- those
    must be used directly instead, and the mailing block must never land in
    street_address/city/zip_code."""
    reg = next(r for r in S.REGISTRIES if r.slug == "nc_dam_safety")
    li = S._to_listing({
        "Owner": "Sherwood Forest Property Owners Association",
        "ADDR_LINE1": "417 Clairemont Avenue", "ADDR_LINE2": "Unit 303",
        "CITY": "Decatur", "STATE": "GA", "ZIP": "30030",
        "COUNTY": "TRANS", "NID_ID": "NC00190",
        "LATITUDE": 35.135, "LONGITUDE": -82.6851,
    }, reg)
    assert li.county == "Transylvania" and li.foreclosure_process == "dam_liability"
    # The dam's real location, taken straight from the layer -- not geocoded.
    assert li.latitude == 35.135 and li.longitude == -82.6851
    # The owner's out-of-state mailing address must never be mistaken for the
    # dam's location.
    assert li.street_address is None
    assert li.city is None
    assert li.zip_code is None
    assert li.parcel_id == "NC00190"
    assert li.raw["state_contamination"]["owner_mailing"]["CITY"] == "Decatur"
    assert "owner mailing" in li.description


def test_dam_row_survives_on_coordinate_alone_with_no_address_field():
    """A dam with a real NID_ID/coordinate but no address at all used to be
    dropped by the old 'if not situs: return None' gate. Losing the lead
    entirely would be worse than the mislabeled-coordinate bug this fixes."""
    reg = next(r for r in S.REGISTRIES if r.slug == "nc_dam_safety")
    li = S._to_listing({"Owner": "Jane Shuttleworth", "COUNTY": "TRANS",
                        "NID_ID": "NC00196", "LATITUDE": 35.3028,
                        "LONGITUDE": -82.6358}, reg)
    assert li is not None
    assert li.latitude == 35.3028 and li.parcel_id == "NC00196"


def test_dam_out_of_range_coordinate_is_dropped_not_trusted():
    reg = next(r for r in S.REGISTRIES if r.slug == "nc_dam_safety")
    li = S._to_listing({"Owner": "X", "COUNTY": "TRANS", "NID_ID": "NC1",
                        "LATITUDE": 999.0, "LONGITUDE": -82.6}, reg)
    assert li.latitude is None and li.longitude == -82.6


def test_none_of_the_registries_have_a_per_record_id_field():
    """id_field is only meaningful for nc_dam_safety's NID_ID -- the other 3
    registries key off a real address (or, for ust/hazardous, their own
    coordinate) and have no independent per-record id."""
    for slug in ("nc_ust_incidents", "nc_land_use_restrictions", "nc_inactive_hazardous"):
        reg = next(r for r in S.REGISTRIES if r.slug == slug)
        assert reg.id_field is None


def test_lur_still_has_no_coordinate_field():
    """nc_land_use_restrictions is walled (Token Required, verified live
    2026-10-01) so its own field list has never been inspected; it keeps
    relying on Prj_Address alone."""
    reg = next(r for r in S.REGISTRIES if r.slug == "nc_land_use_restrictions")
    assert reg.lat_field is None and reg.lon_field is None


def test_ust_and_hazardous_use_their_own_coordinate_not_a_geocode():
    """2026-10-01 fix, same pattern as nc_dam_safety: nc_ust_incidents
    (LatDec/LongDec) and nc_inactive_hazardous (LATITUDE/LONGITUDE) both
    publish their own authoritative site coordinate -- verified live against
    the FeatureServer field lists and real rows. Previously neither field
    was requested at all, so every row relied entirely on the downstream
    Census-geocode backfill of a sometimes-unparseable address (e.g.
    "SR 3495-GLENN BRIDGE RD")."""
    ust = next(r for r in S.REGISTRIES if r.slug == "nc_ust_incidents")
    assert ust.lat_field == "LatDec" and ust.lon_field == "LongDec"
    haz = next(r for r in S.REGISTRIES if r.slug == "nc_inactive_hazardous")
    assert haz.lat_field == "LATITUDE" and haz.lon_field == "LONGITUDE"


def test_ust_row_captures_its_own_coordinate_and_doc_link():
    reg = next(r for r in S.REGISTRIES if r.slug == "nc_ust_incidents")
    li = S._to_listing({
        "IncidentName": "asbury residence", "Address": "15 Beaver Valley Road",
        "County": "BUNCO", "LatDec": 35.563539, "LongDec": -82.51285,
        "DocsLink": "http://edocs.deq.nc.gov/WasteManagement/Search.aspx?dbid=0"
                    "&searchcommand=%7B%5BWM%5D%3A%5BProgram_ID%5D%3D%22%2AAS-7%2A%22%7D",
    }, reg)
    assert li.latitude == 35.563539 and li.longitude == -82.51285
    assert li.raw["state_contamination"]["DocsLink"].startswith("http")


def test_hazardous_row_captures_its_own_coordinate_and_doc_link():
    reg = next(r for r in S.REGISTRIES if r.slug == "nc_inactive_hazardous")
    li = S._to_listing({
        "SITENAME": "ERWIN HILLS ROAD PFAS", "SITEADDR": "180 ERWIN HILLS RD",
        "SITECOUNTY": "BUNCOMBE", "LATITUDE": 35.6209884, "LONGITUDE": -82.6215064,
        "Laserfiche": "https://edocs.deq.nc.gov/WasteManagement/Search.aspx?dbid=0"
                      "&searchcommand=%7B%5BWM%5D:%5BProgram_ID%5D%20%3D%20%22*NONCD0003384*%22%7D",
    }, reg)
    assert li.latitude == 35.6209884 and li.longitude == -82.6215064
    assert li.raw["state_contamination"]["Laserfiche"].startswith("https")


def test_dam_phone_is_captured_under_owner_mailing():
    """Phone is a real, frequently-populated owner contact number (verified
    live, including individual owners, not just HOAs) that was being
    dropped entirely. It belongs alongside the rest of the owner's contact
    block, not street_address/city/zip."""
    reg = next(r for r in S.REGISTRIES if r.slug == "nc_dam_safety")
    li = S._to_listing({
        "Owner": "Jane Shuttleworth", "COUNTY": "TRANS", "NID_ID": "NC00196",
        "LATITUDE": 35.3028, "LONGITUDE": -82.6358, "Phone": "8286930015",
    }, reg)
    assert li.raw["state_contamination"]["owner_mailing"]["Phone"] == "8286930015"


def test_registries_cover_the_thin_counties():
    """The whole point of a statewide file: Mitchell, Polk and McDowell have the
    weakest local coverage in the footprint."""
    for c in ("MITCH", "POLK", "MCDOW"):
        assert c in S.NC_PREFIX
