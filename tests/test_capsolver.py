"""Pin the CapSolver client behavior + dispatch logic.

CapSolver makes real network calls to api.capsolver.com; we mock httpx
to avoid actual paid API hits. Tests cover: missing-key short-circuit,
task-creation success, polling-until-ready, error responses, timeout
behavior.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from foreclosure_scraper.enrichment_capsolver import (
    POLL_MAX_ATTEMPTS,
    solve_aws_waf,
)


@pytest.mark.asyncio
async def test_returns_none_without_api_key(monkeypatch):
    """No CAPSOLVER_API_KEY env → return None silently. Doesn't try
    to call the API at all."""
    monkeypatch.delenv("CAPSOLVER_API_KEY", raising=False)
    out = await solve_aws_waf("https://example.com/")
    assert out is None


@pytest.mark.asyncio
async def test_returns_none_when_create_task_errors(monkeypatch):
    """When CapSolver's createTask returns errorId>0, return None."""
    monkeypatch.setenv("CAPSOLVER_API_KEY", "test-key")

    class FakeResp:
        status_code = 200
        def json(self):
            return {"errorId": 1, "errorCode": "ERROR_KEY_DOES_NOT_EXIST"}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return FakeResp()

    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        out = await solve_aws_waf("https://example.com/")
    assert out is None


@pytest.mark.asyncio
async def test_returns_token_on_ready(monkeypatch):
    """Happy path: createTask → taskId, then poll → ready with cookie."""
    monkeypatch.setenv("CAPSOLVER_API_KEY", "test-key")
    # Speed up polling for the test
    monkeypatch.setattr("foreclosure_scraper.enrichment_capsolver.POLL_INTERVAL_SEC", 0.01)

    call_count = {"n": 0}

    class FakeResp:
        status_code = 200
        def __init__(self, payload):
            self._p = payload
        def json(self):
            return self._p

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None, **kw):
            call_count["n"] += 1
            if "createTask" in url:
                return FakeResp({"errorId": 0, "taskId": "abc-123"})
            # getTaskResult — first call still processing, second is ready
            if call_count["n"] == 2:
                return FakeResp({"errorId": 0, "status": "processing"})
            return FakeResp({
                "errorId": 0,
                "status": "ready",
                "solution": {"cookie": "AWS-WAF-TOKEN-VALUE-123"},
            })

    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        out = await solve_aws_waf("https://example.com/")
    assert out == "AWS-WAF-TOKEN-VALUE-123"


@pytest.mark.asyncio
async def test_returns_none_on_solve_error(monkeypatch):
    """When polling returns an errorId, return None immediately."""
    monkeypatch.setenv("CAPSOLVER_API_KEY", "test-key")
    monkeypatch.setattr("foreclosure_scraper.enrichment_capsolver.POLL_INTERVAL_SEC", 0.01)

    class FakeResp:
        status_code = 200
        def __init__(self, p): self._p = p
        def json(self): return self._p

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None, **kw):
            if "createTask" in url:
                return FakeResp({"errorId": 0, "taskId": "x"})
            return FakeResp({
                "errorId": 1,
                "errorCode": "ERROR_CAPTCHA_UNSOLVABLE",
                "errorDescription": "WAF challenge could not be solved",
            })

    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        out = await solve_aws_waf("https://example.com/")
    assert out is None


@pytest.mark.asyncio
async def test_timeout_after_max_polls(monkeypatch):
    """If polling never resolves to ready, give up after POLL_MAX_ATTEMPTS."""
    monkeypatch.setenv("CAPSOLVER_API_KEY", "test-key")
    monkeypatch.setattr("foreclosure_scraper.enrichment_capsolver.POLL_INTERVAL_SEC", 0.001)
    monkeypatch.setattr("foreclosure_scraper.enrichment_capsolver.POLL_MAX_ATTEMPTS", 3)

    class FakeResp:
        status_code = 200
        def __init__(self, p): self._p = p
        def json(self): return self._p

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None, **kw):
            if "createTask" in url:
                return FakeResp({"errorId": 0, "taskId": "x"})
            return FakeResp({"errorId": 0, "status": "processing"})

    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        out = await solve_aws_waf("https://example.com/")
    assert out is None


@pytest.mark.asyncio
async def test_handles_token_field_alternative(monkeypatch):
    """Some CapSolver task types return 'token' instead of 'cookie' —
    accept either."""
    monkeypatch.setenv("CAPSOLVER_API_KEY", "test-key")
    monkeypatch.setattr("foreclosure_scraper.enrichment_capsolver.POLL_INTERVAL_SEC", 0.01)

    class FakeResp:
        status_code = 200
        def __init__(self, p): self._p = p
        def json(self): return self._p

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None, **kw):
            if "createTask" in url:
                return FakeResp({"errorId": 0, "taskId": "x"})
            return FakeResp({
                "errorId": 0,
                "status": "ready",
                "solution": {"token": "ALT-TOKEN-456"},
            })

    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        out = await solve_aws_waf("https://example.com/")
    assert out == "ALT-TOKEN-456"


def test_poll_max_attempts_sane_default():
    """45 attempts × 2s = 90s solve timeout. Reasonable for AWS WAF
    (most solves return in 5-20s)."""
    assert POLL_MAX_ATTEMPTS >= 30
