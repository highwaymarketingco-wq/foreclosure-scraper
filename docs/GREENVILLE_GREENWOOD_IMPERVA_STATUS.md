# Greenville/Greenwood Imperva - Status Check

## 2026-11-24 RESOLVED -- neither one is actually walled

Both items below turned out to be non-issues once re-tested directly. Closing
this out; do not re-flag these as walled/blocked without new live evidence.

**Greenville Probate -- NOT blocked, already live in production.**
- URL: https://www.greenvillecounty.org/appsas400/Probate/SearchResults.aspx
- Live-tested with plain `curl` (no browser, no Cloudflare-solve, just a
  normal browser User-Agent): got a real 200 response with "2651 Matches
  Found" and a genuine `JobsTable` in ~1 second, first try. The site's CDN
  really is Imperva (`x-cdn: Imperva` header, `incap_ses_*`/`visid_incap_*`
  cookies -- that part of the original report was accurate), but Imperva is
  not actually challenging this request shape at all.
- `src/foreclosure_scraper/scrapers/counties_sc/greenville_probate.py` (the
  existing scraper, last verified live 2026-10-13) already uses exactly this
  plain-httpx-with-redirect-follow approach and is already wired into
  `main.py`. Independent confirmation: the combined verify-sweep's own
  `probate_heir_greenville` ledger is actively climbing right now (706 -> 906
  across a handful of ticks today), meaning this scraper has been producing
  real rows in production the whole time.
- Whatever produced the original "403s even with increased delays" finding,
  it was not reproducible against the real site on a plain, UA-bearing
  request. Nothing here needs StealthyFetcher/browser-based Cloudflare
  solving -- the existing plain-httpx scraper is correct as-is.

**Greenwood -- the real search mechanism already existed, just never finished
building its index.**
- The `.gov` guess (greenwoodsc.gov/148/Probate-Court, 404) was the wrong
  domain -- the real county site is `greenwoodcounty-sc.gov`. Its Probate
  Court page (https://www.greenwoodcounty-sc.gov/probate-court) links an
  "Estate Records Search" at a third-party vendor:
  `https://scportal.hostedbyspartan.com/GreenwoodPublicPortal/pages/InquiryMainPage.aspx`
- That vendor (Spartan's hosted public-probate-inquiry app) is NOT a new
  integration need -- `src/foreclosure_scraper/enrichment_probate_spartan.py`
  already covers Greenwood (plus Newberry and Calhoun on the same vendor),
  built and wired into `main.py` back on 2026-10-09, over a month before this
  doc's original Greenwood-URL question was written. It reads the court's
  whole decedent index (a JSON DataTables handler, no login/CAPTCHA) and
  matches it offline against board owners -- a bulk-index read, not a
  per-owner search, so there was never a "probate search URL" to discover in
  the sense this doc was looking for.
- Why no Greenwood/Newberry data had landed: their decedent indexes
  (20,545 / 13,366 decedents) never finished a first full build -- only
  Calhoun's (3,674) completed, same day the module was written. Confirmed
  live 2026-11-24 this is not a code bug: a direct `read_index()` call against
  Greenwood's real portal works cleanly. Board already carries 1,303
  Greenwood + 1,253 Newberry SC rows, so the enrichment's own precondition
  gate was never the blocker either. Most likely cause: these two indexes are
  each much bigger than Calhoun's and may not have gotten a long enough
  uninterrupted slice in a regular `main.py` enrichment pass to finish in one
  go -- but the module's own on-disk cache (`data/probate_index/*.json`) is
  resumable across runs by design.
- Fix in progress: `scripts/run_probate_spartan_now.py` (new) drives
  `enrich_probate_spartan()` directly against just Greenwood+Newberry with a
  long deadline, so its resumable cache can actually reach completion outside
  the regular pipeline's possibly-too-short slice.

**Status:** Both closed. Neither needed StealthyFetcher/browser-based
Cloudflare-or-Imperva solving -- plain httpx was already correct for both,
the real blockers were a stale docstring/URL guess (Greenwood) and an
index-build that needed a dedicated run to finish (Greenwood/Newberry).
