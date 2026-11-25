"""2Captcha reCAPTCHA v2 solver.

2Captcha (2captcha.com) is a paid CAPTCHA-solving service with the best
pricing for high-volume reCAPTCHA v2 solving:

Pricing (2026-11):
- reCAPTCHA v2: $0.00099 per solve (~$1 per 1000)
- reCAPTCHA v3: $0.00199 per solve (~$2 per 1000)
- reCAPTCHA Enterprise: $0.00199 per solve

For Lexington (32K rows) + Darlington (6K) + Wake (26K) = 64K rows:
- If we scrape weekly: ~64 reCAPTCHAs/week = $0.06/week = $3.24/year
- If we scrape daily: ~64 reCAPTCHAs/day = $0.42/week = $21.84/year

A $10 deposit lasts ~10,000 solves = months/years at our volume.

Alternatives considered:
- CapSolver: $0.00119/solve (20% more expensive)
- AntiCaptcha: $0.00100/solve (same price, less reliable)
- NopeCHA: $0.0014/solve (40% more expensive)
- Death By Captcha: $0.00139/solve (40% more expensive)

Reads TWOCAPTCHA_API_KEY from env or .secrets/2captcha_api_key.txt.
Returns None when unset (caller falls back to Claude vision or fails gracefully).

Usage:
    from .enrichment_2captcha import solve_recaptcha_v2
    
    token = await solve_recaptcha_v2(
        site_key="6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI",
        page_url="https://example.com/page-with-captcha"
    )
    
    if token:
        # Inject token into page via JavaScript:
        await page.evaluate(f'''
            document.getElementById("g-recaptcha-response").innerHTML = "{token}";
        ''')
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx
import structlog

log = structlog.get_logger()

TWOCAPTCHA_BASE = "https://2captcha.com"
# Polling: reCAPTCHA v2 typically resolves in 10-60s
POLL_INTERVAL_SEC = 3.0
POLL_MAX_ATTEMPTS = 40  # 120 seconds max


async def solve_recaptcha_v2(
    site_key: str,
    page_url: str,
    api_key: Optional[str] = None,
    timeout: float = 180.0,
    is_invisible: bool = False,
    enterprise: bool = False,
) -> Optional[str]:
    """Solve a reCAPTCHA v2 challenge and return the response token.
    
    Args:
        site_key: reCAPTCHA site key (from page source)
        page_url: Full URL of the page with the CAPTCHA
        api_key: 2Captcha API key (or reads from env/secrets)
        timeout: Max seconds to wait for solution
        is_invisible: True for invisible reCAPTCHA
        enterprise: True for reCAPTCHA Enterprise
        
    Returns:
        Response token string to inject, or None on failure
    """
    # Get API key
    key = api_key or os.environ.get("TWOCAPTCHA_API_KEY")
    if not key:
        for path in ["~/.secrets/2captcha_api_key.txt", ".secrets/2captcha_api_key.txt"]:
            try:
                with open(os.path.expanduser(path)) as f:
                    key = f.read().strip()
                if key:
                    break
            except Exception:
                pass
    
    if not key:
        log.info("2captcha.no_api_key", hint="Set TWOCAPTCHA_API_KEY or create .secrets/2captcha_api_key.txt")
        return None
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Step 1: Submit task
        try:
            params = {
                "key": key,
                "method": "userrecaptcha",
                "googlekey": site_key,
                "pageurl": page_url,
                "json": "1",
            }
            
            if is_invisible:
                params["invisible"] = "1"
            
            if enterprise:
                params["enterprise"] = "1"
            
            r = await client.get(f"{TWOCAPTCHA_BASE}/in.php", params=params)
            data = r.json()
        except Exception as exc:
            log.warning("2captcha.submit_fail", error=str(exc)[:200])
            return None
        
        if data.get("status") != 1:
            log.warning(
                "2captcha.submit_error",
                error_code=data.get("request"),
                error_text=data.get("error_text", ""),
            )
            return None
        
        task_id = data.get("request")
        if not task_id:
            log.warning("2captcha.no_task_id")
            return None
        
        log.info("2captcha.task_created", task_id=task_id, site_key=site_key[:20], url=page_url[:100])
        
        # Step 2: Poll for solution
        for attempt in range(POLL_MAX_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_SEC)
            
            try:
                r = await client.get(
                    f"{TWOCAPTCHA_BASE}/res.php",
                    params={
                        "key": key,
                        "action": "get",
                        "id": task_id,
                        "json": "1",
                    },
                )
                data = r.json()
            except Exception as exc:
                log.debug("2captcha.poll_fail", attempt=attempt, error=str(exc)[:200])
                continue
            
            status = data.get("status")
            
            if status == 1:
                token = data.get("request")
                if not token:
                    log.warning("2captcha.solution_missing_token")
                    return None
                
                log.info(
                    "2captcha.solved",
                    attempts=attempt + 1,
                    elapsed_sec=round((attempt + 1) * POLL_INTERVAL_SEC, 1),
                )
                return token
            
            # Status 0 means still processing
            if data.get("request") == "CAPCHA_NOT_READY":
                continue
            
            # Any other response is an error
            log.warning(
                "2captcha.solve_error",
                request=data.get("request"),
                error_text=data.get("error_text", ""),
            )
            return None
        
        log.warning(
            "2captcha.timeout",
            task_id=task_id,
            attempts=POLL_MAX_ATTEMPTS,
            total_sec=POLL_MAX_ATTEMPTS * POLL_INTERVAL_SEC,
        )
        return None


async def solve_recaptcha_v3(
    site_key: str,
    page_url: str,
    action: str = "verify",
    min_score: float = 0.3,
    api_key: Optional[str] = None,
    timeout: float = 180.0,
) -> Optional[str]:
    """Solve a reCAPTCHA v3 challenge and return the response token.
    
    Args:
        site_key: reCAPTCHA site key
        page_url: Full URL of the page
        action: Action name (default "verify")
        min_score: Minimum score needed (0.1-0.9, default 0.3)
        api_key: 2Captcha API key
        timeout: Max seconds to wait
        
    Returns:
        Response token string, or None on failure
    """
    key = api_key or os.environ.get("TWOCAPTCHA_API_KEY")
    if not key:
        for path in ["~/.secrets/2captcha_api_key.txt", ".secrets/2captcha_api_key.txt"]:
            try:
                with open(os.path.expanduser(path)) as f:
                    key = f.read().strip()
                if key:
                    break
            except Exception:
                pass
    
    if not key:
        log.info("2captcha.no_api_key")
        return None
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            r = await client.get(
                f"{TWOCAPTCHA_BASE}/in.php",
                params={
                    "key": key,
                    "method": "userrecaptcha",
                    "version": "v3",
                    "googlekey": site_key,
                    "pageurl": page_url,
                    "action": action,
                    "min_score": min_score,
                    "json": "1",
                },
            )
            data = r.json()
        except Exception as exc:
            log.warning("2captcha.v3_submit_fail", error=str(exc)[:200])
            return None
        
        if data.get("status") != 1:
            log.warning("2captcha.v3_submit_error", error_code=data.get("request"))
            return None
        
        task_id = data.get("request")
        log.info("2captcha.v3_task_created", task_id=task_id)
        
        # Poll for solution (same as v2)
        for attempt in range(POLL_MAX_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_SEC)
            
            try:
                r = await client.get(
                    f"{TWOCAPTCHA_BASE}/res.php",
                    params={"key": key, "action": "get", "id": task_id, "json": "1"},
                )
                data = r.json()
            except Exception as exc:
                log.debug("2captcha.v3_poll_fail", attempt=attempt, error=str(exc)[:200])
                continue
            
            if data.get("status") == 1:
                token = data.get("request")
                log.info("2captcha.v3_solved", attempts=attempt + 1)
                return token
            
            if data.get("request") == "CAPCHA_NOT_READY":
                continue
            
            log.warning("2captcha.v3_solve_error", request=data.get("request"))
            return None
        
        log.warning("2captcha.v3_timeout", task_id=task_id)
        return None


async def get_account_balance(api_key: Optional[str] = None) -> Optional[float]:
    """Returns 2Captcha account balance in USD, or None on failure."""
    key = api_key or os.environ.get("TWOCAPTCHA_API_KEY")
    if not key:
        for path in ["~/.secrets/2captcha_api_key.txt", ".secrets/2captcha_api_key.txt"]:
            try:
                with open(os.path.expanduser(path)) as f:
                    key = f.read().strip()
                if key:
                    break
            except Exception:
                pass
    
    if not key:
        return None
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{TWOCAPTCHA_BASE}/res.php",
                params={"key": key, "action": "getbalance", "json": "1"},
            )
            data = r.json()
            
            if data.get("status") == 1:
                balance = data.get("request")
                if balance is not None:
                    return float(balance)
        
        return None
    except Exception:
        return None
