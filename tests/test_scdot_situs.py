"""SCDOT situs extraction + SC counties routed through the statewide layer."""
from __future__ import annotations

from foreclosure_scraper import parcel_inventory as pi


def test_scdot_situs_prefers_full_street_address():
    assert pi._scdot_situs({"StreetAddress": "1101 PARTRIDGE RD"}) == "1101 PARTRIDGE RD"
    assert pi._scdot_situs({"Property_A": "88 COLONIAL ACRES ROAD"}) == "88 COLONIAL ACRES ROAD"


def test_scdot_situs_composes_number_and_name():
    assert pi._scdot_situs({"STREET_NUM": "410", "STREET_NAM": "LUCKY LANE"}) == "410 LUCKY LANE"
    assert pi._scdot_situs({"STREET_NUM": "0", "STREET_NAM": "MAIN ST"}) == "MAIN ST"


def test_scdot_situs_charleston_split_fields():
    # SCDOT Charleston (layer 10): PROP_ST_NO + PROP_ST_NA (live-verified 2026-06-27).
    assert pi._scdot_situs(
        {"PROP_ST_NO": "1887", "PROP_ST_NA": "RICHMOND ST"}) == "1887 RICHMOND ST"
    # vacant parcels carry PROP_ST_NO "0"/"000" -> street name only, no leading zero
    assert pi._scdot_situs(
        {"PROP_ST_NO": "0", "PROP_ST_NA": "OYSTER FACTORY"}) == "OYSTER FACTORY"
    assert pi._scdot_situs(
        {"PROP_ST_NO": "000", "PROP_ST_NA": "CREEK POINT"}) == "CREEK POINT"


def test_scdot_situs_ignores_owner_mailing_block():
    # Union's Address_1 'C/O ...' is owner mailing, not situs -> not returned
    assert pi._scdot_situs({"Address_1": "C/O TRANSPORTATION BANK"}) == ""
    assert pi._scdot_situs({"Address_1": "DONALD"}) == ""
    # ...but a street-looking Address1 is accepted
    assert pi._scdot_situs({"Address1": "123 OAK ST"}) == "123 OAK ST"


def test_scdot_situs_empty_when_no_address():
    assert pi._scdot_situs({"PROP_CLASS": "RES", "OWNER": "SMITH"}) == ""


def test_gap_sc_counties_routed_through_scdot():
    layers = pi._layers()
    for county in ("Oconee", "Union", "Spartanburg", "Laurens", "Anderson", "Cherokee"):
        spec = layers.get(("SC", county))
        assert spec and spec.get("scdot") is True, f"{county} not routed to SCDOT"
        assert "smpesri.scdot.org" in spec["url"]


def test_extract_uses_scdot_situs():
    spec = {"scdot": True}
    out = pi._extract({"PIN": "123", "OWNER": "SMITH JOHN",
                       "STREET_NUM": "410", "STREET_NAM": "LUCKY LANE"}, spec)
    assert out["situs"] == "410 LUCKY LANE"


def test_scdot_parcel_picks_unique_not_subsequence():
    # Spartanburg: must pick TAXPIN, not the non-unique PARCELNUMBER='41'
    a = {"TAXPIN": "713320362391", "PARCELNUMBER": "41", "MAPNUMBER": "7-17-02-041.00"}
    assert pi._scdot_parcel(a) == "713320362391"
    # Oconee uses TMS_NUMBER, Union uses ParcelID, Laurens/Anderson TMS
    assert pi._scdot_parcel({"TMS_NUMBER": "501-00-01-001", "PARCEL_NO": "7"}) == "501-00-01-001"
    assert pi._scdot_parcel({"ParcelID": "U-123-45", "ParcelNumb": "45"}) == "U-123-45"
    assert pi._scdot_parcel({"TMS": "0123456789"}) == "0123456789"


def test_extract_scdot_parcel_in_full_extract():
    out = pi._extract({"TAXPIN": "713320362391", "PARCELNUMBER": "41",
                       "OWNER": "SMITH", "StreetAddress": "1101 PARTRIDGE RD"}, {"scdot": True})
    assert out["parcel_id"] == "713320362391" and out["situs"] == "1101 PARTRIDGE RD"
