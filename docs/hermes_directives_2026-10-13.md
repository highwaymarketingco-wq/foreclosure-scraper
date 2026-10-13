# Session handoff — 2026-10-13

Everything built, fixed, and verified this session, plus exactly what's left for Hermes. All
claims below are either live-verified today (stated how) or explicitly marked otherwise —
several prior "confirmed dead" claims in this codebase turned out wrong when actually
re-fetched, so nothing here is asserted from memory alone.

All work is pushed to `origin/main` and pulled onto the Oracle VM. Commit range:
`edc055e6..87643302` (15 commits).

---

## Part 1 — What was done this session

### 1. New scraper: Greenville County SC probate (`edc055e6`, `fcb37adb`)

`src/foreclosure_scraper/scrapers/counties_sc/greenville_probate.py` — Greenville's own
`appsas400` probate portal (it never fed southcarolinaprobate.net, which `sc_probate_net.py`
already reads). A HERMES status report had claimed this county has "no online portal, manual
pull only" — false. Real mechanics: plain query-string GET + one redirect to an opaque `?q=`
token, a single unpaginated results page per surname search, and a detail page with a real
decedent address field (often blank, but populated on several live cases). Validated with real
output on both Mac and the VM — e.g. a Smith estate filed 3/20/2026, PR Kimberly Truluck
Thomason, 119 Summer Oak Lane, Simpsonville SC. 21 unit tests in `tests/test_greenville_probate.py`.

### 2. Nine test-suite failures fixed, all verified pre-existing/unrelated to the above (`a7ac54a4`..`9231d2ac`)

Running the full 852-file suite after the Greenville build surfaced 21 failures. 3 were caused
by Greenville itself (fixed in `fcb37adb`/`9231d2ac` — a missing `RAW_KEEP` entry and a missing
source-register doc entry). The other 18 were pre-existing, confirmed by diffing against the
parent commit — fixed anyway since they were found:

- **liensnc_incremental** (`a7ac54a4`): 2 tests broke on the real `data/liensnc/OFF` kill-switch
  file (a standing operator decision from earlier this session). Test-only fix.
- **polk_tax** (`4a9efda1`): test helper didn't isolate a second, newer live-search code path
  the scraper gained in a recent rewrite. Test-only fix.
- **sc_public_index** (`30886bb2`): tests were stale after a real, dated fix
  (`be42b5f9`) changed how headlessness is signaled to defeat a Chrome crash. Test-only fix.
- **sc_sos_entity** (`29d92cd5`) — **real bug**: commit `735a5f32` had flipped `disabled=False`
  and claimed a "via patchright" CAPTCHA bypass with zero implementation behind it.
  `search_entity()` is still a plain POST with no CAPTCHA handling at all. Reverted to
  `disabled=True` so the orchestrator reports this honestly. See Part 2, item 1 below — this is
  the main thing left for Hermes.
- **york_delinquent_tax** (`9371607e`) — real gap: a legitimate rewrite to a new ArcGIS API
  dropped the shared junk-row gate. Added `if not parcel_id: continue` in production code;
  rewrote the dead tests to match the new interface.
- **board_persist** (`d48c1931`) — **real, correctness-critical bug**: a second weak-identity
  signature (`"rk"`, a row-fingerprint fallback that doesn't key on `owner_name`) could bypass
  the owner-conflict check the same way the `"k"`/url-key path already guarded against, silently
  folding one owner's prior data onto a different owner's fresh row. Fixed in
  `src/foreclosure_scraper/board_persist.py`'s `merge_prior_board`.
- **lien_registry_wall** (`6decacb1`): Rutherford County (`counties_nc.rutherford_tax` /
  `.rutherford_wildfire_tax`) was still being claimed as a permanent wall even though
  `avalon_tax.py` (built earlier this same session) now covers it live. Removed the stale
  overlap.
- **Privacy fix** (`fd0a57ca`) — **real PII leak in the public repo**: 547 Rutherford tax-debtor
  names and all 198 divorce-case names had leaked into the committed, public verification
  ledger (`docs/handoff/verification/{tax_lien,divorce}/*.json`) because `avalon_tax.py` and
  `divorce_sc_wall.py` never set the standard `ROW_SUMMARY_EXCLUDE = ("owner_name",)` every
  other verifier sets. Fixed both verifiers, added a default-redact safety net in
  `scripts/verification_sweep.py`, and scrubbed the 745 already-committed entries (backed up
  first). **Not done, flagged for the owner, not mine to decide:** this doesn't scrub git
  *history* — the names still sit in earlier commits on a public repo. True removal needs a
  destructive history rewrite + force-push.
- **Docs catch-up** (`9231d2ac`): registered 17 more missing `RAW_KEEP` raw keys and 14 more
  undocumented scrapers the full suite surfaced (nc_avalon_tax, nc_cchs_deeds, nc_rod_captcha,
  nc_rowan_cott, dc_ip_block, lexington_probate, nc_tylertech_estates, city_of_union,
  morganton_nc, polk_tax's second path, sc_tax_walled, nc_unclaimed, sc_rod_walled, sc_qpublic).
- **sc_overage_full_user_agent** (`0e67ada1`) — found on the *final* confirmation run: a real
  live network call was happening inside a "unit" test (`york_overage_claims.py` tries
  `curl_cffi` before its httpx fallback; the test's mock only covered httpx). Fixed by forcing
  `curl_cffi` to fail in-test so the mockable path is always exercised.

### 3. Dead-source re-audit: 16 "confirmed dead/walled" claims re-checked live (`5c1358d8`)

Several earlier "confirmed dead" claims this session (Cherokee ROD, Polk tax search, NC SOS
UCC) turned out wrong on direct re-fetching. Re-checked every other disabled-scraper claim the
same way — fetched the real URL(s), today, not from memory:

**14 confirmed still genuinely accurate** (re-dated with today's evidence, nothing re-enabled):
Abbeville, Darlington, Edgefield, Fairfield, Greenwood, Newberry (all 6: office-contact pages
only, real coverage already comes from a working sibling — see the pushback-check note below),
Oconee FLC, Clarendon, Sumter surplus, Korn law firm, LandsOfAmerica, NC SOS UCC, Beaufort FLC
(one caveat: its authoritative source page couldn't be re-fetched today, Cloudflare-challenged),
and NC TylerTech Estates (had `disabled=True` with **no** `disabled_reason` at all — added one
after confirming its sibling `nc_ecourts_estates.py` genuinely covers the same portal).

**2 had a stale or wrong *mechanism*, even though "stay disabled" was still the right call:**
- Aiken: `PAGE_URL` 301-redirects to a new path now; updated to follow it (still no table).
- Chester: old note said "redirects to homepage" — it's now a domain-wide Cloudflare WAF 403.
- Kershaw FLC: old note said "404s" — it's now a domain-wide Akamai WAF block (confirmed by
  `robots.txt` itself 403ing).

**Pushback double-check** (user relayed counter-claims for Edgefield/Fairfield/Greenwood/
Newberry/Sumter/Korn): all checked directly, none held up. Edgefield and Fairfield are already
swept in bulk by `qpaybill_delinquent_roll.py` / `sc_catalis_delinquent_roll.py` respectively
(the "Unpaid" roll-enumeration the pushback suggested doing manually is already automated);
Greenwood already has its own dedicated live scraper (`greenwood_corebtpay_delinquent_tax.py`);
Newberry's pushback just restated the agent's own finding; the Sumter "missed SCFLC account"
claim named seller ID 3939, which was one of the exact 4 IDs already queried (I independently
rebuilt the GovDeals API call from scratch and reproduced the same empty result); the Korn
"absorbed by other firms" claim named no actual successor to check.

### 4. Legacy.com obituaries re-enabled with a real fix (`87643302`)

`src/foreclosure_scraper/scrapers/national/legacy_obituaries.py` was disabled as a "confirmed
garbage emitter" (state-scoping params silently ignored — an "Asheville" search returned
Tampa/CT/NZ obituaries). Found the real mechanism by driving the live search UI and watching its
own filter dropdowns rewrite the URL: legacy.com scopes on `country`/`state`/`city` as full
human-readable names, not abbreviations or IDs. Verified live against all 19 target cities.
Added a server-side verification pass (drops a row outright if its text names a *different* US
state; flags-but-keeps an ambiguous row) since the site's own facet still leaks ~1-2%. Re-ran
`fetch()` live end-to-end: 107 real rows, 9 real wrong-state obituaries actively caught and
rejected. Re-enabled and added to `main.SCOPE_BYPASS_SOURCES` (county is never attached at
scrape time, same shape as `craigslist_fsbo`/`sc_public_index`).

### Verification posture

Every fix above has its own test coverage and was run against the live site where applicable
(not just unit tests). The full 852-file suite was run clean twice (once locally, once
re-confirming after the overage fix) and once on the VM after deploy.

---

## Part 2 — What's left for Hermes, literally, per instance

### 1. `src/foreclosure_scraper/scrapers/national/sc_sos_entity.py` — wire the audio-solver for real

**Current state:** `disabled = True` (I reverted an unearned `disabled=False` this session —
see Part 1). `search_entity()` is a plain `httpx` POST, no browser, no CAPTCHA handling at all.

**What exists separately:** `scripts/scsos_audio_solver.py` — a standalone script using
`patchright` + Groq Whisper that solved the reCAPTCHA audio challenge for real and produced 48
real entity rows on 2026-10-12, but was **never imported by or wired into** the production
class.

**Why it's not a small wiring job — the two pieces don't fit together as-is:**
- Production `search_entity()` has no browser/page/frame object at all; the solver needs a live
  `patchright` page with iframe access to click/solve.
- The solver launches a *fresh browser per run*; production needs ONE browser session reused
  across many name searches.
- The solver's result-parsing is cruder than production's (dumps every table row; production
  already does name-matching + visits the detail page for entity type/filing date/registered
  agent). Keep production's parsing logic, not the solver's.

**Literal steps:**
1. Rewrite `fetch()` to own a browser lifecycle: launch one `patchright` session (headless=
   False, as the solver's own `main()` already does correctly), one page, loop over whatever
   entity names need checking, close once at the end. Don't launch per-name.
2. Port `solve_audio_challenge()`, `speech_to_text_groq()`, `find_challenge_frame()`,
   `find_anchor_frame()`, `get_recaptcha_response()` from `scsos_audio_solver.py` into
   `sc_sos_entity.py` — that part already works.
3. Change `search_entity()` to take the open `page`, and after the reCAPTCHA is solved, parse
   results using the **existing production logic at lines 198–266 of the current file**
   (name-match against `clean_name`, extract `detail_url`, fetch the detail page, pull
   `entity_type`/`filing_date`/`registered_agent`) — not the solver's flat `{"name","status"}`
   dump.
4. **Unresolved design question — answer this before writing code:** nothing currently calls
   this scraper (confirmed: no `enrichment_sos_sc` module exists, and a repo-wide grep for
   `search_entity` finds zero callers outside this file and its own test). Decide where the list
   of entity names in `fetch()` comes from — a batch pass over every LLC-owned property's owner
   name on the board, or something else. Don't leave `fetch()` with nothing to search.
5. Raise `timeout_s` from the current `60.0` to the 900–2400s range other browser-driven
   scrapers in this codebase use — a single entity can take 60–120+ seconds through several
   audio-retry attempts.
6. Add a pause of at least ~2s between entity searches (same convention as `liensnc.py`'s
   "≥1.6s apart") — hammering reCAPTCHA back-to-back risks escalating challenges.
7. Confirm `GROQ_API_KEY` is available wherever this runs (env var or `~/.secrets/
   groq_api_key.txt` — the solver script already checks both paths).
8. Consider `mac_only = True` — reCAPTCHA is far more likely to succeed from a residential IP
   than Oracle Cloud's datacenter IP, same reasoning as this codebase's existing
   `scrapers/counties_nc/dc_ip_block.py`.
9. Only once that's real and tested against the live site: flip `disabled` back to `False` and
   rewrite the class/module docstrings to describe what's actually implemented. Update
   `tests/test_sc_sos_entity.py` to match (currently asserts `disabled is True`).

### 2. Low-priority, genuinely-walled, low-value — only worth it if Hermes has spare capacity

These are real walls, confirmed live today, but each is either fully or mostly redundant with a
working sibling source already on the board. Not recommended as a priority; listed for
completeness since the audit found them.

- **`src/foreclosure_scraper/scrapers/counties_sc/chester_delinquent_tax.py`** — domain-wide
  Cloudflare WAF 403. **Fully redundant**: `counties_sc.sc_catalis_delinquent_roll.py` already
  covers Chester with a real, live, structured API roll (`SWEEP_ORDER` includes `"Chester"`).
  Not worth Hermes's time.
- **`src/foreclosure_scraper/scrapers/counties_sc/kershaw_flc.py`** — domain-wide Akamai bot
  block (confirmed by `robots.txt` itself 403ing). Kershaw's *general* delinquent-tax roll is
  already covered live by `qpaybill_delinquent_roll.py` (`"Kershaw": "kershawcounty"`), but FLC
  (county-owned, already-forfeited land) is a genuinely different, narrower dataset the roll
  wouldn't include. Real gap, low volume, low priority.
- **`src/foreclosure_scraper/scrapers/counties_sc/beaufort_flc.py`** — its
  `AUTHORITATIVE_SOURCE_URL` returned a Cloudflare challenge today and couldn't be re-fetched to
  confirm the "no properties available" finding directly (only corroborated indirectly via the
  live Beaufort County Treasurer site, which has no FLC link anywhere). Same FLC-vs-general-roll
  distinction as Kershaw above; same low-priority call.

### 3. Everything else confirmed as a genuine, standing wall — no action recommended

`landsofamerica.py` (Akamai Sensor interactive challenge — confirmed via two independent methods
today, instant 403 edge-deny on both target URLs) and `nc_sos_ucc.py` (Cloudflare managed
challenge on every path, confirmed today; also confirmed no alternate NC UCC search venue exists
anywhere, on sosnc.gov or elsewhere) are both genuine, compliance-wall situations per this
project's own stance (a CAPTCHA/interactive challenge is not solved or routed around). Nothing
to do here unless the owner wants to revisit the compliance line itself.

### 4. Open, unresolved from Part 1 (not a Hermes CAPTCHA task — flagging for the owner)

The 745-entry PII leak (Part 1, item 2) is scrubbed from the *current* file state but still sits
in earlier git commits on this public repo. Removing it from history requires `git filter-repo`
or similar + a force-push — destructive, affects every clone, and is the owner's call, not
something either of us should do unilaterally.

---

## Part 3 — Things I explicitly do not know

- Whether Hermes has done its own separate "deep dive on individual listings" pass from a prior
  night's hand-off — I have no visibility into that session. Nothing in this repo's recent
  commit history matches that description as of this writing.
- Whether the owner wants the git-history PII scrub done, and if so, whether this public repo's
  existing clones/forks need separate handling.
