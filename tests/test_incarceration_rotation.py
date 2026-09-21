"""J-01: enrich_incarceration must remember a miss and move on.

Before 2026-09-20 a miss left nothing on the lead, so every run re-queried the
first 150 non-matching owners (`targets[:max_queries]`) and never reached the
rest. Mitchell, Oconee and Union, which have no county roster and depend on this
state-prison match alone, stayed at zero incarceration leads.

What these pin:
  * an ANSWERED miss is stamped raw['incarceration_check'] and skipped next run
  * a lookup that FAILED (timeout, 5xx, unknown page) is never stamped
  * never-checked leads go first, then the oldest stamps; expired stamps re-run
  * the per-run budget is shared across counties, footprint counties first,
    with a per-county cap
  * a host that answers 403 is left alone for the rest of the run
  * what counts as a match is unchanged (single exact result, low confidence)

All names below are obvious placeholders. HTTP is faked; nothing touches a state
server.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from foreclosure_scraper import enrichment_incarceration as inc
from foreclosure_scraper.enrichment_incarceration import (
    _Lookup,
    _dac_lookup,
    _dac_match,
    _scdc_lookup,
    _select_targets,
    enrich_incarceration,
)
from foreclosure_scraper.models import Listing

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _tag(n: int) -> str:
    """Letters only: _name_parts drops digits, so 'LAST001' and 'LAST002' would
    collapse into one name."""
    return "".join(chr(ord("A") + int(d)) for d in f"{n:04d}")


def _nm(n: int) -> tuple[str, str]:
    """(last, first) exactly as the enricher will ask for lead n."""
    return f"TESTLAST{_tag(n)}", f"TESTFIRST{_tag(n)}"


def _lead(n, county="Oconee", state="SC", owner=None):
    """A person-owned lead; `owner` defaults to a unique 'LAST FIRST' placeholder."""
    last, first = _nm(n)
    return Listing(source="test", source_url=f"http://x/{county}/{n}", state=state,
                   county=f"{county} County",
                   raw={"owner_mailing": {"owner": owner or f"{last} {first}"}})


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setenv("INCARCERATION_DELAY", "0")
    monkeypatch.delenv("INCARCERATION_MAX_QUERIES", raising=False)
    monkeypatch.delenv("INCARCERATION_PER_COUNTY_CAP", raising=False)
    monkeypatch.delenv("INCARCERATION_RECHECK_DAYS", raising=False)
    monkeypatch.delenv("INCARCERATION_CONCURRENCY", raising=False)


class _Server:
    """Stands in for both state rosters. Records who was asked, in order."""

    def __init__(self, hits=(), fail=(), block=()):
        self.asked: list[tuple[str, str]] = []
        self.hits, self.fail, self.block = set(hits), set(fail), set(block)

    def install(self, monkeypatch):
        async def look(http, last, first):
            self.asked.append((last, first))
            if (last, first) in self.block:
                return _Lookup(blocked=True)
            if (last, first) in self.fail:
                return _Lookup()                       # answered=False
            if (last, first) in self.hits:
                return _Lookup(match={"state": "SC", "source": "fake", "results": 1,
                                      "matched_name": f"{first} {last}",
                                      "confidence": "name_only_low"}, answered=True)
            return _Lookup(answered=True)
        monkeypatch.setattr(inc, "_scdc_lookup", look)
        monkeypatch.setattr(inc, "_dac_lookup", look)
        return self


# --------------------------------------------------------------------------- #
# The stamp, and skipping stamped leads                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_answered_miss_is_stamped(monkeypatch):
    _Server().install(monkeypatch)
    li = _lead(1)
    res = await enrich_incarceration([li])
    st = li.raw["incarceration_check"]
    assert st["result"] == "no_match"
    assert st["name"] == " ".join(reversed(_nm(1)))
    assert st["source"] == "SC DOC inmate search"
    datetime.fromisoformat(st["checked_at"])          # parseable
    assert "incarceration" not in li.raw              # a miss is NOT the signal
    assert res["stamped_miss"] == 1 and res["matched"] == 0


@pytest.mark.asyncio
async def test_stamp_source_follows_the_state(monkeypatch):
    _Server().install(monkeypatch)
    nc = _lead(1, county="Mitchell", state="NC")
    await enrich_incarceration([nc])
    assert nc.raw["incarceration_check"]["source"] == "NC DAC offender search"


@pytest.mark.asyncio
async def test_second_run_moves_on_instead_of_requerying_the_same_leads(monkeypatch):
    srv = _Server().install(monkeypatch)
    leads = [_lead(i) for i in range(1, 6)]
    await enrich_incarceration(leads, max_queries=2)
    first_run = list(srv.asked)
    assert len(first_run) == 2
    srv.asked.clear()
    await enrich_incarceration(leads, max_queries=2)
    second_run = list(srv.asked)
    assert len(second_run) == 2
    assert not set(first_run) & set(second_run)       # the old code re-asked run 1's two
    srv.asked.clear()
    await enrich_incarceration(leads, max_queries=2)
    assert len(srv.asked) == 1                        # only lead 5 was left
    srv.asked.clear()
    res = await enrich_incarceration(leads, max_queries=2)
    assert srv.asked == [] and res == {"queried": 0, "matched": 0}   # all fresh


@pytest.mark.asyncio
async def test_expired_stamp_is_rechecked_oldest_first(monkeypatch):
    srv = _Server().install(monkeypatch)
    leads = [_lead(i) for i in range(1, 4)]
    await enrich_incarceration(leads)
    # Age the stamps: lead 2 is the oldest, lead 1 next, lead 3 still fresh.
    ages = {1: 40, 2: 90, 3: 5}
    for i, li in enumerate(leads, 1):
        li.raw["incarceration_check"]["checked_at"] = (
            datetime.now(timezone.utc) - timedelta(days=ages[i])).isoformat()
    srv.asked.clear()
    res = await enrich_incarceration(leads, max_queries=1)
    assert srv.asked == [_nm(2)]     # oldest expired first
    assert res["skipped_fresh"] == 1                          # lead 3 (5 days old)
    srv.asked.clear()
    await enrich_incarceration(leads, max_queries=5)
    assert srv.asked == [_nm(1)]     # then the next expired


@pytest.mark.asyncio
async def test_recheck_window_is_tunable(monkeypatch):
    srv = _Server().install(monkeypatch)
    li = _lead(1)
    await enrich_incarceration([li])
    li.raw["incarceration_check"]["checked_at"] = (
        datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    srv.asked.clear()
    await enrich_incarceration([li])
    assert srv.asked == []                                    # 3 days < default 30
    await enrich_incarceration([li], recheck_days=2)
    assert len(srv.asked) == 1


@pytest.mark.asyncio
async def test_stamp_for_a_different_owner_name_does_not_count(monkeypatch):
    srv = _Server().install(monkeypatch)
    li = _lead(1)
    await enrich_incarceration([li])
    li.raw["owner_mailing"]["owner"] = "OTHERLAST OTHERFIRST"   # owner re-resolved
    srv.asked.clear()
    await enrich_incarceration([li])
    assert srv.asked == [("OTHERLAST", "OTHERFIRST")]


@pytest.mark.asyncio
async def test_a_failed_lookup_is_never_stamped(monkeypatch):
    """The divorce enricher's 2026-09-18 bug: a failed search read as 'checked, no
    match'. A timeout must leave the lead as never-checked, still first in line."""
    srv = _Server(fail={_nm(1)}).install(monkeypatch)
    a, b = _lead(1), _lead(2)
    res = await enrich_incarceration([a, b])
    assert "incarceration_check" not in a.raw
    assert "incarceration_check" in b.raw
    assert res["failed"] == 1 and res["stamped_miss"] == 1
    srv.asked.clear()
    await enrich_incarceration([a, b], max_queries=1)
    assert srv.asked == [_nm(1)]     # retried next run


@pytest.mark.asyncio
async def test_a_hit_sets_the_signal_and_drops_any_old_stamp(monkeypatch):
    li = _lead(1)
    li.raw["incarceration_check"] = {"checked_at": "2020-01-01T00:00:00+00:00",
                                     "name": " ".join(reversed(_nm(1))), "result": "no_match"}
    _Server(hits={_nm(1)}).install(monkeypatch)
    res = await enrich_incarceration([li])
    assert li.raw["incarceration"]["confidence"] == "name_only_low"
    assert "incarceration_check" not in li.raw
    assert res["matched"] == 1 and res["matched_sc"] == 1


@pytest.mark.asyncio
async def test_already_flagged_leads_are_not_queried(monkeypatch):
    srv = _Server().install(monkeypatch)
    li = _lead(1)
    li.raw["incarceration"] = {"state": "SC", "source": "Oconee County jail roster"}
    res = await enrich_incarceration([li])
    assert srv.asked == [] and res["queried"] == 0


@pytest.mark.asyncio
async def test_same_owner_on_several_parcels_is_asked_once(monkeypatch):
    srv = _Server().install(monkeypatch)
    a, b, c = (_lead(i, owner="REPEATLAST REPEATFIRST") for i in (1, 2, 3))
    res = await enrich_incarceration([a, b, c])
    assert len(srv.asked) == 1
    assert res["queried"] == 1 and res["stamped_miss"] == 3
    assert all("incarceration_check" in li.raw for li in (a, b, c))


# --------------------------------------------------------------------------- #
# Budget: round-robin across counties, footprint first, per-county cap         #
# --------------------------------------------------------------------------- #
def _cands(leads):
    return [(li, "n", None) for li in leads]


def test_budget_is_shared_across_counties_not_first_come():
    big = [_lead(i, county="Oconee") for i in range(30)]
    small = [_lead(i, county="Union") for i in range(3)]
    picked = _select_targets(_cands(big + small), max_queries=8, per_county_cap=50, now=NOW)
    counties = [li.county for li in picked]
    assert len(picked) == 8
    assert counties.count("Union County") == 3          # small county fully served
    assert counties.count("Oconee County") == 5         # not 8 of the first 8


def test_per_county_cap_holds_even_with_budget_to_spare():
    big = [_lead(i, county="Oconee") for i in range(30)]
    small = [_lead(i, county="Union") for i in range(2)]
    picked = _select_targets(_cands(big + small), max_queries=100, per_county_cap=4, now=NOW)
    counties = [li.county for li in picked]
    assert counties.count("Oconee County") == 4
    assert counties.count("Union County") == 2


def test_cap_zero_means_no_cap():
    big = [_lead(i) for i in range(30)]
    assert len(_select_targets(_cands(big), 100, 0, NOW)) == 30


def test_footprint_counties_go_before_the_rest():
    out_of_scope = [_lead(i, county="Mecklenburg", state="NC") for i in range(40)]
    footprint = [_lead(i, county="Mitchell", state="NC") for i in range(3)]
    picked = _select_targets(_cands(out_of_scope + footprint), 5, 50, NOW)
    assert sum(1 for li in picked if li.county == "Mitchell County") == 3
    assert len(picked) == 5                              # leftover budget still used


def test_within_a_county_never_checked_precede_old_stamps_oldest_first():
    leads = [_lead(i) for i in range(4)]
    stamps = [NOW - timedelta(days=50), None, NOW - timedelta(days=90), None]
    cands = [(li, "n", st) for li, st in zip(leads, stamps)]
    picked = _select_targets(cands, 10, 50, NOW)
    assert [leads.index(li) for li in picked] == [1, 3, 2, 0]


@pytest.mark.asyncio
async def test_default_budget_comes_from_env(monkeypatch):
    srv = _Server().install(monkeypatch)
    monkeypatch.setenv("INCARCERATION_MAX_QUERIES", "3")
    await enrich_incarceration([_lead(i) for i in range(10)])
    assert len(srv.asked) == 3
    srv.asked.clear()
    await enrich_incarceration([_lead(i) for i in range(20, 30)], max_queries=5)
    assert len(srv.asked) == 5                            # an explicit value still wins


@pytest.mark.asyncio
async def test_per_county_cap_from_env(monkeypatch):
    srv = _Server().install(monkeypatch)
    monkeypatch.setenv("INCARCERATION_PER_COUNTY_CAP", "2")
    await enrich_incarceration([_lead(i) for i in range(10)], max_queries=100)
    assert len(srv.asked) == 2


# --------------------------------------------------------------------------- #
# Politeness: stop a host that pushes back                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_blocked_host_is_left_alone_and_nothing_is_stamped(monkeypatch):
    srv = _Server(block={_nm(1)}).install(monkeypatch)
    sc = [_lead(i) for i in range(1, 6)]
    res = await enrich_incarceration(sc)
    assert len(srv.asked) == 1                            # stopped after the first 403
    assert res["blocked_hosts"] == 1
    assert not any("incarceration_check" in li.raw for li in sc)


@pytest.mark.asyncio
async def test_one_blocked_state_does_not_stop_the_other(monkeypatch):
    _Server(block={_nm(1)}).install(monkeypatch)
    sc = [_lead(1, state="SC")]
    nc = [_lead(2, county="Mitchell", state="NC"), _lead(3, county="Mitchell", state="NC")]
    await enrich_incarceration(sc + nc)
    assert all("incarceration_check" in li.raw for li in nc)
    assert "incarceration_check" not in sc[0].raw


@pytest.mark.asyncio
async def test_repeated_unusable_answers_trip_the_host(monkeypatch):
    fails = {_nm(i) for i in range(1, 30)}
    srv = _Server(fail=fails).install(monkeypatch)
    monkeypatch.setenv("INCARCERATION_MAX_FAILURES", "3")
    await enrich_incarceration([_lead(i) for i in range(1, 20)])
    assert len(srv.asked) == 3                            # not 19 requests into a dead host


# --------------------------------------------------------------------------- #
# The matchers: what counts as a match did not change; failures are separable  #
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, text="", status=200, data=None):
        self.text, self.status_code, self._d = text, status, data

    def json(self):
        if isinstance(self._d, Exception):
            raise self._d
        return self._d


class _Http:
    def __init__(self, resp=None, exc=None):
        self._r, self._exc = resp, exc

    async def get(self, *a, **k):
        if self._exc:
            raise self._exc
        return self._r

    async def post(self, *a, **k):
        if self._exc:
            raise self._exc
        return self._r


_DAC_NONE = ("<html><h1>Offender Search Results</h1>No offenders found."
             "<table>Nothing found to display</table></html>")


def _dac_page(rows):
    body = "".join(f'<tr><td><a href="view.do?offenderID={i}">x</a></td>'
                   f"<td>{last}</td><td>{first}</td></tr>"
                   for i, (last, first) in enumerate(rows, 1))
    return f"<html><h1>Offender Search Results</h1><table>{body}</table></html>"


@pytest.mark.asyncio
async def test_dac_real_no_result_page_is_an_answered_miss():
    r = await _dac_lookup(_Http(_Resp(_DAC_NONE)), "TESTLAST", "TESTFIRST")
    assert r.answered and r.match is None and not r.blocked


@pytest.mark.asyncio
async def test_dac_unrecognised_200_is_not_an_answer():
    r = await _dac_lookup(_Http(_Resp("<html>Service temporarily unavailable</html>")),
                          "TESTLAST", "TESTFIRST")
    assert not r.answered and not r.blocked and r.match is None


@pytest.mark.asyncio
async def test_dac_challenge_page_is_a_block_not_a_miss():
    r = await _dac_lookup(_Http(_Resp("<html>Please complete the CAPTCHA</html>")),
                          "TESTLAST", "TESTFIRST")
    assert r.blocked and not r.answered


@pytest.mark.asyncio
@pytest.mark.parametrize("status,blocked", [(403, True), (429, True), (500, False), (503, False)])
async def test_dac_error_statuses(status, blocked):
    r = await _dac_lookup(_Http(_Resp("", status)), "TESTLAST", "TESTFIRST")
    assert r.blocked is blocked and not r.answered


@pytest.mark.asyncio
async def test_dac_exception_is_not_an_answer():
    r = await _dac_lookup(_Http(exc=TimeoutError("slow")), "TESTLAST", "TESTFIRST")
    assert not r.answered and not r.blocked


@pytest.mark.asyncio
async def test_dac_single_exact_row_is_still_a_low_confidence_match():
    r = await _dac_lookup(_Http(_Resp(_dac_page([("TESTLAST", "TESTFIRST")]))),
                          "TESTLAST", "TESTFIRST")
    assert r.answered and r.match["confidence"] == "name_only_low"
    assert r.match["state"] == "NC" and r.match["matched_name"] == "TESTFIRST TESTLAST"


@pytest.mark.asyncio
async def test_dac_two_rows_is_an_answered_miss_not_a_match():
    page = _dac_page([("TESTLAST", "TESTFIRST"), ("TESTLAST", "TESTFIRST")])
    r = await _dac_lookup(_Http(_Resp(page)), "TESTLAST", "TESTFIRST")
    assert r.answered and r.match is None and r.candidates == 2
    assert await _dac_match(_Http(_Resp(page)), "TESTLAST", "TESTFIRST") is None


@pytest.mark.asyncio
async def test_scdc_empty_list_is_an_answered_miss():
    r = await _scdc_lookup(_Http(_Resp(data=[])), "TESTLAST", "TESTFIRST")
    assert r.answered and r.match is None


@pytest.mark.asyncio
async def test_scdc_non_list_body_is_not_an_answer():
    r = await _scdc_lookup(_Http(_Resp(data={"error": "x"})), "TESTLAST", "TESTFIRST")
    assert not r.answered
    r = await _scdc_lookup(_Http(_Resp(data=ValueError("html, not json"))), "TESTLAST", "TESTFIRST")
    assert not r.answered and not r.blocked


@pytest.mark.asyncio
async def test_scdc_403_is_a_block():
    r = await _scdc_lookup(_Http(_Resp(status=403)), "TESTLAST", "TESTFIRST")
    assert r.blocked and not r.answered


@pytest.mark.asyncio
async def test_scdc_near_matches_only_is_an_answered_miss():
    data = [{"lname": "TESTLASTER", "fname": "TESTFIRST", "scdcId": "1"}]
    r = await _scdc_lookup(_Http(_Resp(data=data)), "TESTLAST", "TESTFIRST")
    assert r.answered and r.match is None


# --------------------------------------------------------------------------- #
# Scoring is untouched: the stamp is not the signal                            #
# --------------------------------------------------------------------------- #
def test_stamp_alone_scores_nothing_and_a_match_still_scores_legal_8():
    from foreclosure_scraper.distress_score import _signals_for
    stamped = _lead(1)
    stamped.raw["incarceration_check"] = {"checked_at": NOW.isoformat(), "result": "no_match"}
    assert not [s for s in _signals_for(stamped) if s[0] == "incarceration"]
    hit = _lead(2)
    hit.raw["incarceration"] = {"confidence": "name_only_low"}
    assert ("incarceration", "LEGAL", 8) in _signals_for(hit)


def test_the_stamp_survives_the_publish_slim():
    from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw
    assert "incarceration_check" in RAW_KEEP
    stamp = {"checked_at": NOW.isoformat(), "name": "A B", "source": "s", "result": "no_match"}
    assert _slim_raw({"incarceration_check": stamp})["incarceration_check"] == stamp
