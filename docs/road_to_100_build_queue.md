# Road to 100% — Vetted Build Queue (close-out campaign 2026-08-12)

Result of a 5-cluster discovery sweep (every footprint county x 12 signals, site
inspection + SERP) cross-checked against existing code, the `arcgis_distress_layers`
REJECTED list, and the privacy rules. Per-cluster detail: `docs/discovery/*.md`.

**Headline:** the enumeration is near-exhaustive. Most "finds" were already built,
already wired, or deliberately rejected. The genuinely net-new, compliant, buildable
tail is small — which is itself the answer: there is no hidden trove, and the real
remaining gaps are FOIA/manual by nature (exemption rolls, most code enforcement,
recorded liens, SC divorce).

## Built + committed this session
- **Coastal public-notice wiring** (`e34f798`): 12 coastal counties added to
  `nc_notices_counties` + `sc_public_notices` (foreclosure/estate/tax-sale), 36 gaps closed.
- **eCourts coastal facets**: added Currituck / Hyde / New Hanover to
  `nc_ecourts_lis_pendens.TARGET_COUNTIES` (reused by the divorce scraper) — surfaces their
  foreclosure/lis-pendens/divorce signals. Tests green.

## Already done (discovery re-found; NO action)
- **NC coastal parcel endpoints** (Carteret/Onslow/Brunswick/Pender/New Hanover) — already in `enrichment_arcgis.NC_GIS`.
- **Buncombe unpaid-bills ArcGIS** — already the `buncombe_unpaid_bills` Layer.
- **Cherokee/Oconee/Georgetown/Colleton probate** — already queried by `sc_probate_net` (empty because those courts don't feed the aggregator, not unwired).
- `ncnotices`/`scpublicnotices` coastal — done above.

## Rejected for cause (do NOT build)
- **Pickens `CitizenProblems` code-enforcement + blight** — carry the COMPLAINANT's phone/email, no property locator. Privacy violation. (`arcgis_distress_layers` privacy note already excludes these.)
- **Anderson city code violations** — stub (CaseNumber '123', null owner/TMS).
- **Gaston blight** — 0 rows. **Burke `CitizenReporterContext`** — basemap only.
- Buncombe "Unpaid Bills 2026/2025" raw — whole current-year levy + vehicle-tax rows, not delinquency.

## Genuine BUILD queue (net-new, compliant, ranked)
| # | Source | Signal | Endpoint | Integration | Risk |
|---|---|---|---|---|---|
| 1 | ✅ **DONE — SC county-native resolver** (SCDOT confirmed token-walled) | resolver + S12 | — | Built `SC_GIS` for **6 of 11** counties (Spartanburg/Laurens/Pickens/Colleton/Beaufort/Georgetown), all validated live (commits `3526f55`, `62223ca`). Charleston = spawned follow-up (PID join). Cherokee/Union/Oconee/Anderson walled (walls_register). | done |
| 2 | **New Hanover delinquent tax** | S4/S5 | `nhcgov.com/2877` Excel+CSV, monthly | file-download scraper (multi_year_delinquent_tax pattern) | Low |
| 3 | **Beaufort Treasurer tax-sale list** | S3/S4 | `beaufortcountytreasurer.com` .xlsx/.pdf | file-download scraper | Low |
| 4 | **Polk TaxParcels delinquent** | S4/S12 | `services1.arcgis.com/23uf7jKvz6SRPFWJ/.../TaxParcels/FeatureServer/0` where TOTAL_TAX_OWED>0 | verify real delinquency vs whole roll, then a Layer | Low-Med |
| 5 | **NC SoS Federal Tax Lien** (statewide) | S5 | `sosnc.gov/online_services/search/by_title/_Federal_Tax_Lien` (Incapsula 403s bare client) | stealth-browser scraper, business/LLC liens | Med — new stealth build |
| 6 | **Gastonia city code-enforcement** | S10 (Gaston) | `devsvcs.cityofgastonia.com/CodeEnforcement/Locator?module=CE` | CityView form-POST scraper | Med |
| 7 | New Hanover NHC Vacant layer | S10 (proxy) | NHC Properties `PropertyType=Vacant` | Layer entry | Low |

## HIGH-PRIORITY FLAG — SCDOT token wall
`enrichment_arcgis.SCDOT_BASE` (the shared `SC_Parcels` MapServer that serves owner/situs
resolution for ALL SC counties) is reported token-walled (silent 200+error) per
[[project_resolver_bugs_and_scdot_wall]]. If confirmed dead, SC owner resolution is degraded
board-wide, and the **county-native SC endpoints in queue item 1 are the fix for every SC
county, not just coastal** — this is likely the single biggest lever on the resolver ceiling
(~25-30%). Worth a deliberate build + live SCDOT probe next.

## Walls / FOIA (recorded; stop re-chasing)
- **S11 exemption** — homestead exclusion suppressed from public GIS everywhere except Beaufort's ArcGIS exemption field. FOIA-only.
- **S9 recorded liens** (HOA/mechanic/judgment) — ROD front-ends reCAPTCHA/robots/paywall. Only state DOR+DEW liens are open (built).
- **Most S10 code-enforcement** beyond Asheville/Spartanburg/Gastonia/Pickens(rejected) — FOIA/contact-only.
- **SC divorce** (FCCMS) — ToS wall, manual-save lane only.
- Rutherford/Anderson tax balance, Mitchell roll, Currituck owner/mailing — no free bulk path.
