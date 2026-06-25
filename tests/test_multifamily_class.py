"""Precision/recall regression tests for the multifamily classifier.

Each case below was distilled from real strings observed in the live
docs/listings.json (true positives that must reclassify, and false-positive
traps that must NOT). See enrichment_multifamily_class module docstring.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_multifamily_class import (
    classify_multifamily,
    enrich_multifamily_class,
)
from foreclosure_scraper.models import Listing, PropertyKind


def _L(**kw) -> Listing:
    kw.setdefault("source", "test")
    kw.setdefault("source_url", "http://x")
    return Listing(**kw)


# (name, listing) — every one of these MUST be detected as multifamily.
TRUE_POSITIVES = [
    ("party_apartments_llc", _L(defendant="Oakwood Apartments LLC")),
    ("party_apartment_homes", _L(defendant="Cedar Ridge Apartment Homes LP")),
    ("party_housing_partners", _L(defendant="Piedmont Housing Partners LLC")),
    ("party_villas", _L(defendant="Sunset Villas LLC")),
    ("party_townhomes_llc", _L(defendant="Maple Townhomes LLC")),
    ("party_multifamily_owner", _L(raw={"owner": "BlueSky Multifamily Holdings"})),
    ("party_unit_complex", _L(legal_description="24 unit complex on Lot 5")),
    ("desc_duplex", _L(description="Charming brick duplex, both sides rented.")),
    ("desc_triplex", _L(description="Well-maintained triplex near downtown.")),
    ("desc_six_units", _L(description="Income-producing apartment complex with six units total.")),
    ("desc_4_unit_building", _L(description="4-unit building, fully occupied.")),
    ("desc_fourplex", _L(description="Solid fourplex, value-add opportunity.")),
    ("struct_units_field", _L(raw={"units": 4})),
    ("struct_gis_units", _L(raw={"gis": {"units": 3}})),
    ("zoning_rm", _L(zoning="RM-12")),
]

# (name, listing) — every one of these MUST be left alone (no MF).
TRUE_NEGATIVES = [
    ("ac_unit", _L(description="New AC unit downstairs, window units in back.")),
    ("end_unit", _L(description="Private END UNIT!", property_kind=PropertyKind.TOWNHOUSE)),
    ("garage_apartment", _L(description="SFR with a separate garage apartment.")),
    ("inlaw_apartment", _L(description="Home with in-law apartment over the garage.")),
    ("spec_could_be_duplex", _L(description="Large home that could be converted to a duplex.")),
    ("spec_duplex_etc", _L(description="single family with guest quarters, vacation rental, duplex, etc.")),
    ("spec_zoning_allows", _L(description="R8 zoning allows a duplex per every 1200sqft.")),
    ("spec_not_duplex", _L(description="Although not legally classified as a duplex, layout allows it.")),
    ("landmark_apt", _L(description="New Apartment Complex across the Street and bus garage beside.")),
    ("near_apt", _L(description="Walkable to downtown, close to apartments and shops.")),
    ("addr_place_name", _L(defendant="Treece, Vivian",
                           legal_description="375 East Marion Street, Hickory Creek Apartments, Shelby, North Carolina, 28150")),
    ("hoa_condo_assoc", _L(defendant="Rajiv Patel",
                           plaintiff="Chandler Oaks Apartments Condominium Owners Association",
                           property_kind=PropertyKind.CONDO)),
    ("sfr_plain", _L(description="3 bedroom 2 bath ranch home on a quiet street.")),
    ("luxury_sfr_sqft", _L(living_sqft=8500, bedrooms=4,
                           description="Exceptional mountain home, incredible craftsmanship.")),
]


@pytest.mark.parametrize("name,li", TRUE_POSITIVES, ids=[n for n, _ in TRUE_POSITIVES])
def test_true_positive(name, li):
    assert classify_multifamily(li) is not None, f"{name} should be MF"


@pytest.mark.parametrize("name,li", TRUE_NEGATIVES, ids=[n for n, _ in TRUE_NEGATIVES])
def test_true_negative(name, li):
    assert classify_multifamily(li) is None, f"{name} should NOT be MF"


def test_never_demotes_condo():
    """A condo apartment-association suit must stay CONDO, not become MF."""
    li = _L(defendant="Patel",
            plaintiff="Oaks Apartments Condominium Owners Association",
            property_kind=PropertyKind.CONDO)
    enrich_multifamily_class([li])
    assert li.property_kind == PropertyKind.CONDO


def test_never_touches_existing_mf_idempotent():
    li = _L(description="duplex", property_kind=PropertyKind.MULTI_FAMILY)
    stats = enrich_multifamily_class([li])
    assert stats["already_mf"] == 1
    assert stats["reclassified"] == 0
    assert li.property_kind == PropertyKind.MULTI_FAMILY


def test_stamps_mf_signal_and_promotes():
    li = _L(defendant="Oakwood Apartments LLC", property_kind=PropertyKind.UNKNOWN)
    enrich_multifamily_class([li])
    assert li.property_kind == PropertyKind.MULTI_FAMILY
    assert li.raw["mf_signal"]["tier"] == "party"


def test_overrides_single_family_when_strong_party_signal():
    """SFR mislabel gets corrected when the foreclosed party is a complex."""
    li = _L(defendant="Cedar Ridge Apartment Homes LP",
            property_kind=PropertyKind.SINGLE_FAMILY)
    enrich_multifamily_class([li])
    assert li.property_kind == PropertyKind.MULTI_FAMILY
