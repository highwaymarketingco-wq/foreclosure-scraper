# COVERAGE & GAPS MAP — the authoritative three-level view

One document, three altitudes (STATE → COUNTY → CITY), for the 30-county
foreclosure-lead footprint. Read-only synthesis of `road_to_100_matrix.md`,
`walls_register.md`, `SOURCE_REGISTER.md`, `gap_ledger.md`,
`road_to_100_build_queue.md`, `public_notice_wiring_audit.md`,
`sc_gis_endpoints_upstate.md` / `_coastal.md`, and `discovery/*.md`.
Generated 2026-08-13. No engine runs, no board writes. Where every read doc is
silent, the cell is **UNKNOWN**, never invented.

**Footprint (30 counties, Horry EXCLUDED):**
- NC core (11): Buncombe, Henderson, Cleveland, Gaston, Rutherford, Polk, Transylvania, McDowell, Lincoln, Mitchell, Burke
- NC coastal (8): Currituck, Dare, Hyde, Carteret, Onslow, Pender, New Hanover, Brunswick
- SC core (7): Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens
- SC coastal (4): Charleston, Georgetown, Colleton, Beaufort

**Verdict legend (information-wise, per cell):**
- **GOOD** — a working free source feeds the cell today.
- **PARTIAL** — a source reaches it but is capped (coastal near-beach gate), filter-broken, volume-thin, or notices-only.
- **GAP** — nothing feeds it, but an open/free endpoint exists to build.
- **WALL** — no compliant free path (ToS/CAPTCHA/token/robots); manual-save or paid only.
- **FOIA** — data is public but only via a records request (exemption rolls, most code enforcement).
- **UNKNOWN** — the source docs are silent.

Caveat carried from the matrix: cell verdicts inherit the 2026-08-04 completeness
audit (board = the 07-31 full run). Coastal near-beach gating still caps every
coastal county even though the 08-12 public-notice + eCourts wiring was committed.

---

## 1. PER STATE (NC vs SC)

### North Carolina

**GOOD (open / working systems):**
- **NC eCourts open Judgment Search JSON** — keyless, statewide, facet-selectable. Carries lis-pendens (S2), estates/probate (S6), and divorce/equitable-distribution (S7). This is the spine for the non-foreclosure court signals and it is FREE.
- **Substitute-trustee firm dockets** — Hutchens/Foundation, Brock & Scott, Aldridge Pite, Bell Carrington, ALAW, McMichael Taylor Gray + `wnc_rod_foreclosure_starts`, `nc_rod_substitute_trustee`, `national.nc_upset_bids` (fixed 08-02). Foreclosure + upset-bid spine (S1/S2/S3), statewide.
- **`ncnotices.com` (NC Press Association) public-notice portal** — all 100 counties, foreclosure + notice-to-creditors + tax-sale categories, no login/CAPTCHA. Coastal counties wired 08-12.
- **CourtListener/PACER bankruptcy (S8)** — federal, statewide.
- **County parcel ArcGIS (NC_GIS resolver)** — open owner+mailing feature services for most core + several coastal counties (Carteret, Onslow, Pender, New Hanover, Brunswick already wired).
- **NCPTS/Farragut BillPWA delinquent-tax rolls (S4)** — open bulk rolls for Henderson, Hyde, and other PTS-Cloud tenants.

**WALLED:**
- **NC eCourts Smart Search / Search Hearings** — AWS-WAF. (The open Judgment JSON is the workaround.)
- **NC eCourts estates CAPTCHA** on the detail lane — covered via Column + Judgment JSON instead.
- **NC SoS Federal Tax Lien search** — DOUBLE wall (2026-08-13): ToS forbids automated/scripted search (bulk = paid Data Subscription only) AND Cloudflare 403s bots. Human interactive search permitted; do not automate.
- **County ROD front-ends** (Aumentum/Cott/Kofile reCAPTCHA, login, or robots) — blocks recorded liens (S9) and individual federal-tax liens.
- **Most tax-payment portals** (Bill2Pay, Sturgis/Avalon balance API robots-Disallow) — per-parcel lookup only, not bulk.

**State-specific structural gaps:**
- **No free NC state tax-lien registry (S5).** Every NC S5 cell is a GAP; the only alternates are the walled NC SoS business-entity lien search and county-ROD federal liens (also walled). SC, by contrast, has an open registry.
- **Senior/disabled/veteran exemption (S11)** suppressed from public GIS statewide (PII) except Buncombe's `buncombe_elderly` roster and Pender's parcel `EXEMPT`/`DEFERRED_VALUE` field. Elsewhere FOIA-only.
- **Code enforcement (S10)** is municipal and mostly offline outside Asheville / Hendersonville / (buildable) Gastonia.

### South Carolina

**GOOD (open / working systems):**
- **SC statewide tax-lien registry (S5)** — `sc_state_tax_lien` (SC DOR) + DEW liens, open, covers every SC county. The one signal SC beats NC on outright.
- **Master-in-Equity rosters + FLC lists (S1/S3)** — `*_master_in_equity`, `sc_county_rosters`, `sc_coastal_rosters`, plus county FLC/delinquent-tax scrapers. Solid across core + coastal.
- **`southcarolinaprobate.net` aggregator (S6)** — Charleston (250) live; Cherokee/Oconee buildable (in dropdown). Backed by `scpublicnotices.com` Notice-to-Creditors for the rest.
- **`scpublicnotices.com` (SC Press Association) portal** — all 46 counties, foreclosure/tax-sale/delinquent/probate categories; coastal wired 08-12.
- **County-native ArcGIS parcel resolvers (SCDOT replacement)** — open owner+situs for 7 of 11 in-scope SC counties (see resolver column).
- **PACER bankruptcy (S8)** — statewide, not near-beach-gated.

**WALLED:**
- **SCDOT `SC_Parcels` MapServer** — the shared owner/situs resolver for ALL 11 SC counties is now token-walled (HTTP 200 + `{"error":{"code":499,"message":"Token Required"}}`, silent). Replaced per-county where possible; 4 counties left without a native path.
- **SC PublicIndex family-court (FCCMS) divorce (S7)** — Rule 610 ToS wall. Manual-save operator lane only. Affects all SC counties for divorce detail.
- **SC PublicIndex probate detail** — disclaimer/ToS gate for the counties absent from the probate aggregator (Georgetown, Colleton, Beaufort, Union).
- **County ROD front-ends** (qPublic/Schneider reCAPTCHA, Kofile robots, AcclaimWeb image-paywall) — blocks recorded liens (S9) and per-parcel situs for the walled counties.
- **qPayBill / parcel-mismatch tax wall** — blocks the delinquent-tax roll for Cherokee and Union.

**State-specific structural gaps:**
- **Senior/legal-residence exemption (S11)** suppressed everywhere except **Beaufort** (open `GisFile_Exemption` field — the only true open exemption source in the whole footprint). Charleston/Georgetown/Colleton expose only a `LEGAL_RESIDENCE` owner-occupancy proxy.
- **Divorce (S7)** structurally walled for the whole state (FCCMS ToS) — the mirror of NC's open eCourts divorce.
- **Code enforcement (S10)** open only in Spartanburg (richest in footprint) and city-Spartanburg; Pickens' `CitizenProblems` layer is open but was REJECTED (carries complainant PII, no property locator).

---

## 2. PER COUNTY — 30 × 12 signal grid + resolver

Cell key: **G**=Good · **P**=Partial · **X**=Gap · **W**=Wall · **F**=FOIA.
Signals: S1 FCL · S2 PRE · S3 ROST · S4 TAXD · S5 TAXL · S6 PROB · S7 DIV · S8 BKR · S9 LIEN · S10 CODE · S11 EXEM · S12 DISP.
RES = name→property resolver. `%good` = matrix %grn where available; coastal-4 + Beaufort estimated from discovery.

### NC CORE (11) — tracked, foreclosure spine solid

| County | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S9 | S10 | S11 | S12 | RES | %good |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|--:|
| Buncombe | G | G | G | G | X | G | G | G | W | P | G | G | GOOD | 79 |
| Henderson | G | G | G | G | X | G | G | G | W | G | F | G | GOOD | 75 |
| McDowell | G | G | G | G | X | G | G | G | W | F | F | G | PART | 67 |
| Cleveland | G | G | G | P | X | G | G | G | W | F | F | G | GOOD | 63 |
| Rutherford | G | G | G | P | X | G | G | G | W | F | F | G | GOOD | 63 |
| Burke | G | G | G | P | X | G | G | G | W | F | F | G | GOOD | 63 |
| Lincoln | G | G | G | P | X | G | G | G | W | F | F | G | GOOD | 63 |
| Polk | G | G | G | P | X | G | G | G | W | F | F | G | GOOD | 63 |
| Transylvania | G | G | G | P | X | G | G | G | W | F | F | G | PART | 63 |
| Gaston | G | G | G | X | X | G | G | G | W | X | F | G | GOOD | 58 |
| Mitchell | G | G | G | X | X | G | G | G | W | F | F | G | GAP | 58 |

Notes — Buncombe is the volume anchor and the only NC county with an open exemption roster (S11 GOOD via `buncombe_elderly`); its S10 is PARTIAL (Asheville city code/STR built, unincorporated FOIA). Henderson S10 GOOD (`henderson_code_violations` + `hendersonville_vacant_structures`). Buncombe S4 upgradeable to a live 6,231-row unpaid-bills ArcGIS. Cleveland/Rutherford/Burke/Lincoln/Polk/Transylvania S4 PARTIAL (tax scraper underperforms: Lincoln PDF ID-drift ~1,205 rows, Rutherford 9,328-bill rewrite pending first write). **Gaston + Mitchell S4 = true GAP** (no arrears module at all; buildable endpoints exist — Polk-style ArcGIS for Gaston, unwired roll for Mitchell). S9 = WALL everywhere (ROD front-ends walled; only ~10 lien leads footprint-wide). Gaston S10 = GAP (Gastonia CityView code search buildable). S5 = GAP for all NC (no state registry).

### NC COASTAL (8) — near-beach-gated; all "have" cells cap at PARTIAL

| County | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S9 | S10 | S11 | S12 | RES | %good |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|--:|
| Brunswick | P | P | P | P | X | P | P | X | W | F | F | P | PART | 25 |
| Onslow | P | P | P | P | X | P | P | X | W | F | F | P | GOOD | 25 |
| Carteret | P | P | P | P | X | P | P | X | W | F | P | P | GOOD | 25 |
| New Hanover | P | P | P | X | X | P | P | X | W | X | F | X | GOOD | ~35 |
| Hyde | P | P | X | G | X | P | P | X | W | F | F | X | PART | ~35 |
| Pender | P | P | P | X | X | P | P | X | W | F | P | P | GOOD | 21 |
| Dare | P | P | P | P | X | P | P | X | W | F | F | X | GAP | 21 |
| Currituck | P | P | X | W | X | P | P | X | W | F | F | W | WALL | ~10 |

Notes — S1/S2/S3/S6/S7 reach these via the statewide firms, eCourts Judgment JSON, and `ncnotices.com` but the oceanfront `main._in_scope` gate caps them at PARTIAL. S8 BKR reads GAP (statewide CourtListener rows without a near-beach address are dropped by the gate). **New Hanover** is the best-equipped coastal NC on data: `new_hanover_foreclosures` built (S1/S3), delinquent-tax Excel/CSV buildable (S4), `PropertyType=Vacant` GIS proxy buildable (S10) — but each is gated. **Hyde** S4/S5 GOOD (`nc_ptscloud` 1,367 rows, fully covered). **Currituck** is the worst-covered county in the whole footprint: owner/mailing/tax/ROD all CAPTCHA-or-geometry-only; only `ncnotices` + eCourts reach it. Carteret/Pender parcel layers carry an EXEMPT/DEFERRED field (S11 PARTIAL). Currituck/Dare/Hyde resolvers are geometry-only (no owner in open REST).

### SC CORE (7) — tracked

| County | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S9 | S10 | S11 | S12 | RES | %good |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|--:|
| Spartanburg | G | G | G | G | G | G | G | G | P | G | F | G | GOOD | 88 |
| Pickens | G | G | G | G | G | G | G | G | P | F | F | G | GOOD | 79 |
| Laurens | G | G | G | G | G | G | G | G | P | F | F | G | GOOD | 79 |
| Oconee | G | G | G | G | G | G | G | G | X | F | F | G | PART | 75 |
| Anderson | G | G | G | X | G | G | G | G | X | F | F | G | PART | 67 |
| Union | G | G | G | W | G | W | W | G | X | F | F | P | WALL | 46 |
| Cherokee | G | G | G | W | G | X | W | G | X | F | F | X | WALL | 42 |

Notes — **Spartanburg** is the strongest county in the footprint (88%): richest S10 code/condemned/vacant block, only real gaps S9 (thin) + S11 (absent). **Anderson S4 = GAP** (no source wired to its delinquent-tax roll; ACPASS login + seasonal PostingPro only). **Union + Cherokee are the two worst SC counties:** S4 walled by the qPayBill/parcel-mismatch (Cherokee PDFs thin/past-redemption), S7 divorce is manual-save only, resolver WALLED (Union WAF-403, Cherokee qPublic-only), Cherokee 100% unreachable with zero heirs/absentee. Cherokee S6 probate is a buildable GAP (point `sc_probate_net` at it). Oconee resolver is OWNER-ONLY (no situs); Anderson resolver is SITUS-ONLY (owner masked — cannot resolve by name). S11 exemption suppressed for all 7 (FOIA).

### SC COASTAL (4, Horry excluded) — near-beach-gated

| County | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S9 | S10 | S11 | S12 | RES | %good |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|--:|
| Charleston | P | P | P | P | G | G | W | G | P | W | F | P | GOOD | 46 |
| Beaufort | P | P | P | P | G | P | W | G | X | W | P | P | GOOD | ~46 |
| Georgetown | P | P | P | P | G | P | W | G | X | W | F | P | GOOD | 42 |
| Colleton | P | P | P | P | G | P | W | G | X | W | F | P | GOOD | 42 |

Notes — S5 (SC tax-lien registry) and S8 (PACER) are GOOD (statewide, NOT gated). S1/S3/S4 reach via `charleston_mie`/`charleston_delinquent_tax`, `sc_coastal_rosters`, `georgetown_civicengage`, `colleton_tax_sale`, `horry_flc` pattern — all near-beach-gated → PARTIAL. **Resolvers all BUILT** county-native (Charleston via PID-join address layer; Georgetown split-situs; Colleton clean owner+situs; Beaufort richest). **Beaufort is the standout:** its `EnerGov/MapServer/1` parcel layer is the only open **exemption** source in the footprint (S11 PARTIAL) and its Treasurer tax-sale .xlsx/.pdf is buildable (S4). S7 divorce = WALL (FCCMS ToS) for all four. S6 probate GOOD only for Charleston (`sc_probate_net` 250); Georgetown/Colleton/Beaufort aggregator-dead → PARTIAL via `scpublicnotices` Notice-to-Creditors only. S10 code = WALL for all four (no open code-case layer; EnerGov exposes base map layers only).

**Counties furthest from full coverage:** Currituck (~10%), then Dare + Pender (21%), Brunswick/Onslow/Carteret (25%). Among tracked counties, Cherokee (42%) and Union (46%) are the worst — and unlike the coastal counties (capped by a config gate) their low scores are real data walls (resolver + tax + probate/divorce all walled).

---

## 3. PER CITY (municipal-only signals)

Only three signals vary by municipality: **code enforcement, vacant/condemned registries, demolition/building permits.** Everything else in the grid is county-level. Cities with an OPEN portal are the exception; the default is FOIA/contact-only.

### Cities with an OPEN / built or buildable portal

| City (county) | Signal | Source | State |
|---|---|---|---|
| **Asheville** (Buncombe) | S10 code / STR permits | `asheville_str_permits` (HomestayPermits MapServer) + `asheville_helene` storm | BUILT — open ArcGIS |
| **Hendersonville** (Henderson) | S10 vacant structures | `hendersonville_vacant_structures` (50) | BUILT — open ArcGIS |
| Henderson County | S10 code violations | `henderson_code_violations` (156) | BUILT — open ArcGIS (county, listed for completeness) |
| **Spartanburg city** (Spartanburg) | S10 condemned | `spartanburg_city_condemned` (90) | BUILT — open |
| Spartanburg County | S10 condemned + vacant | `spartanburg_condemned` (1,658) + `spartanburg_vacant` (3,310) | BUILT — richest in footprint |
| **Gastonia** (Gaston) | S10 code enforcement | `devsvcs.cityofgastonia.com/CodeEnforcement/Locator` (Harris CityView, public search) | BUILDABLE — queue #6 |
| **New Hanover / Wilmington area** | S10 vacant proxy | NHC `PropertyType=Vacant` GIS layer | BUILDABLE — queue #7 (county GIS) |

### Cities that are FOIA / contact-only (no online searchable case list)

| City (county) | Why |
|---|---|
| **Shelby** (Cleveland) | Code enforcement / minimum housing — phone/office only |
| **Morganton** (Burke) | Development & Design Services — complaint form pickup in person |
| **Forest City** (Rutherford) | Code enforcement — contact-only |
| **Wilmington** (New Hanover) | Code enforcement + minimum-housing — no public condemned/demo list (WALL) |
| **Charleston city** (Charleston) | No open code-enforcement layer (gisportal confirmed) |
| **Gaffney** (Cherokee) | Marshal's Office / Building Safety — office only, no feed |
| Anderson / Spartanburg | SeeClickFix 311 portals exist but robots.txt names ClaudeBot/anthropic-ai/GPTBot — WONT (Spartanburg already covered via ArcGIS) |
| **Pickens** | `CitizenProblems` code + blight layers are OPEN but REJECTED — carry complainant phone/email PII, no property locator |
| Unincorporated Buncombe, McDowell, Polk, Transylvania, Mitchell, Lincoln | No open ArcGIS/permit feed — FOIA to county code office |
| Beaufort / Georgetown / Colleton (SC coastal) | EnerGov exposes base map layers only; no public code-case layer |

Municipal note: S11 exemption is also technically municipal-adjacent but is FOIA county-wide everywhere except Buncombe (roster) and Beaufort/Pender (parcel field).

---

## 4. SUMMARY COUNTS

### State level
- **NC:** foreclosure/court/probate/divorce/bankruptcy spine GOOD (eCourts JSON + firms + ncnotices + PACER). Structural holes: no state tax-lien registry (S5), exemption FOIA-only, code enforcement municipal + mostly offline.
- **SC:** tax-lien registry + MIE/FLC + probate aggregator GOOD. Structural holes: divorce entirely walled (FCCMS ToS), 4 of 11 resolvers walled, exemption FOIA-only (Beaufort excepted), code enforcement Spartanburg-only.

### County level (30 counties × 12 signals = 360 cells; from the master matrix, board = 07-31)
| Status | Count | Share |
|---|--:|--:|
| GOOD (●) | 145 | 40% |
| PARTIAL (◐) | 64 | 18% |
| GAP / WALL / FOIA (○) | 151 | 42% |

Lane-to-close (matrix): FREE-BUILT 225 · FREE-BUILDABLE 108 · FREE-ALTERNATE-NEEDED 21 · MANUAL-SAVE 6 · **HARD-WALL 0** (every signal has at least one compliant path).

**Resolver tally (name→property):** SC 7 of 11 BUILT+validated (Spartanburg, Laurens, Pickens, Colleton, Beaufort, Georgetown, Charleston); Oconee owner-only, Anderson situs-only, Cherokee + Union WALLED. NC resolvers present for core + 5 coastal (Carteret/Onslow/Pender/New Hanover/Brunswick); Currituck/Dare/Hyde geometry-only.

### City level
- **OPEN/built code-enforcement portals: 5** cities/areas (Asheville, Hendersonville, Spartanburg city, + county Henderson/Spartanburg feeds).
- **Buildable: 2** (Gastonia CityView, New Hanover vacant proxy).
- **FOIA/contact-only or walled: the rest** (Shelby, Morganton, Forest City, Wilmington, Charleston city, Gaffney, Pickens-rejected, all rural unincorporated, SC coastal EnerGov).

### Top 5 highest-value remaining gaps overall
1. **SC resolver walls — Cherokee + Union** (and Anderson owner-masked / Oconee situs-missing). No name→property path caps every downstream signal for these counties; the single biggest lever on the ~25-30% resolver ceiling.
2. **S4 delinquent tax — Anderson, Gaston, Mitchell (no lane at all)** + Cherokee/Union (qPayBill wall) + Lincoln (ID-drift ~1,205 rows) + Rutherford (9,328-bill rewrite pending first write). Highest-value fragile column.
3. **S5 tax liens across all of NC** — no free state registry; the only alternates (NC SoS business liens, county-ROD federal liens) are both walled. Whole-state structural gap.
4. **S9 recorded liens (HOA/mechanic/judgment) footprint-wide** — ~10 leads total; every ROD front-end walled. Waits on the ROD rebuild.
5. **Currituck (and coastal NC generally)** — the near-beach gate + geometry-only GIS + CAPTCHA tax/ROD leave Currituck at ~10%; widening the oceanfront gate is a config toggle that lifts a large block of coastal PARTIAL cells, but Currituck's owner/tax data has no free bulk path regardless.
</content>
</invoke>
