# CAPTCHA-Solving Solutions Research

**Date:** 2026-10-10
**Project:** foreclosure-scraper (Python 3.12, venv at `.venv/`)
**Goal:** Evaluate all viable CAPTCHA-solving approaches for walled NC/SC county sources.

---

## 1. CapSolver API — reCAPTCHA Task Types

### Supported Task Types

| Task Type | Version | Proxy? | Price/1k |
|---|---|---|---|
| `ReCaptchaV2TaskProxyLess` | V2 | Server proxy | ~$1.00–$1.45/1k |
| `ReCaptchaV2EnterpriseTask` | V2 Enterprise | Your proxy | ~$1.45/1k |
| `ReCaptchaV2EnterpriseTaskProxyLess` | V2 Enterprise | Server proxy | ~$1.45/1k |
| `ReCaptchaV3Task` | V3 | Your proxy | $1.00/1k |
| `ReCaptchaV3TaskProxyLess` | V3 | Server proxy | $1.00/1k |
| `ReCaptchaV3EnterpriseTask` | V3 Enterprise | Your proxy | $3.00/1k |
| `ReCaptchaV3EnterpriseTaskProxyLess` | V3 Enterprise | Server proxy | $3.00/1k |
| `ReCaptchaV3M1Task` | V3 High-Score (M1) | Your proxy | $3.00/1k |
| `ReCaptchaV3M1TaskProxyLess` | V3 High-Score (M1) | Server proxy | $3.00/1k |
| `ReCaptchaV3EnterpriseM1Task` | V3 Enterprise M1 | Your proxy | $10.00/1k |
| `ReCaptchaV3EnterpriseM1TaskProxyLess` | V3 Enterprise M1 | Server proxy | $10.00/1k |
| `AntiAwsWafTaskProxyLess` | AWS WAF | Server proxy | ~$1.45/1k (already integrated) |

> **Note:** CapSolver's pricing page returned 404; V2 per-solve cost is ~$0.001–$0.00145 based on 2Captcha comparison and CapSolver's self-description as "cheapest." V3 standard is $1/1k per their docs.

### V2 Detection — How to Tell V2 vs V3

1. **V2 (checkbox):** Look for `<div class="g-recaptcha" data-sitekey="...">` or `grecaptcha.render()` in page source. The widget shows "I'm not a robot" checkbox.
2. **V2 Invisible:** No checkbox visible, but `grecaptcha.render()` is called with `size: 'invisible'`. Challenge appears on form submit.
3. **V3 (invisible, score-based):** Look for `grecaptcha.execute(siteKey, {action: '...'})` in JavaScript. No UI; returns a token with a score 0.0–1.0. Often returns 401 to scripts that don't pass the token.
4. **Enterprise:** Look for `grecaptcha.enterprise.render()` or `grecaptcha.enterprise.execute()`.

### API Request/Response Format

```python
# pip install capsolver   (or use raw requests as below)
import requests, time

API_KEY = os.environ["CAPSOLVER_API_KEY"]

# ---- reCAPTCHA V2 ----
payload = {
    "clientKey": API_KEY,
    "task": {
        "type": "ReCaptchaV2TaskProxyLess",
        "websiteURL": "https://target.gov/page",
        "websiteKey": "6Lc_ SITEKEY_HERE",
        # "isInvisible": False,          # for invisible V2
        # "pageAction": "submit",        # optional, if sa param in /anchor
    }
}
# ---- reCAPTCHA V3 ----
payload = {
    "clientKey": API_KEY,
    "task": {
        "type": "ReCaptchaV3TaskProxyLess",
        "websiteURL": "https://target.gov/page",
        "websiteKey": "6Lc_ SITEKEY_HERE",
        "pageAction": "login",            # found via grecaptcha.execute()
        # "isSession": True,              # if site uses session cookies
    }
}

# Create task
r = requests.post("https://api.capsolver.com/createTask", json=payload)
task_id = r.json()["taskId"]

# Poll for result
while True:
    time.sleep(2)
    r = requests.post("https://api.capsolver.com/getTaskResult",
                      json={"clientKey": API_KEY, "taskId": task_id})
    data = r.json()
    if data["status"] == "ready":
        token = data["solution"]["gRecaptchaResponse"]
        break
    if data.get("errorId", 0) != 0:
        raise Exception(data["errorDescription"])

# Submit token to target site
# For V2: inject into form field 'g-recaptcha-response'
# For V3: pass as header/param 'g-recaptcha-response' or cookie
```

### V3 Token Injection

For V3 (Lexington County probate, returns 401 to scripts):
- The token goes in the `g-recaptcha-response` form field or as a header
- Some sites expect it as a cookie `recaptcha-ca-t` (CapSolver returns this when `isSession: true`)
- The token expires in ~120 seconds — must be used immediately
- The `pageAction` must match what the site expects (e.g., `"login"`, `"submit"`, `"search"`)

### Python SDK

```python
# pip install --upgrade capsolver
import capsolver
capsolver.api_key = os.environ["CAPSOLVER_API_KEY"]

solution = capsolver.solve({
    "type": "ReCaptchaV2TaskProxyLess",
    "websiteURL": "https://target.gov/page",
    "websiteKey": "6Lc_SITEKEY",
})
token = solution["gRecaptchaResponse"]
```

### Existing Integration in Project

`enrichment_capsolver.py` already implements `solve_aws_waf()` for `AntiAwsWafTaskProxyLess`. It needs to be extended with `solve_recaptcha_v2()` and `solve_recaptcha_v3()` functions following the same pattern (async httpx, createTask → poll getTaskResult).

---

## 2. 2Captcha API — reCAPTCHA V2/V3

### Pricing (per 2Captcha pricing page, 2026-10-10)

| CAPTCHA Type | Price per 1000 | Solving Speed |
|---|---|---|
| reCAPTCHA v2 | $1.00 – $2.99 | 3 sec |
| reCAPTCHA v2 Callback | $1.00 – $2.99 | 2 sec |
| reCAPTCHA v2 Invisible | $1.00 – $2.99 | 2 sec |
| reCAPTCHA v3 (score ≤ 0.3) | $1.45 | 1 sec |
| reCAPTCHA v3 (score > 0.3) | $2.99 | 1 sec |
| reCAPTCHA Enterprise | $1.00 – $2.99 | 2 sec |
| Image/Math/Text Captcha | $0.50 – $1.00 | 1–5 sec |
| Amazon (AWS) captcha | $1.45 | 2 sec |

> **Cost comparison:** 2Captcha V2 is $1–$2.99/1k (most solves at $2.99). CapSolver V2 is ~$1–$1.45/1k. CapSolver V3 standard is $1/1k vs 2Captcha V3 at $1.45–$2.99/1k. **CapSolver is cheaper across the board.** 2Captcha may have higher reliability for some V2 cases due to human solvers, but CapSolver is faster and cheaper.

### API Format (nearly identical to CapSolver)

```python
import requests, time

API_KEY = os.environ["TWOCAPTCHA_API_KEY"]

# ---- reCAPTCHA V2 ----
payload = {
    "clientKey": API_KEY,
    "task": {
        "type": "RecaptchaV2TaskProxyless",
        "websiteURL": "https://target.gov/page",
        "websiteKey": "6Lc_SITEKEY",
        "isInvisible": False,
    }
}
r = requests.post("https://api.2captcha.com/createTask", json=payload)
task_id = r.json()["taskId"]

# Poll for result
while True:
    time.sleep(2)
    r = requests.post("https://api.2captcha.com/getTaskResult",
                      json={"clientKey": API_KEY, "taskId": task_id})
    data = r.json()
    if data["status"] == "ready":
        token = data["solution"]["gRecaptchaResponse"]
        break

# ---- reCAPTCHA V3 ----
payload = {
    "clientKey": API_KEY,
    "task": {
        "type": "RecaptchaV3TaskProxyless",
        "websiteURL": "https://target.gov/page",
        "websiteKey": "6Lc_SITEKEY",
        "pageAction": "login",
        "minScore": 0.3,    # minimum acceptable score
    }
}
```

### Python SDK

```python
# pip install 2captcha-python
from twocaptcha import TwoCaptcha
solver = TwoCaptcha(os.environ["TWOCAPTCHA_API_KEY"])
result = solver.recaptcha(sitekey="6Lc_KEY", url="https://target.gov/page")
token = result["code"]
```

### Key Differences from CapSolver

- 2Captcha uses `RecaptchaV2TaskProxyless` (note lowercase 'l') vs CapSolver's `ReCaptchaV2TaskProxyLess`
- 2Captcha returns `cost` and `solveCount` in the response
- 2Captcha V3 supports `minScore` parameter (0.1–0.9) to request specific score quality
- 2Captcha supports `RecaptchaV3EnterpriseTaskProxyless`

---

## 3. Gemini Vision for reCAPTCHA V2 Image Grids

### Current Project Usage (enrichment_waf_oss.py)

The project already uses `gemini-2.5-flash-lite` to solve **AWS WAF** 3×3 image-grid CAPTCHAs. The approach:
1. Screenshot the `<canvas>` element as base64 JPEG via `canvas.toDataURL()`
2. Send to Gemini API with prompt: *"This is a 3x3 grid. Which numbered tiles contain {target}? Reply with JSON array."*
3. Parse the response, click matching tiles, click Confirm

### Can Gemini Solve reCAPTCHA V2 Image Grids?

**Yes, technically** — reCAPTCHA V2's image challenge is a 3×3 or 4×4 grid (e.g., "Select all images with crosswalks"). The same Gemini Vision approach used for AWS WAF would work:

```python
# Adapt the existing _identify_tiles() function from enrichment_waf_oss.py
# reCAPTCHA V2 image grid: usually 3x3 (9 tiles) or 4x4 (16 tiles)
# The prompt needs to match reCAPTCHA's phrasing: "Select all squares with..."

async def solve_recaptcha_v2_grid(page, api_key: str) -> bool:
    """Solve reCAPTCHA V2 image challenge via Gemini Vision."""
    # 1. Click the reCAPTCHA checkbox iframe
    recaptcha_frame = page.frame_locator("iframe[src*='recaptcha/api2/anchor']").first
    await recaptcha_frame.locator("#recaptcha-anchor").click()

    # 2. Wait for challenge iframe
    challenge_frame = page.frame_locator("iframe[src*='recaptcha/api2/bframe']").first
    await challenge_frame.wait_for_selector(".rc-imageselect-target", timeout=10000)

    # 3. Extract target instruction ("Select all images with crosswalks")
    instruction = await challenge_frame.locator(".rc-imageselect-desc-no-canonical").inner_text()

    # 4. Screenshot the image grid
    grid = challenge_frame.locator("#rc-imageselect-target")
    grid_screenshot_b64 = await grid.screenshot()  # bytes → base64

    # 5. Ask Gemini which tiles match
    tiles = await _identify_tiles_gemini(grid_screenshot_b64, instruction, api_key)

    # 6. Click matching tiles
    for tile_num in tiles:
        # reCAPTCHA V2 tiles are <td> elements in a table
        await challenge_frame.locator(f"td:nth-child({tile_num})").click()

    # 7. Click Verify
    await challenge_frame.locator("#recaptcha-verify-button").click()
```

### Limitations

- **reCAPTCHA V2 image grids are more complex than AWS WAF:** tiles may be 3×3, 4×4, or single-image. Google also uses harder images (distorted, partial matches).
- **Google may detect automated clicking patterns** and serve harder challenges or block.
- **Rate limiting:** Free tier is 250 RPD (2.5-flash) or 1000 RPD (2.5-flash-lite). With 3 keys, ~750–3000 solves/day.
- **Reliability: ~60–80%** per solve (vs ~95%+ for paid services). May need 2–3 retries.
- **No headless:** Some sites detect headless browsers; need `headless=False` or stealth mode.

### Audio CAPTCHA via Speech-to-Text (Better Free Option for V2)

See section 5 below — audio CAPTCHA solving is more reliable (~80–90%) and doesn't require vision AI.

---

## 4. Free/Open-Source reCAPTCHA Solvers

### 4a. GoogleRecaptchaBypass (sarperavci) — ⭐ Best Free Option

- **Repo:** `github.com/sarperavci/GoogleRecaptchaBypass`
- **Stars:** ~3,500+
- **Method:** Audio challenge + Google Speech Recognition
- **Deps:** `DrissionPage` (or Selenium), `pydub`, `speech_recognition`, `ffmpeg`
- **Cost:** Free
- **Reliability:** ~80–90% per attempt, solves in <5 seconds
- **How it works:**
  1. Click the reCAPTCHA checkbox
  2. If challenge appears, click audio button
  3. Download the MP3 audio file
  4. Convert to WAV via pydub
  5. Transcribe via `speech_recognition.recognize_google()` (Google STT API, free)
  6. Submit the text answer
- **Limitation:** Google may block IP after too many solves; needs rotating IPs

```python
# pip install DrissionPage pydub SpeechRecognition
# apt install ffmpeg   (or brew install ffmpeg on macOS)

from DrissionPage import ChromiumPage
from RecaptchaSolver import RecaptchaSolver

driver = ChromiumPage()
driver.get("https://target.gov/page-with-recaptcha")
solver = RecaptchaSolver(driver)
solver.solveCaptcha()
# Token is now in the page's g-recaptcha-response field
token = solver.get_token()
```

### 4b. capsolver (ibedevesh) — Whisper-based Audio Solver

- **Repo:** `github.com/ibedevesh/capsolver`
- **Stars:** ~4 (new, but excellent code quality)
- **Method:** Audio challenge + faster-whisper (local, no API)
- **Deps:** `playwright`, `faster-whisper`, `requests`
- **Cost:** Free (runs Whisper locally on CPU)
- **Reliability:** ~90%+ (Whisper handles distorted audio better than Google STT)
- **Model sizes:** tiny (fastest) → base (recommended) → large-v3 (best accuracy)

```python
# pip install playwright faster-whisper requests
# playwright install chromium

from src.recaptcha_v2 import RecaptchaV2Solver

solver = RecaptchaV2Solver(model_size="base")
result = solver.solve("https://target.gov/page-with-recaptcha")
if result["success"]:
    token = result["token"]
```

### 4c. nonoCAPTCHA (mikeyy)

- **Repo:** `github.com/mikeyy/nonoCAPTCHA`
- **Stars:** ~893
- **Method:** Async audio challenge solving (Python, aiohttp)
- **Deps:** `aiohttp`, `asyncio`
- **Cost:** Free
- **Reliability:** ~70–80% (uses Google STT)

### 4d. Buster (dessant) — Browser Extension

- **Repo:** `github.com/dessant/buster`
- **Stars:** ~7,500+
- **Type:** Browser extension (Chrome/Firefox/Edge/Opera)
- **Method:** Audio challenge + speech recognition (client-side)
- **Cost:** Free
- **Use case:** Manual/interactive, NOT suitable for headless scraping automation
- **Can be adapted:** The client app simulates user interactions; could be driven via Playwright with extension loaded

### 4e. recaptcha-v2-solver (njraladdin) — Multi-method

- **Repo:** `github.com/njraladdin/recaptcha-v2-solver`
- **Stars:** ~51
- **Methods:**
  1. Audio (wit.ai STT) — 70–80% success, free
  2. 2Captcha (paid human) — 95%+, $2.99/1k
  3. Visual (Gemini Vision) — experimental
- **Language:** JavaScript/Node.js

### 4f. Theriley106/CaptchaFree

- **Repo:** `github.com/theriley106/CaptchaFree`
- **Stars:** ~8
- **Method:** Selenium wrapper with local audio transcription
- **Cost:** Free

---

## 5. Audio CAPTCHA Solving — Viable Approach

### How It Works

reCAPTCHA V2 provides an audio accessibility challenge. The audio is a short clip (~3–5 seconds) of distorted speech spelling out numbers or words. Modern speech-to-text handles this well.

### Step-by-Step

```python
import requests, tempfile, os
import speech_recognition as sr
import pydub  # pip install pydub
# Requires: ffmpeg installed (brew install ffmpeg / apt install ffmpeg)

async def solve_recaptcha_audio(page) -> str:
    """Solve reCAPTCHA V2 via audio challenge.
    Assumes page has reCAPTCHA V2 widget loaded."""

    # 1. Click the checkbox in the reCAPTCHA anchor iframe
    anchor_frame = page.frame_locator("iframe[src*='recaptcha/api2/anchor']").first
    await anchor_frame.locator("#recaptcha-anchor").click()
    await page.wait_for_timeout(2000)

    # 2. Check if solved without challenge (lucky click)
    if await anchor_frame.locator(".recaptcha-checkbox-checked").is_visible():
        return await get_token(page)

    # 3. Switch to challenge iframe, click audio button
    challenge_frame = page.frame_locator("iframe[src*='recaptcha/api2/bframe']").first
    await challenge_frame.locator("#recaptcha-audio-button").click()
    await page.wait_for_timeout(500)

    # 4. Download the audio file
    audio_src = await challenge_frame.locator("#audio-source").get_attribute("src")
    resp = requests.get(audio_src)
    mp3_path = tempfile.mktemp(suffix=".mp3")
    wav_path = tempfile.mktemp(suffix=".wav")
    with open(mp3_path, "wb") as f:
        f.write(resp.content)

    # 5. Convert MP3 → WAV (speech_recognition needs WAV)
    sound = pydub.AudioSegment.from_mp3(mp3_path)
    sound.export(wav_path, format="wav")

    # 6. Transcribe
    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio = recognizer.record(source)
    # Option A: Google STT (free, no API key)
    text = recognizer.recognize_google(audio)
    # Option B: Whisper (local, more accurate)
    # from faster_whisper import WhisperModel
    # model = WhisperModel("base", device="cpu", compute_type="int8")
    # segments, _ = model.transcribe(wav_path, language="en", beam_size=5)
    # text = " ".join(seg.text for seg in segments)

    # 7. Clean text (lowercase, alphanumeric only)
    text = "".join(c for c in text if c.isalnum() or c.isspace()).strip().lower()

    # 8. Submit answer
    await challenge_frame.locator("#audio-response").fill(text)
    await challenge_frame.locator("#recaptcha-verify-button").click()
    await page.wait_for_timeout(2000)

    # 9. Check if solved
    if await anchor_frame.locator(".recaptcha-checkbox-checked").is_visible():
        return await get_token(page)

    return None  # failed

async def get_token(page) -> str:
    return await page.evaluate(
        "document.getElementById('g-recaptcha-response').value"
    )
```

### Speech-to-Text Options

| Engine | Cost | Accuracy | Speed | API Key? |
|---|---|---|---|---|
| Google STT (`speech_recognition`) | Free | ~80% | Fast | No |
| faster-whisper (local) | Free | ~90%+ | ~2s (CPU) | No |
| OpenAI Whisper API | $0.006/min | ~95% | Fast | Yes |
| wit.ai (Meta) | Free | ~75% | Fast | Free key |

### Viability Assessment

- **Reliability:** 80–90% with Whisper, 70–80% with Google STT
- **Speed:** 3–8 seconds per solve
- **Cost:** Free
- **Limitation:** Google may rate-limit or block IPs after ~50–100 solves/day
- **Best for:** Low-volume sources (county deed searches, a few searches per run)
- **NOT suitable for:** V3 (V3 has no audio challenge) or Enterprise (may not have audio)
- **GitHub projects:** sarperavci/GoogleRecaptchaBypass (best), ibedevesh/capsolver (Whisper), mikeyy/nonoCAPTCHA

---

## 6. reCAPTCHA V3 Token Generation

### Can You Call Google's reCAPTCHA API Directly with the Sitekey?

**No.** reCAPTCHA V3 tokens cannot be generated by calling Google's API directly with just a sitekey. The token generation requires:

1. **A real browser environment** with the reCAPTCHA JavaScript loaded
2. **The `grecaptcha.execute(siteKey, {action: '...'})` call** which runs Google's fingerprinting/analysis code
3. **The resulting token** is tied to the browser session, user agent, IP, and behavioral signals

### Approaches for V3 Token Generation

#### Option A: CapSolver/2Captcha (Recommended)

The paid services generate V3 tokens on their backend infrastructure. They run real browsers with the target site's reCAPTCHA loaded. This is the only reliable way to get V3 tokens without a browser.

```python
# CapSolver V3
token = await solve_recaptcha_v3(
    website_url="https://lexingtoncounty.gov/probate-search",
    website_key="6Lc_SITEKEY",
    page_action="login",  # must match what the site expects
)
# Inject token as g-recaptcha-response header/param on the search request
```

#### Option B: Playwright Browser Execution

Load the page in Playwright, execute `grecaptcha.execute()` in the page context, and extract the token:

```python
async def get_v3_token_via_browser(page, sitekey: str, action: str) -> str:
    """Execute grecaptcha.execute() in a real browser to get a V3 token."""
    token = await page.evaluate(f"""
        async () => {{
            return new Promise((resolve) => {{
                grecaptcha.execute('{sitekey}', {{action: '{action}'}})
                    .then(token => resolve(token))
                    .catch(err => resolve(null));
            }});
        }}
    """)
    return token
```

**Limitations:**
- Requires the reCAPTCHA JS to be loaded on the page (must navigate to the real page)
- Token is tied to the browser session/IP — may not work if the API request comes from a different IP
- Token expires in ~120 seconds
- Google may assign a low score (0.1) to automated browsers, causing the server to reject it

#### Option C: Selenium/Playwright with grecaptcha.execute Override

```python
# Intercept the token after the page's own JS calls grecaptcha.execute()
async def intercept_v3_token(page):
    token = await page.evaluate("""
        () => {
            return new Promise((resolve) => {
                if (window.___grecaptcha_cfg) {
                    const original = grecaptcha.execute;
                    grecaptcha.execute = function(...args) {
                        return original.apply(this, args).then(token => {
                            window.__capturedToken = token;
                            resolve(token);
                            return token;
                        });
                    };
                }
            });
        }
    """)
    return token
```

### V3 for Lexington County Probate (Returns 401 to Scripts)

The 401 response means the server validates the V3 token server-side. Approach:
1. Navigate to the probate search page in Playwright (non-headless or stealth)
2. Wait for the page's own `grecaptcha.execute()` to fire (or trigger it manually)
3. Capture the token from `g-recaptcha-response` or the network request
4. Use the token + session cookies for subsequent API calls

If the browser-based approach doesn't get a high enough score, fall back to CapSolver V3 ($1/1k).

---

## 7. Math Question CAPTCHA (Brunswick NC)

### Detection

Brunswick NC deed search presents a simple math question like:
- "What is 3 + 7?"
- "What is 15 - 8?"
- "What is 4 × 6?"

### Solution: Parse + Eval

```python
import re

def solve_math_captcha(html: str) -> str:
    """Extract and solve a math question CAPTCHA from page HTML."""
    # Common patterns: "What is 3 + 7?", "3 + 7 = ?", "Solve: 15 - 8"
    patterns = [
        r'(?:what is|solve[:]?|answer[:]?|enter)\s*[:]?\s*'
        r'(\d+)\s*([+\-*/×÷x])\s*(\d+)',
        r'(\d+)\s*([+\-*/×÷x])\s*(\d+)\s*=\s*\?',
        r'(\d+)\s*([+\-*/×÷x])\s*(\d+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            a, op, b = match.groups()
            a, b = int(a), int(b)

            # Normalize operators
            op_map = {'×': '*', '÷': '/', 'x': '*'}
            op = op_map.get(op, op)

            # Safe eval (only allow basic arithmetic)
            if op == '+': result = a + b
            elif op == '-': result = a - b
            elif op == '*': result = a * b
            elif op == '/': result = a // b if b != 0 else 0
            else: continue

            return str(result)

    return None

# Usage with Playwright:
async def solve_brunswick_captcha(page):
    """Brunswick NC deed search — math question CAPTCHA."""
    # Get the math question from the page
    question_text = await page.locator(".captcha-question, .math-question").inner_text()
    # Or parse from page HTML
    html = await page.content()
    answer = solve_math_captcha(html)
    if answer:
        await page.locator("input[name='captcha_answer']").fill(answer)
        await page.locator("button[type='submit']").click()
```

### Safety Note

**Never use `eval()` on untrusted input.** The pattern-matching approach above only allows digits and basic operators. If you must use eval, restrict it:

```python
# Safe eval — only digits and +, -, *, /
if re.match(r'^[\d\s+\-*/]+$', expression):
    result = eval(expression, {"__builtins__": {}}, {})
```

### Reliability: ~100% (deterministic, no external dependencies)
### Cost: Free

---

## 8. Other CAPTCHA Types in the Project

### MERS ServicerID (CAPTCHA, type unknown)

- **Likely a simple image CAPTCHA** (distorted text/numbers) or reCAPTCHA V2
- **Solution:** 
  - If image text CAPTCHA: use CapSolver `ImageToTextTask` ($0.5–$1/1k) or 2Captcha `NormalCaptcha` ($0.5–$1/1k)
  - If reCAPTCHA V2: use CapSolver `ReCaptchaV2TaskProxyLess`
  - First, inspect the page to determine the CAPTCHA type

### NC eCourts Portal Hearing Search (CAPTCHA)

- **Likely reCAPTCHA V2 or V3** (NC courts use Google reCAPTCHA)
- **Solution:** Same as other reCAPTCHA sources — CapSolver V2 or V3

### US Courts Unclaimed Funds Locator (CAPTCHA)

- **Likely reCAPTCHA V2** (federal courts typically use Google reCAPTCHA)
- **Solution:** CapSolver `ReCaptchaV2TaskProxyLess` or audio solving

### Kofile/qPublic/Acclaim (reCAPTCHA + paywall)

- These are commercial county deed platforms with **both reCAPTCHA and a paid subscription wall**
- **Solution for CAPTCHA:** CapSolver V2 or V3 (depending on version)
- **Solution for paywall:** Requires valid subscription credentials; CAPTCHA solving alone won't bypass the paywall
- **Recommendation:** Skip these sources unless you have legitimate subscription access

---

## 9. Summary: Walled Source → Best Solution Matrix

| Walled Source | CAPTCHA Type | Best Solution | Cost/Solve | Reliability |
|---|---|---|---|---|
| **SC Secretary of State** (business filings) | reCAPTCHA V2 | CapSolver `ReCaptchaV2TaskProxyLess` | ~$0.001 | 95%+ |
| **Lexington County SC** (probate) | reCAPTCHA V3 invisible | CapSolver `ReCaptchaV3TaskProxyLess` | ~$0.001 | 90%+ |
| **Aiken SC** (tax-overage) | reCAPTCHA (V2 likely) | CapSolver `ReCaptchaV2TaskProxyLess` | ~$0.001 | 95%+ |
| **Beaufort SC** (deed search) | reCAPTCHA (V2 likely) | CapSolver `ReCaptchaV2TaskProxyLess` | ~$0.001 | 95%+ |
| **Jasper SC** (deed search) | reCAPTCHA (V2 likely) | CapSolver `ReCaptchaV2TaskProxyLess` | ~$0.001 | 95%+ |
| **Wake NC** (deed search) | reCAPTCHA V2 (entry disclaimer) | Audio solver (free) or CapSolver V2 | $0 / ~$0.001 | 80–95% |
| **Brunswick NC** (deed search) | Math question | Parse + eval (local) | $0 | ~100% |
| **Iredell NC** (deed search) | reCAPTCHA (V2 likely) | Audio solver or CapSolver V2 | $0 / ~$0.001 | 80–95% |
| **Craven NC** (deed search) | reCAPTCHA (V2 likely) | Audio solver or CapSolver V2 | $0 / ~$0.001 | 80–95% |
| **Greene NC** (deed search) | reCAPTCHA (V2 likely) | Audio solver or CapSolver V2 | $0 / ~$0.001 | 80–95% |
| **Harnett NC** (deed search) | reCAPTCHA (V2 likely) | Audio solver or CapSolver V2 | $0 / ~$0.001 | 80–95% |
| **Randolph NC** (deed search) | reCAPTCHA (V2 likely) | Audio solver or CapSolver V2 | $0 / ~$0.001 | 80–95% |
| **Stokes NC** (deed search) | reCAPTCHA (V2 likely) | Audio solver or CapSolver V2 | $0 / ~$0.001 | 80–95% |
| **Durham NC** (marriage index) | reCAPTCHA V2 (same gate as Wake) | Audio solver or CapSolver V2 | $0 / ~$0.001 | 80–95% |
| **Kofile/qPublic/Acclaim** | reCAPTCHA + paywall | CapSolver V2 (needs subscription too) | ~$0.001 | 95%+ (CAPTCHA only) |
| **MERS ServicerID** | Unknown (likely V2 or image) | CapSolver V2 or `ImageToTextTask` | ~$0.001 | 90%+ |
| **NC eCourts Smart Search** | AWS WAF image grid | Already solved (`enrichment_waf_oss.py`) | Free (Gemini) | 90%+ |
| **NC eCourts Portal** (hearing search) | reCAPTCHA (V2/V3) | CapSolver V2 or V3 | ~$0.001 | 90%+ |
| **US Courts Unclaimed Funds** | reCAPTCHA (V2 likely) | CapSolver `ReCaptchaV2TaskProxyLess` | ~$0.001 | 95%+ |

---

## 10. Recommended Implementation Strategy

### Tier 1: Free (Audio Solving) — For V2 Sources

Implement `enrichment_recaptcha_audio.py` using the Whisper-based approach:
- Use `faster-whisper` for transcription (best free accuracy)
- Drive via Playwright (already a project dependency)
- Fallback to CapSolver V2 if audio fails after 2 attempts
- Covers: Wake NC, Durham NC, Iredell/Craven/Greene/Harnett/Randolph/Stokes NC, Beaufort SC, Jasper SC, SC Secretary of State

```python
# pip install faster-whisper pydub
# brew install ffmpeg   (macOS)
# apt install ffmpeg    (Linux)
```

### Tier 2: Paid (CapSolver) — For V3 and Failed V2

Extend `enrichment_capsolver.py` with:
- `solve_recaptcha_v2(website_url, website_key, **opts)` → `ReCaptchaV2TaskProxyLess`
- `solve_recaptcha_v3(website_url, website_key, page_action, **opts)` → `ReCaptchaV3TaskProxyLess`
- `solve_recaptcha_v2_enterprise(website_url, website_key, **opts)` → `ReCaptchaV2EnterpriseTaskProxyLess`
- `solve_image_to_text(image_base64)` → `ImageToTextTask` (for MERS, simple text CAPTCHAs)

Covers: Lexington County (V3), Aiken SC, NC eCourts Portal, US Courts, MERS, fallback for all V2

### Tier 3: Local (Parse + Eval) — For Math CAPTCHA

Implement inline in the Brunswick NC scraper:
- Regex extraction of math expression
- Safe arithmetic evaluation
- Covers: Brunswick NC (math question)

### Tier 4: Existing (Gemini Vision) — For AWS WAF

Already implemented in `enrichment_waf_oss.py`:
- Covers: NC eCourts Smart Search
- Could be extended to reCAPTCHA V2 image grids as a free fallback

### Cost Estimate

- **Free tier:** Audio solving (Whisper) for V2 sources — $0
- **Paid tier:** CapSolver for V3 (Lexington) + fallback — ~$0.001/solve
- **Estimated weekly cost:** ~50 V3 solves × $0.001 = ~$0.05/week
- **$5 CapSolver deposit lasts ~2 years at this volume**

### Key Decisions

1. **CapSolver as primary paid service** (already integrated, cheapest, fastest)
2. **2Captcha as fallback** (higher reliability for stubborn V2, higher cost)
3. **Audio solving as free first attempt for V2** (Whisper > Google STT)
4. **Math parsing for Brunswick** (trivial, 100% reliable)
5. **Browser-based V3 token capture** for Lexington County (free, may need CapSolver fallback for low scores)
6. **Skip Kofile/qPublic/Acclaim** unless subscription access exists

---

## Appendix A: How to Detect reCAPTCHA Version on a Target Site

```python
import re

def detect_recaptcha_version(html: str) -> dict:
    """Detect reCAPTCHA version from page HTML."""
    info = {"version": None, "sitekey": None, "action": None, "enterprise": False}

    # Check for Enterprise
    if "grecaptcha.enterprise" in html or "enterprise.js" in html:
        info["enterprise"] = True

    # Extract sitekey
    key_match = re.search(r'data-sitekey="([^"]+)"', html)
    if key_match:
        info["sitekey"] = key_match.group(1)
    else:
        key_match = re.search(r'grecaptcha\.(?:execute|render)\(["\']([^"\']+)', html)
        if key_match:
            info["sitekey"] = key_match.group(1)

    # Detect V3: grecaptcha.execute() calls
    if "grecaptcha.execute" in html:
        info["version"] = "v3"
        action_match = re.search(r"grecaptcha\.execute\([^,]+,\s*\{[^}]*action:\s*['\"]([^'\"]+)", html)
        if action_match:
            info["action"] = action_match.group(1)
    # Detect V2: grecaptcha.render() or data-sitekey div
    elif "grecaptcha.render" in html or 'class="g-recaptcha"' in html:
        info["version"] = "v2"
        # Check for invisible
        if "size: 'invisible'" in html or 'size="invisible"' in html:
            info["version"] = "v2_invisible"
    # Detect via script src
    elif "recaptcha/api.js" in html or "recaptcha/enterprise.js" in html:
        if not info["version"]:
            info["version"] = "v2"  # api.js is used by both, but V2 is default

    return info
```

## Appendix B: 2Captcha vs CapSolver Quick Comparison

| Feature | CapSolver | 2Captcha |
|---|---|---|
| reCAPTCHA V2 price | ~$1.00/1k | $1.00–$2.99/1k |
| reCAPTCHA V3 price | $1.00/1k (standard) | $1.45–$2.99/1k |
| V3 Enterprise price | $3.00/1k | $1.00–$2.99/1k |
| V3 High-Score (M1) | $3.00–$10.00/1k | $2.99/1k (score > 0.3) |
| Solving speed | 1–10s | 1–3s |
| API format | createTask/getTaskResult | createTask/getTaskResult |
| Python SDK | `pip install capsolver` | `pip install 2captcha-python` |
| Already integrated | ✅ (enrichment_capsolver.py) | ❌ |
| Image-to-text | `ImageToTextTask` | `NormalCaptcha` |
| AWS WAF | `AntiAwsWafTaskProxyLess` ✅ | `AmazonCaptcha` |
| Math CAPTCHA | — | `MathCaptcha` ($0.50–$1/1k) |
| Free capacity/min | N/A | ~11,000 (V2), ~750 (V3) |

## Appendix C: pip Install Commands

```bash
# CapSolver SDK (already in project)
pip install capsolver

# 2Captcha SDK
pip install 2captcha-python

# Audio CAPTCHA solving (free)
pip install faster-whisper pydub SpeechRecognition
# System dep: ffmpeg (brew install ffmpeg / apt install ffmpeg)

# Playwright (already in project)
pip install playwright
playwright install chromium

# Google Gemini (already in project for WAF)
pip install google-generativeai
# Or use raw HTTP API as enrichment_waf_oss.py does
```
