"""The Burke storm-damage parcel repair must only touch junk record numbers and must never
trust a parcel whose own situs disagrees with the lead's street address."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from repair_burke_storm_damage_parcels import addresses_agree, is_junk_burke_id  # noqa: E402

SRC = "counties_nc.burke_storm_damage"


def test_short_record_numbers_on_the_storm_source_are_junk():
    for pid in ("1", "4821", "99999", "123456"):
        assert is_junk_burke_id(SRC, "NC", "Burke", pid)


def test_real_pins_and_other_sources_and_counties_are_left_alone():
    assert not is_junk_burke_id(SRC, "NC", "Burke", "2711234567")          # a real 10-digit PIN
    assert not is_junk_burke_id(SRC, "NC", "Burke", "")
    assert not is_junk_burke_id(SRC, "NC", "Burke", None)
    assert not is_junk_burke_id("counties_nc.nc_ptscloud_delinquent_tax", "NC", "Burke", "4821")
    assert not is_junk_burke_id(SRC, "NC", "Caldwell", "4821")
    assert not is_junk_burke_id(SRC, "SC", "Burke", "4821")
    assert not is_junk_burke_id(SRC, "NC", "Burke", "12AB")                # not all digits


def test_same_house_number_and_a_shared_street_word_agrees():
    assert addresses_agree("101 Woodsway Ln", "101 WOODSWAY LN")
    assert addresses_agree("2201 N Main St", "2201 MAIN ST")               # direction and suffix ignored
    assert addresses_agree("55 Old Mill Rd, Morganton", "55 OLD MILL ROAD")


def test_a_neighbours_parcel_does_not_agree():
    assert not addresses_agree("101 Woodsway Ln", "103 WOODSWAY LN")       # wrong house number
    assert not addresses_agree("101 Woodsway Ln", "101 CEDAR CT")          # right number, wrong street


def test_a_missing_side_never_agrees():
    assert not addresses_agree("", "101 WOODSWAY LN")
    assert not addresses_agree("101 Woodsway Ln", None)
    assert not addresses_agree("Woodsway Ln", "101 WOODSWAY LN")           # no house number to compare


import sqlite3

from repair_burke_storm_damage_parcels import resolve_by_address  # noqa: E402


def _cache(rows):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE parcels (id TEXT, address TEXT)")
    con.executemany("INSERT INTO parcels VALUES (?, ?)", rows)
    return con


def test_a_unique_address_match_resolves_to_the_10_digit_pin():
    con = _cache([("2711234567", "101 WOODSWAY LN"), ("271123456700000", "101 WOODSWAY LN"),
                  ("2711999999", "103 WOODSWAY LN")])
    assert resolve_by_address(con, "101 Woodsway Ln") == ("unique", "2711234567")


def test_two_parcels_at_one_address_is_ambiguous_not_guessed():
    con = _cache([("2711234567", "101 N MAIN ST"), ("2711234568", "101 S MAIN ST")])
    assert resolve_by_address(con, "101 Main St")[0] == "ambiguous"


def test_no_matching_parcel_and_no_street_are_reported_not_resolved():
    con = _cache([("2711234567", "101 WOODSWAY LN")])
    assert resolve_by_address(con, "500 Nowhere Rd") == ("none", None)
    assert resolve_by_address(con, "Woodsway Ln") == ("no_street", None)
    assert resolve_by_address(con, "") == ("no_street", None)
