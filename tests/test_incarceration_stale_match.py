"""Stale state-prison match invalidation (2026-10-03) -- same bug shape as
owner_name/bop_federal/owner_name_signal, found in enrichment_incarceration.py
during the same sweep: a NC DAC / SC DOC match, once stamped, was never
revisited even after the owner on record changed. The module's own
`if (li.raw or {}).get("incarceration"): continue` guard treated any existing
match as permanent, so a later owner-name refresh (a sale, an estate closing,
a parcel_cache correction) never got reconciled against a name-keyed match
stamped against whoever used to own the parcel.

Live-checked 2026-10-03 against the real board (board_stream, read-only): 11
rows carry raw['incarceration'] naming someone with zero relation to the
CURRENT owner, now an unrelated entity -- e.g. a Henderson County parcel
matched "MICHAEL PEAK" but now reads "FIRST CITIZENS BANK & TRUST CO"; a
Gaston County parcel matched "DEANA WILSON" but now reads "GASTONIA CITY OF"
-- plus several more rows where the current owner parses to a different real
person entirely.

`_owner_still_supports_match` and `_clear_stale_matches` close it, mirroring
enrichment_bop_federal.py's own fix (commit 9e3fd2c9) for the identical shape.
This file pins the real-world case that found it and proves
enrich_incarceration() clears + requeries through the real pre-pass.

HTTP is faked throughout; nothing touches a state server.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper import enrichment_incarceration as inc
from foreclosure_scraper.enrichment_incarceration import (
    DAC_SOURCE,
    SCDC_SOURCE,
    _Lookup,
    _clear_stale_matches,
    _owner_still_supports_match,
    enrich_incarceration,
)
from foreclosure_scraper.models import Listing


def _li(owner, state="NC", county="Henderson"):
    return Listing(source="test", source_url="http://x", state=state,
                   county=f"{county} County",
                   raw={"owner_mailing": {"owner": owner}})


class _Server:
    """Stands in for both state rosters. Records who was asked, in order."""

    def __init__(self, hits=()):
        self.asked: list[tuple[str, str]] = []
        self.hits = set(hits)

    def install(self, monkeypatch):
        async def look(http, last, first):
            self.asked.append((last, first))
            if (last, first) in self.hits:
                return _Lookup(match={"state": "NC", "source": DAC_SOURCE, "results": 1,
                                      "matched_name": f"{first} {last}",
                                      "confidence": "name_only_low"}, answered=True)
            return _Lookup(answered=True)
        monkeypatch.setattr(inc, "_scdc_lookup", look)
        monkeypatch.setattr(inc, "_dac_lookup", look)
        return self


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setenv("INCARCERATION_DELAY", "0")
    monkeypatch.delenv("INCARCERATION_MAX_QUERIES", raising=False)
    monkeypatch.delenv("INCARCERATION_PER_COUNTY_CAP", raising=False)
    monkeypatch.delenv("INCARCERATION_RECHECK_DAYS", raising=False)
    monkeypatch.delenv("INCARCERATION_CONCURRENCY", raising=False)


# --------------------------------------------------------------------------- #
# _owner_still_supports_match                                                 #
# --------------------------------------------------------------------------- #

def test_owner_still_supports_match_true_when_name_unchanged():
    li = _li("HUDSON RUSSELL")
    li.raw["incarceration"] = {"source": DAC_SOURCE, "matched_name": "RUSSELL HUDSON"}
    assert _owner_still_supports_match(li) is True


def test_owner_still_supports_match_false_when_current_owner_is_now_an_entity():
    # Real live example (Henderson County, 2026-10-03): owner changed to a bank.
    li = _li("FIRST CITIZENS BANK & TRUST CO")
    li.raw["incarceration"] = {"source": DAC_SOURCE, "matched_name": "MICHAEL PEAK"}
    assert _owner_still_supports_match(li) is False


def test_owner_still_supports_match_false_when_current_owner_is_a_different_person():
    li = _li("SMITH JANE")
    li.raw["incarceration"] = {"source": SCDC_SOURCE, "matched_name": "CECIL BENNETT"}
    assert _owner_still_supports_match(li) is False


def test_owner_still_supports_match_true_when_no_matched_name_to_check():
    li = _li("HUDSON RUSSELL")
    li.raw["incarceration"] = {"source": DAC_SOURCE}   # malformed/legacy, no matched_name
    assert _owner_still_supports_match(li) is True


def test_owner_still_supports_match_true_when_source_belongs_to_a_different_module():
    """A BOP or county-jail-roster match sharing the same raw['incarceration'] key is
    NOT this module's to clear -- enrichment_bop_federal.py / enrichment_jail_bookings.py
    each own clearing their own."""
    li = _li("FIRST CITIZENS BANK & TRUST CO")
    li.raw["incarceration"] = {"source": "Henderson County jail roster",
                               "matched_name": "MICHAEL PEAK"}
    assert _owner_still_supports_match(li) is True


# --------------------------------------------------------------------------- #
# _clear_stale_matches                                                        #
# --------------------------------------------------------------------------- #

def test_clear_stale_matches_drops_a_stale_dac_match():
    li = _li("FIRST CITIZENS BANK & TRUST CO")
    li.raw["incarceration"] = {"source": DAC_SOURCE, "matched_name": "MICHAEL PEAK"}
    cleared = _clear_stale_matches([li])
    assert cleared == 1
    assert "incarceration" not in li.raw


def test_clear_stale_matches_never_touches_a_bop_or_jail_roster_entry():
    li = _li("FIRST CITIZENS BANK & TRUST CO")
    li.raw["incarceration"] = {"source": "BOP inmate locator", "matched_name": "MICHAEL PEAK"}
    cleared = _clear_stale_matches([li])
    assert cleared == 0
    assert li.raw["incarceration"]["source"] == "BOP inmate locator"   # untouched


def test_clear_stale_matches_leaves_a_still_matching_scdc_entry_alone():
    li = _li("HUDSON RUSSELL", state="SC", county="Oconee")
    li.raw["incarceration"] = {"source": SCDC_SOURCE, "matched_name": "RUSSELL HUDSON"}
    cleared = _clear_stale_matches([li])
    assert cleared == 0
    assert li.raw["incarceration"]["matched_name"] == "RUSSELL HUDSON"


# --------------------------------------------------------------------------- #
# end-to-end through enrich_incarceration()                                   #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_enrich_clears_a_stale_match_and_the_row_stays_unstamped_when_owner_is_now_an_entity(monkeypatch):
    """The exact real-world case: owner changed to an entity. _name_parts
    rejects it outright, so the row correctly ends up with NO incarceration
    tag at all -- absent is honest, a stale wrong match is not."""
    srv = _Server().install(monkeypatch)
    li = _li("FIRST CITIZENS BANK & TRUST CO")
    li.raw["incarceration"] = {"source": DAC_SOURCE, "matched_name": "MICHAEL PEAK"}
    res = await enrich_incarceration([li])
    assert res["stale_cleared"] == 1
    assert "incarceration" not in li.raw
    assert srv.asked == []              # an entity owner is still never queried


@pytest.mark.asyncio
async def test_enrich_clears_a_stale_match_and_requeries_the_new_person(monkeypatch):
    """Ownership changed to a DIFFERENT real person (not an entity) -- the
    stale tag is cleared AND the row becomes a fresh candidate in the same
    run, so it gets re-checked against the new name rather than sitting with
    no answer until some later run."""
    srv = _Server(hits={("SMITH", "JANE")}).install(monkeypatch)
    li = _li("SMITH JANE")
    li.raw["incarceration"] = {"source": DAC_SOURCE, "matched_name": "CECIL BENNETT"}
    res = await enrich_incarceration([li])
    assert res["stale_cleared"] == 1
    assert srv.asked == [("SMITH", "JANE")]
    assert li.raw["incarceration"]["matched_name"] == "JANE SMITH"


@pytest.mark.asyncio
async def test_enrich_leaves_a_still_matching_stamp_alone_and_does_not_requery(monkeypatch):
    srv = _Server().install(monkeypatch)
    li = _li("HUDSON RUSSELL")
    li.raw["incarceration"] = {"source": DAC_SOURCE, "matched_name": "RUSSELL HUDSON"}
    res = await enrich_incarceration([li])
    assert res["stale_cleared"] == 0
    assert srv.asked == []
    assert li.raw["incarceration"]["matched_name"] == "RUSSELL HUDSON"


@pytest.mark.asyncio
async def test_enrich_never_clears_a_bop_or_jail_roster_sourced_entry(monkeypatch):
    """This module must only ever clear a match it itself stamped."""
    srv = _Server().install(monkeypatch)
    li = _li("FIRST CITIZENS BANK & TRUST CO")
    li.raw["incarceration"] = {"source": "BOP inmate locator", "matched_name": "MICHAEL PEAK"}
    res = await enrich_incarceration([li])
    assert res["stale_cleared"] == 0
    assert li.raw["incarceration"]["source"] == "BOP inmate locator"
    assert srv.asked == []   # an entity owner is never queried either way
