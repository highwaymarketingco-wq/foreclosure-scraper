# CCS name-search zero yield (Caldwell/Franklin/Gates) — rigorously isolated, still unexplained

Earlier today's finding ("zero yield confirmed on common surnames") understated
how deep this goes. Re-investigated with a proper A/B against Gaston's own
proven-working host. Full elimination chain below.

## What's confirmed NOT the cause

1. **Request body shape** — `nc_ccs_name_search.py`'s `_body()` is
   byte-for-byte identical to `enrichment_gaston_rod.py`'s own proven `_body()`
   (same field list, same order, same `SearchType=3`/`CodeType=3`/
   `IndexType=3`/`MatchType=beginswith`/`MultiNameSearchType[]=3`). Ruled out
   by direct source comparison.
2. **Parameter values being invalid for this tenant** — read Caldwell's own
   live LRIndex seed page's `<select>` option lists directly (not assumed):
   `IndexType` offers exactly `3=Mixed, 2=Temporary` (no "Permanent" option
   exists at all). **Gaston's own seed page offers the exact same two
   options, same values.** Ruled out — this isn't a per-tenant numbering
   mismatch.
3. **The query itself being invalid/too narrow** — tried both `SMITH`
   (common surname) and a bare single letter `A` (beginswith) against
   Caldwell. Both returned a clean `DXEmptyRow` marker, zero `DXDataRow`s,
   real 200 OK responses (not errors). A single-letter beginswith search
   returning literally zero matches is not plausible for a real deed/
   mortgage index of any size.
4. **The mechanism itself being broken** — the identical `_body('SMITH', '')`
   call, same `_PageSession`/`_run_stealthy` browser-fetch() technique,
   against **Gaston's** host (not Caldwell's) returned 200 real rows going
   back to 1848 (e.g. SMITH/ANDREW grantor, 01/01/1848, book 1 page 113).
   Proves the mechanism, session-seed step, and search POST all work
   correctly end-to-end when pointed at a tenant that has real indexed data.

## What's left unexplained

Caldwell (and by extension, very likely Franklin/Gates, not independently
re-isolated this deeply today but sharing the identical code path) returns a
clean, well-formed, zero-result response to a query that is proven correct in
shape and proven to work against a sibling tenant on the same vendor
platform. Two live possibilities, not yet distinguished:

- **Genuinely sparse/new digitization** — Caldwell's CCS deployment might
  cover a much smaller, newer slice of records than Gaston's (which reaches
  back to 1848). If Caldwell's whole digitized index is small enough, even a
  common surname or single letter COULD legitimately return nothing -- but
  this would be an unusually tiny index for a real county.
- **A session/state difference the seed step isn't capturing** — something
  about how Caldwell's specific tenant instance establishes server-side
  search context might differ in a way not visible in the request/response
  bytes checked so far (e.g. a required prior interaction this headless
  browser session isn't triggering).

## Recommendation

This has had a genuinely rigorous elimination pass today, not a guess-and-
reload loop -- don't re-attempt via more parameter guessing. Next real step
would be a human (not automated) browser session on Caldwell's actual site,
manually performing a real single-letter search and watching whether it
also comes back empty for a person -- that would settle "genuinely sparse
index" vs. "something session-specific breaks automated access" in one
observation, which no amount of further scripted probing will resolve on its
own.
