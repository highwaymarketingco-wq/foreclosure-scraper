"""Vision pool queue resilience — the 2026-07-27 cannibalization regression.

Before the fix, only QuotaExhausted re-queued a listing. Any HARD error
(HTTP 410 end-of-life model, 404 unknown model, unparseable reply, item
timeout) fell through to _apply2(li, None) and the listing was dropped for
the whole run — so every dead backend permanently ate one queue slot per
failure. That pass drained 1,500 queued listings in 5.5 minutes and scored
only 278 because 7 retired NIM models plus a 404 Groq model consumed 1,222
slots between them.

These tests use FAKE backends (no network) to pin the two guards:
  * a hard-failing backend retires after VISION_BACKEND_HARD_FAILS
    consecutive failures, and
  * a hard-failed listing is re-queued at most VISION_MAX_REQUEUE times,
so a healthy backend still gets a shot and a fully-dead pool terminates.
"""
from __future__ import annotations

import asyncio

import pytest

import foreclosure_scraper.enrichment_vision as ev
from foreclosure_scraper.models import Listing


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------

def _mk_listing(n: int) -> Listing:
    return Listing(
        source="test",
        source_url=f"https://example.test/listing/{n}",
        raw={"images": {"real": [f"https://img.test/{n}.jpg"]}},
    )


class _FakeBackend:
    """Minimal backend: same duck-type the pool expects (name/model/delay/assess)."""

    def __init__(self, name: str, behavior: str):
        self.name = name
        self.model = f"fake/{name}"
        self.delay = 0.0
        self.cap = 1
        self.behavior = behavior      # "dead" | "healthy" | "quota"
        self.calls = 0

    async def assess(self, li, payloads, urls):
        self.calls += 1
        await asyncio.sleep(0)        # yield, like a real network call
        if self.behavior == "quota":
            raise ev.QuotaExhausted(self.name)
        if self.behavior == "dead":
            # Mirrors _OpenAICompatBackend on HTTP 410/404: logs and returns None.
            return None
        return ev._finalize(
            {"condition_tier": "cosmetic", "confidence": "HIGH"},
            self.name, self.model, len(payloads), urls,
        )


@pytest.fixture
def pool(monkeypatch):
    """Patch out the network: fixed image payloads, no real backends."""
    async def _fake_fetch(li, http):
        return [(b"\xff\xd8fake-jpeg", "image/jpeg")], ["https://img.test/x.jpg"]

    monkeypatch.setattr(ev, "_fetch_image_blocks", _fake_fetch)
    # No Ollama probe, no wall-clock cap, no watchdog interference.
    monkeypatch.setenv("VISION_USE_OLLAMA", "0")
    monkeypatch.setenv("VISION_MAX_SECONDS", "0")
    monkeypatch.setenv("VISION_BACKEND_COOLDOWN", "0")

    def _install(backends):
        async def _fake_build(http):
            return list(backends)
        monkeypatch.setattr(ev, "_build_backends", _fake_build)

    return _install


def _run(listings):
    asyncio.run(asyncio.wait_for(ev.enrich_with_vision(listings), timeout=30))


def _scored(li: Listing) -> bool:
    return bool(isinstance(li.raw, dict) and li.raw.get("vision"))


# ---------------------------------------------------------------------------
# 1. A hard-failing backend retires after N consecutive failures
# ---------------------------------------------------------------------------

def test_hard_failing_backend_retires_after_n_consecutive(pool, monkeypatch):
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "3")
    monkeypatch.setenv("VISION_MAX_REQUEUE", "0")   # isolate the retire rule
    dead = _FakeBackend("nvidia:dead-410", "dead")
    pool([dead])

    listings = [_mk_listing(i) for i in range(25)]
    _run(listings)

    # It must stop after exactly 3 attempts, not eat all 25 queue slots.
    assert dead.calls == 3, f"expected retire at 3 hard fails, got {dead.calls}"
    assert not any(_scored(li) for li in listings)


def test_success_resets_the_hard_fail_counter(pool, monkeypatch):
    """A backend that fails intermittently must NOT retire — only N in a row does."""
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "3")
    monkeypatch.setenv("VISION_MAX_REQUEUE", "0")

    class _Flaky(_FakeBackend):
        async def assess(self, li, payloads, urls):
            self.calls += 1
            await asyncio.sleep(0)
            if self.calls % 2 == 0:          # fail every other call
                return None
            return ev._finalize({"condition_tier": "cosmetic", "confidence": "HIGH"},
                                self.name, self.model, len(payloads), urls)

    flaky = _Flaky("flaky", "custom")
    pool([flaky])
    listings = [_mk_listing(i) for i in range(20)]
    _run(listings)

    assert flaky.calls == 20, "flaky backend retired early despite successes"
    assert sum(_scored(li) for li in listings) == 10


# ---------------------------------------------------------------------------
# 2. Bounded re-queue: at most VISION_MAX_REQUEUE retries, then dropped
# ---------------------------------------------------------------------------

def test_listing_requeued_at_most_max_requeue_then_dropped(pool, monkeypatch):
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")   # isolate the requeue rule
    dead = _FakeBackend("nvidia:dead-410", "dead")
    pool([dead])

    listings = [_mk_listing(0)]
    _run(listings)

    # 1 initial attempt + 2 re-queued attempts = 3, then given up.
    assert dead.calls == 3, f"expected 1+2 attempts, got {dead.calls}"
    assert not _scored(listings[0])


def test_requeue_bound_is_env_tunable(pool, monkeypatch):
    monkeypatch.setenv("VISION_MAX_REQUEUE", "4")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "99")
    dead = _FakeBackend("nvidia:dead-410", "dead")
    pool([dead])

    listings = [_mk_listing(0)]
    _run(listings)
    assert dead.calls == 5, f"expected 1+4 attempts, got {dead.calls}"


# ---------------------------------------------------------------------------
# 3. THE REGRESSION THAT MATTERS: a dead backend must not steal work from a
#    healthy one. Every listing should still get scored.
# ---------------------------------------------------------------------------

def test_dead_backend_does_not_cannibalize_healthy_backend(pool, monkeypatch):
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "5")

    dead = _FakeBackend("nvidia:dead-410", "dead")
    healthy = _FakeBackend("gemini#1", "healthy")
    pool([dead, healthy])

    listings = [_mk_listing(i) for i in range(30)]
    _run(listings)

    assert all(_scored(li) for li in listings), (
        f"only {sum(_scored(li) for li in listings)}/30 scored — dead backend ate the queue"
    )
    assert dead.calls <= 5, "dead backend should have retired after 5 hard fails"
    for li in listings:
        assert li.raw["vision"]["_provider"] == "gemini#1"


def test_many_dead_backends_one_healthy_still_scores_everything(pool, monkeypatch):
    """The real pool shape: 8 dead lanes + 1 good one."""
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "5")

    dead = [_FakeBackend(f"nvidia:dead{i}", "dead") for i in range(8)]
    healthy = _FakeBackend("gemini#1", "healthy")
    pool(dead + [healthy])

    listings = [_mk_listing(i) for i in range(60)]
    _run(listings)

    n = sum(_scored(li) for li in listings)
    assert n == 60, f"only {n}/60 scored with 8 dead lanes in the pool"
    assert sum(b.calls for b in dead) <= 8 * 5


def test_quota_exhausted_still_requeues_and_retires(pool, monkeypatch):
    """Existing 429 behavior must survive the fix."""
    monkeypatch.setenv("VISION_BACKEND_STRIKES", "2")
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "5")

    spent = _FakeBackend("groq", "quota")
    healthy = _FakeBackend("gemini#1", "healthy")
    pool([spent, healthy])

    listings = [_mk_listing(i) for i in range(10)]
    _run(listings)

    assert spent.calls == 2, f"quota backend should retire on 2 strikes, got {spent.calls}"
    assert all(_scored(li) for li in listings), "429'd listings were not re-queued"


# ---------------------------------------------------------------------------
# 4. An all-dead pool must TERMINATE, not loop forever / spin the CPU
# ---------------------------------------------------------------------------

def test_all_dead_pool_terminates(pool, monkeypatch):
    monkeypatch.setenv("VISION_MAX_REQUEUE", "2")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "5")

    dead = [_FakeBackend(f"nvidia:dead{i}", "dead") for i in range(6)]
    pool(dead)

    listings = [_mk_listing(i) for i in range(200)]
    # asyncio.wait_for inside _run is the guard: a livelock raises TimeoutError.
    _run(listings)

    total = sum(b.calls for b in dead)
    # Bounded twice over: <= 6 backends * 5 hard fails.
    assert total <= 30, f"all-dead pool made {total} calls — bound not enforced"
    assert not any(_scored(li) for li in listings)


def test_groq_backend_sends_reasoning_effort_none(monkeypatch):
    """Groq's qwen3.6 vision model only emits JSON with reasoning_effort=none;
    without it the pool gets a <think> block and zero parseable results."""
    sent = {}

    class _FakeHTTP:
        async def post(self, url, json=None, timeout=None, headers=None):
            sent.update(json or {})
            raise RuntimeError("stop-after-capture")

    b = ev._OpenAICompatBackend("groq", ev.GROQ_URL, "k", ev.GROQ_MODEL,
                                _FakeHTTP(), cap=1, delay=0.0,
                                extra_body=ev.GROQ_EXTRA_BODY)
    li = _mk_listing(0)
    asyncio.run(b.assess(li, [(b"\xff\xd8x", "image/jpeg")], ["u"]))
    assert sent.get("reasoning_effort") == "none"
    assert sent.get("model") == "qwen/qwen3.6-27b"


def test_extra_body_defaults_to_empty_for_other_providers():
    b = ev._OpenAICompatBackend("nvidia:x", ev.NVIDIA_URL, "k",
                                ev.NVIDIA_VISION_MODELS[0], None, cap=1)
    assert b.extra_body == {}


def test_all_dead_pool_with_requeue_disabled_terminates(pool, monkeypatch):
    monkeypatch.setenv("VISION_MAX_REQUEUE", "0")
    monkeypatch.setenv("VISION_BACKEND_HARD_FAILS", "5")
    dead = [_FakeBackend(f"nvidia:dead{i}", "dead") for i in range(3)]
    pool(dead)
    _run([_mk_listing(i) for i in range(50)])
    assert sum(b.calls for b in dead) == 15


# --- regression: a model that cannot SEE the image must never produce a grade ---
# Measured 2026-07-27: gpt-oss-120b/20b, glm-5.2 and deepseek-v4-pro return HTTP 200
# with parseable JSON while blind to the attached photo. A confident tier on an unseen
# photo silently corrupts condition -> rehab -> ARV -> max bid.

def test_blind_reply_is_discarded():
    from foreclosure_scraper.enrichment_vision import _finalize
    for blob in ["There's no image attached, but generally...",
                 "I cannot see the image provided.",
                 "There are no actual property photos, only a generic basemap.",
                 "I do not have access to the photo."]:
        out = _finalize({"condition_tier": "cosmetic", "confidence": "HIGH", "summary": blob},
                        "test", "blind-model", 1, ["u"])
        assert out is None, f"blind reply must be discarded, got: {out}"


def test_sighted_reply_survives():
    from foreclosure_scraper.enrichment_vision import _finalize
    out = _finalize({"condition_tier": "major", "confidence": "HIGH",
                     "summary": "Brick ranch with a sagging porch roof and overgrown yard."},
                    "test", "good-model", 1, ["u"])
    assert out and out["condition_tier"] == "major"
    assert out["_provider"] == "test"
