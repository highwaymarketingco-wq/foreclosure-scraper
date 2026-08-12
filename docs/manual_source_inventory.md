# Manual Source Inventory — the definitive, honest count

**Question this answers:** "I have so many manual sources to save by hand. Which
of them can I stop, and what is the irreducible list I actually have to touch?"

**Method:** every walled/manual portal x county x signal in the 30-county
footprint, classified against the free automated feeds that already run nightly.
Read-only synthesis of `road_to_100_matrix.md`, the three
`road_to_100_alternates_*` docs, `honest_operator_manual.md`,
`manual_playbook_and_limits.md`, `gap_ledger.md`, `case_type_code_map.md`, and a
read of the offline-ingest lane (`scripts/ingest_saved.sh`,
`parse_nc_ecourts_export.py`, `parse_publicindex_export.py`,
`ingest_publicindex_files.py`). No engine runs, no board writes. Written
2026-08-12. No em dashes by house style.

**Footprint (30 counties, Horry excluded per scope):**
- NC core (11): Buncombe, Henderson, Cleveland, Gaston, Rutherford, Polk,
  Transylvania, McDowell, Lincoln, Mitchell, Burke
- NC coastal (8): Currituck, Dare, Hyde, Carteret, Onslow, Pender, New Hanover,
  Brunswick
- SC core (7): Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens
- SC coastal (4): Charleston, Georgetown, Colleton, Beaufort

**Classification key**
- **AUTOMATED-ALREADY** — a free automated feed already carries this signal. The
  portal save is pure duplication. **Stop hand-saving it.**
- **PARTIAL** — the automated feed carries most of it (name/case/county); one
  detail (a dollar figure, a hearing date) still needs a manual touch, and only
  for a few top leads, never a bulk save.
- **GENUINELY-MANUAL** — no free automated path. Operator saves the page; an
  offline parser ingests it.
- **STOP (negative value)** — not automated, but you should stop anyway because
  the save resolves to the wrong party or duplicates a redundant registry.

---

## The true manual workload, before any cutting

The manual universe is two court portals x their lanes x the counties they touch,
plus a short tail of county ROD / tax-behind-login retrievals.

| Portal | Lanes | Counties | Tasks |
|---|--:|--:|--:|
| NC eCourts Smart Search + Search Hearings (AWS-WAF) | 4 | 19 NC | 76 |
| SC PublicIndex + FCCMS (Rule 610 ToS) | 9 | 11 SC | 99 |
| County walled ROD / tax-behind-login (per-parcel, on demand) | n/a | ~4 | ~6 |
| **Total conceivable manual portal x county x signal tasks** | | | **~181** |

That is the number that makes the routine feel endless. Almost all of it is
already covered by feeds that run without you.

---

## PORTAL 1 — NC eCourts (Smart Search + Search Hearings), AWS-WAF

The lane classification is uniform across all 19 NC counties (the WAF and the
free alternates behave the same statewide), so it is stated once per lane. County
scope notes follow.

| Lane (signal) | Class | Free automated alternate (already running) | What, if anything, stays manual |
|---|---|---|---|
| **SP power-of-sale foreclosure** | AUTOMATED-ALREADY | `ncnotices.com` foreclosure notices (`public_notices.nc_notices_counties`) + ROD substitution-of-trustee (`wnc_rod_foreclosure_starts`, `nc_rod_substitute_trustee`) + 9 substitute-trustee law-firm dockets (`law_firms.*`, Brock & Scott / Hutchens / Kania / Aldridge Pite). Law firms carry the sale date and address earlier than the docket. | Nothing. Save SP only for a county where the law-firm feeds show zero. |
| **EST estates / notice to creditors** | AUTOMATED-ALREADY (monitored) | Column legal-notice API (`column_legal_notices`) + `ncnotices.com` "notice to creditors" + Gannett obituaries / funeral-home RSS. Carries decedent + executor/PR name statewide. | Only if the Column count craters (it 200s with 0 rows on filter drift). Then one save/county. This is the one lane the older `honest_operator_manual.md` still lists as "keep"; the fuller alternates analysis supersedes that for the name-level signal. |
| **Raw CVD divorce filing** | AUTOMATED-ALREADY | The open **NC Judgment Search JSON** already serves granted divorces (`FAM - Divorce`) via `nc_ecourts_divorce`; the one-line `FAM - Divorce` cause-filter add makes it statewide, routing around the WAF entirely. | Nothing worth doing. Raw (ungranted) filings stay walled but are low value; granted divorces are the actionable event and are free. |
| **Search Hearings (foreclosure/estate/partition hearing dates)** | PARTIAL | Foreclosure sale/hearing dates ride the law-firm sale calendars + the notice-of-sale (`ncnotices`). | Estate/partition hearing scheduling has no free feed, but it is low-value calendar data. Recommend **drop**, do not save via `headed_hearings_collector.py`. |

**County scope:** all 19 NC counties inherit these verdicts. Volume is
concentrated (Buncombe, Gaston, Cleveland, Henderson); the 8 coastal NC counties
(Currituck, Dare, Hyde, Carteret, Onslow, Pender, New Hanover, Brunswick) have
tiny per-county volume and the same free lanes (Judgment JSON lis-pendens +
RECAP bankruptcy + Column/obits + law firms), so hand-saving them returns almost
nothing.

**Net NC:** 57 of 76 tasks (SP + EST + CVD across 19 counties) are
AUTOMATED-ALREADY. 19 (hearings) are PARTIAL and recommended dropped. **Zero NC
eCourts lanes are genuinely-manual-and-required.**

---

## PORTAL 2 — SC PublicIndex + Family Court FCCMS, Rule 610 ToS

Uniform across all 11 SC counties. The one frozen automated lane
(`sc_public_index_lis_pendens`) stays as is; do not widen it.

| Lane (signal) | Class | Free automated alternate / reason | What stays manual |
|---|---|---|---|
| **Foreclosure (Sub-Type 420)** | AUTOMATED-ALREADY | `scpublicnotices.com` "Foreclosures" (`sc_public_notices`) + MIE rosters (`sc_county_rosters`, `sc_coastal_rosters`, `charleston_mie`) + law-firm dockets. SC foreclosure is judicial, so the summons/sale notice is published. | Optional monthly "insurance" save for Spartanburg / Anderson / Laurens only, against the 250-row grid cap on the automated sweep. Not new data. |
| **Lis Pendens** | AUTOMATED-ALREADY | `sc_public_index_lis_pendens` (frozen lane, best-resolving court source at ~61% name-to-parcel). | Nothing. |
| **MIE sale roster** | AUTOMATED-ALREADY | `sc_county_rosters` / `sc_coastal_rosters` / `charleston_mie` roster PDFs. | Nothing. |
| **State Tax Lien (Sub-Type 432)** | AUTOMATED-ALREADY | Redundant with the statewide SC DOR registry (`sc_state_tax_lien`). | Nothing. |
| **Probate / estates** | AUTOMATED-ALREADY | `sc_probate_notices` (SCPC 62-3-801 Notice to Creditors, carries PR **mailing address**) + `scpublicnotices.com` + `sc_probate_net` + heir/estate GIS parcels. Covers all 46 counties. | Nothing via PublicIndex. Georgetown / Colleton are a free **build** gap on `southcarolinaprobate.net` (wire it, do not hand-save). |
| **Eviction / Possession (Sub-Type 450)** | STOP (negative value) | Not automated, but the ingest keys on the **defendant**, who in an eviction is the **tenant**, not the owner. Every save adds a name that never resolves to a parcel the target owns. | Resume only after a landlord-side signal ships. Until then, saving it is worse than useless. |
| **Judgments (dollar amounts)** | PARTIAL | Scaled substitute = FOIA the Clerk / MIE for the judgment-amount roster (`docs/foia_court_records.md`). | The list save writes a **fake** `$2026.0` (parser reads the case-number year; `ingest_sc_publicindex_export.py:216` bug). The per-case detail page that carries the real $ **has no parser** (dead drop). So for your top ~10 leads, read the number by eye and type it into the CRM. Never bulk-save. |
| **Partition (Sub-Type 440)** | GENUINELY-MANUAL | No free notice or roster alternate; partition is not a reliably published legal notice. | Low volume. Save the list per county only if partition becomes a priority lane. |
| **Family Court divorce (FCCMS, types FD/ID/CD/ED/SA)** | GENUINELY-MANUAL | **The one court wall with no free alternate anywhere.** SC divorce is not a published notice and FCCMS is ToS-locked. Not on PublicIndex at all. | Save-and-ingest only, and ROI is poor. Effectively **skip** unless SC divorce becomes a named priority. |

**County scope:** all 11 SC counties inherit these verdicts. Coastal SC
(Charleston, Georgetown, Colleton, Beaufort) additionally lean on FLC lists +
`sc_state_tax_lien` + RECAP, all automated.

**Net SC:** 55 of 99 tasks (foreclosure / LP / MIE / tax-lien / probate across
11 counties) are AUTOMATED-ALREADY; 11 (eviction) are STOP-negative-value; 11
(judgments) are PARTIAL; 22 (partition + divorce) are GENUINELY-MANUAL but
low-ROI.

---

## PORTAL 3 — County walled ROD / tax-behind-login (per-parcel, on demand)

These are **enrichment** retrievals for a specific top lead, not a per-county
weekly grid. They do not scale and are not part of the routine.

| Item | Counties | Class | Note |
|---|---|---|---|
| Delinquent **tax balance** per parcel | Anderson SC (ACPASS login), Pickens SC (no bulk) | GENUINELY-MANUAL | Read the number, type it into the CRM. **Do not save the HTML** — nothing reads `anderson_tax_*.html` / `pickens_card_*.html`. Every other SC county's balance is automated via qPayBill. |
| Deed-of-trust **loan amount** (image OCR) | walled-ROD counties (Kofile/Cott/Acclaim/Aumentum) | GENUINELY-MANUAL | Spartanburg is free + OCR-wired; elsewhere per-doc fee. Top leads only, for the equity engine. |
| Full NC 105-369 delinquent **roll** | Gaston, Cleveland, Polk, Transylvania NC | AUTOMATED-ALREADY (subset) | Accept the `ncnotices.com` newspaper-ad subset; the full SPA roll is a documented wall. No manual save needed. |

---

## SECTION A — STOP DOING THESE (the win)

Everything here is already covered by a feed that runs without you, or is
actively counter-productive. Quitting all of it removes **~123 of ~181** manual
tasks.

**NC eCourts — stop all routine saves:**
- **SP foreclosure** (all 19 counties) — covered by `ncnotices` + ROD S/T + 9 law-firm dockets (which arrive earlier and carry the address).
- **Estates** (all 19) — covered by Column + `ncnotices` notice-to-creditors + obituaries. (Keep one eye on the Column count; save only if it craters.)
- **Divorce** (all 19) — covered by the NC Judgment JSON `FAM - Divorce` lane. Pure duplication.
- **Search Hearings** (all 19) — drop; foreclosure dates come from the law-firm calendars, estate/partition scheduling is low-value.

**SC PublicIndex — stop these saves:**
- **Foreclosure 420** (all 11) — `scpublicnotices` + MIE rosters + law firms.
- **Lis Pendens** (all 11) — automated `sc_public_index_lis_pendens`.
- **MIE roster** (all 11) — automated roster PDFs.
- **State Tax Lien 432** (all 11) — redundant with SC DOR registry.
- **Probate** (all 11) — `sc_probate_notices` + `scpublicnotices` + `sc_probate_net` (and it uniquely carries the PR mailing address).
- **Eviction / Possession 450** (all 11) — resolves to the tenant, not the owner. Actively pollutes the board.

**Enrichment — stop hand-saving HTML for:**
- Anderson / Pickens tax pages and SC SoS / LLR pages — no parser reads them. Read the value by eye for the specific lead if you need it.

---

## SECTION B — The irreducible GENUINELY-MANUAL checklist

Grouped so one save session covers many counties. Honest headline: the required
weekly routine is **nearly empty**. What remains is small, low-frequency, and
mostly on-demand.

### Weekly (only if these lanes are a named priority — otherwise skip)
- [ ] **SC Family Court divorce (FCCMS)** — the single true wall. One disclaimer-accept per county, save Family cases (types FD/ID/CD/ED/SA, never 50B), drop into the drop folder. ROI is poor; most operators should **skip** this entirely.
- [ ] **SC Partition (440)** — one save per SC county, list only. Low volume; do only if forced-co-owner sales matter to you.

Both above ingest through the existing lane: drop the `.html` into
`~/Desktop/Court Pages (drop here)/` (or repo root / `~/Downloads`) and run the
**"Ingest Saved Court Pages"** app → `scripts/ingest_saved.sh` →
`ingest_publicindex_files.py` (SC) or `parse_nc_ecourts_export.py` (NC). The lane
is board-lock safe and dedupes by case number.

### On demand only (top ~10 leads you are actually calling, never bulk)
- [ ] **Judgment $** — SC: open the specific case detail, read the amount, type into CRM (no parser for detail pages). NC: use FOIA, the $ is not online. Do NOT save the SC list expecting the dollar figure (it writes the fake `$2026`).
- [ ] **Anderson / Pickens tax balance** — per-parcel lookup, read + type into CRM.
- [ ] **Deed-of-trust loan amount** — walled-ROD counties, for the equity engine, top leads only.

### Monthly (the scaled substitute for the per-lead reads above)
- [ ] **FOIA batch** — NC Clerks (foreclosure SP + civil money judgments **with amount**), SC Clerks cc MIE (Common Pleas + MIE roster + judgment $), SC Chief Magistrates (ejectment = the only free case-level eviction route). Templates in `docs/foia_court_records.md`. 15 minutes, then it arrives without you. This retires the per-lead judgment-$ and eviction chases.

---

## SECTION C — Cut the burden further

**1. The biggest cut is deletion, not tooling.** ~70% of the manual routine
(~123 tasks) is duplicate work against feeds that already run. Turning it off
costs zero and is the single largest time saver. Do this first.

**2. Two one-line code changes erase two whole lanes permanently:**
- Add `"FAM - Divorce"` to the NC Judgment JSON cause filter → NC divorce goes
  statewide and off the WAF forever (removes the divorce lane's last excuse to
  be manual).
- Fix `ingest_sc_publicindex_export.py:216` to match "judgment amount" not
  "Judgment #" → stops the fake `$2026` from poisoning the one financial field
  the manual lane feeds.

**3. One small build removes a manual coastal lane:** wire
`southcarolinaprobate.net` Georgetown + Colleton (same code as the live
Charleston `sc_probate_net`) → coastal SC probate becomes automated instead of a
PublicIndex hand-save.

**4. A generated weekly "save-list" helps only the tiny remainder.** The
ingest side is already one click (`ingest_saved.sh` + parsers). A generated
save-list would only serve SC Family divorce + partition (if you even want them)
and the on-demand judgment-$ top-leads. Because the irreducible set is so small,
the payoff is minor. The higher-value automation is the **FOIA batch** (retires
judgment-$ and eviction at scale) and the persistent event ledger, not a
save-list generator.

**5. Delete the dead drop-file instructions** (`detail_<case>.html`,
`anderson_tax_<parcel>.html`, `pickens_card_<parcel>.html`, `sc_sos_<entity>.html`,
`sc_llr_roster.html`) from `gather_steps.md` so you stop producing files nothing
reads.

---

## SUMMARY COUNTS

| Class | Tasks | Share |
|---|--:|--:|
| AUTOMATED-ALREADY (stop, duplicate) | 112 | 62% |
| STOP — negative value (SC eviction) | 11 | 6% |
| PARTIAL (NC hearings 19, SC judgments 11) | 30 | 17% |
| GENUINELY-MANUAL (SC partition 11, SC divorce 11) | 22 | 12% |
| County ROD/tax on-demand enrichment | ~6 | 3% |
| **Total** | **~181** | |

- **True manual count:** ~181 conceivable portal x county x signal tasks (175
  court-portal + ~6 ROD/tax).
- **Eliminated outright:** **123** (112 AUTOMATED-ALREADY + 11 eviction STOP) =
  **68%** of the routine, at zero cost.
- **Irreducible genuinely-manual:** **22** court lanes (SC partition + SC
  divorce), both low-ROI and skippable for most operators, + ~6 on-demand ROD/tax
  reads. Realistic must-do weekly saves: **near zero**.
- **Single biggest lever:** stop the duplicate NC eCourts and SC PublicIndex
  foreclosure / lis-pendens / estate / tax-lien / probate saves — they duplicate
  `ncnotices`, `scpublicnotices`, Column, the MIE rosters, `sc_probate_net`, and
  the NC Judgment JSON that already run nightly. That one decision removes ~112
  of the ~181 tasks. The monthly **FOIA batch** then absorbs the judgment-$ and
  eviction remainder, leaving no meaningful weekly hand-saving at all.

_Generated 2026-08-12. Read-only synthesis; verdicts inherit the 2026-08-04
completeness-audit caveats. Where `honest_operator_manual.md` still lists NC
estates as "keep manual," the fuller `road_to_100_alternates_courts.md` analysis
supersedes it for the name-level signal (Column + ncnotices + obits)._
