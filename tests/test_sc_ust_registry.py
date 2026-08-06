"""SC DES UST registry — the SC contamination spine and Union's first real source.

One statewide search returns all 7 SC footprint counties. Union SC is blocked or
empty on five of six signals in the coverage matrix; this is the first source it
has. 39 rows name an estate as owner of record, which is a probate signal no
probate source in the engine reaches.
"""
from __future__ import annotations

import foreclosure_scraper.scrapers.counties_sc.sc_ust_registry as S


def _cells(owner="SMITH JOHN", addr="123 MAIN ST", county="Union"):
    return ["FACILITY NAME", owner, addr, "WHITMIRE", county, "UST01234", "3", "Details"]


def test_real_estate_company_is_not_flagged_as_a_decedent_estate():
    """'COASTAL REAL ESTATE OF SC LLC' contains 'ESTATE OF' and is a company.
    A bare match flags it as probate, which is simply wrong."""
    assert not S._ESTATE.search("COASTAL REAL ESTATE OF SC LLC")
    assert not S._ESTATE.search("REAL ESTATE OF NC INC")


def test_genuine_estates_are_flagged():
    for n in ("ESTATE OF ALLIE M GRAHAM", "SMITH HEIRS", "JONES HEIR",
              "DECEASED OWNER"):
        assert S._ESTATE.search(n), n


def test_estate_flag_lands_on_the_lead():
    li = S._to_listing(_cells(owner="ESTATE OF ALLIE M GRAHAM"), "Union")
    assert li.raw["sc_ust_registry"]["estate_owned"] is True
    li2 = S._to_listing(_cells(owner="WILLARD OIL CO INC"), "Union")
    assert li2.raw["sc_ust_registry"]["estate_owned"] is False


def test_no_phone_or_email_is_ever_stored():
    """Each row links a Details page carrying Tank Owner Phone — present on 30 of
    30 sampled. We fetch the list only; contact data belongs to skip-trace under
    its own DNC rules, not to a source reader."""
    li = S._to_listing(_cells(), "Union")
    keys = {k.lower() for k in li.raw["sc_ust_registry"]}
    assert not any("phone" in k or "email" in k for k in keys)


def test_only_one_request_per_county_no_per_row_detail_fetch():
    """The guarantee that keeps 3,000+ phone numbers out of the board: exactly
    one POST per county, and nothing that fetches a per-row Details page."""
    import inspect
    code = inspect.getsource(S._one_county) + inspect.getsource(S._to_listing)
    assert code.count("c.post(") == 1, "more than one request per county"
    assert "c.get(" not in code, "a per-row fetch would reach the Details page"


def test_a_row_without_an_address_is_dropped():
    assert S._to_listing(_cells(addr="  "), "Union") is None


def test_a_short_row_is_dropped_not_misparsed():
    assert S._to_listing(["only", "three", "cells"], "Union") is None


def test_all_seven_sc_footprint_counties_are_declared():
    assert set(S.COUNTIES) == {"Spartanburg", "Anderson", "Pickens", "Laurens",
                               "Oconee", "Cherokee", "Union"}


def test_row_maps_to_a_usable_lead():
    li = S._to_listing(_cells(), "Union")
    assert li.state == "SC" and li.county == "Union"
    assert li.street_address == "123 MAIN ST"
    assert li.owner_name == "SMITH JOHN"
    assert li.case_number == "UST01234"
    assert li.foreclosure_process == "contamination"
