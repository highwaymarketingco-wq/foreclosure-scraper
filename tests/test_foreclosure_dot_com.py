"""Regression tests for the foreclosure.com auth-gated scraper.

The site paywalls everything; without credentials we short-circuit
to [] (saves Scrapling stealth time) and the run summary classifies
the source as PAYWALL-BLOCKED rather than REGRESSED.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

from foreclosure_scraper.scrapers.national.foreclosure_dot_com import (
    ForeclosureDotCom,
)


def test_short_circuits_without_credentials(monkeypatch):
    """With no env vars set, fetch() returns [] without any HTTP calls."""
    monkeypatch.delenv("FORECLOSURE_DOT_COM_USER", raising=False)
    monkeypatch.delenv("FORECLOSURE_DOT_COM_PASS", raising=False)
    scraper = ForeclosureDotCom()
    result = list(asyncio.run(scraper.fetch()))
    assert result == []


def test_short_circuits_when_only_user_set(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_DOT_COM_USER", "x@example.com")
    monkeypatch.delenv("FORECLOSURE_DOT_COM_PASS", raising=False)
    scraper = ForeclosureDotCom()
    result = list(asyncio.run(scraper.fetch()))
    assert result == []


def test_marked_as_paywall_required():
    """The scraper class must declare requires_paywall=True so the run
    summary classifies it as PAYWALL-BLOCKED rather than REGRESSED."""
    scraper = ForeclosureDotCom()
    assert getattr(scraper, "requires_paywall", False) is True


def test_main_surfaces_paywall_blocked_status():
    """main.py's source_status logic must check requires_paywall."""
    import inspect
    from foreclosure_scraper import main as orchestrator
    src = inspect.getsource(orchestrator.run)
    assert "requires_paywall" in src
    assert "PAYWALL-BLOCKED" in src
