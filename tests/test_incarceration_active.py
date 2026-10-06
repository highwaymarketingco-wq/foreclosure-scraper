"""A person moved from county jail to state/federal prison must stay scored.

Three linked gaps (found 2026-10-05 after the jail re-evaluation fix, commit 3a8c4e03):
the scorer and the lead-signal tagger dropped ANY raw['incarceration'] once the county jail
booking ended, even a state-prison match; the state-prison lane skipped anyone already
carrying a jail-sourced flag; and the federal lane's setdefault never replaced one.
HTTP is faked throughout.
"""
from __future__ import annotations

from datetime import date

import pytest

from foreclosure_scraper import enrichment_bop_federal as bop
from foreclosure_scraper import enrichment_incarceration as inc
from foreclosure_scraper.distress_score import _signals_for
from foreclosure_scraper.enrichment_lead_signals import _facet_signals
from foreclosure_scraper.models import Listing
from foreclosure_scraper.signal_freshness import (
    PRISON_SOURCES,
    incarceration_active,
    is_jail_sourced,
    is_prison_sourced,
)

TODAY = date(2026, 10, 5)
JAIL_INC = {"state": "NC", "source": "Henderson County jail roster",
            "matched_name": "RUSSELL HUDSON", "confidence": "name_only_low"}
DAC_INC = {"state": "NC", "source": inc.DAC_SOURCE, "matched_name": "RUSSELL HUDSON",
           "confidence": "name_only_low"}
ENDED = {"release_status": "released_or_transferred"}
IN_CUSTODY = {"release_status": "in_custody"}


def _li(raw_extra=None, owner="HUDSON RUSSELL"):
    raw = {"owner_mailing": {"owner": owner}}
    raw.update(raw_extra or {})
    return Listing(source="test", source_url="http://x", state="NC",
                   county="Henderson County", raw=raw)


def test_prison_sources_match_the_enrichers_constants():
    assert set(PRISON_SOURCES) == {inc.DAC_SOURCE, inc.SCDC_SOURCE, bop.BOP_SOURCE}


@pytest.mark.parametrize("incarceration,jail,expected", [
    (None, None, False),
    (DAC_INC, ENDED, True),            # prison match stands on its own
    (DAC_INC, None, True),
    (JAIL_INC, ENDED, False),          # jail flag ends with the jail stay
    (JAIL_INC, IN_CUSTODY, True),
    (JAIL_INC, None, False),           # orphan: a jail flag with no booking record behind it
    (JAIL_INC, {}, False),
    (JAIL_INC, "in_custody", False),   # not a booking record either
    (dict(JAIL_INC, source="Anderson County jail roster"), None, False),
    ({"matched_name": "X"}, None, True),   # legacy source-less flag: unchanged behaviour
])
def test_incarceration_active(incarceration, jail, expected):
    assert incarceration_active(incarceration, jail, TODAY) is expected


def test_is_jail_sourced():
    assert is_jail_sourced(JAIL_INC)
    assert is_jail_sourced({"source": "Polk County jail roster"})
    assert not is_jail_sourced(DAC_INC) and not is_jail_sourced({"source": bop.BOP_SOURCE})
    assert not is_jail_sourced({"matched_name": "X"}) and not is_jail_sourced(None)


def test_orphan_jail_flag_scores_nowhere_and_prison_flags_without_a_booking_still_do():
    orphan = _li({"incarceration": dict(JAIL_INC)})
    assert not _scored(orphan)
    assert "incarceration" not in _facet_signals(orphan, TODAY)
    for src in PRISON_SOURCES:
        li = _li({"incarceration": dict(DAC_INC, source=src)})
        assert _scored(li) and "incarceration" in _facet_signals(li, TODAY)


@pytest.mark.parametrize("raw_extra", [
    {"incarceration": dict(JAIL_INC)},
    {"incarceration": dict(JAIL_INC), "jail_booking": dict(IN_CUSTODY)},
    {"incarceration": dict(JAIL_INC), "jail_booking": dict(ENDED)},
    {"incarceration": dict(DAC_INC)},
    {"incarceration": dict(DAC_INC), "jail_booking": dict(ENDED)},
    {"incarceration": {"matched_name": "X"}},
])
def test_scorer_and_lead_signals_agree_on_every_flag_shape(raw_extra):
    li = _li(raw_extra)
    assert _scored(li) == ("incarceration" in _facet_signals(li, TODAY))


def test_is_prison_sourced():
    assert is_prison_sourced(DAC_INC) and is_prison_sourced({"source": bop.BOP_SOURCE})
    assert not is_prison_sourced(JAIL_INC) and not is_prison_sourced(None)


def _scored(li):
    return ("incarceration", "LEGAL", 8) in _signals_for(li, today=TODAY)


def test_scorer_keeps_a_prison_match_after_the_jail_stay_ends():
    assert _scored(_li({"incarceration": DAC_INC, "jail_booking": ENDED}))


def test_scorer_drops_a_jail_flag_once_the_jail_stay_ends():
    assert not _scored(_li({"incarceration": JAIL_INC, "jail_booking": ENDED}))
    assert _scored(_li({"incarceration": JAIL_INC, "jail_booking": IN_CUSTODY}))


def test_lead_signals_agree_with_the_scorer():
    assert "incarceration" in _facet_signals(
        _li({"incarceration": DAC_INC, "jail_booking": ENDED}), TODAY)
    assert "incarceration" not in _facet_signals(
        _li({"incarceration": JAIL_INC, "jail_booking": ENDED}), TODAY)


class _StateServer:
    def __init__(self, hits=()):
        self.asked: list[tuple[str, str]] = []
        self.hits = set(hits)

    def install(self, monkeypatch):
        async def look(http, last, first):
            self.asked.append((last, first))
            if (last, first) in self.hits:
                return inc._Lookup(match=dict(DAC_INC), answered=True)
            return inc._Lookup(answered=True)
        monkeypatch.setattr(inc, "_dac_lookup", look)
        monkeypatch.setattr(inc, "_scdc_lookup", look)
        return self


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    for k in ("INCARCERATION_MAX_QUERIES", "INCARCERATION_PER_COUNTY_CAP",
              "INCARCERATION_RECHECK_DAYS", "INCARCERATION_CONCURRENCY",
              "BOP_MAX_QUERIES", "BOP_RECHECK_DAYS", "BOP_CONCURRENCY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("INCARCERATION_DELAY", "0")
    monkeypatch.setenv("BOP_DELAY", "0")


@pytest.mark.asyncio
async def test_state_lane_checks_someone_whose_jail_stay_ended_and_records_the_prison_match(monkeypatch):
    srv = _StateServer(hits={("HUDSON", "RUSSELL")}).install(monkeypatch)
    li = _li({"incarceration": dict(JAIL_INC), "jail_booking": dict(ENDED)})
    await inc.enrich_incarceration([li])
    assert srv.asked == [("HUDSON", "RUSSELL")]
    assert li.raw["incarceration"]["source"] == inc.DAC_SOURCE
    assert _scored(li)


@pytest.mark.asyncio
async def test_state_lane_checks_the_owner_behind_an_orphan_jail_flag(monkeypatch):
    srv = _StateServer(hits={("HUDSON", "RUSSELL")}).install(monkeypatch)
    li = _li({"incarceration": dict(JAIL_INC)})
    await inc.enrich_incarceration([li])
    assert srv.asked == [("HUDSON", "RUSSELL")]
    assert li.raw["incarceration"]["source"] == inc.DAC_SOURCE
    assert _scored(li)


@pytest.mark.asyncio
async def test_state_lane_still_skips_someone_in_county_jail_or_already_matched(monkeypatch):
    srv = _StateServer(hits={("HUDSON", "RUSSELL")}).install(monkeypatch)
    in_jail = _li({"incarceration": dict(JAIL_INC), "jail_booking": dict(IN_CUSTODY)})
    in_prison = _li({"incarceration": dict(DAC_INC), "jail_booking": dict(ENDED)})
    await inc.enrich_incarceration([in_jail, in_prison])
    assert srv.asked == []


class _BopServer:
    def install(self, monkeypatch):
        async def look(http, last, first):
            return bop._Lookup(match={
                "matched_name": f"{first} {last}", "inmate_num": "1",
                "facility_code": "BUT", "facility_name": "Butner",
                "facility_type": "federal_prison", "facility_type_raw": "FCI",
                "projected_release_date": None, "actual_release_date": None,
                "in_custody": True, "results": 1,
                "source": bop.BOP_SOURCE, "confidence": "name_only_low"}, answered=True)
        monkeypatch.setattr(bop, "_bop_lookup", look)


@pytest.mark.asyncio
async def test_federal_match_replaces_a_jail_flag(monkeypatch):
    _BopServer().install(monkeypatch)
    li = _li({"incarceration": dict(JAIL_INC), "jail_booking": dict(ENDED)})
    await bop.enrich_bop_federal([li])
    assert li.raw["incarceration"]["source"] == bop.BOP_SOURCE
    assert _scored(li)


@pytest.mark.asyncio
async def test_federal_match_never_replaces_a_state_prison_match(monkeypatch):
    _BopServer().install(monkeypatch)
    li = _li({"incarceration": dict(DAC_INC)})
    await bop.enrich_bop_federal([li])
    assert li.raw["incarceration"]["source"] == inc.DAC_SOURCE
