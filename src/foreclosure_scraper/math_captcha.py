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
    "×": operator.mul,
    "x": operator.mul,  # lowercase 'x' as multiply
    "*": operator.mul,
    "times": operator.mul,
    "multiplied by": operator.mul,
    "multipliedby": operator.mul,
    "÷": operator.floordiv,
    "/": operator.floordiv,
    "divided by": operator.floordiv,
    "dividedby": operator.floordiv,
}

#: Prefixes to strip before parsing (case-insensitive).
_QUESTION_PREFIXES = (
    "what is",
    "solve",
    "solve:",
    "calculate",
    "compute",
    "evaluate",
    "answer",
    "question",
    "please solve",
    "please answer",
)

#: Operator symbols in precedence order (lower index = higher precedence).
#: We evaluate left-to-right for same-precedence ops (sufficient for CAPTCHAs).
_OP_PRECEDENCE = [("/", "÷", "divided by", "dividedby"), ("*", "×", "x", "times", "multiplied by", "multipliedby")]
_OP_ALL_SYMBOLS = "+-*/×÷x"

# Build a regex pattern for each operator token (longest first for words).
_OP_TOKENS_SORTED = sorted(
    list(_OPS.keys()),
    key=len,
    reverse=True,
)
_OP_TOKEN_PATTERN = "|".join(re.escape(tok) for tok in _OP_TOKENS_SORTED)

#: Regex for a multi-term arithmetic expression.
#: Matches a sequence of: number, operator, number, operator, number, ...
#: Supports optional prefixes ("What is", "Solve:", etc.) and suffixes ("=", "?").
_EXPR_RE = re.compile(
    rf"""
    (?:{'|'.join(re.escape(p) for p in _QUESTION_PREFIXES)})?  # optional prefix
    \s*                       # optional whitespace
    (?P<expr>                 # the full expression
        \d+                   # first number
        (?:\s*
            (?:{_OP_TOKEN_PATTERN})   # operator
            \s*
            \d+               # next number
        )+                    # one or more additional (op, number) pairs
    )
    \s*                       # optional whitespace
    [=]?                      # optional trailing equals
    \s*                       # optional whitespace
    \??                       # optional trailing question mark
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Fallback: simple two-term binary expression (for "5 + 3" without operators
#: that the multi-term regex might miss, e.g. very short expressions).
_EXPR_SIMPLE_RE = re.compile(
    rf"""
    (?:{'|'.join(re.escape(p) for p in _QUESTION_PREFIXES)})?
    \s*
    (?P<a>\d+)
    \s*
    (?P<op>{_OP_TOKEN_PATTERN})
    \s*
    (?P<b>\d+)
    \s*
    [=]?
    \s*
    \??
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _tokenize_expression(expr: str) -> list[tuple[str, int]] | None:
    """Tokenize a math expression into a list of (operator, operand) pairs.

    The first element has operator="" (placeholder). Returns None on failure.

    Examples:
        "5 + 3"       -> [("", 5), ("+", 3)]
        "2 * 4 + 1"   -> [("", 2), ("*", 4), ("+", 1)]
    """
    tokens: list[tuple[str, int]] = []
    pos = 0
    expr = expr.strip()

    # Parse the first number.
    m = re.match(r"\s*(\d+)", expr)
    if not m:
        return None
    tokens.append(("", int(m.group(1))))
    pos = m.end()

    while pos < len(expr):
        # Skip whitespace.
        while pos < len(expr) and expr[pos].isspace():
            pos += 1
        if pos >= len(expr):
            break

        # Try to match an operator (longest first).
        remaining = expr[pos:]
        op_match: str | None = None
        for tok in _OP_TOKENS_SORTED:
            if remaining.lower().startswith(tok.lower()):
                # For word operators, check word boundary.
                if tok.isalpha() or " " in tok:
                    # Ensure we match whole words (e.g. "x" shouldn't match
                    # inside "xyz").
                    after = remaining[len(tok):]
                    if after and (after[0].isalpha() or after[0] == "_"):
                        continue
                op_match = tok
                pos += len(tok)
                break

        if op_match is None:
            # Check if it's a symbol operator we haven't matched.
            if remaining[0] in _OP_ALL_SYMBOLS:
                op_match = remaining[0]
                pos += 1
            else:
                break

        # Skip whitespace after operator.
        while pos < len(expr) and expr[pos].isspace():
            pos += 1

        # Parse the next number.
        m = re.match(r"\d+", expr[pos:])
        if not m:
            break
        tokens.append((op_match, int(m.group(0))))
        pos += m.end()

    if len(tokens) < 2:
        return None
    return tokens


def _evaluate_tokens(tokens: list[tuple[str, int]]) -> int | None:
    """Evaluate a tokenized expression with standard operator precedence.

    Evaluates division/multiplication first, then addition/subtraction.
    Left-to-right within the same precedence level.
    """
    if not tokens or len(tokens) < 2:
        return None

    # Pass 1: handle multiplication and division.
    stage1: list[tuple[str, int]] = [tokens[0]]
    for op, val in tokens[1:]:
        prev_op, prev_val = stage1[-1]
        if op.lower().strip() in (
            "*", "×", "x", "times", "multiplied by", "multipliedby"
        ):
            fn = _OPS.get(op.lower().strip().replace("  ", " "))
            if fn is None:
                fn = _OPS.get(op.lower().strip())
            if fn is None:
                return None
            stage1[-1] = (prev_op, fn(prev_val, val))
        elif op.lower().strip() in (
            "/", "÷", "divided by", "dividedby"
        ):
            fn = _OPS.get(op.lower().strip().replace("  ", " "))
            if fn is None:
                fn = _OPS.get(op.lower().strip())
            if fn is None:
                return None
            try:
                stage1[-1] = (prev_op, fn(prev_val, val))
            except ZeroDivisionError:
                log.warning("math_captcha.zero_division")
                return None
        else:
            stage1.append((op, val))

    # Pass 2: handle addition and subtraction (left to right).
    result = stage1[0][1]
    for op, val in stage1[1:]:
        op_key = op.lower().strip().replace("  ", " ")
        fn = _OPS.get(op_key) or _OPS.get(op.lower().strip())
        if fn is None:
            log.warning("math_captcha.unknown_op", op=op)
            return None
        result = fn(result, val)

    return result


def solve_math_question(text: str) -> int | None:
    """Parse a math captcha question and return the answer.

    Args:
        text: The question text, e.g. "What is 3 + 7?" or "Solve: 2 * 4 =".

    Returns:
        The integer answer, or None if the question couldn't be parsed.
    """
    if not text:
        return None

    # Clean up whitespace
    text = text.strip()

    # Try the multi-term regex first (handles "2 + 3 * 4", "Solve: 5 - 3 =", etc.)
    m = _EXPR_RE.search(text)
    if m:
        expr = m.group("expr")
        tokens = _tokenize_expression(expr)
        if tokens:
            result = _evaluate_tokens(tokens)
            if result is not None:
                log.info("math_captcha.solved", expr=expr, result=result)
                return result

    # Fallback: simple two-term regex.
    m = _EXPR_SIMPLE_RE.search(text)
    if m:
        a = int(m.group("a"))
        b = int(m.group("b"))
        op_text = m.group("op").lower().strip().replace("  ", " ")
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

    log.warning("math_captcha.no_match", text=text[:100])
    return None


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
        # New formats: "Solve:" prefix
        ("Solve: 2 * 4 =", 8),
        ("Solve: 5 + 3", 8),
        ("Solve 10 - 3 =", 7),
        # New: "=" suffix
        ("2 * 4 =", 8),
        ("5 + 3 =", 8),
        ("10 - 3 =", 7),
        # New: "What is" + "=" suffix
        ("What is 5 + 3 =?", 8),
        # New: mixed operations (operator precedence: * before +)
        ("2 + 3 * 4", 14),
        ("2 * 3 + 4", 10),
        ("10 - 2 * 3", 4),
        ("20 / 4 + 3", 8),
        # New: "Calculate" / "Compute" prefixes
        ("Calculate 5 + 3", 8),
        ("Compute 10 - 4 =", 6),
        # New: lowercase 'x' as multiply
        ("3 x 4", 12),
        ("What is 3 x 4?", 12),
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
