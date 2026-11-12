"""CapSolver AWS WAF challenge solver.

CapSolver (capsolver.com) is a paid CAPTCHA-solving service. Their
AntiAwsWafTaskProxyLess endpoint takes a target URL, runs the AWS WAF
JavaScript challenge on their backend infrastructure, and returns an
`aws-waf-token` cookie value that bypasses the challenge for ~1 hour.

Pricing (2026-05): $0.001 per solve. Our Tyler workflow needs ~50
solves/run × 4 runs/week ≈ 200 solves/week ≈ $0.20/week. A $5 deposit
lasts roughly 6 months at our volume.

Reads CAPSOLVER_API_KEY from env. Returns None when unset (caller
should fall back gracefully).

Usage:
    from .enrichment_capsolver import solve_aws_waf
    token = await solve_aws_waf("https://target.com/")
    if token:
        # Inject as cookie via Playwright:
        # await page.context.add_cookies([{
        #     "name": "aws-waf-token", "value": token,
        #     "domain": ".target.com", "path": "/",
        # }])
        ...
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx
import structlog

log = structlog.get_logger()

CAPSOLVER_BASE = "https://api.capsolver.com"
# Polling parameters: AWS WAF solves typically resolve in 5-20s; we
# poll every 2s for up to 90s before giving up.
POLL_INTERVAL_SEC = 2.0
POLL_MAX_ATTEMPTS = 45


async def solve_aws_waf(
    website_url: str,
    api_key: Optional[str] = None,
    timeout: float = 120.0,
) -> Optional[str]:
    """Solve an AWS WAF challenge for `website_url` and return the
    aws-waf-token cookie value. Returns None on failure / no creds.

    Logs every step so the orchestrator can surface CapSolver behavior
    in run_health.json.
    """
    key = api_key or os.environ.get("CAPSOLVER_API_KEY")
    if not key:
        log.info("capsolver.no_api_key")
        return None

    async with httpx.AsyncClient(timeout=timeout) as client:
        # Step 1: Create task
        try:
            r = await client.post(
                f"{CAPSOLVER_BASE}/createTask",
                json={
                    "clientKey": key,
                    "task": {
                        "type": "AntiAwsWafTaskProxyLess",
                        "websiteURL": website_url,
                    },
                },
            )
        except Exception as exc:
            log.warning("capsolver.create_task_fail", error=str(exc)[:200])
            return None

        try:
            data = r.json()
        except Exception:
            log.warning("capsolver.create_task_bad_json", status=r.status_code)
            return None

        if data.get("errorId", 0) != 0:
            log.warning(
                "capsolver.create_task_error",
                error_code=data.get("errorCode"),
                error_desc=str(data.get("errorDescription"))[:200],
            )
            return None

        task_id = data.get("taskId")
        if not task_id:
            log.warning("capsolver.no_task_id")
            return None

        log.info("capsolver.task_created", task_id=task_id, url=website_url[:120])

        # Step 2: Poll for solution
        for attempt in range(POLL_MAX_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_SEC)
            try:
                r = await client.post(
                    f"{CAPSOLVER_BASE}/getTaskResult",
                    json={"clientKey": key, "taskId": task_id},
                )
                data = r.json()
            except Exception as exc:
                log.debug("capsolver.poll_fail", attempt=attempt, error=str(exc)[:200])
                continue

            status = data.get("status")
            if status == "ready":
                solution = data.get("solution") or {}
                token = solution.get("cookie") or solution.get("token")
                if not token:
                    log.warning("capsolver.solution_missing_token", solution_keys=list(solution.keys()))
                    return None
                log.info(
                    "capsolver.solved",
                    attempts=attempt + 1,
                    elapsed_sec=round((attempt + 1) * POLL_INTERVAL_SEC, 1),
                )
                return token
            if data.get("errorId", 0) != 0:
                log.warning(
                    "capsolver.solve_error",
                    error_code=data.get("errorCode"),
                    error_desc=str(data.get("errorDescription"))[:200],
                )
                return None
            # status == 'processing', keep polling

        log.warning(
            "capsolver.timeout",
            task_id=task_id,
            attempts=POLL_MAX_ATTEMPTS,
            total_sec=POLL_MAX_ATTEMPTS * POLL_INTERVAL_SEC,
        )
        return None


async def get_account_balance() -> Optional[float]:
    """Returns CapSolver account balance in USD, or None on failure.
    Used for visibility in run_health and to warn when balance is low."""
    key = os.environ.get("CAPSOLVER_API_KEY")
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{CAPSOLVER_BASE}/getBalance",
                json={"clientKey": key},
            )
            data = r.json()
            if data.get("errorId", 0) != 0:
                return None
            return float(data.get("balance", 0))
    except Exception:
        return None
