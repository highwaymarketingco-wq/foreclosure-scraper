"""Regression tests for the previously-silent-broken law-firm scrapers.

After investigation:
  * korn — JS-rendered SPA (gets only "Click here to enter")
  * mcmichael_taylor_gray — AJAX-loaded ("Loading..." in body)
  * aldridge_pite — disclaimer page now requires session cookie
  * finkel — actually works (8 listings/run); most fall outside in-scope
    counties (Lexington, Richland) so post-filter yield is 0

Three of the four are now classified requires_render=True so the
weekly run summary shows "RENDER-REQUIRED" instead of REGRESSED.
This stops the silent-fail noise without claiming we've fixed them
(future fix: wire Scrapling stealth login flow per scraper).
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


def test_aldridge_classified_render_required():
    s = AldridgePite()
    assert getattr(s, "requires_render", False) is True
    assert s.expected_min_count == 0


def test_main_surfaces_render_required_status():
    import inspect
    from foreclosure_scraper import main as orchestrator
    src = inspect.getsource(orchestrator.run)
    assert "RENDER-REQUIRED" in src
    assert "requires_render" in src
