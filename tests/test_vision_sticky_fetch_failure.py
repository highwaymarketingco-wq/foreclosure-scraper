"""Sticky image-fetch-failure marker — the 2026-09-23 backfill_vision_haiku.py
re-burn regression.

MEASURED, live, 2026-09-23: three consecutive runs of
scripts/backfill_vision_haiku.py all hit the IDENTICAL circuit-breaker
stop_reason,

    image_fetch_failing: 100 rows in a row had no downloadable photo (network down?)

while each run's `scored` count roughly HALVED versus the last (299, then
150, then 77) even though the total candidate pool only shrank by the small
number actually scored each time (5311 -> 5012 -> 4862). A real network
outage would not reproduce identically 3 times in a row with different
candidate sets in between.

TRACED root cause (see enrich_with_vision's api_worker, the
"if not payloads:" branch): a listing whose image URL(s) fail to download is
popped off the shared queue and `continue`d past without ever being written
to raw["vision"] or anywhere else _needs_vision() would notice. So the very
next invocation of the script — a fresh process, a fresh load_board() — finds
that listing exactly as eligible as it was before, and _vpri (photo-first,
HOT/WARM-first) sorts it right back to the FRONT of the queue. The same
~100-650 dead-image leads got re-attempted from scratch on every run,
crowding out the fresh leads the run existed to make progress on.

THE FIX: enrichment_vision._mark_fetch_failed() stamps a sticky marker
(persisted across runs via web_artifact.RAW_KEEP's new "vision_fetch_failed"
entry) recording the exact urls that failed, an attempt count, and a
timestamp. _needs_vision() consults it via _fetch_recently_failed() and skips
a listing only once the SAME url set has failed VISION_FETCH_FAIL_RETRIES
times (default 2) and the marker has not yet expired
(VISION_FETCH_FAIL_TTL_DAYS, default 14, 0 = never). A url change (a re-scrape
backfilled a fresh photo) or TTL expiry makes the lead eligible again
immediately. The existing pass-level circuit breaker (fetch_stop_after) is
completely untouched — this sits BEHIND it, deciding what's eligible to be
queued at all on a FUTURE run, not what happens within one run's fetch loop.
"""
from __future__ import annotations

import asyncio
import time

import pytest

import foreclosure_scraper.enrichment_vision as ev
from foreclosure_scraper.models import Listing


# ---------------------------------------------------------------------------
# fixtures / fakes (same shapes as tests/test_vision_pool_repair.py)
# ---------------------------------------------------------------------------

def _mk(n: int, urls: list[str] | None = None) -> Listing:
    urls = urls if urls is not None else [f"https://img.test/{n}.jpg"]
    return Listing(source="test", source_url=f"https://example.test/l/{n}",
                   raw={"images": {"real": urls}})


class _Lane:
    """Minimal healthy backend — same duck type _Lane in test_vision_pool_repair.py."""

    def __init__(self, name="gemini#1"):
        self.name = name
        self.model = f"fake/{name}"
        self.delay = 0.0
        self.cap = 1
        self.workers = 1
        self.calls = 0

    async def assess(self, li, payloads, urls):
        self.calls += 1
        await asyncio.sleep(0)
        return ev._finalize({"condition_tier": "cosmetic", "confidence": "HIGH"},
                            self.name, self.model, len(payloads), urls)


@pytest.fixture
def pool(monkeypatch):
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


# ---------------------------------------------------------------------------
# (a) A listing whose image fetch fails gets marked so a subsequent
#     _needs_vision() call returns False.
# ---------------------------------------------------------------------------

def test_mark_fetch_failed_is_a_noop_below_the_retry_threshold(monkeypatch):
    monkeypatch.setenv("VISION_FETCH_FAIL_RETRIES", "2")
    li = _mk(0)
    urls = ev._select_image_urls(li)
    assert ev._needs_vision(li) is True

    ev._mark_fetch_failed(li, urls)
    assert li.raw["vision_fetch_failed"]["attempts"] == 1
    assert ev._needs_vision(li) is True, "one failure must not exhaust 2 retries"


def test_needs_vision_returns_false_once_retries_exhausted(monkeypatch):
    monkeypatch.setenv("VISION_FETCH_FAIL_RETRIES", "2")
    li = _mk(0)
    urls = ev._select_image_urls(li)

    ev._mark_fetch_failed(li, urls)
    ev._mark_fetch_failed(li, urls)
    assert li.raw["vision_fetch_failed"]["attempts"] == 2
    assert ev._needs_vision(li) is False, (
        "the SAME url set failing twice must deprioritize the lead — this is "
        "exactly what stops backfill_vision_haiku.py from re-burning the same "
        "dead-image leads every single day"
    )


def test_full_pool_run_marks_the_dead_listing_and_excludes_it_next_pass(pool, monkeypatch):
    """End-to-end: run enrich_with_vision() once against a mix of live and dead
    image URLs, then simulate the NEXT DAY'S invocation by re-filtering the
    same (mutated-in-place) listings through _needs_vision directly, exactly
    as enrich_with_vision's own `targets = [li for li in listings if
    _needs_vision(li)]` line does on a fresh process."""
    monkeypatch.setenv("VISION_FETCH_FAIL_RETRIES", "1")   # one failure is enough this test

    calls = {"n": 0}

    async def _fetch(li, http):
        calls["n"] += 1
        if "dead" in li.source_url:
            return [], ev._select_image_urls(li)
        return [(b"\xff\xd8x", "image/jpeg")], ev._select_image_urls(li)

    monkeypatch.setattr(ev, "_fetch_image_blocks", _fetch)
    lane = _Lane()
    pool([lane])

    good = [_mk(i) for i in range(5)]
    dead = [_mk(100 + i, urls=[f"https://img.test/dead{i}.jpg"]) for i in range(3)]
    for li in dead:
        li.source_url = li.source_url.replace("/l/", "/l/dead")
    listings = good + dead
    _run(listings)

    assert all(_scored(li) for li in good)
    assert not any(_scored(li) for li in dead)
    for li in dead:
        assert li.raw.get("vision_fetch_failed", {}).get("attempts") == 1

    # "Next run": _needs_vision must now exclude the dead leads without ever
    # touching the network again (they're sticky-skipped) — and the good ones
    # are excluded too, but for the pre-existing reason (already scored).
    targets = [li for li in listings if ev._needs_vision(li)]
    assert targets == [], (
        "every lead should be settled by now: scored (good) or sticky-skipped "
        f"(dead) — but _needs_vision still wants {[li.source_url for li in targets]}"
    )


# ---------------------------------------------------------------------------
# (b) A listing that already has a working image and gets scored normally is
#     unaffected by the new marker plumbing.
# ---------------------------------------------------------------------------

def test_successfully_scored_listing_needs_vision_false_and_no_marker_created(pool, monkeypatch):
    lane = _Lane()
    pool([lane])

    async def _fetch(li, http):
        return [(b"\xff\xd8x", "image/jpeg")], ev._select_image_urls(li)
    monkeypatch.setattr(ev, "_fetch_image_blocks", _fetch)

    listings = [_mk(i) for i in range(10)]
    _run(listings)

    assert all(_scored(li) for li in listings)
    assert all("vision_fetch_failed" not in (li.raw or {}) for li in listings)
    assert all(ev._needs_vision(li) is False for li in listings)


def test_apply_clears_a_stale_marker_once_the_lead_is_actually_scored(pool, monkeypatch):
    """A lead that failed to fetch on an OLD url set, then got a fresh photo
    via re-scrape and was successfully graded, should not carry the old
    fetch-failure bookkeeping forward. enrich_with_vision's _apply() is a
    closure (not a module-level function), so this exercises it through the
    one real entry point that shares its exact contract: a full pool run."""
    li = _mk(0)
    stale_urls = ["https://img.test/old-dead.jpg"]  # NOT li's current urls
    ev._mark_fetch_failed(li, stale_urls)
    assert "vision_fetch_failed" in li.raw

    async def _fetch(li2, http):
        return [(b"\xff\xd8x", "image/jpeg")], ev._select_image_urls(li2)
    monkeypatch.setattr(ev, "_fetch_image_blocks", _fetch)
    lane = _Lane()
    pool([lane])
    _run([li])

    assert _scored(li)
    assert "vision_fetch_failed" not in li.raw


# ---------------------------------------------------------------------------
# (c) The existing circuit-breaker/streak-stop behavior for a genuine long
#     dead streak is UNCHANGED by the new sticky-marker plumbing.
# ---------------------------------------------------------------------------

def test_long_streak_still_stops_the_pass_and_still_marks_every_row(pool, monkeypatch):
    """Mirrors tests/test_vision_pool_repair.py's
    test_long_streak_of_unfetchable_photos_stops_the_pass_instead_of_draining_the_queue
    — the breaker itself (fetch_stop_after / fetch_pause_after) must behave
    identically with the sticky-marker code active, AND every row that WAS
    attempted before the breaker tripped must have been marked (proving the
    new code runs on that exact path)."""
    async def _no_photos(li, http):
        return [], ev._select_image_urls(li)

    monkeypatch.setattr(ev, "_fetch_image_blocks", _no_photos)
    monkeypatch.setenv("VISION_FETCH_PAUSE_AFTER", "3")
    monkeypatch.setenv("VISION_FETCH_PAUSE_S", "0.01")
    monkeypatch.setenv("VISION_FETCH_STOP_AFTER", "12")
    monkeypatch.setenv("VISION_STOP_GRACE_SECONDS", "0.2")
    lane = _Lane()
    pool([lane])
    listings = [_mk(i) for i in range(500)]
    _run(listings)

    assert ev._LAST_RUN["stop_reason"].startswith("image_fetch_failing")
    assert ev._LAST_RUN["leftover"] > 400, "the queue was drained instead of kept for the next run"
    assert lane.calls == 0
    assert ev._LAST_RUN["no_image"] >= 12

    attempted = [li for li in listings if isinstance(li.raw, dict) and "vision_fetch_failed" in li.raw]
    assert len(attempted) >= 12, "every row the breaker counted should have been sticky-marked too"
    for li in attempted:
        assert li.raw["vision_fetch_failed"]["attempts"] == 1


def test_isolated_dead_urls_still_just_skipped_not_stopped(pool, monkeypatch):
    """Mirrors test_isolated_dead_image_urls_are_just_skipped: an occasional
    dead URL sprinkled among healthy ones must not trip the pass-level
    breaker, and now ALSO leaves each dead one indivudally marked."""
    calls = {"n": 0}

    async def _flaky_fetch(li, http):
        calls["n"] += 1
        if calls["n"] % 5 == 0:
            return [], ev._select_image_urls(li)
        return [(b"\xff\xd8x", "image/jpeg")], ev._select_image_urls(li)

    monkeypatch.setattr(ev, "_fetch_image_blocks", _flaky_fetch)
    lane = _Lane()
    pool([lane])
    listings = [_mk(i) for i in range(50)]
    _run(listings)

    assert ev._LAST_RUN["stop_reason"] is None
    assert ev._LAST_RUN["no_image"] == 10
    marked = [li for li in listings
              if isinstance(li.raw, dict) and "vision_fetch_failed" in li.raw]
    assert len(marked) == 10


# ---------------------------------------------------------------------------
# (d) URL-change and TTL re-eligibility.
# ---------------------------------------------------------------------------

def test_needs_vision_eligible_again_once_the_photo_url_changes(monkeypatch):
    """A re-scrape that backfills a fresh photo URL must make the lead
    eligible again immediately — no waiting on attempts or TTL."""
    monkeypatch.setenv("VISION_FETCH_FAIL_RETRIES", "1")
    li = _mk(0)
    old_urls = ev._select_image_urls(li)
    ev._mark_fetch_failed(li, old_urls)
    assert ev._needs_vision(li) is False

    li.raw["images"]["real"] = ["https://img.test/brand-new-photo.jpg"]
    new_urls = ev._select_image_urls(li)
    assert new_urls != old_urls
    assert ev._needs_vision(li) is True


def test_needs_vision_eligible_again_after_ttl_expires(monkeypatch):
    monkeypatch.setenv("VISION_FETCH_FAIL_RETRIES", "1")
    monkeypatch.setenv("VISION_FETCH_FAIL_TTL_DAYS", "1")
    li = _mk(0)
    urls = ev._select_image_urls(li)
    ev._mark_fetch_failed(li, urls)
    assert ev._needs_vision(li) is False

    # Simulate the marker being 2 days old (older than the 1-day TTL).
    li.raw["vision_fetch_failed"]["at"] = time.time() - 2 * 86400
    assert ev._needs_vision(li) is True


def test_ttl_zero_means_the_marker_never_expires(monkeypatch):
    monkeypatch.setenv("VISION_FETCH_FAIL_RETRIES", "1")
    monkeypatch.setenv("VISION_FETCH_FAIL_TTL_DAYS", "0")
    li = _mk(0)
    urls = ev._select_image_urls(li)
    ev._mark_fetch_failed(li, urls)
    li.raw["vision_fetch_failed"]["at"] = time.time() - 999 * 86400
    assert ev._needs_vision(li) is False, "TTL=0 must mean 'never expires', not 'always expired'"


def test_repeated_failure_against_the_same_urls_accumulates_attempts():
    li = _mk(0)
    urls = ev._select_image_urls(li)
    ev._mark_fetch_failed(li, urls)
    ev._mark_fetch_failed(li, urls)
    ev._mark_fetch_failed(li, urls)
    assert li.raw["vision_fetch_failed"]["attempts"] == 3


def test_failure_against_a_different_url_set_resets_the_attempt_count():
    li = _mk(0)
    ev._mark_fetch_failed(li, ["https://img.test/a.jpg"])
    assert li.raw["vision_fetch_failed"]["attempts"] == 1
    ev._mark_fetch_failed(li, ["https://img.test/b.jpg"])
    assert li.raw["vision_fetch_failed"]["attempts"] == 1, (
        "a different url set is a fresh situation, not a continuation of the old streak"
    )


def test_raw_key_is_registered_in_raw_keep_so_it_survives_a_persist():
    """The marker is worthless if web_artifact._slim_raw() strips it on every
    write — that IS the original mechanism keeping this bug alive across
    process runs (board persisted -> reloaded -> raw wiped -> eligible again).
    See this repo's own RAW_KEEP comments: 'Any new raw key needs RAW_KEEP...
    or it does not exist.'"""
    from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw
    assert "vision_fetch_failed" in RAW_KEEP

    raw = {"vision_fetch_failed": {"urls": ["https://img.test/x.jpg"], "attempts": 2, "at": 123.0}}
    slimmed = _slim_raw(raw)
    assert slimmed.get("vision_fetch_failed") == raw["vision_fetch_failed"], (
        "vision_fetch_failed must round-trip through a board persist unchanged"
    )
