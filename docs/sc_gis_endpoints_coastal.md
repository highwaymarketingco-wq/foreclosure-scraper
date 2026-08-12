# Coastal SC county-native ArcGIS parcel endpoints

Replacement for the now-walled shared SCDOT layer
(`smpesri.scdot.org/.../SC_Parcels/MapServer` -> HTTP 200 + `{"error":{"code":499,"message":"Token Required"}}`).

Live-verified 2026-08-12. All four endpoints are **OPEN** (no token). Horry excluded per scope.

**Matcher note:** `enrichment_arcgis._pick()` does an EXACT case-insensitive key match
(`norm.get(cand.lower())`), NOT a substring match. So a stored alias `SitusAddre` does
**not** match a live field `GisFile_SitusAddre`, and `OwnerName` does not match `OwnerName1`.
Every "NEW ALIAS NEEDED" below is a real exact-name gap. Several of the SCDOT-era comments in
`FIELD_ALIASES` (e.g. "Beaufort=Appraised/Book/Page", "Beaufort/Georgetown SaleDate already
above") referred to the dead SCDOT layer's UN-prefixed column names; the county-native layers
below use different names.

---

## Charleston  — OPEN, owner OK, NO SITUS (mailing only)
- endpoint: `https://gisccapps.charlestoncounty.org/arcgis/rest/services/GIS_VIEWER/New_Parcel_Search/MapServer/61/query`
- owner_field: `OWNER1`  (already aliased ✓; also `OWNER2`)
- situs_field: **NONE.** Layer 61 exposes only owner MAILING: `MAIL_ST_NO` + `MAIL_ST_NAME` + `MAIL_ST_TYPE` + `MAIL_CITY`/`MAIL_STATE`/`MAIL_ZIP`. There is NO property-location field on this layer. (Situs for Charleston still needs the separate chascogis `Charleston_County_Addresses` resolver — join by PID.)
- value_field: no market/appraised value on this layer. Only `SALE_PRICE` (last-sale amount, aliased ✓).
- sale_field: `SALE_PRICE` (✓) + `RECORDED_DATE` (epoch-ms; **NEW ALIAS NEEDED: sale_date=RECORDED_DATE** — existing alias `RECORDED_D` is a different truncated name). `DOC_DATE` = instrument date.
- deed: `DEED_BOOK_PAGE` — single COMBINED "book-page" field ("1152-771"). **NEW ALIAS NEEDED: deed=DEED_BOOK_PAGE (combined; needs split on '-')**. No separate book/page columns.
- sample owner + address: `OWNER1="WILLIAMS LAURA"`, mailing `1716 TELFAIR WAY, CHARLESTON` (no situs available on layer).
- NEW ALIASES: sale_date=RECORDED_DATE ; deed=DEED_BOOK_PAGE(combined) ; mailing = MAIL_ST_NO+MAIL_ST_NAME+MAIL_ST_TYPE (split, needs stitch).
- status: **OPEN** — carries owner + MAILING only, **no true situs**.

---

## Georgetown  — OPEN, owner OK, situs SPLIT (no single field), no value
- endpoint: `https://gis1.georgetowncountysc.org/portal/rest/services/GCGIS_Energov/MapServer/2/query`  (layer 2 = "Parcels"; layer 3 "ParcelView" and layer 5 "Parcels Live Sync" have the same schema)
- owner_field: `Owner1`  (already aliased ✓; also `Owner2`)
- situs_field: **NO single situs column.** Split across `StreetNumber` + `StreetName` (e.g. "615" + "S CEDAR AVE"). **NEW ALIAS NEEDED: situs stitch = StreetNumber + StreetName** (Brunswick `_stitch_situs`-style). `BillingAddress` is the owner MAILING, not situs.
- value_field: **NONE** on this layer (no Land/Improvement/Appraised/market column).
- sale_field: `SaleDate` (epoch-ms, ✓) + `SalePrice` (✓, frequently 0.0).
- deed: `LegalReference` — single COMBINED "book-page" ("4964-237"). **NEW ALIAS NEEDED: deed=LegalReference (combined; split on '-')**.
- parcel_id: `TMS` (✓). mailing: `BillingAddress`(+`BillingAddress2`) — **NEW ALIAS NEEDED: mailing=BillingAddress**.
- sample owner + address: `Owner1="MCCONNELL PATRICIA W LIFE ESTATE"`, situs (stitched) `615 S CEDAR AVE`.
- NEW ALIASES: situs = StreetNumber+StreetName (stitch) ; deed=LegalReference(combined) ; mailing=BillingAddress.
- status: **OPEN** — owner + situs(split) + sale; **no value, situs needs stitch**.

---

## Colleton  — OPEN, owner + situs BOTH GOOD, no value/sale/deed
- endpoint: `https://services1.arcgis.com/m0cnLGKdhwao8WvM/arcgis/rest/services/Public_Data/FeatureServer/2/query`  (org "ColletonGIS"; layer 2 = "parcels")
- owner_field: `OwnerName1`  — **NEW ALIAS NEEDED: owner=OwnerName1** (existing list has `OwnerName`, not `OwnerName1`). Also `OwnerName2`.
- situs_field: `PropertyAddress`  (already aliased ✓; real "1809 MITCHELL ST"). +`PropertyCity`/`PropertyState`/`PropertyZip`.
- value_field: **NONE** (no value column). sale_field: **NONE**. deed: **NONE**.
- mailing: `OwnerAddress1`(+`OwnerCity`/`OwnerState`/`OwnerZip`) — **NEW ALIAS NEEDED: mailing=OwnerAddress1**.
- parcel_id: `PIN` (✓). Note: string fields are whitespace-padded (fixed width) — `.strip()` on read.
- sample owner + address: `OwnerName1="MCCAULEY EMMA JEAN"`, situs `1809 MITCHELL ST, EDISTO ISLAND`.
- NEW ALIASES: owner=OwnerName1 ; mailing=OwnerAddress1.
- status: **OPEN** — confirmed owner + true situs (owner+situs both real). No value/sale/deed on this layer.

---

## Beaufort  — OPEN, owner + situs + value + sale + deed + EXEMPTION (all GisFile_-prefixed)
- endpoint: `https://gis.beaufortcountysc.gov/server/rest/services/EnerGov/MapServer/1/query`  (layer 1 = "Parcels")
- owner_field: `GisFile_Owner1`  — **NEW ALIAS NEEDED: owner=GisFile_Owner1** (also `GisFile_Owner2`).
- situs_field: `GisFile_SitusAddre`  — **NEW ALIAS NEEDED: situs=GisFile_SitusAddre** (true situs, real "20 SMITH RD"; note: some rows blank " ").
- value_field: `GisFile_Appraised`  — **NEW ALIAS NEEDED: value=GisFile_Appraised** (total appraised; also `GisFile_Land`/`GisFile_Improvemen`/`GisFile_Assessed`/`GisFile_Taxable`).
- sale_field: `GisFile_SaleDate` (string "m/d/yyyy") + `GisFile_SalePrice`  — **NEW ALIASES NEEDED: sale_date=GisFile_SaleDate ; sale_amount=GisFile_SalePrice**.
- deed_book / deed_page: `GisFile_Book` / `GisFile_Page`  — **NEW ALIASES NEEDED: deed_book=GisFile_Book ; deed_page=GisFile_Page** (often blank).
- exemption_field: `GisFile_Exemption`  — **NEW ROLE NEEDED: exemption=GisFile_Exemption** (no `exemption` role exists in FIELD_ALIASES today; feeds the senior-exemption signal). Values like "0".
- parcel_id: `ParcelPIN` / `GisFile_PIN`. mailing: `GisFile_MailingAdd` — **NEW ALIAS NEEDED: mailing=GisFile_MailingAdd**.
- sample owner + address: `GisFile_Owner1="PRYOR JULIUS E"`, situs `20 SMITH RD`.
- NEW ALIASES: owner=GisFile_Owner1 ; situs=GisFile_SitusAddre ; value=GisFile_Appraised ; sale_date=GisFile_SaleDate ; sale_amount=GisFile_SalePrice ; deed_book=GisFile_Book ; deed_page=GisFile_Page ; mailing=GisFile_MailingAdd ; **NEW ROLE** exemption=GisFile_Exemption.
- status: **OPEN** — richest layer (owner+situs+value+sale+deed+exemption); every field carries the `GisFile_` prefix, so NONE of the existing unprefixed aliases fire until added.
