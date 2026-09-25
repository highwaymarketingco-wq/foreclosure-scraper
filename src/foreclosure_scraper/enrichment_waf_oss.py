"""Browser-driven AWS WAF CAPTCHA solver using Gemini for image recognition.

Replaces the paid CapSolver path with a free OSS approach. Drives the
CAPTCHA UI directly with Playwright. AWS WAF renders all 9 tiles into a
single 320x320 <canvas>, with 9 zero-size accessibility buttons; actual
clicks are on canvas pixel coordinates. We grab the whole canvas via
toDataURL, ask Gemini which numbered tiles (1-9) contain the target
object, then click the center of each matching tile on the canvas.

After Confirm, AWS WAF's own JS handles /problem -> /verify -> /voucher
client-side and sets the aws-waf-token cookie. Up to 3 puzzles back-to-
back are handled.

Cost: 1 Gemini 2.5-flash call per puzzle (~2-4s). Free tier 250 RPD per
account; with the 3-account rotation that's 750 puzzles/day headroom.

Inspired by github.com/xKiian/awswaf (MIT) but implemented end-to-end
against the rendered Playwright DOM so we never touch /voucher directly.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional

import httpx
import structlog

log = structlog.get_logger()


# Default to 2.5-flash-lite for WAF solves: 1000 RPD per account vs
# 250 for 2.5-flash, and the 3x3 grid CAPTCHA is well within flash-lite's
# recognition ability (verified 2026-05-13). The vision pipeline that
# describes property condition still uses the full 2.5-flash for quality.
GEMINI_MODEL = os.environ.get("WAF_GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_TIMEOUT_S = 30.0

# MEASURED (2026-09-25 incident): a patchright-launched "Chrome for Testing"
# renderer (Scrapling's StealthyFetcher, which drives this module's
# solve_waf_via_browser via its page_action hook) was found pegged at 100%
# CPU for 2.7 hours straight, a direct child of the still-running scraper
# process; killing it immediately unstuck the whole pipeline. Root cause:
# every individual wait below (canvas selector, canvas-render poll, one
# Gemini HTTP call, Confirm click, networkidle) IS already bounded, but they
# compound: MAX_PUZZLES (20) puzzles x up to 11 rotated Gemini keys x
# GEMINI_TIMEOUT_S (30s) is ~110 minutes worst case (e.g. every key
# rate-limited), which dwarfs every caller's own outer timeout_s (180-600s,
# see base_scraper.safe_run) and Scrapling's own `timeout=240000`ms fetch
# param (that only bounds individual page ops it drives itself -- it does
# NOT bound the total runtime of a page_action callback like this one). In
# practice, the only thing that ever stopped a run this long was the
# caller's outer asyncio.wait_for cancelling deep inside this coroutine
# while it sits mid-await on the browser/HTTP call -- an unsafe cancellation
# point for Playwright/patchright's async bindings that is the likely
# leak vector. MAX_TOTAL_SOLVE_SECONDS gives this function its own tight,
# self-imposed wall-clock budget so it returns False on its own -- well
# inside every caller's outer timeout -- instead of relying on being
# force-cancelled mid-browser-op. This does NOT weaken the bypass itself:
# a real puzzle solve finishes in seconds, so the budget only cuts short
# the pathological "stuck in an unresolvable retry loop" case.
MAX_TOTAL_SOLVE_SECONDS = float(os.environ.get("WAF_SOLVE_MAX_SECONDS", "90"))


def _gemini_keys() -> list[str]:
    keys: list[str] = []
    primary = os.environ.get("GEMINI_API_KEY") or ""
    for part in primary.split(","):
        k = part.strip()
        if k:
            keys.append(k)
    for i in range(1, 11):
        v = (os.environ.get(f"GEMINI_API_KEY_{i}") or "").strip()
        if v and v not in keys:
            keys.append(v)
    return keys


async def _identify_tiles(
    canvas_jpeg_b64: str, target_object: str, deadline: Optional[float] = None
) -> Optional[list[int]]:
    """Ask Gemini which tiles (1-9) in the 3x3 grid contain `target_object`.

    Returns list of 1-based tile numbers, or None on failure. Rotates
    Gemini keys on 429.

    `deadline` is a `time.monotonic()` cutoff (see MAX_TOTAL_SOLVE_SECONDS):
    stop rotating keys once it has passed rather than burning the full
    GEMINI_TIMEOUT_S on every remaining key when the puzzle is already
    over budget.
    """
    keys = _gemini_keys()
    if not keys:
        log.warning("waf.gemini.no_key")
        return None

    prompt = (
        f"This image is a 3x3 grid of 9 numbered tiles. Tiles are numbered "
        f"left-to-right, top-to-bottom: top row is 1, 2, 3; middle row is "
        f"4, 5, 6; bottom row is 7, 8, 9. Reply with ONLY a JSON array of "
        f"tile numbers that contain \"{target_object}\". Example: [1,3,5]. "
        f"No other text."
    )
    body = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": "image/jpeg", "data": canvas_jpeg_b64}},
            ],
        }],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }

    async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT_S) as client:
        for idx, key in enumerate(keys):
            if deadline is not None and time.monotonic() >= deadline:
                log.warning("waf.gemini.deadline_exceeded", key_idx=idx, keys_left=len(keys) - idx)
                break
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/"
                f"models/{GEMINI_MODEL}:generateContent?key={key}"
            )
            try:
                r = await client.post(url, json=body)
            except Exception as exc:
                log.warning("waf.gemini.http_error", key_idx=idx, error=str(exc)[:160])
                continue
            if r.status_code == 429:
                log.info("waf.gemini.rate_limit_rotate", key_idx=idx)
                continue
            if r.status_code != 200:
                log.warning(
                    "waf.gemini.bad_status",
                    key_idx=idx, status=r.status_code, body=r.text[:200],
                )
                continue
            try:
                ans = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                solution = json.loads(ans)
                if (isinstance(solution, list)
                        and all(isinstance(i, int) and 1 <= i <= 9 for i in solution)):
                    log.info(
                        "waf.gemini.solved",
                        key_idx=idx, target=target_object, n_selected=len(solution),
                    )
                    return solution
            except Exception as exc:
                log.warning(
                    "waf.gemini.parse_fail",
                    key_idx=idx, error=str(exc)[:160], body=r.text[:200],
                )
                continue
    return None


async def solve_waf_via_browser(page) -> bool:
    """Drive the AWS WAF CAPTCHA UI on the currently-loaded page.

    Returns True if the challenge was solved (aws-waf-token cookie is now
    set in page.context); False on any failure. Handles up to MAX_PUZZLES
    back-to-back puzzles — AWS WAF on portal-nc serves 3-5 in a row when
    it's suspicious of the client (verified 2026-05-13).
    """
    # AWS WAF on portal-nc serves an escalating number of puzzles when
    # the source IP looks suspicious (GitHub Actions runner IPs definitely
    # do). Verified 2026-05-13: 1 puzzle on a "good" run, 8+ on a "bad"
    # run with answers all correct. 20 covers worst observed without
    # exhausting the 4-min StealthyFetcher timeout (20 × ~4s = 80s).
    MAX_PUZZLES = 20

    # Self-imposed wall-clock budget (see MAX_TOTAL_SOLVE_SECONDS docstring
    # above this module's imports) so a run of bad luck (rate-limited keys,
    # a puzzle that never settles) can't compound past every caller's own
    # outer timeout and get force-cancelled mid-browser-op instead of
    # returning False cleanly on its own.
    deadline = time.monotonic() + MAX_TOTAL_SOLVE_SECONDS

    # Click "Begin" if visible
    try:
        begin = page.locator('button:has-text("Begin"), a:has-text("Begin")').first
        if await begin.count() > 0:
            log.info("waf.begin.click")
            await begin.click(timeout=8000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
    except Exception as exc:
        log.info("waf.begin.skip", reason=str(exc)[:120])

    for attempt in range(1, MAX_PUZZLES + 1):
        if time.monotonic() >= deadline:
            log.warning("waf.deadline_exceeded", attempt=attempt,
                        budget_s=MAX_TOTAL_SOLVE_SECONDS)
            return False

        # Wait for the canvas (3x3 puzzle grid) to render
        try:
            await page.wait_for_selector("canvas", timeout=20000)
            # Also wait until the canvas is non-trivial size (rendered)
            await page.wait_for_function(
                "() => { const c = document.querySelector('canvas'); "
                "return c && c.width > 100 && c.height > 100; }",
                timeout=15000,
            )
            # AWS WAF sometimes takes a beat to actually draw — give it 1s
            await asyncio.sleep(1.0)
        except Exception as exc:
            log.info("waf.no_more_puzzles", attempt=attempt, reason=str(exc)[:120])
            break

        # Pull the target word ("Choose all the X")
        target_word = await page.evaluate(
            """() => {
                const t = document.body.innerText;
                const m = t.match(/Choose all\\s+(?:the\\s+)?([^\\n]+)/i);
                return m ? m[1].trim() : null;
            }"""
        )
        if not target_word:
            log.warning("waf.target_not_found", attempt=attempt)
            return False
        log.info("waf.puzzle.start", attempt=attempt, target=target_word[:50])

        # Grab the canvas as base64 JPEG + bounding rect for click positioning
        canvas_info = await page.evaluate(
            """() => {
                const c = document.querySelector('canvas');
                if (!c) return null;
                const r = c.getBoundingClientRect();
                let dataUrl = null;
                try { dataUrl = c.toDataURL('image/jpeg', 0.92); }
                catch (e) { return {err: e.message}; }
                return {
                    rect: {x: r.x, y: r.y, w: r.width, h: r.height},
                    b64: dataUrl ? dataUrl.split(',')[1] : null,
                };
            }"""
        )
        if not canvas_info or canvas_info.get("err") or not canvas_info.get("b64"):
            log.warning("waf.canvas_read_fail", attempt=attempt, info=str(canvas_info)[:200])
            return False

        # Ask Gemini which 1-9 tiles match
        solution = await _identify_tiles(canvas_info["b64"], target_word, deadline=deadline)
        if solution is None:
            log.warning("waf.gemini.failed", attempt=attempt)
            return False

        # Click each matching tile by canvas pixel coordinates.
        # Grid layout: tile N is at (col, row) where N = row*3 + col + 1.
        rect = canvas_info["rect"]
        cell_w = rect["w"] / 3
        cell_h = rect["h"] / 3
        for n in solution:
            if not (1 <= n <= 9):
                continue
            col = (n - 1) % 3
            row = (n - 1) // 3
            cx = rect["x"] + (col + 0.5) * cell_w
            cy = rect["y"] + (row + 0.5) * cell_h
            try:
                await page.mouse.click(cx, cy)
                await asyncio.sleep(0.18)
            except Exception as exc:
                log.warning("waf.tile_click_fail", tile=n, error=str(exc)[:120])
                return False

        # Click Confirm
        confirmed = False
        for sel in (
            'button:has-text("Confirm")',
            'button:has-text("Submit")',
            'button:has-text("Verify")',
        ):
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    await btn.click(timeout=5000)
                    confirmed = True
                    break
            except Exception:
                continue
        if not confirmed:
            log.warning("waf.no_confirm_button", attempt=attempt)
            return False

        # Wait for WAF response — either next puzzle or release
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(1.5)

        # Check if we're past the WAF
        html = await page.content()
        if "awswaf" not in html.lower() and "gokuProps" not in html:
            log.info("waf.solved", attempts_used=attempt)
            return True

        log.info("waf.another_puzzle", attempt=attempt)

    log.warning("waf.max_puzzles_exceeded")
    return False
