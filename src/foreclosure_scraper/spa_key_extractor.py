"""Dynamic SPA security-key extraction — replaces stale hardcoded keys.

Several SC state sites (DEW lien registry, DOR delinquent taxpayers) are
single-page apps that embed a security key in their JS bundle. The key is
public (every browser sends it) but it ROTATES when the site redeploys.
Hardcoding it means the scraper breaks silently when DEW pushes a new bundle.

This module renders the SPA via StealthyFetcher (real camoufox browser) and
extracts the current key from the live page context, so the scraper self-heals
whenever the key changes.

Supported sites:
  - SC DEW Lien Registry (uitax.dew.sc.gov/LienRegistry/)
    Key lives in the Angular app's main bundle as a constant or in a
    global config object. We search window.* and the app's injector tree.

Usage:
    from foreclosure_scraper.spa_key_extractor import extract_dew_security_key

    key = await extract_dew_security_key()
    if key:
        # Use key for direct HTTP API calls
        headers = {"SecurityKey": key, ...}
    else:
        # Fallback: render and do in-page fetch() (key auto-injected)
        ...
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Key extraction strategies — tried in order within the rendered page
# ---------------------------------------------------------------------------

#: JS that searches the Angular app's injector tree for a SecurityKey-like
#: value. Works on Angular 13+ (DEW uses Angular 13).
_INJECTOR_SEARCH_JS = """
() => {
    // Strategy 1: Check common global config locations
    const globals = ['__SPA_CONFIG__', '__APP_CONFIG__', 'appConfig',
                     'envConfig', 'window.__config'];
    for (const g of globals) {
        try {
            const v = eval(g);
            if (v && typeof v === 'object') {
                for (const k of Object.keys(v)) {
                    if (k.toLowerCase().includes('security') || k.toLowerCase().includes('key')) {
                        const val = v[k];
                        if (typeof val === 'string' && val.length > 10) return val;
                    }
                }
            }
        } catch(e) {}
    }

    // Strategy 2: Search all script tags for a SecurityKey assignment
    const scripts = document.querySelectorAll('script');
    for (const s of scripts) {
        const text = s.textContent || '';
        // Match: SecurityKey: "..." or securityKey: "..." or "SecurityKey":"..."
        const m = text.match(/["']?[Ss]ecurity[Kk]ey["']?\\s*[:=]\\s*["']([A-Za-z0-9+/=]+)["']/);
        if (m && m[1].length > 10) return m[1];
    }

    // Strategy 3: Search inline scripts + the page's JS bundles
    // The key is typically a base64 string (ends with = or ==)
    const inline = document.documentElement.innerHTML;
    const m2 = inline.match(/["']?[Ss]ecurity[Kk]ey["']?\\s*[:=]\\s*["']([A-Za-z0-9+/=]{16,64})["']/);
    if (m2 && m2[1].length > 10) return m2[1];

    // Strategy 4: Intercept the actual fetch call the SPA makes
    // Monkey-patch fetch to capture the SecurityKey header on the next request
    if (!window.__keyInterceptor) {
        window.__keyInterceptor = { key: null };
        const origFetch = window.fetch;
        window.fetch = function(...args) {
            try {
                const opts = args[1] || {};
                const hdrs = opts.headers || {};
                for (const [k, v] of Object.entries(hdrs)) {
                    if (k.toLowerCase().includes('security') && k.toLowerCase().includes('key')) {
                        window.__keyInterceptor.key = v;
                        break;
                    }
                }
            } catch(e) {}
            return origFetch.apply(this, args);
        };
    }
    // If a previous fetch already captured the key, return it
    if (window.__keyInterceptor && window.__keyInterceptor.key) {
        return window.__keyInterceptor.key;
    }

    return null;
}
"""

#: JS that triggers a search on the DEW SPA so the interceptor captures the key.
#: We type into the search box and click search, which makes the SPA fire its
#: fetch() with the SecurityKey header.
_TRIGGER_SEARCH_JS = """
async () => {
    // Wait a moment for the Angular app to bootstrap
    await new Promise(r => setTimeout(r, 1500));

    // Try to find and click a search button or trigger a name search
    // The DEW SPA has a "Last Name" search field and a Search button
    const inputs = document.querySelectorAll('input[type="text"], input:not([type])');
    let searchInput = null;
    for (const inp of inputs) {
        const ph = (inp.placeholder || '').toLowerCase() + ' ' +
                   (inp.getAttribute('aria-label') || '').toLowerCase() + ' ' +
                   (inp.id || '').toLowerCase() + ' ' +
                   (inp.name || '').toLowerCase();
        if (ph.includes('last') || ph.includes('name') || ph.includes('search')) {
            searchInput = inp;
            break;
        }
    }

    if (searchInput) {
        // Type a single character to trigger a search (minimal data)
        searchInput.value = 'A';
        searchInput.dispatchEvent(new Event('input', {bubbles: true}));
        searchInput.dispatchEvent(new Event('change', {bubbles: true}));
    }

    // Look for a search/submit button
    const buttons = document.querySelectorAll('button, input[type="submit"], a[role="button"]');
    for (const btn of buttons) {
        const txt = (btn.textContent || btn.value || '').toLowerCase().trim();
        if (txt.includes('search') || txt.includes('submit') || txt.includes('find')) {
            btn.click();
            break;
        }
    }

    // Wait for the fetch to fire
    await new Promise(r => setTimeout(r, 3000));

    // Now check if the interceptor captured the key
    if (window.__keyInterceptor && window.__keyInterceptor.key) {
        return window.__keyInterceptor.key;
    }
    return null;
}
"""


# ---------------------------------------------------------------------------
# Per-site extraction functions
# ---------------------------------------------------------------------------

async def extract_dew_security_key(
    registry_url: str = "https://uitax.dew.sc.gov/LienRegistry/",
    timeout_ms: int = 60000,
) -> Optional[str]:
    """Render the DEW SPA and extract the current SecurityKey from the live page.

    Tries four strategies in order:
    1. Global config objects (window.__SPA_CONFIG__ etc.)
    2. Script tag content (regex for SecurityKey: "...")
    3. Full page HTML (same regex on inline scripts)
    4. Fetch interceptor (monkey-patch window.fetch, trigger a search,
       capture the header from the SPA's own API call)

    Args:
        registry_url: The DEW Lien Registry URL.
        timeout_ms: Render timeout in milliseconds.

    Returns:
        The current SecurityKey string, or None if extraction failed.
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.error("spa_key.scrapling_missing")
        return None

    extracted: dict = {"key": None, "strategy": None, "error": None}

    async def page_action(page):
        # Wait for the Angular app to bootstrap
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        # Strategy 1-3: Static search (no interaction needed)
        try:
            key = await page.evaluate(_INJECTOR_SEARCH_JS)
            if key and isinstance(key, str) and len(key) > 10:
                extracted["key"] = key
                extracted["strategy"] = "static_search"
                log.info("spa_key.extracted",
                         site="dew", strategy="static_search",
                         key_prefix=key[:8] + "...")
                return page
        except Exception as exc:
            log.debug("spa_key.static_failed", error=str(exc)[:120])

        # Strategy 4: Fetch interceptor — trigger a search and capture the header
        try:
            key = await page.evaluate(_TRIGGER_SEARCH_JS)
            if key and isinstance(key, str) and len(key) > 10:
                extracted["key"] = key
                extracted["strategy"] = "fetch_intercept"
                log.info("spa_key.extracted",
                         site="dew", strategy="fetch_intercept",
                         key_prefix=key[:8] + "...")
                return page
        except Exception as exc:
            log.debug("spa_key.intercept_failed", error=str(exc)[:120])

        # Strategy 5: Fetch the main JS bundle directly and regex it
        try:
            bundle_key = await page.evaluate("""
                async () => {
                    // Find all script src URLs
                    const scripts = document.querySelectorAll('script[src]');
                    for (const s of scripts) {
                        const src = s.src;
                        if (!src.includes('main.') && !src.includes('runtime.')
                            && !src.includes('polyfills.')) continue;
                        try {
                            const resp = await fetch(src);
                            const text = await resp.text();
                            // Look for SecurityKey assignment in the bundle
                            const m = text.match(/["']?[Ss]ecurity[Kk]ey["']?\\s*[:=]\\s*["']([A-Za-z0-9+/=]{16,64})["']/);
                            if (m && m[1].length > 10) return m[1];
                        } catch(e) {}
                    }
                    return null;
                }
            """)
            if bundle_key and isinstance(bundle_key, str) and len(bundle_key) > 10:
                extracted["key"] = bundle_key
                extracted["strategy"] = "bundle_regex"
                log.info("spa_key.extracted",
                         site="dew", strategy="bundle_regex",
                         key_prefix=bundle_key[:8] + "...")
                return page
        except Exception as exc:
            log.debug("spa_key.bundle_failed", error=str(exc)[:120])

        extracted["error"] = "all_strategies_failed"
        return page

    try:
        await StealthyFetcher.async_fetch(
            registry_url,
            headless=True,
            network_idle=True,
            timeout=timeout_ms,
            page_action=page_action,
            solve_cloudflare=False,
        )
    except Exception as exc:
        log.warning("spa_key.render_failed", error=str(exc)[:160])
        return None

    return extracted.get("key")


# ---------------------------------------------------------------------------
# Generic key refresh — update the hardcoded key in sc_dew_lien_registry.py
# ---------------------------------------------------------------------------

# Regex to find the SECURITY_KEY assignment in the source file
_KEY_LINE_RE = re.compile(
    r'^(SECURITY_KEY\s*=\s*")[^"]+(")',
    re.MULTILINE,
)


def refresh_hardcoded_key(
    source_path: str = "src/foreclosure_scraper/scrapers/counties_sc/sc_dew_lien_registry.py",
    new_key: str | None = None,
) -> bool:
    """Update the hardcoded SECURITY_KEY in the DEW scraper source file.

    Call this after extract_dew_security_key() returns a new key that differs
    from the hardcoded one. This patches the .py file in-place so the direct
    HTTP path works again without a browser render.

    Args:
        source_path: Path to sc_dew_lien_registry.py.
        new_key: The new key to write. If None, calls extract_dew_security_key().

    Returns:
        True if the key was updated (or already current), False on failure.
    """
    import os

    if new_key is None:
        # Can't call async extract here — caller should pass the key
        log.error("spa_key.refresh_needs_key",
                  hint="Call extract_dew_security_key() first, pass result")
        return False

    if not os.path.exists(source_path):
        log.error("spa_key.source_not_found", path=source_path)
        return False

    with open(source_path, "r") as f:
        content = f.read()

    m = _KEY_LINE_RE.search(content)
    if not m:
        log.error("spa_key.key_line_not_found", path=source_path)
        return False

    old_key = m.group(0)
    new_line = f'SECURITY_KEY = "{new_key}"'

    if new_key in old_key:
        log.info("spa_key.already_current")
        return True

    content = content.replace(old_key, new_line, 1)
    with open(source_path, "w") as f:
        f.write(content)

    log.info("spa_key.updated",
             old_prefix=m.group(0).split('"')[1][:8] + "...",
             new_prefix=new_key[:8] + "...",
             path=source_path)
    return True


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

async def _self_test():
    """Verify the key extraction pipeline (does not hit the live site)."""
    import inspect
    print("spa_key_extractor self-test")
    print(f"  extract_dew_security_key: {'async' if inspect.iscoroutinefunction(extract_dew_security_key) else 'SYNC'}")
    print(f"  refresh_hardcoded_key:    {'async' if inspect.iscoroutinefunction(refresh_hardcoded_key) else 'SYNC'}")
    print(f"  _INJECTOR_SEARCH_JS:      {len(_INJECTOR_SEARCH_JS)} chars")
    print(f"  _TRIGGER_SEARCH_JS:       {len(_TRIGGER_SEARCH_JS)} chars")

    # Test the regex
    test_source = 'SECURITY_KEY = "LbBr3hPJ2qw9mHvmE+Px7gI8HiDaU+F3fWx68Z39YBw="'
    m = _KEY_LINE_RE.search(test_source)
    assert m, "regex should match"
    print(f"  regex test:               OK (matched {m.group(0)[:40]}...)")

    # Test refresh logic (in-memory, no file write)
    new = "NEWKEY1234567890abcdef=="
    replaced = _KEY_LINE_RE.sub(f'SECURITY_KEY = "{new}"', test_source)
    assert new in replaced, "regex replace should work"
    print(f"  replace test:             OK")
    print("  All tests passed.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_self_test())
