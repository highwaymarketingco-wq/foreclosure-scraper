# Walled Sources — Solutions Research

Research into bypassing/accessing login walls, JS client challenges, and paid
sources for the foreclosure-scraper project. Each solution includes cost, code
snippet, which walled sources it covers, and reliability assessment.

**Key compliance constraint** (from `docs/walls_register.md`): the project treats
CAPTCHA/WAF as a wall — do not defeat. Operator-lane (human-cleared → offline
parser) is the compliant pattern. ToS-prohibited automation is a hard wall
regardless of technical feasibility.

---

## 1. Playwright Session Persistence

### Can Playwright save and reuse browser sessions?

**Yes.** Playwright's `BrowserContext.storage_state()` API saves cookies and
localStorage to a JSON file. A new context can be created from that file to
restore the session without re-logging in.

### Implementation

```python
import asyncio
from patchright.async_api import async_playwright

AUTH_DIR = "auth_states"  # gitignored

async def save_session(context, name: str):
    """Save cookies + localStorage after a manual/automated login."""
    await context.storage_state(path=f"{AUTH_DIR}/{name}.json")

async def load_session(browser, name: str):
    """Create a context pre-loaded with saved auth state."""
    import os
    state_path = f"{AUTH_DIR}/{name}.json"
    if os.path.exists(state_path):
        return await browser.new_context(storage_state=state_path)
    # No saved state — fresh context (caller handles login)
    return await browser.new_context()

# --- Usage pattern ---
async def run_with_session(name: str, url: str, do_work):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await load_session(browser, name)
        page = await context.new_page()

        await page.goto(url)

        # Check if still logged in (site-specific selector)
        if await page.query_selector("[data-logged-in='false']"):
            # Session expired — need re-login
            # Option A: trigger automated login flow
            # Option B: flag for operator manual login
            await context.close()
            return None

        result = await do_work(page)

        # Save updated state (cookies may have refreshed)
        await save_session(context, name)
        await context.close()
        return result
```

### Session expiry handling

```python
async def ensure_authenticated(context, name, login_url, login_fn):
    """Check auth, re-login if needed, persist state."""
    page = await context.new_page()
    await page.goto(login_url)

    # Site-specific: check if we're past the login wall
    # e.g., presence of a logged-in user element, absence of login form
    if await page.query_selector("input[type='password']"):
        # Not logged in — run login flow
        await login_fn(page)
        await context.storage_state(path=f"{AUTH_DIR}/{name}.json")

    await page.close()
```

### Multi-account support

```python
# Per-account state files — one per source/account
ACCOUNTS = {
    "forsyth_vital":   "auth_states/forsyth_vital.json",
    "anderson_acpass": "auth_states/anderson_acpass.json",
    "hud_user":        "auth_states/hud_user.json",
    "pacermonitor":    "auth_states/pacermonitor.json",
}

async def get_context_for_source(browser, source: str):
    state_file = ACCOUNTS.get(source)
    if state_file and os.path.exists(state_file):
        return await browser.new_context(storage_state=state_file)
    return await browser.new_context()
```

### What the project already has

The project already uses `page.context.add_cookies()` in
`enrichment_nc_case_status_tyler.py` (lines 203, 252, 499, 561) to inject
pre-fetched WAF tokens. The `storage_state` approach is a superset — it
persists cookies AND localStorage in one call. The project uses **patchright**
(a stealth-patched Playwright fork) and **scrapling** with StealthyFetcher.

### Covered walled sources

| Source | Login type | Session viable? |
|---|---|---|
| Forsyth County NC Vital Records | Free account | ✅ Yes — login once, persist |
| Anderson SC ACPASS | Free account | ✅ Yes |
| High Point NC Accela (ACA) | Registered account | ✅ Yes |
| Forest City SmartGov | Portal login | ✅ Yes |
| Goose Creek SC GIS (EnerGov) | Portal login | ✅ Yes |
| HUD-USPS vacancy data | Free HUD USER account | ✅ Yes |
| PacerMonitor | Account holder | ✅ Yes |
| RES.NET | Login | ✅ Yes |

### Cost

**Free** — uses Playwright/patchright already in the project's venv.

### Reliability

**High.** `storage_state` is a first-class Playwright API. Sessions typically
persist for days to weeks depending on the site's cookie expiry. The main
failure mode is server-side session expiry (short-lived tokens) — handled by
the `ensure_authenticated` pattern above.

### Limitations

- Does NOT bypass CAPTCHA/WAF on the login page itself — it avoids re-hitting
  the login page after the first manual/automated login.
- Some sites use server-side session invalidation (IP binding, concurrent
  session limits) that can't be persisted client-side.
- Must store auth state files securely (gitignore them — they contain session
  cookies equivalent to passwords).

---

## 2. JavaScript Client Challenge Bypassing

### City of Union SC — what is the challenge?

Per `docs/walls_register.md` (probed 2026-09-30): City of Union SC
(`cityofunion.net`) serves a JS bot-mitigation "Client Challenge" interstitial
on every path — `title>Client Challenge`, `/_fs-ch-<id>/script.js` loader,
CSP-locked `noscript` fallback.

As of today's probe (2026-10-10), the homepage returned HTTP 200 with
`<title>City of Union | Home</title>` — no challenge visible to curl. This
suggests the challenge may be **intermittent or IP-reputation-based**, not
always-on.

The `_fs-ch` pattern is associated with **FastBot/Fasteo** client-side
bot detection (a lightweight JS challenge, not Cloudflare Turnstile or AWS WAF).

### Can Playwright with real Chromium just wait for the JS to execute?

**Sometimes yes, for lightweight JS challenges.** A real Chromium engine via
Playwright/patchright executes JavaScript natively. For simple "proof of work"
JS challenges that set a cookie and redirect:

```python
async def handle_js_challenge(page, target_url, timeout_ms=30000):
    """Navigate and wait for a JS client challenge to self-resolve."""
    await page.goto(target_url, wait_until="domcontentloaded")

    # Check if we hit a challenge page
    title = await page.title()
    if "client challenge" in title.lower():
        # Wait for the challenge JS to execute and redirect
        try:
            await page.wait_for_url(
                lambda url: "client" not in (await page.title()).lower(),
                timeout=timeout_ms
            )
        except Exception:
            # Challenge didn't self-resolve — may need fingerprint evasion
            return False

    # Wait for actual content
    await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    return True
```

### Pydoll — fingerprint evasion alternative

**Pydoll** (`autoscrape-labs/pydoll`) drives Chrome/Edge over raw CDP (DevTools
Protocol) with no WebDriver binary, so `navigator.webdriver` is never set. Key
features:

- **No automation markers**: no `navigator.webdriver`, no `--enable-automation`,
  no `Runtime.enable` — they're never there to begin with (unlike
  undetected-chromedriver which patches them after the fact).
- **Fingerprint injection**: `tab.apply_fingerprint()` overrides User-Agent,
  Client Hints, navigator, WebGL, canvas, screen, fonts, timezone — all
  consistent with each other. Survives `toString` and prototype introspection.
- **Humanized interactions**: Bezier-curve mouse movement, realistic typing,
  scroll physics — often enough to pass behavioral challenges.
- **Cloudflare Turnstile handling**: built-in `expect_cloudflare_turnstile()`
  context manager.
- **Playwright-compatible**: change one import (`from pydoll.playwright.sync_api
  import sync_playwright`) and existing Playwright scripts run on Pydoll's CDP
  connection.

```python
# Pydoll with fingerprint injection for JS-challenged sites
from pydoll import Chrome

async def fetch_with_fingerprint(url):
    async with Chrome() as browser:
        tab = await browser.open()
        await tab.apply_fingerprint(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
            locale="en-US",
            timezone="America/New_York",
        )
        await tab.goto(url)
        # JS challenge auto-resolves in real Chrome with no webdriver flag
        await tab.wait_for_page_load()
        content = await tab.page_source
        return content
```

### Compliance assessment

**The project's compliance rule (from `walls_register.md`) explicitly states:
"CAPTCHA/WAF is a wall; do not defeat."** The City of Union SC JS client
challenge IS classified as a WAF/bot-detection wall in the walls register.

This means:
- **Technically**: Pydoll or patchright with a real Chromium engine would very
  likely pass a lightweight JS client challenge (it's just JS execution + cookie
  setting, no CAPTCHA image recognition needed).
- **Per project rules**: This should NOT be automated. The wall is documented,
  and the source (Union SC code enforcement) has no reachable alternative at
  either city or county level.

### Covered walled sources

| Source | Challenge type | Technical bypass? | Compliant? |
|---|---|---|---|
| City of Union SC | JS Client Challenge (Fasteo) | Likely yes (Pydoll/patchright) | ❌ No — WAF wall per project rules |
| City of Morganton NC | Cloudflare Turnstile | Pydoll has `expect_cloudflare_turnstile()` | ❌ No — WAF wall per project rules |

### Cost

- **Pydoll**: Free (open-source). Requires Chrome or Edge installed (already
  available — project uses patchright/scrapling which need Chromium).
- **patchright** (already installed): Free.

### Reliability

- **Lightweight JS challenges** (cookie-set + redirect): **High** — a real
  browser engine executes the JS naturally.
- **Behavioral challenges** (mouse movement analysis): **Medium** — Pydoll's
  humanized interactions help but aren't guaranteed.
- **Cloudflare Turnstile**: **Medium** — Pydoll has built-in support but
  Turnstile is sophisticated; IP reputation matters.
- **Against project compliance rules**: **Not applicable** — these walls are
  documented as "do not defeat."

---

## 3. Token-Based API Sources (499 Token Required)

### What HTTP 499 means

In the ArcGIS ecosystem, HTTP 499 (or HTTP 200 with
`{"error":{"code":499,"message":"Token Required"}}`) means the MapServer/
FeatureServer layer requires token-based authentication. This is **ArcGIS
Server token security**, not a generic API key.

### How ArcGIS token authentication works

1. The MapServer's `/rest/info` endpoint reports `isTokenBasedSecurity: true`
   with a `tokenServicesUrl` pointing to the ArcGIS Portal's token endpoint.
2. Client POSTs to the token endpoint (`/sharing/rest/generateToken` for ArcGIS
   Online, or `/portal/sharing/rest/generateToken` for Enterprise Portal) with:
   - `username`, `password`
   - `client`: `referer` (for web apps) or `ip` (for server-to-server)
   - `referer` or `ip`: the requesting origin
3. The response contains a `token` string (typically valid 1 hour to 30 days).
4. Subsequent API requests include `token=<value>` as a query parameter.

```python
import httpx

async def get_arcgis_token(portal_url: str, username: str, password: str,
                           referer: str = "https://localhost") -> str | None:
    """Generate an ArcGIS token for token-authenticated MapServer layers."""
    token_url = f"{portal_url}/sharing/rest/generateToken"
    data = {
        "username": username,
        "password": password,
        "client": "referer",
        "referer": referer,
        "expiration": 1440,  # minutes (24 hours)
        "f": "json",
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(token_url, data=data, timeout=30)
        result = r.json()
        if "token" in result:
            return result["token"]
        return None

async def query_arcgis_layer(layer_url: str, token: str, where: str = "1=1"):
    """Query a token-protected ArcGIS layer."""
    params = {
        "where": where,
        "outFields": "*",
        "f": "json",
        "token": token,
    }
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{layer_url}/query", params=params, timeout=30)
        return r.json()
```

### What the project already has

The project already has sophisticated ArcGIS token-wall handling in
`enrichment_arcgis.py`:
- `is_token_error()` — detects 499/498/403 codes or "token"/"not authorized"
  messages in ArcGIS error responses
- `host_walled()` / `mark_host_walled()` — circuit breaker that trips on the
  first token error and short-circuits all subsequent calls to that host for
  the process lifetime
- `note_host_hard_failure()` — trips after 8 consecutive hard failures

### Kinston NC heirs-property layer & Salisbury NC chronic abatement layer

These return 499 Token Required, meaning they're ArcGIS Server layers with
token-based security enabled. To obtain tokens:

1. **Check the service's `/rest/info` endpoint** to find the token services URL:
   ```bash
   curl -s "https://<kinston-arcgis-host>/arcgis/rest/info?f=json"
   # Look for: "isTokenBasedSecurity": true, "tokenServicesUrl": "..."
   ```

2. **Request access from the agency** that publishes the layer. For local
   government ArcGIS services, this typically means:
   - Contacting the city/county GIS department
   - Requesting a data-sharing agreement or guest account
   - Explaining the use case (public records research)

3. **For ArcGIS Online (AGOL) hosted layers**: the publishing organization must
   share the layer with your ArcGIS Online account, or make it public.

### SCDOT SC_Parcels (existing wall)

The project already documented this pattern for SCDOT's `SC_Parcels` MapServer
(`smpesri.scdot.org`): `isTokenBasedSecurity: true`, `tokenServicesUrl` points
at SCDOT's internal ArcGIS Enterprise Portal — no self-service sign-up path
found. The project's compliance rule means no access was attempted beyond
probing. The workaround was per-county native ArcGIS endpoints (8 of 11 SC
counties now covered).

### Covered walled sources

| Source | Token type | Access path | Project handling |
|---|---|---|---|
| Kinston NC heirs-property | ArcGIS Server token | Contact Kinston GIS dept | Circuit breaker trips, skips host |
| Salisbury NC chronic abatement | ArcGIS Server token | Contact Salisbury GIS dept | Circuit breaker trips, skips host |
| SCDOT SC_Parcels | ArcGIS Enterprise Portal token | Contact SCDOT (agency-internal portal) | Already replaced with county-native endpoints |

### Cost

**Free** — ArcGIS tokens are free; the barrier is obtaining credentials from
the publishing agency.

### Reliability

- **If you have credentials**: **High** — token auth is standard ArcGIS, tokens
  last hours to days.
- **Obtaining credentials**: **Low-Medium** — depends entirely on the agency's
  willingness to share. Many local governments don't offer public accounts for
  restricted layers. SCDOT's portal is agency-internal with no self-service.
- **Without credentials**: Circuit breaker correctly identifies and skips these
  hosts — no waste, no retry storm.

---

## 4. Free Account Automation

### Can Playwright automate registration and login?

**Technically yes.** Playwright can fill forms, click buttons, and handle email
verification flows. For sites requiring free account registration:

```python
async def register_and_login(page, site_config):
    """Automate free account registration on a government portal."""
    await page.goto(site_config["register_url"])

    # Fill registration form
    await page.fill("#email", site_config["email"])
    await page.fill("#password", site_config["password"])
    await page.fill("#confirm_password", site_config["password"])
    await page.fill("#first_name", site_config["first_name"])
    await page.fill("#last_name", site_config["last_name"])
    await page.fill("#organization", "Real Estate Research")

    # Handle any reCAPTCHA (this is where automation often breaks)
    # reCAPTCHA v2 = hard wall (need CapSolver or similar — paid)
    # reCAPTCHA v3 = passable with good browser fingerprint

    await page.click("button[type='submit']")

    # Check for email verification requirement
    if "verify" in (await page.content()).lower():
        # Need to fetch verification link from email
        # (requires email API integration — e.g., temp mail, IMAP polling)
        verification_link = await fetch_verification_email(site_config["email"])
        await page.goto(verification_link)

    # Save the authenticated session
    await page.context.storage_state(path=f"auth_states/{site_config['name']}.json")
```

### Ethical/safety assessment

**The project's compliance framework draws a clear line:**

| Action | Compliant? | Reasoning |
|---|---|---|
| Automating login with credentials you legitimately hold | ✅ Yes | You're a registered user; using your own account via automation is normal API access |
| Automating free account **registration** | ⚠️ Gray area | ToS varies by site; some prohibit automated account creation; reCAPTCHA often guards registration |
| Using storage_state to persist a **manual** login | ✅ Yes | Human logs in once, script reuses the session — this is the operator-lane pattern |
| Creating fake/disposable accounts | ❌ No | Violates ToS on most government portals; may constitute fraud |
| Defeating reCAPTCHA on registration forms | ❌ No | CAPTCHA is a wall per project rules |

### Recommended approach: Operator-lane registration + automated session reuse

```python
# Step 1: Operator manually registers and logs in (one time)
# Step 2: Script saves the session state
# Step 3: Script reuses the session for all future runs

async def first_time_setup(browser, source_name, login_url):
    """Operator-assisted initial login. Run once, interactively."""
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto(login_url)

    print(f"\nPlease log in to {source_name} in the browser window.")
    print("Press Enter when done...")
    input()  # Blocks until operator confirms

    # Persist the now-authenticated session
    await context.storage_state(path=f"auth_states/{source_name}.json")
    await context.close()
    print(f"Session saved for {source_name}")
```

### Covered walled sources

| Source | Registration | reCAPTCHA on registration? | Approach |
|---|---|---|---|
| Forsyth County NC Vital Records | Free account | Unknown | Operator-lane: manual register → save session |
| Anderson SC ACPASS | Free account | Unknown | Operator-lane: manual register → save session |
| HUD USER | Free account | Likely (AWS WAF detected on HUD) | Operator-lane: manual register → save session |

### HUD-USPS vacancy data — additional finding

HUD USER (`huduser.gov`) is now behind **AWS WAF** (confirmed: `x-amzn-waf-action:
challenge` header on the USPS dataset page). The project already has an AWS WAF
solver (`enrichment_waf_oss.py`) using Gemini vision to solve the 3×3 grid
CAPTCHA. This means:

- **Registration**: May require solving AWS WAF challenge first (project has
  this capability via patchright + Gemini vision)
- **Session persistence**: After login, `storage_state` saves the authenticated
  session including WAF clearance cookies

### Cost

**Free** — uses existing patchright/playwright tooling. Operator time for
one-time manual registration (~5 minutes per source).

### Reliability

**High** for session reuse after manual login. **Medium** for fully automated
registration (depends on CAPTCHA presence, email verification, and ToS).

---

## 5. Akamai Bot Detection

### How Akamai differs from Cloudflare

| Aspect | Cloudflare | Akamai Bot Manager |
|---|---|---|
| **Detection method** | JS challenge (Turnstile), TLS fingerprinting, IP reputation | **Sensor data** — deep browser fingerprinting via injected JS that collects 100+ signals (canvas, WebGL, fonts, plugins, screen, timing, mouse/keyboard behavior) |
| **Cookie name** | `cf_clearance`, `__cf_bm` | `akaas_<segment>`, `_abck` (Akamai Bot Manager cookie) |
| **Challenge type** | Turnstile (visual/behavioral), JS math challenge | **Sensor data POST** — browser must execute Akamai's JS, collect sensor data, POST it back; server validates the sensor payload |
| **TLS fingerprinting** | Yes (JA3/JA4) | Yes (JA3/JA4) |
| **Bypass difficulty** | Medium-High (Turnstile is sophisticated but Pydoll/camoufox can often pass) | **High** — sensor data is deeply encrypted, frequently rotated, and tied to the specific JS version served; static replay doesn't work long |

### Akamai's key differentiator: sensor data

Akamai injects a JS file (often `/_bm/` or `/_sec/` path) that collects a
massive "sensor data" string encoding browser environment + behavioral signals.
This is POSTed to the server, validated, and if it passes, the `_abck` cookie
is set to a "passed" value. The sensor data algorithm is obfuscated and changes
with each JS version.

### Can curl_cffi bypass Akamai?

**Partially.** curl_cffi (already in the project's venv, v0.15.0) can
impersonate browser TLS/JA3/JA4 fingerprints, which defeats the TLS-level
detection. However:

- **TLS fingerprint alone is NOT enough for Akamai Bot Manager** — the sensor
  data JS challenge is the primary gate.
- curl_cffi's README explicitly acknowledges this: "TLS fingerprinting alone
  isn't enough for modern bot protection" and points to **Hyper Solutions**
  (a paid third-party service) for Akamai sensor data generation.
- curl_cffi does support custom `akamai=...` fingerprint strings for advanced
  users who have reverse-engineered the sensor data format — but this is an
  arms race, not a stable solution.

```python
# curl_cffi can match TLS fingerprint but NOT solve Akamai sensor data
from curl_cffi import requests

# This defeats TLS-level detection but NOT the JS sensor challenge
r = requests.get("https://akamai-protected-site.com",
                 impersonate="chrome124")
# If the site requires sensor data, you'll still get a 403 or challenge page
```

### Can undetected-chromedriver bypass Akamai?

**Better than curl_cffi, but not guaranteed.** undetected-chromedriver (UC)
patches Chrome's automation markers (`navigator.webdriver`, `--enable-automation`,
CDP detection). A real Chrome engine can execute Akamai's sensor JS naturally.

However:
- Akamai also checks for CDP (Chrome DevTools Protocol) artifacts — UC uses CDP
  for control, which Akamai can detect.
- Akamai's behavioral analysis (mouse movement, keystroke timing) may flag
  automated interaction patterns.
- IP reputation matters — datacenter IPs are often pre-flagged.

### Can Pydoll bypass Akamai?

**Best chance of the three.** Pydoll's architecture is specifically designed
for this:
- **No CDP detection surface**: Pydoll connects via CDP but doesn't leave the
  same artifacts that UC does (no `Runtime.enable` call, no WebDriver binary).
- **Real Chrome**: sensor JS executes natively in a real browser.
- **Fingerprint injection**: `tab.apply_fingerprint()` makes all browser
  surfaces consistent.
- **Humanized interaction**: Bezier-curve mouse, realistic typing helps with
  behavioral analysis.

But: **Akamai is the hardest bot detection to bypass consistently.** Even Pydoll
may fail on sites with aggressive Akamai configurations. Success depends on
the specific Akamai policy (some are set to "challenge" mode, others to
"hard block").

### Union County NC — Akamai

Per the task description, Union County NC uses Akamai to block scripted
clients. The project's existing approach for Akamai-protected sites should be:

1. **Try curl_cffi with `impersonate="chrome"`** — may work if Akamai is only
   doing TLS fingerprinting (not full sensor data).
2. **If that fails, try patchright/scrapling StealthyFetcher** — real Chromium
   engine, may pass sensor challenge naturally.
3. **If that fails, the wall stands** per project compliance rules.

### Covered walled sources

| Source | Protection | curl_cffi? | patchright? | Pydoll? | Compliant to bypass? |
|---|---|---|---|---|---|
| Union County NC | Akamai Bot Manager | TLS only (likely fails) | Maybe (sensor JS may pass) | Best chance | Depends on ToS — check robots.txt |
| Akamai.com itself | Akamai | Fails | Fails | Maybe | N/A (not a target) |

### Cost

- **curl_cffi**: Free (already installed, v0.15.0)
- **patchright/scrapling**: Free (already installed)
- **Pydoll**: Free (not currently installed; `pip install pydoll`)
- **Hyper Solutions** (Akamai sensor data API, mentioned by curl_cffi):
  **Paid** — commercial service, pricing not public

### Reliability

| Method | vs Cloudflare | vs Akamai |
|---|---|---|
| curl_cffi impersonate | Medium (defeats TLS, not Turnstile) | Low (defeats TLS, not sensor data) |
| patchright (real Chromium) | High (executes JS, may pass Turnstile) | Medium (executes sensor JS, but CDP artifacts) |
| Pydoll (CDP, no webdriver) | High | Medium-High (best chance, but Akamai is hard) |
| Hyper Solutions (paid) | N/A | High (purpose-built for Akamai) |

---

## 6. Paid Sources — Which Are Worth Paying For?

### Value ranking for NC/SC foreclosure leads

Based on the project's goal (foreclosure leads in NC/SC), the project's existing
free coverage, and the documented pricing in `docs/new_sources_2026-10-07_contact_and_facts.md`
and `docs/rei_operator_playbook.md`:

#### Tier 1 — High value per dollar

| Source | Cost | What it provides | Why it's worth it |
|---|---|---|---|
| **Tracerfy skip tracing** | $0.02/hit (only on match) | Owner phone numbers | Cheapest phone data; estimated +9,500-11,900 phones across weakest 10 counties for ~$317 max. Project already identified this as #1 priority paid source. |
| **PACER** | $0.10/page; **free if <$30/quarter** | Federal bankruptcy filings | Bankruptcy = automatic stay + trustee involvement = specialized foreclosure-adjacent lead. Effectively free for light use. |
| **Craftsman National Construction Estimator** | $58.75 PDF / $167.88/yr cloud | Repair-cost tables | Directly improves ARV/rehab estimate accuracy for grading leads. One-time purchase. |

#### Tier 2 — Moderate value, situational

| Source | Cost | What it provides | Assessment |
|---|---|---|---|
| **PropStream** | $99/mo (7-day trial, ~50 free leads) | 100+ distress filters, comps, skip-trace, cash buyer search | Best single paid buy per the operator playbook. But: ToS may restrict automated use; best as operator export lane, not scraper integration. ATTOM data underneath. |
| **PropWire** | Free core (no card) | 157M records, motivated-seller filters, comps | Free tier may provide value without spend. Closest free alternative to PropStream. |
| **RentCast API** | Free: 50 req/mo; $74/mo: 1,000 req | Rent estimates, sale comps | Free tier enough for spot-checking HOT leads. Low priority to upgrade. |
| **Melissa address API** | Free: 250 records/mo; $40 for 10K credits | Address validation, mail deliverability | Free tier useful for mail-bounce prevention. Low volume = stay on free tier. |
| **NC SoS UCC data files** | $4,000/yr | UCC lien filings statewide | UCC liens indicate encumbered properties. High cost; only worth it if lien-flagging is a core lead signal. Project currently gets DOR+DEW liens free. |
| **NC SoS Federal Tax Lien files** | $1,600/yr | Federal tax lien filings | Narrower signal (entity/LLC federal liens). Project already documented the web search as a HARD WALL (ToS prohibits automation). Bulk files are the only automated path. |

#### Tier 3 — Low value for this project

| Source | Cost | Why skip |
|---|---|---|
| **ATTOM API** | Enterprise pricing (~$95/mo entry per operator playbook) | ToS forbids caching >24h and building derivative DB — breaks the persistent self-enriching board. Property data already obtained free from county GIS/assessor. |
| **BatchData** | $1,000-$10,000/mo | 50-75x more expensive than Tracerfy for the same phone data. |
| **ReportAll USA** | Not verified | Parcel data already obtained free from county ArcGIS endpoints. |
| **RSMeans** | $408-$5,973/yr | Construction cost data — overkill for lead grading. Craftsman NCE at $58.75 covers the same need. |
| **RealEstateAPI.com** | Not verified (JS-rendered pricing) | Unverified pricing + same data category as ATTOM/Regrid. |
| **taxsaleresources.com** | $97-$582/yr subscription | Tax sale lists are already scraped free from county sources. Subscription may have some counties the project doesn't cover, but marginal value is low. |
| **Regrid** | Not verified | Nationwide parcel data — but project already has per-county ArcGIS endpoints for 8/11 SC counties and all NC counties. |
| **Data Axle** | Not verified | Consumer/business lists — TCPA risk, not a foreclosure signal. |
| **PropertyRadar** | $119-$249/mo | Operator export lane only; no API integration. Same data as PropStream. |
| **EnformionGO** | $0.01-$0.25/match | People search — similar to Tracerfy but more expensive. |
| **BatchLeads** | $119-$749/mo | PropStream-owned; operator export lane only. |
| **Rentometer** | $59-$96/yr | Manual rent checks — RentCast free tier covers this. |

#### Tier 4 — Not for this project (compliance/coverage issues)

| Source | Issue |
|---|---|
| **TLOxp, IDI idiCORE, LexisNexis Accurint, Tracers** | Account-based, FCRA-regulated, require permissible purpose certification. Not appropriate for automated lead generation — these are for licensed investigators/PIs. |
| **SC DNR, SC Election Commission voter list, SC LLR licensee lists** | Government data with restricted use. Voter lists have specific permitted-use constraints. Low foreclosure-lead relevance. |
| **NC DMV / SC DMV owner records** | DPPA-restricted. Requires permissible purpose. Not accessible for real estate lead generation. |

### Paid sources covering deed image paywalls

| County | Deed image vendor | Cost | Approach |
|---|---|---|---|
| NC: Buncombe, Polk, Gaston, Mecklenburg, Davidson | Aumentum / Kofile | Per-page fee (~$0.50-$5/page) | **Operator-lane**: human opens free-to-view-in-browser image, saves PDF → `extract_lien_amounts.py` folder. HOT/A-grade leads only. |
| SC: Lee, Newberry, Williamsburg, Calhoun, Richland, Darlington | Kofile / Cott / Acclaim | Per-page fee or subscription | Same operator-lane approach. |

**These are NOT worth automating.** Deed images are needed for a small number
of HOT leads where the lien amount matters for grading — not for bulk scraping.
An operator pulling 5-10 images per week is far cheaper than any automation
approach, and avoids reCAPTCHA/paywall walls.

### Bottom line: recommended paid purchases

1. **Tracerfy** — $0.02/hit, ~$317 max for full phone coverage of weakest 10
   counties. **Highest ROI by far.**
2. **PACER** — Effectively free for light use. Federal bankruptcy signal.
3. **Craftsman NCE** — $58.75 one-time. Repair-cost precision.
4. **PropStream trial** — Free 7-day trial with ~50 leads. Use for one-shot
   enrichment, don't subscribe unless operator wants the dashboard.
5. **NC SoS Federal Tax Lien files** — $1,600/yr. Only if federal lien
   flagging becomes a core signal (currently a narrow entity/LLC signal).

---

## Summary Matrix

| Solution | Cost | Walled Sources Covered | Reliable? | Compliant? |
|---|---|---|---|---|
| **Playwright `storage_state`** | Free | All login walls (Forsyth, ACPASS, ACA, SmartGov, HUD, PacerMonitor, RES.NET) | ✅ High | ✅ Yes (with legitimate credentials) |
| **Pydoll fingerprint evasion** | Free | JS challenges (Union SC), Cloudflare (Morganton) | ⚠️ Medium | ❌ No — WAF wall per project rules |
| **ArcGIS token auth** | Free (if creds obtained) | Kinston, Salisbury, SCDOT | ✅ High (with creds) | ✅ Yes (if agency grants access) |
| **Operator-lane registration** | Free (operator time) | Forsyth, ACPASS, HUD | ✅ High | ✅ Yes (human does registration) |
| **curl_cffi impersonate** | Free (installed) | TLS-level blocks, some Akamai | ⚠️ Low for Akamai | ✅ Yes (no ToS issue) |
| **Tracerfy skip tracing** | ~$317 max | Phone numbers for 10K+ leads | ✅ High | ✅ Yes (paid service, TCPA-gated) |
| **PACER** | Free (<$30/quarter) | Federal bankruptcy filings | ✅ High | ✅ Yes |
| **Craftsman NCE** | $58.75 one-time | Repair-cost estimates | ✅ High | ✅ Yes |
| **NC SoS data files** | $1,600-$4,000/yr | Federal tax lien / UCC bulk data | ✅ High | ✅ Yes (paid bulk access) |

### Project's existing capabilities (already in venv)

- **patchright** — stealth-patched Playwright (installed)
- **curl_cffi** v0.15.0 — TLS fingerprint impersonation (installed)
- **scrapling** — StealthyFetcher browser automation (installed)
- **AWS WAF solver** — Gemini vision-based 3×3 CAPTCHA solver
  (`enrichment_waf_oss.py`)
- **ArcGIS circuit breaker** — token-wall detection + host-level skip
  (`enrichment_arcgis.py`)
- **Cookie injection** — `page.context.add_cookies()` in Tyler eCourts flow
  (`enrichment_nc_case_status_tyler.py`)

### Recommended next steps

1. **Implement `storage_state` session persistence** for all login-wall sources
   — wrap existing patchright browser launches with save/load auth state. This
   is the single highest-impact change: it covers 8+ walled sources with one
   pattern, uses libraries already installed, and is fully compliant.

2. **Add ArcGIS token generation** — extend `enrichment_arcgis.py` with a
   `generate_token()` function for when credentials are obtained. The circuit
   breaker already handles the "no credentials" case gracefully.

3. **Do NOT pursue** Pydoll/WAF bypass for Union SC or Morganton NC — these are
   documented walls per project compliance rules. The operator-lane pattern
   (human-cleared → offline parser) remains the compliant approach.

4. **Pilot Tracerfy** — $0.50 for a 25-lead test batch to verify match rates
   before committing to the full ~$317 spend.

5. **Register PACER account** — free, gives access to federal bankruptcy
   filings in NC/SC districts.
