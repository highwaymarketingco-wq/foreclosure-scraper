# Road to 100% — Footprint Coverage Plan

**Date:** 2026-08-12. **Goal:** every footprint county (core + coastal) at 100% of all
12 distress signals. **Method:** free scraping + operator manual-save lanes only. No paid.
No CAPTCHA solving, no robots-Disallow riding, no people-search PII (project compliance
constitution holds).

Style: no em dashes.

## The map

Full county x signal grid: [`road_to_100_matrix.md`](road_to_100_matrix.md). Free-alternate
research: [`courts`](road_to_100_alternates_courts.md), [`rod_tax`](road_to_100_alternates_rod_tax.md),
[`signals`](road_to_100_alternates_signals.md).

**360 cells (30 counties x 12 signals):** HAVE 145 (40%), PARTIAL 64 (18%), GAP 151 (42%).
By lane: FREE-BUILT 225, FREE-BUILDABLE 108, FREE-ALTERNATE-NEEDED 21, MANUAL-SAVE 6,
**HARD-WALL 0.**

**Headline:** no cell is a true hard wall. Every walled source (NC eCourts Smart Search,
SC PublicIndex, Sturgis/Avalon balance API, Kofile/qPublic ROD) has a named compliant free
alternate, and the two press-association public-notice portals already carry the mandated
foreclosure / estate / probate / tax-sale notices for the whole footprint.

## The lever findings

1. **Clay / Haywood / Yancey are a policy toggle, not a wall.** All three sit at 0% only
   because they are in `config.SCOPE_DENY_COUNTIES`, dropped even from statewide bypass
   sources. Un-deny them and they immediately ride the existing NC court / firm / deed
   scrapers. Fastest single win on the board.
2. **The 9 coastal counties are oceanfront-gated.** Dedicated scrapers exist
   (`charleston_mie`, `sc_coastal_rosters`, `horry_flc`, `nc_coastal_tax_foreclosure`, ...)
   but `main._in_scope` caps them to the near-beach fraction, so their best cells read
   PARTIAL not HAVE. Widening that gate is the lever, IF the buy-box intent is all-coastal-
   distress rather than beach-only. DECISION NEEDED before flipping.
3. **The genuine build gaps are signal concentration:** S11 senior/disabled exemption
   (Buncombe-only, and FOIA-walled elsewhere), S10 code enforcement (Spartanburg-only,
   FOIA elsewhere), S9 liens (~unbuilt).

## Priority order to 100%

### Tier 1 — Config toggles (near-instant, biggest jump, free)
- Un-deny Clay / Haywood / Yancey from `SCOPE_DENY_COUNTIES` (3 of the 5 worst counties, 0% -> riding all NC scrapers).
- Widen the oceanfront gate in `main._in_scope` for the 9 coastal counties (PARTIAL -> HAVE). Confirm buy-box intent first.

### Tier 2 — Wire built-but-unwired free sources (low effort)
- SC coastal probate: Georgetown / Colleton / Dorchester on `southcarolinaprobate.net`, same code as the live Charleston feed. Unwired, not blocked.

### Tier 3 — FREE-BUILDABLE gaps (108 cells, open endpoints needing code)
- County tax-collector delinquent PDFs + ArcGIS delinquent layers for the counties not yet flowing.
- qPayBill unpaid ladders for remaining SC counties.
- Land / lien / absentee facets where a free endpoint exists.

### Tier 4 — FREE-ALTERNATE-NEEDED (21 cells, wire the alternate feed)
- Confirm ncnotices.com / scpublicnotices.com coverage is wired for every footprint county and every mandated-notice signal (foreclosure, estate, tax sale).

### Tier 5 — MANUAL-SAVE operator lanes (6 cells)
- SC divorce (FCCMS, off-portal), NC coastal estates (eCourts WAF), Horry / Berkeley SC probate. Operator saves the page, offline parser ingests. Extend the existing `ingest_saved.sh` lane.

### FOIA lane (records requests, not code)
- Senior / disabled / veteran exemption rolls beyond Buncombe (PII-adjacent, suppressed on parcel layers).
- Code enforcement / condemnation beyond Asheville + Spartanburg.

### Downstream caps (not source gaps, worth their own push)
- Name -> parcel resolver ceiling ~25-30%. Mailability ~29.5%. These limit how many captured
  filings become actionable leads even at 100% source coverage.

## What does NOT get touched
- `rutherford_wildfire_tax.py` (robots, fails closed by design) and every other robots/ToS wall stays walled. We use the named free alternate, never ride the wall.
