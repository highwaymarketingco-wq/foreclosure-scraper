"""Tyler eCourts WAF Session Capture Tool

When nc_ecourts_estates successfully bypasses the AWS WAF (the "lucky working moment"),
this tool captures everything about that successful session for later comparison:

- Browser fingerprint (user-agent, viewport, headers)
- Network timing (request/response timings for the initial page load)
- Cookies (all cookies, especially aws-waf-token)
- Request headers sent to Tyler
- WAF challenge response (if any)
- Success indicators (what proved it worked)

Usage:
  TYLER_CAPTURE_SESSION=1 python -m foreclosure_scraper run counties_nc.nc_ecourts_estates

When enabled, runs the normal scraper but logs comprehensive session details to:
  ~/.foreclosure_scraper/tyler_sessions/success_TIMESTAMP.json

Compare successful vs failed sessions to find patterns that correlate with bypassing WAF.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

CAPTURE_DIR = Path.home() / ".foreclosure_scraper" / "tyler_sessions"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


def is_capture_enabled() -> bool:
    """Check if Tyler session capture is enabled via env var."""
    return os.environ.get("TYLER_CAPTURE_SESSION", "").lower() in ("1", "true", "yes")


class TylerSessionCapture:
    """Captures comprehensive session details for Tyler WAF debugging."""

    def __init__(self):
        self.enabled = is_capture_enabled()
        self.data: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "unix_timestamp": time.time(),
            "success": None,  # Set to True/False when outcome known
            "rows_fetched": 0,
            "browser": {},
            "network": {},
            "cookies": [],
            "headers": {},
            "waf_events": [],
            "timing": {},
        }
        self.start_time = time.time()

    def log_browser_launch(self, headless: bool, user_agent: str, viewport: dict):
        """Log browser configuration."""
        if not self.enabled:
            return
        self.data["browser"] = {
            "headless": headless,
            "user_agent": user_agent,
            "viewport": viewport,
            "launch_timestamp": time.time(),
        }
        log.info("tyler_capture.browser_launch", **self.data["browser"])

    def log_pretoken(self, token: str | None, solved: bool):
        """Log AWS WAF pretoken attempt."""
        if not self.enabled:
            return
        self.data["waf_events"].append({
            "event": "pretoken_attempt",
            "timestamp": time.time(),
            "solved": solved,
            "token_present": token is not None,
            "token_length": len(token) if token else 0,
        })
        log.info("tyler_capture.pretoken", solved=solved, has_token=token is not None)

    def log_page_load(self, url: str, status: int, timing_ms: float):
        """Log initial page load."""
        if not self.enabled:
            return
        self.data["network"]["initial_load"] = {
            "url": url,
            "status": status,
            "timing_ms": timing_ms,
            "timestamp": time.time(),
        }
        log.info("tyler_capture.page_load", url=url, status=status, timing_ms=timing_ms)

    def log_waf_challenge(self, challenge_type: str, solved: bool, elapsed_s: float):
        """Log WAF challenge encounter."""
        if not self.enabled:
            return
        self.data["waf_events"].append({
            "event": "challenge",
            "type": challenge_type,
            "solved": solved,
            "elapsed_s": elapsed_s,
            "timestamp": time.time(),
        })
        log.info("tyler_capture.waf_challenge", type=challenge_type, solved=solved, elapsed_s=elapsed_s)

    def log_cookies(self, cookies: list[dict]):
        """Log all cookies after successful page load."""
        if not self.enabled:
            return
        self.data["cookies"] = [
            {
                "name": c.get("name"),
                "value": c.get("value")[:50] + "..." if len(c.get("value", "")) > 50 else c.get("value"),
                "domain": c.get("domain"),
                "secure": c.get("secure"),
                "httpOnly": c.get("httpOnly"),
            }
            for c in cookies
        ]
        # Log aws-waf-token specifically
        waf_cookie = next((c for c in cookies if c.get("name") == "aws-waf-token"), None)
        if waf_cookie:
            log.info("tyler_capture.waf_cookie_present", value_length=len(waf_cookie.get("value", "")))

    def log_request_headers(self, headers: dict):
        """Log request headers sent to Tyler."""
        if not self.enabled:
            return
        self.data["headers"] = dict(headers)
        log.info("tyler_capture.request_headers", header_count=len(headers))

    def log_outcome(self, success: bool, rows_fetched: int, error: str | None = None):
        """Log final outcome (success or failure)."""
        if not self.enabled:
            return
        elapsed = time.time() - self.start_time
        self.data["success"] = success
        self.data["rows_fetched"] = rows_fetched
        self.data["timing"]["total_elapsed_s"] = elapsed
        if error:
            self.data["error"] = error

        # Save to file
        outcome = "success" if success else "failure"
        filename = f"{outcome}_{int(time.time())}.json"
        filepath = CAPTURE_DIR / filename

        with open(filepath, "w") as f:
            json.dump(self.data, f, indent=2)

        log.info(
            "tyler_capture.saved",
            filepath=str(filepath),
            success=success,
            rows=rows_fetched,
            elapsed_s=round(elapsed, 1),
        )

    def add_note(self, key: str, value: Any):
        """Add arbitrary debug note."""
        if not self.enabled:
            return
        if "notes" not in self.data:
            self.data["notes"] = {}
        self.data["notes"][key] = value


# Global singleton for easy access
_capture_instance: TylerSessionCapture | None = None


def get_capture() -> TylerSessionCapture:
    """Get or create the global capture instance."""
    global _capture_instance
    if _capture_instance is None:
        _capture_instance = TylerSessionCapture()
    return _capture_instance
