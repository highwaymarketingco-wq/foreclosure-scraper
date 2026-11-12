# SC Upstate Core — Net-New Source Discovery

Written 2026-08-12. Scope: 7 SC Upstate counties (Spartanburg, Anderson, Pickens,
Oconee, Cherokee, Union, Laurens) x 12 distress signals. Goal: NET-NEW, FREE,
BUILDABLE sources that are NOT already wired and NOT a known wall.

Compliance frame: FREE + PUBLIC only. No CAPTCHA solving, no people-search PII,
no riding a robots Disallow, no login/paywall. Style: no em dashes.

Method: read the live registry (`SOURCE_REGISTER.md`, `COUNTY_SYSTEMS_REGISTRY.md`,
`road_to_100_matrix.md`, `road_to_100_alternates_*`, `gap_ledger.md`) to establish
what is already wired/walled, then live-probed county ArcGIS REST directories and
official sites (1-2 GETs each). Probe results dated inline.

Signals: S1 foreclosure (SC CP-420 MIE) · S2 pre-fcl/lis-pendens · S3 MIE/sheriff
rosters+FLC · S4 tax delinquency · S5 tax liens · S6 probate/estates · S7 divorce ·
S8 bankruptcy · S9 liens (HOA/mechanic/judgment) · S10 code-enf/condemn/vacant ·
S11 senior/disabled/veteran exemption · S12 absentee/cash-buyer.

Access legend: **ArcGIS** = open REST FeatureServer query · **GET** = open URL ·
**platform** = existing scraper platform, new county · **wall** = no compliant free
path found this pass.

---

## Executive summary

The 7 counties are already densely covered (Spartanburg 88%, Pickens/Laurens 79%,
Oconee 75%, Anderson 67%, Union 46%, Cherokee 42% per `road_to_100_matrix.md`).
The net-new finds this pass are concentrated in **S10 code/vacant (Pickens)** and
**S6 probate (Cherokee)**, both fully free and buildable, plus an Anderson GIS lane
that needs a TLS-relaxed client.

### Net-new BUILDABLE sources found: 5 solid + 2 low-confidence candidates

1. **Pickens code-enforcement** — `CitizenProblems_code_enforcement` ArcGIS
   FeatureServer, **70 records live 2026-08-12**, closes the Pickens S10 GAP.
2. **Pickens blight/demolition** — `CitizenProblems_blight_...` ArcGIS layer
   (Dilapidated Building, Illegal Dumping, Abandoned Vehicle), same org.
3. **Cherokee probate** — `southcarolinaprobate.net` carries Cherokee, same
   platform as the built Charleston `sc_probate_net`. Closes Cherokee S6 GAP.
4. **Anderson parcel-sales / property viewer** — `propertyviewer.andersoncountysc.org`
   ArcGIS (Parcel_Sales last-5yr = S12 cash-buyer/absentee deed signal). Buildable
   but the host has a TLS chain error, needs a cert-relaxed client.
5. **Anderson city parcels** — `gis.cityofandersonsc.com` clean FeatureServer
   (resolver/enrichment, owner+situs).

Low-confidence: **Pickens `vacant_co_prop`** (county-OWNED surplus, adjacent to FLC,
verify overlap before wiring); **Union WTH GIS** (`unionsc.wthgis.com`, REST endpoint
not exposed in page HTML, needs a browser network trace to resolve).

### Top 5 (county + signal + URL)

1. Pickens · S10 code-enf · `services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/CitizenProblems_code_enforcement/FeatureServer/0`
2. Pickens · S10 blight · `services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/CitizenProblems_blight_2ae5fad95a5d4dcf91bb93230f9f6d9a/FeatureServer/0`
3. Cherokee · S6 probate · `southcarolinaprobate.net/search/` (county = Cherokee)
4. Anderson · S12 dispo · `propertyviewer.andersoncountysc.org/arcgis/rest/services/Parcel_Sales/MapServer`
5. Pickens · S12/surplus · `services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/vacant_co_prop/FeatureServer/0`

### County x signal with NO free path (record so not re-chased)

- **S11 exemption (all 7)** — senior/disabled/veteran homestead EXCLUSION is
  suppressed from every public parcel GIS (it names a resident's age/disability).
  Confirmed absent in Pickens/Oconee orgs this pass, consistent with
  `road_to_100_alternates_signals.md` finding. Free path = FOIA to county tax
  office only. Automated lane is a wall.
- **S9 liens HOA/mechanic/judgment (all 7)** — recorded in ROD or filed at Clerk of
  Court; every ROD front-end for these counties is walled (Schneider/qPublic
  reCAPTCHA, Kofile robots-Disallow for Oconee, AcclaimWeb image-paywall for
  Pickens). State liens (SC DOR + DEW) are already built. No open per-county
  judgment/mechanic-lien feed. Wall.
- **Cherokee S10 code** — Marshal's Office / Building Safety, no online complaint
  feed or ArcGIS mirror. Cherokee GIS is qPublic/Schneider reCAPTCHA. Wall.
- **Anderson / Spartanburg S10 via SeeClickFix** — both counties run SeeClickFix
  311 portals, but SeeClickFix robots.txt names ClaudeBot/anthropic-ai/GPTBot
  (WONT per register). Spartanburg S10 is already HAVE via ArcGIS (condemned +
  city_condemned + vacant), so no loss there; Anderson has no ArcGIS code mirror.
- **Anderson S4 delinquent-tax balance** — ACPASS login + seasonal PostingPro only
  (already documented in `road_to_100_alternates_rod_tax.md`). Not net-new.
- **S7 divorce Union/Cherokee** — SC PublicIndex disclaimer/ToS wall; manual-save
  lane only (already documented).

---

## Per-county tables

### Pickens SC — ArcGIS org `services1.arcgis.com/59960rq18IxUcAVI` (already the wired delinquent-tax org)

| Signal | Source | URL / endpoint | Access | Live? | Needs code/wiring | Confidence |
|---|---|---|---|---|---|---|
| S10 code | Citizen_Problems (code enforcement) | `.../CitizenProblems_code_enforcement/FeatureServer/0` | ArcGIS | **YES, 70 recs 08-12** | NEW parser (points; fields probtype, status, locdesc, dates; probtypes incl. Abandoned Dwelling, Unsafe Building, Tall Grass, Trash/Debris) | HIGH |
| S10 blight | Citizen_Problems (blight view) | `.../CitizenProblems_blight_2ae5fad95a5d4dcf91bb93230f9f6d9a/FeatureServer/0` | ArcGIS | YES 08-12 | NEW parser (Dilapidated Building, Illegal Dumping, Abandoned Vehicle, Illegal Storage RV) | HIGH |
| S12/surplus | vacant_co_prop (county-owned) | `.../vacant_co_prop/FeatureServer/0` | ArcGIS | YES 08-12 | NEW parser; polygon; PIN, NAME1/2, LOCADD, SALEDT, SALEP, BLDGS. County-OWNED surplus (FLC-adjacent) not private vacant | MED (verify overlap w/ FLC_2022) |
| S4 tax | dqnt_2024 / DelParces_October2025NewsAd | (org above) | ArcGIS | wired | `pickens_delinquent_parcels` (1,928) | built |
| S3 FLC | FLC_2022 | (org above) | ArcGIS | wired | built | built |
| S9 lien | AcclaimWeb ROD | — | image-paywall | n/a | WALL | — |
| S11 exempt | parcel layer | — | field suppressed | n/a | WALL (FOIA) | — |

### Cherokee SC

| Signal | Source | URL / endpoint | Access | Live? | Needs code/wiring | Confidence |
|---|---|---|---|---|---|---|
| S6 probate | southcarolinaprobate.net (Cherokee) | `southcarolinaprobate.net/search/` county=Cherokee | platform (GET) | YES 08-12 (in dropdown) | point existing `sc_probate_net.py` at Cherokee; carries decedent + PR mailing addr | HIGH |
| S4 tax | county wp-json media PDFs | `cherokeecountysc.gov/wp-json/wp/v2/media?search=tax%20sale` | GET | thin | media-index reader (only Nov-2024 ledger, past redemption) | LOW (documented thin) |
| S10 code | Marshal / Building Safety | `cherokeecountysc.gov/building-safety/` | office only | n/a | WALL (no feed) | — |
| GIS/parcels | qPublic Schneider | `qpublic.schneidercorp.com?App=CherokeeCountySC` | reCAPTCHA | n/a | WALL | — |
| S9/S11 | ROD / exemption | — | walled/suppressed | n/a | WALL | — |

### Anderson SC

| Signal | Source | URL / endpoint | Access | Live? | Needs code/wiring | Confidence |
|---|---|---|---|---|---|---|
| S12 dispo | Parcel_Sales (last 5 yrs) | `propertyviewer.andersoncountysc.org/arcgis/rest/services/Parcel_Sales/MapServer` | ArcGIS | serves data; **TLS chain error to default clients 08-12** | NEW parser w/ cert-relaxed client (verify off); cash-buyer/absentee deed signal | MED |
| resolver | City_Parcels | `gis.cityofandersonsc.com/arcgis/rest/services/Local_Government/City_Parcels/FeatureServer` | ArcGIS | YES 08-12 (clean cert) | enrichment: owner + situs (city footprint only) | MED |
| assessment | Opengov/MAT, NewPropertyViewer | `propertyviewer.andersoncountysc.org/arcgis/rest/services/` | ArcGIS | TLS chain error | enumerate w/ cert-relaxed client for owner-mailing/assessment | MED |
| S4 tax | PostingPro (seasonal) / ACPASS | `anderson.postingpro.net` | seasonal / login | n/a | WALL (documented, not net-new) | — |
| S10 code | SeeClickFix 311 | `seeclickfix.com/web_portal/.../Anderson` | robots-WONT | n/a | WALL | — |
| S3 FLC | Terry Howe / sc_flc | — | wired | built | built | built |

### Oconee SC — org `services1.arcgis.com/UOvRn2Rvzysthh3i` (already wired)

| Signal | Source | URL / endpoint | Access | Live? | Needs code/wiring | Confidence |
|---|---|---|---|---|---|---|
| S6 probate | southcarolinaprobate.net (Oconee) | `southcarolinaprobate.net/search/` county=Oconee | platform | YES 08-12 | DEPTH-ADD only (Oconee S6 already HAVE via notices); wire if depth wanted | MED |
| S4 tax | DT2025 (645) + Google Sheet | (org above) | ArcGIS/Sheet | wired | `oconee_tax_sale` / multi_year | built |
| S3 FLC | Assignment_FLC | (org above) | ArcGIS | wired | built | built |
| Delinquent_Tax_Properties | cumulative layer | `.../Delinquent_Tax_Properties/FeatureServer/0` | ArcGIS | **only 2 recs 08-12** | skip (near-empty vs DT2025) | reject |
| S10 code / S11 exempt | none / suppressed | — | wall | n/a | WALL | — |

### Laurens SC — `laurenscountygis.org`

| Signal | Source | URL / endpoint | Access | Live? | Needs code/wiring | Confidence |
|---|---|---|---|---|---|---|
| resolver | Baselayers / Pebble TaxParcel | `laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer` | ArcGIS | YES 08-12 | parcels only, no code/vacant/tax-status/exemption layers exposed | LOW (resolver only) |
| S4 tax | qPayBill | `laurenstreasurer.qpaybill.com` | wired | built | built | built |
| S10 code / S9 / S11 | none exposed | — | wall | n/a | WALL | — |

### Union SC

| Signal | Source | URL / endpoint | Access | Live? | Needs code/wiring | Confidence |
|---|---|---|---|---|---|---|
| resolver | WTH GIS viewer | `unionsc.wthgis.com/` | vendor viewer | viewer live 08-12 | REST endpoint NOT in page HTML; needs browser network trace to resolve backend service | LOW (unmapped candidate) |
| S4 tax | qPayBill | `uniontreasurer.qpaybill.com` | wired | built | built | built |
| S6 probate | not on southcarolinaprobate.net | — | separate system | n/a | WALL (own probate, not on platform) | — |
| S7 divorce | SC PublicIndex | — | ToS/disclaimer | n/a | manual-save lane (known) | — |
| S9 / S10 / S11 | none | — | wall | n/a | WALL | — |

### Spartanburg SC (anchor, 88% — remaining gaps only)

| Signal | Source | URL / endpoint | Access | Live? | Needs code/wiring | Confidence |
|---|---|---|---|---|---|---|
| S10 code | condemned + city_condemned + vacant | `maps.spartanburgcounty.org` / `services9.arcgis.com/HoRra3ATPLGmyjn6` | ArcGIS | wired (richest in footprint) | built | built |
| S11 exempt | parcel layer | — | field suppressed | n/a | WALL (FOIA) | — |
| S9 lien | ROD `search.spartanburgdeeds.com` | — | disclaimer only, but index carries no lien-$ | n/a | manual/thin | — |

---

## Notes for the builder

- The Pickens `CitizenProblems_*` layers are ArcGIS "Crowdsource Reporter" hosted
  FeatureServers on the county org. Even though the intake app resembles a 311
  tool, the DATA is exposed as an open, queryable ArcGIS REST layer with no robots
  Disallow, so it is compliant to read (unlike SeeClickFix's robots-walled site).
- Cherokee/Oconee probate ride the EXISTING `sc_probate_net.py` platform; wiring is
  adding the county code, not a new scraper. Cherokee is the net-new cell.
- Anderson `propertyviewer.andersoncountysc.org` returns a TLS "unable to verify
  first certificate" error to WebFetch/default httpx. That is a cert-chain issue,
  not a wall; a client with relaxed verification reads it. Do not classify as CANT.
- `dpaY3zboICQILFY5` (services6) and `7YUdLQ8pDBKU1XYI` (services8) surfaced in
  search but are Cherokee County GEORGIA and Union County NORTH CAROLINA
  respectively. Do NOT wire them for SC.
