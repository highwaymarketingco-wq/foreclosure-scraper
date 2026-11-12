"""Tests for math_captcha.py — the Brunswick NC ROD false-positive fix.

Root cause (confirmed live against brunswick-live.inttek.net 2026-10-14, see
module docstring): the old `solve_math_captcha()` fed the ENTIRE page's
`page.inner_text("body")` to `solve_math_question()`, which regex-searches
for ANY "number operator number" shape anywhere in the given text. Brunswick's
real question is rendered as 4 separate word-images (`getpng.php?a=N&b=M`,
confirmed live by fetching and visually reading them: "Five" "Plus" "Nine"
"Equals" — the `a`/`b` query params are NOT the literal operands, they're
opaque render params). With no real question anywhere in the page's visible
TEXT, the old code's whole-body regex instead matched the Register of Deeds
office's own footer phone number ("(910) 253-2690") as "253 - 2690" = -2437,
filled that in, submitted, and returned True (claiming success) even though
the resulting page was byte-for-byte unchanged.

The fix: scope question-text extraction to the fieldset/form immediately
around the answer input (never the whole page), strip phone-number-shaped
substrings as a second independent guard, detect an image-rendered question
instead of silently falling through to a loose regex, and verify post-submit
that the gate's answer field is actually gone before ever returning True.

These tests run with no network and no real browser — `_FakePage` below is a
minimal stand-in for the handful of Playwright `Page` methods
`solve_math_captcha()` actually calls, backed by BeautifulSoup over plain
HTML strings so the DOM-scoping logic is exercised for real.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bs4 import BeautifulSoup

from foreclosure_scraper import math_captcha as mc


# ---------------------------------------------------------------------------
# Fixtures — real shapes, not invented ones
# ---------------------------------------------------------------------------

# Trimmed but structurally faithful to the REAL page fetched live from
# https://brunswick-live.inttek.net/ on 2026-10-14. The 4 getpng.php URLs
# below are the actual ones from that live page; fetching and viewing them
# (PNG, 116x55px each) showed the words "Five" "Plus" "Nine" "Equals" in
# that exact order — i.e. the real question was "Five Plus Nine Equals ___"
# = 14. The phone numbers in the footer are the real office numbers from
# that same live page, deliberately placed OUTSIDE the fieldset, in a
# sibling section of the one page-spanning <form> — exactly like the real
# site, which is the whole reason the old whole-body regex matched them.
BRUNSWICK_HTML = """
<html><body>
<form name="formname" method="POST" action="./index.ntk?s=aqG8y0CYske6m64y">
<table>
<tr><td>
<fieldset class="captcha" style="width:600px;">
<div class="fieldset-body">
<div class="description">This question tests whether you are a human or a
computer program. Solve the math problem below and enter the result as a
number. For instance:
<ul>
<li><b>EXAMPLE ONLY:</b> for "one plus three" enter "4"</li>
<li><b>EXAMPLE ONLY:</b> for "two minus twelve" enter "-10"</li>
</ul>
</div>
<div class="form-item" id="edit-captcha-response-wrapper">
<span class="field-prefix">
<img alt="If you are having difficulties using this website, please call us at (800) 792-1786 ext. 2 to get logged in" style="width:75%;" src="getpng.php?a=438&amp;b=19">
<img alt="If you are having difficulties using this website, please call us at (800) 792-1786 ext. 2 to get logged in" style="width:75%;" src="getpng.php?a=237&amp;b=20">
<img alt="If you are having difficulties using this website, please call us at (800) 792-1786 ext. 2 to get logged in" style="width:75%;" src="getpng.php?a=586&amp;b=14">
<img alt="If you are having difficulties using this website, please call us at (800) 792-1786 ext. 2 to get logged in" style="width:75%;" src="getpng.php?a=973&amp;b=11">
</span>
<input style="vertical-align:bottom" type="text" maxlength="4" name="captcha_response" id="edit-captcha-response" aria-label="Answer to CAPTCHA" size="6" value="" class="form-text required" />
</div>
</div>
</fieldset>
<input type="hidden" name="a1" id="a1" value="901" />
<input type="hidden" name="a2" id="a2" value="12" />
<input type="hidden" name="b1" id="b1" value="335" />
<input type="hidden" name="b2" id="b2" value="23" />
<input type="image" src="./images/click_login.jpg" alt="Click here to Login" value="Submit!" name="submit" border="0">
</td></tr>
<tr><td>
<span class="color-1">
(910) 253-2690 OFFICE
877-625-9310 TOLL FREE
(910) 253-2703 FAX
</span>
</td></tr>
</table>
</form>
</body></html>
"""

# A page with no captcha/answer field at all — stands in for "we got past
# the gate" (Brunswick's real post-clear page is a document-search UI with
# no `name=*captcha*`/`name=*answer*` field).
POST_GATE_HTML = "<html><body><div id='search-form'>Search Deeds</div></body></html>"

# A legitimate text-based county (Brunswick's 2026-10-12 docstring originally
# assumed this shape before the image gate was discovered live) — question
# sits in the same fieldset as the input, like Brunswick's.
LEGIT_TEXT_HTML = """
<html><body>
<form>
<fieldset>
<label>What is 3 + 7?</label>
<input type="text" name="captcha_answer" id="captcha_answer" />
</fieldset>
<button type="submit">Submit</button>
</form>
</body></html>
"""


# ---------------------------------------------------------------------------
# Fake Playwright Page — the handful of methods solve_math_captcha() calls,
# backed by BeautifulSoup over a plain HTML string. No browser involved.
# ---------------------------------------------------------------------------

class _FakeElement:
    def __init__(self, page, tag):
        self.page = page
        self.tag = tag

    async def fill(self, value):
        self.page.last_filled = value

    async def press(self, key):
        if key == "Enter":
            await self.page._submit()

    async def click(self, force=False):
        await self.page._submit()


class _FakeResponse:
    def __init__(self, status=200, body=b"\x89PNGfakebytes", content_type="image/png"):
        self.status = status
        self._body = body
        self.headers = {"content-type": content_type}

    async def body(self):
        return self._body


class _FakeRequestContext:
    def __init__(self, response=None):
        self._response = response or _FakeResponse()
        self.urls_fetched: list[str] = []

    async def get(self, url):
        self.urls_fetched.append(url)
        return self._response


class _FakePage:
    """Stands in for a Playwright Page already navigated to the CAPTCHA
    page. `html_after` is what `.content()` returns once `_submit()` fires
    (simulating the server's response to the form POST) — same HTML as
    `html_before` means "nothing changed" (wrong answer / gate not cleared).
    """

    def __init__(self, html_before: str, html_after: str | None = None,
                 url: str = "https://brunswick-live.inttek.net/"):
        self.html_before = html_before
        self.html_after = html_after if html_after is not None else html_before
        self._current = html_before
        self.submitted = False
        self.last_filled = None
        self.url = url
        self.request = _FakeRequestContext()

    async def _submit(self):
        self.submitted = True
        self._current = self.html_after

    def _soup(self):
        return BeautifulSoup(self._current, "html.parser")

    async def content(self):
        return self._current

    async def wait_for_selector(self, selector, timeout=2000):
        tag = self._soup().select_one(selector)
        if tag is None:
            raise TimeoutError(f"no match for {selector}")
        return _FakeElement(self, tag)

    async def query_selector(self, selector):
        tag = self._soup().select_one(selector)
        return _FakeElement(self, tag) if tag else None

    async def query_selector_all(self, selector):
        return [_FakeElement(self, t) for t in self._soup().select(selector)]

    async def wait_for_load_state(self, state=None, timeout=None):
        return None


# ---------------------------------------------------------------------------
# (a) The phone-number false positive — the core regression test
# ---------------------------------------------------------------------------

def test_solve_question_text_rejects_bare_phone_number():
    """A body_text sample containing only a hyphenated phone number and no
    real question must return None, not a bogus 'answer' computed from the
    phone number's digits — this is the EXACT bug (see module docstring):
    "(910) 253-2690" used to parse as "253 - 2690" = -2437."""
    assert mc._solve_question_text("For help call (910) 253-2690 OFFICE.") is None
    assert mc._solve_question_text("Call 704-253-4000 for assistance.") is None
    assert mc._solve_question_text("877-625-9310 TOLL FREE  (910) 253-2703 FAX") is None


def test_solve_question_text_phone_number_does_not_mask_real_question():
    """A phone number elsewhere in the same snippet must not prevent a REAL
    question from being read — only the phone-shaped substring is stripped."""
    text = "What is 3 + 7? Call (910) 253-2690 for help."
    assert mc._solve_question_text(text) == 10


def test_analyze_captcha_html_brunswick_excludes_footer_phone():
    """The scoped container (Brunswick's fieldset) must not include the
    footer phone number, which sits in a SIBLING table row of the same
    page-spanning <form> — several DOM levels away from the fieldset."""
    analysis = mc._analyze_captcha_html(BRUNSWICK_HTML)
    assert analysis["answer_selector"] is not None
    assert analysis["scoped_text"] is not None
    assert "253-2690" not in analysis["scoped_text"]
    assert "792-1786" not in analysis["scoped_text"]  # alt text isn't text content anyway
    # No parseable question in the scoped text either (it's genuinely
    # image-only on Brunswick) -- the "EXAMPLE ONLY" instructional text
    # uses spelled-out numbers ("one plus three"), which solve_math_question
    # correctly ignores since it requires digit operands.
    assert mc._solve_question_text(analysis["scoped_text"]) is None


def test_analyze_captcha_html_finds_brunswick_images_in_order():
    analysis = mc._analyze_captcha_html(BRUNSWICK_HTML)
    assert len(analysis["image_srcs"]) == 4
    assert analysis["image_srcs"] == [
        "getpng.php?a=438&b=19",
        "getpng.php?a=237&b=20",
        "getpng.php?a=586&b=14",
        "getpng.php?a=973&b=11",
    ]


@pytest.mark.asyncio
async def test_solve_math_captcha_brunswick_without_ocr_returns_false(monkeypatch):
    """End-to-end regression test: given the real Brunswick page shape (image
    question + footer phone number), with OCR unavailable, solve_math_captcha
    must return False -- NOT silently submit a phone-number-derived guess and
    claim success, which is exactly what the old code did."""
    monkeypatch.setattr(mc, "_parse_gemini_keys", lambda: [])
    page = _FakePage(BRUNSWICK_HTML)
    result = await mc.solve_math_captcha(page)
    assert result is False
    assert page.submitted is False  # never even tried to submit a guess
    assert page.last_filled is None


@pytest.mark.asyncio
async def test_solve_math_captcha_wrong_answer_not_cleared_returns_false(monkeypatch):
    """Even if SOME answer were (wrongly) computed and submitted, a post-
    submit page that still shows the captcha field must not be reported as
    solved. Simulated here with a legit text question but a server response
    that doesn't change (the "wrong answer" case)."""
    page = _FakePage(LEGIT_TEXT_HTML, html_after=LEGIT_TEXT_HTML)
    result = await mc.solve_math_captcha(page)
    assert result is False
    assert page.submitted is True
    assert page.last_filled == "10"  # it did solve 3+7 correctly...
    # ...but since the gate didn't clear, the function must still say False.


# ---------------------------------------------------------------------------
# (b) Legitimate text-based questions still work
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("What is 3 + 7?", 10),
    ("3 + 7", 10),
    ("what is 12 minus 5", 7),
    ("12 - 5?", 7),
    ("7 × 8", 56),
    ("20 divided by 4", 5),
    ("What is 15 plus 27?", 42),
    ("Solve: 2 * 4 =", 8),
    ("2 + 3 * 4", 14),
    ("3 x 4", 12),
])
def test_solve_math_question_self_test_cases_unchanged(text, expected):
    """solve_math_question() itself is untouched by this fix (the bug was in
    WHAT TEXT got fed to it, not the parser) -- a sample of the module's own
    _self_test() cases, still passing."""
    assert mc.solve_math_question(text) == expected


def test_self_test_still_fully_passes():
    assert mc._self_test() is True


@pytest.mark.asyncio
async def test_solve_math_captcha_legit_text_flow_succeeds():
    """A county whose question really is in the text (no image gate): scoped
    extraction finds it, submit fires, and the post-submit page (no captcha
    field) confirms the gate actually cleared."""
    page = _FakePage(LEGIT_TEXT_HTML, html_after=POST_GATE_HTML)
    result = await mc.solve_math_captcha(page)
    assert result is True
    assert page.last_filled == "10"
    assert page.submitted is True


@pytest.mark.asyncio
async def test_solve_math_captcha_no_captcha_present_returns_false():
    """A page with no answer field at all (nothing to solve) must return
    False, not raise."""
    page = _FakePage(POST_GATE_HTML)
    result = await mc.solve_math_captcha(page)
    assert result is False


# ---------------------------------------------------------------------------
# (c) OCR stretch goal — image-rendered question solved via the reused
# Gemini vision plumbing (enrichment_vision._parse_gemini_keys /
# _parse_json_response), mocked here so the test needs no network/API key.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_solve_image_question_reads_brunswick_word_images(monkeypatch):
    """Direct test of the OCR path: given Brunswick's 4 getpng.php URLs and a
    mocked Gemini response describing the real live content ("Five Plus Nine
    Equals ___" = 14, confirmed by fetching and visually reading the actual
    PNGs from brunswick-live.inttek.net on 2026-10-14), the function must
    fetch all 4 images (through page.request, i.e. session-bearing) and
    return the correct integer answer."""
    monkeypatch.setattr(mc, "_parse_gemini_keys", lambda: ["fake-gemini-key"])

    fake_generate_content = AsyncMock(
        return_value=SimpleNamespace(text='{"a": 5, "op": "+", "b": 9}')
    )
    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate_content))
    )
    fake_genai = SimpleNamespace(Client=lambda api_key: fake_client)
    fake_genai_types = SimpleNamespace(
        Part=SimpleNamespace(from_bytes=lambda data, mime_type: {"data": data, "mime_type": mime_type}),
        GenerateContentConfig=lambda **kw: kw,
    )
    monkeypatch.setattr(mc, "_genai", fake_genai)
    monkeypatch.setattr(mc, "_genai_types", fake_genai_types)

    page = _FakePage(BRUNSWICK_HTML)
    image_srcs = mc._analyze_captcha_html(BRUNSWICK_HTML)["image_srcs"]
    assert len(image_srcs) == 4

    answer = await mc._solve_image_question(page, image_srcs)
    assert answer == 14
    assert fake_generate_content.await_count == 1
    # All 4 word-images were fetched through the page's own session.
    assert len(page.request.urls_fetched) == 4


@pytest.mark.asyncio
async def test_solve_math_captcha_end_to_end_with_ocr_stretch(monkeypatch):
    """Full solve_math_captcha() flow on the real Brunswick page shape, with
    OCR mocked to return the real live answer (14): fills "14", submits, and
    a post-gate page (no captcha field) confirms success."""
    monkeypatch.setattr(mc, "_parse_gemini_keys", lambda: ["fake-gemini-key"])

    fake_generate_content = AsyncMock(
        return_value=SimpleNamespace(text='{"a": 5, "op": "+", "b": 9}')
    )
    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate_content))
    )
    fake_genai = SimpleNamespace(Client=lambda api_key: fake_client)
    fake_genai_types = SimpleNamespace(
        Part=SimpleNamespace(from_bytes=lambda data, mime_type: {"data": data, "mime_type": mime_type}),
        GenerateContentConfig=lambda **kw: kw,
    )
    monkeypatch.setattr(mc, "_genai", fake_genai)
    monkeypatch.setattr(mc, "_genai_types", fake_genai_types)

    page = _FakePage(BRUNSWICK_HTML, html_after=POST_GATE_HTML)
    result = await mc.solve_math_captcha(page)
    assert result is True
    assert page.last_filled == "14"


@pytest.mark.asyncio
async def test_solve_image_question_no_keys_returns_none(monkeypatch):
    """OCR unavailable (no Gemini keys) -- must return None, never guess."""
    monkeypatch.setattr(mc, "_parse_gemini_keys", lambda: [])
    page = _FakePage(BRUNSWICK_HTML)
    answer = await mc._solve_image_question(page, ["getpng.php?a=438&b=19"])
    assert answer is None
