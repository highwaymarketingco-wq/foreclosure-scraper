# Scraper — Stack, Architecture & Maturity

A plain-language reference for how the engine is built: how mature the software is, and the exact tools that do the fetching, parsing, and enrichment (with each tool's job and its limits).

---

## How built-out it is

This is a real production data platform, not a script. It runs on its own schedule (the current repo HEAD is often an *automated* commit) and publishes a live 17,000-lead dashboard.

**By the numbers**
- **~70,000 lines** of Python across **296 modules**
- **110 scrapers** + **93 enrichers** + 60 operational scripts
- A **2,392-line orchestrator** (`main.py`) running the full fetch → dedupe → resolve → enrich → score → publish pipeline
- **1,319 test functions** across 146 files (suite green)
- **17,003 live leads** on a hosted GitHub Pages dashboard
- **Scheduled + self-running**: 4 GitHub Actions workflows (cloud) + 4 launchd jobs (weekly full run, daily vision, land-records, SoS)

**What's mature / solid**
- **The scraper contract is real.** Every scraper inherits `safe_run()` → an `asyncio.wait_for` timeout (180s default), typed error handling (Timeout / HTTPStatus / ConnErr / Proxy / generic), an outcome label (OK/ERROR), and an `expected_min_count` sanity check. One scraper failing is isolated and logged — it never crashes the run.
- **Robustness is spread through the code**, not bolted on: timeouts in 112 files, min-count guards in 108, retry in 17, circuit-breakers in 12, budget-bails in 26, block-signal detection in 18.
- **Deep enrichment (93 enrichers):** owner/mailing, county GIS, ARV/comps, equity, lien stack, distress scoring/grading, vision condition, court-confirmation. Leads are graded and priced, not just scraped.
- **Serious data engineering:** multi-pass union-merge dedup (48 files), a lazy-detail sidecar + `load_board` integrity guard, deterministic gzip publishing, a scoring/grading engine.
- **Tested + regression-guarded** (sidecar round-trip, real-format parsers, the 8-script sidecar-wipe fix).

**Honest weak spots**
- **The render/stealth tier is the fragile part** — ~40 modules need a browser render or must pass anti-bot; these break most often when a county redesigns a portal, run 25–40s/lead, and are exactly the walled ones. Everything JSON/API-based is rock-solid.
- **Observability is thin** — there's `run_meta.source_status`, but no proactive alerting; you notice a dead scraper by leads dropping, not by a page. (Being fixed with a source-health monitor.)
- **Board size** (~60 MB) trends toward the git/Pages ceiling; the dashboard is fast (gzip) but the git-side trim is deferred.
- **Contactability ceiling** — phones are voter-file/licensed only (a data-market wall, not a code gap).

**Verdict:** a strong production MVP+. Breadth, core engineering, and ops are genuinely mature; the frontier is reliability/observability and the walled sources (the human-gather loop).

---

## The tech stack

### Core design — a tiered fetch that auto-escalates
Scrapers don't choose a tool. They call `get_text()` in `http_client.py`, which walks fetch tiers **cheapest-first** and escalates only when blocked — with per-host throttle locks and block-signal detection. Once a host blocks a plain request it's remembered, so future hits start impersonating. Result: ~90% of fetches never spin up a browser.

### Fetch tier
- **httpx** — *~67 files.* Async HTTP/2 client, the default. Handles all JSON/API/GIS/ArcGIS/tax feeds at ~50 ms–1 s. **Limit:** no JavaScript; trips fingerprint/JA3 anti-bot; blocked by any TLS-checking WAF.
- **curl_cffi** (`impersonate="chrome"`) — *~18 files.* Sends a real Chrome JA3/TLS + HTTP/2 fingerprint, so it passes fingerprint walls (Akamai, some Cloudflare) that httpx trips. Still ~1 s, static. **Limit:** still no JS; won't pass a JS-challenge WAF or a CAPTCHA; behavioral bot-detection can still catch it.
- **Scrapling `StealthyFetcher`** (over **camoufox**) — *~33–41 files.* A stealth real browser that runs the page's own JS with anti-fingerprinting; handles JS-rendered SPAs and `solve_cloudflare` (17 files). The heavy tier. **Limit:** slow (seconds–30 s/page), resource-heavy, fragile (breaks on DOM/WAF changes), and it does **not** solve CAPTCHAs.
- **Playwright** (direct) — *~5 files.* Full browser automation for the nastiest flows — ASP.NET `__doPostBack` form drives and `__VIEWSTATE` handshakes (the ROD/court render scrapers). **Limit:** slowest, most brittle, ~25–40 s/lead; a site redesign breaks it.

### Parse tier
- **selectolax** — *~47 files.* Fast C (Modest-engine) HTML parser with CSS selectors; the primary parser for every results table. **Limit:** no JS; no `:scope` selector (we hand-walk direct children); CSS-only.
- **pdfplumber (14) + pypdf (9)** — text/table extraction from PDFs (delinquent-tax rolls, deed indexes, sale lists). **Limit:** only works on a text-layer PDF; a scanned/image PDF has no text → must go to OCR.
- **Gemini** (free tier, via REST; OCR path ~5 files) — LLM **OCR** of scanned docs (deed-of-trust "principal sum of $X", legal notices) + **vision** property-condition grading; 9-key rotation for free quota. **Limit:** rate-limited (hence rotation), non-deterministic accuracy, needs the image/PDF fetched first; not for bulk.

### Data / model tier
- **pydantic** — the `Listing` model: validation, coercion, and the `merge()` that powers multi-source attribution (`also_seen_in`).
- **rapidfuzz** — fuzzy address matching in dedup (`token_set_ratio ≥ 92`) so "3 Beech St" and "3 BEECH STREET" merge. **Limit:** fuzzy = occasional false merge/split (mitigated by a 3-pass union-merge).
- **pandas** — CSV/tabular ingest (tax rolls, exports). **structlog** — structured per-scraper logging.

### Bypass tier — and where the ceiling really is
- **`solve_cloudflare`** + **camoufox** stealth pass *fingerprint/JS* challenges by being a real browser running the page's own JS (no forgery). **Compliant** — used.
- **WAF-token minting** (`tyler_waf_token`, awswaf) + **CapSolver** (CAPTCHA-solving) exist in the repo but are **not operated** — solving a CAPTCHA / defeating a WAF bot-check is the line we hold, so those court portals stay human-gather.

### What the whole stack fundamentally cannot do (no library fixes these)
- **Solve CAPTCHAs** — Scrapling passes challenges but not CAPTCHAs, and we won't run CapSolver → NC eCourts / SC PublicIndex stay human-gather.
- **Defeat a ToS "no automation" clause** — a browser can load it; we won't script it → same portals.
- **Extract data that's legally absent** — Gemini can OCR a deed, but an exempt "$5" deed has no real price to read.
- **Get owner PII (phones)** from ban-automation people-search sites → voter-file/licensed only.

**Bottom line:** the fetch/parse/AI stack is capable and well-layered — impersonation + stealth-render + OCR covers most of the free web. The remaining walls are **CAPTCHA + ToS + legally-absent + PII**, which are deliberate boundaries, not missing tools. The one genuine *tooling* fragility is the render tier (~40 modules), which is why the next reliability investment is a **source-health monitor** that flags any scraper whose output craters.
