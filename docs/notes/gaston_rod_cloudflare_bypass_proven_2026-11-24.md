# Gaston/CCS Register of Deeds — Cloudflare wall confirmed beatable, fix not yet integrated

## Context

`nc_cchs_deeds.py`'s 2026-10-13 audit (its own docstring) found gastonnc.courthousecomputersystems.com
and alleghanync.courthousecomputersystems.com genuinely Cloudflare-walled (not just a wrong URL),
confirmed via both a real browser (never clears in 20+s) and curl_cffi Chrome-impersonation (403 on
the "Just a moment" page). `enrichment_gaston_rod.py`'s own docstring separately claims this exact
host was "live-verified 2026-06-29" via plain curl_cffi with no login/CAPTCHA — stale: that module
is Default-ON in production (`FORECLOSURE_GASTON_ROD` defaults to `"1"`) and has very likely been
silently returning zero lien-existence data for every Gaston board owner since Cloudflare's posture
changed sometime between June and October — a silent broken-producer gap, not a known one.

## What was proven live today (2026-11-24)

1. Re-confirmed the wall: `enrichment_gaston_rod._seed()`'s own curl_cffi approach still gets a
   plain `HTTP 403` today. The October finding holds; nothing has reverted.
2. **`scrapling.fetchers.StealthyFetcher` with `solve_cloudflare=True`** (the same tool already
   proven working for `nc_ecourts_estates.py`'s AWS WAF, in this same session) **solves Gaston's
   Cloudflare Turnstile challenge and gets a real 200** — confirmed via page title ("Register Of
   Deeds | Gaston County, NC").
3. Went further: ran the full 3-step search (GET `/` → GET `/LRSearch/LRIndex?searchTabID=0` →
   POST `/LRSearch/ExecuteSearch`) as **in-page `fetch()` calls from inside that same solved
   browser page** (`page.evaluate()`), reusing `enrichment_gaston_rod.py`'s own exact, already-
   proven request body (`_body()`) and headers. Result: **200 real, correctly-parsed instrument
   rows** for a test name ("Smith") — `parse_rows()` and `classify()` (both unchanged, pure
   functions) correctly read 61 releases, 127 deeds, 5 corp, 6 plat, and flagged both a mortgage
   and an adverse lien (JUDG) present. Not a fluke or an empty-grid shell — real board-relevant data.

## What this does and doesn't fix yet

**Proven**: the Cloudflare wall is beatable, and a **name-based lookup** (the enrichment pattern —
"does this specific owner have any recorded instruments") works end-to-end once past it.

**Not yet proven**: `nc_cchs_deeds.py`'s own job is different — a broad, no-name, date-range
"Advanced Search" for *new* deeds (discovery, not per-owner enrichment). The same October audit
found that exact query SHAPE times out on the application backend (Cloudflare 524, "A timeout
occurred") for caldwell/franklin/hertford/gates even where Cloudflare's own front-door wall isn't
the obstacle — a genuine backend reliability limit of the broad/no-name path, confirmed on 5
separate attempts with different date windows. There's no reason to assume a Cloudflare-solved
session would avoid that same backend timeout for gaston/alleghany's own Advanced Search, and this
was NOT tested today. So this finding does **not** directly unlock `nc_cchs_deeds.py`'s 21K-row
discovery mission for gaston/alleghany — it directly unlocks `enrichment_gaston_rod.py`'s own
narrower, already-running enrichment mission (fixing a silent month+ zero-data gap), which is a
real and worthwhile win on its own, just a different, smaller one than "CCS Deeds" in the master
plan implies.

## What integrating this actually requires (not done today — scoped, not attempted)

`enrichment_gaston_rod.py`'s `enrich_gaston_rod()` currently holds ONE curl_cffi `AsyncSession` open
across all target lookups in a run. Swapping to StealthyFetcher means restructuring that to: one
`StealthyFetcher.async_fetch()` call whose `page_action` callback seeds once (GET LRIndex) then
loops ALL targets inside itself doing repeated in-page `fetch()` calls on the same already-solved
page, rather than looping outside a `with AsyncSession() as s:` block. `_seed(session)` and
`search_instruments(session, ...)` take a curl_cffi session today; either they get rewritten to take
a Playwright `page` instead, or `enrich_gaston_rod()` inlines the in-page-fetch logic directly and
these two become dead code for the live path (kept for whatever still calls them, if anything).

`tests/test_gaston_rod.py` has real tests against the current session-based `_seed`/
`search_instruments`/`enrich_gaston_rod` (mocked sessions, not live network) — `test_seed_returns_
true_on_two_clean_gets`, `test_search_instruments_raises_gaston_wall_on_a_challenge_mid_run`,
`test_enrich_gaston_rod_stops_immediately_on_a_walled_seed`, and more. A session-model rewrite needs
these updated too, not just the implementation.

**Scope estimate**: a real but bounded rewrite (one module + its test file), not a research
problem — the hard part (does the Cloudflare-bypass + search-shape combination actually work
end-to-end against the live site) is the part already proven above. Picking this up should start
from this file, not re-derive the wall-is-beatable finding.

## Confirmed NOT affected by this

Checked whether other scrapers import `enrichment_gaston_rod` and would be affected by a rewrite:
only `tests/test_gaston_rod.py` does. `darlington_recordhub.py`, `sc_countyfusion_rod.py`,
`sc_avenu_rod.py` do not reference this module despite superficially similar grep hits on unrelated
terms — confirmed by checking each file directly, not assumed from the first grep.

## Addendum 2026-11-24, later same day: NC eCourts category-filter investigation hit a NEW wall

Retried `/tmp/gaston_investigate_scratch/run_category_investigation.py` after
confirming Gemini keys now fail fast (HTTP 429 "exceeded your current quota",
not the earlier slow 503 "high demand" storm) -- the fast-fail meant the WAF
puzzle solve succeeded cleanly on attempt 1 this time (`waf.solved
attempts_used=1`, after keys 0-4 rotated past quota and key 5 answered).

But immediately after the solved WAF puzzle, the page landed on
`https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29` showing a flat
**403 Forbidden** -- a different wall than the original category-filter bug
this script was built to diagnose, and one that did not appear on the
earlier attempt today (that one got past WAF fine and reached the real
search-form timeout). This looks like TylerTech's own portal rate-limiting
or flagging this Mac's IP given the volume of automated WAF-solving traffic
sent to it today (this investigation plus whatever Hermes ran).

Not worth retrying again today from this IP -- same category as the
Lexington reCAPTCHA finding (see
docs/LEXINGTON_PROBATE_RECAPTCHA_STATUS_2026-11-24.md): a traffic-pattern/IP
reputation block, not a code bug, that needs a cooldown or a different
egress IP (e.g. the VM's) rather than more same-IP attempts. The original
category-filter DOM bug is still unconfirmed/unfixed -- this 403 blocked
reaching it again, it didn't answer it.
