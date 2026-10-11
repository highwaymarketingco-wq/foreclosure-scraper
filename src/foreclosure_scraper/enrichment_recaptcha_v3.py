"""Free reCAPTCHA token capture — V3 and V2 audio solver integration.

NOTE (2026-10-10 live test): Lexington County (www.lex-co.com/ProbateSearch/estates)
was believed to use reCAPTCHA V3, but live testing revealed it uses reCAPTCHA V2
in explicit render mode (2 iframes, textarea, `render=explicit`). For Lexington,
use `enrichment_recaptcha_audio.solve_recaptcha_v2()` instead.

This module's V3 token capture (`get_recaptcha_v3_token()`) is still valid for
any site that genuinely uses reCAPTCHA V3 (invisible, score-based). The site key
extraction is enhanced to search Angular/React JS bundles for embedded keys,
excluding Google CDN scripts that contain internal Google keys.

For V2 sites, the `solve_recaptcha_v2()` function in `enrichment_recaptcha_audio`
is the correct tool — it uses Playwright to click the checkbox, trigger the
audio challenge, download the audio, transcribe it with faster-whisper, and
submit the text answer.

Usage (V3):
    from foreclosure_scraper.enrichment_recaptcha_v3 import get_recaptcha_v3_token

    token = await get_recaptcha_v3_token(
        url="https://example.com",
        action="search",
    )
    if token:
        # Use the token in the search API request
        headers = {"X-ReCaptcha-Token": token, ...}

Usage (V2 — for Lexington County and similar):
    from playwright.async_api import async_playwright
    from foreclosure_scraper.enrichment_recaptcha_audio import solve_recaptcha_v2

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.lex-co.com/ProbateSearch/estates")
        solved = await solve_recaptcha_v2(page)
        if solved:
            # reCAPTCHA cleared — proceed with the page
            ...
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Token cache with freshness (TTL) management
# ---------------------------------------------------------------------------

#: Maximum age (in seconds) of a cached reCAPTCHA V3 token before it must be
#: refreshed. reCAPTCHA V3 tokens have a ~120s TTL on Google's side; we use
#: 90s to leave a safety margin so the token is still valid when the consuming
#: API receives it.
_TOKEN_TTL_S = int(os.environ.get("RECAPTCHA_V3_TOKEN_TTL_S", "90"))

#: Cached token and its capture timestamp.
_cached_token: Optional[str] = None
_cached_token_ts: float = 0.0
_cached_token_url: Optional[str] = None
_cached_token_action: Optional[str] = None
_token_lock = asyncio.Lock()


def _is_token_fresh(
    url: str | None = None,
    action: str | None = None,
) -> bool:
    """Return True if the cached token is still fresh and matches the params.

    A token is fresh if:
    - It exists (non-None)
    - Its age is less than ``_TOKEN_TTL_S``
    - It was captured for the same URL and action (different pages may use
      different site keys, so a token from one page won't work on another)
    """
    global _cached_token, _cached_token_ts, _cached_token_url, _cached_token_action
    if _cached_token is None:
        return False
    age = time.monotonic() - _cached_token_ts
    if age >= _TOKEN_TTL_S:
        return False
    if url is not None and _cached_token_url is not None and url != _cached_token_url:
        return False
    if action is not None and _cached_token_action is not None and action != _cached_token_action:
        return False
    return True


async def get_cached_recaptcha_v3_token(
    url: str = "https://www.lex-co.com/ProbateSearch/estates",
    action: str = "search",
    site_key: Optional[str] = None,
    headless: bool = True,
    timeout_ms: int = 30000,
) -> Optional[str]:
    """Return a fresh reCAPTCHA V3 token, refreshing the cache if stale.

    If a previously captured token is still fresh (< 90s old) and was captured
    for the same URL and action, it is returned immediately without launching
    a browser. Otherwise, a new token is captured via :func:`get_recaptcha_v3_token`
    and cached.

    Args:
        url: The page URL that loads reCAPTCHA V3.
        action: The reCAPTCHA action string.
        site_key: The reCAPTCHA site key. If None, extracted from the page.
        headless: Whether to run the browser headless.
        timeout_ms: Total timeout for the operation.

    Returns:
        The reCAPTCHA V3 token string, or None if capture failed.
    """
    global _cached_token, _cached_token_ts, _cached_token_url, _cached_token_action

    # Fast path: return cached token if still fresh.
    if _is_token_fresh(url=url, action=action):
        log.info("recaptcha_v3.token_cache_hit", age_s=round(time.monotonic() - _cached_token_ts, 1))
        return _cached_token

    async with _token_lock:
        # Double-check after acquiring the lock — another task may have
        # refreshed the token while we were waiting.
        if _is_token_fresh(url=url, action=action):
            log.info("recaptcha_v3.token_cache_hit_after_lock")
            return _cached_token

        log.info("recaptcha_v3.token_cache_miss_refreshing", url=url[:80], action=action)
        token = await get_recaptcha_v3_token(
            url=url,
            action=action,
            site_key=site_key,
            headless=headless,
            timeout_ms=timeout_ms,
        )
        if token:
            _cached_token = token
            _cached_token_ts = time.monotonic()
            _cached_token_url = url
            _cached_token_action = action
            log.info("recaptcha_v3.token_cached", ttl_s=_TOKEN_TTL_S)
        return token


def invalidate_cached_recaptcha_v3_token() -> None:
    """Clear the cached reCAPTCHA V3 token.

    Call this if the token was rejected by the API (e.g. 400/403 response)
    so the next call to :func:`get_cached_recaptcha_v3_token` captures a
    fresh token.
    """
    global _cached_token, _cached_token_ts, _cached_token_url, _cached_token_action
    _cached_token = None
    _cached_token_ts = 0.0
    _cached_token_url = None
    _cached_token_action = None
    log.info("recaptcha_v3.token_cache_invalidated")


# ---------------------------------------------------------------------------
# Site key extraction — find the reCAPTCHA site key from the rendered page
# ---------------------------------------------------------------------------

#: Regex to find the reCAPTCHA site key in script tags or data attributes.
_SITE_KEY_RE = re.compile(
    r'(?:data-sitekey|grecaptcha\.render|sitekey)["\']?\s*[:=,]\s*'
    r'["\']([0-9A-Za-z_-]{40})["\']',
    re.IGNORECASE,
)

#: JS that extracts the site key from the page at runtime.
_EXTRACT_SITE_KEY_JS = """
(() => {
    // Method 1: Search for grecaptcha.render() calls in inline scripts
    const scripts = document.querySelectorAll('script');
    for (const s of scripts) {
        const text = s.textContent || '';
        const m = text.match(/(?:sitekey|site_key|data-sitekey)['"]?\\s*[:=,]\\s*['"]([0-9A-Za-z_-]{40})['"]/i);
        if (m) return m[1];
    }

    // Method 2: Search data attributes on .g-recaptcha elements
    const el = document.querySelector('.g-recaptcha[data-sitekey]');
    if (el) return el.getAttribute('data-sitekey');

    // Method 3: Search all elements with data-sitekey
    const els = document.querySelectorAll('[data-sitekey]');
    if (els.length > 0) return els[0].getAttribute('data-sitekey');

    // Method 4: Search the page source for the render key
    const html = document.documentElement.innerHTML;
    const m2 = html.match(/['"]?sitekey['"]?\\s*[:=,]\\s*['"]([0-9A-Za-z_-]{40})['"]/i);
    if (m2) return m2[1];

    // Method 5: Check window.___grecaptcha_cfg
    try {
        if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
            const clients = window.___grecaptcha_cfg.clients;
            for (const cid of Object.keys(clients)) {
                const client = clients[cid];
                // Walk the client object tree to find the site key
                const found = JSON.stringify(client).match(/[0-9A-Za-z_-]{40}/);
                if (found) return found[0];
            }
        }
    } catch(e) {}

    return null;
})()
"""

#: JS that fetches same-origin script bundles and searches for site keys.
#: Excludes Google/gstatic CDN scripts (they contain Google's internal keys).
_SEARCH_BUNDLES_JS = """
(async () => {
    // Find all script[src] tags, fetch each, search for reCAPTCHA site key
    // Only search same-origin scripts — Google CDN scripts contain internal keys
    const scripts = Array.from(document.querySelectorAll('script[src]'));
    for (const s of scripts) {
        // Skip Google CDN scripts — they contain Google's own keys, not site keys
        if (s.src.includes('google.com') || s.src.includes('gstatic.com')) continue;
        try {
            const resp = await fetch(s.src);
            const text = await resp.text();
            // reCAPTCHA site keys start with 6L and are 40 chars
            const m = text.match(/6L[0-9A-Za-z_-]{38}/);
            if (m) return m[0];
        } catch(e) {}
    }
    return null;
})()
"""


# ---------------------------------------------------------------------------
# Token capture — execute grecaptcha.execute() in a real browser
# ---------------------------------------------------------------------------

#: JS that calls grecaptcha.execute() to get a V3 token.
_EXECUTE_RECAPTCHA_JS = """
async (args) => {
    const siteKey = args.siteKey;
    const action = args.action;
    // Wait for grecaptcha to be ready
    if (typeof grecaptcha === 'undefined') {
        return {err: 'grecaptcha not loaded'};
    }

    // grecaptcha.ready() takes a callback in some versions, returns Promise in others.
    // Wrap it to handle both cases.
    try {
        if (typeof grecaptcha.ready === 'function') {
            await new Promise((resolve) => {
                try {
                    const r = grecaptcha.ready(resolve);
                    if (r && typeof r.then === 'function') r.then(resolve, resolve);
                } catch(e) { resolve(); }
            });
        }
    } catch(e) {
        // ready() might not work but execute() may still be available
    }

    if (typeof grecaptcha.execute !== 'function') {
        return {err: 'grecaptcha.execute is not a function'};
    }

    try {
        const token = await grecaptcha.execute(siteKey, {action: action});
        if (token && typeof token === 'string' && token.length > 20) {
            return {token: token};
        }
        return {err: 'empty or short token: ' + String(token).slice(0, 30)};
    } catch(e) {
        return {err: 'grecaptcha.execute() failed: ' + String(e)};
    }
}
"""


async def get_recaptcha_v3_token(
    url: str = "https://www.lex-co.com/ProbateSearch/estates",
    action: str = "search",
    site_key: Optional[str] = None,
    headless: bool = True,
    timeout_ms: int = 30000,
) -> Optional[str]:
    """Render a page with reCAPTCHA V3 and capture the verification token.

    Args:
        url: The page URL that loads reCAPTCHA V3.
        action: The reCAPTCHA action string (must match what the site expects,
            usually "search", "submit", "login", etc.).
        site_key: The reCAPTCHA site key. If None, extracted from the page.
        headless: Whether to run the browser headless.
        timeout_ms: Total timeout for the operation.

    Returns:
        The reCAPTCHA V3 token string, or None if capture failed.
        The token is short-lived (~2 min TTL) — use it immediately.
    """
    from playwright.async_api import async_playwright

    log.info("recaptcha_v3.start", url=url, action=action,
             site_key_provided=site_key is not None)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-web-security",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        page = await context.new_page()

        try:
            # Step 1: Navigate to the page.
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            log.info("recaptcha_v3.page_loaded")

            # Step 2: Simulate human interaction to improve the V3 score.
            await _simulate_human(page)

            # Step 3: Extract the site key if not provided.
            if site_key is None:
                site_key = await page.evaluate(_EXTRACT_SITE_KEY_JS)
                if not site_key:
                    # Fallback: search JS bundles for reCAPTCHA site key
                    # (Angular/React SPAs often embed the key in compiled JS)
                    log.info("recaptcha_v3.searching_bundles")
                    site_key = await page.evaluate(_SEARCH_BUNDLES_JS)
                if not site_key:
                    log.warning("recaptcha_v3.no_site_key")
                    await browser.close()
                    return None
                log.info("recaptcha_v3.site_key_found",
                         key_prefix=site_key[:12] + "...")

            # Step 4: Wait for grecaptcha to be ready.
            try:
                await page.wait_for_function(
                    "typeof grecaptcha !== 'undefined' && typeof grecaptcha.execute === 'function'",
                    timeout=15000,
                )
            except Exception:
                log.warning("recaptcha_v3.grecaptcha_not_ready")
                await browser.close()
                return None

            # Step 5: Execute grecaptcha.execute() to get the token.
            result = await page.evaluate(
                _EXECUTE_RECAPTCHA_JS, {"siteKey": site_key, "action": action}
            )

            if isinstance(result, dict) and result.get("token"):
                token = result["token"]
                log.info("recaptcha_v3.token_captured",
                         token_len=len(token),
                         token_prefix=token[:20] + "...")
                return token
            else:
                err = (result or {}).get("err", "unknown") if isinstance(result, dict) else str(result)
                log.warning("recaptcha_v3.token_failed", error=err)
                return None

        except Exception as exc:
            log.warning("recaptcha_v3.error", error=str(exc)[:160])
            return None
        finally:
            await browser.close()


async def _simulate_human(page) -> None:
    """Simulate human-like interaction to improve the reCAPTCHA V3 score.

    reCAPTCHA V3 scores sessions based on interaction patterns. A page that
    loads and immediately calls execute() with no interaction scores low.
    Mouse movement, scrolling, and a short delay all help.
    """
    import random

    # Random mouse movements
    for _ in range(random.randint(3, 5)):
        x = random.randint(100, 1500)
        y = random.randint(100, 800)
        await page.mouse.move(x, y, steps=random.randint(5, 15))
        await asyncio.sleep(random.uniform(0.1, 0.3))

    # Scroll down and up
    await page.evaluate("window.scrollBy(0, 300)")
    await asyncio.sleep(0.5)
    await page.evaluate("window.scrollBy(0, -100)")
    await asyncio.sleep(random.uniform(0.5, 1.5))

    # Click somewhere innocuous (not a button/link)
    await page.mouse.click(400, 300)
    await asyncio.sleep(random.uniform(0.3, 0.8))


# ---------------------------------------------------------------------------
# High-level helper — get token and make a search request
# ---------------------------------------------------------------------------

async def search_with_recaptcha_v3(
    url: str,
    api_url: str,
    search_payload: dict,
    action: str = "search",
    token_header: str = "X-ReCaptcha-Token",
    site_key: Optional[str] = None,
) -> Optional[dict]:
    """Capture a V3 token and immediately use it for an API search.

    Args:
        url: The page URL that loads reCAPTCHA V3.
        api_url: The backend API URL to call with the token.
        search_payload: The JSON body for the search request.
        action: The reCAPTCHA action string.
        token_header: The HTTP header name to carry the token.
        site_key: Optional pre-known site key.

    Returns:
        The JSON response from the API, or None on failure.
    """
    import httpx

    # Use the cached token function so we get a fresh token if the cached
    # one is older than 90s.
    token = await get_cached_recaptcha_v3_token(url=url, action=action, site_key=site_key)
    if not token:
        log.warning("recaptcha_v3_search.no_token")
        return None

    headers = {
        "Content-Type": "application/json",
        token_header: token,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(api_url, json=search_payload, headers=headers)
            # If the token was rejected, invalidate the cache so the next
            # call captures a fresh one.
            if r.status_code in (400, 403):
                log.warning("recaptcha_v3_search.token_rejected", status=r.status_code)
                invalidate_cached_recaptcha_v3_token()
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        log.warning("recaptcha_v3_search.api_failed", error=str(exc)[:160])
        return None


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

async def _self_test():
    """Verify imports and function signatures."""
    import inspect
    print("reCAPTCHA V3 token capture self-test")
    print(f"  get_recaptcha_v3_token:      {'async' if inspect.iscoroutinefunction(get_recaptcha_v3_token) else 'SYNC'}")
    print(f"  get_cached_recaptcha_v3_token: {'async' if inspect.iscoroutinefunction(get_cached_recaptcha_v3_token) else 'SYNC'}")
    print(f"  search_with_recaptcha_v3:    {'async' if inspect.iscoroutinefunction(search_with_recaptcha_v3) else 'SYNC'}")
    print(f"  _simulate_human:             {'async' if inspect.iscoroutinefunction(_simulate_human) else 'SYNC'}")
    print(f"  _is_token_fresh:             {'async' if inspect.iscoroutinefunction(_is_token_fresh) else 'SYNC'}")
    print(f"  invalidate_cached_recaptcha_v3_token: {'async' if inspect.iscoroutinefunction(invalidate_cached_recaptcha_v3_token) else 'SYNC'}")
    print(f"  _TOKEN_TTL_S:                {_TOKEN_TTL_S}s")
    print(f"  _SITE_KEY_RE:                {len(_SITE_KEY_RE.pattern)} chars")
    print(f"  _EXTRACT_SITE_KEY_JS:        {len(_EXTRACT_SITE_KEY_JS)} chars")
    print(f"  _EXECUTE_RECAPTCHA_JS:       {len(_EXECUTE_RECAPTCHA_JS)} chars")

    # Test the regex
    test_html = 'grecaptcha.render(container, {sitekey: "6Lc_abcdefghijklmnopqrstuvwxyz0123456789"})'
    m = _SITE_KEY_RE.search(test_html)
    assert m, "regex should match"
    print(f"  regex test:                  OK (matched {m.group(1)[:16]}...)")

    # Test token freshness logic
    global _cached_token, _cached_token_ts, _cached_token_url, _cached_token_action
    _cached_token = "fake_token"
    _cached_token_ts = time.monotonic()
    _cached_token_url = "https://example.com"
    _cached_token_action = "search"
    assert _is_token_fresh(url="https://example.com", action="search"), "fresh token should return True"
    assert not _is_token_fresh(url="https://other.com", action="search"), "different URL should return False"
    assert not _is_token_fresh(url="https://example.com", action="login"), "different action should return False"
    # Simulate expired token.
    _cached_token_ts = time.monotonic() - _TOKEN_TTL_S - 1
    assert not _is_token_fresh(url="https://example.com", action="search"), "expired token should return False"
    invalidate_cached_recaptcha_v3_token()
    assert _cached_token is None, "invalidate should clear the token"
    print("  token freshness:             OK")

    print("  All tests passed.")


if __name__ == "__main__":
    asyncio.run(_self_test())
