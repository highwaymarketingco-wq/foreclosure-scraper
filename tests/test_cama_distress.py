"""CAMA distress-signal extraction (the 'D' ask via clean ArcGIS).

Harvests ROD-adjacent signals (condition, owner-occupancy, last sale, deed ref,
previous owner) from the Spartanburg Parcel_and_CAMA layer we already query.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_owner_mailing import (
    _extract_distress, _build_result,
)
from foreclosure_scraper.models import Listing, ListingType

SPEC = {"owner": ["OwnerName"], "mail": ["StreetAddr", "City", "State", "Zip"],
        "mail_state": "State", "situs": ["PropertyLo"], "parcel": "TAXPIN"}


def _attrs(**over):
    a = {"OwnerName": "DOE JANE", "StreetAddr": "9 FAR AWAY RD",
         "City": "ATLANTA", "State": "GA", "Zip": "30301",
         "PropertyLo": "12 MAIN ST SPARTANBURG", "TAXPIN": "1-23-45",
         "ConditionF": "AV", "HomesteadN": " ", "SaleDate": 1263513600000,
         "SaleAmount": 95000, "DeedBook": "126P", "DeedPage": "942",
         "PreviousOw": "SMITH BOB"}
    a.update(over)
    return a


def test_poor_condition_flags_distress():
    for code in ("PR", "VP", "DL"):
        d = _extract_distress(_attrs(ConditionF=code))
        assert d["condition_distressed"] is True
        assert d["condition_code"] == code


def test_fair_and_good_condition_not_distressed():
    for code in ("AV", "GD", "FR", "FA", "EX"):
        d = _extract_distress(_attrs(ConditionF=code))
        assert "condition_distressed" not in d


def test_homestead_marks_owner_occupied():
    assert _extract_distress(_attrs(HomesteadN="H")).get("owner_occupied") is True
    # blank is the majority -> NOT treated as owner-occupied (and not absentee)
    assert "owner_occupied" not in _extract_distress(_attrs(HomesteadN=" "))


def test_nominal_sale_flag():
    assert _extract_distress(_attrs(SaleAmount=1)).get("nominal_transfer") is True
    assert _extract_distress(_attrs(SaleAmount=150000)).get("nominal_transfer") is None
    assert _extract_distress(_attrs(SaleAmount=150000))["last_sale_amount"] == 150000.0


def test_deed_ref_and_prev_owner():
    d = _extract_distress(_attrs())
    assert d["deed_ref"] == "126P/942"
    assert d["previous_owner"] == "SMITH BOB"


def test_empty_attrs_safe():
    assert _extract_distress({}) == {}
    assert _extract_distress(None) == {}


def test_build_result_includes_distress():
    li = Listing(source="x", source_url="http://x", listing_type=ListingType.REO,
                 state="SC", county="Spartanburg", street_address="12 MAIN ST")
    res = _build_result(li, SPEC, _attrs(ConditionF="VP", HomesteadN="H"))
    assert res is not None
    d = res["_distress"]
    assert d["condition_distressed"] is True and d["owner_occupied"] is True
