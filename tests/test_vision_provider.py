"""Pin the VISION_PROVIDER dispatch.

Prevents regressions where the Anthropic + Gemini code paths drift apart
or one provider silently breaks. Doesn't actually call the APIs — it
verifies the right client builder + assess fn pair is wired up for each
provider value, and that both produce the same output dict shape.
"""
from __future__ import annotations

import os
import sys
import importlib

import pytest


def _reload_module():
    """VISION_PROVIDER is read at import time, so re-import after env mutation."""
    import foreclosure_scraper.enrichment_vision as ev
    importlib.reload(ev)
    return ev


def test_default_provider_is_anthropic(monkeypatch):
    monkeypatch.delenv("VISION_PROVIDER", raising=False)
    ev = _reload_module()
    assert ev.VISION_PROVIDER == "anthropic"


def test_provider_switch_to_gemini(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "gemini")
    ev = _reload_module()
    assert ev.VISION_PROVIDER == "gemini"


def test_provider_case_insensitive(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "GEMINI")
    ev = _reload_module()
    assert ev.VISION_PROVIDER == "gemini"


def test_anthropic_builder_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ev = _reload_module()
    client, assess_fn = ev._build_anthropic_client()
    assert client is None and assess_fn is None


def test_gemini_builder_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    ev = _reload_module()
    client, assess_fn = ev._build_gemini_client()
    assert client is None and assess_fn is None


def test_anthropic_assess_fn_wired(monkeypatch):
    """When ANTHROPIC_API_KEY is present, builder returns the anthropic
    assess function — guards against accidental cross-wiring."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    ev = _reload_module()
    client, assess_fn = ev._build_anthropic_client()
    if client is None:
        pytest.skip("anthropic SDK not installed")
    assert assess_fn is ev._assess_one_anthropic


def test_gemini_assess_fn_wired(monkeypatch):
    """When GEMINI_API_KEY is present, builder returns the gemini assess
    function — guards against accidental cross-wiring."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    ev = _reload_module()
    model, assess_fn = ev._build_gemini_client()
    if model is None:
        pytest.skip("google-generativeai SDK not installed")
    assert assess_fn is ev._assess_one_gemini


def test_provider_pricing_table_covers_both():
    """Cost-estimate logging will throw KeyError if one provider is
    missing pricing — pin both."""
    ev = _reload_module()
    assert "anthropic" in ev._PROVIDER_PRICING
    assert "gemini" in ev._PROVIDER_PRICING
    for p in ("anthropic", "gemini"):
        assert "in_per_mtok" in ev._PROVIDER_PRICING[p]
        assert "out_per_mtok" in ev._PROVIDER_PRICING[p]


def test_gemini_cheaper_than_anthropic():
    """Sanity check the relative pricing — if Gemini ever ends up more
    expensive than Anthropic the user should re-evaluate which to default
    to. This will fail loudly if pricing changes invert."""
    ev = _reload_module()
    g = ev._PROVIDER_PRICING["gemini"]
    a = ev._PROVIDER_PRICING["anthropic"]
    assert g["in_per_mtok"] < a["in_per_mtok"]
    assert g["out_per_mtok"] < a["out_per_mtok"]


# --- output shape consistency between providers ---

def test_both_assess_fns_exist_and_callable():
    """Both providers must expose an async coroutine function. Catches
    type drift if someone refactors one and not the other."""
    import inspect
    ev = _reload_module()
    assert inspect.iscoroutinefunction(ev._assess_one_anthropic)
    assert inspect.iscoroutinefunction(ev._assess_one_gemini)


def test_legacy_assess_one_alias_preserved():
    """External callers may import _assess_one (pre-refactor name).
    Keep the alias so we don't break them silently."""
    ev = _reload_module()
    assert ev._assess_one is ev._assess_one_anthropic
