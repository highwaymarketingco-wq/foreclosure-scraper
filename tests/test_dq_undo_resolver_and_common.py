"""undo_resolver_middle_conflicts (which committed name resolutions are PROVEN wrong), the RAW_KEEP guard every
apply path uses, and the Transylvania address-point row builder."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _dq_common as C  # noqa: E402
import build_transylvania_address_points as T  # noqa: E402
import undo_resolver_middle_conflicts as U  # noqa: E402


def _prov(query, matched, conf="strong", **kw):
    return {"queried": True, "confidence": conf, "matched_owner": matched, "query_name": query, **kw}


# ---- the judgement -------------------------------------------------------------------------------
def test_a_differing_middle_initial_on_both_sides_is_a_proven_conflict():
    assert U.judge(_prov("David Lee Evans", "EVANS DAVID N"), None, None)[0] == "conflict"
    assert U.judge(_prov("Lonnie B. Dawkins", "DAWKINS LONNIE F & SHIRLEY D"), None, None)[0] == "conflict"
    assert U.judge(_prov("Luis A Belteton Morales", "MORALES LUIS VICENTE"), None, None)[0] == "conflict"


def test_a_spelled_out_middle_name_that_differs_is_a_proven_conflict():
    assert U.judge(_prov("James Quentin Kirby", "KIRBY JAMES HUNTER"), None, None)[0] == "conflict"


def test_matching_initials_or_a_missing_middle_prove_nothing():
    assert U.judge(_prov("James R Smith", "SMITH JAMES ROBERT"), None, None)[0] == "agrees"
    assert U.judge(_prov("James Smith", "SMITH JAMES R"), None, None)[0] == "unverified"
    assert U.judge(_prov("James R Smith", "SMITH JAMES"), None, None)[0] == "unverified"


def test_a_different_name_altogether_is_not_a_middle_conflict():
    assert U.judge(_prov("Maria Garcia", "GARCIA JOSE"), None, None)[0] == "different_name"
    assert U.judge(_prov("x", ""), None, None)[0] == "no_matched_owner"


def test_the_leads_own_defendant_or_owner_name_is_used_when_no_query_name_was_stored():
    p = {"queried": True, "confidence": "unique_match", "matched_owner": "EVANS DAVID N"}
    assert U.judge(p, None, "David Lee Evans")[0] == "conflict"
    assert U.judge(p, "David Lee Evans", None)[0] == "conflict"
    assert U.judge(p, "David N Evans", "David Lee Evans")[0] == "conflict"   # the defendant conflicts even if the owner agrees


def test_only_commit_confidences_are_reviewed():
    assert U.COMMIT == {"exact", "strong", "unique_match"}
    assert "ambiguous_multi_parcel" not in U.COMMIT and "no_match" not in U.COMMIT


# ---- who owns the parcel and street fields ----------------------------------------------------------
def test_a_lead_from_a_name_only_source_owns_nothing_native_and_may_be_blanked():
    rates = {"counties_sc.sc_public_index": 0.06, "counties_sc.spartanburg_vacant": 1.0, "counties_nc.nc_ecourts_judgments": 0.14}
    assert U.is_resolver_owned("counties_sc.sc_public_index", None, rates)
    assert U.is_resolver_owned("counties_sc.sc_public_index", [{"source": "counties_nc.nc_ecourts_judgments"}], rates)


def test_a_lead_merged_with_a_parcel_native_source_is_only_flagged():
    rates = {"counties_sc.sc_public_index": 0.06, "counties_sc.spartanburg_vacant": 1.0}
    assert not U.is_resolver_owned("counties_sc.spartanburg_vacant", None, rates)
    assert not U.is_resolver_owned("counties_sc.sc_public_index", [{"source": "counties_sc.spartanburg_vacant"}], rates)


def test_owned_removal_lists_only_what_is_present_and_owner_only_when_it_is_the_matched_owner():
    row = {"parcel_id": "712", "street_address": "9 OAK ST", "market_value": 100.0, "living_sqft": 0, "owner_name": "EVANS DAVID N",
           "acreage": None}
    out = U.owned_removal(row, "EVANS DAVID N")
    assert out == {"parcel_id": "712", "street_address": "9 OAK ST", "market_value": 100.0, "owner_name": "EVANS DAVID N"}
    assert "owner_name" not in U.owned_removal({**row, "owner_name": "SOMEONE ELSE"}, "EVANS DAVID N")


# ---- the RAW_KEEP guard -------------------------------------------------------------------------------
def test_missing_raw_keep_finds_keys_write_artifact_would_silently_drop():
    assert C.missing_raw_keep(["owner_mailing", "resolved_from_name", "parcel_from_geo"]) == []
    assert C.missing_raw_keep(["definitely_not_a_registered_raw_key"]) == ["definitely_not_a_registered_raw_key"]


def test_require_raw_keep_refuses_with_an_actionable_message():
    try:
        C.require_raw_keep(["definitely_not_a_registered_raw_key"])
    except SystemExit as e:
        assert "RAW_KEEP" in str(e) and "definitely_not_a_registered_raw_key" in str(e)
    else:
        raise AssertionError("expected SystemExit")


def test_county_in_state_is_the_guard_against_reading_another_states_parcels():
    assert C.county_in_state("Buncombe County", "NC") and not C.county_in_state("Buncombe", "SC")
    assert C.county_in_state("Cherokee", "NC") and C.county_in_state("Cherokee", "SC")
    assert not C.county_in_state("Statewide", "NC") and not C.county_in_state(None, "SC")


# ---- the Transylvania address-point builder -----------------------------------------------------------
def test_build_rows_keeps_single_address_parcels_and_drops_duplexes():
    feats = [
        {"attributes": {"PARCELNUM": "9506212520000", "FULLADDR": "70 ABERDEEN LN", "POSTALCOM": "PISGAH FOREST", "POSTALZIP": "28768"}},
        {"attributes": {"PARCELNUM": "8523513477000", "FULLADDR": "1575 BLUE RIDGE RD", "POSTALCOM": "LAKE TOXAWAY", "POSTALZIP": "28747"}},
        {"attributes": {"PARCELNUM": "8523513477000", "FULLADDR": "1577 BLUE RIDGE RD", "POSTALCOM": "LAKE TOXAWAY", "POSTALZIP": "28747"}},
        {"attributes": {"PARCELNUM": "", "FULLADDR": "1 NOWHERE LN"}},
    ]
    rows = T.build_rows(feats)
    assert rows == {"9506212520000": ("70 ABERDEEN LN", "Pisgah Forest", "28768")}
