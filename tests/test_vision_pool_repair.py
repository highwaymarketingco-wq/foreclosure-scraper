"""Vision pool repair, 2026-09-21 (docs/vision_repair_2026-09-21.md).

The daily 09:30 pass held the board lock for 4 hours to score 371-759 leads while
live_workers collapsed from 21 to 1 inside 40 minutes on every run. Root causes and the
guard each test pins:

  * no re-admission: a banned backend's worker simply returned, forever
        -> half-open circuit breaker (_LaneHealth): retry a banned lane after
           VISION_BACKEND_REOPEN_SECONDS (default 600).
  * permanent errors (410 end-of-life, 402 unpaid, 404 not entitled) each ate five
    listings before the lane retired
        -> BackendDisabled: disabled for the run on the FIRST occurrence.
  * every 429 got the same fixed 70s cooldown, and a DAILY cap (Cloudflare neurons,
    Gemini PerDay) was retried ten times
        -> exponential back-off with jitter that honours retry-after; daily -> disabled.
  * no HOT/WARM ordering and basemap-only rows were graded
        -> _vpri + photo-only targets.
  * a dead pool held the lock for 4 hours
        -> _YieldMonitor (collapse / low yield) + 90-minute wall clock default.

Everything here is offline: fake backends, fake clocks, a fake HTTP client.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

import httpx
import pytest
import structlog

import foreclosure_scraper.enrichment_vision as ev
from foreclosure_scraper.models import Listing


# ---------------------------------------------------------------------------
# fixtures / fakes
# ---------------------------------------------------------------------------

def _mk(n: int, tier: str | None = None, photo: bool = True, sale=None) -> Listing:
    raw: dict = {"images": {"real": [f"https://img.test/{n}.jpg"]}} if photo \
        else {"images": {"map": f"https://img.test/map{n}.png"}}
    if tier:
        raw["distress_stack"] = {"tier": tier}
    return Listing(source="test", source_url=f"https://example.test/l/{n}", raw=raw,
                   sale_date=sale)


class _Lane:
    """Duck-typed backend: name/model/delay/cap/workers/assess."""

    def __init__(self, name, mode="ok", *, delay=0.0, workers=1, work_s=0.0, **kw):
        self.name = name
        self.model = f"fake/{name}"
        self.delay = delay
        self.cap = 1
        self.workers = workers
        self.mode = mode
        self.work_s = work_s
        self.calls = 0
        self.stamps: list[float] = []
        self.order: list[str] = []
        self.concurrent = 0
        self.max_concurrent = 0
        self.kw = kw

    def _ok(self, li, payloads, urls):
        return ev._finalize({"condition_tier": "cosmetic", "confidence": "HIGH"},
                            self.name, self.model, len(payloads), urls)

    async def assess(self, li, payloads, urls):
        self.calls += 1
        self.stamps.append(time.monotonic())
        self.order.append(li.source_url)
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            await asyncio.sleep(self.work_s)
            if self.mode == "ok":
                return self._ok(li, payloads, urls)
            if self.mode == "none":                       # transient hard failure
                return None
            if self.mode == "disabled":                   # 410 / 402
                raise ev.BackendDisabled(self.name, self.kw.get("status", 410), "eol")
            if self.mode == "quota":
                raise ev.QuotaExhausted(self.name, retry_after=self.kw.get("retry_after"),
                                        daily=self.kw.get("daily", False))
            if self.mode == "recovering":                 # fails N times, then healthy
                if self.calls <= self.kw.get("fail_first", 2):
                    return None
                return self._ok(li, payloads, urls)
            if self.mode == "quota_then_ok":
                if self.calls <= self.kw.get("quota_first", 2):
                    raise ev.QuotaExhausted(self.name, retry_after=self.kw.get("retry_after"))
                return self._ok(li, payloads, urls)
            raise AssertionError(self.mode)
        finally:
            self.concurrent -= 1


@pytest.fixture
def pool(monkeypatch):
    async def _fake_fetch(li, http):
        return [(b"\xff\xd8fake-jpeg", "image/jpeg")], ["https://img.test/x.jpg"]

    monkeypatch.setattr(ev, "_fetch_image_blocks", _fake_fetch)
    monkeypatch.setenv("VISION_USE_OLLAMA", "0")
    monkeypatch.setenv("VISION_MAX_SECONDS", "0")
    monkeypatch.setenv("VISION_BACKEND_COOLDOWN", "0")
    monkeypatch.setenv("VISION_IDLE_TICK", "0.01")

    def _install(backends):
        async def _fake_build(http):
            return list(backends)
        monkeypatch.setattr(ev, "_build_backends", _fake_build)

    return _install


def _run(listings, timeout: float = 30.0):
    ev._LAST_RUN = {}
    asyncio.run(asyncio.wait_for(ev.enrich_with_vision(listings), timeout=timeout))


def _scored(li: Listing) -> bool:
    return bool(isinstance(li.raw, dict) and li.raw.get("vision"))


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


# ---------------------------------------------------------------------------
# 1. Circuit breaker: half-open re-admission
# ---------------------------------------------------------------------------

def test_breaker_bans_then_admits_exactly_one_probe_after_reopen():
    clk = _Clock()
    h = ev._LaneHealth("nvidia:x", hard_limit=3, reopen_s=600, clock=clk)
    for _ in range(2):
        assert h.record_hard_fail("timeout") is False
    assert h.gate() == ("go", 0.0)
    assert h.record_hard_fail("timeout") is True            # 3rd consecutive -> banned
    assert h.state == "open" and not h.up

    verdict, wait = h.gate()
    assert verdict == "wait" and 599 <= wait <= 600          # banned for 10 minutes

    clk.advance(599)
    assert h.gate()[0] == "wait"                             # one second early: still banned
    clk.advance(2)
    assert h.gate() == ("probe", 0.0)                        # half-open: ONE probe granted
    assert h.up                                              # a probe in flight counts as live
    assert h.gate()[0] == "wait", "a second worker must not also probe"

    assert h.record_success() is True                        # probe succeeded -> re-admitted
    assert h.state == "closed" and h.gate() == ("go", 0.0)
    assert h.hard_fails == 0 and h.readmissions == 1


def test_failed_probe_reopens_the_ban_for_another_full_window():
    clk = _Clock()
    h = ev._LaneHealth("x", hard_limit=1, reopen_s=600, clock=clk)
    h.record_hard_fail("timeout")
    clk.advance(601)
    assert h.gate() == ("probe", 0.0)
    assert h.record_hard_fail("timeout") is True             # probe failed
    assert h.state == "open" and h.trips == 2
    assert h.gate()[0] == "wait" and h.gate()[1] > 590       # a fresh 10 minutes
    clk.advance(601)
    assert h.gate() == ("probe", 0.0)


def test_a_permanent_disable_is_not_undone_by_a_late_failure_from_a_peer_worker():
    clk = _Clock()
    h = ev._LaneHealth("nvidia:x", hard_limit=2, reopen_s=600, clock=clk)
    h.record_hard_fail("timeout")                      # 1 of 2
    h.record_permanent(410, "eol")                     # a peer worker got the 410
    assert h.state == "disabled"
    h.record_hard_fail("timeout")                      # in-flight call of another worker fails late
    h.record_quota(retry_after=1.0)
    clk.advance(10_000)
    assert h.state == "disabled" and h.gate() == ("off", 0.0)


def test_reopen_zero_restores_legacy_retire_for_the_run():
    h = ev._LaneHealth("x", hard_limit=1, reopen_s=0, clock=_Clock())
    h.record_hard_fail("timeout")
    assert h.state == "disabled" and h.gate() == ("off", 0.0)


def test_banned_lane_is_readmitted_inside_a_live_pool(pool, monkeypatch):
    """End to end: a lane that fails twice is banned, is probed after the reopen
    window, succeeds, and goes back to scoring. Before the fix its worker had
    already returned, so it could never contribute again."""
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "2")
    monkeypatch.setenv("VISION_BACKEND_REOPEN_SECONDS", "0.3")
    flaky = _Lane("nvidia:flaky", "recovering", fail_first=2, delay=0.02)
    steady = _Lane("gemini#1", "ok", delay=0.03, work_s=0.02)
    pool([flaky, steady])
    listings = [_mk(i) for i in range(90)]
    _run(listings)

    stats = ev._LAST_RUN["backends"]["nvidia:flaky"]
    assert stats["trips"] >= 1 and stats["readmissions"] >= 1, stats
    assert flaky.calls > 2, "the banned lane was never probed again"
    assert any(li.raw["vision"]["_provider"] == "nvidia:flaky" for li in listings if _scored(li))
    assert all(_scored(li) for li in listings)


def test_still_dead_lane_gets_one_probe_per_window_not_a_flood(pool, monkeypatch):
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "2")
    monkeypatch.setenv("VISION_BACKEND_REOPEN_SECONDS", "0.25")
    dead = _Lane("nvidia:dead", "none")
    steady = _Lane("gemini#1", "ok", delay=0.04, work_s=0.01)
    pool([dead, steady])
    listings = [_mk(i) for i in range(60)]
    t0 = time.monotonic()
    _run(listings)
    elapsed = time.monotonic() - t0
    # 2 calls to trip, then at most one probe per 0.25s window.
    assert dead.calls >= 3
    assert dead.calls <= 2 + int(elapsed / 0.25) + 2, (dead.calls, elapsed)
    assert ev._LAST_RUN["backends"]["nvidia:dead"]["trips"] >= 2
    assert all(_scored(li) for li in listings)


# ---------------------------------------------------------------------------
# 2. 410 / 402 (and friends) disable the lane on the FIRST hit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [410, 402, 401, 403, 404])
def test_permanent_error_disables_lane_for_the_run_after_one_call(pool, status):
    dead = _Lane("nvidia:eol", "disabled", status=status)
    steady = _Lane("gemini#1", "ok", delay=0.0)
    pool([dead, steady])
    listings = [_mk(i) for i in range(40)]
    _run(listings)

    assert dead.calls == 1, f"a {status} lane must not be fed a second listing"
    st = ev._LAST_RUN["backends"]["nvidia:eol"]
    assert st["state"] == "disabled" and f"http{status}" in st["errors"]
    assert all(_scored(li) for li in listings), "the listing the dead lane held was lost"
    assert all(li.raw["vision"]["_provider"] == "gemini#1" for li in listings)


def test_disabled_lane_is_never_probed_again(pool, monkeypatch):
    monkeypatch.setenv("VISION_BACKEND_REOPEN_SECONDS", "0.05")     # would probe constantly
    dead = _Lane("github:gpt-4o", "disabled", status=410)
    steady = _Lane("gemini#1", "ok", delay=0.02, work_s=0.01)
    pool([dead, steady])
    _run([_mk(i) for i in range(50)])
    assert dead.calls == 1


def test_disabled_listing_does_not_spend_an_attempt(pool, monkeypatch):
    """The 410 lane never assessed the listing, so it must still have its full
    budget: with MAX_REQUEUE=0 and one attempt per lane, the healthy lane must
    still be allowed to score everything the dead lane popped."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "0")
    dead = _Lane("d", "disabled", status=402)
    steady = _Lane("gemini#1", "ok")
    pool([dead, steady])
    listings = [_mk(i) for i in range(20)]
    _run(listings)
    assert all(_scored(li) for li in listings)


def _fake_response(status, text="", headers=None):
    return httpx.Response(status, text=text, headers=headers or {},
                          request=httpx.Request("POST", "https://x.test"))


class _FakeHTTP:
    def __init__(self, resp):
        self.resp = resp
        self.timeouts = []

    async def post(self, url, json=None, timeout=None, headers=None):
        self.timeouts.append(timeout)
        return self.resp


def _assess(backend, li=None):
    li = li or _mk(0)
    return asyncio.run(backend.assess(li, [(b"\xff\xd8x", "image/jpeg")], ["u"]))


@pytest.mark.parametrize("status,body", [
    (410, '{"error":{"code":"github_models_retirement_brownout"}}'),
    (410, '{"detail":"The model has reached its end of life on 2026-08-25"}'),
    (402, '{"detail":"Check your subscription on https://admin.mistral.ai/subscription"}'),
    (404, '{"detail":"Function \'abc\': Not found for account \'SECRETACCT123\'"}'),
    (401, "unauthorized"), (403, "forbidden"),
])
def test_openai_compat_backend_raises_disabled_on_permanent_status(status, body):
    http = _FakeHTTP(_fake_response(status, body))
    b = ev._OpenAICompatBackend("nvidia:x", ev.NVIDIA_URL, "k", "m", http, cap=1)
    with pytest.raises(ev.BackendDisabled) as ei:
        _assess(b)
    assert ei.value.status == status


def test_account_identifier_is_redacted_from_provider_error_logs():
    http = _FakeHTTP(_fake_response(404, "Function 'f': Not found for account 'SECRETACCT123'"))
    b = ev._OpenAICompatBackend("nvidia:x", ev.NVIDIA_URL, "k", "m", http, cap=1)
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(ev.BackendDisabled) as ei:
            _assess(b)
    assert "SECRETACCT123" not in str(logs) and "SECRETACCT123" not in ei.value.reason


def test_server_errors_stay_transient_not_disabled():
    for status in (500, 502, 503):
        http = _FakeHTTP(_fake_response(status, "worker limit reached"))
        b = ev._OpenAICompatBackend("nvidia:x", ev.NVIDIA_URL, "k", "m", http, cap=1)
        assert _assess(b) is None            # a hard failure the breaker counts, NOT a disable


# ---------------------------------------------------------------------------
# 3. 429: back off with jitter, honour retry-after, daily cap disables
# ---------------------------------------------------------------------------

def test_429_backoff_is_exponential_jittered_and_capped():
    h = ev._LaneHealth("x", strike_limit=99, cooldown_s=10, max_backoff_s=60, rand=lambda: 0.0)
    waits = [h.record_quota()[0] for _ in range(5)]
    assert waits == [10, 20, 40, 60, 60]                  # doubles, capped at max_backoff

    h2 = ev._LaneHealth("x", strike_limit=99, cooldown_s=10, max_backoff_s=60, rand=lambda: 1.0)
    assert h2.record_quota()[0] == pytest.approx(12.5)    # +25% jitter: never lock-step

    seen = set()
    import random
    h3 = ev._LaneHealth("x", strike_limit=99, cooldown_s=10, rand=random.random)
    for _ in range(20):
        h3.strikes = 0
        seen.add(round(h3.record_quota()[0], 3))
    assert len(seen) > 5, "jitter must spread retries"


def test_429_honours_the_providers_retry_after():
    h = ev._LaneHealth("x", strike_limit=99, cooldown_s=70, rand=lambda: 0.0)
    wait, tripped = h.record_quota(retry_after=14.6)
    assert not tripped and wait == pytest.approx(15.6)    # not a blind 70s


def test_consecutive_429s_trip_the_breaker_and_a_success_resets_them():
    h = ev._LaneHealth("x", strike_limit=3, cooldown_s=0, reopen_s=600, clock=_Clock())
    h.record_quota(); h.record_quota()
    h.record_success()
    assert h.strikes == 0
    h.record_quota(); h.record_quota()
    assert h.state == "closed"
    _, tripped = h.record_quota()
    assert tripped and h.state == "open"


def test_daily_429_disables_instead_of_retrying_ten_times():
    h = ev._LaneHealth("cloudflare", strike_limit=10, reopen_s=600, clock=_Clock())
    wait, tripped = h.record_quota(daily=True)
    assert tripped and h.state == "disabled" and wait == 0.0
    assert h.gate() == ("off", 0.0)


def test_429_details_are_parsed_from_real_provider_bodies():
    gem_min = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
               "current quota... limit: 15, model: gemini-3.5-flash-lite\\nPlease retry in 14.59s.', "
               "'details': [{'violations': [{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}]}}")
    gem_day = gem_min.replace("PerMinute", "PerDay").replace("14.59", "51.68")
    cf = ('{"errors":[{"message":"AiError: you have used up your daily free allocation of '
          '10,000 neurons, please upgrade","code":4006}]}')
    groq = "Rate limit reached for model in organization on tokens per minute (TPM): Limit 8000"
    assert ev._is_daily_quota(gem_day) and not ev._is_daily_quota(gem_min)
    assert ev._is_daily_quota(cf) and not ev._is_daily_quota(groq)
    assert ev._retry_after_seconds(gem_min) == pytest.approx(14.59)
    assert ev._retry_after_seconds("", "5") == 5.0
    assert ev._retry_after_seconds("nothing here") is None


def test_openai_compat_429_carries_retry_after_and_daily_flag():
    http = _FakeHTTP(_fake_response(429, '{"errors":[{"message":"used up your daily free '
                                         'allocation of 10,000 neurons"}]}',
                                    headers={"retry-after": "7"}))
    b = ev._OpenAICompatBackend("cloudflare", "https://x.test", "k", "m", http, cap=1)
    with pytest.raises(ev.QuotaExhausted) as ei:
        _assess(b)
    assert ei.value.daily is True and ei.value.retry_after == 7.0


def test_429_in_a_live_pool_waits_at_least_the_retry_after(pool):
    q = _Lane("nvidia:q", "quota_then_ok", quota_first=2, retry_after=0.2)
    pool([q])
    listings = [_mk(i) for i in range(3)]
    _run(listings)
    assert q.calls == 5                                  # 2 x 429 + 3 listings
    assert q.stamps[1] - q.stamps[0] >= 0.2
    assert q.stamps[2] - q.stamps[1] >= 0.2
    assert all(_scored(li) for li in listings), "a 429'd listing must be re-queued"


def test_daily_quota_lane_is_disabled_in_a_live_pool(pool):
    cf = _Lane("cloudflare", "quota", daily=True)
    steady = _Lane("gemini#1", "ok")
    pool([cf, steady])
    listings = [_mk(i) for i in range(25)]
    _run(listings)
    assert cf.calls == 1, "a spent daily allocation must not be retried"
    assert ev._LAST_RUN["backends"]["cloudflare"]["state"] == "disabled"
    assert all(_scored(li) for li in listings)


# ---------------------------------------------------------------------------
# 4. Timeouts: shorter, and fewer retries
# ---------------------------------------------------------------------------

def test_provider_call_timeout_is_60s_by_default_and_env_tunable(monkeypatch):
    monkeypatch.delenv("VISION_CALL_TIMEOUT", raising=False)
    http = _FakeHTTP(_fake_response(500, "x"))
    b = ev._OpenAICompatBackend("nvidia:x", ev.NVIDIA_URL, "k", "m", http, cap=1)
    _assess(b)
    assert http.timeouts[-1] == 60.0
    monkeypatch.setenv("VISION_CALL_TIMEOUT", "25")
    _assess(b)
    assert http.timeouts[-1] == 25.0


def test_listing_attempts_are_capped_even_with_many_lanes(pool, monkeypatch):
    """With 40+ lanes the old len(backends)+2 budget let one unscorable listing walk
    every slow lane. VISION_MAX_ATTEMPTS caps it."""
    monkeypatch.setenv("VISION_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")
    lanes = [_Lane(f"dead{i}", "none") for i in range(12)]
    pool(lanes)
    listings = [_mk(i) for i in range(10)]
    _run(listings)
    per: dict[str, int] = {}
    for lane in lanes:
        for u in lane.order:
            per[u] = per.get(u, 0) + 1
    assert max(per.values()) <= 3, per


def test_worker_wait_for_item_timeout_counts_as_a_hard_failure(pool, monkeypatch):
    monkeypatch.setenv("VISION_ITEM_TIMEOUT", "0.05")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "2")
    monkeypatch.setenv("VISION_BACKEND_REOPEN_SECONDS", "0")
    slow = _Lane("nvidia:slow", "ok", work_s=1.0)
    steady = _Lane("gemini#1", "ok", delay=0.01)
    pool([slow, steady])
    listings = [_mk(i) for i in range(12)]
    _run(listings)
    st = ev._LAST_RUN["backends"]["nvidia:slow"]
    assert st["errors"].get("timeout", 0) >= 2 and st["state"] == "disabled"
    assert all(_scored(li) for li in listings)


# ---------------------------------------------------------------------------
# 5. Ordering: HOT, then WARM, photo rows only
# ---------------------------------------------------------------------------

def test_priority_is_photo_then_hot_then_warm_then_date():
    cold = _mk(1)
    warm = _mk(2, "WARM")
    hot = _mk(3, "HOT")
    hot_late = _mk(4, "HOT", sale=datetime(2026, 12, 1))
    hot_soon = _mk(5, "HOT", sale=datetime(2026, 10, 1))
    hot_nophoto = _mk(6, "HOT", photo=False)
    order = sorted([cold, warm, hot, hot_late, hot_soon, hot_nophoto], key=ev._vpri)
    assert [li.source_url[-1] for li in order] == ["5", "4", "3", "2", "1", "6"]
    #   dated HOT first (soonest sale first), then undated HOT, WARM, COLD, and the
    #   photo-less HOT row sorts LAST: a photo outranks a tier.


def test_pool_scores_hot_then_warm_first_and_skips_rows_without_a_photo(pool):
    lane = _Lane("gemini#1", "ok")
    pool([lane])
    rows = [_mk(1), _mk(2, "WARM"), _mk(3, "HOT"), _mk(4, "HOT", photo=False), _mk(5)]
    _run(rows)
    assert lane.order == ["https://example.test/l/3", "https://example.test/l/2",
                          "https://example.test/l/1", "https://example.test/l/5"]
    assert "https://example.test/l/4" not in lane.order, "a basemap-only row must never be sent"
    assert not _scored(rows[3])


def test_no_photo_rows_can_be_opted_back_in(pool, monkeypatch):
    monkeypatch.setenv("VISION_INCLUDE_NO_PHOTO", "1")
    lane = _Lane("gemini#1", "ok")
    pool([lane])
    _run([_mk(1), _mk(2, photo=False)])
    assert len(lane.order) == 2


def test_cap_keeps_the_hot_rows_when_the_budget_is_smaller_than_the_queue(pool):
    lane = _Lane("gemini#1", "ok")
    pool([lane])
    rows = [_mk(i) for i in range(20)] + [_mk(100 + i, "HOT") for i in range(3)]
    ev._LAST_RUN = {}
    asyncio.run(asyncio.wait_for(ev.enrich_with_vision(rows, max_listings=3), timeout=20))
    assert sorted(lane.order) == [f"https://example.test/l/{100 + i}" for i in range(3)]


# ---------------------------------------------------------------------------
# 6. Yield stop + wall clock
# ---------------------------------------------------------------------------

def test_yield_monitor_stops_when_live_workers_stay_at_or_below_two():
    clk = _Clock()
    m = ev._YieldMonitor(initial_live=21, min_live=2, live_window_s=900, clock=clk)
    assert m.update(12, 100, 500) is None
    assert m.update(2, 100, 500) is None                       # below the bar, timer starts
    clk.advance(899)
    assert m.update(1, 100, 500) is None
    clk.advance(2)
    why = m.update(1, 100, 500)
    assert why and "live_workers<=2" in why and "started with 21" in why


def test_yield_monitor_timer_resets_when_the_pool_recovers():
    clk = _Clock()
    m = ev._YieldMonitor(initial_live=21, live_window_s=900, min_rate_per_h=0, clock=clk)
    m.update(1, 0, 10)
    clk.advance(800)
    assert m.update(5, 0, 10) is None                          # recovered -> timer cleared
    clk.advance(800)
    assert m.update(1, 0, 10) is None                          # a NEW 15-minute window begins
    clk.advance(901)
    assert m.update(1, 0, 10) is not None


def test_yield_monitor_ignores_a_pool_that_never_had_more_than_two_backends():
    clk = _Clock()
    m = ev._YieldMonitor(initial_live=2, live_window_s=900, min_rate_per_h=0, clock=clk)
    for _ in range(5):
        assert m.update(2, 0, 10) is None
        clk.advance(600)


def test_yield_monitor_stops_below_100_scored_per_hour_after_the_grace_period():
    clk = _Clock()
    m = ev._YieldMonitor(initial_live=10, min_live=-1, min_rate_per_h=100,
                         rate_window_s=1800, grace_s=1800, clock=clk)
    scored = 0
    reason = None
    for minute in range(1, 61):
        clk.advance(60)
        scored += 1                                            # 60/hour: too slow
        reason = m.update(10, scored, 4000)
        if reason:
            break
    assert reason and "scored/hour" in reason
    assert minute >= 30, "must not fire before a full 30-minute window exists"


def test_yield_monitor_defaults_are_15_minute_window_after_20_minute_warmup():
    """The numbers in the audit (O6) and in run_daily_vision.sh's comment."""
    clk = _Clock()
    m = ev._YieldMonitor(initial_live=10, min_live=-1, clock=clk)
    assert (m.min_rate_per_h, m.rate_window_s, m.grace_s) == (100.0, 900.0, 1200.0)
    assert (ev._YieldMonitor(initial_live=10).min_live,
            ev._YieldMonitor(initial_live=10).live_window_s) == (2, 900.0)
    scored, fired_at = 0, None
    for minute in range(1, 61):
        clk.advance(60)
        scored += 1                                            # 60/hour
        if m.update(10, scored, 4000):
            fired_at = minute
            break
    assert fired_at is not None and 20 <= fired_at <= 22, fired_at


def test_yield_stop_env_zero_disables_both_rules(pool, monkeypatch):
    monkeypatch.setenv("VISION_YIELD_STOP", "0")
    monkeypatch.setenv("VISION_HEARTBEAT_SECONDS", "0.05")
    monkeypatch.setenv("VISION_YIELD_LIVE_S", "0.1")
    monkeypatch.setenv("VISION_YIELD_WARMUP_S", "0")
    monkeypatch.setenv("VISION_YIELD_WINDOW_S", "0.1")
    monkeypatch.setenv("VISION_MIN_SCORED_PER_HOUR", "1000000000")
    dead = [_Lane(f"nvidia:eol{i}", "disabled") for i in range(4)]
    steady = _Lane("gemini#1", "ok", delay=0.03)
    pool(dead + [steady])
    listings = [_mk(i) for i in range(40)]
    _run(listings)
    assert ev._LAST_RUN["stop_reason"] is None
    assert all(_scored(li) for li in listings), "the yield stop fired although it was disabled"


def test_yield_monitor_keeps_a_healthy_rate_and_never_fires_on_an_empty_queue():
    clk = _Clock()
    m = ev._YieldMonitor(initial_live=10, min_live=-1, min_rate_per_h=100, clock=clk)
    scored = 0
    for _ in range(90):
        clk.advance(60)
        scored += 3                                            # 180/hour
        assert m.update(10, scored, 4000) is None
    slow = ev._YieldMonitor(initial_live=10, min_live=-1, min_rate_per_h=100, clock=_Clock())
    slow_clk = slow._clock
    for _ in range(90):
        slow_clk.advance(60)
        assert slow.update(10, 0, 0) is None                   # queue empty: run is finishing


def test_pool_exits_early_when_it_collapses(pool, monkeypatch):
    """4 of 5 lanes die on the first call; the survivor is slow. The pass must end
    on the collapse rule instead of grinding on with one lane."""
    monkeypatch.setenv("VISION_HEARTBEAT_SECONDS", "0.05")
    monkeypatch.setenv("VISION_YIELD_LIVE_S", "0.2")
    monkeypatch.setenv("VISION_STOP_GRACE_SECONDS", "0.2")
    dead = [_Lane(f"nvidia:eol{i}", "disabled") for i in range(4)]
    steady = _Lane("gemini#1", "ok", delay=0.05)
    pool(dead + [steady])
    listings = [_mk(i) for i in range(400)]
    t0 = time.monotonic()
    _run(listings)
    assert time.monotonic() - t0 < 12, "400 listings at 0.05s would take 20s: it must stop early"
    assert ev._LAST_RUN["stop_reason"].startswith("yield:")
    assert "live_workers" in ev._LAST_RUN["stop_reason"]
    assert ev._LAST_RUN["leftover"] > 0
    assert 0 < sum(_scored(li) for li in listings) < 400


def test_pool_exits_on_low_yield(pool, monkeypatch):
    monkeypatch.setenv("VISION_HEARTBEAT_SECONDS", "0.05")
    monkeypatch.setenv("VISION_YIELD_LIVE_MIN", "-1")             # isolate the rate rule
    monkeypatch.setenv("VISION_YIELD_WARMUP_S", "0.4")
    monkeypatch.setenv("VISION_YIELD_WINDOW_S", "0.4")
    monkeypatch.setenv("VISION_MIN_SCORED_PER_HOUR", "100000")     # ~28/s; the lane does ~10/s
    monkeypatch.setenv("VISION_STOP_GRACE_SECONDS", "0.2")
    lane = _Lane("gemini#1", "ok", delay=0.1)
    other = _Lane("gemini#2", "ok", delay=0.1)
    pool([lane, other])
    _run([_mk(i) for i in range(300)])
    assert "scored/hour" in ev._LAST_RUN["stop_reason"]
    assert ev._LAST_RUN["leftover"] > 0


def test_wall_clock_default_is_90_minutes_and_env_overridable(monkeypatch):
    monkeypatch.delenv("VISION_MAX_SECONDS", raising=False)
    assert ev.vision_max_seconds() == 5400.0
    monkeypatch.setenv("VISION_MAX_SECONDS", "")
    assert ev.vision_max_seconds() == 5400.0
    monkeypatch.setenv("VISION_MAX_SECONDS", "1200")
    assert ev.vision_max_seconds() == 1200.0
    monkeypatch.setenv("VISION_MAX_SECONDS", "0")                 # explicit opt-out
    assert ev.vision_max_seconds() == 0.0
    monkeypatch.setenv("VISION_MAX_SECONDS", "not-a-number")      # never silently unlimited
    assert ev.vision_max_seconds() == 5400.0


def test_pool_stops_at_the_wall_clock(pool, monkeypatch):
    monkeypatch.setenv("VISION_MAX_SECONDS", "0.4")
    lane = _Lane("gemini#1", "ok", delay=0.05)
    pool([lane])
    listings = [_mk(i) for i in range(400)]
    t0 = time.monotonic()
    _run(listings)
    assert time.monotonic() - t0 < 6
    assert ev._LAST_RUN["stop_reason"] == "wall_clock"
    assert 0 < sum(_scored(li) for li in listings) < 400


# ---------------------------------------------------------------------------
# 7. Concurrency + pool construction
# ---------------------------------------------------------------------------

def test_a_lane_with_workers_runs_that_many_calls_at_once(pool):
    lane = _Lane("nvidia:ising", "ok", workers=3, work_s=0.05)
    pool([lane])
    listings = [_mk(i) for i in range(18)]
    t0 = time.monotonic()
    _run(listings)
    assert lane.max_concurrent == 3
    assert all(_scored(li) for li in listings)
    assert time.monotonic() - t0 < 18 * 0.05 * 0.7, "workers did not parallelise the lane"


def test_workers_share_one_health_record(pool, monkeypatch):
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "4")
    monkeypatch.setenv("VISION_BACKEND_REOPEN_SECONDS", "0")
    dead = _Lane("nvidia:dead", "none", workers=3)
    steady = _Lane("gemini#1", "ok", delay=0.01)
    pool([dead, steady])
    _run([_mk(i) for i in range(40)])
    assert 4 <= dead.calls <= 4 + 2, "3 workers must trip ONE breaker, not 3 x 4 failures"


def _clear_gemini_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 61):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    for k in ("GITHUB_MODELS_TOKEN", "GITHUB_TOKEN", "GROQ_API_KEY", "OPENROUTER_API_KEY",
              "MISTRAL_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
              "NVIDIA_API_KEY", "ANTHROPIC_API_KEY", "VISION_ENABLE_GITHUB",
              "VISION_ENABLE_MISTRAL", "VISION_INCLUDE_ANTHROPIC"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VISION_USE_OLLAMA", "0")


def _build():
    async def go():
        async with httpx.AsyncClient() as http:
            return await ev._build_backends(http)
    return asyncio.run(go())


def test_gemini_pool_is_one_lane_per_key_and_model_with_rotated_starts(monkeypatch):
    _clear_gemini_env(monkeypatch)
    for i in (1, 2, 3):
        monkeypatch.setenv(f"GEMINI_API_KEY_{i}", f"fake-key-{i}")
    monkeypatch.setattr(ev, "GEMINI_POOL_MODELS", ["gemini-a", "gemini-b", "gemini-c"])
    lanes = _build()
    assert len(lanes) == 9 and len({b.name for b in lanes}) == 9
    firsts = [b.model for b in lanes if b.name.startswith(("gemini#1:", "gemini#2:", "gemini#3:"))]
    by_key = {}
    for b in lanes:
        by_key.setdefault(b.name.split(":")[0], []).append(b.model)
    # each key opens on a DIFFERENT model, so nine keys do not all hit one model at once
    assert [v[0] for v in by_key.values()] == ["gemini-a", "gemini-b", "gemini-c"]
    assert all(sorted(v) == ["gemini-a", "gemini-b", "gemini-c"] for v in by_key.values())
    assert firsts and all(b.workers == 1 for b in lanes)
    # ONE concurrency gate per key, shared by that key's lanes only
    k1 = [b for b in lanes if b.name.startswith("gemini#1:")]
    k2 = [b for b in lanes if b.name.startswith("gemini#2:")]
    assert len({id(b.gate) for b in k1}) == 1 and id(k1[0].gate) != id(k2[0].gate)
    assert k1[0].gate._value == 2                          # VISION_GEMINI_KEY_CONCURRENCY default


def test_gemini_lane_pacing_follows_the_models_free_tier_rpm(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY_1", "fake-key-1")
    monkeypatch.setattr(ev, "GEMINI_POOL_MODELS", ["gemini-3.5-flash-lite", "gemini-3-flash-preview"])
    monkeypatch.setattr(ev, "INTER_CALL_DELAY", 4.0)
    by_model = {b.model: b.delay for b in _build()}
    assert by_model["gemini-3.5-flash-lite"] == pytest.approx(4.5)     # 15 RPM
    assert by_model["gemini-3-flash-preview"] == pytest.approx(12.5)   # 5 RPM


def test_single_model_pool_keeps_the_legacy_lane_names(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY_1", "fake-key-1")
    monkeypatch.setattr(ev, "GEMINI_POOL_MODELS", ["gemini-2.5-flash"])
    assert [b.name for b in _build()] == ["gemini#1"]


def test_dead_providers_are_not_registered_by_default(monkeypatch):
    """GitHub Models was retired 2026-07-30 (410/503 for every model) and Mistral
    answers 402 on every call. Neither may be built unless explicitly re-enabled."""
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GITHUB_MODELS_TOKEN", "x")
    monkeypatch.setenv("MISTRAL_API_KEY", "x")
    assert _build() == []
    monkeypatch.setenv("VISION_ENABLE_GITHUB", "1")
    monkeypatch.setenv("VISION_ENABLE_MISTRAL", "1")
    names = [b.name for b in _build()]
    assert any(n.startswith("github:") for n in names) and any(n.startswith("mistral:") for n in names)


def test_nvidia_lanes_are_the_verified_models_with_worker_counts(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("NVIDIA_API_KEY", "x")
    lanes = {b.model: b for b in _build()}
    assert set(lanes) == set(ev.NVIDIA_VISION_MODELS)
    for eol in ("nvidia/nemotron-nano-12b-v2-vl", "thinkingmachines/inkling",
                "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"):
        assert eol not in lanes, f"{eol} is HTTP 410 end-of-life"
    assert lanes["nvidia/ising-calibration-1.5-31b"].workers == ev.NVIDIA_DEFAULT_WORKERS
    assert lanes["nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"].workers == 1
    assert all(b.cap == 1 for b in lanes.values())


# ---------------------------------------------------------------------------
# 8. Gemini error mapping
# ---------------------------------------------------------------------------

class _GenaiErr(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class _StubClient:
    def __init__(self, exc):
        class _Models:
            async def generate_content(self, **kw):
                raise exc

        class _Aio:
            models = _Models()

        self.aio = _Aio()


def _gemini_assess(exc):
    b = ev._GeminiBackend("fake-key", 1, model="gemini-3.5-flash-lite")
    b.client = _StubClient(exc)
    return asyncio.run(b.assess(_mk(0), [(b"\xff\xd8x", "image/jpeg")], ["u"]))


def test_gemini_per_minute_429_is_a_short_backoff_not_a_disable():
    msg = ("429 RESOURCE_EXHAUSTED. {'error': {'message': 'Quota exceeded ... limit: 15, model: "
           "gemini-3.5-flash-lite\\nPlease retry in 14.59s.', 'details': [{'violations': "
           "[{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}]}}")
    with pytest.raises(ev.QuotaExhausted) as ei:
        _gemini_assess(_GenaiErr(429, msg))
    assert ei.value.daily is False and ei.value.retry_after == pytest.approx(14.59)


def test_gemini_per_day_429_is_flagged_daily():
    msg = ("429 RESOURCE_EXHAUSTED. {'error': {'message': 'Quota exceeded, limit: 20, model: "
           "gemini-2.5-flash\\nPlease retry in 51.6s.', 'details': [{'violations': "
           "[{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}}")
    with pytest.raises(ev.QuotaExhausted) as ei:
        _gemini_assess(_GenaiErr(429, msg))
    assert ei.value.daily is True


def test_gemini_404_and_bad_key_disable_the_lane_and_503_stays_transient():
    with pytest.raises(ev.BackendDisabled):
        _gemini_assess(_GenaiErr(404, "404 NOT_FOUND. models/gemini-9 is not found"))
    with pytest.raises(ev.BackendDisabled):
        _gemini_assess(_GenaiErr(400, "400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key."))
    with pytest.raises(ev.BackendDisabled):
        _gemini_assess(_GenaiErr(403, "403 PERMISSION_DENIED"))
    assert _gemini_assess(_GenaiErr(503, "503 UNAVAILABLE. This model is currently experiencing high demand.")) is None
    assert _gemini_assess(_GenaiErr(400, "400 INVALID_ARGUMENT. bad image")) is None


def test_opening_burst_is_staggered_across_keys_and_workers(monkeypatch):
    _clear_gemini_env(monkeypatch)
    for i in (1, 2, 3):
        monkeypatch.setenv(f"GEMINI_API_KEY_{i}", f"fake-key-{i}")
    monkeypatch.setenv("NVIDIA_API_KEY", "x")
    monkeypatch.setattr(ev, "GEMINI_POOL_MODELS", ["gemini-a", "gemini-b"])
    lanes = _build()
    starts = [b.start_delay for b in lanes if b.name.startswith("gemini#")]
    assert len(set(starts)) == len(starts), "every Gemini lane must open at a different moment"
    assert min(starts) == 0.0 and max(starts) > 0
    nim = [b for b in lanes if b.name.startswith("nvidia:")]
    assert all(b.worker_stagger > 0 for b in nim)
    monkeypatch.setenv("VISION_START_STAGGER_S", "0")
    assert all(b.start_delay == 0.0 for b in _build() if b.name.startswith("gemini#"))


# ---------------------------------------------------------------------------
# 9. A network outage must not silently drain the queue (9/14 and 9/20 passes)
# ---------------------------------------------------------------------------

def test_long_streak_of_unfetchable_photos_stops_the_pass_instead_of_draining_the_queue(pool, monkeypatch):
    async def _no_photos(li, http):
        return [], []

    monkeypatch.setattr(ev, "_fetch_image_blocks", _no_photos)
    monkeypatch.setenv("VISION_FETCH_PAUSE_AFTER", "3")
    monkeypatch.setenv("VISION_FETCH_PAUSE_S", "0.01")
    monkeypatch.setenv("VISION_FETCH_STOP_AFTER", "12")
    monkeypatch.setenv("VISION_STOP_GRACE_SECONDS", "0.2")
    lane = _Lane("gemini#1", "ok")
    pool([lane])
    listings = [_mk(i) for i in range(500)]
    _run(listings)
    assert ev._LAST_RUN["stop_reason"].startswith("image_fetch_failing")
    assert ev._LAST_RUN["leftover"] > 400, "the queue was drained instead of kept for the next run"
    assert lane.calls == 0
    assert ev._LAST_RUN["no_image"] >= 12


def test_isolated_dead_image_urls_are_just_skipped(pool, monkeypatch):
    calls = {"n": 0}

    async def _flaky_fetch(li, http):
        calls["n"] += 1
        if calls["n"] % 5 == 0:                        # every 5th row has a dead URL
            return [], []
        return [(b"\xff\xd8x", "image/jpeg")], ["https://img.test/x.jpg"]

    monkeypatch.setattr(ev, "_fetch_image_blocks", _flaky_fetch)
    lane = _Lane("gemini#1", "ok")
    pool([lane])
    listings = [_mk(i) for i in range(50)]
    _run(listings)
    assert ev._LAST_RUN["stop_reason"] is None
    assert ev._LAST_RUN["no_image"] == 10
    assert sum(_scored(li) for li in listings) == 40
