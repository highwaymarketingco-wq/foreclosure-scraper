"""Stale county-jail match invalidation (2026-10-03) -- same bug shape as
owner_name/bop_federal/enrichment_incarceration's own state-prison lane, found
in enrichment_jail_bookings.py during the same sweep: `match_rosters` and the
per-name SEARCH_ROSTERS lane both skip a listing the moment
raw['jail_booking'] is truthy, forever, so a later owner-name refresh (a sale,
an estate closing, a parcel_cache correction) never got reconciled against a
name-keyed match stamped against whoever used to own the parcel.

Live-checked 2026-10-03 against the real board (board_stream, read-only):
several county-jail-roster matches now name an unrelated entity -- e.g. a
Gaston County parcel matched "DEANA WILSON" but now reads "GASTONIA CITY OF";
an Anderson County parcel matched "USUF ABUZAHRI" but now reads
"ANDERSON CITY OF".

`_owner_still_supports_match` and `_clear_stale_matches` close it, mirroring
enrichment_bop_federal.py's (commit 9e3fd2c9) and
enrichment_incarceration.py's own fix for the identical shape, both landed the
same day. This file pins the real-world case that found it and proves
enrich_jail_bookings() clears + (when the county is covered) requeries
through the real pre-pass.

Network is faked throughout (`_load_roster` is monkeypatched to an empty
in-memory roster, same technique test_jail_bookings_laurens_oconee.py and
friends use for their own setup) -- nothing touches a live jail-roster vendor.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper import enrichment_jail_bookings as jb
from foreclosure_scraper.enrichment_jail_bookings import (
    _clear_stale_matches,
    _owner_still_supports_match,
    enrich_jail_bookings,
)
from foreclosure_scraper.models import Listing

DAC_SOURCE = "NC DAC offender search"
SCDC_SOURCE = "SC DOC inmate search"
BOP_SOURCE = "BOP inmate locator"


def _li(owner, state="NC", county="Gaston"):
    return Listing(source="test", source_url="http://x", state=state,
                   county=f"{county} County",
                   raw={"owner_mailing": {"owner": owner}})


# --------------------------------------------------------------------------- #
# _owner_still_supports_match                                                 #
# --------------------------------------------------------------------------- #

def test_owner_still_supports_match_true_when_name_unchanged():
    li = _li("WILSON DEANA")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    assert _owner_still_supports_match(li) is True


def test_owner_still_supports_match_false_when_current_owner_is_now_an_entity():
    # Real live example (Gaston County, 2026-10-03): owner changed to a city.
    li = _li("GASTONIA CITY OF")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    assert _owner_still_supports_match(li) is False


def test_owner_still_supports_match_false_when_current_owner_is_a_different_person():
    li = _li("SMITH JANE")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    assert _owner_still_supports_match(li) is False


def test_owner_still_supports_match_true_when_no_matched_name_to_check():
    li = _li("WILSON DEANA")
    li.raw["jail_booking"] = {"county": "Gaston"}   # malformed/legacy, no matched_name
    assert _owner_still_supports_match(li) is True


def test_owner_still_supports_match_true_when_no_jail_booking_tag():
    li = _li("GASTONIA CITY OF")
    assert _owner_still_supports_match(li) is True


# --------------------------------------------------------------------------- #
# _clear_stale_matches                                                        #
# --------------------------------------------------------------------------- #

def test_clear_stale_matches_drops_jail_booking_and_its_own_incarceration_tag():
    li = _li("GASTONIA CITY OF")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    li.raw["incarceration"] = {"source": "Gaston County jail roster",
                               "matched_name": "DEANA WILSON"}
    cleared = _clear_stale_matches([li])
    assert cleared == 1
    assert "jail_booking" not in li.raw
    assert "incarceration" not in li.raw


def test_clear_stale_matches_never_touches_a_dac_sourced_incarceration_entry():
    """A county-jail jail_booking match can be stale while a SEPARATE NC-DAC
    match shares the same raw['incarceration'] key -- only the owning module
    (enrichment_incarceration.py) may clear that one."""
    li = _li("GASTONIA CITY OF")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    li.raw["incarceration"] = {"source": DAC_SOURCE, "matched_name": "SOMEONE ELSE"}
    cleared = _clear_stale_matches([li])
    assert cleared == 1
    assert "jail_booking" not in li.raw
    assert li.raw["incarceration"]["source"] == DAC_SOURCE   # untouched


def test_clear_stale_matches_never_touches_a_bop_sourced_incarceration_entry():
    li = _li("GASTONIA CITY OF")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    li.raw["incarceration"] = {"source": BOP_SOURCE, "matched_name": "SOMEONE ELSE"}
    cleared = _clear_stale_matches([li])
    assert cleared == 1
    assert "jail_booking" not in li.raw
    assert li.raw["incarceration"]["source"] == BOP_SOURCE   # untouched


def test_clear_stale_matches_leaves_a_still_matching_booking_alone():
    li = _li("WILSON DEANA")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    li.raw["incarceration"] = {"source": "Gaston County jail roster",
                               "matched_name": "DEANA WILSON"}
    cleared = _clear_stale_matches([li])
    assert cleared == 0
    assert li.raw["jail_booking"]["matched_name"] == "DEANA WILSON"
    assert li.raw["incarceration"]["matched_name"] == "DEANA WILSON"


# --------------------------------------------------------------------------- #
# end-to-end through enrich_jail_bookings()                                   #
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _empty_rosters(monkeypatch):
    """Every bulk-roster fetch returns an empty index -- isolates the
    pre-pass (and match_rosters' re-match attempt, which will simply miss)
    from any real network call."""
    async def fake_load_roster(state, county, vendor, target, dry_run=False):
        return (state, county), {}
    monkeypatch.setattr(jb, "_load_roster", fake_load_roster)


@pytest.mark.asyncio
async def test_enrich_clears_a_stale_match_when_owner_is_now_an_entity():
    """The exact real-world case: owner changed to an entity. _name_parts
    rejects it outright, so the row correctly ends up with NO jail_booking or
    incarceration tag at all -- absent is honest, a stale wrong match is not."""
    li = _li("GASTONIA CITY OF")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    li.raw["incarceration"] = {"source": "Gaston County jail roster",
                               "matched_name": "DEANA WILSON"}
    res = await enrich_jail_bookings([li])
    assert res["stale_cleared"] == 1
    assert "jail_booking" not in li.raw
    assert "incarceration" not in li.raw


@pytest.mark.asyncio
async def test_enrich_clears_a_stale_match_and_leaves_the_row_open_to_rematch():
    """Ownership changed to a DIFFERENT real person (not an entity) -- the
    stale tag is cleared, and since the empty fake roster has no record for
    the new name, the row simply ends up with no match this run rather than
    sitting with the OLD wrong name forever."""
    li = _li("SMITH JANE")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    li.raw["incarceration"] = {"source": "Gaston County jail roster",
                               "matched_name": "DEANA WILSON"}
    res = await enrich_jail_bookings([li])
    assert res["stale_cleared"] == 1
    assert "jail_booking" not in li.raw
    assert "incarceration" not in li.raw


@pytest.mark.asyncio
async def test_enrich_leaves_a_still_matching_booking_alone():
    li = _li("WILSON DEANA")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    li.raw["incarceration"] = {"source": "Gaston County jail roster",
                               "matched_name": "DEANA WILSON"}
    res = await enrich_jail_bookings([li])
    assert res["stale_cleared"] == 0
    assert li.raw["jail_booking"]["matched_name"] == "DEANA WILSON"


@pytest.mark.asyncio
async def test_enrich_never_clears_a_dac_sourced_incarceration_entry():
    """This module must only ever clear a county-jail match it itself
    stamped -- an NC-DAC match sharing the key is enrichment_incarceration.py's
    to own."""
    li = _li("GASTONIA CITY OF")
    li.raw["jail_booking"] = {"matched_name": "DEANA WILSON"}
    li.raw["incarceration"] = {"source": DAC_SOURCE, "matched_name": "SOMEONE ELSE"}
    res = await enrich_jail_bookings([li])
    assert res["stale_cleared"] == 1
    assert "jail_booking" not in li.raw
    assert li.raw["incarceration"]["source"] == DAC_SOURCE
