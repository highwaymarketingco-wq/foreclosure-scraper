"""Tests for the Tyler AWS WAF token pre-warmer.

We pin behavior at the seam between `fetch_waf_token` and `curl_cffi` so
the flag gating, WAF-detection branch, image-grid fallback, and error
paths each have a regression net. Live WAF interaction is not mocked
(it'd be brittle to AWS-side rotations); we just verify the helper's
internal decision tree.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from foreclosure_scraper.tyler_waf_token import fetch_waf_token, _is_enabled


def _set_flag(monkeypatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("TYLER_USE_WAF_SOLVER", raising=False)
    else:
        monkeypatch.setenv("TYLER_USE_WAF_SOLVER", value)


# ---- flag gating ----

def test_flag_unset_is_disabled(monkeypatch):
    _set_flag(monkeypatch, None)
    assert _is_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "Yes"])
def test_flag_truthy_values_enable(monkeypatch, value):
    _set_flag(monkeypatch, value)
    assert _is_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "off"])
def test_flag_falsy_values_disable(monkeypatch, value):
    _set_flag(monkeypatch, value)
    assert _is_enabled() is False


@pytest.mark.asyncio
async def test_disabled_flag_short_circuits_without_fetching(monkeypatch):
    _set_flag(monkeypatch, None)
    # If curl_cffi were called, this would explode (we'd have a network call)
    res = await fetch_waf_token("https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29",
                                 "portal-nc.tylertech.cloud")
    assert res is None


# ---- WAF-detection branches ----

@pytest.mark.asyncio
async def test_no_challenge_in_response_returns_none(monkeypatch):
    """If the response body doesn't contain the WAF marker, we skip."""
    _set_flag(monkeypatch, "1")
    fake_session = MagicMock()
    fake_resp = MagicMock()
    fake_resp.text = "<html><body>Tyler Portal home page</body></html>"
    fake_resp.status_code = 200
    fake_session.get.return_value = fake_resp

    with patch("curl_cffi.requests.Session", return_value=fake_session):
        res = await fetch_waf_token("https://x", "x.com")
    assert res is None


@pytest.mark.asyncio
async def test_extract_fail_returns_none(monkeypatch):
    """Body looks WAF-ish but the gokuProps line is malformed."""
    _set_flag(monkeypatch, "1")
    fake_session = MagicMock()
    fake_resp = MagicMock()
    fake_resp.text = (
        '<html><script src="https://nope/challenge.js"></script>'
        'window.gokuProps = {malformed_no_json};</html>'
    )
    fake_resp.status_code = 405
    fake_session.get.return_value = fake_resp

    with patch("curl_cffi.requests.Session", return_value=fake_session):
        res = await fetch_waf_token("https://x", "x.com")
    assert res is None


@pytest.mark.asyncio
async def test_initial_get_exception_returns_none(monkeypatch):
    _set_flag(monkeypatch, "1")
    fake_session = MagicMock()
    fake_session.get.side_effect = RuntimeError("network down")

    with patch("curl_cffi.requests.Session", return_value=fake_session):
        res = await fetch_waf_token("https://x", "x.com")
    assert res is None


@pytest.mark.asyncio
async def test_solver_returns_token_passes_through(monkeypatch):
    """Happy path: challenge served + solver succeeds → cookie value returned."""
    _set_flag(monkeypatch, "1")
    fake_session = MagicMock()
    fake_resp = MagicMock()
    fake_resp.text = (
        '<html><script src="https://aws-waf-host.example/challenge.js"></script>'
        '<script>window.gokuProps = {"a":1};</script></html>'
    )
    fake_resp.status_code = 405
    fake_session.get.return_value = fake_resp

    fake_solver_instance = MagicMock(return_value="signed.waf.token.payload")
    fake_solver_cls = MagicMock(return_value=fake_solver_instance)
    # extract() is a staticmethod — patch directly on the class
    fake_solver_cls.extract = MagicMock(return_value=({"a": 1}, "aws-waf-host.example"))

    with patch("curl_cffi.requests.Session", return_value=fake_session), \
         patch("foreclosure_scraper._vendor.awswaf.AwsWaf", fake_solver_cls):
        res = await fetch_waf_token("https://x", "x.com")
    assert res == "signed.waf.token.payload"


@pytest.mark.asyncio
async def test_image_grid_challenge_returns_none(monkeypatch):
    """Image-grid (mp_verify) → solver raises Unsupported, we return None."""
    _set_flag(monkeypatch, "1")
    from foreclosure_scraper._vendor.awswaf.aws import UnsupportedChallengeError

    fake_session = MagicMock()
    fake_resp = MagicMock()
    fake_resp.text = (
        '<html><script src="https://aws-waf-host.example/challenge.js"></script>'
        '<script>window.gokuProps = {"a":1};</script></html>'
    )
    fake_resp.status_code = 405
    fake_session.get.return_value = fake_resp

    fake_solver_instance = MagicMock(side_effect=UnsupportedChallengeError("image grid"))
    fake_solver_cls = MagicMock(return_value=fake_solver_instance)
    fake_solver_cls.extract = MagicMock(return_value=({"a": 1}, "aws-waf-host.example"))

    with patch("curl_cffi.requests.Session", return_value=fake_session), \
         patch("foreclosure_scraper._vendor.awswaf.AwsWaf", fake_solver_cls):
        res = await fetch_waf_token("https://x", "x.com")
    assert res is None


@pytest.mark.asyncio
async def test_solver_generic_exception_returns_none(monkeypatch):
    _set_flag(monkeypatch, "1")
    fake_session = MagicMock()
    fake_resp = MagicMock()
    fake_resp.text = (
        '<html><script src="https://aws-waf-host.example/challenge.js"></script>'
        '<script>window.gokuProps = {"a":1};</script></html>'
    )
    fake_resp.status_code = 405
    fake_session.get.return_value = fake_resp

    fake_solver_instance = MagicMock(side_effect=RuntimeError("verify endpoint 500"))
    fake_solver_cls = MagicMock(return_value=fake_solver_instance)
    fake_solver_cls.extract = MagicMock(return_value=({"a": 1}, "aws-waf-host.example"))

    with patch("curl_cffi.requests.Session", return_value=fake_session), \
         patch("foreclosure_scraper._vendor.awswaf.AwsWaf", fake_solver_cls):
        res = await fetch_waf_token("https://x", "x.com")
    assert res is None
