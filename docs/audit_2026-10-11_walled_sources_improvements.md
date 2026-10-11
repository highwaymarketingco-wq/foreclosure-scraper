# Walled-sources pipeline (14d7e7fc): full audit and everything I would fix

Scope and a boundary, stated once so the rest of this doc can be read plainly: this covers
`scripts/run_walled_sources.py`, `scripts/wire_walled_to_board.py`, and the scraper/plumbing code
the owner's other platform wrote or changed in commit `14d7e7fc` and is running on the VM. I read
every file in full, read the live output it has produced, and checked the VM for anything
uncommitted (nothing). **I did not run anything, did not touch the live process, and did not edit
the solving/evasion logic inside `wall_bypass.py`, `enrichment_recaptcha_v3.py`,
`enrichment_recaptcha_audio.py`, or `math_captcha.py`.** Everything below that touches those four
files is a bug report only, not a fix I'm offering to make. Everything else is plumbing, and I will
fix all of it on request, because none of it is CAPTCHA-solving: it's the ordinary data-handling
work of getting a scraped row onto the board correctly, the same work every other source in this
repo already goes through.

## 1. What is actually broken right now (confirmed live, not theoretical)

I pulled a real row out of the live output file 50 minutes into the overnight run:
`street_address` is `None`, `zip_code` is `None`, `parcel_id` is `None`, `case_number` is `None`.
Every row from every source in this run has this shape. Two bugs compound:

- **`run_walled_sources.py`**: it reads `li.address` and `li.zip` off each `Listing`. The real field
  names are `street_address` and `zip_code` (`src/foreclosure_scraper/models.py`). So every address
  and zip this run writes is empty, for every source, every county.
- **`wire_walled_to_board.py`**: with no address, parcel, or case number, its dedupe key falls back
  to `url:walled://<source>` — the same key for every row from one source. Instead of 15,447 real NC
  lis pendens rows, the board would receive ONE row (whichever happened to merge last).

This is the single highest-value fix. Nothing else in this list matters until this is fixed,
because right now the whole night's run produces data that cannot reach the board as real leads.

**Fix:** rename the two field reads in `run_walled_sources.py` to `street_address` / `zip_code`
(copy the field list straight off `Listing` so this can't drift again), and give
`wire_walled_to_board.py` the same multi-key identity logic the main pipeline already uses
(`row_keys()` in `src/foreclosure_scraper/verification/core.py` — parcel, then case number, then
address, then a last-resort key that is at least unique per source record, never per source).

## 2. Other plumbing bugs (confirmed by reading the code; same fix-now list)

- **`sc_dew_lien_registry.py` SecurityKey self-heal**: the retry re-posts to the DEW endpoint after
  the HTTP client's connection pool for that host has already been closed. The retry can never
  succeed; it will always need the same manual key-refresh it was supposed to make unnecessary.
  **Fix:** reopen the client (or reuse a fresh one) before the retry, not after the close.
  (Note: DEW is actually working well tonight otherwise — 5,161 real rows in 75 seconds, "no browser
  needed", a genuinely good result. This bug only matters the next time the key rotates.)
- **WAF challenge page counted as a clean empty result**: a blocked request and a real "nothing
  found" look identical in the log and in the output file. This means a whole county or window could
  be silently walled and nobody would know without reading every log line.
  **Fix:** check the response for the WAF's own markers (the repo's `wall_bypass` detection already
  does this upstream in several places) and write a distinct outcome (`"outcome": "BLOCKED"`, which
  the rest of this repo already uses, e.g. `scraper.ok outcome=BLOCKED` in other scrapers) instead of
  `ZERO_RESULT`.
- **Timeout budgets don't match the real cost**: NC divorce and lis pendens are capped at 250
  seconds against a job that needs roughly 15–20x that to cover the full county list; SC Public
  Index needs ~42 browser launches against an 1800-second budget. Every run truncates mid-county with
  only a warning, and the rows for the counties it never reached are simply missing, with nothing
  recorded that says "not yet attempted" versus "attempted and found nothing."
  **Fix:** either raise the budgets to match measured cost per county, or — better, and consistent
  with how the rest of this repo handles exactly this problem — make the run resumable: a small
  on-disk ledger per source (`{county: last_attempted_at, status}`), so a truncated run picks up
  where it left off next time instead of restarting the county list from the top every night. The
  tax-verification ledger (`docs/handoff/verification/*`) and the document-processing ledger
  (`docs/handoff/documents/*`) are the existing pattern for this; I'd build this one the same way.
- **`national prefix path` silently drops a third capped letter-pair**: when a county has more
  two-letter prefixes than the 80-query cap allows, the extra ones are dropped with no log line at
  all, not even a warning. **Fix:** log what was skipped and why, same as the other caps in this
  codebase already do (`drops-*` style logging the audit framework already expects).
- **NC estates runs headful (`headless=False`)**: on a VM with no display this will fail outright,
  every time, not intermittently. **Fix:** set it back to headless unless there's a specific,
  tested reason v2 reCAPTCHA needs a real display on this particular VM (I don't know of one; the
  `session_persist.py` module this same commit added is designed for exactly this — reuse a solved
  session instead of re-solving headful each run).
- **Browser contexts not reliably closed on the timeout path** in `wall_bypass.py`'s Playwright
  calls: a timeout exception can escape before the `finally`/context-manager closes the page. Over
  many hours this leaks headless Chrome processes. **Fix:** wrap the fetch in a context manager or
  `try/finally` that always closes the context, even on timeout.
- **`enrichment_recaptcha_v3.py` has a real bug independent of its solving logic**: one of its
  site-key lookup methods returns the whole regex match instead of the captured group, so even on
  pages where the rest of the approach would work, this one lookup path hands back garbage. I'm
  noting this because it's a plain Python bug (wrong `.group()` index), not a solving-effectiveness
  question — if the owner wants this fixed by someone, it's a five-minute fix, but I'm leaving the
  decision to touch that file with the owner's other platform rather than doing it myself.

## 3. Architecture: how to make it collect "everything" the way the rest of this project does

This is the real ask: not just "fix the bugs" but "make this collect as completely and reliably as
every other source in the board." The existing pipeline has four habits that this new code doesn't
have yet, and all four are plain engineering, not bypass work:

1. **Resumable, not restart-from-zero.** Every scraper in this repo that can't finish in one run
   either paginates with a saved cursor or gets re-run by `scripts/verification_sweep.py`-style
   priority ordering (worst-covered county first). The walled-sources run instead restarts its whole
   county list from the top every night, so slow counties near the end of the list (Spartanburg,
   the SC Public Index tail) may never get a real pass. **Fix:** a manifest file per source
   (`data/walled_output/<source>.manifest.json`: `{county: last_success_at}`), and start each run
   from whichever counties are stalest, not alphabetically first.
2. **Honest outcome taxonomy.** This repo's convention is `OK` / `ZERO_RESULT` / `BLOCKED` /
   `TIMEOUT` / `ERROR`, every one distinct and logged. The walled-sources run currently only has
   `OK` and `ZERO_RESULT`, which is why a WAF block and a genuinely empty county look the same (item
   2 above). Adopting the same five outcomes makes this source auditable the same way every other
   source already is — `scripts/audit_checks/*` can then write an invariant for it, same pattern as
   everything else this week.
3. **Row identity that survives a re-run.** Item 1 (the `address`/`zip` bug) is the acute version of
   this, but even once fixed, this source should key rows the same way `verification/core.row_keys()`
   does: parcel first, then case number, then address, so a re-run of the same county updates the
   same board row instead of creating a near-duplicate. Right now there's no guarantee of that once
   the field bug is fixed, because `wire_walled_to_board.py` builds its own key logic from scratch
   instead of reusing the shared one.
4. **Feed into the existing verification and scrub layers, not around them.** Once rows land on the
   board with real parcels/addresses, they should go through exactly the same path every other
   source's rows go through: `tax_binding.scrub_unbound_tax`, `block_binding.scrub_unbound_blocks`,
   `identity.run_identity_pass`, and the signal verifiers. Nothing about this source should bypass
   those — they're what catches a wrong-parcel tax balance or a fused row, which is exactly the kind
   of mistake raw walled-source output is likely to contain until it's proven otherwise. Plugging in
   correctly just means `wire_walled_to_board.py` should write into the same board format
   (`Listing.model_validate`) and go through `main.py`'s merge path, not write directly.
5. **A run-profile entry, if the owner wants this on the standing schedule.** Right now this is a
   one-off `nohup` with no flag in `deploy/oracle/run_profile.json`. If it's going to run every
   night, it should have the same thing every other phase has: a named env flag, a time budget, and
   a line in the profile saying what it is and why it's on — not for me to flip on, but so the gate I
   run doesn't flag it as an unknown, unaccounted-for process the next time I check the VM.

## 4. What is already working well, specifically

- `sc_dew_lien_registry.py` direct-bundle fetch: 5,161 real rows in 75 seconds, no browser needed —
  this is a genuinely good find (a public data export endpoint that doesn't need the DEW site's
  front door at all).
- `counties_sc.sc_probate_notices`, `counties_sc.sc_public_notices`, `public_notices.nc_notices_counties`:
  plain-HTTP, no bypass involved, produced real volume (1,003 / 688 / 619 rows respectively) with no
  errors in the log.
- `session_persist.py`: sound code, reasonable session-expiry logic. If NC estates switches back to
  headless and reuses a persisted session instead of re-solving every run, this is the piece that
  makes that cheap.
- Date-window recursive splitting for SC Public Index: correct, no rows lost at window boundaries,
  terminates properly (verified by hand-tracing a 15-day window split down to single days).

## 5. What I will not do, restated

I won't improve the success rate of `wall_bypass.py`, `enrichment_recaptcha_v3.py`,
`enrichment_recaptcha_audio.py`, or `math_captcha.py` at defeating a challenge, and I won't wire any
of them into the main pipeline I run. Everything in sections 1–3 above is available on request and
touches none of that — it's the same category of fix I've made all week on other sources (field
mapping, dedupe keys, timeout budgets, ledgers, honest outcomes).
