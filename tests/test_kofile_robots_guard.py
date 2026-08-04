"""Offline tests for the Kofile PublicSearch robots-compliance guard.

Every in-footprint Kofile *.publicsearch.us host serves (verified live 2026-07-02):

    user-agent: *
    Allow: /$
    Disallow: /

That `Disallow: /` is a machine-readable no-automation directive covering the SPA
search routes (/search, /results) and the internal JSON API (/api/search) — so the
source is WALLED, not render-unlockable, under the project's compliance line (render
an OPEN, robots-ALLOWED page's own JS; never ride a CAPTCHA/login/WAF/robots-ban).

These tests pin the robots evaluator against the REAL Kofile robots body and confirm
both public entry points short-circuit to a clean [] no-op (no httpx probe, no stealth
render) when the search path is robots-disallowed. CI never hits the network.
"""
from pathlib import Path

import pytest

from foreclosure_scraper.rod import kofile
from foreclosure_scraper.rod.kofile import (
    _path_disallowed,
    _robots_blocks_search,
    _ROBOTS_SEARCH_PATHS,
)

# The exact robots.txt body served by oconee.sc.publicsearch.us +
# greenville.sc.publicsearch.us (both identical, captured live 2026-07-02).
KOFILE_ROBOTS = "user-agent: *\nAllow: /$\nDisallow: /"

# A hypothetical robots-clean body a county could publish to flip the source on.
CLEAN_ROBOTS = "user-agent: *\nAllow: /\nDisallow: /admin/"


def test_kofile_robots_disallows_every_search_path():
    """The real Kofile robots body disallows all three paths we would query."""
    for path in _ROBOTS_SEARCH_PATHS:
        assert _path_disallowed(KOFILE_ROBOTS, path) is True, path


def test_kofile_robots_allows_bare_root_only():
    """`Allow: /$` is an EXACT-match anchor: only the bare root is allowed; any
    deeper path (what we actually need) stays disallowed."""
    assert _path_disallowed(KOFILE_ROBOTS, "/") is False
    assert _path_disallowed(KOFILE_ROBOTS, "/search") is True


def test_clean_robots_would_allow_search():
    """Guard is not a blanket off-switch: a robots-clean host allows the paths,
    so the source flips on for free the day a county relaxes its robots."""
    for path in _ROBOTS_SEARCH_PATHS:
        assert _path_disallowed(CLEAN_ROBOTS, path) is False, path


def test_allow_longer_than_disallow_wins():
    """Standard robots longest-match/Allow-tiebreak semantics."""
    body = "user-agent: *\nDisallow: /search\nAllow: /search/public"
    assert _path_disallowed(body, "/search") is True
    assert _path_disallowed(body, "/search/public") is False


def test_robots_blocks_search_fails_closed_on_error(monkeypatch):
    """If robots.txt can't be read, treat as blocked — never query an endpoint we
    can't confirm is robots-allowed."""
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(kofile.httpx, "get", boom)
    assert _robots_blocks_search("oconee.sc.publicsearch.us") is True


def test_robots_blocks_search_true_on_real_body(monkeypatch):
    class _Resp:
        status_code = 200
        text = KOFILE_ROBOTS

    monkeypatch.setattr(kofile.httpx, "get", lambda *a, **k: _Resp())
    assert _robots_blocks_search("oconee.sc.publicsearch.us") is True


def test_robots_blocks_search_false_on_clean_body(monkeypatch):
    class _Resp:
        status_code = 200
        text = CLEAN_ROBOTS

    monkeypatch.setattr(kofile.httpx, "get", lambda *a, **k: _Resp())
    assert _robots_blocks_search("oconee.sc.publicsearch.us") is False


def test_no_robots_escape_hatch_exists():
    """There must be NO env switch that skips the robots guard.

    This test previously asserted the opposite: that KOFILE_IGNORE_ROBOTS=1
    disabled the check. That switch was removed, because a flag that ignores a
    machine-readable no-automation directive is a bypass with a config file in
    front of it — the same reason the equivalent switch was removed from the
    Rutherford Sturgis module. If a Kofile host goes robots-clean, the guard
    notices on its own on the next run.
    """
    assert not hasattr(kofile, "_IGNORE_ROBOTS"), (
        "a robots escape hatch was reintroduced into rod/kofile.py"
    )
    src = Path(kofile.__file__).read_text()
    assert "IGNORE_ROBOTS" not in src, (
        "rod/kofile.py references an IGNORE_ROBOTS switch again"
    )


@pytest.mark.asyncio
async def test_search_by_name_short_circuits_when_robots_blocked(monkeypatch):
    """search_by_name must return [] WITHOUT hitting the API/render when the
    search path is robots-disallowed. We assert it never touches the http client."""
    monkeypatch.setattr(kofile, "_robots_blocks_search", lambda host: True)

    def _fail_client(*a, **k):  # would raise if the guard let execution through
        raise AssertionError("http client called despite robots block")

    monkeypatch.setattr(kofile, "client", _fail_client)
    out = await kofile.search_by_name("SC", "Oconee", "SMITH JOHN")
    assert out == []


@pytest.mark.asyncio
async def test_discover_recent_nods_short_circuits_when_robots_blocked(monkeypatch):
    monkeypatch.setattr(kofile, "_robots_blocks_search", lambda host: True)

    def _fail_client(*a, **k):
        raise AssertionError("http client called despite robots block")

    monkeypatch.setattr(kofile, "client", _fail_client)
    out = await kofile.discover_recent_nods("SC", "Oconee", days_back=60)
    assert out == []


@pytest.mark.asyncio
async def test_unmapped_county_returns_empty():
    """Sanity: a county not in KOFILE_COUNTIES is a plain [] (guard not reached)."""
    assert await kofile.search_by_name("NC", "Wake", "SMITH") == []
