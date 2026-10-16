"""_gather_phases' wall-clock budget must respect a caller's own default_s the same way
_await_capped already does -- otherwise a phase that sizes its own budget (e.g. the
2026-10-16 divorce fix, default_s=1920) is silently capped back down to whatever
ENRICH_PHASE_MAX_SECONDS happens to be set to in the run environment, exactly the
"2026-09-23 dot_ocr zero-visibility bug" deploy/oracle/run_profile.json already warns
ENRICH_PHASE_MAX_SECONDS can cause.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import main as M


def test_a_custom_default_s_is_not_overridden_by_the_global_env_var(monkeypatch):
    # Simulates the real failure: ENRICH_PHASE_MAX_SECONDS set to the ordinary 900s
    # global default while this phase needs more time, same shape as deploy/oracle/
    # run_profile.json's documented "*" wildcard for this env var.
    monkeypatch.setenv("ENRICH_PHASE_MAX_SECONDS", "0.01")

    async def _slow_but_under_custom_budget():
        await asyncio.sleep(0.05)
        return "ok"

    result = asyncio.run(M._gather_phases({"p": _slow_but_under_custom_budget()}, default_s=5))
    assert result == {"p": "ok"}   # survived past the env var's 0.01s because default_s=5 won


def test_the_bare_900_default_still_honors_the_global_env_var(monkeypatch):
    """No existing call site passes a non-default default_s today -- this locks in that
    the escape hatch changes nothing for them: default_s==900 still defers to the env var,
    exactly like before this fix."""
    monkeypatch.setenv("ENRICH_PHASE_MAX_SECONDS", "0.01")

    async def _never_finishes_in_time():
        await asyncio.sleep(5)
        return "too slow"

    result = asyncio.run(M._gather_phases({"p": _never_finishes_in_time()}))
    assert result == {"p": None}   # timed out at the env var's 0.01s, not the 900s default


def test_no_env_var_set_falls_back_to_the_passed_default_s(monkeypatch):
    monkeypatch.delenv("ENRICH_PHASE_MAX_SECONDS", raising=False)

    async def _ok():
        return "fine"

    result = asyncio.run(M._gather_phases({"p": _ok()}, default_s=5))
    assert result == {"p": "fine"}


def test_the_divorce_gather_phases_call_site_passes_its_own_budget():
    """Regression guard on the call site itself: enrichment_sc_divorce.py's own budget
    (FORECLOSURE_SC_DIVORCE_BUDGET_S, 1800s default) was being hard-cancelled at the bare
    900s default every run (confirmed live, 2026-10-16: no sc_divorce.enrich.done line
    anywhere in a full VM run log). The fix must keep passing a default_s comfortably
    above 1800."""
    import re
    from pathlib import Path
    main_src = (Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper"
                / "main.py").read_text()
    i = main_src.index("_divorce_results = await _gather_phases(")
    site = main_src[i:main_src.index("\n", i)]
    m = re.search(r"default_s=(\d+)", site)
    assert m, f"divorce _gather_phases call has no default_s: {site}"
    assert int(m.group(1)) > 1800, "must exceed enrichment_sc_divorce.py's own 1800s budget"
