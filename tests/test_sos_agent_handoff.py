"""NC SOS registered-agent hand-off (2026-10-05): the Mac looks entities up and pushes a
cumulative ledger (docs/handoff/sos_agent_results.json); the VM applies it during its run.

Covers, with no network and no write to the real board:
  * the ledger never loses an entry (record_result / merge_ledgers / save+load round trip)
  * the recheck policy (resolved never, answered miss 30 d, no-answer 3 d)
  * seeding from profiles already on the board, without spreading a stale profile to a new owner
  * the adaptive cap: back off on a breaker trip / failed session / mostly no-answers, step up
    after a clean run, hold otherwise
  * the VM apply: the exact raw['sos_agent'] shape, propagated to every row of the entity,
    and a missing / stale / unreadable / broken hand-off is never fatal
  * _batch_lookup's breaker: answered misses do not trip it, no-answers and block pages do
  * scripts/sos_agent_refresh.py end to end on a scratch board, which it must not modify
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_sos_agent as sa
from foreclosure_scraper import sos_agent_handoff as ho
from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.models import Listing, ListingType

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import sos_agent_refresh as sar  # noqa: E402


def _prof(sosid="42", **kw):
    p = {"checked": True, "source": "nc_sos", "legal_name": "Acme Holdings, LLC", "sosid": sosid,
         "status": "Current-Active", "registered_agent": "Jane Owner",
         "best_contact_name": "Jane Owner", "best_contact_address": "1 Main St, Shelby, NC 28150",
         "agent_is_service": False, "profile_url": "https://www.sosnc.gov/x", "match_count": 1}
    p.update(kw)
    return p


def _li(owner, state="NC", raw=None, i=0, **kw):
    return Listing(source="x", source_url=f"https://example.test/{i}",
                   listing_type=ListingType.FORECLOSURE_SALE, state=state, county="Gaston",
                   street_address=f"{i + 1} Main St", zip_code="28052",
                   owner_name=owner, raw=raw or {}, **kw)


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------

def test_entity_key_ignores_case_punctuation_and_spacing():
    assert sa.entity_key("ACME HOLDINGS, LLC") == sa.entity_key("Acme  Holdings LLC") == \
        "acme holdings llc"
    assert sa.entity_key("A&B Rentals, Inc.") == "a b rentals inc"


def test_record_result_never_loses_a_resolved_profile():
    ents: dict = {}
    ho.record_result(ents, "ACME HOLDINGS LLC", "resolved", _prof(), today="2026-10-01")
    ho.record_result(ents, "Acme Holdings, LLC", "miss", today="2026-10-05")
    ho.record_result(ents, "acme holdings llc", "error", today="2026-10-06")
    (e,) = ents.values()
    assert e["status"] == "resolved" and e["profile"]["sosid"] == "42"
    assert e["checks"] == 3 and e["last_attempt"] == "error" and e["checked_at"] == "2026-10-06"
    assert e["first_checked_at"] == "2026-10-01"


def test_record_result_upgrades_but_never_downgrades():
    ents: dict = {}
    ho.record_result(ents, "BETA LLC", "error", today="2026-10-01")
    assert ents["beta llc"]["status"] == "error"
    ho.record_result(ents, "BETA LLC", "miss", today="2026-10-02")
    assert ents["beta llc"]["status"] == "miss"
    ho.record_result(ents, "BETA LLC", "error", today="2026-10-03")
    assert ents["beta llc"]["status"] == "miss", "a no-answer must not erase an answered miss"
    ho.record_result(ents, "BETA LLC", "resolved", _prof("7"), today="2026-11-05")
    assert ents["beta llc"]["status"] == "resolved" and ents["beta llc"]["profile"]["sosid"] == "7"
    with pytest.raises(ValueError):
        ho.record_result(ents, "GAMMA LLC", "resolved", {"sosid": ""})


def test_merge_ledgers_is_a_union_that_keeps_the_best_of_each_entry():
    a = ho.empty_ledger()
    b = ho.empty_ledger()
    ho.record_result(a["entities"], "ONLY IN A LLC", "miss", today="2026-10-01")
    ho.record_result(b["entities"], "ONLY IN B LLC", "resolved", _prof("1"), today="2026-10-02")
    ho.record_result(a["entities"], "SHARED LLC", "resolved", _prof("5"), today="2026-10-01")
    ho.record_result(b["entities"], "SHARED LLC", "miss", today="2026-10-04")
    ho.record_result(a["entities"], "UPGRADE LLC", "miss", today="2026-10-01")
    ho.record_result(b["entities"], "UPGRADE LLC", "resolved", _prof("9"), today="2026-10-03")

    ho.merge_ledgers(a, b)
    ents = a["entities"]
    assert set(ents) == {"only in a llc", "only in b llc", "shared llc", "upgrade llc"}
    assert ents["shared llc"]["status"] == "resolved" and ents["shared llc"]["profile"]["sosid"] == "5"
    assert ents["shared llc"]["checked_at"] == "2026-10-04"
    assert ents["upgrade llc"]["status"] == "resolved" and ents["upgrade llc"]["profile"]["sosid"] == "9"
    # and the other way round loses nothing either
    ho.merge_ledgers(b, a)
    assert set(b["entities"]) == set(ents)


def test_save_and_load_round_trip_one_entity_per_line(tmp_path):
    p = tmp_path / "handoff" / "sos_agent_results.json"
    led = ho.empty_ledger()
    for i in range(5):
        ho.record_result(led["entities"], f"ENTITY {i} LLC", "miss", today="2026-10-05")
    ho.record_result(led["entities"], "ACME HOLDINGS LLC", "resolved", _prof(), today="2026-10-05")
    ho.save_ledger(led, p, host="test-host")
    text = p.read_text()
    back = ho.load_ledger(p)
    assert back["entities"] == led["entities"]
    assert back["counts"] == {"entities": 6, "resolved": 1, "miss": 5, "error": 0,
                              "ambiguous": 0, "mismatch": 0}
    assert back["host"] == "test-host" and back["schema"] == 1 and back["generated_at"]
    # one entity per line, so a day's commit is a few changed lines
    assert sum(1 for line in text.splitlines() if line.startswith('"entity ')) == 5
    assert not p.with_name(p.name + ".tmp").exists()


def test_unreadable_ledger_raises_instead_of_looking_empty(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{not json")
    with pytest.raises(ho.LedgerUnreadable):
        ho.load_ledger(p)
    p.write_text('{"leads": []}')
    with pytest.raises(ho.LedgerUnreadable):
        ho.load_ledger(p)
    assert ho.load_ledger(tmp_path / "missing.json")["entities"] == {}


def test_recheck_policy(monkeypatch):
    monkeypatch.delenv("SOS_AGENT_RECHECK_DAYS", raising=False)
    monkeypatch.delenv("SOS_AGENT_ERROR_RECHECK_DAYS", raising=False)
    ents: dict = {}
    ho.record_result(ents, "R LLC", "resolved", _prof(), today="2020-01-01")
    ho.record_result(ents, "M LLC", "miss", today="2026-10-01")
    ho.record_result(ents, "E LLC", "error", today="2026-10-01")
    assert ho.is_due(None, "2026-10-05")
    assert not ho.is_due(ents["r llc"], "2030-01-01"), "resolved is never re-checked"
    assert not ho.is_due(ents["m llc"], "2026-10-30")
    assert ho.is_due(ents["m llc"], "2026-10-31")
    assert not ho.is_due(ents["e llc"], "2026-10-03")
    assert ho.is_due(ents["e llc"], "2026-10-04")


# ---------------------------------------------------------------------------
# seeding from profiles already on the board
# ---------------------------------------------------------------------------

def test_seed_uses_resolved_for_entity_when_stamped():
    prof = _prof(resolved_for_entity="ACME HOLDINGS LLC", resolved_at="2026-10-03")
    assert ho.seed_names_for_board_profile(prof, "SOMEONE ELSE LLC") == ["ACME HOLDINGS LLC"]


def test_seed_legacy_profile_files_under_current_owner_only_when_it_is_the_same_entity():
    prof = _prof(legal_name="Acme Holdings, L.L.C.")          # legacy: no resolved_for_entity
    names = ho.seed_names_for_board_profile(prof, "ACME HOLDINGS LLC")
    assert [sa.entity_key(n) for n in names] == ["acme holdings l l c", "acme holdings llc"]


def test_seed_never_files_a_stale_profile_under_the_new_owner():
    """docs/HANDOFF.md item 57: the owner changed after the lookup (e.g. now NEWDOMINION BANK).
    Filing BECM's agent under the bank would spread it to every bank-owned row."""
    prof = _prof(legal_name="BECM Properties LLC")
    names = ho.seed_names_for_board_profile(prof, "NEWDOMINION BANK INC")
    assert [sa.entity_key(n) for n in names] == ["becm properties llc"]
    ents: dict = {}
    ho.seed_from_board_profile(ents, prof, "NEWDOMINION BANK INC", today="2026-10-05")
    assert set(ents) == {"becm properties llc"}
    assert ents["becm properties llc"]["source"] == "board_seed"
    assert ents["becm properties llc"]["checks"] == 0, "a seed is not a lookup"
    assert ents["becm properties llc"]["profile"] == prof, "copied as-is, nothing invented"


# ---------------------------------------------------------------------------
# adaptive cap
# ---------------------------------------------------------------------------

LIM = (150, 40, 25)


def _oc(attempted, errors=0, **kw):
    o = {"attempted": attempted, "errors": ["x"] * errors, "resolved": [], "misses": [],
         "breaker_tripped": False, "deadline_hit": False, "session_failed": False}
    o.update(kw)
    return o


def test_backoff_halves_on_breaker_trip_with_a_floor():
    assert ho.next_cap(150, _oc(30, 6, breaker_tripped=True), 150, LIM)[:2] == (75, "back_off")
    assert ho.next_cap(75, _oc(30, 6, breaker_tripped=True), 75, LIM)[:2] == (40, "back_off")
    assert ho.next_cap(40, _oc(30, 6, breaker_tripped=True), 40, LIM)[:2] == (40, "back_off")


def test_backoff_on_failed_session_or_mostly_no_answers():
    assert ho.next_cap(150, _oc(0, session_failed=True), 150, LIM)[:2] == (75, "back_off")
    assert ho.next_cap(150, _oc(20, 11), 150, LIM)[:2] == (75, "back_off")
    nxt, verdict, why = ho.next_cap(150, _oc(20, 11), 150, LIM)
    assert "11/20" in why


def test_steps_back_up_after_clean_runs_toward_the_max():
    cap, seen = 40, []
    for _ in range(6):
        cap, verdict, _why = ho.next_cap(cap, _oc(cap, 1), cap, LIM)
        seen.append(cap)
    assert seen == [65, 90, 115, 140, 150, 150]


def test_holds_on_a_middling_run_a_deadline_or_no_targets():
    assert ho.next_cap(100, _oc(100, 20), 100, LIM)[:2] == (100, "hold")       # 20% no-answer
    assert ho.next_cap(100, _oc(80, 0, deadline_hit=True), 100, LIM)[:2] == (100, "hold")
    assert ho.next_cap(100, _oc(0), 0, LIM)[:2] == (100, "hold")


def test_choose_cap_reads_and_clamps_the_state():
    assert ho.choose_cap({}, LIM)[0] == 150
    assert ho.choose_cap({"cap": 75, "reason": "back_off: breaker"}, LIM) == (75, "back_off: breaker")
    assert ho.choose_cap({"cap": 10}, LIM)[0] == 40
    assert ho.choose_cap({"cap": 999}, LIM)[0] == 150


def test_cap_limits_from_env(monkeypatch):
    monkeypatch.setenv("SOS_AGENT_MAX_CHECK", "30")
    monkeypatch.setenv("SOS_AGENT_MIN_CHECK", "40")
    assert ho.cap_limits()[:2] == (30, 30), "the floor can never sit above the ceiling"


def test_backoff_state_round_trip(tmp_path):
    p = tmp_path / "s.json"
    assert ho.load_backoff(p) == {}
    ho.save_backoff({"cap": 75, "reason": "x"}, p)
    assert ho.load_backoff(p)["cap"] == 75


# ---------------------------------------------------------------------------
# VM apply
# ---------------------------------------------------------------------------

def _write_handoff(path: Path, entities: dict, generated_at: datetime | None = None):
    led = ho.empty_ledger()
    led["entities"] = entities
    ho.save_ledger(led, path, host="mac", now=generated_at)


def test_apply_attaches_the_exact_profile_to_every_row_of_the_entity(tmp_path):
    prof = sa.stamp_profile(_prof(), "ACME HOLDINGS LLC")
    ents: dict = {}
    ho.record_result(ents, "ACME HOLDINGS LLC", "resolved", prof)
    ho.record_result(ents, "MISSING LLC", "miss")
    ho.record_result(ents, "TIMEOUT LLC", "error")
    p = tmp_path / "sos_agent_results.json"
    _write_handoff(p, ents)

    rows = [
        _li("ACME HOLDINGS LLC", i=0),
        _li("Acme Holdings, LLC", i=1),                       # same entity, other spelling
        _li("ACME HOLDINGS LLC", i=2, raw={"sos_agent": {"sosid": "9"}}),   # keeps its own
        _li("ACME HOLDINGS LLC", state="SC", i=3),            # SC: never (CAPTCHA-walled state)
        _li("Jane Q. Person", i=4),                           # not an entity
        _li("MISSING LLC", i=5),                              # answered miss: nothing to attach
        _li("TIMEOUT LLC", i=6),
        Listing(source="x", source_url="u7", listing_type=ListingType.FORECLOSURE_SALE,
                state="NC", county="Gaston", owner_name=None, defendant="ACME HOLDINGS LLC"),
    ]
    out = ho.apply_sos_agent_handoff(rows, path=p)

    assert out["status"] == "ok" and out["attached"] == 3
    assert out["resolved_entities"] == 1 and out["entities"] == 3
    for i in (0, 1, 7):
        assert rows[i].raw["sos_agent"] == prof, f"row {i}"
    assert rows[0].raw["sos_agent"]["resolved_for_entity"] == "ACME HOLDINGS LLC"
    assert rows[0].raw["sos_agent"] is not rows[1].raw["sos_agent"], "each row gets its own copy"
    assert rows[2].raw["sos_agent"] == {"sosid": "9"}
    for i in (3, 4, 5, 6):
        assert "sos_agent" not in rows[i].raw, f"row {i}"


def test_apply_output_survives_the_publish_slim(tmp_path):
    prof = sa.stamp_profile(_prof(), "ACME HOLDINGS LLC")
    ents: dict = {}
    ho.record_result(ents, "ACME HOLDINGS LLC", "resolved", prof)
    p = tmp_path / "h.json"
    _write_handoff(p, ents)
    row = _li("ACME HOLDINGS LLC")
    ho.apply_sos_agent_handoff([row], path=p)
    assert wa.RAW_KEEP.get("sos_agent") == "*"
    assert wa._slim_raw(row.raw)["sos_agent"] == prof


def test_missing_handoff_is_not_fatal(tmp_path):
    rows = [_li("ACME HOLDINGS LLC")]
    out = ho.apply_sos_agent_handoff(rows, path=tmp_path / "nope.json")
    assert out["status"] == "absent" and out["attached"] == 0
    assert "sos_agent" not in rows[0].raw


def test_stale_handoff_is_logged_and_still_applied(tmp_path, monkeypatch):
    ents: dict = {}
    ho.record_result(ents, "ACME HOLDINGS LLC", "resolved", _prof())
    p = tmp_path / "h.json"
    _write_handoff(p, ents, generated_at=datetime.now(timezone.utc) - timedelta(days=10))
    seen = []
    monkeypatch.setattr(ho.log, "warning", lambda ev, **kw: seen.append((ev, kw)))
    rows = [_li("ACME HOLDINGS LLC")]
    out = ho.apply_sos_agent_handoff(rows, path=p)
    assert out["status"] == "stale" and out["age_hours"] > 230
    assert out["attached"] == 1 and rows[0].raw["sos_agent"]["sosid"] == "42"
    assert seen and seen[0][0] == "sos_agent_handoff.stale"


def test_unreadable_or_broken_handoff_is_not_fatal(tmp_path, monkeypatch):
    p = tmp_path / "h.json"
    p.write_text("{garbage")
    rows = [_li("ACME HOLDINGS LLC")]
    assert ho.apply_sos_agent_handoff(rows, path=p)["status"] == "unreadable"

    ents: dict = {}
    ho.record_result(ents, "ACME HOLDINGS LLC", "resolved", _prof())
    _write_handoff(p, ents)

    def boom(*a, **k):
        raise RuntimeError("simulated bug")
    monkeypatch.setattr(ho, "propagate_profiles", boom)
    out = ho.apply_sos_agent_handoff(rows, path=p)
    assert out["status"] == "error" and "simulated bug" in out["error"]


def test_apply_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SOS_AGENT_HANDOFF_APPLY", "0")
    assert ho.apply_sos_agent_handoff([], path=tmp_path / "x.json")["status"] == "disabled"


def test_main_runs_the_apply_step_for_every_role_before_the_gated_live_phase():
    src = (REPO / "src" / "foreclosure_scraper" / "main.py").read_text()
    i_apply = src.index("apply_sos_agent_handoff(enriched)")
    i_live = src.index("enrich_with_sos_agent(enriched)")
    assert i_apply < i_live
    block = src[src.rindex("try:", 0, i_apply):i_apply]
    assert "FORECLOSURE_ROLE" not in block.split("try:")[-1], "the apply must not be role-gated"


# ---------------------------------------------------------------------------
# _batch_lookup: the breaker counts no-answers, not answered misses
# ---------------------------------------------------------------------------

class _FakePage:
    """Just enough of a Playwright page for _batch_lookup's _one()."""

    def __init__(self, script):
        self.script = script          # name core -> "hit" | "miss" | "block" | "raise"
        self.core = None
        self.url = "https://www.sosnc.gov/online_services/search/Business_Registration_Results"
        self._title = "Business Registration Results"

    async def goto(self, url):
        if "Business_Registration_Profile" in url:
            self.url = url

    async def wait_for_selector(self, sel, timeout=0):
        return True

    async def fill(self, sel, value):
        self.core = value
        if self.script.get(value) == "raise":
            raise RuntimeError("Timeout 20000ms exceeded")

    async def eval_on_selector(self, sel, js):
        return None

    async def wait_for_load_state(self, state, timeout=0):
        return None

    async def eval_on_selector_all(self, sel, js):
        kind = self.script.get(self.core)
        self._title = "Just a moment..." if kind == "block" else "Business Registration Results"
        return ["/online_services/search/Business_Registration_Profile?Id=1"] if kind == "hit" else []

    async def content(self):
        # the result list _one() reads to choose the hit (real structure: one accordion per
        # entity, tests/fixtures/sosnc_search_*.html); only a "hit" gets this far
        return ('<div class="usa-accordion__heading"><button aria-controls="a1">'
                '<div class="searchHeader">Hit LLC <span> • 77</span></div>'
                '<div class="searchSubHeader">Current - Active • Limited Liability Company</div>'
                '</button></div><div id="a1" class="usa-accordion__content" hidden="">'
                '<div class="para-small"><span class="boldSpan">Legal name:</span> Hit LLC</div>'
                '<div class="para-small"><span class="boldSpan">Status:</span> Current - Active</div>'
                '<div class="para-small"><a href="/online_services/search/'
                'Business_Registration_Profile?Id=1">More information</a></div></div>')

    async def inner_text(self, sel):
        return "Legal name: Hit LLC\nSecretary of State Identification Number (SOSID): 77\n"

    async def title(self):
        return self._title


def _install_fake_scrapling(monkeypatch, page):
    async def async_fetch(url, page_action=None, **kw):
        await page_action(page)

    mod = types.ModuleType("scrapling.fetchers")
    mod.StealthyFetcher = types.SimpleNamespace(async_fetch=async_fetch)
    monkeypatch.setitem(sys.modules, "scrapling", types.ModuleType("scrapling"))
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", mod)


def test_answered_misses_do_not_trip_the_breaker(monkeypatch):
    names = [f"MISS{i} LLC" for i in range(10)] + ["HIT LLC"]
    script = {f"MISS{i}": "miss" for i in range(10)} | {"HIT": "hit"}
    _install_fake_scrapling(monkeypatch, _FakePage(script))
    monkeypatch.setattr(sa, "_PAUSE_MIN_S", 0.0)
    monkeypatch.setattr(sa, "_PAUSE_MAX_S", 0.0)
    oc: dict = {}
    res = asyncio.run(sa._batch_lookup(names, outcome=oc))
    assert oc["attempted"] == 11 and not oc["breaker_tripped"]
    assert oc["misses"] == names[:10] and oc["resolved"] == ["HIT LLC"] and oc["errors"] == []
    assert res["HIT LLC"]["sosid"] == "77"


def test_no_answers_and_block_pages_trip_the_breaker(monkeypatch):
    names = ["A LLC", "B LLC", "C LLC", "D LLC", "E LLC", "F LLC", "G LLC", "H LLC"]
    script = {"A": "raise", "B": "block", "C": "raise", "D": "block", "E": "raise",
              "F": "raise", "G": "hit", "H": "hit"}
    _install_fake_scrapling(monkeypatch, _FakePage(script))
    monkeypatch.setattr(sa, "_PAUSE_MIN_S", 0.0)
    monkeypatch.setattr(sa, "_PAUSE_MAX_S", 0.0)
    oc: dict = {}
    asyncio.run(sa._batch_lookup(names, outcome=oc))
    assert oc["breaker_tripped"] and oc["attempted"] == 6
    assert oc["errors"] == names[:6] and oc["misses"] == [] and oc["resolved"] == []


def test_polite_pause_runs_between_lookups_not_before_the_first(monkeypatch):
    _install_fake_scrapling(monkeypatch, _FakePage({"A": "miss", "B": "miss", "C": "hit"}))
    calls = []

    async def fake_sleep(s):
        calls.append(s)
    monkeypatch.setattr(sa.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sa, "_PAUSE_MIN_S", 4.0)
    monkeypatch.setattr(sa, "_PAUSE_MAX_S", 6.0)
    asyncio.run(sa._batch_lookup(["A LLC", "B LLC", "C LLC"], outcome={}))
    assert len(calls) == 2 and all(4.0 <= s <= 6.0 for s in calls)


def test_session_failure_is_reported(monkeypatch):
    async def async_fetch(url, page_action=None, **kw):
        raise RuntimeError("net::ERR_INTERNET_DISCONNECTED")
    mod = types.ModuleType("scrapling.fetchers")
    mod.StealthyFetcher = types.SimpleNamespace(async_fetch=async_fetch)
    monkeypatch.setitem(sys.modules, "scrapling", types.ModuleType("scrapling"))
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", mod)
    oc: dict = {}
    assert asyncio.run(sa._batch_lookup(["A LLC"], outcome=oc)) == {}
    assert oc["session_failed"] and "DISCONNECTED" in oc["error"]
    assert ho.next_cap(150, oc, 1, LIM)[1] == "back_off"


# ---------------------------------------------------------------------------
# scripts/sos_agent_refresh.py end to end on a scratch board
# ---------------------------------------------------------------------------

def _board_rows() -> list[Listing]:
    legacy = {"sosid": "1", "legal_name": "ACME HOLDINGS LLC", "best_contact_name": "Prior Officer"}
    return [
        _li("ACME HOLDINGS LLC", i=0, raw={"sos_agent": legacy}),       # already on the board
        _li("ACME HOLDINGS LLC", i=1),                                  # co-owned: VM will fill it
        _li("GAMMA PROPERTIES LLC", i=2),                               # new, no tier
        _li("BETA VENTURES LLC", i=3, raw={"distress_stack": {"tier": "HOT"}}),   # new, HOT
        _li("Jane Q. Person", i=4),                                     # not an entity
        _li("DELTA HOLDINGS LLC", state="SC", i=5),                     # out of scope
        _li("Beta Ventures, LLC", i=6),                                 # BETA again, other spelling
    ]


def _board_digest(docs: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(docs.rglob("*")):
        if p.is_file() and "handoff" not in p.parts:
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    wa.write_artifact(_board_rows(), {"notes": "sos hand-off seed"}, docs_dir=docs)
    monkeypatch.setattr(sar, "REPO", repo)
    monkeypatch.setattr(sar, "DOCS", docs)
    monkeypatch.setattr(sar, "HANDOFF", docs / "handoff" / "sos_agent_results.json")
    monkeypatch.setattr(sar, "BACKOFF", repo / "data" / "sos_agent_backoff.json")
    monkeypatch.setattr(sar, "RUN_LOCK", repo / "logs" / ".sos_agent_refresh.lock")
    monkeypatch.setattr(sar, "PUSH", False)
    monkeypatch.setenv("SOS_AGENT", "1")
    monkeypatch.setenv("SOS_AGENT_OUTCOME_FILE", str(repo / "logs" / "outcome"))
    for k in ("SOS_AGENT_MAX_CHECK", "SOS_AGENT_MIN_CHECK", "SOS_AGENT_CAP_STEP"):
        monkeypatch.delenv(k, raising=False)
    return repo


def test_refresh_writes_the_ledger_and_never_the_board(scratch, monkeypatch):
    docs = scratch / "docs"
    before = _board_digest(docs)
    asked = []

    async def fake_batch(names, outcome=None):
        asked.append(list(names))
        outcome.update({"attempted": len(names), "resolved": [], "misses": [], "errors": [],
                        "breaker_tripped": False, "deadline_hit": False, "session_failed": False})
        res = {}
        for n in names:
            if sa.entity_key(n) == "beta ventures llc":
                res[n] = _prof("42", legal_name="Beta Ventures, LLC")
                outcome["resolved"].append(n)
            else:
                res[n] = None
                outcome["misses"].append(n)
        return res
    monkeypatch.setattr(sar, "_batch_lookup", fake_batch)

    assert sar.main([]) == 0
    assert _board_digest(docs) == before, "the Mac pass must not write the board"
    # HOT first; ACME is already known (seeded from the board), so never asked
    assert asked == [["BETA VENTURES LLC", "GAMMA PROPERTIES LLC"]]

    led = ho.load_ledger(scratch / "docs" / "handoff" / "sos_agent_results.json")
    ents = led["entities"]
    assert ents["acme holdings llc"]["source"] == "board_seed"
    assert ents["beta ventures llc"]["status"] == "resolved"
    assert ents["beta ventures llc"]["profile"]["resolved_for_entity"] == "BETA VENTURES LLC"
    assert ents["beta ventures llc"]["profile"]["resolved_at"]
    assert ents["gamma properties llc"]["status"] == "miss"
    assert led["last_run"]["resolved"] == 1 and led["last_run"]["awaiting_vm_rows"] == 3

    state = json.loads((scratch / "data" / "sos_agent_backoff.json").read_text())
    assert state["last_run"]["cap_used"] == 150 and state["cap"] == 150
    assert (scratch / "logs" / "outcome").read_text().splitlines()[0] == "ok"

    # second run: nothing left to ask (BETA resolved, GAMMA an answered miss < 30 days old)
    asked.clear()
    assert sar.main([]) == 0
    assert asked == []
    assert set(ho.load_ledger(scratch / "docs" / "handoff" / "sos_agent_results.json")["entities"]) \
        == set(ents), "a run with nothing to do still loses nothing"

    # and the VM side, fed this ledger, fills both BETA rows + the co-owned ACME row
    rows = _board_rows()
    out = ho.apply_sos_agent_handoff(rows, path=scratch / "docs" / "handoff" / "sos_agent_results.json")
    assert out["attached"] == 3
    assert rows[1].raw["sos_agent"]["best_contact_name"] == "Prior Officer"
    assert rows[3].raw["sos_agent"]["sosid"] == "42" and rows[6].raw["sos_agent"]["sosid"] == "42"
    assert "sos_agent" not in rows[2].raw


def test_manual_cap_never_raises_the_adaptive_cap_but_a_bad_run_lowers_it(scratch, monkeypatch):
    async def walled(names, outcome=None):
        outcome.update({"attempted": 0, "resolved": [], "misses": [], "errors": [],
                        "breaker_tripped": False, "deadline_hit": False, "session_failed": True,
                        "error": "net::ERR_INTERNET_DISCONNECTED"})
        return {}
    monkeypatch.setattr(sar, "_batch_lookup", walled)
    assert sar.main(["--cap", "1"]) == 0
    state = json.loads((scratch / "data" / "sos_agent_backoff.json").read_text())
    assert state["last_run"]["cap_used"] == 1 and state["cap"] == 75
    assert state["reason"].startswith("back_off")
    # the no-answer names were not recorded as misses: nothing was attempted
    assert ho.load_ledger(scratch / "docs" / "handoff" / "sos_agent_results.json")["counts"]["miss"] == 0


def test_dry_run_writes_nothing(scratch, monkeypatch):
    async def must_not_run(names, outcome=None):
        raise AssertionError("dry run looked something up")
    monkeypatch.setattr(sar, "_batch_lookup", must_not_run)
    assert sar.main(["--dry-run"]) == 0
    assert not (scratch / "docs" / "handoff" / "sos_agent_results.json").exists()
    assert not (scratch / "data" / "sos_agent_backoff.json").exists()


def test_an_unreadable_ledger_is_never_overwritten(scratch, monkeypatch):
    p = scratch / "docs" / "handoff" / "sos_agent_results.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{truncated")
    assert sar.main([]) == 1
    assert p.read_text() == "{truncated"


def test_the_mac_pass_holds_no_board_write_path():
    import ast
    tree = ast.parse((REPO / "scripts" / "sos_agent_refresh.py").read_text())
    called = {(n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", ""))
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    for banned in ("patch_existing_rows", "write_artifact", "load_board", "read_board_records"):
        assert banned not in called and banned not in imported, banned
    sh = (REPO / "scripts" / "sos_agent_refresh.sh").read_text()
    assert "board_lock_acquire" not in sh and "publish_commit" not in sh
    assert 'SOS_AGENT_MAX_CHECK:-150' in sh and "SOS_TIMEOUT:-${SOS_MAX_RUNTIME:-4200}" in sh
