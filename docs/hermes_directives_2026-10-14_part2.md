# Session handoff — 2026-10-14, Part 2

Supersedes nothing in `hermes_directives_2026-10-14.md` (Part 1) — this is the continuation
covering everything committed AFTER that file was written. Commit range `0f4fb66a..9a528828`
(12 commits), all pushed to `origin/main` and pulled onto the Oracle VM. Read Part 1 first if
you haven't; this picks up right where it left off (the math_captcha.py false-positive bug and
the "needs YOU logged in" list).

---

## Part 1 — What was done this session (continuation)

### `math_captcha.py` — the false-positive bug, fully fixed (commit `0f4fb66a`)

`solve_math_captcha()` used to regex the ENTIRE page body for anything shaped like
`number operator number`. On Brunswick, the real question is an IMAGE (no text in the DOM at
all), so the old code would latch onto something else on the page — a hyphenated phone number
like `704-253-4000` parses as `704 - 253` under this module's own operator table (`-` =
subtraction) — compute a wrong answer, submit it, and report `solved=True` with **zero
verification the gate actually cleared**. This was a silent false-positive, not a missing
feature, and it affected every caller of this module.

Fixed: question-text extraction is now scoped to the form/fieldset around the actual answer
input (not the whole page body), an independent phone-number-shaped-substring guard was added,
and — critically — the function now verifies the answer field is actually gone from the page
before returning `True`.

**Stretch goal also landed**: Brunswick's question turned out to be 4 separate word-images
(`getpng.php?a=N&b=M` — the params are opaque, not the literal operands). New
`_solve_image_question()` reuses this codebase's existing Gemini OCR plumbing
(`enrichment_vision._parse_gemini_keys`) to read and solve it for real. Verified end-to-end on
the Oracle VM through actual Playwright/Chromium (headful via Xvfb `:99`): OCR → answer → submit
→ gate confirmed cleared (the answer field is genuinely gone afterward). 34 tests pass.

### Brunswick's full gate chain — now complete (commit `0f47c4b4`)

The math CAPTCHA clearing (above) was only step 1 of 3. Live-verified and wired the rest:
step 2 (a disclaimer-accept link that appears right after the CAPTCHA clears — two links exist,
"I do NOT agree" listed FIRST, a naive substring match hits the wrong one, this cost one failed
attempt during verification, now disambiguated correctly) and step 3 (the real search UI:
`SUBSTITUTE TRUSTEE` and `NOTICE OF FORECLOSURE` are the two real pre-foreclosure doc-type
values this platform offers — "Combined Real Property" is NOT distress-only, it's every
instrument type). Real sample data pulled live: book 5596 page 1287, defendant
`VEGA, ESTEBAN EMILIO; MILLS, BRANDI`, lender `ROCKET MORTGAGE, LLC` correctly filtered out of
the defendant field (institutional-name detection, same convention as `nc_rod_logan.py`).
Document PDFs confirmed durable, stateless, cookie-less signed URLs — stamped via
`document_links.stamp_documents`.

### The "Needs YOU logged in" list — CLOSED OUT, 9 of 9 counties resolved, zero remain

This is the big one. The audit's original list named 6 files / 11 counties as needing the
owner's own login session. **Every single one was checked live, one at a time, with the owner
personally clearing each real CAPTCHA** (same boundary this project has always held — a human
clears the gate, the code never attempts to solve a real reCAPTCHA/image-CAPTCHA itself).
Result: **every one of them was a false flag for "needs login" in the account-wall sense** — none
needed credentials or an account, they needed a human to clear a bot-check once per session, then
everything downstream (search, parsing, document capture) is ordinary free data, now built and
tested. Final tally:

- **`sc_rod_acclaim.py` (Pickens SC)** — AcclaimWeb. No account exists anywhere on this
  deployment. `Search/GridResults` JSON carries `TransactionItemId`; `GET
  Image/DocumentPdfAllPages/{id}` returns the real PDF COLD, zero prior requests, no CAPTCHA at
  all on this specific county. (Already covered in Part 1.)
- **`sc_rod_walled.py` / Beaufort SC** — no WAF at all. Free JSON API, new `rod/beaufort_dmp.py`.
  (Part 1.)
- **`sc_rod_walled.py` / Clarendon SC** — same AcclaimWeb vendor as Pickens, Cloudflare-only edge
  (not a CAPTCHA puzzle — cleared by this codebase's existing nodriver stealth-fingerprint tier,
  same category as other already-shipped scrapers, not a new compliance line). (Part 1.)
- **`sc_rod_cott.py` (Union SC)** — the "free vs. pay-per-view" contradiction settled: genuinely
  free, gated by an anti-hotlinking Referer header, not an account. (Part 1.)
- **`sc_rod_walled.py` / Jasper SC — commit `069ee8e8`.** Real Google reCAPTCHA v2. Platform:
  Courthouse Computer Systems ("CCS DevExpress") — DIFFERENT vendor from Tyler/AcclaimWeb, new
  `rod/ccs_devexpress.py` module (507 lines). Owner cleared the reCAPTCHA live; search, 5
  distress-code classification (LIEN/MECHANICS LIEN/TAX LIEN/LIS PENDENS/DEATH CERTIFICATE), and
  free document-image capture all built and live-verified (real IRS lien, real federal judgment
  lien, real HOA/mechanics liens, real death certificates — used as test fixtures). Session-reuse
  window: the page's own JS sets a 12-hour timeout, pings its own keep-alive only every 6 hours;
  corroborated live with that heartbeat blocked, the same session answered a real search after
  22+ minutes of continuous use. **Jasper's lien-claimant/debtor convention is the OPPOSITE of a
  mortgage** (claimant=grantor, owner=grantee) — don't assume mortgage convention carries over.
  40 tests pass.
- **`nc_rod_captcha.py` / Wake NC — commit `08e29a17`.** Real reCAPTCHA checkbox, Tyler
  "Self-Service" platform (same family as Durham, below). Owner cleared it; built real search
  (SUBSTITUTE TRUSTEE / FORECLOSURE NOTICE doc types), reused `rod/nc_tyler.py`'s
  `parse_selfservice()` parser (same as Durham), plus a budget-capped one-hop
  related-documents follow-through (a Notice of Correction can link to the original Deed of
  Trust — that original document often carries the real loan amount/lender, which the correction
  notice alone doesn't). **Session-reuse window MEASURED, not assumed**: blocked the page's own
  heartbeat, made zero requests for 7m14s, then a real authenticated fetch still worked — floor
  confirmed, real ceiling likely much longer (10-20s self-heartbeat on this platform is strong
  architectural evidence). Real sample data: instrument 2026082901, grantors LEE
  MAURICE LORANZO/LEE TRACY/WIGGINS ELLEN, lender R&R FUNDING GROUP correctly separated from
  grantors. 28 tests pass. **Two real gaps found and left documented, not silently dropped** (see
  Part 2 below — these got fixed in a follow-up, not this commit).
- **`nc_rod_captcha.py` / Iredell NC — commit `3c07b883`.** Same CCS DevExpress platform as
  Jasper. This build specifically GENERALIZED `rod/ccs_devexpress.py` (it was Jasper-specific
  before) because Iredell's grid uses split Grantor/Grantee columns vs. Jasper's combined
  role+name cell — the parser now resolves fields via a live `header_map` built from the grid's
  own CSS classes, falling back to Jasper's fixed positions only when no map is given (zero
  behavior change for Jasper). Doc-type codes differ from Jasper too: `FCL/S-TR/BKCY/JGMT/LIEN/
  LIS/P`, no death-certificate code. Institutional-party filtering specifically drops NCDOT
  self-referential condemnation-judgment noise. **Critical finding: Iredell's cleared session
  does NOT survive a fresh tab/navigation** — a brand-new tab re-shows the real CAPTCHA. Any
  caller MUST drive the already-cleared page in place, never `page.goto()` away from it.
  Session-reuse: 679 seconds (11m19s) of confirmed zero-activity idle survival — stronger than
  Wake's floor. 86/86 tests pass.
- **`nc_rod_captcha.py` / Craven, Greene, Harnett, Randolph, Stokes NC — commit `aa9fdf85`,
  final batch.** All 5 wired in ONE pass through a shared, county-parameterized helper
  (`_fetch_ccs_devexpress_county` / `_ccs_doc_to_listing`) rather than 5 copies of bespoke code.
  Each county's own doc-type dictionary read live and genuinely differs — don't assume any
  carries over: Craven `BKCY/FCL/FCL-CONDO/JGMT/LIEN/LIS/P/S/TR`; **Greene genuinely has NO lien
  code and NO lis-pendens code at all** (confirmed absence, not a bug — `FCL/S/TR/JGMT/BNKRPT/ML`
  is the whole relevant set); Harnett uses FULL WORDS not short codes
  (`FORECLOSE/FORECLOSURE/S-TR/BKCY/JUDGMENT/LIEN`); Randolph `FCL/S/TR/JGMT/LIEN/LIS/P/BKCY/
  BANKRUPTCY` (both bankruptcy spellings kept); Stokes has real duplicate/typo spellings in its
  own dictionary (`BKCY`/`BCKY`, `JGMT`/`JDMT`) and substitute-trustee has NO slash/hyphen
  spelling, only a literal space (`S TR`). **Two more generic platform bugs found and fixed in
  the shared module** (confirmed harmless on Jasper/Iredell, but were real on these 5):
  `isLoading()` was always-true against a permanently-hidden "Loading..." template on this
  platform revision (caused spurious timeouts with real data already rendered); the Advanced
  tab's date fields share identical label text with the Standard tab's, so label-based lookup
  silently filled the WRONG fields (a "90-day" search was actually returning 1995-dated rows
  under the ~10,000-record cap — this one is a genuine, fixed bug, not a feature). Harnett alone
  also needed two structural parser fixes (bracketed `[R]`/`[E]` role tokens, a nested-table
  column-desync under recursive `querySelectorAll`). 105/105 relevant tests pass (65 NC + 40 SC).

**Bottom line for Hermes: the "needs login" list is empty.** No county in the original audit
actually needs a persistent account or credentials. What they need is a human (or Hermes, if/when
it has a working solver for these specific CAPTCHA types — see the architecture note below) to
clear a bot-check ONCE, after which `gate_cleared=True` and the rest of the pipeline — search,
classification, document capture — runs on ordinary free public data, already built and tested
for all 9.

### Durham pagination + a shared multi-tract parsing bug (commit `ec17412c`)

Two more real gaps, found because the owner specifically pressed on date/completeness coverage
mid-session (worth noting: this is exactly the right instinct to keep applying — pressing on
"are we actually getting everything" surfaced 3 concrete, confirmed bugs in one afternoon):

1. **Durham was page-1-only** — a 90-day window is actually 96 pages (~9,502 rows), the old code
   only ever read page 1 (~100 rows). Fixed: walks pages 2..20 (`_DURHAM_MAX_PAGES`), confirmed
   live (20 pages → 2,000 distinct instrument numbers, zero overlap — genuine advancement, not a
   repeat).
2. **`rod/nc_tyler.py`'s shared header regex (`_SS_HEAD`) failed outright on multi-tract
   instruments** (two B:/P: book-page pairs in one header instead of one) — silently dropped
   `instrument_no`/`recorded`/`book`/`page` entirely for that row. Affects BOTH Wake and Durham
   (shared parser). Fixed by splitting on the bullets first, then sub-parsing the middle blob.
3. **Confirmed, not fixable at this level**: Wake/Durham's grantor/grantee display genuinely
   truncates at 5 names in the search-results DOM itself (not a parser bug — verified on a real
   12-grantor deed where the DOM literally only contains 5 `<li>` nodes). The full list IS present
   one hop deeper on the document detail page. ~7.6% of a live sample affected. Not wired up
   (would need a per-row detail-page follow-through, real but scoped future work, not urgent).

41/41 tests pass (local + VM) for this fix.

### Architecture clarification — important for how Hermes should think about these 9 counties

`enrichment_recaptcha_audio.py`'s `solve_recaptcha_v2()` and `enrichment_waf_oss.py`'s
`solve_waf_via_browser()` are PRE-EXISTING (built 2026-10-11/10-12, before any of this session's
work) — this IS Hermes's own automated-solve attempt layer, consistent with the owner's
standing 2026-10-02 decision that this project uses real CAPTCHA/WAF-defeat techniques (see
[[project_waf_bypass_compliance_audit]] if you have access to that memory — Gemini vision +
CapSolver precedent for `nc_ecourts_estates.py`). This session's agents did NOT touch that
solving logic. What they DID confirm, live, for every one of these 9 counties: **the existing
automated solver genuinely fails against the real reCAPTCHA v2 widget** (this is documented
in-code per county, e.g. Wake's comment: "solve_recaptcha_v2 is live-reverified to never
actually clear it"). So `gate_cleared` only reaches `True` today via a human clearing the
session first. If Hermes's own solver ever becomes capable of clearing these specific reCAPTCHA
v2 widgets (different from the AWS-WAF image-CAPTCHA `nc_ecourts_estates.py` solves), the exact
same downstream code runs unchanged — nothing here is hardcoded to a human clearing it
specifically, just to `gate_cleared` being true by whatever means.

---

## Part 2 — What's left

### 1. Operationalizing the 9 CCS/Tyler counties for unattended runs

All 9 are built and tested against ordinary scheduled `fetch()` calls, but `gate_cleared` still
requires either (a) a human clearing the session right before a run, or (b) Hermes's own solver
succeeding (confirmed not currently happening for these specific reCAPTCHA v2 widgets). This is
an operational/process question, not a code gap — worth the owner and Hermes settling explicitly
whether this becomes a periodic manual-clear-then-batch-run pattern (same shape as the
Cherokee/LiensNC manual lane in `docs/HERMES.md` §11) or something else.

### 2. Date-coverage / completeness audit — IN PROGRESS as of this doc

The owner raised a sharp, important concern: rolling lookback windows (correct for event-stream
sources like ROD recordings) could be silently excluding the MOST distressed, MOST motivated-
seller leads if any current-state-roll source (tax-delinquent lists, FLC/forfeited-land,
code-enforcement/vacant/condemned registries, overage claims) has a hidden date filter that
doesn't match what the underlying source actually offers. A property delinquent 5 years should
appear on today's roll with its full accumulated balance — these sources are supposed to be
date-agnostic. A Phase 1 code-level audit across ~129 candidate roll-source files is running NOW
(not yet landed as of this doc) — look for `docs/date_coverage_audit_2026-10-14.md` once it
lands; it will classify each as CLEAN / code-imposed-limit (the real bug target) /
source-limitation (not fixable) / needs-live-check, with a prioritized Phase 2 fix list. If you
read this before that doc exists, it's still running — check back.

### 3. Carried over from Part 1, still open

- `sc_qpublic.py` — genuinely disabled for an architectural reason (stateful ASP.NET POST form,
  this codebase's tooling is GET-only), not login. Real, separate, bigger project if ever
  prioritized (full browser-driven session, same shape as `assessor_cards/qpublic_render.py`'s
  existing 4-county pattern).
- `loopnet.py` — confirmed hard-walled (Akamai 403) as of 2026-10-14, a REGRESSION from working
  cleanly on 2026-10-04. Check scheduled-run BLOCKED status for this source specifically.
- The backfill question — still open with the owner, not started. Every fix across both of these
  handoff docs only takes effect on a source's NEXT run; none of the ~350,000+ leads already on
  the board have been retroactively touched.

---

## Part 3 — Things I explicitly do not know

- Whether Hermes's own solver has ever successfully cleared a reCAPTCHA v2 checkbox widget (as
  opposed to the AWS-WAF image-CAPTCHA it's confirmed to solve) — worth testing/confirming
  directly rather than assuming either way.
- The real ceiling on the CCS DevExpress / Tyler Self-Service session-reuse windows (floors were
  measured: Wake 7m14s, Jasper 22+min, Iredell 11m19s — all are "at least," none are "exactly").
- Whether the Phase 1 date-coverage audit's findings will reveal anything systemic versus a
  handful of isolated bugs — genuinely unknown until it lands.
