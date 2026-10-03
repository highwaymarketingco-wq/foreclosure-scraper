"""enrichment_bop_federal.py — BOP.gov Inmate Locator name match.

Dirty Deeds Tier B #36's federal-locator ask. Mirrors
tests/test_incarceration_rotation.py and test_incarceration_sc.py's gate/stamp
patterns since this enricher is deliberately built the same way (name-only,
exactly-one-exact-result gate, answered-miss stamp so a fixed budget rotates
through the board). HTTP is faked throughout; nothing touches bop.gov.

Owner strings are ALL-CAPS "LAST FIRST" with no comma throughout (the GIS
convention _name_parts assumes for that shape — see enrichment_incarceration
._name_parts), so `_li(last="HUDSON", first="RUSSELL")` makes the enricher
compute `name_parts == ("HUDSON", "RUSSELL")` and query bop_lookup(last=
"HUDSON", first="RUSSELL") exactly as written, with no reordering surprises.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from foreclosure_scraper import enrichment_bop_federal as bop
from foreclosure_scraper.enrichment_bop_federal import (
    _Lookup,
    _bop_lookup,
    _clear_stale_matches,
    _facility_type,
    _owner_still_supports_match,
    enrich_bop_federal,
)
from foreclosure_scraper.models import Listing


def _li(last="HUDSON", first="RUSSELL", state="NC", county="Buncombe"):
    return Listing(source="test", source_url="http://x", state=state,
                   county=f"{county} County",
                   raw={"owner_mailing": {"owner": f"{last} {first}"}})


class _FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d


class _FakeHTTP:
    def __init__(self, data, status=200):
        self._d, self._status = data, status
        self.calls: list[dict] = []

    async def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(params)
        return _FakeResp(self._d, self._status)


def _inmate(last, first, faclType="FCI", faclName="Butner", faclCode="BUT",
           actRelDate="", projRelDate="06/01/2030", inmateNum="12345-058"):
    return {"nameLast": last, "nameFirst": first, "faclType": faclType,
            "faclName": faclName, "faclCode": faclCode, "actRelDate": actRelDate,
            "projRelDate": projRelDate, "inmateNum": inmateNum}


# --------------------------------------------------------------------------- #
# _bop_lookup gate logic                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_flags_unique_exact_match_and_marks_in_custody_when_no_release_date():
    http = _FakeHTTP({"Captcha": False, "InmateLocator": [_inmate("HUDSON", "RUSSELL")]})
    res = await _bop_lookup(http, "HUDSON", "RUSSELL")
    assert res.match is not None
    assert res.match["facility_name"] == "Butner"
    assert res.match["facility_type"] == "federal_prison"
    assert res.match["in_custody"] is True
    assert res.match["confidence"] == "name_only_low"


@pytest.mark.asyncio
async def test_a_populated_actual_release_date_means_not_in_custody():
    http = _FakeHTTP({"Captcha": False, "InmateLocator": [
        _inmate("HUDSON", "RUSSELL", actRelDate="12/26/1997", projRelDate="")]})
    res = await _bop_lookup(http, "HUDSON", "RUSSELL")
    assert res.match["in_custody"] is False
    assert res.match["actual_release_date"] == "12/26/1997"


@pytest.mark.asyncio
async def test_empty_inmate_locator_is_an_answered_miss():
    http = _FakeHTTP({"Captcha": False, "InmateLocator": []})
    res = await _bop_lookup(http, "NOBODY", "HERE")
    assert res.match is None and res.answered is True and res.blocked is False


@pytest.mark.asyncio
async def test_rejects_common_name_with_multiple_exact_hits():
    http = _FakeHTTP({"Captcha": False, "InmateLocator": [
        _inmate("HUDSON", "RUSSELL", inmateNum="1"),
        _inmate("HUDSON", "RUSSELL", inmateNum="2")]})
    res = await _bop_lookup(http, "HUDSON", "RUSSELL")
    assert res.match is None and res.answered is True and res.candidates == 2


@pytest.mark.asyncio
async def test_ignores_non_exact_rows():
    http = _FakeHTTP({"Captcha": False, "InmateLocator": [
        _inmate("HUDSONS", "RUSSELL", inmateNum="x"),
        _inmate("HUDSON", "RUSS", inmateNum="y"),
        _inmate("HUDSON", "RUSSELL", inmateNum="z")]})
    res = await _bop_lookup(http, "HUDSON", "RUSSELL")
    assert res.match is not None and res.match["inmate_num"] == "z"


@pytest.mark.asyncio
async def test_a_non_json_or_unrecognized_shape_is_not_an_answer():
    http = _FakeHTTP({"unexpected": "shape"})   # no "InmateLocator" key at all
    res = await _bop_lookup(http, "X", "Y")
    assert res.match is None and res.answered is False and res.blocked is False


@pytest.mark.asyncio
async def test_a_block_status_is_reported_blocked_not_answered():
    http = _FakeHTTP({}, status=403)
    res = await _bop_lookup(http, "X", "Y")
    assert res.blocked is True and res.answered is False


def test_facility_type_buckets_known_codes_and_falls_back_for_unknown():
    assert _facility_type("FCI") == "federal_prison"
    assert _facility_type("USP") == "federal_prison"
    assert _facility_type("FDC") == "federal_detention"
    assert _facility_type("MCC") == "federal_detention"
    assert _facility_type("RRM") == "community_confinement"
    assert _facility_type("CCM") == "community_confinement"
    assert _facility_type("something-bop-never-documented") == "federal_other"
    assert _facility_type(None) == "federal_other"


# --------------------------------------------------------------------------- #
# enrich_bop_federal orchestration: stamping, rotation, scoring                #
# --------------------------------------------------------------------------- #
class _Server:
    """Stands in for _bop_lookup. Records who was asked (last, first), in order."""

    def __init__(self, hits=(), fail=(), block=(), facility_type="federal_prison",
                in_custody=True):
        self.asked: list[tuple[str, str]] = []
        self.hits, self.fail, self.block = set(hits), set(fail), set(block)
        self._facility_type, self._in_custody = facility_type, in_custody

    def install(self, monkeypatch):
        async def look(http, last, first):
            self.asked.append((last, first))
            if (last, first) in self.block:
                return _Lookup(blocked=True)
            if (last, first) in self.fail:
                return _Lookup()
            if (last, first) in self.hits:
                return _Lookup(match={
                    "matched_name": f"{first} {last}", "inmate_num": "1",
                    "facility_code": "BUT", "facility_name": "Butner",
                    "facility_type": self._facility_type, "facility_type_raw": "FCI",
                    "projected_release_date": None, "actual_release_date": None,
                    "in_custody": self._in_custody, "results": 1,
                    "source": bop.BOP_SOURCE, "confidence": "name_only_low"},
                    answered=True)
            return _Lookup(answered=True)
        monkeypatch.setattr(bop, "_bop_lookup", look)
        return self


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setenv("BOP_DELAY", "0")
    monkeypatch.delenv("BOP_MAX_QUERIES", raising=False)
    monkeypatch.delenv("BOP_RECHECK_DAYS", raising=False)
    monkeypatch.delenv("BOP_CONCURRENCY", raising=False)


def _tag(n: int) -> str:
    """Letters only: _name_parts drops digits from owner strings, so distinct
    numeric suffixes would otherwise collapse into the same (last, first)."""
    return "".join(chr(ord("A") + int(d)) for d in f"{n:04d}")


@pytest.mark.asyncio
async def test_match_sets_bop_federal_and_the_shared_incarceration_signal_when_in_custody(monkeypatch):
    _Server(hits={("HUDSON", "RUSSELL")}).install(monkeypatch)
    li = _li(last="HUDSON", first="RUSSELL")
    res = await enrich_bop_federal([li])
    assert res["matched"] == 1
    assert li.raw["bop_federal"]["facility_name"] == "Butner"
    assert li.raw["incarceration"]["source"] == bop.BOP_SOURCE
    assert li.raw["incarceration"]["state"] == "FEDERAL"


@pytest.mark.asyncio
async def test_a_released_match_sets_bop_federal_but_not_the_incarceration_signal(monkeypatch):
    _Server(hits={("HUDSON", "RUSSELL")}, in_custody=False).install(monkeypatch)
    li = _li(last="HUDSON", first="RUSSELL")
    await enrich_bop_federal([li])
    assert li.raw["bop_federal"]["in_custody"] is False
    assert "incarceration" not in li.raw


@pytest.mark.asyncio
async def test_answered_miss_is_stamped_and_not_treated_as_incarcerated(monkeypatch):
    _Server().install(monkeypatch)
    li = _li()
    res = await enrich_bop_federal([li])
    st = li.raw["bop_check"]
    assert st["result"] == "no_match" and st["source"] == bop.BOP_SOURCE
    datetime.fromisoformat(st["checked_at"])
    assert "incarceration" not in li.raw and "bop_federal" not in li.raw
    assert res["stamped_miss"] == 1


@pytest.mark.asyncio
async def test_a_failed_lookup_is_never_stamped(monkeypatch):
    _Server(fail={("HUDSON", "RUSSELL")}).install(monkeypatch)
    li = _li(last="HUDSON", first="RUSSELL")
    res = await enrich_bop_federal([li])
    assert "bop_check" not in li.raw
    assert res["failed"] == 1


@pytest.mark.asyncio
async def test_second_run_moves_on_instead_of_requerying_the_same_leads(monkeypatch):
    srv = _Server().install(monkeypatch)
    leads = [_li(last=f"TESTLAST{_tag(i)}", first=f"TESTFIRST{_tag(i)}") for i in range(1, 6)]
    await enrich_bop_federal(leads, max_queries=2)
    first_run = list(srv.asked)
    assert len(first_run) == 2
    srv.asked.clear()
    await enrich_bop_federal(leads, max_queries=2)
    second_run = list(srv.asked)
    assert len(second_run) == 2
    assert not set(first_run) & set(second_run)


@pytest.mark.asyncio
async def test_a_fresh_stamp_is_skipped_but_an_expired_one_is_rechecked(monkeypatch):
    srv = _Server().install(monkeypatch)
    li = _li(last="STALE", first="TESTCASE")
    now = datetime(2026, 9, 29, tzinfo=timezone.utc)
    # Name in the stamp must match how enrich_bop_federal actually computes it:
    # f"{first} {last}" — see _stamp_of / the "name" var in enrich_bop_federal.
    li.raw["bop_check"] = {"checked_at": now.isoformat(), "name": "TESTCASE STALE",
                           "source": bop.BOP_SOURCE, "result": "no_match"}
    res = await enrich_bop_federal([li], recheck_days=30)
    assert res == {"queried": 0, "matched": 0, "stale_cleared": 0}   # fresh: not re-asked
    old = now - timedelta(days=45)
    li.raw["bop_check"]["checked_at"] = old.isoformat()
    await enrich_bop_federal([li], recheck_days=30)
    assert srv.asked == [("STALE", "TESTCASE")]  # expired: re-asked


@pytest.mark.asyncio
async def test_a_blocked_host_leaves_remaining_leads_unstamped(monkeypatch):
    srv = _Server(block={("ALPHA", "ONE")}).install(monkeypatch)
    leads = [_li(last="ALPHA", first="ONE"), _li(last="BETA", first="TWO")]
    res = await enrich_bop_federal(leads)
    assert res["blocked"] == 1
    assert "bop_check" not in leads[0].raw and "bop_check" not in leads[1].raw


@pytest.mark.asyncio
async def test_the_same_owner_across_two_parcels_is_only_queried_once(monkeypatch):
    srv = _Server(hits={("SHARED", "OWNER")}).install(monkeypatch)
    leads = [_li(last="SHARED", first="OWNER"),
            _li(last="SHARED", first="OWNER", county="Henderson")]
    res = await enrich_bop_federal(leads)
    assert srv.asked.count(("SHARED", "OWNER")) == 1
    assert res["matched"] == 2   # both parcels flagged from the one lookup


@pytest.mark.asyncio
async def test_out_of_footprint_state_and_entity_owner_are_skipped(monkeypatch):
    srv = _Server().install(monkeypatch)
    ga = _li(last="SOMEBODY", first="ELSE", state="GA", county="Fulton")
    llc = Listing(source="test", source_url="http://x", state="NC",
                 county="Buncombe County",
                 raw={"owner_mailing": {"owner": "ACME HOLDINGS LLC"}})
    res = await enrich_bop_federal([ga, llc])
    assert srv.asked == []
    assert res == {"queried": 0, "matched": 0, "stale_cleared": 0}


# --------------------------------------------------------------------------- #
# stale-match invalidation: a changed CURRENT owner shouldn't keep carrying   #
# someone else's federal record forever (live-found 2026-10-03, a real       #
# Buncombe row: owner now "COVENANT PRESBYTERIAN CHURCH", bop_federal still  #
# said "CECIL BENNETT")                                                      #
# --------------------------------------------------------------------------- #
def test_owner_still_supports_match_true_when_name_unchanged():
    li = _li(last="HUDSON", first="RUSSELL")
    li.raw["bop_federal"] = {"matched_name": "RUSSELL HUDSON"}
    assert _owner_still_supports_match(li) is True


def test_owner_still_supports_match_false_when_current_owner_is_now_an_entity():
    li = _li(last="BENNETT", first="CECIL")
    li.raw["bop_federal"] = {"matched_name": "CECIL BENNETT"}
    # Ownership has since changed hands to an entity -- same shape as the real
    # Buncombe row this was found on.
    li.raw["owner_mailing"] = {"owner": "COVENANT PRESBYTERIAN CHURCH"}
    assert _owner_still_supports_match(li) is False


def test_owner_still_supports_match_false_when_current_owner_is_a_different_person():
    li = _li(last="BENNETT", first="CECIL")
    li.raw["bop_federal"] = {"matched_name": "CECIL BENNETT"}
    li.raw["owner_mailing"] = {"owner": "SMITH JANE"}
    assert _owner_still_supports_match(li) is False


def test_owner_still_supports_match_true_when_no_matched_name_to_check():
    li = _li()
    li.raw["bop_federal"] = {"facility_name": "Butner"}   # malformed/legacy, no matched_name
    assert _owner_still_supports_match(li) is True


def test_clear_stale_matches_drops_tag_and_bop_sourced_incarceration_only():
    li = _li(last="BENNETT", first="CECIL")
    li.raw["owner_mailing"] = {"owner": "COVENANT PRESBYTERIAN CHURCH"}
    li.raw["bop_federal"] = {"matched_name": "CECIL BENNETT"}
    li.raw["incarceration"] = {"source": bop.BOP_SOURCE, "state": "FEDERAL"}
    cleared = _clear_stale_matches([li])
    assert cleared == 1
    assert "bop_federal" not in li.raw and "incarceration" not in li.raw


def test_clear_stale_matches_never_touches_a_non_bop_incarceration_entry():
    li = _li(last="BENNETT", first="CECIL")
    li.raw["owner_mailing"] = {"owner": "COVENANT PRESBYTERIAN CHURCH"}
    li.raw["bop_federal"] = {"matched_name": "CECIL BENNETT"}
    li.raw["incarceration"] = {"source": "NC DAC offender search", "state": "NC"}
    cleared = _clear_stale_matches([li])
    assert cleared == 1
    assert "bop_federal" not in li.raw
    assert li.raw["incarceration"]["source"] == "NC DAC offender search"   # untouched


@pytest.mark.asyncio
async def test_enrich_clears_a_stale_match_and_the_row_stays_unstamped_when_owner_is_now_an_entity(monkeypatch):
    """The exact real-world case: owner changed to an entity. _name_parts
    rejects it outright, so the row correctly ends up with NO bop_federal at
    all -- absent is honest, a stale wrong match is not."""
    srv = _Server().install(monkeypatch)
    li = _li(last="BENNETT", first="CECIL")
    li.raw["owner_mailing"] = {"owner": "COVENANT PRESBYTERIAN CHURCH"}
    li.raw["bop_federal"] = {"matched_name": "CECIL BENNETT"}
    res = await enrich_bop_federal([li])
    assert res["stale_cleared"] == 1
    assert "bop_federal" not in li.raw
    assert srv.asked == []              # an entity owner is still never queried


@pytest.mark.asyncio
async def test_enrich_clears_a_stale_match_and_requeries_the_new_person(monkeypatch):
    """Ownership changed to a DIFFERENT real person (not an entity) -- the
    stale tag is cleared AND the row becomes a fresh candidate in the same
    run, so it gets re-checked against the new name rather than sitting with
    no answer until some later run."""
    srv = _Server(hits={("SMITH", "JANE")}).install(monkeypatch)
    li = _li(last="BENNETT", first="CECIL")
    li.raw["owner_mailing"] = {"owner": "SMITH JANE"}
    li.raw["bop_federal"] = {"matched_name": "CECIL BENNETT"}
    res = await enrich_bop_federal([li])
    assert res["stale_cleared"] == 1
    assert srv.asked == [("SMITH", "JANE")]
    assert li.raw["bop_federal"]["matched_name"] == "JANE SMITH"
