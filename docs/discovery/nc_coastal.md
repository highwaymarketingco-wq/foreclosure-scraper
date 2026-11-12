# NC Coastal Discovery — Currituck, Dare, Hyde, Carteret, Onslow, Pender, New Hanover, Brunswick

Net-new, FREE, buildable lead-source hunt across the 12 distress signals for the
8 NC coastal counties newly brought fully into scope. Every row below was probed
LIVE (one probe each) on 2026-08-12. Sources already wired or already known-walled
are recorded in the "Already wired / walled" section so they are not re-proposed.

Signals: 1 foreclosure (power-of-sale SP) · 2 pre-fc/lis-pendens/NOD · 3 sheriff/trustee
sale + upset bids · 4 tax delinquency · 5 tax liens · 6 probate/estates · 7 divorce ·
8 bankruptcy · 9 liens · 10 code-enf/condemnation/vacant/demo · 11 senior/disabled/veteran
exemption · 12 absentee/cash-buyer.

`needs` = code-or-wiring effort. Confidence = likelihood it yields as described.

---

## Already wired (do NOT rebuild)

- `nc_coastal_tax_foreclosure` — Brunswick /912/Legal-Notices, Onslow foreclosure PDF, Carteret /1149 tax-foreclosure table (signals 1/3).
- `new_hanover_foreclosures` — nhcgov.com/345/Foreclosures in-rem tax sale list (signals 1/3).
- `brunswick_legal_notices` — Brunswick legal-notices feed.
- `nc_ecourts_lis_pendens` / `nc_ecourts_divorce` / `nc_ecourts_estates` — keyless Tyler Judgment Search JSON, facet-selectable. TARGET_COUNTIES already includes **Brunswick, Pender, Onslow, Carteret, Dare** (signals 2/6/7/9). **NOT** Currituck, Hyde, New Hanover — see wiring note below.
- `nc_ptscloud_delinquent_tax` — Farragut BillPWA roll; **Hyde already fully covered (1,367 rows)** (signals 4/5).
- `national.courtlistener_bankruptcy` — federal, statewide, covers all 8 (signal 8).
- `nc_govdeals_real_property` — statewide NC surplus/tax-foreclosed real property (signals 1/3).
- `law_firms.zacchaeus` (zls-nc.com/listings) — statewide tax-foreclosure docket incl. Dare (signals 1/3/4). **Already wired — not net-new.**
- Newspapers `carolina_coast` (Onslow), `coastland_times` (Dare); `national.sheriff_sales` (brunswicksheriff.com).

## Known walls (do NOT re-propose)
- ROD online indexes: Currituck (CAPTCHA), Carteret (login), Onslow (CAPTCHA+subscription+login), Dare permitium — gated.
- Tax portals (per-parcel lookups): Currituck (CAPTCHA/login), Dare/Brunswick/Onslow (Bill2Pay subscription), Pender (CAPTCHA) — these are lookup UIs, not bulk lists.
- Dare Clerk of Court foreclosures page (darenc.gov/.../special-proceedings/foreclosures) — **403/WAF** to plain GET (confirmed again 2026-08-12). Dare fc precursors already flow via eCourts.
- Wilmington / New Hanover code enforcement + minimum-housing: no public condemned/demo list (WALL).

---

## NET-NEW buildable sources

### STATEWIDE — covers all 8 counties

| signal | source | URL / endpoint | access | live? | needs | conf |
|---|---|---|---|---|---|---|
| 1,2,3,6 | **NC Press Assn public notices (`ncnotices.com`)** | https://www.ncnotices.com/ (search by county + keyword `foreclosure`/`substitute trustee`/`executor`/`administrator`/`estate`) | free HTML search, no login/CAPTCHA; 12 mo window | **yes** | new scraper (HTML result parse; per-county + keyword loop) | High |

`ncnotices.com` is the single biggest gap-closer: it carries foreclosure + estate
legal notices for **all 100 counties**, including **Currituck, Hyde, New Hanover**
which are NOT in the eCourts target list. Results are human-HTML (needs parsing) but
free and unauthenticated.

### Currituck
| signal | source | URL / endpoint | access | live? | needs | conf |
|---|---|---|---|---|---|---|
| 1,2,3,6 | ncnotices.com (county=Currituck) | see statewide row | free | yes | shared statewide scraper | High |
| 12 | Currituck GIS parcels | maps.currituckcountync.gov/arcgis/rest/services/Currituck/iasWorldBase2026/MapServer/0 | open REST, queryable | yes | — | **Low** — geometry only (PARCEL_ID/PIN); **no owner/mailing/tax exposed publicly** (iasWorld backing not surfaced). Owner = no free REST path. |

Currituck has effectively no free bulk owner/tax/exemption path (GIS geometry-only,
tax + ROD both CAPTCHA-walled). Distress coverage = ncnotices + eCourts-if-wired only.

### Dare
| signal | source | URL / endpoint | access | live? | needs | conf |
|---|---|---|---|---|---|---|
| 1,2,3,6 | ncnotices.com (county=Dare) | see statewide row | free | yes | shared scraper | High |
| 12 | Dare GIS parcels | maps.darecountync.gov/arcgis/rest/services (Parcels layer id 3) | open REST, queryable | yes | — | **Low** — parcels geometry-only; owner via viewer CSV export, not raw REST. |

Dare tax-fc already via `zacchaeus` + county; fc precursors via eCourts. GIS owner not
in public REST (viewer offers CSV export but not a documented service).

### Hyde
| signal | source | URL / endpoint | access | live? | needs | conf |
|---|---|---|---|---|---|---|
| 4,5 | (already wired) `nc_ptscloud_delinquent_tax` | bcpwa.ncptscloud.com (Hyde tenant, 1,367 rows) | — | yes | none | — |
| 1,2,3,6 | ncnotices.com (county=Hyde) | see statewide row | free | yes | shared scraper | Med |

Hyde has no own ArcGIS server (parcels resolve via NC OneMap statewide, already wired
for geo→parcel). Smallest county; tax lane already maxed. No net-new county-hosted source.

### Carteret
| signal | source | URL / endpoint | access | live? | needs | conf |
|---|---|---|---|---|---|---|
| 12, 11(partial) | **Carteret parcel roll (owner+mailing)** | https://arcgisweb.carteretcountync.gov/arcgis/rest/services/Layers/Parceldata/FeatureServer/0 | open REST, queryable | **yes** | new query wrapper | High — layer `parcel_boundaries`: OWNER/OWNER2, MAIL_ADDRESS1/2/CITY/STATE/ZIP, FullMailingAddress, PropertyAddress, SALE_PRICE, SaleDate, Total_EMV, Use_code, **ROLL_TYPE** (taxed vs tax-exempt). Absentee = MAIL_STATE≠NC or mail≠situs. |
| 4,5 | Carteret delinquent-taxpayer advertisement | https://www.carteretcountync.gov/2274/Delinquent-Taxpayers | free HTML | yes | — | **Low** — no downloadable file; lien list published in newspaper only → capture via ncnotices, not standalone. |
| 1,3 | (already wired) county /1149 tax-fc | — | — | — | — | — |

### Onslow
| signal | source | URL / endpoint | access | live? | needs | conf |
|---|---|---|---|---|---|---|
| 12 | **Onslow parcel roll (owner+mailing)** | https://services8.arcgis.com/eJ9GuQwMsO1iIOw1/ArcGIS/rest/services/parcels/FeatureServer/0 | open hosted FeatureServer, queryable | **yes** | new query wrapper | High — full NC-OneMap schema: ownname/ownfrst/ownlast, mailadd+mcity/mstate/mzip, siteadd, saledate, parval/landval/improvval, parusecode. Absentee via mstate/mcity vs situs. |
| 4,5 | (already PARTIAL-live) tax_lien via existing lanes | — | — | — | probe PTS `bcpwa` tenant for full roll | Med |

### Pender
| signal | source | URL / endpoint | access | live? | needs | conf |
|---|---|---|---|---|---|---|
| 11, 12 | **Pender parcel roll — carries EXEMPT + DEFERRED_VALUE** | https://gis.pendercountync.gov/arcgis/rest/services/Layers/MapServer/4 | open REST, queryable | **yes** | new query wrapper | High — Parcels layer: NAME, ADDR/CITY/STATE/ZIP (mailing), PROPERTY_ADDRESS, SALE_PRICE, LAND/BUILDING/TOTAL_VALUE, TAX_CODES, **EXEMPT**, **DEFERRED_VALUE**, USE_, DEED_BOOK/PAGE, DATE. Best single coastal source: hits signal 11 (senior/disabled/veteran exemption + deferral) AND 12 (absentee) directly. |

### New Hanover
| signal | source | URL / endpoint | access | live? | needs | conf |
|---|---|---|---|---|---|---|
| 4,5 | **New Hanover delinquent real-estate list — DOWNLOADABLE Excel + CSV** | https://www.nhcgov.com/2877/Delinquent-Taxes | free file download, no login; monthly refresh, 10-yr history | **yes** | new fetch+parse (cleanest structured file of all 8) | High |
| 10, 12 | **New Hanover "NHC Properties" — owner + Vacant flag** | https://gis.nhcgov.com/server/rest/services/Thematic/NHC_PropertiesAndBuildings/MapServer/2 | open REST, queryable | **yes** | new query wrapper | Med-High — OWNER, AddressNum/Dir/Street/Type, LAND_USE_CODE, **PropertyType** (values incl. `Vacant`, `FEMA Buyback`). PropertyType=Vacant = signal 10 net-new; no mailing field (pair owner with delinquent CSV for absentee). |
| 1,3 | (already wired) `new_hanover_foreclosures` | — | — | — | — | — |

### Brunswick
| signal | source | URL / endpoint | access | live? | needs | conf |
|---|---|---|---|---|---|---|
| 12 | Brunswick parcel roll | bcgis.brunswickcountync.gov/arcgis/rest/services (Layers folder; TaxParcels/0 per gap_ledger) + data-brunsco.opendata.arcgis.com | open REST | yes | probe Layers-folder parcel layer for owner/mailing fields (root dir confirmed live; specific parcel-with-owner layer not yet field-verified) | Med |
| 1,3 / 4 | (already wired) legal-notices + LP; full tax roll needs PTS-tenant probe (low pri) | — | — | — | — | — |

---

## Wiring win (existing source, cheap change)

**Add New Hanover, Currituck, Hyde to `nc_ecourts_lis_pendens.TARGET_COUNTIES`** (and the
mirrored lists in `nc_ecourts_divorce` / `nc_ecourts_estates`). The Tyler Judgment Search
JSON is keyless, statewide, and facet-selectable — these three coastal counties are simply
absent from the facet list. One-line-per-file change instantly adds signals 2 (lis-pendens),
6 (estates) and 7 (divorce) for the three counties currently getting none of them. Highest
ROI item here after ncnotices.

## County × signal with NO free path (hard walls)
- **Currituck** — owner/mailing/exemption (GIS geometry-only; tax + ROD CAPTCHA). Only ncnotices + eCourts-if-wired reach it.
- **Code enforcement / condemnation / demolition (signal 10)** — no public list for any of the 8 except New Hanover's GIS `PropertyType=Vacant` proxy. Wilmington code enforcement, Onslow/Brunswick/Carteret planning: no machine-readable violation/condemned feed (WALL).
- **Divorce (signal 7)** for Currituck/Hyde/New Hanover until the eCourts facet is added (see wiring win).
- **Bulk tax roll** for Currituck, Carteret, Dare, Brunswick, Pender — only per-parcel/subscription UIs (New Hanover is the lone downloadable-list county).
