"""counties_nc.transylvania_vacant extraction-completeness audit (2026-10-03).

Diffed the live 65-field ArcGIS layer schema against the 22-field outFields
list and live-sampled 500/2000 real BUILDING_V=0 rows:

  - CITY/STATE/ZIP + ADDRESS_2/3 (the owner mailing address) were already
    fetched but stashed only under raw['transylvania_vacant']['owner_mailing'],
    a private key none of enrichment_lead_signals.py's absentee_owner check,
    enrichment_skip_trace.py, or enrichment_notice_service_defect.py read --
    all three read raw['owner_mailing'] (top-level) via mailing_shape.py.
    Live full run: 10,899/11,109 listings now carry it, 4,718 (42.5%) flag
    absentee_owner.
  - ADDRESS_1 was mislabeled "street" by the old code; live-sampled it is
    almost always a CO-OWNER/trustee/attn line ("Bruce Dorothy C Trustees",
    "CO-TRUSTEE"), not a street -- publishing it as the mailing street would
    have put a person's name in a street-address field.
  - SALE_PRICE + SALE_DATE were already fetched but never paired into
    raw['gis']['last_sale'] (enrichment_last_sale.py's key).
  - WATERFRONT (Y on 8/500 live), SALE_INST/SALE_QUALI (sale instrument +
    qualification code -- tells a quitclaim/non-arms-length sale from a real
    comp), SALE_IMP (improved-at-time-of-sale, 'I' on 13/500 despite
    BUILDING_V=0 today -- a demolished/burned structure), ACCOUNT_NO (100%
    filled, a stable cross-reference id) and XFOB_VALUE (nonzero on 20/500,
    a well/septic/outbuilding) were never requested at all.

GOTCHA caught live-verifying the absentee heuristic (same one lincoln_vacant
hit): LEGAL_ADDR on vacant land is almost always just a road name with no
house number (2,000-row sample: only 5, 0.25%, start with a digit), so the
street-token comparison only runs when situs itself starts with a digit.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc.transylvania_vacant import (
    _build_raw, _is_absentee,
)


# --------------------------------------------------------------------------- _is_absentee

def test_out_of_state_mailing_is_absentee():
    assert _is_absentee("GA", "840 Springdale Rd NE", "CASHIERS RD") is True


def test_in_state_po_box_is_absentee():
    assert _is_absentee("NC", "PO Box 2772", "CASHIERS RD") is True


def test_same_state_no_house_number_situs_is_not_flagged_on_token_mismatch():
    """The core guard: vacant land's situs is almost always a bare road name
    with no house number, so a street-token mismatch must NOT fire unless
    situs itself starts with a digit (otherwise ~every owner is 'absentee')."""
    assert _is_absentee("NC", "109 Goathill Rd", "CASHIERS RD") is False


def test_same_state_with_house_number_situs_detects_real_mismatch():
    assert _is_absentee("NC", "109 Goathill Rd", "456 Oak Ridge Dr") is True


def test_same_state_with_house_number_situs_matching_street_is_not_absentee():
    assert _is_absentee("NC", "109 Goathill Rd", "109 Goathill Rd") is False


def test_in_state_normal_mailing_is_not_absentee():
    assert _is_absentee("NC", "", "CASHIERS RD") is False


# --------------------------------------------------------------------------- _build_raw

def _attrs(**overrides):
    base = {
        "BUILDING_V": 0, "LAND_VALUE": 20000, "ASSESSED_V": 20000,
        "SALE_PRICE": 62500, "SALE_DATE": "199606", "SALE_INST": "WD",
        "SALE_QUALI": "X", "SALE_IMP": "V", "DEED_BK": "123", "PAGE": "456",
        "USECODE": "VAC", "ACRES": 1.5, "WATERFRONT": "Y",
        "ACCOUNT_NO": "42817100", "XFOB_VALUE": 3500,
    }
    base.update(overrides)
    return base


def test_owner_mailing_is_wired_to_top_level_key():
    mailing = {"owner_line2": None, "street": "840 Springdale Rd NE",
               "city": "Atlanta", "state": "GA", "zip": "30306"}
    raw = _build_raw(_attrs(), "CASHIERS RD", mailing, "840 Springdale Rd NE",
                     "Atlanta", "GA", 62500.0, "199606")
    assert raw["owner_mailing"] == mailing
    assert raw["absentee_owner"] is True  # GA != NC


def test_no_mailing_street_or_city_does_not_set_owner_mailing():
    mailing = {"owner_line2": None, "street": None, "city": None,
               "state": None, "zip": None}
    raw = _build_raw(_attrs(), "CASHIERS RD", mailing, None, None, None, None, None)
    assert "owner_mailing" not in raw
    assert "absentee_owner" not in raw


def test_gis_last_sale_wired_when_both_amount_and_date_present():
    mailing = {"owner_line2": None, "street": "109 Goathill Rd",
               "city": "Moorseville", "state": "NC", "zip": "28117"}
    raw = _build_raw(_attrs(), "CASHIERS RD", mailing, "109 Goathill Rd",
                     "Moorseville", "NC", 62500.0, "199606")
    assert raw["gis"]["last_sale"] == {
        "amount": 62500.0, "date": "199606", "source": "transylvania_county_gis",
    }


def test_no_gis_last_sale_when_sale_amount_missing():
    mailing = {"owner_line2": None, "street": "109 Goathill Rd",
               "city": "Moorseville", "state": "NC", "zip": "28117"}
    raw = _build_raw(_attrs(SALE_PRICE=0), "CASHIERS RD", mailing,
                     "109 Goathill Rd", "Moorseville", "NC", None, "199606")
    assert "gis" not in raw


def test_new_fields_land_in_transylvania_vacant_raw():
    mailing = {"owner_line2": None, "street": None, "city": None,
               "state": None, "zip": None}
    raw = _build_raw(_attrs(), "CASHIERS RD", mailing, None, None, None, None, None)
    tv = raw["transylvania_vacant"]
    assert tv["waterfront"] == "Y"
    assert tv["account_number"] == "42817100"
    assert tv["extra_features_value"] == 3500.0
    assert tv["sale_instrument"] == "WD"
    assert tv["sale_qualifying_code"] == "X"
    assert tv["sale_improved_at_sale"] == "V"
