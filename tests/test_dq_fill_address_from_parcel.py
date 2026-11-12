"""fill_address_from_parcel: classification of cache situs text, the fill/upgrade decision, and its guards."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fill_address_from_parcel as F  # noqa: E402
from foreclosure_scraper.web_artifact import is_pinpointable_address  # noqa: E402


# ---- classify_situs -------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,kind", [
    ("3101 CAMDEN DR", "numbered"),
    ("000141 LEVI DR", "numbered"),                         # McDowell zero-pads the number
    ("3603  MCLEAN CHAPEL CHURCH RD  BUNNLEVEL", "numbered"),
    ("12C TOXAWAY FALLS DR     .86", "numbered"),          # the county appends the acreage
    ("0 CALHOUN TRL", "road_only"),                        # sentinel house number
    ("99999 DUCKERS  VW", "road_only"),
    ("0 QUEENS GAP", "road_only"),                         # sentinel + road, suffix not one we know
    ("MEADOW RD", "road_only"),
    ("OFF SR 1151 EXT", "legal"),
    ("COMMON AREA-WHITEWATER   COVE", "road_only"),        # a subdivision that ends in a road word: no number, no fill
    ("PINEWOOD ACRES    3101 CAMDEN DR", "legal"),
    ("S-6-65", "legal"),
    ("1324     2.00", "junk"),
    ("5 ACRES ON HWY 9", "legal"),
    ("1163", "junk"),
    ("0 NO ADDRESS ASSIGNED", "junk"),
    ("PO BOX 4", "junk"),
    ("7 OX RD", "numbered"),
    ("220 4TH AVE", "numbered"),
    ("", "junk"),
    (None, "junk"),
])
def test_classify_situs(raw, kind):
    assert F.classify_situs(raw)["kind"] == kind


def test_a_numbered_result_is_pinpointable_and_cleaned():
    c = F.classify_situs("000141 LEVI DR")
    assert c["address"] == "141 LEVI DR" and is_pinpointable_address(c["address"])
    assert F.classify_situs("12C TOXAWAY FALLS DR     .86")["address"] == "12C TOXAWAY FALLS DR"


# ---- mailing-derived city and zip -----------------------------------------------------------------
def test_city_and_zip_only_when_the_mailing_starts_with_the_property_street():
    assert F.city_zip_from_mailing("459 BROWN FARM RD", "459 BROWN FARM RD SENECA SC 29678", "SC") == ("Seneca", "29678")
    assert F.city_zip_from_mailing("2204 E Bobo Newsom Hwy", "2204 E Bobo Newsom Hwy Hartsville SC", "SC") == ("Hartsville", None)
    assert F.city_zip_from_mailing("12 OAK ST", "12 OAK ST FOUNTAIN INN SC 29644", "SC") == ("Fountain Inn", "29644")
    assert F.city_zip_from_mailing("12 OAK ST", "PO BOX 9 SENECA SC 29678", "SC") == (None, None)      # a different address
    assert F.city_zip_from_mailing("12 OAK ST", "12 OAK ST SENECA SC 29678", "NC") == (None, None)      # state mismatch


# ---- plan_fill --------------------------------------------------------------------------------------
def _plan(**kw):
    base = dict(state="SC", county="Darlington", listing_type="tax_lien", parcel_id="100-00-02-141.000",
                street=None, city=None, zip_code=None, mailing=None, hit=None, tier=None, cache_exists=True)
    base.update(kw)
    return F.plan_fill(**base)


def test_numbered_cache_address_fills_a_blank_street_and_takes_city_zip_from_the_mailing():
    hit = {"address": "437 SEMINOLE DR", "owner_mailing": "437 SEMINOLE DR HARTSVILLE SC 29550"}
    p = _plan(hit=hit, tier="zero_suffix")
    assert p["status"] == "filled" and p["pop"] == "gap"
    assert p["set"]["street_address"] == "437 SEMINOLE DR"
    assert p["set"]["city"] == "Hartsville" and p["set"]["zip_code"] == "29550"
    assert p["set"]["_source"] == "parcel_cache:zero_suffix"


def test_a_legal_description_is_never_written_as_a_street():
    p = _plan(hit={"address": "SPLIT FROM 116-00-01-048"}, tier="exact")
    assert p["status"] == "hit_legal_or_junk" and not p["set"]
    p = _plan(hit={"address": "COMMON AREA-WHITEWATER COVE"}, tier="exact")     # no house number: not filled
    assert not p["set"]


def test_road_only_is_kept_as_context_not_as_the_address():
    p = _plan(hit={"address": "0 CALHOUN TRL"}, tier="exact")
    assert p["status"] == "road_only" and not p["set"]
    assert p["road_only"]["road"] == "CALHOUN TRL" and "not a building" in p["road_only"]["note"]


def test_no_cache_miss_and_empty_hit_are_told_apart():
    assert _plan(hit=None, cache_exists=False)["status"] == "no_cache"
    assert _plan(hit=None, cache_exists=True)["status"] == "miss"
    assert _plan(hit={"owner": "X"}, tier="exact")["status"] == "hit_no_address"


def test_tax_sale_overage_no_parcel_and_wrong_state_county_are_skipped():
    assert _plan(listing_type="tax_sale_overage", hit={"address": "1 OAK ST"})["status"] == "skip_tax_sale_overage"
    assert _plan(parcel_id="", hit={"address": "1 OAK ST"})["status"] == "skip_no_parcel"
    assert _plan(state="SC", county="Buncombe", hit={"address": "1 OAK ST"})["status"] == "skip_county_not_in_state"
    assert _plan(state="NC", county="Union", hit={"address": "1 OAK ST"}, tier="exact")["status"] == "filled"


def test_a_lead_that_already_has_a_numbered_address_is_not_touched():
    p = _plan(street="12 OAK ST", hit={"address": "99 OTHER ST"}, tier="exact")
    assert p["pop"] is None and not p["set"]


def test_street_name_only_is_upgraded_only_when_both_name_the_same_street():
    hit = {"address": "1575 BLUE RIDGE RD"}
    p = _plan(state="NC", county="Transylvania", street="BLUE RIDGE RD", hit=hit, tier="exact")
    assert p["status"] == "upgraded" and p["set"]["street_address"] == "1575 BLUE RIDGE RD"
    assert p["replaced_street"] == "BLUE RIDGE RD"
    p = _plan(state="NC", county="Transylvania", street="PICKENS ST", hit=hit, tier="exact")
    assert p["status"] == "name_only_street_disagrees" and not p["set"]
    # the Transylvania cache text is a legal description, so nothing upgrades from it
    p = _plan(state="NC", county="Transylvania", street="COMMON AREA-WHITEWATER COVE",
              hit={"address": "COMMON AREA-WHITEWATER   COVE"}, tier="exact")
    assert not p["set"]


def test_a_unit_range_is_a_house_number_and_a_conflicting_direction_blocks_an_upgrade():
    assert F.has_house_number("831/833 N Oak St") and F.has_house_number("12-14 Main St")
    p = _plan(state="NC", county="Henderson", street="831/833 N Oak St", hit={"address": "831 N OAK ST"}, tier="exact")
    assert p["pop"] is None and not p["set"]                              # already numbered: never rewritten
    hit = {"address": "1501 N CHESTER ST"}
    p = _plan(state="NC", county="Gaston", street="S CHESTER ST", hit=hit, tier="exact")
    assert p["status"] == "name_only_street_disagrees" and not p["set"]
    p = _plan(state="NC", county="Gaston", street="CHESTER ST", hit=hit, tier="exact")   # no direction on one side: fine
    assert p["status"] == "upgraded"
    assert F.street_dirs("SOUTH Main St") == frozenset({"S"})


def test_an_address_point_overlay_supplies_number_city_and_zip(tmp_path, monkeypatch):
    con = sqlite3.connect(tmp_path / "transylvania.sqlite")
    con.execute("CREATE TABLE pts(id TEXT, address TEXT, city TEXT, zip TEXT)")
    con.execute("INSERT INTO pts VALUES('9506212520000','70 ABERDEEN LN','Pisgah Forest','28768')")
    con.commit()
    con.close()
    monkeypatch.setattr(F, "OVERLAY_DIR", tmp_path)
    F._OVERLAY.clear()
    ov = F.overlay_lookup("Transylvania", "NC", "9506-21-2520-000")
    assert ov == {"address": "70 ABERDEEN LN", "city": "Pisgah Forest", "zip": "28768"}
    p = _plan(state="NC", county="Transylvania", parcel_id="9506-21-2520-000", street="ABERDEEN LN", hit=None,
              overlay=ov)
    assert p["status"] == "upgraded" and p["set"]["city"] == "Pisgah Forest" and p["set"]["zip_code"] == "28768"
    assert p["set"]["_source"] == "address_points"
    F._OVERLAY.clear()


def test_street_words_ignore_number_suffix_and_direction():
    assert F.street_words("123 N PICKENS STREET") == F.street_words("PICKENS ST") == frozenset({"PICKENS"})
