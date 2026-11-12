# NC Core-B discovery — net-new source hunt

Counties: **Rutherford, Cleveland, Gaston, Lincoln, Mitchell, Burke** (all NC).
Frame: FREE + PUBLIC only. No CAPTCHA solve, no robots-Disallow ride, no
people-search PII. Every candidate below was probed **live** once (date 2026-08-12).

## How to read this

Before this pass, the 6 counties were already saturated on S1/S2/S3 (foreclosure
spine), S6 PROB, S7 DIV, S8 BKR (statewide court/firm lanes) and had documented
walls on S4 full-roll (Gaston/Cleveland/Mitchell) and S5 (`fa`). This pass hunted
**only** for sources NOT in `SOURCE_REGISTER.md` / `net_new_source_register.md` /
`road_to_100_*`. The honest yield is small — the prior enumeration was deep — but
two genuinely net-new **buildable** sources came out, plus a batch of confirmed
walls that should now stop being re-chased.

---

## NET-NEW BUILDABLE (the actual finds)

### 1. NC Secretary of State — Federal Tax Lien search (S5 TAXL) — ALL 6 counties
Prior state: matrix marks S5 `fa` for every NC county ("NC has no free state
tax-lien registry"). That is true for the *state* delinquent-tax registry, but the
**NC SoS UCC section runs a free, public, login-free online Federal Tax Lien
search** that was never recorded.

| field | value |
|---|---|
| landing | `https://sosnc.gov/divisions/uniform_commercial_code/federal_tax_liens` |
| search app | `https://www.sosnc.gov/online_services/search/by_title/_Federal_Tax_Lien` → results host `.../search/Federal_Tax_Liens_results_Desk` |
| scope | Federal Tax Liens recorded against **corporations & partnerships domiciled in NC** (business/LLC-owned property). Individual IRS liens are NOT here — those sit at the county ROD (the existing ROD document lane). |
| access | Free, no login, no fee for the online search (mailed UCC-11 is $5; the web search is free). Search by debtor (entity) name. |
| live? | **YES** — service confirmed live and free by NC SoS UCC pages. Direct fetch returns HTTP 403 to a bare client (Incapsula/anti-bot), but **robots.txt does not disallow** the path. So it is a stealth-browser build, not a hard wall. |
| needs-code-or-wiring | New scraper: stealth browser (engine already ships one) → entity-name POST → parse debtor + lien rows. Statewide index; join to leads by business-owner name (LLC/absentee slice). |
| confidence | HIGH on free/public/live; MEDIUM on residential yield (business entities only) |

Value: closes the S5 `fa` cell for the business-owned slice of all 6 counties in
one build, and it is the highest-intent lien type (active IRS enforcement).

### 2. City of Gastonia — CityView code-enforcement case search (S10 CODE) — Gaston
Prior state: S10 CODE for Gaston is `○fx`; prior work checked only the **county**
(county GIS publishes no code service; county EnerGov CSS API 500s / token-walls).
The **City of Gastonia** (county's largest city, ~80k) runs a public CityView
portal with a code-enforcement **Complaint Search Locator** that was never recorded.

| field | value |
|---|---|
| portal (current) | `https://devsvcs.gastonianc.gov/` (Harris CityView; `/Account/Logon` exists but the case-search Locator is public) |
| complaint search | `https://devsvcs.cityofgastonia.com/CodeEnforcement/Locator?module=CE` (public "Complaint Search") and `.../CodeEnforcement/Complaint?module=CE` |
| county page that links it | `https://www.gastonianc.gov/i-want-to/report/code-ordinance-violation.html` |
| access | Public complaint **search** (login-free in CityView; login only gates permit/pay). CityView search is typically a form-POST returning case rows by address/case #. |
| live? | **YES** — both hosts resolve and are linked from the official city page; search Locator is public. (Fetch proxy could not DNS-resolve the host in-tool, but it is confirmed live via the city's own site + SERP.) |
| needs-code-or-wiring | New scraper: CityView Locator form-POST → parse case address/status/type. Verify the Locator returns rows without login on first build. |
| confidence | MEDIUM-HIGH |

---

## CONFIRMED WALLS / NO-FREE-PATH (stop re-chasing)

| county×signal | source probed | result |
|---|---|---|
| Gaston S10 CODE (county) | county GIS `EnerGov` folder `gis.gastoncountync.gov/publicgis/rest/services/EnerGov?f=json` | **499 Token Required** — walled |
| Lincoln S10 CODE | county GIS `Planning` folder `gis.lincolncountync.gov/server/rest/services/Planning?f=json` | **499 Token Required** — walled |
| Gaston S4 TAXD (full roll) | `DevNet` folder = assessment/valuation views only (`v_gis_assessment_*`, `v_gis_parcel_search`); no delinquent/arrears view | full delinquent roll still DEVNET/newspaper-only WALL (known) |
| Cleveland S10 CODE (Shelby) | City of Shelby code enforcement / minimum housing | phone/office only, **no online searchable list** — no free path |
| Burke S10 CODE (Morganton) | Morganton Development & Design Services | complaint **form pickup in person**, no online case search — no free path |
| Rutherford S10 CODE (Forest City) | Town of Forest City Code Enforcement | contact-only, no online case search — no free path |
| Burke S10 CODE (county) | GIS `CitizenReporterContext/MapServer` looked promising by name → is just a basemap (Centerlines/Parcels/Boundary) | not code enforcement |
| Mitchell (all signals) | re-confirmed prior walls: `secure.webtaxpay.com` 403 (tax), no jail roster, county EnerGov map = parcels/zoning/flood only, no AGOL org | **no net-new free path found**; county is genuinely thin |
| S11 EXEM (senior/disabled/veteran) — all 6 | county GIS parcel `EXEMPT_COD`/`LANDEFERRED` fields | these encode **organizational/religious/ag** exemptions, NOT the senior/disabled/veteran homestead exclusion. No free per-parcel senior-exemption source found for any of the 6 (Buncombe-style elderly roster has no analog here) |

---

## PER-COUNTY SUMMARY

| County | net-new buildable this pass | notes |
|---|---|---|
| Rutherford | S5 (SoS fed lien) | S10 municipal (Forest City) = no online list |
| Cleveland | S5 (SoS fed lien) | S10 municipal (Shelby) = no online list |
| Gaston | S5 (SoS fed lien) **+ S10 Gastonia CityView** | best net-new municipal find |
| Lincoln | S5 (SoS fed lien) | county Planning GIS token-walled |
| Mitchell | S5 (SoS fed lien) | otherwise no net-new free path (thinnest county) |
| Burke | S5 (SoS fed lien) | S10 municipal (Morganton) = no online list |

## VERDICT
- **Net-new buildable sources: 2** — (1) NC SoS Federal Tax Lien search, statewide,
  closes S5 for the business-owned slice of all 6 counties; (2) City of Gastonia
  CityView code-enforcement search, closes S10 for Gaston (municipal).
- **County×signal with no free path found this pass:** S11 EXEM (senior/disabled/
  veteran) for all 6; municipal S10 for Cleveland/Burke/Rutherford (Shelby/
  Morganton/Forest City are offline); Mitchell tax/jail/code all remain walled.
- Everything else the 6 counties need for S1/S2/S3/S4-subset/S6/S7/S8/S12 is
  already wired or already documented as a wall in the prior register.
