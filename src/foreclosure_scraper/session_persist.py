"""Playwright storage_state session persistence for login-walled sources.

Pattern: a human logs in once → we save the browser state (cookies + localStorage)
→ all future automated runs reuse that session without re-logging in.

This is the compliant operator-lane approach: no automated registration, no
credential stuffing, no ToS violation. The operator hands us a logged-in
session; we just keep it alive.

Login-walled sources covered:
- Anderson SC ACPASS (https://acpass.andersoncountysc.org/courts.htm)
- Forsyth NC Vital Records (https://forsythdeeds.com/vital/login.php)
- SC Neumo/Avenu GRIDS (https://cherokeesc.avenuinsights.com/)
- LiensNC (https://apps.liensnc.com/scr/filing/advancedSearch.html)
- PropWire (https://propwire.com/) — also has DataDome (use with nodriver)

Usage:
  # Operator: log in manually, save the session
  python -m foreclosure_scraper.session_persist save --source forsyth_vital \\
      --url https://forsythdeeds.com/vital/login.php

  # Scraper: load the saved session
  state = await load_storage_state("forsyth_vital")
  async with async_playwright() as p:
      browser = await p.chromium.launch(headless=True)
      context = await browser.new_context(storage_state=state)
      page = await context.new_page()
      await page.goto("https://forsythdeeds.com/vital/...")
      # Already logged in!
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

#: Directory for saved sessions.
SESSION_DIR = Path(
    os.environ.get(
        "SESSION_STATE_DIR",
        str(Path.home() / ".foreclosure_scraper" / "sessions"),
    )
)

#: Session files expire after this many days (re-login needed).
SESSION_MAX_AGE_DAYS = 30


# ---------------------------------------------------------------------------
# Source registry — known login-walled sources
# ---------------------------------------------------------------------------

KNOWN_SOURCES: dict[str, dict[str, str]] = {
    "anderson_acpass": {
        "url": "https://acpass.andersoncountysc.org/courts.htm",
        "login_url": "https://acpass.andersoncountysc.org/login.php",
        "description": "Anderson SC probate index — free account login",
    },
    "forsyth_vital": {
        "url": "https://forsythdeeds.com/vital/login.php",
        "login_url": "https://forsythdeeds.com/vital/login.php",
        "description": "Forsyth NC marriage records — Vital Records login",
    },
    "neumo_grids": {
        "url": "https://cherokeesc.avenuinsights.com/",
        "login_url": "https://cherokeesc.avenuinsights.com/",
        "description": "SC deed search — Neumo/Avenu GRIDS account login",
    },
    "liensnc": {
        "url": "https://apps.liensnc.com/scr/filing/advancedSearch.html",
        "login_url": "https://apps.liensnc.com/scr/filing/login.html",
        "description": "LiensNC lien-agent appointments — owner's login",
    },
    "propwire": {
        "url": "https://propwire.com/",
        "login_url": "https://propwire.com/login",
        "description": "PropWire — DataDome + account login",
    },
}


def session_path(source: str) -> Path:
    """File path for a source's saved session state."""
    return SESSION_DIR / f"{source}.json"


def has_valid_session(source: str) -> bool:
    """Check if a non-expired session state file exists for the source."""
    p = session_path(source)
    if not p.exists():
        return False
    age_days = (time.time() - p.stat().st_mtime) / 86400
    return age_days < SESSION_MAX_AGE_DAYS


async def load_storage_state(source: str) -> dict[str, Any] | None:
    """Load a saved Playwright storage_state for the source.

    Returns the state dict (cookies + origins/origins.localStorage) or None
    if no valid session exists. Pass the result to
    ``browser.new_context(storage_state=state)``.
    """
    p = session_path(source)
    if not has_valid_session(source):
        log.info("session_persist.no_session", source=source)
        return None
    try:
        data = json.loads(p.read_text())
        log.info(
            "session_persist.loaded",
            source=source,
            cookies=len(data.get("cookies", [])),
            origins=len(data.get("origins", [])),
        )
        return data
    except Exception as exc:
        log.warning("session_persist.load_error", source=source, error=str(exc)[:120])
        return None


async def save_storage_state(
    source: str, context: Any
) -> bool:
    """Save a Playwright browser context's state as storage_state.

    After the operator logs in via a Playwright-controlled browser, call this
    with the context to persist cookies + localStorage for future runs.
    """
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    try:
        state = await context.storage_state(path=str(session_path(source)))
        log.info(
            "session_persist.saved",
            source=source,
            cookies=len(state.get("cookies", [])),
            origins=len(state.get("origins", [])),
        )
        return True
    except Exception as exc:
        log.warning("session_persist.save_error", source=source, error=str(exc)[:120])
        return False


# ---------------------------------------------------------------------------
# Interactive login helper — operator opens browser, logs in, we save state
# ---------------------------------------------------------------------------

async def interactive_login(source: str, headless: bool = False) -> bool:
    """Open a browser for the operator to log in manually.

    After the operator closes the page (or presses Enter in the terminal),
    the browser context's state is saved for future automated runs.

    This is the ONLY way credentials enter the system — no passwords are
    stored in code or config. Only the resulting session cookies are saved.
    """
    from playwright.async_api import async_playwright

    info = KNOWN_SOURCES.get(source)
    if not info:
        log.error("session_persist.unknown_source", source=source)
        return False

    url = info["login_url"]
    log.info("session_persist.interactive_start", source=source, url=url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url)

        print(f"\n{'='*60}")
        print(f"Browser opened for: {info['description']}")
        print(f"URL: {url}")
        print(f"Log in with your credentials.")
        print(f"When you're done, come back here and press Enter.")
        print(f"{'='*60}\n")

        # Wait for operator to press Enter
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input, "Press Enter after logging in...")

        # Save the session state
        success = await save_storage_state(source, context)
        await browser.close()
        return success


# ---------------------------------------------------------------------------
# Context factory — for scrapers that need a logged-in Playwright context
# ---------------------------------------------------------------------------

async def create_logged_in_context(
    source: str,
    browser: Any,
    *,
    headless: bool = True,
) -> tuple[Any, bool]:
    """Create a Playwright context pre-loaded with saved session state.

    Returns (context, is_logged_in). If no saved session exists, returns a
    fresh context with is_logged_in=False — the caller should then skip
    the source or prompt the operator to run interactive_login first.

    Usage in a scraper:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context, logged_in = await create_logged_in_context(
                "anderson_acpass", browser
            )
            if not logged_in:
                log.warning("anderson_acpass.no_session")
                return
            page = await context.new_page()
            await page.goto("https://acpass.andersoncountysc.org/courts.htm")
            # Already authenticated!
    """
    state = await load_storage_state(source)
    if state is None:
        context = await browser.new_context()
        return context, False

    context = await browser.new_context(storage_state=state)
    return context, True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="Session state persistence")
    sub = parser.add_subparsers(dest="command")

    save_p = sub.add_parser("save", help="Open browser for interactive login")
    save_p.add_argument("--source", required=True, choices=list(KNOWN_SOURCES))
    save_p.add_argument("--url", help="Override login URL")
    save_p.add_argument("--headless", action="store_true")

    check_p = sub.add_parser("check", help="Check if session exists")
    check_p.add_argument("--source", required=True)

    list_p = sub.add_parser("list", help="List all known sources and their status")

    args = parser.parse_args()

    if args.command == "save":
        asyncio.run(interactive_login(args.source, headless=args.headless))
    elif args.command == "check":
        exists = has_valid_session(args.source)
        age = ""
        p = session_path(args.source)
        if p.exists():
            age_days = (time.time() - p.stat().st_mtime) / 86400
            age = f" ({age_days:.1f} days old)"
        print(f"{args.source}: {'VALID' if exists else 'MISSING/EXPIRED'}{age}")
    elif args.command == "list":
        for src, info in KNOWN_SOURCES.items():
            exists = has_valid_session(src)
            status = "✓ VALID" if exists else "✗ missing"
            print(f"  {src:20s} {status:12s} {info['description']}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
