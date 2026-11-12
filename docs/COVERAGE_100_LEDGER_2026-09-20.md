# Coverage ledger, 18-county footprint, 2026-09-20

Measured on the live board (170,528 rows, 75K of them in the footprint) with
`scripts/coverage_100_ledger.py`. Every number below was counted, not estimated.
Regenerate any time: `uv run python scripts/coverage_100_ledger.py`.

## What "100%" means here

- **There are two scopes, and this ledger covers only the narrower one.** Flip-type leads
  (a scheduled foreclosure, sheriff or HOA sale, an auction, REO) are in scope only in the 18
  `config.py` footprint counties. NC: Rutherford, Cleveland, Henderson, Polk, Gaston,
  Buncombe, Transylvania, McDowell, Lincoln, Mitchell, Burke. SC: Spartanburg, Anderson,
  Pickens, Oconee, Cherokee, Union, Laurens. Distressed leads (tax delinquency, liens,
  probate, divorce, code enforcement and the like) are in scope in all 146 NC and SC
  counties (`config.in_scope_distressed`, owner direction 2026-09-15). The first version of
  this ledger called the roughly 90K rows outside the footprint "out of scope by the owner's
  direction". That was wrong for distressed leads. Their coverage is measured in
  `docs/AUDIT_2026-09-21.md`; this ledger's per-county layer table stays footprint-only.
- **Free and public data only.** No paid APIs, no CAPTCHA or WAF bypass, no robot-held logins.
  A cell that needs one of those is WALLED, and is reported as a wall, not a gap.
- A county is covered only when every layer is present: identity (parcel and situs), value,
  owner name, mail, phone, actual debt. The weakest layer is the county's real coverage.

## Layers today (share of each county's leads; arrows show this session's change)

| County | Rows | Identity | Value | Mail | Phone | Actual debt | Weakest layer |
|---|--:|---|---|---|--:|---|---|
| Rutherford NC | 5,005 | 77% | 89% | 91% | 46% | 85% | phone |
| Cleveland NC | 1,169 | 51% > **74%** | 51% > **52%** | 53% > **74%** | 39% | 3% | debt |
| Henderson NC | 2,773 | 60% > **63%** | 75% | 64% > **80%** | 42% | 52% | phone |
| Polk NC | 470 | 56% > **66%** | 56% | 59% > **67%** | 36% | 9% | debt |
| Gaston NC | 9,810 | 81% | 67% | 14% > **86%** | 12% | 1% | debt |
| Buncombe NC | 8,949 | 71% | 69% > **70%** | 70% > **76%** | 65% | 23% > **25%** | debt |
| Transylvania NC | 6,204 | 71% | 91% > **92%** | 5% > **92%** | 3% | 1% > **7%** | phone |
| McDowell NC | 2,147 | 68% | 82% | 79% > **89%** | 44% | 66% > **67%** | phone |
| Lincoln NC | 3,632 | 73% | 80% > **81%** | 27% > **87%** | 21% | 13% | debt |
| Mitchell NC | 238 | 60% > **68%** | 60% | 66% > **73%** | 29% | 2% | debt |
| Burke NC | 1,391 | 59% > **70%** | 31% > **51%** | 41% > **74%** | 32% | 4% | debt |
| Spartanburg SC | 15,311 | 53% > **69%** | 42% > **55%** | 52% > **69%** | 5% | 13% > **38%** | phone |
| Anderson SC | 2,620 | 15% > **41%** | 16% > **42%** | 11% > **41%** | 9% | 24% | phone |
| Pickens SC | 4,629 | 47% > **52%** | 46% > **5%** (correction) | 58% > **69%** | 8% | 43% | value |
| Oconee SC | 3,309 | 50% | 52% | 68% | 5% | 33% > **74%** | phone |
| Cherokee SC | 2,949 | 37% | 38% | 8% | 3% | 6% > **43%** | phone |
| Union SC | 1,368 | 46% | 46% | 3% > **40%** | 6% | 6% > **53%** | phone |
| Laurens SC | 3,203 | 33% > **37%** | 44% | 38% > **46%** | 3% | 8% > **46%** | phone |

Pickens value is a correction, not a loss. The old 46% counted 2,030 leads whose "market value"
was really an acreage (0.59, 1.24, 6.59). Real Pickens value coverage is 5%.

## Signals (lead count per family; 0 means no lead carries it)

8 of 180 county-by-family cells are empty (11 at the start of the session). Full grid: run the ledger script.

| Empty cell | Disposition |
|---|---|
| tax_sale in Transylvania, Mitchell | Buildable but low odds: Column public-notice recon (T-01). Transylvania Times is robots-disallowed. |
| tax_sale in McDowell | Legitimately empty: the county page says no sales are scheduled. Re-check in season. |
| divorce in Lincoln, Mitchell | Open Judgment Search sweep (V-01). NC Smart Search is behind an AWS-WAF CAPTCHA (wall). |
| incarceration in Transylvania | Rosters are wired and checked: 0 of 432 person-owned leads match the 91 names in custody, a genuine zero. |
| incarceration in Mitchell, Union | State-prison name match only. No county roster is known or reachable. |
| incarceration in Cleveland, Lincoln, Oconee | Filled this session from county jail rosters. |

SC divorce is covered: 28,660 of about 30,300 eligible SC leads were searched against the FCCMS
public portal, 5,523 have a case. The rest are company names and sources that historically hit 0%.

## Fixed this session (all committed, all verified on the board)

| What | Before | After |
|---|---|---|
| Court-verified divorce reaches the score | 5,523 hits ranked nothing | 1,714 stacks carry it; recency-weighted (47% of cases are over 15 years old) |
| Old code stamped failed FCCMS searches "no divorce" | unknown | 715 suspect stamps cleared and re-searched; 42 real cases recovered (5.9%) |
| Actual debt known (`balance_owed` was never read) | 29,274 leads | 63,806 leads |
| Pickens acreage stored as market value | 2,030 leads, one rated HOT off a $0.59 value | 0; ARV, equity, tier and rank re-derived |
| `gis.last_sale.amount` stored as text | 588 rows, crashed the valuation pass | all numeric; parser added to both writers |
| Parcel-cache join was never re-run | 31,038 mailings unfilled | filled, plus 14,396 values, 5,249 owner names, 3,985 situs, 17,429 absentee flags |
| Per-lead mailing pass (90 min, partial) | Union 3% | Union 40%; +1,366 mailings |
| Irreplaceable Anderson owner database | one copy | verified backup at `~/Documents/foreclosure-backups/` |
| Anderson name resolver had no backend (the offline owner roll had no callers) | 0 leads resolved | 201 of 1,091 resolved (87 ambiguous flagged, not guessed); with the offline mailing pass, identity 15% to 41%, mail 11% to 42% |
| Incarceration re-queried the same 150 leads every run (no stamp on a miss) | 267 flagged, 6 empty cells | negatives stamped; 412 more leads flagged from 10 county jail rosters (509 total); cross-county control put coincidental matches at roughly 5 to 10% |
| Burke storm-damage leads stored a record number as parcel_id | 397 leads, no owner, mailing or value | 282 resolved by exact street address against the county cache (coordinates were tried first: 72% landed on the wrong parcel); value 31% to 51%, mail 42% to 63% |
| Overnight per-lead mailing pass (Burke, Cleveland, Polk, Mitchell, Union; 1,455 leads) | mail 54-74% | +597 mailings, 430 newly absentee; Cleveland identity 51% to 74%, mail 54% to 74%; Burke mail 63% to 74% |
| Deed-index defects behind the dormant `repeat_tax_loss` | 4 classifier and join defects | fixed with 179 tests; CCHS sweep built but the live search is behind a Cloudflare challenge |

Tiers per lead after all of it: HOT about 1,900, WARM about 70,700, COLD about 94,900 (a mailable owner gates HOT;
the recompute also applied the existing quality downranks to carried-over rows).

## What is left to build (measured, ranked)

| Item | Counties | Lift | Status |
|---|---|---|---|
| Finish the per-lead mailing pass for the larger counties (Buncombe 1,729, Laurens 785, Gaston 765, Oconee 537, Pickens 534 and others; about 6,000 leads) | 10 | mail | Build-ready. About 15 leads a minute, polite by design; needs several multi-hour runs in a window with no scheduled board writer. |
| Promote the PTS-cloud `mailing` block into `owner_mailing` (Henderson tax rows carry it, 885 leads) | Henderson | mail, absentee | Build-ready, small. |
| Laurens qPayBill rows keyed by account number, not parcel (393 leads); Rutherford tax and heir-estate rows (338) | 2 | identity, value | Needs a per-source key map. |
| Cherokee situs from the ledger row (I-04) | Cherokee | identity | Build-ready, small. |
| Deed-index sweep for `repeat_tax_loss` | 7 buildable, 11 walled | about 790 loss deeds a year footprint-wide | Code and 179 tests done; the live search is behind a Cloudflare bot challenge. Re-check politely later. Small signal even fully built. |

Queue items I measured and did not build: D-02 (Cherokee 16-digit IDs: about 28 leads at most),
I-03 (Pickens EnerGov value: 15% populated, tax year 2027, does not match assessed values),
M-02 as a parcel-cache entry (adding SC Union under that name would stop the NC Union cache
refreshing; needs a state-aware refresh API), M-01 (only 363 Transylvania rows).

## What 100% cannot mean

- **SC phone (3 to 9%)**: the SC voter file is paid and phone-less; consumer people-search is
  bot-walled and barred. Free ceiling is about 21% board-wide.
- **Cherokee and Union parcel owner, mailing, value**: Cloudflare interstitial on the assessor
  portal. Cherokee mail stays at 8%.
- **NC eCourts Smart Search (estates, raw divorce filings)**: AWS-WAF CAPTCHA.
- **Live payoff balances, NC power-of-sale debt, SC exempt-deed prices**: the data is not published.
- **Nine deed-index hosts**: `robots.txt` Disallow. Whether that counts as a wall is an owner decision.

## Decisions (all settled as of 2026-09-21)

1. The daily court job (failing since 8/20, and it would have enabled a CAPTCHA solver and automated SC
   Public Index queries) was unloaded. To re-enable, rename its plist in `~/Library/LaunchAgents` back.
2. `robots.txt` Disallow does not count as a wall. CAPTCHA, login, hard 403 or Cloudflare challenges, and
   click-through terms still do.
3. Land max bids: no change. On land, an ARV up to 6x the county appraisal is accepted and 20x is withheld
   (`ARV_ANCHOR_SOFT_MULT_LAND` and `ARV_ANCHOR_HARD_MULT_LAND` in `valuation/calc.py`, calibrated to the
   board's p90 and p99). The 445 Lincoln land leads with a bid over 2x assessed sit inside that band, carry
   `geo_imprecise_comps` at MEDIUM or LOW confidence, and are cold tier with no deal verdict. A backtest
   against recent recorded sales was too thin to justify re-calibrating (54 leads, none in Lincoln, which has
   no recorded sales for them); it leaned toward inflation in Rutherford and Henderson (about 3x recent
   sale prices against 1.4x for ordinary land). If a tighter guard is ever wanted, lower the soft multiple.
