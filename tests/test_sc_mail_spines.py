"""SC mail spines — Oconee / Pickens / Anderson owner+mailing layers.

These are the three SC counties where owner mailing was thinnest. Each test
drives the REAL matcher/result-builder against a response saved off the live
layer (tests/fixtures/sc_*.json), so a field rename or a repoint that quietly
stops returning owners fails here instead of on the board.

Also pins the two shared-matcher fixes these counties exposed:
  * the situs candidate scan was capped at ONE page of 25 rows, while the broad
    street-word LIKE returns 44-900 rows on these layers, so the right parcel was
    usually past the cap and the lead resolved to nothing;
  * absentee was a bare substring test, which a padded / subdivision-prefixed
    situs ('SPRINGSIDE  300 SPRINGSIDE CIR', '535  PORTER RD') always failed —
    flagging owner-occupants as absentee, worth +8 distress and a HOT gate.

2026-09-30: Anderson's fixture (sc_anderson_county_parcels.json) was rebuilt
from a fresh live query after finding the spec's OWNER/OWNER_ADDR/CITY/ZIPCODE/
PREV_OWNER field names had drifted off the schema (confirmed independently
live, cross-referenced against enrichment_arcgis.py's SC_GIS["Anderson"] from
commit 55f6d2a1). Anderson is now wired situs+value-only in COUNTY_GIS (no
`owner`/`mail` fields at all — TAXOWNSTR is the only owner-shaped column and is
confirmed always-null), and the old owner/mailing-focused Anderson tests below
are replaced with tests pinning: (a) the situs+value-only shape, and (b) that
_build_result's gate no longer discards a matched row just because owner and
mailing are both empty.

PRIVACY: all three specs enumerate outFields; none uses `*`, and none of these
layers carries a phone / e-mail / account / SSN / DOB column.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from foreclosure_scraper.enrichment_owner_mailing import (
    COUNTY_GIS,
    _build_result,
    _clean_mailing,
    _has_house_number,
    _is_absentee,
    _match_attrs,
    _norm,
    _scan,
)
from tests._arcgis_fakes import FakeHttp

FIXTURES = Path(__file__).parent / "fixtures"

OCONEE = COUNTY_GIS["SC:Oconee"]
PICKENS = COUNTY_GIS["SC:Pickens"]
ANDERSON = COUNTY_GIS["SC:Anderson"]


def _rows(name: str) -> list[dict]:
    payload = json.loads((FIXTURES / name).read_text())
    return [f["attributes"] for f in payload["features"]]


class Lead:
    """Minimal Listing stand-in — the matcher only reads these attributes."""

    def __init__(self, *, county, state, parcel_id=None, street_address=None):
        self.county = county
        self.state = state
        self.parcel_id = parcel_id
        self.street_address = street_address
        self.zip_code = None
        self.raw: dict = {}


# --------------------------------------------------------------- config shape

def test_all_three_sc_spines_enumerate_out_fields_and_never_use_star():
    for key in ("SC:Oconee", "SC:Pickens", "SC:Anderson"):
        of = COUNTY_GIS[key].get("out_fields")
        assert of, f"{key} must enumerate outFields"
        assert "*" not in of, f"{key} must never request outFields=*"


def test_no_sc_spine_requests_a_contact_or_identity_column():
    banned = ("phone", "email", "mail_addr_e", "ssn", "dl_", "dob", "birth",
              "pocphone", "pocemail", "account_no", "acct_no")
    for key in ("SC:Oconee", "SC:Pickens", "SC:Anderson"):
        of = COUNTY_GIS[key]["out_fields"].lower()
        assert not [b for b in banned if b in of], key


def test_oconee_points_at_the_assessor_table_not_the_owner_less_parcel_layer():
    # Oconee's parcel layers (CitizenServe/1, Parcels_OpenData/0) carry NO owner
    # and NO mailing; the assessor table is the county's only mail spine.
    assert OCONEE["url"].endswith("/CitizenServe/MapServer/5")
    assert OCONEE["parcel"] == "pin"
    assert OCONEE["situs"] == []          # no situs column exists -> parcel-only
    assert OCONEE["order_by"] == "pin"    # objectIdField is null on this table


def test_anderson_spine_is_wired_and_is_a_parcel_layer_not_a_utility_table():
    assert "County_Parcels/FeatureServer/0" in ANDERSON["url"]
    # situs+value ONLY (2026-09-30): OWNER/OWNER_ADDR/CITY/ZIPCODE no longer
    # exist on the live schema -- TAXOWNSTR is the only owner-shaped column
    # left and is confirmed always-null, so it is deliberately not wired here
    # (same call enrichment_arcgis.py's SC_GIS["Anderson"] made).
    assert ANDERSON["owner"] == []
    assert ANDERSON["mail"] == []
    assert ANDERSON["situs"] == ["PHYS_ADDR"]
    assert ANDERSON["parcel"] == "TMS"
    assert "OWNER" not in ANDERSON["out_fields"]  # would silently no-op if requested
    assert "MRKT_VALUE" in ANDERSON["out_fields"]


# ------------------------------------------------------------ result building

def test_oconee_row_yields_owner_mailing_parcel_and_state():
    li = Lead(county="Oconee", state="SC", parcel_id="500-23-01-004")
    res = _build_result(li, OCONEE, _rows("sc_oconee_citizenserve_assessor.json")[0])
    assert res["owner"] == "LEWIS DEBRA GILLESPIE"
    assert res["mailing"] == "310 JAYNES ST WALHALLA SC 29691"
    assert res["parcel_id"] == "500-23-01-004"   # space padding stripped
    assert res["mail_state"] == "SC"             # recovered from the mailing tail
    assert res["out_of_state"] is False


def test_pickens_zip_plus_four_is_not_mailed_as_a_nine_digit_run_on():
    rows = {r["PIN"]: r for r in _rows("sc_pickens_parcels_locadd.json")}
    li = Lead(county="Pickens", state="SC", street_address="535 Porter Rd")
    res = _build_result(li, PICKENS, rows["4063-00-69-0900"])
    assert res["mailing"] == "535 PORTER RD PENDLETON SC 29670"   # ZIP was 296700000
    # real ZIP+4 keeps both halves, hyphenated
    res2 = _build_result(li, PICKENS, rows["4099-00-73-5178"])
    assert res2["mailing"].endswith("29657-9243")                 # ZIP was 296579243


def test_anderson_row_yields_situs_and_market_value_with_no_owner_or_mailing():
    # 2026-09-30: live-verified — OWNER/OWNER_ADDR/CITY/ZIPCODE/PREV_OWNER no
    # longer exist on this layer's schema, so owner/mailing are genuinely
    # unavailable here (not a bug in this test's fixture). The row must still
    # resolve — this is the core fix: before it, the empty owner+mailing
    # tripped the gate and the whole row (including situs and value) was
    # silently discarded.
    li = Lead(county="Anderson", state="SC", street_address="300 Springside Cir")
    res = _build_result(li, ANDERSON, _rows("sc_anderson_county_parcels.json")[0])
    assert res is not None, "situs+value match must not be discarded for missing owner/mailing"
    assert res["owner"] is None
    assert res["mailing"] is None
    assert res["situs"].startswith("SPRINGSIDE")
    assert "300 SPRINGSIDE CIR" in res["situs"]
    assert res["parcel_id"] == "692401005"
    assert res["_value"] == 225270.0          # MRKT_VALUE feeds the proxy-ARV
    assert "previous_owner" not in res["_distress"]  # PREV_OWNER no longer queried
    assert res["absentee"] is False           # no mailing to compare -> never flagged
    assert res["out_of_state"] is False


def test_anderson_value_only_match_also_survives_the_gate():
    # A synthetic row with a real value but a blank/garbage situs string (e.g. a
    # layer quirk, or a lead with no street_address to match on so only the
    # parcel-id path ran) must still count as a match -- value alone is
    # sufficient evidence, mirroring the situs-alone case above.
    attrs = {"TMS": "692401099", "PHYS_ADDR": "   ", "MRKT_VALUE": 198000,
             "SALE_PRICE": 150000, "SALE_YEAR": 2021, "DBOOK": "1", "DPAGE": "2",
             "TAXOWNSTR": None}
    res = _build_result(Lead(county="Anderson", state="SC"), ANDERSON, attrs)
    assert res is not None
    assert res["owner"] is None
    assert res["mailing"] is None
    assert not res["situs"]                   # blank/whitespace-only situs
    assert res["_value"] == 198000.0


def test_anderson_row_with_nothing_usable_is_still_discarded():
    # The gate widening must not turn into "always accept a match": a row with
    # no owner, no mailing, no situs and no extractable value is genuinely
    # useless and should still be dropped.
    attrs = {"TMS": "692401099", "PHYS_ADDR": "", "MRKT_VALUE": None}
    assert _build_result(Lead(county="Anderson", state="SC"), ANDERSON, attrs) is None


# ------------------------------------------------------------------- absentee

def test_anderson_absentee_is_never_flagged_now_that_it_has_no_mailing_field():
    # Anderson's subdivision-prefixed situs ('SPRINGSIDE  300 SPRINGSIDE CIR')
    # used to be compared against a real OWNER_ADDR/CITY/ZIPCODE mailing string
    # (the token-subset regression this file originally pinned); that mailing
    # path no longer exists on the live schema, so absentee is trivially False
    # here (no mailing to compare against at all). The subdivision-prefix
    # token-subset logic itself is still pinned directly below
    # (test_absentee_subset_rule_needs_a_house_number_and_a_street_word) and by
    # Pickens' padded-situs case, so the original regression stays covered.
    res = _build_result(Lead(county="Anderson", state="SC"), ANDERSON,
                        _rows("sc_anderson_county_parcels.json")[0])
    assert res["situs"].startswith("SPRINGSIDE")
    assert res["absentee"] is False


def test_padded_situs_does_not_fake_an_absentee_owner():
    # Pickens LOCADD double-spaces the house number off the street name.
    rows = {r["PIN"]: r for r in _rows("sc_pickens_parcels_locadd.json")}
    res = _build_result(Lead(county="Pickens", state="SC"), PICKENS,
                        rows["4099-00-73-5178"])
    assert res["situs"] == "208  PORTER  RD"
    assert res["absentee"] is False


def test_a_real_absentee_owner_is_still_flagged():
    rows = {r["PIN"]: r for r in _rows("sc_pickens_parcels_locadd.json")}
    res = _build_result(Lead(county="Pickens", state="SC"), PICKENS,
                        rows["4099-00-72-7787"])          # situs 233 Porter Rd
    assert res["mailing"].startswith("PO BOX 1307")       # mails to an Easley PO box
    assert res["absentee"] is True


def test_absentee_subset_rule_needs_a_house_number_and_a_street_word():
    # Street words alone, in any order and with no house number, must NOT clear
    # the flag — only a numbered address is specific enough to be the property.
    assert _is_absentee("Oak Ridge Rd", "RD OAK RIDGE, ASHEVILLE NC 28801") is True
    assert _is_absentee("300 Springside Cir",
                        "300 SPRINGSIDE CIR ANDERSON SC 29625") is False
    assert _is_absentee("300 Springside Cir",
                        "999 OTHER RD ATLANTA GA 30301") is True


def test_norm_collapses_the_fixed_width_padding_these_rolls_ship():
    assert _norm("SPRINGSIDE        300 SPRINGSIDE CIR") == "springside 300 springside cir"
    assert _norm("208  PORTER  RD") == "208 porter rd"


# ------------------------------------------------------------ mailing cleanup

@pytest.mark.parametrize("raw,want", [
    ("535 PORTER RD PENDLETON SC 296700000", "535 PORTER RD PENDLETON SC 29670"),
    ("208 PORTER RD LIBERTY SC 296579243", "208 PORTER RD LIBERTY SC 29657-9243"),
    ("PO BOX 12 EASLEY SC 0", "PO BOX 12 EASLEY SC"),
    ("300 SPRINGSIDE CIR   ANDERSON  SC 29625", "300 SPRINGSIDE CIR ANDERSON SC 29625"),
    ("", ""),
])
def test_clean_mailing(raw, want):
    assert _clean_mailing(raw) == want


# ------------------------------------------------------- house-number matching

def test_house_number_must_be_a_whole_token():
    assert _has_house_number("144", "144 porter rd") is True
    assert _has_house_number("144", "springside 144 springside cir") is True
    assert _has_house_number("144", "1440 porter rd") is False   # was a false hit
    assert _has_house_number("144", "2144 porter rd") is False


# ----------------------------------------------------------- paged situs scan

def _page(rows: list[dict], *, exceeded: bool) -> dict:
    return {"features": [{"attributes": r} for r in rows],
            "exceededTransferLimit": exceeded}


def test_scan_pages_with_result_offset_and_a_sort_and_enumerated_fields(monkeypatch):
    import foreclosure_scraper.enrichment_owner_mailing as mod
    monkeypatch.setattr(mod, "_SITUS_PAGE", 2)
    monkeypatch.setattr(mod, "_SITUS_SCAN_CAP", 6)
    http = FakeHttp(pages=[
        _page([{"PIN": "a"}, {"PIN": "b"}], exceeded=True),
        _page([{"PIN": "c"}, {"PIN": "d"}], exceeded=True),
        _page([{"PIN": "e"}], exceeded=False),
    ])
    rows = asyncio.run(_scan(http, PICKENS, "UPPER(LOCADD) LIKE '%PORTER%'"))

    assert [r["PIN"] for r in rows] == ["a", "b", "c", "d", "e"]
    offsets = [c[2].get("resultOffset") for c in http.calls]
    assert offsets == [None, "2", "4"]                       # proper paging
    for _verb, _url, params in http.calls:
        assert params["orderByFields"] == "PIN"              # stable order
        assert params["outFields"] == PICKENS["out_fields"]  # never `*`
        assert params["resultRecordCount"] == "2"


def test_situs_match_finds_a_parcel_that_falls_past_the_first_page(monkeypatch):
    """The 25-row cap regression: the right parcel is only on page 2."""
    import foreclosure_scraper.enrichment_owner_mailing as mod
    monkeypatch.setattr(mod, "_SITUS_PAGE", 2)
    monkeypatch.setattr(mod, "_SITUS_SCAN_CAP", 10)
    wanted = {"PIN": "4099-00-73-5431", "NAME1": "PILGRIM MICHAEL BLAKE", "NAME2": " ",
              "ADD1": "188 PORTER RD", "CITY": "LIBERTY", "STATE": "SC",
              "ZIP": 296570000, "LOCADD": "188  PORTER  RD"}
    http = FakeHttp(pages=[
        _page([{"PIN": "x", "LOCADD": "535  PORTER RD"},
               {"PIN": "y", "LOCADD": "233  PORTER RD"}], exceeded=True),
        _page([{"PIN": "z", "LOCADD": "208  PORTER  RD"}, wanted], exceeded=False),
    ])
    li = Lead(county="Pickens", state="SC", street_address="188 Porter Rd")
    attrs = asyncio.run(_match_attrs(http, li, PICKENS))

    assert attrs is not None and attrs["PIN"] == "4099-00-73-5431"
    assert len(http.calls) == 2, "should have paged, not stopped after one page"


def test_situs_match_does_not_return_a_longer_house_number(monkeypatch):
    import foreclosure_scraper.enrichment_owner_mailing as mod
    monkeypatch.setattr(mod, "_SITUS_PAGE", 5)
    monkeypatch.setattr(mod, "_SITUS_SCAN_CAP", 5)
    http = FakeHttp(pages=[_page([{"PIN": "wrong", "LOCADD": "1440  PORTER RD"}],
                                 exceeded=False)])
    li = Lead(county="Pickens", state="SC", street_address="144 Porter Rd")
    assert asyncio.run(_match_attrs(http, li, PICKENS)) is None
