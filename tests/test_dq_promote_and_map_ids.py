"""promote_ptscloud_block (Henderson PTS numbers) and map_account_ids_to_parcels (Laurens account numbers,
Rutherford PINs): pure planning functions, no board and no network."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import map_account_ids_to_parcels as M  # noqa: E402
import promote_ptscloud_block as P  # noqa: E402

SRC = "counties_nc.nc_ptscloud_delinquent_tax"


def _block(**kw):
    b = {"tenant": "Henderson", "parcel": "9941506", "principal_tax_due": 890.93, "assessed_value": 36300.0,
         "tax_year": "1993", "owner": "DALTON, DWIGHT", "prop_size": "0.94 AC", "legal_description": "MH ON LEASED LAND",
         "mailing": {"addr": "RT 1 BOX 218, HENDERSONVILLE, NC,  28792", "addr1": "RT 1 BOX 218",
                     "addr2": "HENDERSONVILLE, NC,  28792", "addr3": None}}
    b.update(kw)
    return b


def _plan(raw, cache=None, **kw):
    base = dict(source=SRC, county="Henderson", parcel_id="9941506", owner_name="DALTON, DWIGHT", assessed_value=36300.0, acreage=0.94,
                legal_description="MH ON LEASED LAND", street="20 TWIN WILLOW DR", raw=raw,
                cache_lookup=lambda pin: cache.get(pin) if cache else None)
    base.update(kw)
    return P.plan(**base)


# ---- promote_ptscloud_block -------------------------------------------------------------------------
def test_only_henderson_rows_are_handled():
    p = _plan({"nc_ptscloud_delinquent_tax": _block()}, county="Hyde")
    assert not p["is_pts"] and p["status"] == "other_county" and not p["fill"]


def test_only_rows_whose_parcel_id_is_the_blocks_own_pts_number_are_touched():
    assert P.is_pts_row(SRC, "9941506", _block())
    assert not P.is_pts_row(SRC, "0601560094", _block())                       # already a 10-digit PIN
    assert not P.is_pts_row("counties_nc.rutherford_tax", "9941506", _block())
    assert not _plan({"nc_ptscloud_delinquent_tax": _block()}, parcel_id="0601560094")["is_pts"]


def test_pts_number_is_replaced_by_the_pin_only_when_the_cache_owner_agrees_with_the_taxpayer():
    raw = {SRC.split(".")[-1]: _block(), "owner_mailing": {"owner": "X", "mailing": "PO BOX 245 EDNEYVILLE NC 28727",
                                                           "parcel_id": "0601560094"}}
    cache = {"0601560094": {"owner": "THE DWIGHT E. DALTON REVOCABLE LIVING TRUST;DALTON, DWIGHT E. TRUSTEE"}}
    p = _plan(raw, cache)
    assert p["new_parcel"] == "0601560094" and p["status"] == "promote_pin" and p["mismatch"] is None


def test_a_stranger_at_the_resolved_parcel_is_flagged_not_promoted():
    raw = {"nc_ptscloud_delinquent_tax": _block(owner="ROBINSON, CARROLL K"),
           "owner_mailing": {"mailing": "801 N WHITTED ST", "parcel_id": "9568493963"}}
    p = _plan(raw, {"9568493963": {"owner": "MITCHUM, LUCILLE"}}, parcel_id="9941506")
    assert p["new_parcel"] is None and p["status"] == "resolved_parcel_owner_differs"
    assert p["mismatch"]["snapped_owner"] == "MITCHUM, LUCILLE" and p["mismatch"]["defendant_surname"] == "ROBINSON"


def test_placeholder_owners_never_agree_and_are_never_promoted():
    assert not P.owners_agree("UNKNOWN OWNER", "UNKNOWN OWNER")
    assert not P.owners_agree("MAPPING WORK IN PROGRESS", "MAPPING WORK IN PROGRESS")
    assert P.is_placeholder_owner("MAPPING WORK IN PROGRESS") and not P.is_placeholder_owner("DALTON, DWIGHT")
    raw = {"nc_ptscloud_delinquent_tax": _block(owner="UNKNOWN OWNER"),
           "owner_mailing": {"mailing": "X", "parcel_id": "9597576162"}}
    p = _plan(raw, {"9597576162": {"owner": "UNKNOWN OWNER"}}, owner_name=None)
    assert p["new_parcel"] is None and "owner_name" not in p["fill"]


def test_a_shared_surname_alone_is_not_agreement():
    assert P.owners_agree("DALTON, DWIGHT", "THE DWIGHT E. DALTON REVOCABLE LIVING TRUST;DALTON, DWIGHT E. TRUSTEE")
    assert not P.owners_agree("SMITH, JOHN", "SMITH, MARY")
    assert P.owners_agree("WESTERN AND SOUTHERN LIFE INSURANCE", "THE WESTERN AND SOUTHERN LIFE INSURANCE")
    assert P.owners_agree("ACME", "ACME LLC")                       # a single-token name can only match on that token


def test_blank_fields_are_filled_from_the_block_and_present_ones_are_left_alone():
    raw = {"nc_ptscloud_delinquent_tax": _block()}
    p = _plan(raw, owner_name=None, assessed_value=None, acreage=None, legal_description=None)
    assert p["fill"] == {"owner_name": "DALTON, DWIGHT", "assessed_value": 36300.0, "acreage": 0.94,
                         "legal_description": "MH ON LEASED LAND"}
    assert _plan(raw)["fill"] == {}


def test_owner_mailing_is_built_from_the_block_only_when_the_row_has_none():
    raw = {"nc_ptscloud_delinquent_tax": _block()}
    d = _plan(raw)["owner_mailing"]
    assert d["mailing"] == "RT 1 BOX 218 HENDERSONVILLE, NC, 28792" and d["source"] == "ptscloud_block" and d["mail_state"] == "NC"
    raw["owner_mailing"] = {"mailing": "PO BOX 9 X NC", "parcel_id": ""}
    assert _plan(raw)["owner_mailing"] is None


def test_acres_from_prop_size():
    assert P.acres_from("0.94 AC") == 0.94 and P.acres_from("0.00 AC") is None and P.acres_from(None) is None


# ---- map_account_ids_to_parcels ---------------------------------------------------------------------
def _q(map_number):
    return {"qpaybill_roll": {"identification_no": "000789", "detail": {"map_number": map_number}}}


def test_laurens_account_number_becomes_the_tms_from_the_block():
    assert M.laurens_rule("SC", "Laurens", "000789", _q("094-00-00-036.002")) == "094-00-00-036.002"
    assert M.laurens_rule("SC", "Laurens County", "944994", _q("083-00-00-006.001")) == "083-00-00-006.001"


def test_laurens_rule_leaves_real_tms_ids_other_counties_and_bad_map_numbers_alone():
    assert M.laurens_rule("SC", "Laurens", "094-00-00-036", _q("094-00-00-036.002")) is None    # already a TMS
    assert M.laurens_rule("SC", "Greenville", "000789", _q("094-00-00-036.002")) is None
    assert M.laurens_rule("NC", "Laurens", "000789", _q("094-00-00-036.002")) is None
    assert M.laurens_rule("SC", "Laurens", "000789", _q("683-00-00-005LH")) is None            # not TMS shaped
    assert M.laurens_rule("SC", "Laurens", "000789", {}) is None


def test_rutherford_pin_maps_to_the_reid_only_when_the_bag_is_the_rows_own_parcel():
    bag = {"PIN": "1549378423", "LEGACY_PIN": "1549103784230000", "REID": "419510"}
    cache = {"419510": {"owner": "BRISTOL"}}
    look = lambda pid: cache.get(pid)                                              # noqa: E731
    assert M.rutherford_rule("NC", "Rutherford", "1549378423", {"gis_attrs_full": bag}, look) == ("419510", "resolved")
    assert M.rutherford_rule("NC", "Rutherford", "1549-37-8423", {"gis_attrs_full": bag}, look)[0] == "419510"
    # the bag belongs to a DIFFERENT parcel (the coordinates were approximate): never trusted
    assert M.rutherford_rule("NC", "Rutherford", "1610224", {"gis_attrs_full": bag}, look) == (None, "bag_is_a_different_parcel")
    assert M.rutherford_rule("NC", "Rutherford", "1549378423", {}, look) == (None, "no_gis_bag")
    assert M.rutherford_rule("NC", "Rutherford", "419510", {"gis_attrs_full": bag}, look) == (None, "already_resolves")
    assert M.rutherford_rule("NC", "Rutherford", "1549378423", {"gis_attrs_full": bag}, lambda p: None)[1] == "reid_not_in_cache"
