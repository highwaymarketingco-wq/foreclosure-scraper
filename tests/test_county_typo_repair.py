"""County repair must never file a lead in the wrong county.

`county` drives routing, scope_repass and every per-county count. 1,815 board rows
(all from the builder-typed liensnc pool) carry a value that is not a real county,
spread over 425 distinct spellings. Recovering them is worth doing, but a WRONG
county is worse than an unroutable one: it passes scope_repass and lands a lead in a
county the operator does not work.

These tests pin the two failure modes that matter, both found in the real data:

  * "Stanley" fuzzy-matches the real county "Stanly" at 92 -- but the town of Stanley
    sits on the Gaston/Lincoln line, ~90 miles from Stanly County.
  * "Leland" fuzzy-matches "Cleveland" at 80 -- but Leland is a town in Brunswick.

So the resolution order is city-lookup, then explicit seat table, then fuzzy at a
threshold chosen from the real values (85), and anything left is CLEARED rather than
guessed. Loosening the threshold is what breaks it: at 80, Leland goes to Cleveland.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "county_repair",
    Path(__file__).resolve().parent.parent / "scripts" / "repair_county_typos_and_towns.py",
)
cr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cr)

_NO_CITY = lambda _c: None  # noqa: E731 -- force the seat/fuzzy paths


@pytest.mark.parametrize("bad,expect", [
    # "Stanley" is NOT here any more. It used to assert Gaston, which is what a flat
    # seat lookup returns -- and the live board then showed 41 of its 43 rows carry a
    # STANLY-County city (35x Albemarle, Stanly's own seat). The name is ambiguous, so
    # it is arbitrated by the row's city and cleared when the city cannot corroborate;
    # see test_stanley_is_decided_by_the_rows_own_city below. This test kept passing
    # while the behaviour it pinned was wrong on 95% of the real rows, which is why the
    # expectations here are now anchored to measured counts rather than to plausibility.
    ("Leland", "Brunswick"),        # NOT Cleveland
    ("Rutherfordton", "Rutherford"),
    ("Hendersonville", "Henderson"),
    ("Lincolnton", "Lincoln"),
    ("Marion", "Mcdowell"),
    ("Columbus", "Polk"),
])
def test_town_names_resolve_to_their_actual_county(bad, expect):
    got, how = cr.resolve(bad, "NC", None, _NO_CITY)
    assert got == expect, f"{bad!r} -> {got!r} via {how}"
    assert how in ("seat_lookup", "city_field", "town_via_resolver")


@pytest.mark.parametrize("typo,expect", [
    ("Bumcombe", "Buncombe"), ("Buncombee", "Buncombe"), ("Buncomb", "Buncombe"),
    ("Bucombe", "Buncombe"), ("Buncome", "Buncombe"),
    ("Mecklenberg", "Mecklenburg"), ("Mcklenburg", "Mecklenburg"),
    ("Mechlenburg", "Mecklenburg"), ("Mecklinburg", "Mecklenburg"),
    ("Meckenburg", "Mecklenburg"), ("Mecklemburg", "Mecklenburg"),
    ("Guiford", "Guilford"), ("Guildford", "Guilford"),
    ("Forstyh", "Forsyth"), ("Forsythe", "Forsyth"),
    ("Catwaba", "Catawba"), ("Catawaba", "Catawba"),
    ("Cabarras", "Cabarrus"), ("Cabbarus", "Cabarrus"), ("Carbarrus", "Cabarrus"),
    ("New Hannover", "New Hanover"), ("North Hampton", "Northampton"),
    ("Watagua", "Watauga"), ("Cateret", "Carteret"), ("Yancy", "Yancey"),
    ("Hatwood", "Haywood"),
])
def test_real_misspellings_recover(typo, expect):
    """Every one of these is an actual value on the board."""
    got, how = cr.resolve(typo, "NC", None, _NO_CITY)
    assert got == expect, f"{typo!r} -> {got!r} via {how}"


def test_stanly_the_real_county_is_left_alone():
    """The guard must not make the genuine county unrecognisable."""
    assert cr.is_real("Stanly", "NC") is True
    assert cr.is_real("Stanley", "NC") is False


@pytest.mark.parametrize("name,state", [
    ("Wake", "NC"), ("Mecklenburg", "NC"), ("Durham", "NC"),   # real, out of footprint
    ("Buncombe", "NC"), ("Spartanburg", "SC"), ("Charleston", "SC"),
])
def test_real_counties_are_never_touched(name, state):
    """is_real must use the OFFICIAL county list, not the footprint -- an
    out-of-footprint but genuine county is not junk to be repaired."""
    assert cr.is_real(name, state) is True


def test_unresolvable_is_cleared_not_guessed():
    """An honest None beats a confident wrong county."""
    got, how = cr.resolve("Zzzqqx", "NC", None, _NO_CITY)
    assert got is None
    assert how == "cleared"


def test_the_city_field_wins_over_fuzzy():
    """A row whose own city resolves is authoritative; fuzzy must not override it."""
    got, how = cr.resolve("Bumcombe", "NC", "Gaffney", lambda c: "Cherokee" if c == "Gaffney" else None)
    assert got == "Cherokee"
    assert how == "city_field"


def test_lowering_the_threshold_would_reintroduce_the_leland_bug():
    """Documents WHY the threshold is 85. Leland/Cleveland scores 80, so an 80
    threshold files Brunswick rows in Cleveland. If someone lowers it, this fails."""
    from rapidfuzz import fuzz
    assert 78 <= fuzz.ratio("leland", "cleveland") < 85
    assert "leland" in cr.TOWN_NOT_COUNTY   # belt and braces even if the score moves


# ---------------------------------------------------------------------------
# COMPLETENESS. The tests above sampled six counties and passed while the list
# was missing one, so sampling is not the guard -- these three are.
#
# The omission was "polk", a FOOTPRINT county. It did not fail loudly: a real
# county absent from NC_ALL is judged not-a-real-county, falls through to fuzzy
# (which cannot match a name absent from its own pool) and is CLEARED. The
# dry run was about to blank `county` on 1,217 rows.
# ---------------------------------------------------------------------------

def test_nc_list_holds_all_one_hundred_counties():
    assert len(cr.NC_ALL) == 100, (
        f"NC has 100 counties, NC_ALL has {len(cr.NC_ALL)}. A missing county is "
        f"silently CLEARED on every row that carries it."
    )


def test_sc_list_holds_all_forty_six_counties():
    assert len(cr.SC_ALL) == 46, (
        f"SC has 46 counties, SC_ALL has {len(cr.SC_ALL)}."
    )


def test_every_footprint_county_is_recognised_as_real():
    """THE guard. Anchored to the repo's own county config rather than to a list
    typed by hand, so it cannot drift out of step with the footprint. A footprint
    county missing here means the engine erases the county on the operator's own
    leads."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from foreclosure_scraper import config

    missing = [f"{c.state.upper()} {c.name}" for c in config.ALL_COUNTIES
               if not cr.is_real(c.name, c.state)]
    assert not missing, f"footprint counties treated as junk and cleared: {missing}"


def test_polk_the_county_that_was_missing():
    """Regression pin for the specific omission, with its town seats, which are
    what makes Polk easy to leave out: Columbus and Tryon are both in Polk."""
    # is_real is the gate the caller checks BEFORE resolve(), so a True here is
    # what keeps Polk rows from ever entering the repair path. Asserting anything
    # about resolve("Polk") would be asserting a tautology -- it is never called.
    assert cr.is_real("Polk", "NC") is True
    assert cr.is_real("Polk County", "NC") is True
    assert cr.SEAT_TO_COUNTY["columbus"] == ("Polk", "NC")
    assert cr.SEAT_TO_COUNTY["tryon"] == ("Polk", "NC")


# ---------------------------------------------------------------------------
# AMBIGUOUS names: a value that is both a real town and a plausible misspelling
# of a DIFFERENT real county. Measured on the live board: "Stanley" was on 43
# rows and 41 carried a STANLY-County city (35x Albemarle, Stanly's own seat,
# and 6x Locust). A flat seat lookup sent all 43 to Gaston -- a wrong county,
# which passes scope_repass and lands the lead in a county nobody works.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("city,expect", [
    ("Albemarle", "Stanly"),      # 35 real rows -- Stanly's county seat
    ("Locust", "Stanly"),         # 6 real rows
    ("Oakboro", "Stanly"),
    ("Norwood", "Stanly"),
    ("Stanley", "Gaston"),        # 2 real rows -- the town itself
    ("Mount Holly", "Gaston"),
    ("GASTONIA", "Gaston"),       # case must not matter
])
def test_stanley_is_decided_by_the_rows_own_city(city, expect):
    got, how = cr.resolve("Stanley", "NC", city, _NO_CITY)
    # Two legitimate paths reach the same county: the city-side seat lookup fires
    # first for cities that happen to be in SEAT_TO_COUNTY (Stanley, Gastonia), and
    # the ambiguity table handles the rest. What must hold is the COUNTY.
    assert got == expect, f"city={city!r} -> {got!r} via {how}"
    assert how in ("city_via_seat_table", "ambiguous_city_decided", "city_field")


@pytest.mark.parametrize("city", [None, "", "4625 Wolf pond rd", "Nowhereville"])
def test_stanley_with_no_usable_city_is_cleared_not_guessed(city):
    """No corroboration means no guess. Missing beats wrong.

    "Charlotte" is deliberately NOT in this list: a row reading county='Stanley'
    city='Charlotte' resolves to Mecklenburg, because the city is authoritative and
    Charlotte is unambiguous. That is a recovery, not a failure to guess."""
    got, how = cr.resolve("Stanley", "NC", city, _NO_CITY)
    assert got is None
    assert how == "cleared_ambiguous"


def test_a_known_city_outranks_the_ambiguous_county_string():
    assert cr.resolve("Stanley", "NC", "Charlotte", _NO_CITY) == ("Mecklenburg", "city_via_seat_table")


def test_the_unambiguous_seats_still_resolve():
    """The ambiguity guard must not cost the cases that were already right --
    Leland/Winnabow are both Brunswick, Rutherfordton is Rutherford's seat."""
    assert cr.resolve("Leland", "NC", "Winnabow", _NO_CITY) == ("Brunswick", "seat_lookup")
    assert cr.resolve("Lincolnton", "NC", "Denver", _NO_CITY) == ("Lincoln", "seat_lookup")
    # Rutherfordton resolves via the CITY side of the seat table, since the city and
    # the bad county value are the same string here. Same county, earlier path.
    assert cr.resolve("Rutherfordton", "NC", "Rutherfordton", _NO_CITY) == (
        "Rutherford", "city_via_seat_table")
    assert cr.resolve("Rutherfordton", "NC", None, _NO_CITY) == ("Rutherford", "seat_lookup")


# ---------------------------------------------------------------------------
# PARSED LEGAL PROSE. The largest group of unresolvable values was never typos:
# it is deed/plat language the re-parse captured into `county`, with the county
# name sitting inside the string. Counts are from the live board 2026-09-10.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prose,expect", [
    ("In The Harnett", "Harnett"),                                  # 37 rows
    ("In The Nash", "Nash"),                                        # 30
    ("In The Duplin", "Duplin"),                                    # 29
    ("In The Catawba", "Catawba"),                                  # 27
    ("In The Rowan", "Rowan"),                                      # 27
    ("In The Brunswick", "Brunswick"),                              # 22
    ("Parcel In Wake", "Wake"),                                     # 15
    ("In The Office Of The Register Of Deeds For Columbus", "Columbus"),   # 15
    ("In The Register Of Deeds Office For Nash", "Nash"),            # 15
    ("-J In The Wayne", "Wayne"),                                   # 14
    ("With The Pitt", "Pitt"),                                      # 11
    ("E In The Craven", "Craven"),                                  # 10
    ("Of Pitt", "Pitt"),                                            # 7
    ("Which Said Plat Is Now On File In The Office Of The Register Of Deeds Of Durham",
     "Durham"),                                                     # 7
])
def test_a_county_named_inside_prose_is_recovered(prose, expect):
    got, how = cr.resolve(prose, "NC", None, _NO_CITY)
    assert (got, how) == (expect, "county_inside_prose")


def test_prose_naming_two_counties_is_not_guessed():
    """"...for Union recorded in Lee" names two. Picking one would be a coin flip."""
    got, how = cr.resolve("Deeds For Union Recorded In Lee", "NC", None, _NO_CITY)
    assert got is None and how == "cleared"


def test_a_bare_ambiguous_name_does_not_use_the_prose_path():
    """The prose scan is MULTI-TOKEN only. A bare "Columbus" is genuinely
    ambiguous -- Polk's county seat vs Columbus County -- and must keep falling
    through rather than being read as the county."""
    got, how = cr.resolve("Columbus", "SC", None, _NO_CITY)
    assert got is None
    assert how != "county_inside_prose"


def test_prose_respects_the_rows_state():
    """"In The York" is York County SC, and must not resolve while the row says NC,
    because there is no York County in North Carolina."""
    assert cr.resolve("In The York", "SC", None, _NO_CITY) == ("York", "county_inside_prose")
    assert cr.resolve("In The York", "NC", None, _NO_CITY)[0] is None


@pytest.mark.parametrize("abbrev,expect", [("Meck", "Mecklenburg"), ("meck", "Mecklenburg")])
def test_abbreviations_fuzzy_cannot_reach(abbrev, expect):
    """"meck" scores 44 against "mecklenburg" -- far below any threshold that is
    safe for real misspellings -- so it needs an explicit entry. 25 rows."""
    from rapidfuzz import fuzz
    assert fuzz.ratio("meck", "mecklenburg") < 85
    assert cr.resolve(abbrev, "NC", None, _NO_CITY) == (expect, "abbrev")


def test_the_rows_city_is_consulted_against_the_seat_table_too():
    """`upstate_county_for` knows Upstate SC and Western NC only, so rows whose city
    lies outside that window (Albemarle, Old Fort, Raleigh) used to fall through to
    guessing from the misspelled county string. 'Mcdonnell' scores 71 against
    'mcdowell' -- unreachable by fuzzy -- but its rows carry city='Old Fort', which
    is in McDowell."""
    assert cr.resolve("Mcdonnell", "NC", "Old Fort", _NO_CITY) == ("Mcdowell", "city_via_seat_table")
    assert cr.resolve("Zzzqqx", "NC", "Raleigh", _NO_CITY) == ("Wake", "city_via_seat_table")


def test_a_garbage_city_does_not_produce_a_county():
    """One real row carries city='4625 Wolf pond rd'. It must match nothing."""
    assert cr.resolve("Zzzqqx", "NC", "4625 Wolf pond rd", _NO_CITY) == (None, "cleared")


def test_lenior_stays_cleared_because_it_names_two_places():
    """The CITY of Lenoir is in CALDWELL County; Lenoir County is 200 miles east.
    'Lenior' scores 83 against 'lenoir', just under the 85 threshold, so it clears --
    the correct outcome, and the reason the threshold is not loosened."""
    from rapidfuzz import fuzz
    assert 80 <= fuzz.ratio("lenior", "lenoir") < 85
    assert cr.resolve("Lenior", "NC", None, _NO_CITY) == (None, "cleared")
