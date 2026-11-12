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

---

## MEASURED RECONCILIATION — 2026-09-10

The grid above is what the plan says SHOULD exist. This section is what the
published board actually CONTAINS, measured by `scripts/county_coverage_matrix.py`
against `docs/listings.json.gz`. Where they disagree, the measurement wins.

### The plan counts SIGNALS. A signal is not a lead.

A lead is workable only when five layers exist: SIGNAL, IDENTITY (parcel + situs
address), VALUE (county 100%-basis appraisal), CONTACT (owner name + phone or
mailing), RANKED. The Aug-12 grid scores only the first. That is why "40% HAVE"
and a board you cannot call from are both true at once.

Measured, per footprint county, worst layer first:

| county | rows | ident | value | mail | phone | signal families |
|---|---|---|---|---|---|---|
| Cherokee,SC | 1,136 | 0% | 1% | 0% | 8% | 3/9 |
| Union,SC | 496 | 6% | 3% | 2% | 16% | 4/9 |
| Gaston,NC | 2,473 | 23% | 18% | 7% | 66% | 6/9 |
| Cleveland,NC | 1,105 | 25% | 26% | 10% | 62% | 6/9 |
| Laurens,SC | 979 | 27% | 22% | 12% | 11% | 6/9 |
| Anderson,SC | 1,230 | 28% | 32% | 5% | 18% | 6/9 |
| Lincoln,NC | 1,354 | 28% | 43% | 29% | 75% | 7/9 |
| Transylvania,NC | 580 | 28% | 32% | 13% | 57% | 5/9 |
| Oconee,SC | 1,315 | 31% | 1% | 62% | 11% | 4/9 |
| Burke,NC | 671 | 39% | 31% | 16% | 68% | 6/9 |
| Henderson,NC | 2,810 | 48% | 56% | 11% | 56% | 7/9 |
| Polk,NC | 421 | 49% | 26% | 15% | 56% | 5/9 |
| McDowell,NC | 1,913 | 67% | 80% | 73% | 56% | 6/9 |
| Spartanburg,SC | 6,195 | 68% | 75% | 68% | 13% | 7/9 |
| Pickens,SC | 2,711 | 69% | 78% | 70% | 13% | 6/9 |
| Rutherford,NC | 4,929 | 69% | 86% | 84% | 50% | 6/9 |
| Buncombe,NC | 7,404 | 75% | 70% | 66% | 89% | 6/9 |
| Mitchell,NC | 187 | 78% | 63% | 38% | 50% | 5/9 |

### The one finding that reframes the whole plan

**NC phone 50-89%. SC phone 8-18%.** NC's phones are a side effect of LiensNC
lien-agent filings, where the owner publishes their own number: 56,452 of the
board's 67,217 phones carry `match="self_filed_lien_agent_appointment"`. SC has no
free equivalent, so all seven SC counties are mail-only. 14,062 SC leads, no phone
lane. That is the engine's binding constraint, and no amount of additional SIGNAL
scraping relieves it.

Two corrections to assumptions worth recording:
- `raw.skip_trace` carries NO phone numbers. `phone_numbers` is empty on all 21,400
  rows that have it and `provider` is 100% `tax_records_only`. It is a mailing-address
  source and was being counted as a contact source.
- Only 240 phones are `attorney_in_notice`, so the phone count is not meaningfully
  inflated by attorney/trustee numbers.

### Signal families, measured across the 18 footprint counties

    code_vacancy            2/18   the real worst gap
    divorce                 5/18   Buncombe 38, Transylvania 9, Cleveland 4, Henderson 1, McDowell 1
    tax_foreclosure         6/18   the book's sharpest filter
    tax_delinquent         10/18   the book's PRIMARY source, missing from 8 counties
    liens                  15/18
    probate_estate         16/18
    mortgage_foreclosure   17/18
    lis_pendens            17/18
    bankruptcy             17/18

CORRECTION: an earlier pass of this section reported divorce at 0/18. That was a
classifier bug, not missing data. `_family()` is first-match-wins and the
`lis_pendens` pattern list contained a bare "ecourts", which is checked before
`divorce` -- so nc_ecourts_divorce (75 board rows, 53 in-footprint) was being
counted as lis_pendens. NC eCourts serves four distinct dockets (divorce, estates,
judgments, lis pendens); each now matches on its own noun.

### "HARD-WALL 0" needs one amendment

The Aug-12 claim that no cell is a true hard wall holds for SIGNAL. It does not
hold for CONTACT in South Carolina: free people-search is bot-walled, the SC voter
file is paid and carries no phone, and SC SoS is captcha-walled. SC phone is a real
wall until a paid lane or a manual-save lane is accepted.

### Build queue, ranked by what actually blocks a deal

1. SC phone lane. Binding constraint on 14,062 leads. No free path identified.
2. Cherokee SC (identity 0%, value 1%) and Union SC (6%/3%) — 1,632 rows that can
   be neither underwritten nor contacted. Either resolve them or stop counting them.
3. Gaston NC identity 23% / value 18% on 2,473 rows — worst NC county, and Gaston
   is in a major MSA so the exit is good if the data can be filled.
4. tax_delinquent into the 8 counties missing it; tax_foreclosure into the 12.
5. divorce (0/18) and code_vacancy (2/18) as whole missing families.
6. Oconee SC value 1% — has mail (62%) but nothing to underwrite against.
