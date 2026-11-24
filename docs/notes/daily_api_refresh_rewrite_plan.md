# daily_api_refresh.py rewrite — scoping notes (2026-11-24)

## Why this isn't a simple load_board()->append_new_rows() swap

The two scripts fixed earlier tonight (ingest_nc_never_run_batch2.py,
ingest_counties_generic_never_run.py) only ever touched a small, bounded set of
*new* candidate rows. `load_board()` was incidental there — easy to replace with
a streamed check against the existing board.

`daily_api_refresh.py` is different by design, not by accident:

1. **Churn/merge logic** (lines ~145-216): matches fresh-pulled rows from ~14
   REO/API sources against their own prior rows by normalized address, refreshes
   volatile fields (source_url/case_number/price), drops rows missed 4+ pulls in a
   row. This part genuinely only needs the prior rows *from those 14 sources* —
   everything else is passed through untouched (`if li.source not in healthy:
   out.append(li); continue`). **This part is scopable**, same pattern as
   tonight's fixes.

2. **Whole-board re-grade/re-score/equity recompute** (lines ~273-323): `_regrade()`,
   `enrich_equity()`, `enrich_derived_signals()`, `enrich_data_quality()`,
   `enrich_title_risk()`, `score_board()`, and a second `dedupe()` pass all run over
   `merged` — which is effectively the *entire* board (untouched rows got appended
   to `out` unchanged, so they're still in `merged`). This recomputes grading/
   scoring for ~636K rows every day even though ~99.98% of them didn't change
   today. **This is the part that actually requires load_board()-scale memory**,
   and it's not a streaming-vs-materializing problem — `dedupe()` and
   `score_board()` are inherently cross-row algorithms (dedupe needs to compare
   candidates against everything; score_board likely needs board-wide context,
   e.g. percentile-style tiering) that resist naive streaming without changing
   their own algorithms.

## What a real fix looks like (not attempted tonight — see below for why)

- Scope the churn/merge step to just the ~14 sources' own prior+fresh rows
  (small, safe, same shape as tonight's fixes) — but the existing cross-source
  `dedupe()` calls (lines 218, 321) exist specifically to catch a refreshed row
  that's secretly the same property as some OTHER, non-refreshed-source row (e.g.
  a Fannie REO listing at the same address as an existing tax-lien record). A
  scoped rewrite needs a *targeted* cross-check (stream the board once, check the
  handful of refreshed-source candidates against it via `_append_dict_sigs()`-
  style signatures) instead of holding the whole board as Listings just to dedupe.
- Decide, separately, whether the whole-board re-grade/re-score/equity pass
  genuinely needs to run *daily* via this script, or whether it duplicates/
  should defer to whatever already handles board-wide scoring on a different
  cadence (main.py's "weekly crawl", per this script's own docstring) — this is
  a real product/architecture decision, not a mechanical fix.

## Why this wasn't attempted tonight

This affects HOT/WARM/COLD tier scoring — i.e., which leads get called first.
Getting a scoped rewrite of cross-row dedupe/scoring logic wrong has much higher
blast radius than tonight's append-only ingest fixes, and deserves dedicated,
unhurried testing (compare scored output against a known-good full run,
row-by-row, before trusting it) rather than being squeezed into a supervision
tick. Flagging this clearly so the next pass at it starts from this understanding
instead of re-deriving it.
