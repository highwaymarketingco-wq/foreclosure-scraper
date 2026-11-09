# Extraction Audit — Top 20 Sources — 2026-11-09

Audit of the top 20 sources by board row count from `docs/run_meta.json -> by_source_on_board`.
Each source probed via live httpx GET where possible. Browser not used.

## Top 20 sources and audit status

| Rows | Source | Gaps found | Fixed? |
|------|--------|-----------|--------|
| 52,408 | `counties_generic.liensnc` | Login handoff scraper — fields fully extracted via `run_cycle()` | No gaps |
| 41,458 | `counties_generic.state_contamination.nc_ust_incidents` | ArcGIS FeatureServer — full field set captured | No gaps |
| 39,046 | `counties_sc.qpaybill_delinquent_roll` | Captures parcel/owner/balance/years/mailing/absentee/value | No gaps |
| 24,999 | `counties_nc.nc_heir_estate_parcels` | Captures acreage/legal/parcel/owner/heirs/mailing/value/rank | No gaps |
| 21,608 | `counties_nc.gaston_vacant` | Beds/baths fields (`XBEDRM`/`XBATHS`/`BASEMENT`) may exist on layer | Deferred — live probe returned empty body |
| 20,786 | `counties_nc.mecklenburg_delinquent_tax` | XLSX-based, field-limited by source format | No gaps |
| 20,399 | `counties_nc.nc_ptscloud_delinquent_tax` | Captures parcel/owner/legal/acreage/assessed/years/interest/bills | No gaps |
| 15,942 | `counties_nc.lincoln_vacant` | Patched Oct 7 — SALEPRICE/SDATE/deed ref/NAME2/mailing all captured | No gaps |
| 15,873 | `counties_sc.sc_ust_registry` | Captures facility/owner/permit/tanks/estate_owned | No gaps |
| 15,258 | `counties_nc.nc_its_public_tax` | Captures parcel/owner/street/city/zip/acreage/legal/years/amounts | No gaps |
| 12,683 | `counties_nc.nc_tax_lien_ads` | PDF-parsed — source-limited (Hoke/Lee/Davidson/Randolph) | No gaps |
| 10,897 | `counties_nc.transylvania_vacant` | Beds/baths fields (`BATHS`/`BEDROOMS`/`HALF_BATHS`) may exist | Deferred — live probe returned empty body |
| 9,310 | `counties_nc.albemarle_observer_tax_lists` | WordPress API + PDF — source-limited | No gaps |
| 9,163 | `counties_nc.rutherford_tax` | XLSX — captures parcel/owner/street/city/zip/legal/amount | No gaps |
| 8,528 | `counties_sc.sc_heir_estate_parcel_cache` | Captures parcel/owner/heirs/mailing/acreage/value/land_use/sale_date | No gaps |
| 8,394 | `counties_sc.sc_dew_lien_registry` | Captures all API fields: balance/tax/interest/penalty/lien_periods | No gaps |
| 8,305 | `counties_nc.nc_county_pdf_delinquent_tax` | PDF-parsed (Lincoln/Catawba/McDowell) — source-limited | No gaps |
| 7,693 | `counties_nc.nc_ecourts_lis_pendens` | Tyler Tech API — full fields extracted | No gaps |
| 7,609 | `counties_generic.state_contamination.nc_dam_safety` | ArcGIS — full fields captured | No gaps |

## Deferred items (ArcGIS live probe failed today)

Both gaston_vacant and transylvania_vacant have candidate bed/bath fields that the agent
found by reading the layer schema previously. Live probe today returned empty body for both
ArcGIS endpoints — cannot add `outFields` without confirming field names exist and are populated.
Action for next session: probe `MapServer/11?f=json` (Gaston) and the Transylvania parcels
layer directly, check field list, then add `XBEDRM,XBATHS` / `BEDROOMS,BATHS` to `_OUT` if confirmed.

---
*Generated 2026-11-09.*
