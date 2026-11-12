# Audit 2026-10-09, area top80_verify: the verification items of the ranked build list

Scope: every item of the top 80 of `county_signal_build_list_2026-10-09.csv` with layer `verify`
(ranks 4, 12, 14, 17, 36, 55, 68, 70, 74) and the two NC public-notice items (ranks 2 and 3,
`heir_naming_publication` and `quiet_title`). Counts, county names, source slugs and signal names
only; no names, addresses or notice text.

## 1. What was measured and how

- Cube before/after: `scripts/gap_matrix.py` over the reconciled pre-publish checkpoint (383,378
  rows) with its screen ledger, once on the 10/9 code (docs/gap_matrix/gap_list_2026-10-09.csv at
  ab4eb4b5) and once on this group's code. Repeat: `uv run python scripts/gap_matrix.py --board
  <checkpoint dir> --screens <screen_ledger.json> --date 2026-10-09 --out-dir <scratch>`.
- Verifier coverage survey of the same checkpoint: every tax_lien / tax_sale / other-lien row
  against the registered verifiers (live, wall, none). Before the four tax verifiers: live 88,954, wall 61,357 (with
  `lien_registry_wall`), none 37,546; after: live 96,942, none 29,558. The rest of the "none" are the walled-by-register county sites (matrix) and
  the sources named in section 3.
- Live proof (`scripts/top80_verify_proof.py`, 2 s between requests per host, read-only): see each
  item.

Cells of the 965 in this group's verify/check rows (10 columns): sourced-not-built 602 -> 10;
a verdict (walled or no source known) 67 -> 369; built-but-low-yield (a verifier or scraper exists;
a sweep or the next run fills it) 296 -> 586.

## 2. Items

| rank | column | outcome | what was done | live proof | cells (before -> after) |
|---|---|---|---|---|---|
| 2, 3 | heir_naming_publication, quiet_title (NC) | BUILT | `scrapers/public_notices/nc_heir_notices.py`: Column's open statewide notice API searched by text (quiet title, unknown heirs, unlocatable heirs, heirs at law, heirs of); three notice shapes parsed (quiet-title hearing, G.S. 105-375 tax foreclosure naming heirs, other unknown-heir notices); a PROBATE_NOTICE row per distinct notice with `raw.heir_naming_publication` in the SC parser's shape. Screen ledger entry for the 75 NC counties with a Column paper. The other 25 counties have no Column notice in 365 days: verdict walled (ncnotices.com bodies are CAPTCHA-walled). | one fetch: 972 notices -> 89 leads in 26 counties, 58 with a parcel, 37 tax-foreclosure heirs, 50 other, 2 quiet-title hearings; includes Jackson, one of the 20 listed cells | 20 + 20 sourced-not-built -> 105 built (a run fills them) + 25 walled, per column |
| 4, 55 | comps, comps_tight (verify) | NOT WORTH BUILDING (no free source) | NC OneMap carries a sale date but no price; the only county layers with a price are Buncombe (verifier exists, `comps_buncombe`), Anderson (no address key) and Cleveland (unvalidated two-hop join). A comp verdict governs nothing (ARV is not a distress signal). Cube reads the verifying source as "no free per-sale price record outside Buncombe". | existing verifier: 40 ledger verdicts | 85 + 44 sourced-not-built -> no source known |
| 12 | tax_aging_surfaced (verify) | BUILT + WALLED | rides the tax_lien verifiers below | see 74 | 11 sourced-not-built -> 0 (9 walled, 51 built-but-low-yield for the sweep, 6 no source) |
| 14 | lt_divorce_notice (verify, NC) | VERIFIER EXISTED; CUBE WAS READING THE WRONG LEDGER | `Spec.ledger` named `divorce` (the SC wall); the NC rows are covered by `nc_ecourts_case`. Spec now names both; `ledger_signals()` accepts `a|b`. | 3 divorce + 3 lis pendens rows in 6 counties: 6 confirmed (+5/5 on the checkpoint) | 93 sourced-not-built -> 93 built-but-low-yield (sweep) |
| 68 | lt_lis_pendens (verify, NC) | same | `foreclosure_rod|nc_ecourts_case|court_wall` | as above | 65 -> 62 built-but-low-yield, 4 sourced-not-built (rows from the walled ncnotices lane, 19 rows) |
| 70 | heir_estate (verify) | same | `probate_heir|heir_roll` | heir_roll 3 + 5 rows in 8 counties: all confirmed | 68 -> 68 built-but-low-yield (1 left: Cleveland, 78 rows, another source) |
| 17, 36 | lt_probate_notice (verify, SC + NC) | VERDICT: the verifying source is the probate court, not the notice | `verify_family="probate"`: the cube reads the county's probate-index access from the matrix. NC: eCourts Smart Search CAPTCHA (walled). SC: blocked/login/captcha counties walled, no-online-index counties "no source known"; Lexington moved to captcha per the register override; 5 open indexes (Greenville, Richland, Newberry, Calhoun, Greenwood) hold 64 rows in all: not worth building. | n/a (no fetch) | 124 sourced-not-built -> 98 walled, 21 no source known, 5 open-index (64 rows) |
| 74 | lt_tax_lien (verify, 72 cells) | BUILT 4 VERIFIERS + 1 WALL + REGISTER WALLS | see below | see below | 72 sourced-not-built + 23 no source -> 0 + 2; walled 14 -> 32; built-but-low-yield 24 -> 99 |

### Item 74, the tax lien family, in detail

| piece | rows (2026-10-09 checkpoint) | outcome | live proof |
|---|---|---|---|
| `verifiers/lien_registry_wall.py` (signal `lien_registry_wall`, WALL) | liensnc 45,093 (all "Appointment of Lien Agent", typed tax_lien); SC DEW 8,288; SC DOR 319; Rutherford 8,544 | WALLED with cards `liensnc_login`, `sc_lien_registries` (new) and `avalon_tax` | DEW search service answers "Invalid Security Key" to a plain request (read 2026-10-09) |
| `verifiers/tax_lien_perquimans.py` | 1,493 (newspaper list) | BUILT (county tax search, plain GET) | 10 rows: 9 confirmed, 1 map not on the site |
| `verifiers/tax_lien_itsnet.py` (classic ITS.NET: Iredell, Chowan) | 2,360 + 868 | BUILT | 10 rows (6 Iredell, 4 Chowan): 8 confirmed, 2 stale (paid since the list) |
| `verifiers/tax_lien_pwa.py` (PTS Public Web Access: Randolph, Mecklenburg) | 4,128 + 616 | BUILT; bill flags (DLQ, ADVERTISED, ATT REF IN REM) in the evidence | 10 rows: Mecklenburg 4 confirmed, Randolph 6 stale (paid since the spring list) |
| matrix tax access from the register | Charleston (4,163), Georgetown (396), McDowell (2,201), Lincoln (1,103), Burke, Union, Edgecombe, Lee, Avery | WALLED (cards `sc_tax_walled`, `avalon_tax`, `nc_tax_walled`, `dc_ip_block`); the matrix still said "open" | n/a |
| matrix: no per-parcel bill source | Cumberland (3,719), Stokes, Gates (603) | NO SOURCE (bill search answers HTTP 500 / zero records) | n/a |

Not built, with the reason (the cells stay open): Rowan (2,663 rows): the iasWorld property search
returns owner, account and tax year but no balance without a row-selection (script) step and shows a
maintenance banner; 1-2 days. Davidson (3,194), Hoke (2,830), Washington (1,613), Tyrrell (391): the
county has no public bill search (matrix: payment processor only). Bertie (1,533): CAPTCHA (walled).

## 3. Defects found

| class | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|
| the cube read a verification ledger the covering verifier does not write | 93 + 65 + 68 NC cells (14,000+ rows) | `Spec.ledger` named `divorce` / `foreclosure_rod` / `probate_heir`; the NC rows are covered by `nc_ecourts_case` / `heir_roll`. The same drift on lt_foreclosure_sale, lt_tax_lien, lt_tax_sale, lt_probate_notice (court_wall, lien_registry_wall, foreclosure_sale_list) | `Spec.ledger` accepts `a|b`; each feed column names every signal that covers its claim | tests/test_gap_matrix.py | `top80v-cube-names-the-verifier` (0 on the checkpoint; fails on the old specs), `top80v-cube-ledger-names-registered` |
| a hit row's VERIFYING source was taken to be its detecting source | 124 + 129 cells | probate notices are detected statewide, verified at the county probate court; comps are detected from MLS/county sales, verified only where a county layer carries a price | `Spec.verify_family`, `source_status` family `sales` | test_gap_matrix.py | (same) |
| matrix said "open" where the register says walled | 10 county tax sites + Lexington probate | county_records_matrix.json predated the 10/9 register decisions | matrix `tax.access` / `probate.access` set, with a note naming the card | test_gap_matrix.py | `top80v-tax-claim-has-verifier` |
| 45,093 rows typed `tax_lien` are lien-agent appointments | 45,093 | counties_generic.liensnc maps "Appointment of Lien Agent" to ListingType.TAX_LIEN | labelled wall (no tax claim to verify); scorer not touched | test_verification_lien_registry_wall.py | `top80v-tax-claim-has-verifier` |
| NC quiet-title / heir notices never read | 20 + 20 cells; 89 leads in one fetch | no NC parser | `nc_heir_notices` | tests/test_nc_heir_notices.py (11) | `top80v-nc-heir-notice-shape`, `top80v-quiet-title-flag-has-text` |

## 4. Open items (owner / lead)

1. Wiring (main.py is not edited here). `public_notices.nc_heir_notices` rows carry no sale date and
   `_active_only` drops them (checked: False without the entry). In `DATELESS_OK_SOURCES`, after the
   line `"public_notices.nc_notices_counties",`, add:
   `    "public_notices.nc_heir_notices",                          # Column NC quiet-title / heir-naming court notices (no sale date)`
   Nothing else: the scraper is auto-discovered, plain HTTP (VM-safe), no flag, no run_profile or
   vm_lib change.
2. Sweeps (Mac, `scripts/verification_sweep.py`, ledgers committed by the sweep): the cube counts a
   cell closed only when every hit row has a verdict. In order of rows: `--signal tax_lien
   --max-rows 20000` (now also reads Perquimans, Iredell, Chowan, Randolph, Mecklenburg);
   `--signal nc_ecourts_case --max-rows 20000` (7,249 divorce + 6,991 lis pendens rows, one request
   per county and three-day window, cached); `--signal heir_roll --max-rows 8000`;
   `--signal lien_registry_wall --max-rows 70000` (no fetch). Budget: `--budget-s 14400`.
3. After the next run the 75 NC counties with a Column paper read "screened, none found" for both
   columns through `screen_ledger.py`; until then they are built-but-low-yield.
4. Refresh docs/gap_matrix with the new code (the cube agent's outputs predate it).
5. Not verified: that Column's `county` tag covers every county it lists (it is the paper's county;
   the notice body decides the row's county); the Randolph "stale" rate (6 of 6) is plausible for a
   spring advertisement list and was checked on 3 rows against the county's amounts, not against
   payment receipts.

## 5. Outside this area

- The same Column query finds 26 NC counties of leads the existing lanes miss; ncnotices.com is the
  only other statewide aggregator and its bodies are walled.
- `counties_nc.nc_ecourts_lis_pendens` / `nc_ecourts_judgments` rows typed tax_lien (about 940 in
  Mecklenburg 317, Wake 285, New Hanover 173, Guilford 165) are not taken by `nc_ecourts_case` (its claim kinds
  exclude them): court_signals owns that.
- The albemarle_observer lists for Washington, Bertie, Gates, Tyrrell (4,000 rows) are newspaper
  snapshots of counties with no readable bill search.
