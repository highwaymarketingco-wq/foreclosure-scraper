"""Free wall-bypass fetch tiers — pydoll (Turnstile) + nodriver (DataDome/hard CF).

These sit ABOVE the curl-cffi impersonation tier in http_client.get_text's
escalation chain. They launch real browser processes, so they are slower
(~5-15s) and are only invoked when every cheaper tier has failed.

Tier order in the full chain:
  1. plain httpx (http_client.get_text)
  2. curl subprocess fallback (http_client._curl_fallback_text)
  3. curl-cffi Chrome impersonation (http_client.get_text_impersonate)
  4. StealthyFetcher / camoufox (render.fetch_rendered) — JS rendering
  5. pydoll (this module) — Cloudflare Turnstile + JS challenges
  6. nodriver (this module) — DataDome + harder anti-bot

All tiers are FREE — no paid CAPTCHA solving service is used. pydoll has
built-in Cloudflare Turnstile bypass via CDP; nodriver is undetected Chrome
that defeats DataDome and similar fingerprinting systems.

Each function returns rendered page text (visible text preferred, HTML
fallback) or "" on failure — matching the render.fetch_rendered contract.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import structlog

log = structlog.get_logger()

# Concurrency: real browsers are heavy. One at a time by default.
_PYDOLL_SEM: Optional[asyncio.Semaphore] = None
_NODRIVER_SEM: Optional[asyncio.Semaphore] = None

_PYDOLL_TIMEOUT_S = int(os.environ.get("PYDOLL_TIMEOUT_S", "30"))
_NODRIVER_TIMEOUT_S = int(os.environ.get("NODRIVER_TIMEOUT_S", "30"))
# DataDome requires non-headless to pass the JS challenge — headless is detected.
# pydoll handles Turnstile fine headless, so it stays headless by default.
# Override with env vars: WALL_BYPASS_HEADLESS=0 to force headless off for both.
_PYDOLL_HEADLESS = os.environ.get("WALL_BYPASS_HEADLESS", "1") != "0"
_NODRIVER_HEADLESS = os.environ.get("WALL_BYPASS_HEADLESS", "0") != "0"


def _pydoll_sem() -> asyncio.Semaphore:
    global _PYDOLL_SEM
    if _PYDOLL_SEM is None:
        _PYDOLL_SEM = asyncio.Semaphore(1)
    return _PYDOLL_SEM


def _nodriver_sem() -> asyncio.Semaphore:
    global _NODRIVER_SEM
    if _NODRIVER_SEM is None:
        _NODRIVER_SEM = asyncio.Semaphore(1)
    return _NODRIVER_SEM


# ---------------------------------------------------------------------------
# pydoll — Cloudflare Turnstile + JS challenges
# ---------------------------------------------------------------------------

async def fetch_with_pydoll(
    url: str,
    *,
    timeout_s: int = _PYDOLL_TIMEOUT_S,
    wait_for_selector: str | None = None,
) -> str:
    """Fetch a URL with pydoll's undetected Chrome, auto-solving Cloudflare
    Turnstile challenges.

    pydoll uses CDP (Chrome DevTools Protocol) directly — no Selenium/WebDriver
    fingerprint. Its ``enable_auto_solve_cloudflare_captcha`` detects and clicks
    Turnstile checkboxes automatically.

    Returns rendered page text, or "" on failure.
    """
    async with _pydoll_sem():
        return await asyncio.wait_for(
            _pydoll_fetch(url, timeout_s, wait_for_selector),
            timeout=timeout_s + 20,  # hard outer bound
        )


def _find_chrome_binary() -> str | None:
    """Find Chrome/Chromium binary on macOS/Linux."""
    import shutil
    # Explicit env override.
    env_path = os.environ.get("CHROME_BINARY")
    if env_path and os.path.isfile(env_path):
        return env_path
    # Common macOS paths
    mac_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for p in mac_paths:
        if os.path.exists(p):
            return p
    # Linux — snap first (Ubuntu VM), then system PATH.
    linux_paths = ["/snap/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"]
    for p in linux_paths:
        if os.path.exists(p):
            return p
    return shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium")


async def _pydoll_fetch(
    url: str, timeout_s: int, wait_for_selector: str | None
) -> str:
    try:
        from pydoll.browser.chromium import Chrome
        from pydoll.browser.options import ChromiumOptions
    except ImportError:
        log.warning("wall_bypass.pydoll_not_installed")
        return ""

    browser = None
    try:
        opts = ChromiumOptions()
        opts.headless = _PYDOLL_HEADLESS
        chrome_bin = _find_chrome_binary()
        if chrome_bin:
            opts.binary_location = chrome_bin
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-gpu")

        browser = Chrome(options=opts)
        await browser.__aenter__()
        # __aenter__ doesn't auto-start; we must call start() explicitly.
        initial_tab = await browser.start()
        tab = await browser.new_tab(url)
        # Enable auto-solve for any Cloudflare challenge that appears.
        await tab.enable_auto_solve_cloudflare_captcha(
            time_to_wait_captcha=10.0,
        )
        # Navigate (new_tab may not wait for full load).
        await tab.go_to(url, timeout=timeout_s)

        # If caller wants to wait for a specific element, poll for it.
        if wait_for_selector:
            deadline = asyncio.get_event_loop().time() + timeout_s
            while asyncio.get_event_loop().time() < deadline:
                try:
                    el = await tab.find(
                        class_name=wait_for_selector, timeout=2, raise_exc=False
                    )
                    if el:
                        break
                except Exception:
                    pass
                await asyncio.sleep(1)

        # Give Cloudflare a moment to clear if it's still processing.
        await asyncio.sleep(2)

        # Get page source — page_source is a coroutine property.
        try:
            html = await tab.page_source
        except Exception:
            # Fallback: execute JS to get document content
            try:
                result = await tab.execute_script(
                    "document.documentElement.outerHTML"
                )
                html = (
                    result.get("result", {}).get("value", "")
                    if isinstance(result, dict)
                    else str(result)
                )
            except Exception:
                html = ""

        if not html:
            return ""

        # Extract visible text from HTML.
        return _html_to_text(html)

    except asyncio.TimeoutError:
        log.warning("wall_bypass.pydoll_timeout", url=url[:120])
        return ""
    except Exception as exc:
        log.debug(
            "wall_bypass.pydoll_error",
            url=url[:120],
            error=f"{type(exc).__name__}: {exc}"[:200],
        )
        return ""
    finally:
        # Ensure the browser process is always cleaned up, even on
        # CancelledError from asyncio.wait_for — the async with context
        # manager's __aexit__ may not complete if the task is cancelled.
        if browser is not None:
            try:
                await browser.__aexit__(None, None, None)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# nodriver — DataDome + harder anti-bot
# ---------------------------------------------------------------------------

async def fetch_with_nodriver(
    url: str,
    *,
    timeout_s: int = _NODRIVER_TIMEOUT_S,
    wait_for_text: str | None = None,
) -> str:
    """Fetch a URL with nodriver (undetected Chrome).

    nodriver is designed to evade DataDome, PerimeterX, and similar
    fingerprinting anti-bot systems that go beyond Cloudflare. It uses
    CDP directly and patches Chrome's automation fingerprints.

    Returns rendered page text, or "" on failure.
    """
    async with _nodriver_sem():
        return await asyncio.wait_for(
            _nodriver_fetch(url, timeout_s, wait_for_text),
            timeout=timeout_s + 20,
        )


async def _nodriver_fetch(
    url: str, timeout_s: int, wait_for_text: str | None
) -> str:
    from foreclosure_scraper.browser_utils import start_browser

    browser = None
    try:
        browser = await start_browser(
            headless=_NODRIVER_HEADLESS,
            browser_args=[
                "--no-sandbox",
                "--disable-gpu",
                "--window-size=1920,1080",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        tab = await browser.get(url)

        # Wait for page to settle.
        await tab.wait(3)

        # If waiting for specific text, poll for it.
        if wait_for_text:
            deadline = asyncio.get_event_loop().time() + timeout_s
            while asyncio.get_event_loop().time() < deadline:
                try:
                    content = await tab.get_content()
                    if wait_for_text.lower() in content.lower():
                        break
                except Exception:
                    pass
                await asyncio.sleep(2)

        # Get page content.
        try:
            html = await tab.get_content()
        except Exception:
            try:
                html = await tab.evaluate(
                    "document.documentElement.outerHTML",
                    return_by_value=True,
                )
                if isinstance(html, str):
                    pass
                else:
                    html = str(html)
            except Exception:
                html = ""

        if not html:
            return ""

        return _html_to_text(html)

    except asyncio.TimeoutError:
        log.warning("wall_bypass.nodriver_timeout", url=url[:120])
        return ""
    except Exception as exc:
        log.debug(
            "wall_bypass.nodriver_error",
            url=url[:120],
            error=f"{type(exc).__name__}: {exc}"[:200],
        )
        return ""
    finally:
        if browser is not None:
            try:
                browser.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Escalation helper — try render → pydoll → nodriver
# ---------------------------------------------------------------------------

async def fetch_through_walls(
    url: str,
    *,
    render_first: bool = True,
    timeout_s: int = 30,
) -> str:
    """Try every wall-bypass tier in order until one returns non-empty text.

    Order: StealthyFetcher (render) → pydoll (Turnstile) → nodriver (DataDome).

    Use this when a URL is known to be walled but you don't know which wall
    type it uses. Returns "" if all tiers fail.
    """
    # Tier 1: StealthyFetcher (camoufox) — cheapest real-browser option.
    if render_first:
        try:
            from .render import fetch_rendered
            text = await fetch_rendered(url)
            if text and len(text) > 100:
                return text
        except Exception:
            pass

    # Tier 2: pydoll (Turnstile + Cloudflare JS challenge).
    text = await fetch_with_pydoll(url, timeout_s=timeout_s)
    if text and len(text) > 100:
        return text

    # Tier 3: nodriver (DataDome + harder cases).
    text = await fetch_with_nodriver(url, timeout_s=timeout_s)
    if text:
        return text

    return ""


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _html_to_text(html: str) -> str:
    """Quick HTML → visible text extraction (no BS4 dependency needed).

    Strips script/style tags and HTML entities, collapses whitespace.
    Not as precise as BS4 but sufficient for scraper regex matching.
    """
    import re
    # Remove script and style blocks.
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all tags.
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode common HTML entities.
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    text = text.replace("&#39;", "'").replace("&#x27;", "'")
    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text).strip()
    return text
