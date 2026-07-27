"""Vision pool: flaky lanes + ungraded (condition_tier null) results.

Two gaps the bounded-re-queue fix left open, both measured on the live pool:

1. FLAKY LANES ate listings' attempt budgets. The re-queue budget used to be
   GLOBAL per listing (1 + VISION_MAX_REQUEUE attempts total). Intermittent
   backends (verified live 2026-07-27: mistral-medium-3.5-128b answered 1 of 4
   real calls, llama-3.2-11b-vision 3 of 4) never accumulate
   VISION_BACKEND_HARD_FAILS *consecutive* failures, so they never retire and
   keep drawing work. Three bounces off flaky lanes burned a listing's whole
   budget and it was given up on while a HEALTHY lane sat right there — a
   60-listing / 3-flaky + 1-healthy stress test scored only 57.
   The budget is now per-listing-PER-BACKEND (each lane gets one turn, plus
   VISION_MAX_REQUEUE extra retries once every live lane has had its turn), and
   the pop side prefers a listing the popping lane has not tried.

2. A condition_tier=null result still wrote raw["vision"], which is exactly what
   needs_vision()/_vpri read as "already scored" — so one weak lane (7 of 9
   lanes returned null on a real-photo probe) could permanently lock a lead out
   of ever being graded. A null tier now re-queues to another lane, and if every
   lane declines it lands in raw["vision_unscored"] (not in
   web_artifact.RAW_KEEP → never published) so the lead stays re-gradable.

All FAKE backends, no network.
"""
from __future__ import annotations

import asyncio

import pytest

import foreclosure_scraper.enrichment_vision as ev
from foreclosure_scraper.models import Listing


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _mk_listing(n: int, source_url: str | None = None) -> Listing:
    return Listing(
        source="test",
        source_url=source_url or f"https://example.test/listing/{n}",
        raw={"images": {"real": [f"https://img.test/{n}.jpg"]}},
    )


class _Lane:
    """Fake backend. `mode` decides what each call returns.

    healthy — always a real graded report
    dead    — always None (mirrors HTTP 410/404/parse-fail)
    flaky   — graded on every `period`-th call, None otherwise. Because a
              success resets the consecutive-hard-fail counter, a flaky lane
              NEVER retires; that is the whole point of the regression.
    null    — always answers, always with condition_tier null (weak lane, or a
              basemap-only property)
    """

    def __init__(self, name: str, mode: str, period: int = 4,
                 idx: int = 0, ledger: list | None = None):
        self.name = name
        self.model = f"fake/{name}"
        self.delay = 0.0
        self.cap = 1
        self.mode = mode
        self.period = period
        self.calls = 0
        self.seen: list[int] = []          # id(li) per call
        self.idx = idx
        self.ledger = ledger               # shared, time-ordered (lane, id(li))

    def _report(self, tier, li, payloads, urls):
        return ev._finalize({"condition_tier": tier, "confidence": "HIGH"},
                            self.name, self.model, len(payloads), urls)

    async def assess(self, li, payloads, urls):
        self.calls += 1
        self.seen.append(id(li))
        if self.ledger is not None:
            self.ledger.append((self.idx, id(li)))
        await asyncio.sleep(0)             # yield like a real network call
        if self.mode == "healthy":
            return self._report("cosmetic", li, payloads, urls)
        if self.mode == "dead":
            return None
        if self.mode == "null":
            return self._report(None, li, payloads, urls)
        if self.mode == "flaky":
            if self.calls % self.period == 0:
                return self._report("major", li, payloads, urls)
            return None
        raise AssertionError(f"bad mode {self.mode}")


@pytest.fixture
def pool(monkeypatch):
    async def _fake_fetch(li, http):
        return [(b"\xff\xd8fake-jpeg", "image/jpeg")], ["https://img.test/x.jpg"]

    monkeypatch.setattr(ev, "_fetch_image_blocks", _fake_fetch)
    monkeypatch.setenv("VISION_USE_OLLAMA", "0")
    monkeypatch.setenv("VISION_MAX_SECONDS", "0")
    monkeypatch.setenv("VISION_BACKEND_COOLDOWN", "0")
    # Pure timing knob: the idle poll a worker uses while peers are still
    # holding items. Shortened so these tests aren't dominated by sleeps.
    monkeypatch.setenv("VISION_IDLE_TICK", "0.01")

    def _install(backends):
        async def _fake_build(http):
            return list(backends)
        monkeypatch.setattr(ev, "_build_backends", _fake_build)

    return _install


def _run(listings, timeout: float = 30):
    asyncio.run(asyncio.wait_for(ev.enrich_with_vision(listings), timeout=timeout))


def _scored(li: Listing) -> bool:
    """The same test needs_vision()/_vpri apply: raw["vision"] present."""
    return bool(isinstance(li.raw, dict) and li.raw.get("vision"))


def _attempts_by_listing(lanes) -> dict[int, int]:
    out: dict[int, int] = {}
    for b in lanes:
        for k in b.seen:
            out[k] = out.get(k, 0) + 1
    return out


# ---------------------------------------------------------------------------
# 1. THE GAP: flaky lanes must not burn a listing's budget
# ---------------------------------------------------------------------------

def test_flaky_lanes_plus_one_healthy_scores_every_listing(pool, monkeypatch):
    """3 flaky lanes + 1 healthy, 60 listings → 60/60 (was 57/60)."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "5")

    flaky = [_Lane(f"nvidia:flaky{i}", "flaky", period=4) for i in range(3)]
    healthy = _Lane("gemini#1", "healthy")
    pool(flaky + [healthy])

    listings = [_mk_listing(i) for i in range(60)]
    _run(listings)

    n = sum(_scored(li) for li in listings)
    assert n == 60, f"only {n}/60 scored — flaky lanes ate the attempt budget"
    # Flaky lanes stay alive all run (a success resets the hard-fail counter),
    # which is exactly why a GLOBAL budget failed here.
    assert all(b.calls > 5 for b in flaky), "flaky lanes should never retire"


def test_fast_flaky_lanes_cannot_outrun_a_slow_healthy_lane(pool, monkeypatch):
    """Production shape: the free NIM lanes are FAST (delay 2s) and flaky, the
    good lane is SLOW (Gemini paces at 6s). Under the old global budget the fast
    lanes burned every listing's attempts before the slow one could take them —
    measured 34/60 with the cap forced back to 3. Per-backend budget: 60/60."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "5")

    lanes = [_Lane(f"nvidia:flaky{i}", "flaky", period=4) for i in range(3)]
    healthy = _Lane("gemini#1", "healthy")
    healthy.delay = 0.02          # scaled-down stand-in for the 6s Gemini pace
    pool(lanes + [healthy])

    listings = [_mk_listing(i) for i in range(60)]
    _run(listings)

    n = sum(_scored(li) for li in listings)
    assert n == 60, f"only {n}/60 scored — fast flaky lanes outran the good one"


def test_listing_failed_on_one_lane_is_retried_on_an_untried_lane(pool, monkeypatch):
    """Per-BACKEND budget: even with the extra-retry budget at zero, a listing a
    dead lane failed still reaches an untried healthy lane."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "0")       # no same-lane retries at all
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")

    dead = _Lane("nvidia:dead-410", "dead")
    healthy = _Lane("gemini#1", "healthy")
    pool([dead, healthy])

    listings = [_mk_listing(i) for i in range(20)]
    _run(listings)

    assert all(_scored(li) for li in listings)
    for li in listings:
        assert li.raw["vision"]["_provider"] == "gemini#1"


def test_pop_prefers_a_lane_that_has_not_tried_the_listing(pool, monkeypatch):
    """Preference rule (b): no lane re-attempts a listing while a live lane that
    has never seen it could take it instead. With 3 lanes and a 3+2 budget, the
    first three attempts on every listing must come from three DIFFERENT lanes."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")

    ledger: list[tuple[int, int]] = []      # time-ordered (lane_idx, id(listing))
    lanes = [_Lane(f"dead{i}", "dead", idx=i, ledger=ledger) for i in range(3)]
    pool(lanes)
    listings = [_mk_listing(i) for i in range(12)]
    _run(listings)

    order: dict[int, list[int]] = {}
    for lane_idx, key in ledger:
        order.setdefault(key, []).append(lane_idx)
    assert len(order) == 12
    for key, lane_ids in order.items():
        assert len(lane_ids) >= 3, f"listing {key} only reached {lane_ids}"
        assert len(set(lane_ids[:3])) == 3, (
            f"a lane retried listing {key} before every lane had a turn: {lane_ids}")


# ---------------------------------------------------------------------------
# 2. Bounds — a dead pool terminates, attempts per listing are finite
# ---------------------------------------------------------------------------

def test_all_dead_pool_terminates_with_per_backend_budget(pool, monkeypatch):
    """Retirement disabled (HARD_FAILS=99) so ONLY the attempt budget can stop
    it. It still terminates, and the pool never loops forever."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")

    lanes = [_Lane(f"dead{i}", "dead") for i in range(4)]
    pool(lanes)
    listings = [_mk_listing(i) for i in range(40)]
    _run(listings)     # wait_for inside _run is the livelock guard

    assert not any(_scored(li) for li in listings)
    total = sum(b.calls for b in lanes)
    # 40 listings * (4 lanes + 2 extra retries) is the ceiling.
    assert total <= 40 * (4 + 2), f"unbounded: {total} calls"


def test_total_attempts_per_listing_is_bounded(pool, monkeypatch):
    """attempts(listing) <= len(backends) + VISION_MAX_REQUEUE, proven per id."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")

    lanes = [_Lane(f"dead{i}", "dead") for i in range(5)]
    pool(lanes)
    listings = [_mk_listing(i) for i in range(30)]
    _run(listings)

    per = _attempts_by_listing(lanes)
    bound = len(lanes) + 2
    worst = max(per.values())
    assert worst <= bound, f"a listing got {worst} attempts, bound is {bound}"
    assert len(per) == 30, "every listing should have been attempted at least once"


def test_attempt_budget_key_is_per_object_not_source_url(pool, monkeypatch):
    """Identity guard. 652 source_urls are shared by 19,392 live leads, so a
    url-keyed budget would let one lead spend thousands of others' attempts.
    Ten leads sharing ONE source_url must each get their own full budget."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")

    lanes = [_Lane("dead0", "dead")]
    pool(lanes)
    shared = "https://gis.example.test/arcgis/rest/services/Parcels/FeatureServer/0"
    listings = [_mk_listing(i, source_url=shared) for i in range(10)]
    assert len({li.source_url for li in listings}) == 1, "fixture must collide"
    assert len({id(li) for li in listings}) == 10, "id() must not collide"

    _run(listings)

    per = _attempts_by_listing(lanes)
    assert len(per) == 10, "budgets were merged across leads sharing a source_url"
    assert set(per.values()) == {3}, f"each lead should get 1+2 attempts, got {per}"


def test_floor_backend_present_does_not_deadlock_the_api_lanes(pool, monkeypatch):
    """A floor lane (local Ollama) waits for every API lane to exit before it
    takes anything. If the API lanes in turn waited for the floor to come pick
    up a listing they had all already tried, nothing would ever move. The floor
    is therefore not counted as "a lane that is coming" — API lanes finish, then
    the floor drains the leftovers."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")

    dead = _Lane("nvidia:dead", "dead")
    floor = _Lane("ollama", "healthy")
    floor.is_floor = True
    pool([dead, floor])

    listings = [_mk_listing(i) for i in range(8)]
    _run(listings, timeout=20)      # a deadlock shows up as TimeoutError

    assert all(_scored(li) for li in listings)
    assert all(li.raw["vision"]["_provider"] == "ollama" for li in listings)


def test_floor_backend_does_not_persist_a_null_tier_either(pool, monkeypatch):
    monkeypatch.setenv("VISION_MAX_REQUEUE", "0")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")

    floor = _Lane("ollama", "null")
    floor.is_floor = True
    pool([floor])

    listings = [_mk_listing(i) for i in range(5)]
    _run(listings, timeout=20)

    for li in listings:
        assert not _scored(li)
        assert li.raw.get("vision_unscored")


# ---------------------------------------------------------------------------
# 3. Ungraded (condition_tier null) results
# ---------------------------------------------------------------------------

def test_null_tier_is_requeued_to_another_lane_and_not_persisted(pool, monkeypatch):
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")

    weak = _Lane("nvidia:weak", "null")
    healthy = _Lane("gemini#1", "healthy")
    pool([weak, healthy])

    listings = [_mk_listing(i) for i in range(20)]
    _run(listings)

    assert all(_scored(li) for li in listings)
    for li in listings:
        assert li.raw["vision"]["condition_tier"] == "cosmetic"
        assert li.raw["vision"]["_provider"] == "gemini#1"
        assert "vision_unscored" not in li.raw, "a null report must not be kept once graded"


def test_all_null_pool_terminates_and_leaves_leads_regradable(pool, monkeypatch):
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")

    lanes = [_Lane(f"null{i}", "null") for i in range(3)]
    pool(lanes)
    listings = [_mk_listing(i) for i in range(25)]
    _run(listings)

    for li in listings:
        # THE POINT: no raw["vision"], so needs_vision() still returns True and
        # the lead gets a real grader on the next run.
        assert not _scored(li), "a null-tier report must not count as a score"
        assert li.raw.get("vision_unscored"), "the null report should be kept for diagnostics"
        assert li.raw["vision_unscored"]["condition_tier"] is None
        assert "condition_tier" not in li.raw, "no tier override from a null grade"

    per = _attempts_by_listing(lanes)
    assert max(per.values()) <= len(lanes) + 2, "null loop is not bounded"


def test_ungraded_report_never_reaches_the_published_board(tmp_path, pool, monkeypatch):
    """raw["vision_unscored"] is absent from web_artifact.RAW_KEEP, so it is
    dropped on write — the lead comes back un-scored (re-gradable) next run."""
    from foreclosure_scraper import web_artifact

    monkeypatch.setenv("VISION_MAX_REQUEUE", "0")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")
    pool([_Lane("null0", "null")])
    listings = [_mk_listing(0)]
    _run(listings)
    assert listings[0].raw.get("vision_unscored")

    docs = tmp_path / "docs"          # TEMP docs dir — never the real one
    web_artifact.write_artifact(listings, {}, docs_dir=docs)
    board = web_artifact.load_board(docs)
    assert len(board) == 1
    assert "vision_unscored" not in (board[0].raw or {})
    assert not (board[0].raw or {}).get("vision"), "lead must load back un-scored"


def test_null_tier_does_not_count_a_hard_fail_against_a_live_lane(pool, monkeypatch):
    """A basemap-only property makes EVERY lane answer null. That is the
    property's fault, not the lane's — a good lane must not be retired for it."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "0")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "3")

    lane = _Lane("gemini#1", "null")
    pool([lane])
    listings = [_mk_listing(i) for i in range(15)]
    _run(listings)

    assert lane.calls == 15, f"lane retired on null tiers ({lane.calls} calls)"


# ---------------------------------------------------------------------------
# 4. _canonical_tier unit coverage (the null shapes seen live)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    None, "null", "NULL", "none", "n/a", "unknown", "condition_tier=null", "", 7, [],
])
def test_canonical_tier_rejects_non_tiers(value):
    d = {"condition_tier": value}
    assert ev._canonical_tier(d) is None
    assert d["condition_tier"] is None


@pytest.mark.parametrize("value,want", [
    ("cosmetic", "cosmetic"), (" GUT ", "gut"), ("Major", "major"),
    ("condition_tier=move_in_ready", "move_in_ready"),
])
def test_canonical_tier_accepts_real_tiers(value, want):
    d = {"condition_tier": value}
    assert ev._canonical_tier(d) == want
    assert d["condition_tier"] == want


def test_canonical_tier_handles_missing_key_and_non_dict():
    d: dict = {}
    assert ev._canonical_tier(d) is None
    assert ev._canonical_tier(None) is None
