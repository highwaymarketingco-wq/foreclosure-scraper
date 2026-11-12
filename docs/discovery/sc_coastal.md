# SC Coastal net-new source discovery — Charleston, Georgetown, Colleton, Beaufort

Date: 2026-08-12. Read-only discovery. Horry EXCLUDED per directive.

Goal: NET-NEW, FREE, buildable lead sources across the 12 distress signals for the four
non-Horry SC coastal counties — sources NOT already wired and NOT known walls.

## Already wired / known (do not re-propose)
- `charleston_mie` (S1/S3 MIE roster), `charleston_delinquent_tax` (S4, RP+MH+FLC),
  `sc_coastal_rosters` (S1 MIE for Georgetown/Colleton/Beaufort — Beaufort 17 MO rosters),
  `georgetown_civicengage` (408), `colleton_tax_sale`, `sc_probate_net` (Charleston 250),
  `sc_state_tax_lien` (S5 statewide DOR), `sc_public_index_lis_pendens` (S2, disclaimer lane),
  bankruptcy (S8 statewide PACER), `enrichment_rod_name_index` (Georgetown+Colleton "Online
  Record System" name→party+amount), Georgetown/Colleton ROD bulk-by-date (georgetowndeeds.com
  honoured; colletondeeds.com ignores window).
- Known WALLS: qPublic/Schneider parcels for Colleton+Georgetown (CAPTCHA/login); Charleston
  gisportal/gis.charlestoncounty.org "no open code layer"; southcarolinaprobate.net
  Georgetown/Colleton dropdowns = 0 records (dead); SCDOT statewide `SC_Parcels` now token-walled.

## KEY THEME
The four counties each self-host an OPEN, no-token county-native ArcGIS parcel REST endpoint
carrying **owner + full mailing address (+ sale price, class, exemption/legal-residence)**.
These are NET-NEW (the wired coastal path used statewide SCDOT SC_Parcels, which is now
token-walled), and they double as the compliant workaround for the qPublic CAPTCHA wall.
They unlock S12 absentee (mailing city/zip != situs) everywhere, feed the address/owner
resolver, and Beaufort even exposes an Exemption field (S11).

---

## Charleston
| Signal | Source | URL / endpoint | Access | Live? | Code/wiring | Conf |
|---|---|---|---|---|---|---|
| 12 absentee + resolver | County parcels (OWNER1/2, full MAIL_* mailing, SALE_PRICE, LEGAL_RESIDENCE, CLASS_CODE) | `gisccapps.charlestoncounty.org/arcgis/rest/services/GIS_VIEWER/New_Parcel_Search/MapServer/61` | ArcGIS query, OPEN no token | YES | New scraper/enricher | High |
| — | (Parcel_Search & Public_Search MapServers) | same host, `/Parcel_Search`, `/Public_Search` | TOKEN-WALLED (499) | wall | — | — |
| 11 exemption | LEGAL_RESIDENCE flag = owner-occupancy proxy (4% ratio), NOT true homestead/senior/vet | layer 61 field | derive | YES | filter | Med |
| 1/2/3/4/5/6 | already wired (mie, delinquent_tax, lis_pendens, state_tax_lien, probate_net) | — | — | — | — | — |
| 10 code/vacant | no open code-enforcement layer (prior wall confirmed) | — | WALL | no | — | — |

## Beaufort  (least-covered county — biggest win)
| Signal | Source | URL / endpoint | Access | Live? | Code/wiring | Conf |
|---|---|---|---|---|---|---|
| 12 absentee + 11 exemption + resolver | County parcels: Owner1/2, MailingAdd/City/State/ZIP, **Exemption**, **LEGRES**, SalePrice, ClassCode, Assessed/Appraised | `gis.beaufortcountysc.gov/server/rest/services/EnerGov/MapServer/1` | ArcGIS query, OPEN | YES | New scraper/enricher | High |
| 4 tax delinquency / 3 tax sale | Treasurer "Tax Sale Final Listing" published as **.xlsx + .pdf** (open, updated pre-sale; 2025 sale Oct 6) | beaufortcountytreasurer.com / treasurerhelp.zendesk.com art. 4409081325069 | GET file (bot-403 on HTML shell; file itself public) | list YES | New scraper (harvest direct file URL) | Med-High |
| — | 48-service open GIS server (ArchiveParcels, Zoning, FloodZones, Addresses, EnerGov) | `gis.beaufortcountysc.gov/server/rest/services` | OPEN | YES | enrichment | High |
| 1 foreclosure MIE | already wired via `sc_coastal_rosters` (17 MO rosters) | — | — | — | — | — |
| 6 probate | NOT on southcarolinaprobate.net; only free path = SC PublicIndex probate disclaimer lane | `publicindex.sccourts.org/beaufort/` | disclaimer | partial | extend lis-pendens lane | Med |
| 10 code/vacant | EnerGov/EnerGovEdit = permit BASE layers only, no public code-case layer | — | WALL | no | — | — |

## Georgetown
| Signal | Source | URL / endpoint | Access | Live? | Code/wiring | Conf |
|---|---|---|---|---|---|---|
| 12 absentee + resolver | Energov PARCELATTRIBUTES: Owner1/2, BillingAddress, City/State/Zip, SalePrice/SaleDate; + layer 2 Parcels (OWNER1/2, full MAIL_*, SALE_PRICE, LEGAL_RESIDENCE) | `gis1.georgetowncountysc.org/portal/rest/services/GCGIS_Energov/MapServer` (tbl 6, layers 2/3) | ArcGIS query, OPEN | YES | New scraper/enricher | High |
| — | GCGIS_OpenData FeatureServer | `gis1.georgetowncountysc.org/portal/rest/services/GCGIS_OpenData/FeatureServer` | OPEN | YES | enrichment | Med |
| 1 MIE / 4 tax / 2 LP | already wired (sc_coastal_rosters, civicengage, colleton path, lis_pendens) + ROD bulk-by-date | — | — | — | — | — |
| 6 probate | aggregator dropdown dead (0 rows); free path = SC PublicIndex probate lane only | `publicindex.sccourts.org/georgetown/` | disclaimer | partial | — | Low-Med |
| 10 code/vacant | Energov service exposes no public violation/case layer | — | WALL | no | — | — |

## Colleton
| Signal | Source | URL / endpoint | Access | Live? | Code/wiring | Conf |
|---|---|---|---|---|---|---|
| 12 absentee + resolver | County parcels open via ArcGIS Hub / Experience viewer (owner-bearing FeatureServer) | hub dataset `colletoncounty::parcels`; viewer `experience.arcgis.com/experience/c3ed5805c6fa4ca5bbaf650fb91cd728` | OPEN (Hub) — exact owner REST endpoint NOT pinned this pass | YES (hub) | Confirm endpoint, then scraper | Med |
| 9 liens / resolver | already wired `enrichment_rod_name_index` (Online Record System, party+doc+amount) + colletondeeds.com | — | — | — | — | — |
| 3/4 tax sale | already wired `colleton_tax_sale` | — | — | — | — | — |
| 1 MIE | already wired `sc_coastal_rosters` (Edisto Beach MO roster) | — | — | — | — | — |
| 6 probate | aggregator dropdown dead; free path = SC PublicIndex probate lane only | `publicindex.sccourts.org/colleton/` | disclaimer | partial | — | Low-Med |
| 10 code/vacant | no open code layer found | — | WALL | no | — | — |

---

## County x signal with NO free path (hard walls)
- **S10 code-enforcement / condemnation / vacant / demolition — all four counties.** Charleston
  (prior wall), Beaufort/Georgetown EnerGov expose only base map layers (Tyler EnerGov
  CitizenAccess portals are JS/login), Colleton none. No free structured feed.
- **S11 true homestead/senior/veteran exemption — Charleston, Georgetown, Colleton.** Only
  occupancy proxies (LEGAL_RESIDENCE) are open; Beaufort is the exception (open `Exemption` code field).
- **S6 probate — Georgetown & Colleton.** southcarolinaprobate.net dropdowns return 0; only the
  SC PublicIndex disclaimer lane remains (partial, not a clean aggregator feed). Beaufort probate
  also aggregator-absent, same PublicIndex-only path.

## Net-new buildable count: 6
1. Charleston `New_Parcel_Search/61` open parcels (owner+mailing+absentee+resolver)
2. Beaufort `EnerGov/MapServer/1` open parcels (owner+mailing+**exemption**+absentee)
3. Beaufort Treasurer delinquent tax-sale list (.xlsx/.pdf)
4. Georgetown `GCGIS_Energov` parcels/PARCELATTRIBUTES (owner+mailing+absentee)
5. Colleton Hub/Experience parcels (owner-bearing, endpoint to confirm)
6. S12 absentee/cash-buyer derivation layer across all four (mailing != situs) — powered by 1/2/4/5
