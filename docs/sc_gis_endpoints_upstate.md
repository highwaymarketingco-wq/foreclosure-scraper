# Upstate SC county-native ArcGIS parcel endpoints (owner + situs)

Replacement for the hard-walled shared SCDOT layer
(`smpesri.scdot.org/.../SC_Parcels/MapServer` → HTTP 200 + `{"error":{"code":499,"message":"Token Required"}}`).

Goal per county: ONE open (no-token) county-native ArcGIS layer returning BOTH a real
OWNER name and a real SITUS (property street address, not the owner mailing address).
Field names below are matched against `FIELD_ALIASES` in `enrichment_arcgis.py`.

Probed live 2026-08-12. Query pattern used:
`<url>/query?where=1=1&outFields=*&resultRecordCount=1&returnGeometry=false&f=json`

Legend: OPEN = free, no token, owner+situs both present & populated.
OWNER-ONLY / SITUS-ONLY = one of the two missing. WALLED = no free county-native path.

---

## Spartanburg — OPEN ✅
- Endpoint: `https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0/query`
- owner_field: `OwnerName`  (also `TaxpayerName`, `PreviousOwnerName`)
- situs_field: `PropertyLocation`  (also `StreetAddress` + `City`/`Zip`)
- value_field: `CurrentAppraisedLandValue` + `CurrentAppraisedBuildingValue` (no single total; `SaleAmount` was null)
- sale_field: `SaleDate`  (epoch ms)
- deed_book / deed_page: `DeedBook` / `DeedPage` (also `InstrumentNumber`)
- sample: OwnerName `HALLIDAY Q STANFORD IV` | PropertyLocation `1101 PARTRIDGE RD SPARTANBURG`
- NEW ALIASES: owner `OwnerName` = already known. situs `PropertyLocation` = already known.
  value=`CurrentAppraisedLandValue`/`CurrentAppraisedBuildingValue` and deed=`DeedBook`/`DeedPage` if not aliased.
- Note: richest layer of the seven (full CAMA roll — beds/baths/year built/land use all present). `/server/` path, NOT `/arcgis/`.

## Laurens — OPEN ✅
- Endpoint: `https://www.laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/5/query`
- owner_field: `Owner`  (also `Name1`, `Name2`)
- situs_field: `Property_Address`  (distinct from mailing `Mailing_Address` / `Mailing_City_State_ZIP`)
- value_field: none (no market value; only `Sale_Price`)
- sale_field: `Sale_Date` (yyyymmdd string), `Sale_Price`
- deed_book / deed_page: `Deed_Book` / `Deed_Page` (also `Plat_Book`/`Plat_Page`)
- sample: Owner `KELLEY NATHANIEL L TRUSTEE` | Property_Address `487 COOPER BRIDGE ROAD` (mailing = `PO BOX 41`)
- NEW ALIASES: situs `Property_Address` = already known. owner `Name1` = known (`NAME1`); flag `Owner` (mixed-case) as NEW if alias match is case-sensitive — NEW ALIAS NEEDED: owner=Owner.
- Note: also `Pebble/LaurensCountyData/MapServer/0` ("Property Parcels") exists but its query 400s (group/annotation); use TaxParcel/5.

## Pickens — OPEN ✅
- Endpoint: `https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6/query`
- owner_field: `NAME1`  (also `NAME2`)
- situs_field: `LOCADD`  (+ `LOCCITY`/`LOCZIP`; mailing is separate `ADD1`/`CITY`/`STATE`/`ZIP`)
- value_field: none (no market value; `BLDGS` count, `ACRES` only)
- sale_field: `SALEDT`, `SALEP`
- deed_book / deed_page: none
- sample: NAME1 `HOLDER STEPHEN R` | LOCADD `413 BROWN BOTTOM RD` CENTRAL (mailing `1201 COLONIAL RIDGE CT SW`)
- NEW ALIASES: owner `NAME1` = already known. **NEW ALIAS NEEDED: situs=LOCADD** (not in situs alias list).
- Note: layer-0 first rows are blank/placeholder; filter `where=NAME1<>' '`. This is the county's own hosted open-data roll (GISpickens org). The prior `pickens_delinquent_parcels` layers are a different (delinquent-only) product.

## Oconee — OWNER-ONLY ⚠️ (no situs; mailing address only)
- Endpoint: `https://arcserver2.oconeesc.com/arcgis/rest/services/PARCELDATA_owner/MapServer/1/query`
- owner_field: `current_owner`
- situs_field: NONE — only `owner_street` / `owner_citystate` / `owner_zip` = OWNER MAILING address, not situs
- value_field: none
- sale_field: none
- deed_book / deed_page: `deed_book` / `deed_page`
- sample: current_owner `CROWE MICHAEL CLAYTON` | owner_street `141 HONEYWOOD LN` WEST UNION SC (mailing)
- NEW ALIASES: **NEW ALIAS NEEDED: owner=current_owner**. Mailing (not situs): `owner_street`.
- Note: `PARCELDATA_owner/0`, `PARCELDATA/0`, `PARCELDATA/1`, `Parcels_OpenData/0` are group layers or geometry-only (TMS, no owner/situs). Only `PARCELDATA_owner/MapServer/1` carries owner. No property street address anywhere in the open Oconee ArcGIS — situs still requires qPublic/CARD.

## Anderson — SITUS-ONLY ⚠️ (owner masked)
- Endpoint (situs/value): `https://propertyviewer.andersoncountysc.org/arcgis/rest/services/NewPropertyViewer/MapServer/5/query` (also `QueryMap/MapServer/8`)
- owner_field: `TAXOWNSTR` exists but is ALWAYS NULL (masked); `TAXOWN` in `Parcel_Sales/0` also always null → NO usable owner
- situs_field: `PHYS_ADDR`  (e.g. `ASHLEY DOWNS 601 ASHLEY DOWNS CIR`)
- value_field: `MRKT_VALUE`
- sale_field: `SALE_YEAR`, `SALE_PRICE`
- deed_book / deed_page: `DBOOK` / `DPAGE`
- NEW ALIASES: situs `PHYS_ADDR` = already known. value `MRKT_VALUE` if not aliased.
- Verdict: WALLED for name→address resolution — Anderson's public GIS deliberately nulls owner. Endpoint is open and gives situs+value+deed keyed by TMS, but cannot resolve BY owner name. (Note: TLS chain on this host validates with normal curl; no cert error hit. The known `propertyviewer` candidate and `gis.cityofandersonsc.com/City_Parcels` both expose no owner.)

## Cherokee — WALLED ❌
- No county-native open ArcGIS. `cherokeecountysc.gov/gis-mapping/gis-parcel-map` routes to qPublic (`qpublic.schneidercorp.com?App=CherokeeCountySC`).
- AGO-hosted `Cherokee_County_Parcels_` (org `dpaY3zboICQILFY5`) is Cherokee County **GEORGIA** (Canton), not SC.
- Only SC parcel layer indexed is the token-walled SCDOT `SC_Parcels/MapServer/10`. No free owner+situs endpoint.

## Union — WALLED ❌
- County ArcGIS server exists (`http://www.unionco.org/unioncomaps/rest/services/...`) but WAF-403s all programmatic requests (Referer/UA spoofing did not help; blocks directory and every service incl. layers its own webmap references).
- The AGO "Union County Tax Parcels" webmap (`fe8023d9ec4a4feaa53b14fc2d3d25ad`, owner `mlayos`) lists only Soils/Roads/Aerial/Zoning/Boundary/DFIRM — NO parcel operational layer.
- Public viewer `unionsc.wthgis.com` is a proprietary WTH Technology raster viewer with no ArcGIS/REST backend exposed.
- The experience app `8ce9289b…` labeled "Union County Parcel Viewer" is actually Union County **New Mexico** (data source `unioncountynm-assessor.tylerhost.net`).
- No free county-native open owner+situs endpoint reachable. Owner data behind WAF/WTH/SCDOT-walled only.

---

## Summary table
| County | Status | Endpoint (…/query) | owner | situs |
|---|---|---|---|---|
| Spartanburg | OPEN | maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0 | OwnerName | PropertyLocation |
| Laurens | OPEN | laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/5 | Owner / Name1 | Property_Address |
| Pickens | OPEN | services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6 | NAME1 | LOCADD (NEW) |
| Oconee | OWNER-ONLY | arcserver2.oconeesc.com/arcgis/rest/services/PARCELDATA_owner/MapServer/1 | current_owner (NEW) | — (mailing only) |
| Anderson | SITUS-ONLY | propertyviewer.andersoncountysc.org/arcgis/rest/services/NewPropertyViewer/MapServer/5 | masked/null | PHYS_ADDR |
| Cherokee | WALLED | — | — | — |
| Union | WALLED | — | — | — |

## FIELD_ALIASES additions needed
- situs: add `LOCADD` (Pickens)
- owner: add `current_owner` (Oconee); add `Owner` (Laurens) if match is case-sensitive
- (optional) value: `MRKT_VALUE` (Anderson), `CurrentAppraisedLandValue`/`CurrentAppraisedBuildingValue` (Spartanburg)
- (optional) deed: `DeedBook`/`DeedPage` (Spartanburg), `Deed_Book`/`Deed_Page` (Laurens), `deed_book`/`deed_page` (Oconee), `DBOOK`/`DPAGE` (Anderson)
