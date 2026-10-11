"""Math CAPTCHA solver — for Brunswick NC and similar ROD sites.

Brunswick County NC's deed search shows a "math question" on the public
sign-in page (e.g. "What is 3 + 7?"). This module:

1. Renders the sign-in page with Playwright (real browser, real JS).
2. Extracts the math question text from the page.
3. Parses and evaluates the arithmetic (addition, subtraction,
   multiplication, division — integers only).
4. Fills in the answer field and submits.

This is a FREE solution — no API keys, no external services.

Usage in a scraper:
    from foreclosure_scraper.math_captcha import solve_math_captcha

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://rodrecords.brunswickcountync.gov/...")
        solved = await solve_math_captcha(page)
        if solved:
            # Now on the search page — proceed with scraping
            ...
"""
from __future__ import annotations

import re
import operator
from typing import Any

import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Math expression parser — safe eval, no exec()
# ---------------------------------------------------------------------------

#: Maps text operators to Python functions.
_OPS: dict[str, Any] = {
    "+": operator.add,
    "-": operator.sub,
    "plus": operator.add,
    "minus": operator.sub,
    "minus": operator.sub,
    "×": operator.mul,
    "*": operator.mul,
    "times": operator.mul,
    "multiplied by": operator.mul,
    "multipliedby": operator.mul,
    "÷": operator.floordiv,
    "/": operator.floordiv,
    "divided by": operator.floordiv,
    "dividedby": operator.floordiv,
}

#: Regex for a simple binary arithmetic expression.
# Matches: "3 + 7", "what is 12 minus 5", "7 × 8", etc.
_EXPR_RE = re.compile(
    r"""
    (?:what\s+is\s+)?        # optional "what is" prefix
    (?P<a>\d+)               # first operand
    \s*
    (?P<op>[+\-*/×÷]|        # symbol operators
        plus|minus|times|
        multiplied\s+by|
        divided\s+by)        # or word operators
    \s*
    (?P<b>\d+)               # second operand
    \s*\??                   # optional trailing question mark
    """,
    re.IGNORECASE | re.VERBOSE,
)


def solve_math_question(text: str) -> int | None:
    """Parse a math captcha question and return the answer.

    Args:
        text: The question text, e.g. "What is 3 + 7?" or "7 × 8".

    Returns:
        The integer answer, or None if the question couldn't be parsed.
    """
    if not text:
        return None

    # Clean up whitespace
    text = text.strip()

    m = _EXPR_RE.search(text)
    if not m:
        log.warning("math_captcha.no_match", text=text[:100])
        return None

    a = int(m.group("a"))
    b = int(m.group("b"))
    op_text = m.group("op").lower().strip().replace("  ", " ")

    # Normalize word operators
    op_key = op_text.replace(" ", "")

    fn = _OPS.get(op_key) or _OPS.get(op_text)
    if fn is None:
        log.warning("math_captcha.unknown_op", op=op_text, text=text[:100])
        return None

    try:
        result = fn(a, b)
    except (ZeroDivisionError, ValueError) as exc:
        log.warning("math_captcha.eval_error", error=str(exc), a=a, op=op_text, b=b)
        return None

    log.info("math_captcha.solved", a=a, op=op_text, b=b, result=result)
    return result


# ---------------------------------------------------------------------------
# Playwright integration — find the question on the page, answer it
# ---------------------------------------------------------------------------

#: CSS selectors for common math captcha layouts on NC ROD sites.
_QUESTION_SELECTORS = [
    # Brunswick NC / CivicPlus style — question in a label or span
    "label:has-text('+')",
    "label:has-text('-')",
    "label:has-text('×')",
    "label:has-text('÷')",
    "label:has-text('plus')",
    "label:has-text('minus')",
    "label:has-text('times')",
    # Generic: any element with a math expression
    "span:has-text('what is')",
    "span:has-text('What is')",
    "div:has-text('+')",
    "div:has-text('-')",
    # Some sites put it in <b> or <strong>
    "b:has-text('+')",
    "strong:has-text('+')",
]

#: Selectors for the answer input field.
_ANSWER_SELECTORS = [
    "input[name*='captcha']",
    "input[name*='math']",
    "input[name*='answer']",
    "input[name*='question']",
    "input[name*='security']",
    "input[id*='captcha']",
    "input[id*='math']",
    "input[id*='answer']",
    # Fallback: any small text input near the question
    "input[type='text']",
]


async def solve_math_captcha(page: Any, timeout_ms: int = 5000) -> bool:
    """Find, solve, and submit the math CAPTCHA on a Playwright page.

    Args:
        page: A Playwright Page already navigated to the CAPTCHA page.
        timeout_ms: How long to wait for elements to appear.

    Returns:
        True if the CAPTCHA was found, solved, and submitted successfully.
        False if no CAPTCHA was found or the answer couldn't be determined.
    """
    # Step 1: Try to extract the question text from the page.
    # We grab the full visible text and search it for a math expression,
    # which is more robust than matching specific CSS selectors.
    try:
        body_text = await page.inner_text("body", timeout=timeout_ms)
    except Exception as exc:
        log.warning("math_captcha.no_body_text", error=str(exc)[:120])
        return False

    answer = solve_math_question(body_text)
    if answer is None:
        log.warning("math_captcha.no_question_found",
                    body_text_preview=body_text[:200])
        return False

    # Step 2: Find the answer input field.
    answer_input = None
    for selector in _ANSWER_SELECTORS:
        try:
            element = await page.wait_for_selector(selector, timeout=2000)
            if element:
                answer_input = element
                log.info("math_captcha.found_input", selector=selector)
                break
        except Exception:
            continue

    if answer_input is None:
        log.warning("math_captcha.no_input_field")
        return False

    # Step 3: Fill in the answer.
    await answer_input.fill(str(answer))
    log.info("math_captcha.filled_answer", answer=answer)

    # Step 4: Submit — try clicking a submit button, or press Enter.
    submitted = False
    for btn_selector in [
        "input[type='submit']",
        "button[type='submit']",
        "button:has-text('Submit')",
        "button:has-text('Search')",
        "button:has-text('Continue')",
        "button:has-text('OK')",
        "input[type='button'][value='Submit']",
        "input[type='button'][value='Search']",
    ]:
        try:
            btn = await page.query_selector(btn_selector)
            if btn:
                await btn.click()
                submitted = True
                log.info("math_captcha.clicked_submit", selector=btn_selector)
                break
        except Exception:
            continue

    if not submitted:
        # Fallback: press Enter in the input field
        try:
            await answer_input.press("Enter")
            submitted = True
            log.info("math_captcha.enter_submit")
        except Exception as exc:
            log.warning("math_captcha.submit_failed", error=str(exc)[:120])
            return False

    # Step 5: Wait for navigation (CAPTCHA page → search page).
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        # Some sites don't fully reach networkidle — that's OK
        pass

    log.info("math_captcha.submitted", answer=answer, submitted=submitted)
    return True


# ---------------------------------------------------------------------------
# Unit tests — run directly to verify the solver
# ---------------------------------------------------------------------------

def _self_test():
    """Verify the math captcha parser with known inputs."""
    cases = [
        ("What is 3 + 7?", 10),
        ("3 + 7", 10),
        ("what is 12 minus 5", 7),
        ("12 - 5?", 7),
        ("7 × 8", 56),
        ("7 * 8", 56),
        ("7 times 8", 56),
        ("20 ÷ 4", 5),
        ("20 / 4", 5),
        ("20 divided by 4", 5),
        ("What is 15 plus 27?", 42),
        ("9 - 3", 6),
        ("1 + 1", 2),
        ("What is 100 minus 37?", 63),
    ]
    passed = 0
    for text, expected in cases:
        result = solve_math_question(text)
        status = "✓" if result == expected else "✗"
        if result == expected:
            passed += 1
        else:
            print(f"  {status} FAIL: '{text}' → got {result}, expected {expected}")
    print(f"Math captcha self-test: {passed}/{len(cases)} passed")
    return passed == len(cases)


if __name__ == "__main__":
    import sys
    success = _self_test()
    sys.exit(0 if success else 1)
