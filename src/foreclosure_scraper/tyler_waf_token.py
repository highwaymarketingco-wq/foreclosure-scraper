"""Headless-less AWS WAF token fetcher for Tyler eCourts portal.

The Scrapling+`solve_cloudflare` path has been escalating to AWS WAF's
image-grid CAPTCHA in patch-run testing — the browser fingerprint
triggers WAF's suspicious-client heuristic and image puzzles follow.

This module short-circuits that flow: hit the URL with `curl_cffi`
(no browser), detect an AWS WAF challenge response, and solve the
invisible/PoW challenge via the vendored xKiian/awswaf port. Returns
the `aws-waf-token` cookie value to inject into the subsequent browser
session so WAF sees a valid token on first request and skips the
challenge entirely.

Behind the `TYLER_USE_WAF_SOLVER=1` env flag; defaults off so we
can A/B against the current Scrapling-only path on real patch runs.

Falls back gracefully:
  - No WAF challenge served → returns None, caller proceeds normally
  - Image-grid challenge served → returns None, caller falls through
    to existing Scrapling+Gemini-Vision puzzle path
  - Any other error → logs + returns None
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import structlog

log = structlog.get_logger()


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def _is_enabled() -> bool:
    return os.environ.get("TYLER_USE_WAF_SOLVER", "").lower() in ("1", "true", "yes")


def _fetch_token_sync(target_url: str, domain: str) -> Optional[str]:
    """Synchronous worker: GET the URL, detect WAF challenge, solve, return token.
    Runs on a worker thread because curl_cffi is sync."""
    try:
        from curl_cffi import requests as cf_requests
    except ImportError:
        log.warning("tyler_waf.curl_cffi_missing")
        return None

    try:
        from ._vendor.awswaf import AwsWaf
        from ._vendor.awswaf.aws import UnsupportedChallengeError
    except ImportError as exc:
        log.warning("tyler_waf.vendor_missing", error=str(exc)[:120])
        return None

    try:
        session = cf_requests.Session(impersonate="chrome")
        session.headers = {
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "accept-language": "en-US,en;q=0.5",
            "user-agent": USER_AGENT,
            "upgrade-insecure-requests": "1",
        }
        resp = session.get(target_url, timeout=30)
    except Exception as exc:
        log.warning("tyler_waf.initial_get_fail", error=str(exc)[:200])
        return None

    body = resp.text or ""
    if "window.gokuProps" not in body or "challenge.js" not in body:
        # No WAF challenge — page is already accessible (cookie still
        # valid from a prior run, or WAF wasn't gating this request).
        log.info("tyler_waf.no_challenge_served", status=resp.status_code)
        return None

    try:
        goku_props, host = AwsWaf.extract(body)
    except ValueError as exc:
        log.warning("tyler_waf.extract_fail", error=str(exc)[:120])
        return None

    try:
        solver = AwsWaf(goku_props, host, domain, user_agent=USER_AGENT)
        token = solver()
    except UnsupportedChallengeError:
        # AWS WAF served the image-grid CAPTCHA. The PoW solver can't
        # handle it; the caller's existing Scrapling+Gemini-Vision path
        # is the fallback.
        log.info("tyler_waf.image_grid_served")
        return None
    except Exception as exc:
        log.warning("tyler_waf.solve_fail", error=str(exc)[:200])
        return None

    if not token or not isinstance(token, str):
        return None
    log.info("tyler_waf.solved", token_len=len(token))
    return token


async def fetch_waf_token(target_url: str, domain: str) -> Optional[str]:
    """Async wrapper around the curl_cffi-based sync worker.

    Returns the `aws-waf-token` cookie value on success, or None if no
    challenge was served / image-grid was served / any error occurred.
    Callers should treat None as "carry on with the existing flow."
    """
    if not _is_enabled():
        return None
    return await asyncio.to_thread(_fetch_token_sync, target_url, domain)
