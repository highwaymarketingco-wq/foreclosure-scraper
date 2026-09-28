# Completeness audit, 2026-09-28

Measured read-only on the live board, 217,773 rows (NC 135,061, SC 82,712), streamed once with
`board_stream.iter_board_rows()` (~300MB constant-memory reader, ~16s wall time for the full pass).
A second, independent pass was run to attribute rows by source for root-cause checks. No `load_board`,
no scraper or writer ran, no `board_lock`/`write_artifact` call, no git command ran. This is read-only
analysis only.

This is the direct sequel to `docs/completeness_audit_2026-09-27.md` (215,535 rows), which is the
baseline for every comparison below. Methodology is unchanged and deliberately identical: family
definitions come straight off `listing_type` (tax delinquent = `tax_lien`, tax sale = `tax_sale`, lis
pendens = `lis_pendens`, probate = `probate_notice` + `estate_lead`, divorce = `divorce_notice`,
bankruptcy = `bankruptcy`, code/vacant = `distressed`), the 18-county flip footprint is
`config.NC_COUNTIES + config.SC_COUNTIES` (Rutherford, Cleveland, Henderson, Polk, Gaston, Buncombe,
Transylvania, McDowell, Lincoln, Mitchell, Burke NC; Spartanburg, Anderson, Pickens, Oconee, Cherokee,
Union, Laurens SC), "identity" is `parcel_id` AND `street_address` both present, flip-lane "value" is
`market_value` or a published (non-withheld) `calc.arv_expected`, and "workable" (All 3) is identity AND
mail AND value together. The 146-county universe is `validation.NC_COUNTIES`/`SC_COUNTIES` (100 + 46),
matched case-insensitively.

One definition is made explicit here because the 9/27 doc never states it in one place: **owner_mailing**
is true when any of `raw.skip_trace.owner_mailing_address`, `raw.outreach.mailing_address`,
`raw.liensnc_related.owner_contact.mailing`, `raw.owner_mailing` (dict `.mailing` or a bare string), or
`raw.gis.mailing` is present — the same union `scripts/coverage_100_ledger.py` uses, the most recent
committed definition in the repo. **Phone** is true when `enrichment_sc_phone.usable_owner_phone(raw)`
(the do-not-dial / uncorroborated-xref / agent-contact gate) or `raw.outreach.phones` or
`raw.liensnc_related.owner_contact.phone` is present. Neither the 2026-09-23 nor the 2026-09-27 audit
reported a phone figure, so Section 2's phone numbers have no baseline to diff against — they are
reported fresh, for the first time in this audit series.

## Bottom line

**This was a small, surgical session, not a re-scrape.** Every board-wide completeness metric moved by
less than 1 point in either direction. The two real, verifiable events are: (1) three brand-new
code/vacant sources landed in Guilford, Durham NC and York SC (1,539 genuine rows), plus a Beaufort SC
tax-sale source (22 rows) and normal weekly drift in nine other counties, for a net +2,238 rows
board-wide; and (2) the Anderson SC parcel-resolution fix worked exactly as its commit message claimed
— identity jumped from 44% to 88% — but the county's workable-lead rate barely moved (28%→29%) because
**mail, not identity, is now Anderson's binding constraint**, and Anderson's own GIS masks the owner
field on the layer that carries situs (confirmed in `docs/walls_register.md`), so this is not a "did it
work" story with one answer — the fix did exactly what it targeted, and the metric the user will
actually judge it by (a workable lead) is gated by a different, still-open wall.

- **Board totals**: 217,773 rows (+2,238, +1.0%), NC 135,061 (+1,752), SC 82,712 (+486). Every one of the
  13 counties that changed row count this session went **up**; zero counties lost rows.
- **Board-wide field completeness is flat.** Address 72.7%→73.1% (+0.4pp), owner mailing 64.5%→65.1%
  (+0.6pp), owner name 88.4%→88.3% (-0.1pp, noise), either-value 56.1%→56.2% (+0.1pp). Phone, reported
  for the first time: 29.6% board-wide, split brutally uneven — NC 47.7%, **SC 0.005% (4 of 82,712
  rows)** — a structural finding, explained below, not a measurement artifact.
- **Family breadth is essentially frozen.** Only one county changed tier: Beaufort SC (3/7→4/7, gained
  Tax Sale via `beaufort_flc`, +22 rows). The 7/7 ceiling is still the same 5 counties. Code/vacant
  presence is still exactly 49/146 counties — frozen for the second audit running — even though this
  session added 1,539 genuine code-enforcement rows, because all three landing counties (Guilford,
  Durham, York) already counted as "CV present" via a weaker HUD REAC signal before this session.
- **Anderson SC: the fix landed, the headline metric didn't move much, and that's real, not a failure.**
  Identity 44%→88% (the fix's actual target, confirmed). Mail stayed at 30% (a separate, still-open wall:
  Anderson's own ArcGIS layer masks `TAXOWNSTR`, the owner field, per `docs/walls_register.md`). Workable
  (all 3) moved 28%→29% (+0.6pp, 88→90 of 315 rows) — a real but small gain, because the lane was already
  mail-bound, not identity-bound.
- **8 code/vacant dead ends confirmed this session** (not 20 — see Section 5 for the discrepancy with
  the brief): Wake, Forsyth, Cumberland, Union, Cabarrus, Iredell NC; Lexington, Horry SC. 3 of the 12
  counties probed landed real sources (Guilford, Durham NC; York SC); Mecklenburg was already covered
  elsewhere and wasn't re-probed.

## 0. What changed since 2026-09-27 — top-line before/after

| Metric | 2026-09-27 | 2026-09-28 | Δ |
|---|--:|--:|--:|
| Total rows | 215,535 | 217,773 | +2,238 (+1.0%) |
| NC rows | 133,309 | 135,061 | +1,752 |
| SC rows | 82,226 | 82,712 | +486 |
| Street address (all) | 72.7% | 73.1% | +0.4pp |
| House number (all) | 67.4% | 67.2% | -0.2pp |
| Neither address nor parcel (all) | 19.7% | 18.9% | -0.8pp (better) |
| Owner mailing (all) | 64.5% | 65.1% | +0.6pp |
| Owner name (all) | 88.4% | 88.3% | -0.1pp (noise) |
| Market value (all) | 51.4% | 51.6% | +0.2pp |
| Tax value (all) | 45.9% | 46.1% | +0.2pp |
| Either value (all) | 56.1% | 56.2% | +0.1pp |
| Phone (all) | not measured | 29.6% | new metric |
| Counties with 1/7 families | 10 | 10 | +0 |
| Counties with 3/7 | 47 | 46 | -1 |
| Counties with 4/7 | 37 | 38 | +1 |
| Counties with 7/7 (full breadth) | 5 | 5 | +0 |
| Code/vacant present in (of 146) | 49 | 49 | +0 (frozen again) |
| Tax sale present in (of 146) | 60 | 61 | +1 (Beaufort SC) |
| 18-county flip rows | 2,356 | 2,356 | +0 (no new flip-type rows) |
| 18-county flip lane, identity+mail+value | 49.2% (1,159) | 49.4% (1,163) | +0.2pp |
| Anderson SC flip-lane identity | 44% | 88% | **+44pp** |
| Anderson SC flip-lane workable (all 3) | 28% (88/315) | 29% (90/315) | +0.6pp |

## 1. Board totals and what drove the growth

The board grew by exactly 2,238 rows, and every county that changed moved up — a clean, fully
reconciled picture with no regressions:

| County | State | 9/27 rows | 9/28 rows | Δ | Source of the gain |
|---|---|--:|--:|--:|---|
| Durham | NC | 2,144 | 3,019 | +875 | **New**: `counties_generic.arcgis_distress.durham_open_code_violations` (875 rows, exact match — brand-new source, 0→875) |
| Guilford | NC | 5,041 | 5,664 | +623 | **New**: `counties_generic.arcgis_distress.greensboro_code_housing` (623 rows, exact match — brand-new source, 0→623) |
| Spartanburg | SC | 17,934 | 18,259 | +325 | Organic drift across many already-live sources (no single new source accounts for it — normal weekly re-scrape of `spartanburg_vacant`, `qpaybill_delinquent_roll`, `spartanburg_property_cleanup`, etc.) |
| Burke | NC | 1,430 | 1,525 | +95 | Organic drift (`burke_storm_damage`, `liensnc`, NC eCourts feeds) |
| New Hanover | NC | 4,766 | 4,841 | +75 | Organic drift (`nc_ecourts_judgments`, `liensnc`) |
| Laurens | SC | 2,785 | 2,838 | +53 | Organic drift (`qpaybill_delinquent_roll`, `sc_public_index`) |
| Greenville | SC | 3,223 | 3,268 | +45 | Organic drift (`greenville_unpaid_tax_parcels`) |
| York | SC | 133 | 174 | +41 | **New**: `rockhill_code_housing` (16) + `rockhill_code_demolition` (13) + `rockhill_code_exterior_major` (12) = 41, exact match |
| Transylvania | NC | 6,295 | 6,331 | +36 | Organic drift (`transylvania_vacant`, eCourts feeds) |
| Lincoln | NC | 3,578 | 3,613 | +35 | Organic drift (`lincoln_vacant`, `nc_county_pdf_delinquent_tax`) |
| Beaufort | SC | 879 | 901 | +22 | **New**: `counties_sc.beaufort_flc` (22 rows, exact match) |
| Henderson | NC | 3,287 | 3,299 | +12 | Organic drift |
| Buncombe | NC | 10,499 | 10,500 | +1 | Organic drift |
| **Total** | | | | **+2,238** | |

**Correction to the session brief's framing**: the brief described this as "Beaufort FLC +22, code/vacant
expansion +2,216." Measured directly, the genuinely-new code/vacant sources (Durham + Guilford + York)
total **1,539 rows**, not 2,216. The remaining 677 rows are ordinary weekly refresh growth in nine
other counties' already-existing sources (mostly tax and court-docket feeds, not code/vacant) — real
board growth, but not attributable to a "code/vacant expansion" mechanism. The two `parcel_from_geo`
runs and the Berkeley SC funeral-home RSS feed, also named in the brief, are both confirmed to have
added **zero net rows** in this pass (see below) — they did exactly what their commit messages claimed
(enrich existing rows / check for new obituaries and find none this cycle), not add new leads. This is
the honest reconciliation, not a discrepancy to paper over.

**`parcel_from_geo` confirmed as enrichment-only.** Two runs landed this session (`3ae9e45`, `20b3010`,
resolving 2,101 and 2,002 parcel_ids respectively), and the board's total row count is unchanged by
either — consistent with the tool's job (point-in-polygon resolution against already-published rows).
Its effect shows up as improved `parcel_id`/identity fill on existing rows: Cleveland NC (+4pp identity),
Henderson NC (+4pp), Polk NC (+9pp), Burke NC (+9pp) and Anderson SC (+44pp) flip-lane identity all moved
this session with zero row-count change in any of them — direct, board-wide confirmation the runs
touched NC counties too, not only Anderson.

**Berkeley SC funeral-home RSS added 0 net rows this cycle.** Berkeley SC's row count is unchanged at
2,327, and its family-breadth footprint (Prob already present) was unchanged from the 2026-09-27
baseline — Berkeley already carried a probate signal before this session. The RSS feed landed as working
code (confirmed: `newspapers.berkeley_independent`, 9 rows, is live on the board) but this specific run
found no new obituaries to add.

## 2. Owner mailing, owner name, value, and phone — board-wide

| Group | Rows | Owner mailing | Owner name | Market value | Tax value | Either value | Phone |
|---|--:|--:|--:|--:|--:|--:|--:|
| **All (now)** | 217,773 | 141,828 (65.1%) | 192,339 (88.3%) | 112,340 (51.6%) | 100,292 (46.1%) | 122,497 (56.2%) | 64,456 (29.6%) |
| **NC (now)** | 135,061 | 99,553 (73.7%) | 117,925 (87.3%) | 79,869 (59.1%) | 70,922 (52.5%) | 82,098 (60.8%) | 64,452 (47.7%) |
| **SC (now)** | 82,712 | 42,275 (51.1%) | 74,414 (90.0%) | 32,471 (39.3%) | 29,370 (35.5%) | 40,399 (48.8%) | 4 (0.005%) |
| All (2026-09-27 baseline) | 215,535 | 139,034 (64.5%) | 190,433 (88.4%) | 110,715 (51.4%) | 98,986 (45.9%) | 120,913 (56.1%) | not measured |
| NC (2026-09-27 baseline) | 133,309 | 97,149 (72.9%) | 116,432 (87.3%) | 78,727 (59.1%) | 69,861 (52.4%) | 80,995 (60.8%) | not measured |
| SC (2026-09-27 baseline) | 82,226 | 41,885 (50.9%) | 74,001 (90.0%) | 31,988 (38.9%) | 29,125 (35.4%) | 39,918 (48.5%) | not measured |

Every field is flat to +0.8pp. This is exactly what a session with no statewide-widening mechanism (no
new eCourts county list, no new gazetteer) should look like — contrast this with the 9/27 audit, where
the same widening that drove 92 counties' breadth gains also dragged board-wide address/name/value down
5-7 points in a single audit cycle. Nothing like that happened this session; the small positive drift
across every metric is consistent with two narrow, well-targeted parcel-resolution runs plus a handful
of new per-county sources.

**Phone is the one genuinely new, and genuinely alarming, number in this section.** SC phone
completeness is **0.005%** — 4 rows out of 82,712 — not because SC owners don't have phone numbers on
file, but because of a data-quality gate: 1,662 SC rows carry a raw `owner_phone.phone` value, and 1,659
of them are blocked by `enrichment_sc_phone.owner_phone_block_reason` before they can be called usable —
1,198 `sc_xref_identity_unverified`, 287 `sc_xref_identity_contradicted`, 174 `agent_contact`. SC's phone
numbers come from a voter-registration name cross-reference that the engine correctly refuses to treat
as a verified owner contact unless the identity match is corroborated. NC's phone completeness (47.7%)
comes from a different, apparently more reliable mechanism and is not subject to the same gate at scale.
**This is a structural, compliance-driven gap, not an oversight** — the correct fix is a better SC
identity-corroboration source, not loosening the gate.

## 3. Distress-family breadth, all 146 NC+SC counties

**5 of 146 counties have all 7 families**, unchanged from 2026-09-27: Buncombe, Burke, Cleveland,
Henderson, Rutherford NC. All five still sit inside the 18-county flip footprint.

**0 of 146 counties have zero rows**, unchanged.

**Exactly one county changed tier this session**: Beaufort SC, 3/7→4/7 (gained Tax Sale via
`beaufort_flc`, +22 rows, landing this session). No other county's family count moved — the 92-county
surge from the 9/23→9/27 audit was a one-time effect of the eCourts statewide widening, and nothing of
that scale ran this session.

Family-count histogram, all 146 counties, with the 2026-09-27 baseline alongside:

| Families present | Counties (now) | Counties (2026-09-27) | Δ |
|--:|--:|--:|--:|
| 0/7 | 0 | 0 | +0 |
| 1/7 | 10 | 10 | +0 |
| 2/7 | 14 | 14 | +0 |
| 3/7 | 46 | 47 | -1 |
| 4/7 | 38 | 37 | +1 |
| 5/7 | 14 | 14 | +0 |
| 6/7 | 19 | 19 | +0 |
| 7/7 | 5 | 5 | +0 |

The single county that moved (Beaufort SC, 3/7→4/7) accounts for the entire histogram shift.

**Families ranked by how commonly they're missing (of 146), with the 2026-09-27 baseline:**

| Family | Missing now | Present now | Present, 2026-09-27 | Δ present |
|---|--:|--:|--:|--:|
| Divorce | 53 | 93 | 93 | +0 |
| Bankruptcy | 98 | 48 | 48 | +0 |
| Probate/estate | 97 | 49 | 49 | +0 |
| Lis pendens | 28 | 118 | 118 | +0 |
| Code/vacant | 97 | 49 | 49 | **+0 (frozen, second audit running)** |
| Tax sale | 85 | 61 | 60 | **+1 (Beaufort SC)** |
| Tax delinquent | 17 | 129 | 129 | +0 (already near-solved) |

**Code/vacant's freeze deserves its own explanation, because real work landed against it this session and
the county-count still didn't move.** Three brand-new, genuine code-enforcement sources went live —
`greensboro_code_housing` (Guilford NC, 623 rows), `durham_open_code_violations` (Durham NC, 875 rows),
and the three Rock Hill layers (York SC, 41 rows) — landing 1,539 real rows. But the commit that added
them says outright that "their prior 'coverage' in the family-breadth audit was HUD REAC [inspection
data]," and confirmed against this pass: all three counties already showed CV present in the 2026-09-27
table (Guilford missing only BK, Durham missing TaxS+Prob, York missing TaxS+LisP+Div+BK — none of them
had CV in their missing list even before this session). So the family-presence flag was already true for
these three counties via a weaker generic signal; this session's work materially improved the quality
and volume of that signal without moving the county-count metric. The metric is doing its job — it
counts genuine per-county work only when it crosses a threshold nothing had crossed before — but it is
worth being explicit that "frozen at 49" undersells what actually happened in these 3 counties.

### Full county table (all 146, fresh)

Rows, address/mail/value completeness and families present (X/7), sorted NC then SC, by rows descending
within state. Compare directly against the identically-formatted table in
`docs/completeness_audit_2026-09-27.md` Section 3 for any individual county's before/after.

| County | State | Rows | Addr | Mail | Value | Fam | Missing families |
|---|---|--:|--:|--:|--:|--:|---|
| Mecklenburg | NC | 11,041 | 79% | 79% | 51% | 6/7 | TaxS |
| Buncombe | NC | 10,500 | 93% | 90% | 86% | 7/7 | (none) |
| Gaston | NC | 9,340 | 92% | 87% | 72% | 6/7 | TaxS |
| Rutherford | NC | 8,750 | 66% | 88% | 91% | 7/7 | (none) |
| Wake | NC | 7,090 | 79% | 78% | 55% | 6/7 | Prob |
| Forsyth | NC | 6,355 | 69% | 84% | 80% | 5/7 | Prob, BK |
| Transylvania | NC | 6,331 | 74% | 93% | 93% | 6/7 | TaxS |
| Guilford | NC | 5,664 | 35% | 25% | 56% | 6/7 | BK |
| Catawba | NC | 5,131 | 23% | 23% | 20% | 6/7 | Prob |
| New Hanover | NC | 4,841 | 78% | 76% | 62% | 5/7 | TaxS, BK |
| Brunswick | NC | 4,002 | 79% | 79% | 49% | 6/7 | CV |
| Lincoln | NC | 3,613 | 93% | 93% | 89% | 6/7 | Div |
| Henderson | NC | 3,299 | 67% | 80% | 84% | 7/7 | (none) |
| Durham | NC | 3,019 | 85% | 81% | 64% | 5/7 | TaxS, Prob |
| McDowell | NC | 2,700 | 79% | 92% | 89% | 6/7 | TaxS |
| Pitt | NC | 2,390 | 23% | 24% | 78% | 3/7 | TaxS, Prob, BK, CV |
| Orange | NC | 1,941 | 28% | 83% | 72% | 4/7 | TaxS, Prob, CV |
| Johnston | NC | 1,692 | 76% | 78% | 28% | 5/7 | TaxS, CV |
| Union | NC | 1,564 | 78% | 79% | 46% | 4/7 | TaxS, Prob, CV |
| Onslow | NC | 1,556 | 70% | 69% | 29% | 5/7 | TaxS, CV |
| Harnett | NC | 1,530 | 83% | 85% | 37% | 4/7 | TaxS, Prob, CV |
| Burke | NC | 1,525 | 89% | 77% | 68% | 7/7 | (none) |
| Cumberland | NC | 1,260 | 52% | 51% | 26% | 4/7 | TaxS, Prob, BK |
| Cleveland | NC | 1,144 | 79% | 68% | 67% | 7/7 | (none) |
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
| Craven | NC | 508 | 76% | 76% | 45% | 3/7 | TaxS, Prob, BK, CV |
| Gates | NC | 461 | 95% | 79% | 77% | 3/7 | TaxS, Prob, BK, CV |
| Carteret | NC | 456 | 90% | 88% | 62% | 5/7 | TaxS, Div |
| Wayne | NC | 456 | 65% | 66% | 17% | 3/7 | TaxS, Prob, BK, CV |
| Polk | NC | 449 | 83% | 74% | 72% | 6/7 | TaxS |
| Stanly | NC | 433 | 76% | 79% | 34% | 3/7 | TaxS, Prob, BK, CV |
| Lee | NC | 385 | 46% | 77% | 21% | 3/7 | TaxS, Prob, BK, CV |
| Dare | NC | 373 | 80% | 81% | 54% | 4/7 | TaxS, BK, CV |
| Hoke | NC | 353 | 80% | 83% | 0% | 3/7 | TaxS, Prob, BK, CV |
| Currituck | NC | 337 | 82% | 84% | 74% | 3/7 | TaxS, Prob, BK, CV |
| Wilson | NC | 324 | 62% | 62% | 28% | 5/7 | TaxS, CV |
| Watauga | NC | 319 | 79% | 87% | 70% | 4/7 | TaxS, Prob, CV |
| Granville | NC | 300 | 81% | 83% | 30% | 4/7 | TaxS, Prob, BK |
| Caldwell | NC | 281 | 72% | 74% | 56% | 3/7 | TaxS, Prob, BK, CV |
| Tyrrell | NC | 278 | 99% | 99% | 97% | 3/7 | TaxS, Prob, BK, CV |
| Robeson | NC | 263 | 45% | 49% | 19% | 4/7 | Prob, BK, CV |
| Mitchell | NC | 260 | 87% | 71% | 68% | 6/7 | TaxS |
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
| Beaufort | NC | 158 | 73% | 74% | 56% | 4/7 | TaxS, Prob, CV |
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
| Caswell | NC | 80 | 68% | 75% | 38% | 4/7 | TaxS, Prob, BK |
| Clay | NC | 80 | 49% | 79% | 24% | 3/7 | TaxS, Prob, BK, CV |
| Swain | NC | 80 | 71% | 70% | 36% | 4/7 | TaxS, Prob, BK |
| Pamlico | NC | 79 | 86% | 89% | 58% | 3/7 | TaxS, Prob, BK, CV |
| Chowan | NC | 78 | 83% | 83% | 0% | 4/7 | Prob, BK, CV |
| Perquimans | NC | 72 | 69% | 74% | 22% | 4/7 | Prob, BK, CV |
| Anson | NC | 62 | 61% | 77% | 32% | 3/7 | TaxS, Prob, BK, CV |
| Alleghany | NC | 56 | 75% | 100% | 55% | 1/7 | TaxS, LisP, Prob, Div, BK, CV |
| Northampton | NC | 54 | 44% | 44% | 31% | 4/7 | TaxS, Prob, CV |
| Hyde | NC | 50 | 92% | 86% | 76% | 3/7 | TaxS, Div, BK, CV |
| Martin | NC | 41 | 59% | 59% | 44% | 3/7 | TaxS, Prob, BK, CV |
| Greene | NC | 40 | 52% | 65% | 25% | 3/7 | TaxS, Prob, BK, CV |
| Hertford | NC | 35 | 54% | 57% | 37% | 4/7 | TaxS, BK, CV |
| Washington | NC | 18 | 61% | 56% | 33% | 3/7 | TaxS, Prob, BK, CV |
| Spartanburg | SC | 18,259 | 87% | 84% | 77% | 6/7 | Div |
| Charleston | SC | 6,572 | 72% | 13% | 26% | 5/7 | Div, BK |
| Horry | SC | 4,890 | 82% | 50% | 74% | 4/7 | LisP, Div, BK |
| Pickens | SC | 4,741 | 72% | 76% | 5% | 6/7 | Div |
| Greenville | SC | 3,268 | 90% | 93% | 93% | 5/7 | Div, BK |
| Oconee | SC | 3,211 | 71% | 68% | 40% | 6/7 | Div |
| Sumter | SC | 3,095 | 99% | 76% | 94% | 5/7 | Prob, Div |
| Laurens | SC | 2,838 | 62% | 52% | 41% | 6/7 | Div |
| Cherokee | SC | 2,756 | 56% | 9% | 37% | 5/7 | Div, BK |
| Anderson | SC | 2,684 | 68% | 34% | 47% | 6/7 | Div |
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
| Beaufort | SC | 901 | 99% | 0% | 0% | 4/7 | Div, BK, CV |
| Lancaster | SC | 896 | 99% | 72% | 0% | 2/7 | LisP, Prob, Div, BK, CV |
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
| York | SC | 174 | 97% | 19% | 19% | 3/7 | TaxS, LisP, Div, BK |
| Orangeburg | SC | 133 | 83% | 0% | 0% | 4/7 | LisP, Div, BK |
| Edgefield | SC | 49 | 0% | 0% | 0% | 2/7 | TaxD, TaxS, Prob, Div, BK |
| Marion | SC | 35 | 46% | 0% | 0% | 3/7 | TaxS, LisP, Div, CV |
| Aiken | SC | 28 | 57% | 0% | 0% | 4/7 | TaxS, Prob, Div |
| Chester | SC | 17 | 100% | 100% | 100% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Dorchester | SC | 8 | 0% | 0% | 0% | 2/7 | TaxD, TaxS, Div, BK, CV |
| Fairfield | SC | 6 | 100% | 0% | 0% | 1/7 | TaxD, LisP, Prob, Div, BK, CV |
| Greenwood | SC | 6 | 67% | 0% | 0% | 2/7 | TaxD, TaxS, Prob, Div, BK |
| Hampton | SC | 2 | 0% | 0% | 0% | 2/7 | TaxS, LisP, Prob, Div, CV |

**Note on unattributed rows**: 7,107 board rows (5,125 NC + 1,982 SC) carry a valid state but a blank
`county` field, so they fall outside this 146-row table entirely — the same gap existed in the 9/27
baseline (215,535 − 208,428 county-attributed = 7,107, identical to the pixel). This is a pre-existing
county-attribution gap, unchanged by this session's work, not a new issue.

## 4. Foreclosure/flip lane, 18 footprint counties

Same scope as the 2026-09-27 audit: `listing_type` in foreclosure_sale, auction, reo, sheriff_sale,
hoa_sale, in the 18 footprint counties only. "Sale ≥ today" uses 2026-09-28 (today). **Zero flip-type
rows changed count in any of the 18 counties this session** — every county's row total below is
identical to the 9/27 "new" figure, confirmed county-by-county. Only the identity/mail/value/workable
percentages moved, purely from enrichment.

| County | State | Rows | fc_sale | auction | reo | sheriff | hoa | Sale≥today | Mail% | Value% | Identity% | All3 9/27→9/28 | pp |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|
| Anderson | SC | 315 | 92 | 49 | 174 | 0 | 0 | 15 | 30% | 91% | 88% | 28%→**29%** (90/315) | +0.6 |
| Buncombe | NC | 121 | 106 | 4 | 11 | 0 | 0 | 18 | 81% | 93% | 81% | 81%→**81%** (98/121) | +0.0 |
| Burke | NC | 62 | 39 | 3 | 20 | 0 | 0 | 5 | 77% | 84% | 85% | 74%→**74%** (46/62) | +0.2 |
| Cherokee | SC | 137 | 40 | 7 | 90 | 0 | 0 | 3 | 7% | 86% | 1% | 0%→**0%** (0/137) | +0.0 |
| Cleveland | NC | 56 | 39 | 6 | 10 | 1 | 0 | 10 | 77% | 89% | 34% | 30%→**32%** (18/56) | +2.1 |
| Gaston | NC | 92 | 58 | 1 | 33 | 0 | 0 | 26 | 78% | 91% | 77% | 77%→**77%** (71/92) | +0.2 |
| Henderson | NC | 27 | 19 | 2 | 6 | 0 | 0 | 6 | 70% | 78% | 74% | 70%→**70%** (19/27) | +0.4 |
| Laurens | SC | 361 | 34 | 122 | 205 | 0 | 0 | 7 | 34% | 73% | 33% | 29%→**29%** (104/361) | -0.2 |
| Lincoln | NC | 25 | 13 | 0 | 12 | 0 | 0 | 4 | 84% | 96% | 84% | 84%→**84%** (21/25) | +0.0 |
| McDowell | NC | 30 | 19 | 1 | 10 | 0 | 0 | 3 | 53% | 83% | 53% | 47%→**47%** (14/30) | -0.3 |
| Mitchell | NC | 9 | 1 | 3 | 5 | 0 | 0 | 2 | 44% | 78% | 44% | 44%→**44%** (4/9) | +0.4 |
| Oconee | SC | 134 | 26 | 10 | 98 | 0 | 0 | 8 | 13% | 90% | 4% | 3%→**3%** (4/134) | -0.0 |
| Pickens | SC | 165 | 33 | 10 | 122 | 0 | 0 | 15 | 63% | 90% | 67% | 62%→**62%** (102/165) | -0.2 |
| Polk | NC | 11 | 2 | 1 | 8 | 0 | 0 | 1 | 64% | 100% | 45% | 36%→**45%** (5/11) | +9.5 |
| Rutherford | NC | 28 | 19 | 0 | 9 | 0 | 0 | 6 | 71% | 93% | 61% | 61%→**61%** (17/28) | -0.3 |
| Spartanburg | SC | 684 | 109 | 142 | 433 | 0 | 0 | 30 | 80% | 93% | 81% | 80%→**80%** (547/684) | +0.0 |
| Transylvania | NC | 6 | 5 | 0 | 1 | 0 | 0 | 0 | 50% | 83% | 17% | 17%→**17%** (1/6) | -0.3 |
| Union | SC | 93 | 9 | 3 | 81 | 0 | 0 | 0 | 3% | 96% | 2% | 2%→**2%** (2/93) | +0.2 |
| **Total** | | **2,356** | | | | | | 159 | 53% | 88% | 59% | 49.2%→**49.4%** (1,163/2,356) | +0.2 |

### Anderson SC: confirmed and quantified

The regression the 9/27 audit flagged (36%→28%, "needs its own look") was targeted this session with a
native-GIS fallback (`enrichment_parcel_from_geo.py`'s `NATIVE_SC_POINT_CAPABLE` allowlist, gated to
live-verified counties) after confirming SCDOT's `SC_Parcels` MapServer is dead again ("Token Required,"
the same wall documented in `docs/walls_register.md` since 2026-08-12). Measured directly:

- **Identity: 44% → 88% (+44pp)** — the fix's stated target, and it worked. The commit message claimed
  "92 of 150 sampled unresolvable Anderson rows (61%) now resolve"; board-wide the identity rate more
  than doubled, consistent with that claim at scale (276 of 315 flip-type rows now carry both a parcel_id
  and a street_address, versus roughly 139 before).
- **Value: 88% → 91% (+3pp)** — a small additional gain, likely a second-order effect of more rows now
  having a resolvable parcel_id to key a comp/ARV lookup off of.
- **Mail: 30% → 30% (unchanged)** — the fix did not touch mail, because it wasn't built to. This is
  Anderson's real remaining wall: `docs/walls_register.md` documents that Anderson's own ArcGIS layer
  (`NewPropertyViewer/MapServer/5`) has situs and value but the owner field (`TAXOWNSTR`) is
  "masked/always-null — cannot resolve by name." The parcel/situs fix and the owner-mailing wall are two
  different layers on the same host with two different access outcomes.
- **Workable (identity AND mail AND value): 28% → 29% (+0.6pp, 88→90 of 315 rows)**. This is the honest
  bottom line: the fix did exactly what its commit said, and it barely moved the metric a user actually
  acts on, because Anderson's workable rate was already gated by mail (30%), not identity (44% before the
  fix). A rate-limiting fix on a non-bottleneck layer produces a small gain, not a large one — that is
  what a correct measurement of this fix should show, and it is what was measured.

**No other footprint county regressed.** Cleveland NC gained the most (+2.1pp, 30%→32%, one more
resolvable row), and Polk NC's identity and value both moved (45%→45% all3, but note Polk's base is only
11 rows — a single row is 9pp on that denominator, so treat Polk's swing as noise, not signal).
Transylvania NC and McDowell NC and Rutherford NC each ticked down by less than half a point, all on
small denominators (6, 30, and 28 rows respectively) — noise, not regression.

## 5. Dead ends vs. live gaps — what's fixable and what isn't

### Confirmed dead ends (not fixable by more scraping)

**Code/vacant — 8 counties confirmed dead this session**, not 20. `arcgis_distress_layers.py`'s own
2026-09-28 comment block documents the actual sweep: 12 counties were checked (Mecklenburg, Wake,
Guilford, Forsyth, Durham, Cumberland, Union, Cabarrus, Iredell NC; York, Lexington, Horry SC).
Mecklenburg was already covered elsewhere (`city_websites/charlotte_open_data.py`) and wasn't re-probed.
3 of the remaining 11 turned up real, live, case-level sources (Guilford, Durham NC; York SC — landed
this session, see Section 1). The other **8 are the confirmed dead ends**: **Wake, Forsyth, Cumberland,
Union, Cabarrus, Iredell NC; Lexington, Horry SC** — "nothing live and free after a real per-county
search... stale one-time snapshots, boundary-only layers with no case data, thin non-property nuisance
complaints, or an outright login/token wall" (verbatim from the source comment). The session brief this
audit was commissioned against named 20 counties as confirmed dead ends this session, including Orange,
Pitt, Rowan, Davidson, Randolph, Alamance NC and Berkeley, Kershaw, Williamsburg, Colleton, Clarendon,
Marlboro SC — **that second group of 12 does not appear anywhere in `arcgis_distress_layers.py`, in
`docs/walls_register.md`, or in any doc modified this session.** They are real gaps (all 12 are missing
CV in Section 3's table), but nothing in the codebase documents a per-county search having been run
against them this session or any other — they should be treated as **unprobed**, not confirmed dead,
until someone actually runs the check. This correction matters: reporting them as "confirmed dead" would
close off a lane that was never actually tried.

Of the 8 genuinely-confirmed dead counties, 7 (all but Union NC) already show CV "present" in Section 3's
table via a weaker, pre-existing signal (mostly HUD REAC inspection data) — so "dead end" here means "no
better free source exists," not "zero code/vacant signal on the board."

**SC phone contactability is structurally near-zero (0.005%, 4 of 82,712 rows)**, not from a missing
scraper but from `enrichment_sc_phone.py`'s identity-corroboration gate correctly refusing to promote
1,659 voter-registration-xref phone matches to "usable owner contact" absent a corroborated identity
match. This is a compliance-correct decision, not a bug — fixing it needs a better SC identity source
(a second corroborating dataset), not a change to the gate.

**Anderson SC's owner-mailing wall**: `NewPropertyViewer/MapServer/5`'s `TAXOWNSTR` field is
masked/always-null on the county's own live GIS (confirmed live, `docs/walls_register.md`, 2026-08-12,
re-confirmed structurally unchanged by this session's identity fix, which used a different query against
the same layer for situs/parcel only). No free alternative owner-name source for Anderson SC is
documented anywhere in the repo.

**Previously-confirmed walls, unchanged and not re-probed this session** (carried forward from
`docs/walls_register.md` and `docs/coverage_gap_build_plan_2026-09-23.md`, still binding): SC divorce
automation (FCCMS Rule 610 ToS — 0 of 46 SC counties show Divorce, structurally, not from lack of
trying), the SCDOT `SC_Parcels` statewide resolver (token-walled, "confirmed dead again" per this
session's own Anderson-fix commit message), Cherokee/Union/Oconee SC's absent or masked native
parcel-owner GIS paths.

### Live gaps that could still be closed

- **Probate/estate (97 of 146 counties missing)**: the funeral-home RSS mechanism is proven extensible —
  it grew from 3 to 10 hosts in the 9/23→9/27 cycle and directly produced 7 of that cycle's 11 probate
  gains. Berkeley SC's host was added this session and simply had nothing new to report this run; adding
  more hosts in the still-missing counties remains a live, mechanical lever, not a research problem.
- **Tax sale (85 of 146 counties missing)**: the SC Forfeited Land Commission pattern (`_flc` sources)
  has now landed real rows in Chester, Fairfield (9/27 cycle) and Beaufort (this session) — a repeatable
  pattern with more SC counties still untried.
- **The 12-county gap named in the session brief but never actually probed** (Orange, Pitt, Rowan,
  Davidson, Randolph, Alamance NC; Berkeley, Kershaw, Williamsburg, Colleton, Clarendon, Marlboro SC) is
  the single most concrete "still fixable, or still needs finding out" item this audit surfaced — the
  next code/vacant sweep should start here rather than assuming it's already a dead end.
- **Cleveland NC's flip-lane identity (34%, still the second-lowest in the footprint after
  Transylvania)**: unchanged structural cause from prior audits (national trustee/auction feeds carry a
  street address but no parcel_id), but note it moved from 30%→34% this session from the general
  `parcel_from_geo` run — the same mechanism that fixed Anderson SC's identity is already chipping away
  at Cleveland's, just more slowly. Worth a dedicated pass rather than assuming it's fully structural.
- **York SC's mail/value (19%/19%, still 3/7 families)**: the three new code-enforcement layers added
  this session carry situs only, no owner field — the same resolver gap Richland's `columbia_code_vacant_boarded`
  already has a documented workaround for (parcel resolver fills owner from situs). Wiring that same
  path for York's three new layers is a small, concrete follow-up, not a new discovery task.
