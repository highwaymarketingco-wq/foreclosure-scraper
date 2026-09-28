# Completeness audit, 2026-09-27

Measured read-only on the live board, 215,535 rows (NC 133,309, SC 82,226), streamed once with
`board_stream.iter_board_rows` in a single pass (one additional read of the same stream's listing-type
breakdown for the address-dilution root-cause check in Section 1; no `load_board`, no scraper or
writer ran, no `board_lock`/`write_artifact` call, no git command ran).

This is the direct sequel to `docs/completeness_audit_2026-09-23.md`, which measured a 192,805-row
board four days ago. Every number below is fresh; every comparison below is against that exact
document (not the 2026-09-21 board it in turn compared against). The board grew by 22,730 rows
(+11.8%) in the four days between audits, through a full re-scrape plus two rounds of targeted
fixes described in `docs/coverage_gap_build_plan_2026-09-23.md` — most visibly, `nc_ecourts_lis_pendens.TARGET_COUNTIES`
was widened from 22 NC counties to all 100 (confirmed by reading the scraper source), `nc_ecourts_divorce.py`
now reads that same widened list instead of its own narrow one, the bankruptcy scraper's 21-county
`CITY_TO_COUNTY` dict was replaced by a full 146-county gazetteer module (`_bankruptcy_city_to_county.py`),
and `funeral_home_rss.HOMES` grew from 3 hosts/counties to 10.

Family definitions are unchanged from the prior audit, taken directly off `listing_type`: tax
delinquent = `tax_lien`, tax sale = `tax_sale`, lis pendens = `lis_pendens`, probate = `probate_notice`
+ `estate_lead`, divorce = `divorce_notice`, bankruptcy = `bankruptcy`, code/vacant = `distressed`.
FLIP types and `elderly_disabled`/`unknown` are out of scope for the family-breadth section (covered
in Section 4 and Section 1 respectively). County matching in this pass fixes a casing bug the prior
audit did not have to deal with (`"McDowell".title()` corrupts to `"Mcdowell"` in Python and silently
drops county-Y matches) — a case-insensitive lookup is used instead, confirmed against
`mailing_shape`/`validation.py`'s own documented "Mcdowell vs McDowell" casing-error note.

## Bottom line

**Breadth got dramatically better. Completeness got measurably worse. Both are real, and neither
cancels the other out.**

- **Family breadth**: 92 of 146 counties gained at least one distress family since 2026-09-23. Lis
  pendens coverage jumped from 41 to 118 counties (+77), divorce from 19 to 93 (+74), bankruptcy from
  23 to 48 (+25), probate from 38 to 49 (+11), tax sale from 58 to 60 (+2). The 1-family-only tier
  (was 65 counties, all TaxD-only) collapsed to 10. Two previously-empty counties (Chester, Fairfield
  SC) now have rows. **But the ceiling didn't move**: still exactly 5 of 146 counties at 7/7 (Buncombe,
  Burke, Cleveland, Henderson, Rutherford NC — the same five, all inside the 18-county footprint), and
  Code/vacant coverage is frozen at 49 counties, unchanged to the county, because nothing was built
  against it this week (confirmed structural, not measurement noise: 0 gains, 0 losses).

- **Address/mail/value completeness fell, board-wide, and it is not noise.** Street-address
  coverage: 78.1% → 72.7% (-5.4pp). Rows with neither an address nor a parcel id: 11.5% → 19.7%
  (+8.2pp, i.e. roughly 1 in 5 rows now cannot be located at all, up from roughly 1 in 9). Owner-name
  coverage, which sat at 95.8% and looked closed, fell to 88.4% (-7.4pp). Either-value coverage: 61.0%
  → 56.1% (-4.9pp). **The cause is identified, not mysterious**: the same statewide widening that
  drove the breadth win pulled in tens of thousands of court-docket rows that are, by nature, case-party
  records rather than property records — `lis_pendens` (13,362 rows board-wide) is 7.6% address / 7.3%
  mail; `divorce_notice` (6,678 rows) is 0.6% address / 0.7% mail; `bankruptcy` (5,516 rows) is 5.2%
  address / 6.5% owner-name. These three types alone are >25,000 rows that were never going to carry a
  situs address, and they now make up a much larger share of the board than four days ago. This is a
  real, expected trade-off of the breadth strategy, not a regression bug — but it is a genuine decline
  in the board's address/mail/value completeness by any measure, and is reported here as such.

- **The 18-county flip lane improved substantially and un-ambiguously**: combined "identity + mail +
  value" (the workable-lead bar) rose from 32% to 49.2% (553/1,733 → 1,159/2,356), a +17.3pp gain, with
  total flip-type rows also growing 36% (1,733 → 2,356). The single biggest driver is a comp-based ARV
  now being published (`calc.arv_expected`) on rows that previously had neither a county market value
  nor a comp valuation at all — flip-lane "Value" coverage went from 39% to 88% board-wide, including
  counties that were at literal 0% four days ago (Oconee, Union). Two real regressions inside this
  otherwise-positive picture: Anderson SC fell from 36% to 28% workable (-8.1pp) and Cleveland NC's
  "identity" rate, while up in absolute terms, still caps its workable rate at 30% because most of its
  flip rows still come from national trustee/auction feeds that carry a street address but no parcel id
  — the same structural gap the prior audit named.

## 0. What changed since 2026-09-23 — top-line before/after

| Metric | 2026-09-23 | 2026-09-27 | Δ |
|---|--:|--:|--:|
| Total rows | 192,805 | 215,535 | +22,730 (+11.8%) |
| NC rows | 115,471 | 133,309 | +17,838 |
| SC rows | 77,334 | 82,226 | +4,892 |
| Street address (all) | 78.1% | 72.7% | **-5.4pp** |
| House number (all) | 72.1% | 67.4% | **-4.7pp** |
| Neither address nor parcel (all) | 11.5% | 19.7% | **+8.2pp (worse)** |
| Owner mailing (all) | 65.0% | 64.5% | -0.5pp |
| Owner name (all) | 95.8% | 88.4% | **-7.4pp** |
| Market value (all) | 55.6% | 51.4% | **-4.2pp** |
| Tax value (all) | 46.2% | 45.9% | -0.3pp |
| Either value (all) | 61.0% | 56.1% | **-4.9pp** |
| Counties with 0/7 families | 2 | 0 | -2 |
| Counties with exactly 1/7 | 65 | 10 | -55 |
| Counties with 7/7 (full breadth) | 5 | 5 | +0 |
| Lis pendens present in (of 146) | 41 | 118 | **+77** |
| Divorce present in (of 146) | 19 | 93 | **+74** |
| Probate present in (of 146) | 38 | 49 | +11 |
| Bankruptcy present in (of 146) | 23 | 48 | +25 |
| Tax sale present in (of 146) | 58 | 60 | +2 |
| Code/vacant present in (of 146) | 49 | 49 | +0 (frozen) |
| 18-county flip rows | 1,733 | 2,356 | +623 (+36%) |
| 18-county flip lane, identity+mail+value | 32% (553) | 49.2% (1,159) | **+17.3pp** |

## 1. Address completeness

| Group | Rows | Street address | With a house number | Neither address nor parcel |
|---|--:|--:|--:|--:|
| **All (now)** | 215,535 | 156,753 (72.7%) | 145,214 (67.4%) | 42,561 (19.7%) |
| All (2026-09-23 baseline, 192,805 rows) | 192,805 | 150,617 (78.1%) | 139,069 (72.1%) | 22,092 (11.5%) |
| **NC (now)** | 133,309 | 93,298 (70.0%) | 84,605 (63.5%) | 31,901 (23.9%) |
| **SC (now)** | 82,226 | 63,455 (77.2%) | 60,609 (73.7%) | 10,660 (13.0%) |
| NC (2026-09-23 baseline) | 115,471 | 88,682 (76.8%) | 79,942 (69.2%) | 14,668 (12.7%) |
| SC (2026-09-23 baseline) | 77,334 | 61,935 (80.1%) | 59,127 (76.5%) | 7,424 (9.6%) |

**This is a real, board-wide decline, not sampling noise.** Address share fell in both states: NC
76.8%→70.0% (-6.8pp), SC 80.1%→77.2% (-2.9pp). "Neither address nor parcel" rose in both: NC
12.7%→23.9% (+11.2pp — nearly a quarter of NC rows are now unlocatable by either field), SC
9.6%→13.0% (+3.4pp).

**Root cause, verified by listing-type breakdown of the fresh board** (a second streaming pass over
the same board, read-only):

| Listing type | Rows (now) | Address % | Mail % | Owner-name % |
|---|--:|--:|--:|--:|
| `lis_pendens` | 13,362 | 7.6% | 7.3% | 24.4% |
| `divorce_notice` | 6,678 | 0.6% | 0.7% | 61.1% |
| `bankruptcy` | 5,516 | 5.2% | 5.3% | 6.5% |
| `tax_lien` | 96,542 | 79.3% | 78.0% | 97.2% |
| `tax_sale` | 41,074 | 82.3% | 53.4% | 97.4% |
| `distressed` | 25,959 | 96.9% | 74.9% | 95.9% |

`lis_pendens`, `divorce_notice` and `bankruptcy` together are 25,556 rows — more than the board's
entire net growth this week — and by nature carry a case caption (plaintiff/defendant names, a court,
a filing date) rather than a situs address; a lis pendens or divorce filing does not publish the
debtor's street address, and a bankruptcy docket's caption rarely names one either (confirmed in the
2026-09-23 build plan: county attribution there is done by regexing a city name out of the caption,
not by reading an address field that doesn't exist). **This is the direct, intended cost of the
breadth strategy in Section 3** — widening `nc_ecourts_lis_pendens`/`nc_ecourts_divorce` to statewide
coverage was explicitly sized in the build plan as "Lis pendens, up to ~78 more NC counties, in one
run" with no claim that those new rows would carry property data. The trade was made deliberately and
paid off on breadth; it was not free, and the address/mail dilution above is the bill.

Two smaller, unrelated observations from this pass, not re-verified in depth (out of scope for this
audit's requested deliverables — see the 2026-09-23 audit's own Section 1 sub-items for the
legal-description/placeholder/parcel-cache-disagreement spot checks, which were not re-run here):
the same casing bug class the 2026-09-23 audit and `validation.py` both flag ("Mcdowell" vs
"McDowell") is confirmed still live in the raw board data (10 of McDowell NC's 2,700 rows carry the
lowercase-`d` variant) — cosmetic for this audit because a case-insensitive lookup was used, but it
would still break any exact-string join done elsewhere in the pipeline.

## 2. Owner mailing, owner name, market value, tax value

| Group | Rows | Owner mailing | Owner name | Market value | Tax value | Either value |
|---|--:|--:|--:|--:|--:|--:|
| **All (now)** | 215,535 | 139,034 (64.5%) | 190,433 (88.4%) | 110,715 (51.4%) | 98,986 (45.9%) | 120,913 (56.1%) |
| **NC (now)** | 133,309 | 97,149 (72.9%) | 116,432 (87.3%) | 78,727 (59.1%) | 69,861 (52.4%) | 80,995 (60.8%) |
| **SC (now)** | 82,226 | 41,885 (50.9%) | 74,001 (90.0%) | 31,988 (38.9%) | 29,125 (35.4%) | 39,918 (48.5%) |
| All (2026-09-23 baseline) | 192,805 | 125,323 (65.0%) | 184,649 (95.8%) | 107,188 (55.6%) | 89,116 (46.2%) | 117,581 (61.0%) |
| NC (2026-09-23 baseline) | 115,471 | 86,005 (74.5%) | 111,789 (96.8%) | 76,742 (66.5%) | 61,010 (52.8%) | 78,983 (68.4%) |
| SC (2026-09-23 baseline) | 77,334 | 39,318 (50.8%) | 72,860 (94.2%) | 30,446 (39.4%) | 28,106 (36.3%) | 38,598 (49.9%) |

Owner mailing held roughly flat board-wide (65.0%→64.5%, -0.5pp) — NC fell slightly (74.5%→72.9%),
SC was flat (50.8%→50.9%). **Owner name is the sharpest single decline in this section**: 95.8%→88.4%
board-wide (-7.4pp), almost entirely an NC effect (96.8%→87.3%, -9.5pp) versus a smaller SC slip
(94.2%→90.0%, -4.2pp) — consistent with the same lis-pendens/divorce/bankruptcy dilution named in
Section 1 (`bankruptcy` rows are only 6.5% owner-name; a federal docket caption names a debtor but the
scraper doesn't reliably promote that name into `owner_name`). Market value fell 55.6%→51.4% and
either-value fell 61.0%→56.1%, both roughly proportional to the address decline rather than a separate
problem — the same new-row mix that lacks an address mostly also lacks a valuation, since valuation
pipelines key off parcel/address resolution.

## 3. Distress-family breadth, all 146 NC+SC counties (fresh)

**5 of 146 counties have all 7 families** (unchanged from 2026-09-23): Buncombe NC, Burke NC,
Cleveland NC, Henderson NC, Rutherford NC. All five sit inside the 18-county footprint; not one of
the other 141 counties reached full breadth this week, despite 92 of them gaining at least one family.

**0 of 146 counties have zero rows now** (down from 2: Chester SC and Fairfield SC both picked up a
handful of tax-sale rows — 17 and 6 respectively — moving them from 0/7 to 1/7).

Family-count histogram, all 146 counties, with the 2026-09-23 baseline alongside:

| Families present | Counties (now) | Counties (2026-09-23) | Δ |
|--:|--:|--:|--:|
| 0/7 | 0 | 2 | -2 |
| 1/7 | 10 | 65 | **-55** |
| 2/7 | 14 | 27 | -13 |
| 3/7 | 47 | 18 | **+29** |
| 4/7 | 37 | 8 | **+29** |
| 5/7 | 14 | 9 | +5 |
| 6/7 | 19 | 12 | +7 |
| 7/7 | 5 | 5 | +0 |

The 65-county "TaxD-only" wall the build plan identified as the single biggest gap is effectively
gone — only 10 counties remain at exactly 1 family. The shape of the board moved from a long left tail
(most counties clustered at 1-2 families) to a mode at 3-4 families. This is the direct, verified
payoff of the lis-pendens widening and the bankruptcy gazetteer: **92 of 146 counties (63%) gained at
least one family this week**; of those, 20 gained exactly one family tier, 49 gained exactly two, 21
gained exactly three, and 2 — Johnston NC and Wilson NC, both 1/7→5/7 — gained four at once, the
biggest single jumps: both went from TaxD-only to TaxD+LisP+Prob+Div+BK in the same run, still
missing TaxS and CV.

**Families ranked by how commonly they're missing (of 146), with the 2026-09-23 baseline:**

| Family | Missing now | Present now | Present, 2026-09-23 | Δ present |
|---|--:|--:|--:|--:|
| Divorce | 53 | 93 | 19 | **+74** |
| Bankruptcy | 98 | 48 | 23 | **+25** |
| Probate/estate | 97 | 49 | 38 | +11 |
| Lis pendens | 28 | 118 | 41 | **+77** |
| Code/vacant | 97 | 49 | 49 | **+0 (frozen)** |
| Tax sale | 86 | 60 | 58 | +2 |
| Tax delinquent | 17 | 129 | 129 | +0 (already near-solved) |

**Lis pendens (+77) and Divorce (+74) are the two headline movers, and they trace directly to the
build plan's #1 and #2 recommendations landing.** `nc_ecourts_lis_pendens.TARGET_COUNTIES` reads all
100 NC counties today (verified in source, was 22); `nc_ecourts_divorce.py` now imports that same
list instead of maintaining its own (verified in source: "the current pagination sizing... vs this
scraper's pagination... reads `nc_ecourts_lis_pendens.TARGET_COUNTIES` directly"). Every NC county
that gained Lis Pendens or Divorce this week did so through that one widening — 77 counties for
LisP, 74 for Divorce, 71 of them overlapping. 6 counties picked up LisP without (yet) showing a
Divorce gain — Avery, Davie, Mecklenburg, Richmond NC plus Edgefield and Saluda SC (the last two via
a separate SC lis-pendens ingestion lane, not the NC statewide widening) — and 3 counties gained
Divorce without LisP (Catawba, Madison, Mitchell NC), consistent with the WAF-solve reliability
caveat the build plan flagged for the divorce path specifically (it still solves an image-grid
CAPTCHA per county; a handful of counties succeeding on one path and not the other in a single run
is expected noise, not a new gap).

**Probate's +11 splits into two mechanisms.** 7 of the 11 gains — Cabarrus, Wilson, Edgecombe,
Johnston NC and Williamsburg, Barnwell, Orangeburg SC — map exactly to the 7 new hosts added to
`funeral_home_rss.HOMES` this week (confirmed in source: the module's "Round 2 (2026-09-27 gap sweep)"
comment names these same counties). The other 4 (Guilford, Iredell NC, Lexington, York SC) gained
probate through a different channel not investigated in this pass.

**Bankruptcy's +25 is the gazetteer fix landing.** The build plan's item 3 called for replacing the
21-county `CITY_TO_COUNTY` dict with a full 146-county gazetteer; that dict no longer exists in
`courtlistener_bankruptcy.py` — it's been replaced by `_bankruptcy_city_to_county.py`, described in
the current source as covering "all 146 NC+SC counties." 25 counties picked up their first bankruptcy
row this week as a direct result, with zero new scraping (the same dockets were already being fetched;
only the county-attribution step changed).

**Code/vacant is exactly, precisely frozen: 49 counties present, 49 counties present four days ago,
the same 49.** Zero gains, zero losses. This matches the build plan's own conclusion verbatim — "no
statewide or generic shortcut exists in this codebase for [Code/vacant]... each needs a genuine
per-county discovery pass" — and confirms nothing was built against it this week. This is a
structural gap, not a measurement artifact.

**Tax sale's +2 is Chester and Fairfield SC** going from zero rows to a handful of tax-sale rows each
(see above) — consistent with the build plan's item 7 (extending the SC Forfeited Land Commission
pattern to more counties), though at this small a count it isn't possible to confirm the mechanism
from the board data alone.

### Full county table (all 146, fresh)

Rows, address/mail/value completeness and families present (X/7), sorted NC then SC, by rows
descending within state. Compare directly against the identically-formatted table in
`docs/completeness_audit_2026-09-23.md` Section 3 for any individual county's before/after.

| County | State | Rows | Addr | Mail | Value | Fam | Missing families |
|---|---|--:|--:|--:|--:|--:|---|
| Mecklenburg | NC | 11,041 | 79% | 78% | 51% | 6/7 | TaxS |
| Buncombe | NC | 10,499 | 93% | 84% | 86% | 7/7 | (none) |
| Gaston | NC | 9,340 | 92% | 86% | 71% | 6/7 | TaxS |
| Rutherford | NC | 8,750 | 65% | 88% | 91% | 7/7 | (none) |
| Wake | NC | 7,090 | 79% | 78% | 55% | 6/7 | Prob |
| Forsyth | NC | 6,355 | 69% | 84% | 80% | 5/7 | Prob, BK |
| Transylvania | NC | 6,295 | 74% | 93% | 92% | 6/7 | TaxS |
| Catawba | NC | 5,131 | 23% | 23% | 20% | 6/7 | Prob |
| Guilford | NC | 5,041 | 27% | 28% | 63% | 6/7 | BK |
| New Hanover | NC | 4,766 | 77% | 77% | 63% | 5/7 | TaxS, BK |
| Brunswick | NC | 4,002 | 78% | 79% | 48% | 6/7 | CV |
| Lincoln | NC | 3,578 | 90% | 81% | 89% | 6/7 | Div |
| Henderson | NC | 3,287 | 67% | 76% | 83% | 7/7 | (none) |
| McDowell | NC | 2,700 | 79% | 90% | 88% | 6/7 | TaxS |
| Pitt | NC | 2,390 | 23% | 24% | 78% | 3/7 | TaxS, Prob, BK, CV |
| Durham | NC | 2,144 | 80% | 79% | 54% | 5/7 | TaxS, Prob |
| Orange | NC | 1,941 | 28% | 83% | 72% | 4/7 | TaxS, Prob, CV |
| Johnston | NC | 1,692 | 76% | 78% | 28% | 5/7 | TaxS, CV |
| Union | NC | 1,564 | 78% | 79% | 46% | 4/7 | TaxS, Prob, CV |
| Onslow | NC | 1,556 | 70% | 69% | 29% | 5/7 | TaxS, CV |
| Harnett | NC | 1,530 | 83% | 85% | 37% | 4/7 | TaxS, Prob, CV |
| Burke | NC | 1,430 | 88% | 79% | 72% | 7/7 | (none) |
| Cumberland | NC | 1,260 | 52% | 51% | 26% | 4/7 | TaxS, Prob, BK |
| Cleveland | NC | 1,144 | 78% | 63% | 67% | 7/7 | (none) |
| Iredell | NC | 1,130 | 65% | 65% | 55% | 6/7 | BK |
| Cabarrus | NC | 1,127 | 72% | 71% | 20% | 6/7 | BK |
| Bertie | NC | 1,106 | 99% | 99% | 99% | 3/7 | TaxS, Prob, BK, CV |
| Alamance | NC | 944 | 77% | 77% | 34% | 4/7 | TaxS, Prob, CV |
| Madison | NC | 902 | 39% | 10% | 92% | 4/7 | TaxS, Prob, CV |
| Rowan | NC | 813 | 81% | 84% | 34% | 4/7 | TaxS, Prob, CV |
| Davidson | NC | 792 | 73% | 73% | 33% | 3/7 | TaxS, Prob, BK, CV |
| Pender | NC | 729 | 75% | 78% | 60% | 5/7 | TaxS, CV |
| Moore | NC | 715 | 85% | 86% | 61% | 3/7 | TaxS, Prob, BK, CV |
| Haywood | NC | 641 | 36% | 38% | 28% | 4/7 | Prob, BK, CV |
| Rockingham | NC | 616 | 42% | 44% | 21% | 4/7 | TaxS, Prob, CV |
| Randolph | NC | 559 | 70% | 72% | 31% | 3/7 | TaxS, Prob, BK, CV |
| Chatham | NC | 553 | 82% | 83% | 43% | 5/7 | Prob, BK |
| Graham | NC | 528 | 83% | 80% | 79% | 3/7 | TaxS, Prob, BK, CV |
| Nash | NC | 523 | 76% | 79% | 27% | 3/7 | TaxS, Prob, BK, CV |
| Franklin | NC | 519 | 81% | 82% | 14% | 3/7 | TaxS, Prob, BK, CV |
| Craven | NC | 508 | 76% | 76% | 44% | 3/7 | TaxS, Prob, BK, CV |
| Gates | NC | 461 | 95% | 79% | 77% | 3/7 | TaxS, Prob, BK, CV |
| Carteret | NC | 456 | 89% | 83% | 61% | 5/7 | TaxS, Div |
| Wayne | NC | 456 | 65% | 66% | 17% | 3/7 | TaxS, Prob, BK, CV |
| Polk | NC | 449 | 82% | 67% | 68% | 6/7 | TaxS |
| Stanly | NC | 433 | 76% | 79% | 34% | 3/7 | TaxS, Prob, BK, CV |
| Lee | NC | 385 | 46% | 77% | 21% | 3/7 | TaxS, Prob, BK, CV |
| Dare | NC | 373 | 80% | 80% | 54% | 4/7 | TaxS, BK, CV |
| Hoke | NC | 353 | 80% | 83% | 0% | 3/7 | TaxS, Prob, BK, CV |
| Currituck | NC | 337 | 82% | 84% | 74% | 3/7 | TaxS, Prob, BK, CV |
| Wilson | NC | 324 | 62% | 62% | 28% | 5/7 | TaxS, CV |
| Watauga | NC | 319 | 79% | 87% | 70% | 4/7 | TaxS, Prob, CV |
| Granville | NC | 300 | 81% | 83% | 30% | 4/7 | TaxS, Prob, BK |
| Caldwell | NC | 281 | 72% | 74% | 56% | 3/7 | TaxS, Prob, BK, CV |
| Tyrrell | NC | 278 | 99% | 99% | 97% | 3/7 | TaxS, Prob, BK, CV |
| Robeson | NC | 263 | 45% | 49% | 19% | 4/7 | Prob, BK, CV |
| Mitchell | NC | 260 | 85% | 65% | 63% | 6/7 | TaxS |
| Jackson | NC | 257 | 63% | 70% | 42% | 3/7 | TaxS, Prob, BK, CV |
| Stokes | NC | 230 | 57% | 58% | 32% | 3/7 | TaxS, Prob, BK, CV |
| Cherokee | NC | 220 | 70% | 75% | 42% | 4/7 | TaxS, Prob, CV |
| Surry | NC | 211 | 68% | 80% | 51% | 3/7 | TaxS, Prob, BK, CV |
| Duplin | NC | 205 | 63% | 67% | 38% | 3/7 | TaxS, Prob, BK, CV |
| Wilkes | NC | 191 | 53% | 63% | 26% | 3/7 | TaxS, Prob, BK, CV |
| Yadkin | NC | 182 | 71% | 75% | 51% | 3/7 | TaxS, Prob, BK, CV |
| Person | NC | 179 | 78% | 80% | 47% | 3/7 | TaxS, Prob, BK, CV |
| Columbus | NC | 167 | 56% | 61% | 34% | 4/7 | TaxS, Prob, CV |
| Ashe | NC | 165 | 57% | 81% | 45% | 4/7 | TaxS, Prob, CV |
| Beaufort | NC | 158 | 68% | 68% | 50% | 4/7 | TaxS, Prob, CV |
| Edgecombe | NC | 157 | 50% | 54% | 36% | 5/7 | BK, CV |
| Lenoir | NC | 157 | 61% | 61% | 30% | 3/7 | TaxS, Prob, BK, CV |
| Sampson | NC | 155 | 54% | 59% | 24% | 4/7 | TaxS, Prob, CV |
| Jones | NC | 151 | 16% | 16% | 10% | 3/7 | TaxS, Prob, BK, CV |
| Macon | NC | 147 | 50% | 65% | 38% | 4/7 | TaxS, Prob, CV |
| Warren | NC | 140 | 54% | 54% | 29% | 4/7 | Prob, BK, CV |
| Davie | NC | 135 | 87% | 89% | 39% | 2/7 | TaxS, Prob, Div, BK, CV |
| Montgomery | NC | 132 | 77% | 83% | 49% | 4/7 | TaxS, Prob, CV |
| Pasquotank | NC | 126 | 75% | 76% | 63% | 3/7 | TaxS, Prob, BK, CV |
| Yancey | NC | 122 | 89% | 91% | 0% | 3/7 | TaxS, Prob, BK, CV |
| Avery | NC | 115 | 71% | 75% | 50% | 2/7 | TaxS, Prob, Div, BK, CV |
| Vance | NC | 115 | 52% | 56% | 37% | 4/7 | TaxS, Prob, CV |
| Halifax | NC | 109 | 48% | 50% | 28% | 3/7 | TaxS, Prob, BK, CV |
| Scotland | NC | 108 | 64% | 72% | 39% | 4/7 | Prob, BK, CV |
| Richmond | NC | 102 | 85% | 89% | 43% | 3/7 | Prob, Div, BK, CV |
| Bladen | NC | 92 | 47% | 47% | 14% | 3/7 | TaxS, Prob, BK, CV |
| Alexander | NC | 90 | 61% | 63% | 44% | 3/7 | TaxS, Prob, BK, CV |
| Camden | NC | 82 | 88% | 94% | 0% | 3/7 | TaxS, Prob, BK, CV |
| Caswell | NC | 80 | 68% | 74% | 38% | 4/7 | TaxS, Prob, BK |
| Clay | NC | 80 | 49% | 79% | 24% | 3/7 | TaxS, Prob, BK, CV |
| Swain | NC | 80 | 71% | 70% | 36% | 4/7 | TaxS, Prob, BK |
| Pamlico | NC | 79 | 86% | 89% | 58% | 3/7 | TaxS, Prob, BK, CV |
| Chowan | NC | 78 | 83% | 83% | 0% | 4/7 | Prob, BK, CV |
| Perquimans | NC | 72 | 69% | 74% | 22% | 4/7 | Prob, BK, CV |
| Anson | NC | 62 | 61% | 77% | 32% | 3/7 | TaxS, Prob, BK, CV |
| Alleghany | NC | 56 | 75% | 100% | 55% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Northampton | NC | 54 | 44% | 44% | 31% | 4/7 | TaxS, Prob, CV |
| Hyde | NC | 50 | 92% | 84% | 76% | 3/7 | TaxS, Div, BK, CV |
| Martin | NC | 41 | 59% | 59% | 44% | 3/7 | TaxS, Prob, BK, CV |
| Greene | NC | 40 | 52% | 65% | 25% | 3/7 | TaxS, Prob, BK, CV |
| Hertford | NC | 35 | 54% | 57% | 37% | 4/7 | TaxS, BK, CV |
| Washington | NC | 18 | 61% | 56% | 33% | 3/7 | TaxS, Prob, BK, CV |
| Spartanburg | SC | 17,934 | 87% | 84% | 77% | 6/7 | Div |
| Charleston | SC | 6,572 | 72% | 14% | 26% | 5/7 | Div, BK |
| Horry | SC | 4,890 | 82% | 50% | 74% | 4/7 | LisP, Div, BK |
| Pickens | SC | 4,741 | 72% | 75% | 5% | 6/7 | Div |
| Greenville | SC | 3,223 | 91% | 93% | 93% | 5/7 | Div, BK |
| Oconee | SC | 3,211 | 71% | 68% | 40% | 6/7 | Div |
| Sumter | SC | 3,095 | 99% | 76% | 94% | 5/7 | Prob, Div |
| Laurens | SC | 2,785 | 63% | 51% | 41% | 6/7 | Div |
| Cherokee | SC | 2,756 | 56% | 9% | 37% | 5/7 | Div, BK |
| Anderson | SC | 2,684 | 61% | 34% | 38% | 6/7 | Div |
| Darlington | SC | 2,520 | 79% | 69% | 69% | 2/7 | TaxD, LisP, Prob, Div, BK |
| Berkeley | SC | 2,327 | 74% | 99% | 95% | 4/7 | Div, BK, CV |
| Williamsburg | SC | 2,272 | 70% | 0% | 0% | 2/7 | TaxD, LisP, Div, BK, CV |
| Lexington | SC | 2,231 | 98% | 57% | 76% | 4/7 | LisP, Div, BK |
| Kershaw | SC | 1,699 | 91% | 0% | 78% | 2/7 | LisP, Prob, Div, BK, CV |
| Florence | SC | 1,668 | 74% | 84% | 0% | 4/7 | LisP, Div, BK |
| Colleton | SC | 1,317 | 82% | 61% | 82% | 4/7 | Div, BK, CV |
| Union | SC | 1,297 | 66% | 40% | 37% | 6/7 | Div |
| Clarendon | SC | 1,221 | 79% | 0% | 0% | 2/7 | LisP, Prob, Div, BK, CV |
| Marlboro | SC | 1,063 | 57% | 0% | 0% | 2/7 | TaxD, LisP, Div, BK, CV |
| Lancaster | SC | 896 | 99% | 72% | 0% | 2/7 | LisP, Prob, Div, BK, CV |
| Beaufort | SC | 879 | 99% | 0% | 0% | 3/7 | TaxS, Div, BK, CV |
| Richland | SC | 860 | 99% | 0% | 0% | 3/7 | LisP, Prob, Div, BK |
| Dillon | SC | 825 | 82% | 1% | 1% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Jasper | SC | 824 | 70% | 1% | 0% | 2/7 | LisP, Prob, Div, BK, CV |
| Barnwell | SC | 810 | 62% | 55% | 55% | 3/7 | TaxD, LisP, Div, BK |
| Newberry | SC | 722 | 96% | 0% | 0% | 3/7 | LisP, Prob, Div, BK |
| Chesterfield | SC | 654 | 78% | 0% | 0% | 2/7 | TaxD, LisP, Prob, Div, BK |
| Abbeville | SC | 597 | 97% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Georgetown | SC | 577 | 55% | 0% | 0% | 4/7 | Div, BK, CV |
| Allendale | SC | 509 | 53% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Calhoun | SC | 497 | 83% | 80% | 80% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Bamberg | SC | 474 | 93% | 0% | 84% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Lee | SC | 460 | 74% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Saluda | SC | 460 | 78% | 53% | 74% | 3/7 | Prob, Div, BK, CV |
| McCormick | SC | 277 | 40% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Orangeburg | SC | 133 | 83% | 0% | 0% | 4/7 | LisP, Div, BK |
| York | SC | 133 | 96% | 3% | 3% | 3/7 | TaxS, LisP, Div, BK |
| Edgefield | SC | 49 | 0% | 0% | 0% | 2/7 | TaxD, TaxS, Prob, Div, BK |
| Marion | SC | 35 | 46% | 0% | 0% | 3/7 | TaxS, LisP, Div, CV |
| Aiken | SC | 28 | 57% | 0% | 0% | 4/7 | TaxS, Prob, Div |
| Chester | SC | 17 | 100% | 100% | 100% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Dorchester | SC | 8 | 0% | 0% | 0% | 2/7 | TaxD, TaxS, Div, BK, CV |
| Fairfield | SC | 6 | 100% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Greenwood | SC | 6 | 67% | 0% | 0% | 2/7 | TaxD, TaxS, Prob, Div, BK |
| Hampton | SC | 2 | 0% | 0% | 0% | 2/7 | TaxS, LisP, Prob, Div, CV |

## 4. Foreclosure/flip lane, 18 footprint counties

Same scope as the 2026-09-23 audit: `listing_type` in foreclosure_sale, auction, reo, sheriff_sale,
hoa_sale, in the 18 footprint counties only. "Sale ≥ today" uses 2026-09-27 (today). "Value" is
market_value or a published `calc.arv_expected` (not withheld/flagged). "Identity" is parcel_id AND
street_address both present. "All 3" is identity AND mail AND value together.

| County | State | Flip rows (old→new) | foreclosure_sale | auction | reo | sheriff_sale | hoa_sale | Sale ≥ today | Mail % | Value % | Identity % | All 3 old% → new% | Δ pp |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|
| Rutherford | NC | 21→28 | 19 | 0 | 9 | 0 | 0 | 6 | 71% | 93% | 61% | 48%→**61%** (17/28) | +12.7 |
| Cleveland | NC | 46→56 | 39 | 6 | 10 | 1 | 0 | 10 | 77% | 89% | 30% | 0%→**30%** (17/56) | +30.4 |
| Henderson | NC | 22→27 | 19 | 2 | 6 | 0 | 0 | 6 | 70% | 78% | 70% | 55%→**70%** (19/27) | +15.4 |
| Polk | NC | 7→11 | 2 | 1 | 8 | 0 | 0 | 1 | 55% | 91% | 36% | 29%→**36%** (4/11) | +7.4 |
| Gaston | NC | 63→92 | 58 | 1 | 33 | 0 | 0 | 26 | 78% | 91% | 77% | 71%→**77%** (71/92) | +6.2 |
| Buncombe | NC | 110→121 | 106 | 4 | 11 | 0 | 0 | 18 | 81% | 93% | 81% | 75%→**81%** (98/121) | +6.0 |
| Transylvania | NC | 6→6 | 5 | 0 | 1 | 0 | 0 | 0 | 50% | 83% | 17% | 17%→**17%** (1/6) | -0.3 |
| McDowell | NC | 20→30 | 19 | 1 | 10 | 0 | 0 | 3 | 50% | 83% | 50% | 40%→**47%** (14/30) | +6.7 |
| Lincoln | NC | 13→25 | 13 | 0 | 12 | 0 | 0 | 4 | 84% | 96% | 84% | 69%→**84%** (21/25) | +15.0 |
| Mitchell | NC | 4→9 | 1 | 3 | 5 | 0 | 0 | 2 | 44% | 78% | 44% | 50%→**44%** (4/9) | -5.6 |
| Burke | NC | 44→62 | 39 | 3 | 20 | 0 | 0 | 5 | 76% | 84% | 76% | 61%→**74%** (46/62) | +13.2 |
| Spartanburg | SC | 422→684 | 109 | 142 | 433 | 0 | 0 | 30 | 80% | 93% | 81% | 62%→**80%** (547/684) | +18.0 |
| Anderson | SC | 236→315 | 92 | 49 | 174 | 0 | 0 | 15 | 30% | 88% | 44% | 36%→**28%** (88/315) | -8.1 |
| Pickens | SC | 127→165 | 33 | 10 | 122 | 0 | 0 | 15 | 63% | 90% | 67% | 1%→**62%** (102/165) | +60.8 |
| Oconee | SC | 118→134 | 26 | 10 | 98 | 0 | 0 | 8 | 13% | 90% | 4% | 0%→**3%** (4/134) | +3.0 |
| Cherokee | SC | 124→137 | 40 | 7 | 90 | 0 | 0 | 3 | 7% | 86% | 1% | 0%→**0%** (0/137) | +0.0 |
| Union | SC | 83→93 | 9 | 3 | 81 | 0 | 0 | 0 | 3% | 96% | 2% | 0%→**2%** (2/93) | +2.2 |
| Laurens | SC | 267→361 | 34 | 122 | 205 | 0 | 0 | 7 | 32% | 73% | 33% | 3%→**29%** (104/361) | +25.8 |
| **Total** | | **1,733→2,356** | | | | | | | 53% | 88% | 53% | 32%→**49.2%** (1,159/2,356) | **+17.3** |

### Verdict

**No county is at 100%, but the combined lane moved from "one-third workable" to "half workable" in
four days.** 553/1,733 (32%) → 1,159/2,356 (49.2%) across all 18 footprint counties. Ranked best to
worst by the new figure:

- Spartanburg SC: 80% (up from 62%)
- Buncombe NC: 81% (up from 75%)
- Lincoln NC: 84% (up from 69%)
- Pickens SC: 62% (up from 1% — the single biggest swing in the table)
- Gaston NC: 77% (up from 71%)
- Rutherford NC: 61% (up from 48%)
- Burke NC: 74% (up from 61%)
- Henderson NC: 70% (up from 55%)
- McDowell NC: 47% (up from 40%)
- Laurens SC: 29% (up from 3%)
- Mitchell NC: 44% (down from 50%)
- Polk NC: 36% (up from 29%)
- Cleveland NC: 30% (up from 0%)
- Anderson SC: 28% (**down** from 36%)
- Transylvania NC: 17% (flat)
- Union SC: 2% (up from 0%, still near-zero)
- Oconee SC: 3% (up from 0%, still near-zero)
- Cherokee SC: 0% (unchanged — still the floor)

**The value jump is real and comp-driven, not a market-value backfill.** Flip-lane value coverage
went 39%→88% board-wide, and the county-level detail shows it's almost entirely `calc.arv_expected`
carrying rows that have no county `market_value` at all — spot-checked directly against Union and
Oconee SC (previously 0% value, now 96% and 90%): of 227 flip-type rows in those two counties, 210
have a genuine, non-withheld `arv_expected` from recorded comps and zero have a `market_value`. This
is consistent with the "recompute after calc.py" valuation-calibration work noted elsewhere as
recently run board-wide; it is the single largest driver of this section's improvement and should be
understood as an ARV/comp result, not a county-appraisal-data win.

**Two real regressions, called out plainly.** Anderson SC fell 8.1pp (36%→28%) despite growing from
236 to 315 flip rows — its mail rate collapsed from an implied high to 30% and its identity rate to
44%, both worse in relative terms than four days ago; this needs its own look, not covered by this
audit's scope. Mitchell NC fell slightly (50%→44%) on a small base (4→9 rows) where a couple of
un-identified new rows are enough to move the percentage. Transylvania NC is flat at a genuinely bad
17% on an unchanged 6 rows — still the second-worst NC county in the lane after Cleveland.

**Cleveland NC's structural gap is unchanged in kind, improved in degree.** The prior audit noted its
0% was because "all 46 of its flip rows come from national trustee/auction feeds... that carry a
street address but never a parcel id at all." That's still the binding constraint — identity is 30%
against a mail rate of 77% and value rate of 89% — but 17 of its (now 56) rows do carry both fields,
up from literally zero, so something changed for a minority of its rows even though the
national-feed-without-parcel-id problem for the rest has not been fixed.

Only 159 of 2,356 footprint flip leads have a sale date today (2026-09-27) or later (6.7%, down from
9.7% — 168/1,733 — at the 2026-09-23 baseline against its own 2026-09-23 cutoff) — the actionable
window remains the tightest constraint on this lane regardless of the identity/value/mail
improvements above, and it got proportionally tighter, not looser, this week.

## 5. Honest read — what moved, what didn't, and why

**Real wins, verified against source:**
- NC lis pendens and divorce coverage: both scrapers now run against all 100 NC counties (confirmed
  in `nc_ecourts_lis_pendens.py`/`nc_ecourts_divorce.py` source), not 22. This is the single biggest
  lever pulled this week and it shows up exactly where predicted — Lis pendens present-in jumped from
  41 to 118 counties, Divorce from 19 to 93.
- Bankruptcy county-attribution: the 21-county `CITY_TO_COUNTY` dict was replaced with a 146-county
  gazetteer, with zero new API calls — 25 counties gained their first bankruptcy row from parsing
  fixes alone.
- Funeral-home RSS: grew from 3 hosts to 10, and 7 of the 11 new probate/estate counties trace
  directly to the 7 new hosts.
- 18-county flip lane workability: 32%→49.2%, driven mostly by comp-based ARV now covering rows that
  had zero valuation four days ago.
- Two previously-empty counties (Chester, Fairfield SC) now have rows at all.

**Real regressions, not spin:**
- Street address, house-number, owner-name, market-value and either-value completeness all fell
  board-wide. Owner name specifically fell 7.4 points, the sharpest drop of any completeness metric
  measured. The cause is identified and load-bearing to report honestly: the same widening that
  produced the breadth win added >25,000 court-docket rows (`lis_pendens`, `divorce_notice`,
  `bankruptcy`) that structurally cannot carry a situs address, diluting every board-wide
  completeness percentage even though no individual source got worse at its own job.
- Anderson SC's flip-lane workability fell 8.1 points on a larger row count — worth its own
  investigation, not explained by anything in this audit's scope.
- The actionable sale-date window (sale ≥ today) shrank proportionally, 9.7%→6.7% of flip rows.

**Confirmed structural, no movement expected or seen:**
- Code/vacant family breadth: exactly 49 of 146 counties both before and after, to the county. The
  build plan explicitly named this (and NC tax sale) as having no generic/statewide pattern in this
  codebase — every county needs its own per-county discovery pass, and none was run against this
  family this week. This is not a missed opportunity from this run; it's a backlog item nobody
  started.
- The 7/7-family ceiling: still exactly the same 5 counties (Buncombe, Burke, Cleveland, Henderson,
  Rutherford NC), all inside the 18-county footprint. Nothing outside that set reached full breadth,
  even the counties that gained 3-4 families this week (Johnston and Wilson NC each jumped from 1/7
  to 5/7 and are still 2 families short).
- SC divorce automation remains a legal wall (FCCMS ToS bans automated querying), not a technical
  gap — 0 of 46 SC counties show Divorce, unchanged, and none should be expected to move without a
  change in that legal posture.
