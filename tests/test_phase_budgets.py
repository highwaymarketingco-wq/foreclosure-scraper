"""Long phases must be bounded, and bounding must not throw away finished work.

The 2026-08-11 run took 23 hours. 16 of those were two unbounded phases sitting
on sources that are documented as permanently walled:

  5.5 h  scrape phase, stealth browser retrying an AWS-WAF portal (202s)
 10.5 h  skip trace, grinding fastpeoplesearch 403s

Neither emitted a single log line while it happened. These tests pin the two
properties that matter: the budget fires, and a source that already finished
still counts.
"""
from __future__ import annotations

import asyncio

import pytest


async def _bounded_phase(tasks, budget_s):
    """The shape used in main.run for the scrape phase: keep what finished,
    cancel only what is still hanging."""
    done, pending = await asyncio.wait(tasks, timeout=budget_s)
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    out = []
    for t in done:
        try:
            out.append(t.result())
        except Exception:  # noqa: BLE001
            pass
    return out, pending


@pytest.mark.asyncio
async def test_budget_keeps_completed_sources_and_cancels_hangers():
    async def quick(name):
        await asyncio.sleep(0.01)
        return name

    async def hangs(name):
        await asyncio.sleep(3600)
        return name

    tasks = [asyncio.create_task(quick("a"), name="a"),
             asyncio.create_task(quick("b"), name="b"),
             asyncio.create_task(hangs("walled"), name="walled")]

    results, pending = await _bounded_phase(tasks, budget_s=0.3)

    assert sorted(results) == ["a", "b"], "finished sources were discarded"
    assert {t.get_name() for t in pending} == {"walled"}


@pytest.mark.asyncio
async def test_wait_for_around_gather_would_have_lost_everything():
    """Why the phase does not use wait_for(gather(...)).

    This is the naive fix, and it throws away every source that finished.
    Pinned so nobody 'simplifies' the phase back into it.
    """
    async def quick(name):
        await asyncio.sleep(0.01)
        return name

    async def hangs(name):
        await asyncio.sleep(3600)
        return name

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            asyncio.gather(quick("a"), quick("b"), hangs("walled")),
            timeout=0.3,
        )
    # Nothing is recoverable from that call: the two finished results are gone.


@pytest.mark.asyncio
async def test_a_hanging_phase_is_capped_not_infinite():
    """The skip-trace shape: one coroutine that never returns."""
    async def never():
        await asyncio.sleep(3600)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(never(), timeout=0.2)


def test_every_long_phase_declares_a_budget_env_var():
    """A new unbounded phase is how this regressed. Any phase that can sit on a
    walled source must be listed here."""
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "src/foreclosure_scraper/main.py"
    body = src.read_text()
    for var in ("COURT_PHASE_MAX_SECONDS", "VISION_MAX_SECONDS",
                "SKIP_TRACE_MAX_SECONDS", "SCRAPE_PHASE_MAX_SECONDS"):
        assert var in body, f"{var} budget disappeared from the orchestrator"


def test_scrape_phase_does_not_use_wait_for_around_gather():
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "src/foreclosure_scraper/main.py"
    body = src.read_text()
    i = body.find("SCRAPE_PHASE_MAX_SECONDS")
    assert i != -1
    window = body[i:i + 700]
    assert "asyncio.wait(" in window, "scrape phase must keep completed sources"
