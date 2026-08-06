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


def test_dam_address_is_composed_from_parts():
    reg = next(r for r in S.REGISTRIES if r.slug == "nc_dam_safety")
    li = S._to_listing({"Owner": "C.B. DELLINGER", "ADDR_LINE1": "HWY 150 W",
                        "ADDR_LINE2": "", "COUNTY": "LINCO", "CITY": "Lincolnton"}, reg)
    assert li.street_address == "HWY 150 W"
    assert li.county == "Lincoln"
    assert li.foreclosure_process == "dam_liability"


def test_registries_cover_the_thin_counties():
    """The whole point of a statewide file: Mitchell, Polk and McDowell have the
    weakest local coverage in the footprint."""
    for c in ("MITCH", "POLK", "MCDOW"):
        assert c in S.NC_PREFIX
