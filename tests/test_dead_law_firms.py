"""Regression tests for the previously-silent-broken law-firm scrapers.

After investigation:
  * korn — parked/dead domain (FingerprintJS redirect shim, no firm content)
  * mcmichael_taylor_gray — AJAX-loaded ("Loading..." in body)
  * aldridge_pite — FIXED via compliant plain fetch (GET + disclaimer Referer
    returns the table server-side; no bot-detection bypass). NC table is
    often empty between sale cycles.
  * finkel — actually works (8 listings/run); most fall outside in-scope
    counties (Lexington, Richland) so post-filter yield is 0

korn + mcmichael remain requires_render=True so the weekly run summary
shows "RENDER-REQUIRED" instead of REGRESSED (stops silent-fail noise
without claiming a fix).
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.law_firms.korn import Korn
from foreclosure_scraper.scrapers.law_firms.mcmichael_taylor_gray import (
    McMichaelTaylorGray,
)
from foreclosure_scraper.scrapers.law_firms.aldridge_pite import AldridgePite


def test_korn_classified_render_required():
    s = Korn()
    assert getattr(s, "requires_render", False) is True
    assert s.expected_min_count == 0


def test_mtg_classified_render_required():
    s = McMichaelTaylorGray()
    assert getattr(s, "requires_render", False) is True
    assert s.expected_min_count == 0


def test_aldridge_now_plain_fetch():
    # aldridge_pite was reclassified from RENDER-REQUIRED to a plain, compliant
    # fetch: a normal GET with a disclaimer-page Referer returns the listings
    # table server-side (no stealth browser, no bot-detection bypass). The NC
    # table is often empty between sale cycles, hence expected_min_count == 0.
    s = AldridgePite()
    assert getattr(s, "requires_render", False) is False
    assert s.expected_min_count == 0


def test_main_surfaces_render_required_status():
    import inspect
    from foreclosure_scraper import main as orchestrator
    src = inspect.getsource(orchestrator.run)
    assert "RENDER-REQUIRED" in src
    assert "requires_render" in src
