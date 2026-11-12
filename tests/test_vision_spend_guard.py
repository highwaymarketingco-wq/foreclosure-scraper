"""_SpendGuard — the $ stop on the paid Anthropic vision path.

Added 2026-08-07 when the operator funded a one-time $38 Anthropic vision
spend to clear the backlog faster than the free provider pool alone. The
guard must be provably safe against overspend even under worker-pool
concurrency, and must degrade to "free backends finish the rest" rather than
stopping the run when the budget is hit.
"""
from foreclosure_scraper.enrichment_vision import (
    _ANTHROPIC_PRICE_PER_MTOK, _SpendGuard,
)


def test_unset_limit_never_trips():
    """VISION_MAX_SPEND_USD unset (limit 0) means unlimited — existing default
    behavior for anyone who hasn't opted into a cap."""
    g = _SpendGuard()
    g.limit = 0
    for _ in range(1000):
        g.record("claude-haiku-4-5", 1_000_000, 1_000_000)
    assert g.over_budget() is False


def test_trips_once_spend_reaches_the_limit():
    g = _SpendGuard()
    g.limit = 1.00
    assert g.over_budget() is False
    # Haiku 4.5: $1/Mtok in, $5/Mtok out. 500k in + 100k out = $0.50 + $0.50 = $1.00.
    g.record("claude-haiku-4-5", 500_000, 100_000)
    assert g.spent == 1.00
    assert g.over_budget() is True


def test_does_not_trip_one_cent_under():
    g = _SpendGuard()
    g.limit = 1.00
    g.record("claude-haiku-4-5", 500_000, 99_000)  # $0.50 + $0.495 = $0.995
    assert g.over_budget() is False


def test_unknown_model_falls_back_to_haiku_pricing_not_zero():
    """A price-table miss must not let spend silently go unrecorded — that
    would mean the guard never trips and the real bill has no ceiling."""
    g = _SpendGuard()
    g.limit = 0.01
    g.record("some-future-model-not-in-the-table", 5_000, 1_000)
    assert g.spent > 0
    assert g.over_budget() is True


def test_full_backlog_at_haiku_pricing_stays_under_38_dollars():
    """Sizes the actual claim made to the operator: the measured 9,326-lead
    backlog at ~1,600 in / ~400 out tokens/lead fits inside the $38 funded,
    with the guard as the enforcement mechanism if the real average runs a
    little hot."""
    g = _SpendGuard()
    g.limit = 38.00
    per_lead_in, per_lead_out = 1600, 400
    n = 9326
    for _ in range(n):
        if g.over_budget():
            break
        g.record("claude-haiku-4-5", per_lead_in, per_lead_out)
    assert g.spent <= 38.00
    # Confirms the whole backlog was affordable — the guard did not have to
    # cut it short. If this ever fails, the backlog grew past what $38 covers
    # and VISION_MAX_SPEND_USD is now the thing keeping spend in bounds
    # rather than a belt-and-suspenders check.
    assert g.spent < 35.00


def test_haiku_is_meaningfully_cheaper_than_opus_for_the_same_grading_task():
    """Pins the reasoning for defaulting to Haiku: same call shape, ~5x cost
    gap, for a task ('roof condition, boarded windows, 1-5') that doesn't need
    a frontier model."""
    haiku_in, haiku_out = _ANTHROPIC_PRICE_PER_MTOK["claude-haiku-4-5"]
    opus_in, opus_out = _ANTHROPIC_PRICE_PER_MTOK["claude-opus-5"]
    assert opus_in / haiku_in >= 4
    assert opus_out / haiku_out >= 4
