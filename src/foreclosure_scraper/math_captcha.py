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
from urllib.parse import urljoin

import structlog
from bs4 import BeautifulSoup

log = structlog.get_logger()

# Optional OCR plumbing (stretch goal: read an image-rendered question).
# Reuses this codebase's existing free-tier-first Gemini key rotation /
# JSON-response parsing (enrichment_vision — the same helpers
# enrichment_doc_ocr.py uses for scanned documents) rather than duplicating
# it. A dedicated prompt is used below since reading two numbers + an
# operator off a tiny arithmetic image has nothing in common with
# enrichment_doc_ocr's legal-document extraction schema.
try:
    from .enrichment_vision import _parse_gemini_keys, _parse_json_response, GEMINI_VISION_MODEL
except Exception:  # noqa: BLE001 - OCR is optional; module must still import
    _parse_gemini_keys = None  # type: ignore[assignment]
    _parse_json_response = None  # type: ignore[assignment]
    GEMINI_VISION_MODEL = None  # type: ignore[assignment]

try:
    from google import genai as _genai
    from google.genai import types as _genai_types
except ImportError:
    _genai = None
    _genai_types = None

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


#: A US phone number shape: optional area-code parens, 3-3-4 digit groups
#: with optional separators (e.g. "704-253-4000", "(910) 253-2690"). THIS is
#: the exact false-positive this module used to ship (see module docstring
#: and _solve_question_text below): "253-2690" parses as a valid "number
#: MINUS number" expression to solve_math_question(), which has no way to
#: know it's a phone number rather than a real question. Stripped out of any
#: text before it's handed to solve_math_question().
_PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


def _solve_question_text(text: str | None) -> int | None:
    """Parse a math captcha question from a short snippet of SCOPED page
    text (never the whole page — see _analyze_captcha_html), after first
    stripping anything that looks like a US phone number.

    solve_math_question()'s regex is intentionally generic (any "number
    operator number" shape in the text it's given) — correct for a real
    question, but it will happily match a phone number's exchange and line
    number as a subtraction (e.g. "(910) 253-2690" -> "253 - 2690" = -2437).
    A phone number is the one digit-operator-digit shape that shows up on
    these CAPTCHA pages for a reason OTHER than being the question (office
    contact info in a header/footer), so it's stripped before parsing
    rather than trusted like a real expression would be.
    """
    if not text:
        return None
    cleaned = _PHONE_RE.sub(" ", text)
    return solve_math_question(cleaned)


# ---------------------------------------------------------------------------
# Playwright integration — find the question on the page, answer it
# ---------------------------------------------------------------------------

#: CSS selectors for common math captcha layouts on NC ROD sites. No longer
#: used for a page-wide text search (see module docstring's false-positive
#: fix) — kept as documentation of the tag shapes seen in the wild.
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

#: Selectors for the answer input field, tried in order (most-specific
#: first). The last one, `input[type='text']`, is a broad catch-all — fine
#: for FINDING the field (a real CAPTCHA page rarely has other bare text
#: inputs), but too broad to trust as evidence the gate is still showing
#: AFTER submit (a legitimate post-gate search page can have text inputs
#: too) — see _GATE_MARKER_SELECTORS below, which deliberately excludes it.
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

#: Selectors specific enough that a legitimate post-gate page is very
#: unlikely to also match them — used ONLY for the post-submit "did we
#: actually get past it" check.
_GATE_MARKER_SELECTORS = [s for s in _ANSWER_SELECTORS if s != "input[type='text']"]

#: Submit controls seen on these ROD sites, including the `input[type=image]`
#: "click to login" graphic Brunswick itself uses (confirmed live 2026-10-14
#: — none of the other selectors below match it, so without this entry the
#: code always fell through to the Enter-key fallback for Brunswick).
_SUBMIT_SELECTORS = [
    "input[type='submit']",
    "button[type='submit']",
    "button:has-text('Submit')",
    "button:has-text('Search')",
    "button:has-text('Continue')",
    "button:has-text('OK')",
    "input[type='button'][value='Submit']",
    "input[type='button'][value='Search']",
    "input[type='image']",
]

#: Container tags that plausibly group a CAPTCHA question with its answer
#: field, nearest-first. Brunswick's real markup (live-confirmed 2026-10-14)
#: wraps the question + input in a `<fieldset class="captcha">` that sits
#: deep inside one page-spanning `<form>` — the office phone number is a
#: SIBLING section of that same outer form, several DOM levels away, so
#: scoping to the nearest fieldset (not the outer form) is what actually
#: keeps it out.
_CONTAINER_TAGS = ("fieldset", "form")

#: A scoped container larger than this many characters of text is not a
#: tightly-scoped question field — treat it as "no scoped text" rather than
#: regex across something page-sized (the same mistake the old whole-body
#: search made, just with a bigger excuse).
_MAX_SCOPED_TEXT_CHARS = 1500

#: An <img> matching one of these (checked against `src` and `alt`) inside
#: the scoped container is treated as the captcha question rendered as an
#: IMAGE rather than text — Brunswick's `getpng.php?a=N&b=M` pattern
#: (live-confirmed 2026-10-14: 4 such images in one page, each rendering ONE
#: WORD of the question, e.g. "Five" / "Plus" / "Nine" / "Equals"; the `a`/
#: `b` query params are NOT the literal operands — they're opaque render
#: params, confirmed by fetching and visually reading the actual PNGs).
_IMAGE_PATTERN_RE = re.compile(r"getpng|captcha|math[-_]?question|mathcaptcha", re.I)


def _answer_tag(soup: BeautifulSoup) -> tuple[Any, str | None]:
    """First element in `soup` matching one of _ANSWER_SELECTORS, and which
    selector matched (same order of preference as the live Playwright
    lookup below, so the static analysis and the live fill agree on which
    field is "the" answer field)."""
    for selector in _ANSWER_SELECTORS:
        try:
            tag = soup.select_one(selector)
        except Exception:  # noqa: BLE001 - a selector soupsieve can't parse
            continue
        if tag is not None:
            return tag, selector
    return None, None


def _scoped_container(tag: Any) -> Any:
    """Climb from the answer <input> tag to the nearest fieldset/form. Never
    returns <body>/<html> — those aren't a "scope" at all, they're the whole
    page, which is exactly what this module stopped trusting (see module
    docstring)."""
    container = tag.find_parent(_CONTAINER_TAGS)
    if container is None:
        container = tag.parent
    if container is None:
        return None
    if getattr(container, "name", None) in ("body", "html", None):
        return None
    return container


def _analyze_captcha_html(html: str) -> dict:
    """Locate the answer field in a snapshot of the page and extract ONLY
    the text/images inside its immediate fieldset/form — never the whole
    page body. This is the core of the false-positive fix: the old code fed
    `page.inner_text("body")` (the ENTIRE page, including footer contact
    info) to the question parser; this scopes to the one container that
    actually holds the question.

    Returns {"answer_selector", "scoped_text", "image_srcs"}. `image_srcs`
    is a list in DOCUMENT ORDER (Brunswick's 4 word-images must be read in
    order to reconstruct the sentence). Any value may be None/empty if not
    found — callers must not fall back to a wider search.
    """
    result: dict = {"answer_selector": None, "scoped_text": None, "image_srcs": []}
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception as exc:  # noqa: BLE001
        log.debug("math_captcha.html_parse_error", error=str(exc)[:120])
        return result

    tag, selector = _answer_tag(soup)
    if tag is None:
        return result
    result["answer_selector"] = selector

    container = _scoped_container(tag)
    if container is None:
        return result

    text = container.get_text(" ", strip=True)
    if text and len(text) <= _MAX_SCOPED_TEXT_CHARS:
        result["scoped_text"] = text

    srcs: list[str] = []
    for img in container.find_all("img"):
        src = img.get("src") or ""
        alt = img.get("alt") or ""
        if _IMAGE_PATTERN_RE.search(src) or _IMAGE_PATTERN_RE.search(alt):
            srcs.append(src)
    result["image_srcs"] = srcs

    return result


async def _gate_still_present(page: Any) -> bool:
    """After submit, is the captcha/answer field still showing? Used to
    catch exactly the false positive this module used to ship: Brunswick's
    wrong-answer submit reloaded a byte-for-byte identical page, which the
    old code never checked for before returning True. Fails CLOSED (treats
    an unreadable page as "gate still present") — the old bug's failure
    mode was the opposite assumption (treat the unverified case as success),
    which is the thing being fixed.
    """
    try:
        html = await page.content()
    except Exception as exc:
        log.debug("math_captcha.gate_check_no_content", error=str(exc)[:120])
        return True
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception:
        return True
    for selector in _GATE_MARKER_SELECTORS:
        try:
            if soup.select_one(selector) is not None:
                return True
        except Exception:
            continue
    return False


_MATH_IMAGE_PROMPT = (
    "These images, in order, together spell out ONE simple arithmetic "
    "CAPTCHA question — either as words (e.g. one image reads \"Five\", the "
    "next \"Plus\", the next \"Nine\", the next \"Equals\") or as symbols "
    "(e.g. \"3 + 7 = ?\"). Read them together as a single sentence and "
    "identify the two numbers and the operator. Return STRICT JSON only, no "
    "markdown fences, no explanation:\n"
    '  {"a": <first number as an int>, "op": "+" | "-" | "*" | "/", '
    '"b": <second number as an int>}'
)


async def _fetch_image_bytes(page: Any, image_src: str) -> tuple[bytes, str] | None:
    """Fetch one captcha-question image through the page's own browser
    context (cookies included) — some of these ROD platforms 302 a cookie-
    less request to a login/disclaimer page instead of the real image (the
    same lesson nc_rod_captcha.py's Durham document-image route already
    learned), so this deliberately uses `page.request`, not a bare client."""
    try:
        url = urljoin(page.url, image_src)
    except Exception:
        url = image_src
    try:
        resp = await page.request.get(url)
    except Exception as exc:
        log.warning("math_captcha.image_fetch_error", error=str(exc)[:160])
        return None
    status = getattr(resp, "status", 200)
    if status and status >= 400:
        log.warning("math_captcha.image_fetch_bad_status", status=status)
        return None
    try:
        data = await resp.body()
    except Exception as exc:
        log.warning("math_captcha.image_body_error", error=str(exc)[:160])
        return None
    if not data:
        return None
    mime = "image/png"
    try:
        headers = resp.headers
        ct = headers.get("content-type") if headers else None
        if ct and ct.split(";")[0].strip().startswith("image/"):
            mime = ct.split(";")[0].strip()
    except Exception:
        pass
    return data, mime


async def _solve_image_question(page: Any, image_srcs: list[str]) -> int | None:
    """Stretch goal: OCR an image-rendered math question (Brunswick's
    getpng.php word-images) using this codebase's existing free-tier-first
    Gemini OCR plumbing (enrichment_vision._parse_gemini_keys /
    _parse_json_response — the same key-rotation helpers
    enrichment_doc_ocr.py uses for scanned documents, reused here with a
    dedicated prompt since reading two numbers + an operator off tiny
    arithmetic word-images is nothing like extracting owner/address fields
    off a legal document).

    Returns the integer answer, or None if OCR is unavailable or fails —
    callers MUST treat None as "could not solve", never guess. That
    guessing-and-reporting-success-anyway is exactly the bug being fixed.
    """
    if not image_srcs:
        return None
    if _genai is None or _parse_gemini_keys is None or _parse_json_response is None:
        log.info("math_captcha.ocr_unavailable", reason="no_genai_or_vision_helpers")
        return None

    keys = _parse_gemini_keys()
    if not keys:
        log.info("math_captcha.ocr_no_keys")
        return None

    blocks: list[tuple[bytes, str]] = []
    for src in image_srcs:
        fetched = await _fetch_image_bytes(page, src)
        if fetched is None:
            log.warning("math_captcha.ocr_image_fetch_failed", src=src[:160])
            return None
        blocks.append(fetched)

    for key in keys:
        try:
            client = _genai.Client(api_key=key)
            contents = [_genai_types.Part.from_bytes(data=d, mime_type=m) for d, m in blocks]
            contents.append(_MATH_IMAGE_PROMPT)
            resp = await client.aio.models.generate_content(
                model=GEMINI_VISION_MODEL,
                contents=contents,
                config=_genai_types.GenerateContentConfig(
                    max_output_tokens=200, response_mime_type="application/json"),
            )
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "quota" in msg.lower() or "resource_exhausted" in msg.lower():
                log.info("math_captcha.ocr_key_exhausted")
                continue
            log.warning("math_captcha.ocr_gemini_error", error=msg[:160])
            continue

        text = ""
        try:
            text = (resp.text or "").strip()
        except Exception:
            for cand in getattr(resp, "candidates", []) or []:
                for p in getattr(getattr(cand, "content", None), "parts", []) or []:
                    text += getattr(p, "text", "") or ""

        parsed = _parse_json_response(text)
        if not parsed:
            continue
        try:
            a = int(parsed["a"])
            b = int(parsed["b"])
            op_raw = str(parsed.get("op", "")).strip().lower()
        except Exception:
            continue
        fn = _OPS.get(op_raw)
        if fn is None:
            log.warning("math_captcha.ocr_unknown_op", op=op_raw)
            continue
        try:
            result = fn(a, b)
        except ZeroDivisionError:
            continue
        log.info("math_captcha.ocr_solved", a=a, op=op_raw, b=b, result=result)
        return result

    log.warning("math_captcha.ocr_all_keys_failed")
    return None


async def solve_math_captcha(page: Any, timeout_ms: int = 5000) -> bool:
    """Find, solve, and submit the math CAPTCHA on a Playwright page.

    Args:
        page: A Playwright Page already navigated to the CAPTCHA page.
        timeout_ms: How long to wait for elements to appear.

    Returns:
        True only if the CAPTCHA was found, a real question was read
        (scoped text or OCR'd image — never a page-wide regex guess),
        answered, submitted, AND the post-submit page confirms the gate is
        no longer showing. False in every other case, including "solved
        the arithmetic but the gate didn't actually clear" — a caller must
        never see True for a guess that happened to look plausible.
    """
    # Step 1: snapshot the page and find the answer field + its SCOPED
    # question — the form/fieldset immediately around it, never the whole
    # body (see module docstring's false-positive fix).
    try:
        html = await page.content()
    except Exception as exc:
        log.warning("math_captcha.no_page_content", error=str(exc)[:120])
        return False

    analysis = _analyze_captcha_html(html)
    if analysis["answer_selector"] is None:
        log.warning("math_captcha.no_input_field")
        return False

    answer = _solve_question_text(analysis["scoped_text"])

    if answer is None and analysis["image_srcs"]:
        log.info("math_captcha.image_question_detected",
                 count=len(analysis["image_srcs"]))
        answer = await _solve_image_question(page, analysis["image_srcs"])

    if answer is None:
        if analysis["image_srcs"]:
            # A real question exists but it's rendered as an image we
            # couldn't (or didn't try to) OCR — report failure, do NOT fall
            # through to a loose whole-page regex guess.
            log.warning("math_captcha.image_question_unsolved",
                        count=len(analysis["image_srcs"]))
        else:
            log.warning("math_captcha.no_question_found",
                        scoped_text_preview=(analysis["scoped_text"] or "")[:200])
        return False

    # Step 2: find + fill the real answer input via live Playwright
    # selectors (the DOM may have shifted slightly since the snapshot).
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
        log.warning("math_captcha.no_input_field_live")
        return False

    await answer_input.fill(str(answer))
    log.info("math_captcha.filled_answer", answer=answer)

    # Step 3: submit — try clicking a submit control, or press Enter.
    submitted = False
    for btn_selector in _SUBMIT_SELECTORS:
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
        try:
            await answer_input.press("Enter")
            submitted = True
            log.info("math_captcha.enter_submit")
        except Exception as exc:
            log.warning("math_captcha.submit_failed", error=str(exc)[:120])
            return False

    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        # Some sites don't fully reach networkidle — that's OK
        pass

    # Step 4: VERIFY the gate actually cleared instead of trusting that the
    # click/Enter "worked" — the exact check the old code skipped, which is
    # how it reported solved=True on Brunswick's unchanged disclaimer page.
    if await _gate_still_present(page):
        log.warning("math_captcha.gate_still_present_after_submit", answer=answer)
        return False

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
