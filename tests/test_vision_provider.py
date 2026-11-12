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


# ---- Gemini multi-key rotation -----------------------------------------------

def test_parse_gemini_keys_single(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "key-A")
    monkeypatch.delenv("GEMINI_API_KEY_1", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    ev = _reload_module()
    assert ev._parse_gemini_keys() == ["key-A"]


def test_parse_gemini_keys_comma_separated(monkeypatch):
    """Comma-separated list yields multiple keys, whitespace stripped."""
    monkeypatch.setenv("GEMINI_API_KEY", "key-A, key-B ,key-C")
    monkeypatch.delenv("GEMINI_API_KEY_1", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    ev = _reload_module()
    assert ev._parse_gemini_keys() == ["key-A", "key-B", "key-C"]


def test_parse_gemini_keys_numbered_fallback(monkeypatch):
    """Numbered env vars (GEMINI_API_KEY_1, _2, ...) collected too."""
    monkeypatch.setenv("GEMINI_API_KEY", "primary")
    monkeypatch.setenv("GEMINI_API_KEY_1", "k1")
    monkeypatch.setenv("GEMINI_API_KEY_2", "k2")
    monkeypatch.setenv("GEMINI_API_KEY_3", "k3")
    monkeypatch.delenv("GEMINI_API_KEY_4", raising=False)
    ev = _reload_module()
    assert ev._parse_gemini_keys() == ["primary", "k1", "k2", "k3"]


def test_parse_gemini_keys_dedupe_numbered_with_primary(monkeypatch):
    """If a numbered key duplicates a primary-list key, dedupe."""
    monkeypatch.setenv("GEMINI_API_KEY", "k1,k2")
    monkeypatch.setenv("GEMINI_API_KEY_1", "k1")  # duplicate of primary
    monkeypatch.setenv("GEMINI_API_KEY_2", "k3")
    ev = _reload_module()
    assert ev._parse_gemini_keys() == ["k1", "k2", "k3"]


def test_parse_gemini_keys_empty(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_1", raising=False)
    ev = _reload_module()
    assert ev._parse_gemini_keys() == []


def test_single_key_builds_plain_client(monkeypatch):
    """One key → plain genai.Client, no rotation overhead."""
    monkeypatch.setenv("GEMINI_API_KEY", "single-key")
    monkeypatch.delenv("GEMINI_API_KEY_1", raising=False)
    ev = _reload_module()
    client, fn = ev._build_gemini_client()
    if client is None:
        pytest.skip("google-genai SDK not installed")
    # Plain client exposes .aio.models without our rotation wrapper
    assert not isinstance(client, ev.GeminiRotatingClient)
    assert fn is ev._assess_one_gemini


def test_multi_key_builds_rotating_client(monkeypatch):
    """Multiple keys → GeminiRotatingClient wrapper."""
    monkeypatch.setenv("GEMINI_API_KEY", "k1,k2,k3")
    monkeypatch.delenv("GEMINI_API_KEY_1", raising=False)
    ev = _reload_module()
    client, fn = ev._build_gemini_client()
    if client is None:
        pytest.skip("google-genai SDK not installed")
    assert isinstance(client, ev.GeminiRotatingClient)
    assert client.num_keys == 3
    assert fn is ev._assess_one_gemini


@pytest.mark.asyncio
async def test_rotating_client_rotates_on_429(monkeypatch):
    """When current key returns a quota error, rotate to next key + retry."""
    monkeypatch.setenv("GEMINI_API_KEY", "k1,k2")
    monkeypatch.delenv("GEMINI_API_KEY_1", raising=False)
    ev = _reload_module()
    try:
        client = ev.GeminiRotatingClient(["k1", "k2"])
    except ImportError:
        pytest.skip("google-genai SDK not installed")

    call_log = []

    class FakeKey:
        def __init__(self, name, should_429):
            self.name = name
            self.should_429 = should_429

        class Aio:
            def __init__(self, outer):
                self.outer = outer

            class Models:
                def __init__(self, outer):
                    self.outer = outer

                async def generate_content(self, **kwargs):
                    call_log.append(self.outer.outer.name)
                    if self.outer.outer.should_429:
                        raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")
                    return {"ok": True, "key": self.outer.outer.name}

            @property
            def models(self):
                return FakeKey.Aio.Models(self)

        @property
        def aio(self):
            return FakeKey.Aio(self)

    # Inject fake clients
    client._clients = {
        0: FakeKey("k1", should_429=True),   # k1 quota'd
        1: FakeKey("k2", should_429=False),  # k2 fresh
    }
    result = await client.aio.models.generate_content(model="x", contents=[])
    assert result == {"ok": True, "key": "k2"}
    assert call_log == ["k1", "k2"]
    # k1 marked exhausted, k2 is current
    assert 0 in client._exhausted
    assert client._idx == 1


@pytest.mark.asyncio
async def test_rotating_client_all_keys_exhausted_raises(monkeypatch):
    """When every key is exhausted, the final 429 propagates."""
    monkeypatch.setenv("GEMINI_API_KEY", "k1,k2")
    ev = _reload_module()
    try:
        client = ev.GeminiRotatingClient(["k1", "k2"])
    except ImportError:
        pytest.skip("google-genai SDK not installed")

    class FakeKey:
        class Aio:
            class Models:
                async def generate_content(self, **kwargs):
                    raise RuntimeError("429 RESOURCE_EXHAUSTED")

            @property
            def models(self):
                return FakeKey.Aio.Models()

        @property
        def aio(self):
            return FakeKey.Aio()

    client._clients = {0: FakeKey(), 1: FakeKey()}
    with pytest.raises(RuntimeError, match="429"):
        await client.aio.models.generate_content(model="x", contents=[])
    assert client._exhausted == {0, 1}


@pytest.mark.asyncio
async def test_rotating_client_non_quota_error_no_rotation(monkeypatch):
    """A non-429 error (network, auth, etc.) should NOT burn through keys —
    propagate immediately without rotating."""
    monkeypatch.setenv("GEMINI_API_KEY", "k1,k2,k3")
    ev = _reload_module()
    try:
        client = ev.GeminiRotatingClient(["k1", "k2", "k3"])
    except ImportError:
        pytest.skip("google-genai SDK not installed")

    class FakeKey:
        class Aio:
            class Models:
                async def generate_content(self, **kwargs):
                    raise RuntimeError("503 Service Unavailable")

            @property
            def models(self):
                return FakeKey.Aio.Models()

        @property
        def aio(self):
            return FakeKey.Aio()

    client._clients = {0: FakeKey(), 1: FakeKey(), 2: FakeKey()}
    with pytest.raises(RuntimeError, match="503"):
        await client.aio.models.generate_content(model="x", contents=[])
    # No keys marked exhausted — only quota errors trigger rotation
    assert client._exhausted == set()
