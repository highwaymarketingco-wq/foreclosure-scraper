"""Browser-driven AWS WAF CAPTCHA solver using Gemini for image recognition.

Replaces the paid CapSolver path with a free OSS approach. Drives the
CAPTCHA UI directly with Playwright, extracts the 9-image grid via the
DOM, asks Gemini which tiles contain the target object, clicks them,
clicks Confirm. The WAF JS handles all token/voucher/cookie plumbing
client-side — we just need to click the right tiles like a human.

Why this approach over the AWS WAF API-direct port (xKiian/awswaf):
  - No /voucher format guessing — the WAF's own JS makes that call
  - Uses real browser context, so AWS WAF's behavioral signals pass
  - Single Gemini call per solve (5-10s), no rate-limit pressure on
    the 250 RPD vision quota

Cost: ~1 Gemini 2.5-flash call per Tyler scrape session (cookie persists
hours). Roughly $0 with the 3-account rotation we already have.

Inspired by the captcha flow reverse-engineered in github.com/xKiian/awswaf
(MIT licensed) but implemented from scratch on top of Playwright so we
don't have to vendor Go bindings or hit the /voucher endpoint directly.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Optional

import httpx
import structlog

log = structlog.get_logger()


# Use 2.5-flash since 2.0-flash free tier is dead (see enrichment_vision.py).
# 250 RPD per account is plenty — we solve at most once per Tyler session.
GEMINI_MODEL = os.environ.get("WAF_GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_S = 30.0


def _gemini_keys() -> list[str]:
    """Read all available Gemini keys, primary first then numbered."""
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


async def _identify_tiles(image_b64s: list[str], target_object: str) -> Optional[list[int]]:
    """Ask Gemini which tile indexes contain `target_object`. Returns the
    list of indexes (0-based), or None on failure. Rotates keys on 429."""
    keys = _gemini_keys()
    if not keys:
        log.warning("waf.gemini.no_key")
        return None

    prompt = (
        f"Look at these {len(image_b64s)} images, numbered 0 through "
        f"{len(image_b64s) - 1} in order. Reply with ONLY a JSON array "
        f"of indexes for images that contain \"{target_object}\". "
        f"Example: [0,2,4]. No other text."
    )
    parts = [{"text": prompt}] + [
        {"inlineData": {"mimeType": "image/jpeg", "data": b}}
        for b in image_b64s
    ]
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT_S) as client:
        for idx, key in enumerate(keys):
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/"
                f"models/{GEMINI_MODEL}:generateContent?key={key}"
            )
            try:
                r = await client.post(url, json=body)
            except Exception as exc:
                log.warning(
                    "waf.gemini.http_error",
                    key_idx=idx, error=str(exc)[:160],
                )
                continue
            if r.status_code == 429:
                log.info("waf.gemini.rate_limit_rotate", key_idx=idx)
                continue
            if r.status_code != 200:
                log.warning(
                    "waf.gemini.bad_status",
                    key_idx=idx, status=r.status_code,
                    body=r.text[:200],
                )
                continue
            try:
                ans_text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                solution = json.loads(ans_text)
                if isinstance(solution, list) and all(isinstance(i, int) for i in solution):
                    log.info(
                        "waf.gemini.solved",
                        key_idx=idx, target=target_object,
                        n_selected=len(solution),
                    )
                    return solution
            except Exception as exc:
                log.warning(
                    "waf.gemini.parse_fail",
                    key_idx=idx, error=str(exc)[:160],
                    body=r.text[:200],
                )
                continue
    return None


async def solve_waf_via_browser(page) -> bool:
    """Drive the AWS WAF CAPTCHA UI on the currently-loaded page.

    Caller has navigated to a page where the WAF challenge is visible
    ("Let's confirm you are human" + Begin button OR already-rendered grid).
    Returns True if the challenge was solved and the page moved past it
    (aws-waf-token cookie now set in page.context). False on any failure.

    Up to 3 puzzles in a row may be required by AWS WAF — handles that loop.
    """
    MAX_PUZZLES = 3

    # If we landed on the "Begin" gate, click it first.
    try:
        begin = page.locator('button:has-text("Begin"), a:has-text("Begin")').first
        if await begin.count() > 0:
            log.info("waf.begin.click")
            await begin.click(timeout=8000)
            await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as exc:
        log.info("waf.begin.skip", reason=str(exc)[:120])

    for attempt in range(1, MAX_PUZZLES + 1):
        # Wait for the puzzle to be rendered. The target word is inside
        # an <a>/<span> following the "Choose all" text; the 9 images are
        # <img> inside a grid wrapper.
        try:
            await page.wait_for_selector(
                'img[src^="data:image/jpeg"], img[src^="data:image/png"]',
                timeout=20000,
            )
        except Exception:
            # No more puzzles — maybe we're past the WAF already
            log.info("waf.no_more_puzzles", attempt=attempt)
            break

        # Extract target word ("Choose all <target>" — the underlined link
        # is the target). Fallback: any <a> right after "Choose all".
        target_word = await page.evaluate(
            """() => {
                const all = document.body.innerText;
                const m = all.match(/Choose all\\s+(?:the\\s+)?([^\\n]+)/i);
                if (m) return m[1].trim();
                return null;
            }"""
        )
        if not target_word:
            log.warning("waf.target_not_found", attempt=attempt)
            return False
        log.info("waf.puzzle.start", attempt=attempt, target=target_word[:50])

        # Pull all 9 (or N) image elements' data: extract base64 from src.
        # Each src looks like "data:image/jpeg;base64,/9j/4AA..."
        tiles = await page.evaluate(
            """() => {
                const imgs = [...document.querySelectorAll('img')]
                    .filter(i => /^data:image\\/(jpe?g|png);base64,/i.test(i.src));
                return imgs.map((i, idx) => ({
                    idx,
                    b64: i.src.split(',')[1],
                    boundingRect: (() => {
                        const r = i.getBoundingClientRect();
                        return {x: r.x, y: r.y, w: r.width, h: r.height};
                    })()
                }));
            }"""
        )
        if not tiles or len(tiles) < 4:
            log.warning("waf.no_tiles", attempt=attempt, count=len(tiles or []))
            return False

        image_b64s = [t["b64"] for t in tiles]
        solution = await _identify_tiles(image_b64s, target_word)
        if solution is None:
            log.warning("waf.gemini.failed", attempt=attempt)
            return False

        # Click each matching tile via center of its bounding rect.
        for idx in solution:
            if not (0 <= idx < len(tiles)):
                continue
            r = tiles[idx]["boundingRect"]
            cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
            try:
                await page.mouse.click(cx, cy)
                await asyncio.sleep(0.15)
            except Exception as exc:
                log.warning("waf.tile_click_fail", idx=idx, error=str(exc)[:120])
                return False

        # Click Confirm button. Selectors vary; try several.
        confirmed = False
        for sel in (
            'button:has-text("Confirm")',
            'button:has-text("Submit")',
            'button:has-text("Verify")',
            'button[data-action="confirm"]',
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

        # Wait for AWS WAF to process. Either:
        #  - next puzzle renders (loop)
        #  - we get redirected past the WAF (return True)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        # Detect "past WAF": no more goku/awswaf challenge markers
        html = await page.content()
        if "awswaf" not in html.lower() and "gokuProps" not in html:
            log.info("waf.solved", attempts_used=attempt)
            return True

        # Otherwise, AWS gave another puzzle — loop
        log.info("waf.another_puzzle", attempt=attempt)

    log.warning("waf.max_puzzles_exceeded")
    return False
