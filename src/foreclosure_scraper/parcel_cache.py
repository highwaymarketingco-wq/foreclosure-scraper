"""Local parcel-layer cache — bulk-download each county's parcel layer ONCE into a
local SQLite table, then enrich board leads by an in-memory JOIN instead of a
per-lead live GIS query. Turns the multi-hour GIS/resolver phase into seconds.

PROVEN 2026-08-14 (Buncombe): 135,180 parcels downloaded in 80s -> 13.5 MB SQLite ->
6,632 board leads joined in 42 ms (vs ~2.7 h of live per-lead queries every run).

Design:
- `PARCEL_LAYERS[county]` = the county's EXACT parcel-layer /query endpoint + the
  join id field + a field map to our schema. Adding a county = one verified line.
  (Only OPEN ArcGIS counties — SCDOT-token / qPublic / Cott counties can't bulk-export.)
- `refresh_county()` paginates the whole layer and VERIFIES completeness
  (downloaded == server returnCountOnly) before replacing the cache file in place —
  so a truncated download is flagged, never silently accepted. Overwrite-in-place =
  constant disk (~10-15 MB/county, ~200-400 MB all counties, no growth, no cleanup).
- `lookup(county, parcel_id)` reads the local table (indexed on a normalized id).
- Refresh weekly (parcels are slow-moving); runs just READ the cache.
"""
from __future__ import annotations

import json
from urllib.parse import quote
import re
import sqlite3
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger()

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "parcel_cache"
_PAGE = 2000

# county -> {url: full .../query endpoint, id: source id field, map: {our_field: src_field}}
# Only counties VERIFIED (count-match + sample join). Extend one line at a time.
def sale_amount(v) -> "float | None":
    """A parcel-cache sale price as a positive float, or None.

    Some counties' caches store the price as display text ("330,000", "$1,200") and
    a few hold a non-number ("DOD"). Writing that text into raw['gis']['last_sale']
    ['amount'] made 588 board rows carry a string where every consumer (flags.py,
    calc.py, the gis_derived plausibility cap) does arithmetic, and crashed
    scripts/recompute_valuation.py (str > int) on 2026-09-20.
    """
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None
    if f != f or f <= 0:
        return None
    return f


PARCEL_LAYERS: dict[str, dict] = {
    "Buncombe": {
        "url": "https://gis.buncombecounty.org/arcgis/rest/services/property_bc_dis/MapServer/1/query",
        # board ids are the 15-digit PIN (pinnum); index pin (10-digit) too for robustness.
        "id_fields": ["pinnum", "pin"],
        "map": {"owner": "owner", "address": "Address", "market_value": "TotalMarketValue",
                "tax_value": "TaxValue", "acreage": "Acreage",
                "sale_price": "SalePrice"},
    },
    # --- NC core footprint (each id_field + field map VERIFIED against a live sample 2026-08-14) ---
    "Rutherford": {  # board parcel_id = the 6-7 digit internal Parcel_Number (NOT the 10-digit PIN)
        "url": "https://gis.rutherfordcountync.gov/arcgis/rest/services/TaxParcels/MapServer/0/query",
        "id_fields": ["Parcel_Number", "PIN"],   # PIN added 2026-09-21: 367 board rows carry the 10-digit PIN (data-quality audit)
        "map": {"owner": "Property_Owner", "address": "Physical_Address",
                "market_value": "Total_Property_Value", "tax_value": "Total_Land_Value_Assessed",
                "acreage": "Acreage", "living_sqft": "Heated_Area",  # Heated_Area = vision-gate sqft
                "land_use": "Land_Class",
                "owner_mailing": ["Owner_Mailing_Address_1", "Owner_Mailing_Address_2", "Owner_Mailing_Address_3", "Owner_Mailing_Address_City"],
                "sale_price": "Sale_Price"},
    },
    "Lincoln": {  # 10-digit PIN; situs is split across STREETNUM + STREETNAME
        "url": "https://arcgisserver.lincolncountync.gov/arcgis/rest/services/Server_TaxParcelViewerSP/MapServer/0/query",
        # leads with addresses carry the 10-digit PIN; address-less leads carry the internal PARCELID
        "id_fields": ["PIN", "PARCELID"],
        "map": {"owner": "NAME1", "address": ["STREETNUM", "STREETNAME"],
                "market_value": "TOTALVALUE", "acreage": "ACRE", "living_sqft": "MAINAREASQFT",
                "sale_price": "SALEPRICE"},
    },
    "Henderson": {  # 10-digit PIN
        "url": "https://gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "id_fields": ["PIN", "PARCEL_PK"],   # address-less leads carry the internal PARCEL_PK
        "map": {"owner": "PROPERTY_OWNER", "address": "LOCATION_ADDR",
                "market_value": "TOTAL_PROP_VALUE", "acreage": "ACREAGE", "living_sqft": "HEATED_AREA",
                "land_use": "LAND_CLASS",
                "owner_mailing": ["OWNER_MAIL_1", "OWNER_MAIL_2", "OWNER_MAIL_3", "OWNER_MAIL_CITY"],
                "sale_price": "PKG_SALE_PRICE"},
    },
    "Burke": {  # 10-digit PIN
        "url": "https://gis.burkenc.org/arcgis/rest/services/ProdParcelViewFC/MapServer/0/query",
        "id_fields": ["PIN"],
        "map": {"owner": "PROPERTY_OWNER", "address": "LOCATION_ADDR",
                "market_value": "TOTAL_PROP_VALUE", "acreage": "ACREAGE", "living_sqft": "HEATED_AREA",
                "land_use": "LAND_CLASS",
                "owner_mailing": ["OWNER_MAIL_1", "OWNER_MAIL_2", "OWNER_MAIL_3", "OWNER_MAIL_CITY"],
                "sale_price": "PKG_SALE_PRICE"},
    },
    "McDowell": {  # 12-digit parno/altparno
        "url": "https://services9.arcgis.com/ETP7IuCigkUz7iI9/arcgis/rest/services/McDowell_Parcels/FeatureServer/0/query",
        "id_fields": ["parno", "altparno"],
        "map": {"owner": "ownname", "address": "siteadd", "market_value": "parval",
                "tax_value": "landval", "acreage": "gisacres",
                "owner_mailing": "mailadd"},
    },
    "Cleveland": {  # internal 5-digit PID appears as COUNTY_PID/GIS_PID/LOCATE_PID
        "url": "https://gis.clevelandcounty.com/arcgis/rest/services/Basemap/Parcels/MapServer/0/query",
        "id_fields": ["COUNTY_PID", "GIS_PID", "LOCATE_PID"],
        "map": {"owner": "COUNTY_OWNER_1", "address": "LOCATE_ADDRESS",
                "market_value": "COUNTY_TOTAL_VALUE", "acreage": "COUNTY_ACRES",
                "owner_mailing": "COUNTY_MAILING_ADDRESS"},
    },
    # --- SC ---
    "Spartanburg": {
        # board 12-digit id = GISParcelNumber (7102-28-3341.88) with punctuation stripped.
        #
        # CORRECTED 2026-09-13. The previous mapping had `"address": "StreetAddress"` with
        # a comment calling StreetAddress "clean situs". It is NOT the situs -- it is the
        # OWNER'S MAILING ADDRESS. The situs lives in StreetNumber / StreetName /
        # StreetCommunity / StreetZip.
        #
        # They coincide for owner-occupants and diverge for absentees, so the error hid in
        # the majority case. Measured over a 1,000-parcel sample:
        #     559 (56%) mailing == situs   owner-occupied, no visible harm
        #     441 (44%) mailing != situs   the stored "situs" was the mailing address
        # e.g. 3-22-00-019.04 stored "194 WATERFRONT ROW, PROSPERITY" as the property
        # address; the property is at 251 NEAL RD, SPARTANBURG. One row stored
        # "PO BOX 145, INMAN" as a street address.
        #
        # The damage was worst exactly where it mattered: a wrong situs breaks routing and
        # geocoding, and it silently defeats the absentee test, because comparing the
        # mailing address against itself always reports "not absentee". Spartanburg is the
        # largest footprint county on the board at 10,054 rows.
        "url": "https://maps.spartanburgcounty.org/server/rest/services/GIS/CAMA_Parcels/FeatureServer/0/query",
        "id_fields": ["GISParcelNumber", "PARCELNUMBER", "MAPNUMBER"],
        "map": {"owner": "OwnerName",
                "address": ["StreetNumber", "StreetName", "StreetCommunity"],
                "owner_mailing": ["StreetAddress", "City", "State", "Zip"],
                "market_value": "CurrentAppraisedBuildingValue",
                "tax_value": "CurrentTaxableBuildingValue",
                "acreage": "Acreage", "living_sqft": "LivingArea",
                "land_use": "LandUse", "sale_price": "SaleAmount"},
    },
    # --- 2026-09-13. York SC. Found by searching the ArcGIS portal for an SC
    # statewide parcel layer: there ISN'T one (RFA publishes only per-county web
    # maps, unlike NC OneMap), but the search surfaced York's own open service.
    # 134,479 parcels, open Query, and it carries the thing the SC counties keep
    # failing to give us: the OWNER'S MAILING ADDRESS. SC contact coverage is
    # 8-18% against NC's 50-89%, and that gap is THE binding constraint.
    #
    # Verified live: every mapped field populated on sampled rows. Situs is
    # PropertyAddress and mailing is MailAddr1/City/State/Zip -- they are
    # SEPARATE fields here, so this layer cannot repeat the Spartanburg
    # situs-was-really-the-mailing-address bug above. Confirmed on a sample:
    # ParcelID 0300301068 mails to 892 CANIPE RD BLACKSBURG, property is at
    # 2020 KISATCHIE DR, LandUseDesc RESIDENTIAL VACANT -- absentee AND vacant.
    # --- 2026-09-13. Colleton SC. Situs + owner + MAILING for 34,382 parcels.
    # No value field on this layer, so it cannot lift the buy-box arithmetic on its
    # own — but mailing drives the absentee flag, which gates HOT, and Colleton's
    # sampled rows are exactly the profile: properties in Walterboro whose owners
    # mail from Lexington KY, Greenbrae CA and Sumter SC.
    #
    # PIN is the dashed form and matches the board's Colleton parcel_ids exactly
    # ("357-09-00-077.000"). The layer space-pads every text column, which is what
    # prompted the strip fix in _map_val above.
    "Colleton": {
        "state": "SC",
        "url": "https://services1.arcgis.com/m0cnLGKdhwao8WvM/arcgis/rest/services/Public_Data/FeatureServer/2/query",
        "id_fields": ["PIN"],
        "map": {"owner": "OwnerName1", "address": "PropertyAddress",
                "owner_mailing": ["OwnerAddress1", "OwnerCity", "OwnerState", "OwnerZip"],
                "acreage": "Acreage"},
    },
    # --- 2026-09-13. Sumter SC. Found while chasing why the 13,609 new qPayBill
    # leads all ranked D: they carry no value and no mailing address, so the buy-box
    # arithmetic cannot score them. This layer fixes both for Sumter's 3,084 rows.
    #
    # 61,684 parcels, open Query, and it is a FULL record: situs
    # (parcel_address_one) and the owner's MAILING address in separate fields, plus
    # market value, acreage and deed book/page. Sampled rows are textbook absentees
    # — situs 8415 ST JOHNS RD with the owner mailing to COLUMBIA.
    #
    # Board parcel_ids for Sumter are the undashed form ("2241103014"), which is
    # exactly `parid`; `parcel_number` carries the dashed form, so both are indexed.
    "Sumter": {
        "state": "SC",
        "url": "https://gis.sumter-sc.com/server/rest/services/BaseMaps/Sumter_City_County/FeatureServer/7/query",
        "id_fields": ["parid", "parcel_number"],
        "map": {"owner": "owner_name", "address": "parcel_address_one",
                "owner_mailing": ["owner_address_one", "owner_address_two",
                                  "owner_city", "owner_state", "owner_zip"],
                "market_value": "market_value_total",
                "tax_value": "market_value_total",
                "acreage": "deedacre"},
    },
    "York": {  # 10-digit TMS, no punctuation (ParcelID == TAXMAPID)
        "state": "SC",
        "url": "https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "id_fields": ["ParcelID", "TAXMAPID", "AprAccNum"],
        "map": {"owner": "Owner1", "address": "PropertyAddress",
                "owner_mailing": ["MailAddr1", "MailCity", "MailState", "MailZip"],
                "market_value": "AprTotVal", "tax_value": "TaxTotVal",
                "acreage": "deededacres", "living_sqft": "FinishedSQFT",
                "land_use": "LandUseDesc", "sale_price": "SalePrice",
                "sale_date": "DateSold"},
    },
    # Found 2026-09-14 while auditing why Horry (4,213 board rows) sat at 0%
    # mailing: SCDOT (the intended statewide SC fallback) is confirmed dead
    # (token-walled since 2026-08-12), but Horry runs its OWN free public
    # ArcGIS MapServer, independent of SCDOT. Board parcel_id (from qpaybill)
    # is the 11-digit legacy PIN, NOT this layer's 10-digit TMS -- verified
    # live it matches the PINtext field (a string mirror of the numeric PIN
    # field). No situs/property-address field exists on this layer at all
    # (only the OWNER's mailing address columns) -- "address" left unmapped
    # on purpose; every board row already carries its own street_address from
    # its scraper source, and this cache's only job here is mailing.
    "Horry": {
        "state": "SC",
        "url": "https://www.horrycountysc.gov/parcelapp/rest/services/HorryCountyGISApp/MapServer/24/query",
        "id_fields": ["PINtext", "PIN", "TMS"],
        "map": {"owner": "OwnerName",
                "owner_mailing": ["OwnerStreet", "OwnerCity", "OwnerState", "OwnerZip"],
                # AssessedProp is the ~4% SC ratio assessment, not a value: mapping it to tax_value made the
                # tax_value*1.25 ARV fallback price Horry parcels at a fraction of worth (audit 2026-09-21)
                "market_value": "MarketProp",
                "acreage": "Acreage", "land_use": "LandUseCode",
                "sale_date": "SaleDate"},
        # 2026-09-21: the parcel layer above has NO situs field, so horry.sqlite (765,736
        # index rows) held zero addresses and Horry leads sat at 41% address. Layer 22
        # "Addresses" on the SAME service is one point per unit (242,675 points; PIN is a
        # float such as 29612040003.0, TMS a 10-digit text; ADDRESS is the street line
        # "3936 HWY 472", UNIT is separate). VERIFIED LIVE 2026-09-21, maxRecordCount 2000.
        # build_address_overlay keys it by both PIN and TMS and keeps one address per
        # parcel, preferring the row with no UNIT / the lowest UNIT.
        "address_overlay": {
            "url": "https://www.horrycountysc.gov/parcelapp/rest/services/HorryCountyGISApp/MapServer/22/query",
            "id_fields": ["PIN", "TMS"],
            "address": "ADDRESS",
            "unit": "UNIT",
        },
    },
    # Found 2026-09-14, same audit as Horry above: Darlington (2,689 board
    # rows, 0% mailing) runs its own free public ArcGIS FeatureServer,
    # discovered via its published "Darlington County Parcel Viewer" Web Map
    # on ArcGIS Online (the Web Map's operationalLayers list the real
    # FeatureServer URL; the Item page itself never exposes it for a Web Map
    # type, only for Feature Service items directly -- Web Map needs its own
    # /data fetch). MBP/Map_Number carry the SAME dashed TMS board parcel_ids
    # already use, verified live. Zip_Code is deliberately NOT joined into
    # owner_mailing: the live field is an odd (ZIP*10000 + ZIP4) integer
    # encoding (e.g. 293072417 = 29307-2417, 290690000 = 29069 with no +4) that
    # this module's map framework has no transform hook for -- joining it
    # verbatim would bake a malformed 9-digit string onto every mailing
    # address. Address_1 + Address_2_ (street, "City ST") is still a usable,
    # correctly-formed mailing address without it.
    "Darlington": {
        "state": "SC",
        "url": "https://services5.arcgis.com/8FJikaProY6O3ncx/arcgis/rest/services/PARCELS/FeatureServer/1/query",
        "id_fields": ["MBP", "Map_Number"],
        "map": {"owner": ["Name_1", "Name_2_1"], "address": ["E911_STNUM", "E911_STREE"],
                "owner_mailing": ["Address_1", "Address_2_"],
                "market_value": "TOT_MARKET", "tax_value": "ASSESSED_V",
                "acreage": "GIS_ACRES", "land_use": "LANDUSE"},
    },
    # Found 2026-09-14, same audit: Lexington (2,214 board rows, 0% mailing).
    # Rich CAMA layer -- discovered via the county's own ArcGIS Online GIS
    # account ("lexcogis") publishing a plain Map Service, not buried in a Web
    # Map/Experience Builder config this time. TMS matches board parcel_id
    # format exactly (dashed, e.g. "004121-01-024"), verified live on 3 real
    # board rows.
    "Lexington": {
        "state": "SC",
        "url": "https://maps.lex-co.com/agstserver/rest/services/Property/MapServer/4/query",
        "id_fields": ["TMS", "TMS_No_Dash"],
        "map": {"owner": "Owner",
                "address": ["PropAddr_Num", "PropAddr_Str", "PropAddr_Suf"],
                "owner_mailing": ["MailAddr", "MailAddr2", "MailAddr3",
                                   "MailAddr_City", "MailAddr_State", "MailAddr_Zip"],
                "market_value": "MktTotal", "tax_value": "TaxableTotal",
                "acreage": "Acres", "living_sqft": "SqftLA",
                "land_use": "PropTypeDesc", "sale_price": "SalePrice",
                "sale_date": "SaleDate"},
    },
    # Found 2026-09-14, same audit: Lancaster (911 board rows, 0% mailing).
    # Own FeatureServer, found via an ArcGIS Online item under a third-party
    # "layermanager" account (a common pattern for a county that contracts its
    # GIS hosting out) rather than the county's own name -- worth remembering
    # for future county searches when a direct county-owner search comes up
    # empty. PIN matches board parcel_id format exactly (dashed with a
    # trailing ".00", e.g. "0068J-0H-012.00"), verified live. No market/
    # assessed value field on this layer (owner+mailing+situs+sale only).
    "Lancaster": {
        "state": "SC",
        "url": "https://services3.arcgis.com/rJcpRneDUBgTeCT3/arcgis/rest/services/LC_Parcels/FeatureServer/0/query",
        "id_fields": ["PIN", "PIN2"],
        "map": {"owner": "OWNER_NAME", "address": "PROP_LOCAT",
                "owner_mailing": ["OWNER_ADDR", "OWNER_CITY", "OWNER_STAT", "OWNER_ZIP"],
                "acreage": "ACRES", "sale_price": "SALE_PRICE"},
    },
    # Found 2026-09-14, same audit: Barnwell (886 board rows, 0% mailing).
    # Found by guessing an AGOL account-name pattern ("barnwellcountysc")
    # after generic keyword search returned nothing -- worth trying this
    # pattern class (<county>countysc, <county>gis, gis<county>, etc.) before
    # concluding a county has no independent layer. Very rich CAMA export
    # (110 fields: mailing, situs, sqft, beds/baths, year built,
    # owner-occupied flag, sale history). TaxPIN matches board parcel_id for
    # UN-suffixed parcels; board parcel_ids with a trailing ".NN" sub-parcel
    # suffix (about 2 of 5 sampled) have no exact match on this layer at
    # all -- it only carries the PARENT parcel. Left as a straight miss
    # rather than falling back to the parent's data, which could be a
    # different owner for a split sub-parcel.
    "Barnwell": {
        "state": "SC",
        "url": "https://services8.arcgis.com/qqnlHdXochyJPfSY/arcgis/rest/services/ParcelData_ExportFeatures/FeatureServer/2/query",
        "id_fields": ["TaxPIN", "Map_Number"],
        "map": {"owner": ["Name", "Name_2"],
                "address": ["Street_Number_E911", "Street_Name_E911"],
                "owner_mailing": ["Address_1", "Address_2"],
                "market_value": "Tot_Assesd_Value", "tax_value": "Tot_Assesd_Value",
                "acreage": "Tot_Number_Acres", "living_sqft": "SqFt_Total",
                "land_use": "PT163_Class"},
    },
    # --- 2026-09-15: SC mailing-gap sweep, found via a scouting pass over the
    # 10 remaining zero-parcel-cache counties. Both verified live directly
    # (not just via the scouting pass) before being wired in here.
    "Saluda": {  # Saluda was 0% mailing on 428 board rows
        # Own ArcGIS Server at saludacountysc.net, found via the county's
        # classic ArcGIS JS 3.x "SaludaCountyViewer" app (its js/settings.js
        # hard-codes this query URL). Layer 4 is a JOIN VIEW of two SDE
        # tables (Parcels + AssessorData), so every field name below is
        # fully qualified with its source table -- unusual, but confirmed
        # live: 15,566 parcels, count verified via returnCountOnly.
        "state": "SC",
        "url": "https://saludacountysc.net/arcgis/rest/services/ParcelViewers/PublicWebsite_Pro/MapServer/4/query",
        "id_fields": ["SDE.DBO.Parcels.TaxMapNumber", "SDE.DBO.AssessorData.Map_Number"],
        # Situs (Street_Number_E911/Street_Name_E911/PhysicalAddress) came back
        # NULL on all 5 rows sampled live -- mapped anyway since some parcels
        # may carry it, but expect near-zero situs coverage from this layer.
        # Zip_Code is the same malformed ZIP*10000+ZIP4 integer encoding
        # already documented for Darlington (e.g. 290723914 = 29072-3914);
        # left OUT of owner_mailing on purpose -- Address_1 + Address_2
        # ("City ST") is still a usable mailing address without it.
        "map": {"owner": ["SDE.DBO.AssessorData.Name", "SDE.DBO.AssessorData.Name_2"],
                "address": ["SDE.DBO.AssessorData.Street_Number_E911", "SDE.DBO.AssessorData.Street_Name_E911"],
                "owner_mailing": ["SDE.DBO.AssessorData.Address_1", "SDE.DBO.AssessorData.Address_2"],
                "market_value": "SDE.DBO.AssessorData.Tot_Assesd_Value",
                "acreage": "SDE.DBO.AssessorData.Tot_Number_Acres"},
    },
    "Calhoun": {  # Calhoun was 0% mailing on 512 board rows
        # AECOM-hosted ArcGIS Server, found via the county's Esri Web
        # AppBuilder app (gis.aecomonline.net/Calhounparcel) whose
        # config.json points at a webmap item on the county's own ArcGIS
        # Online org (calhouncountysc.maps.arcgis.com) -- the webmap's
        # operationalLayers exposed this real MapServer URL. Confirmed live:
        # 13,867 parcels, TMS format matches board parcel_id exactly
        # (dashed, e.g. "168-00-02-027").
        #
        # Tot_Market_Appr and Sale_Price are comma-formatted strings
        # ("15,700"), which is what prompted the comma-strip fix in
        # _map_val above -- without it this layer's value fields silently
        # dropped to None on every row. Owner is NULL/empty on every row
        # sampled live; the real name lives in Name1/Name2.
        #
        # sale_date deliberately NOT mapped: Sale_Date here is a STRING
        # YYYYMMDD ("20180129", or "00000000" for no sale), not the epoch-
        # millisecond esriFieldTypeDate _iso_date() is built to parse. Fed
        # through as-is it either gets caught by the null-date guard
        # (0 -> None, correct by luck) or silently discarded as
        # implausible (any real 8-digit YYYYMMDD is far too small to be a
        # real epoch-ms timestamp) -- wrong either way. Fixing _iso_date to
        # detect this second date shape is out of scope for one county's
        # sale_date field when owner_mailing is what this cache exists for;
        # left unmapped rather than silently wrong.
        "state": "SC",
        "url": "https://gis.aecomonline.net/arcgis/rest/services/CalhounCO/Parcel/MapServer/2/query",
        "id_fields": ["TMS"],
        "map": {"owner": ["Name1", "Name2"], "address": "Property_Address",
                "owner_mailing": ["Mailing_Address", "Mailing_City_State_ZIP"],
                "market_value": "Tot_Market_Appr", "acreage": "Acres",
                "sale_price": "Sale_Price"},
    },
    "Laurens": {  # TMS (dash format); layer has situs but no value field
        "url": "https://laurenscountygis.org/arcgis/rest/services/Pebble/TaxParcel/MapServer/5/query",
        "id_fields": ["TMS"],
        "map": {"owner": "Owner", "address": "Property_Address", "acreage": "Acres",
                "owner_mailing": ["Mailing_Address", "Mailing_City_State_ZIP"],
                "sale_price": "Sale_Price"},
    },
    # --- 2026-08-30 backbone additions (field maps probed live, valid certs) ---
    "Pickens": {  # SC dashed PIN e.g. "4037-00-34-5506"; open FeatureServer layer 6 (66k parcels)
        "url": "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6/query",
        "id_fields": ["PIN", "ACCTNO"],   # ACCTNO = tax account (e.g. "R0084565")
        "map": {"owner": "NAME1", "address": "LOCADD", "acreage": "ACRES"},  # no total-value field on this layer
    },
    "Gaston": {  # PIN = dashed 10-digit; PID = numeric account; 117k parcels
        "url": "https://gis.gastoncountync.gov/publicgis/rest/services/PublicGIS/Parcels/MapServer/11/query",
        "id_fields": ["PIN", "PID"],
        # FMV_TOTAL (not TOTVAL — reads 0 on exempt parcels); CALCAC (not DEEDAC)
        "map": {"owner": "JAN1_NAME1", "address": "WHOLE_ADDRESS", "market_value": "FMV_TOTAL", "acreage": "CALCAC"},
    },
    "Polk": {  # TMS map-page format e.g. "P92-42"; 17k parcels
        "url": "https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/Parcel_view/FeatureServer/0/query",
        "id_fields": ["TMS"],
        "map": {"owner": "OWNAM1", "address": "PHYSICAL_STREET_ADDRESS",
                "market_value": "TOTAL_TAX_VALUE", "acreage": "DEEDED_ACRES"},
    },
    "Oconee": {
        # ADDED 2026-09-13, overturning the note that used to sit here. It said Oconee's
        # ArcGIS server "rejects bulk paginated export (returns 0 rows to resultOffset
        # queries)" and that "the layer carries no situs street field anyway".
        #
        # Both halves were tested against the wrong service. The CitizenServe layer 5
        # (GISDATA.DBO.assessordata_Registered) answers resultOffset 0, 5,000 AND 60,000
        # with rows, so pagination works. It has no situs -- that half stands -- but it
        # carries the OWNER MAILING ADDRESS on 68,091 of 68,091 parcels, which is the
        # field Oconee actually needed: the county sat at 33% mailing on 2,682 board rows.
        #
        # The join key looked wrong at first glance: some `pin` values are short
        # ("00022"). But the layer also holds proper TMS pins with trailing whitespace
        # ("002-00-01-001   "), and three real board parcels were looked up by hand and
        # all three hit -- 226-00-04-016, 161-00-04-015, 306-02-01-003.
        "url": "https://arcserver2.oconeesc.com/arcgis/rest/services/CitizenServe/MapServer/5/query",
        "id_fields": ["pin"],
        "map": {"owner": "current_owner",
                "owner_mailing": ["owner_street", "owner_citystate", "owner_zip"],
                "acreage": "proval_acres", "land_use": "legal_descr",
                "address": None, "market_value": None},
    },
    "Transylvania": {  # dash-PIN; ADDRESS_1/3 are owner mailing, so owner+value+acre only
        "url": "https://gis.transylvaniacounty.org/server/rest/services/Parcels/MapServer/2/query",
        "id_fields": ["PIN"],
        "map": {"owner": "OWNER_NAME", "market_value": "ASSESSED_V", "acreage": "ACRES",
                "living_sqft": "HEATED_SQ_",
                "sale_price": "SALE_PRICE"},
    },
    # --- 2026-08-18: 4 more counties added (verified live, bulk-exportable) ---
    "Gaston": {  # 117,571 parcels; PIN (dash format) or AKPAR (internal int)
        "url": "https://gis.gastoncountync.gov/publicgis/rest/services/PublicGIS/Parcels/FeatureServer/11/query",
        "id_fields": ["PIN", "AKPAR", "PID"],
        "map": {"owner": "CURR_NAME1", "address": "PHYSSTRADD",
                "market_value": "FMV_TOTAL", "tax_value": "TOTVAL", "acreage": "CALCAC",
                "living_sqft": "SQFT", "land_use": "property_use",
                "owner_mailing": "CURR_ADDR1"},
    },
    "Mitchell": {  # 17,664 parcels; GISPIN (dash format) is the board id
        "url": "https://mapping.mitchellcountync.gov/arcgis/rest/services/WebMapNew/MapServer/12/query",
        "id_fields": ["GISPIN", "PIN", "TaxAcct"],
        "map": {"owner": "Owner1", "address": "LocAddr",
                "market_value": "Total", "tax_value": "Land", "acreage": "LegalAc",
                "living_sqft": "Dwelling",
                "owner_mailing": ["MailAddr", "MailCity", "MailState", "MailZip"]},
    },
    "Polk": {  # 16,878 parcels; TMS (dash format) is the board id
        "url": "https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/TaxParcels/FeatureServer/0/query",
        "id_fields": ["TMS"],
        "map": {"owner": "OWNAM1", "address": "PHYSICAL_STREET_ADDRESS",
                "market_value": "TOTAL_TAX_VALUE", "acreage": "DEEDED_ACRES",
                "living_sqft": "BUILDING_VALUE", "land_use": "NEIGHBORHOOD_CODE",
                "owner_mailing": ["OWCITY", "OWZIPA"]},
    },
    "Pickens": {  # 66,417 parcels; PIN is the board id
        "url": "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/Pickens_Open_data/FeatureServer/6/query",
        "id_fields": ["PIN", "ACCTNO"],
        # market_value was mapped to "CalcAcres" -- an ACREAGE field in a value column.
        # The layer publishes no appraised value, so the honest mapping is None.
        "map": {"owner": "NAME1", "address": "LOCADD",
                "market_value": None, "acreage": "ACRES",
                "land_use": "TAXAREA",
                "owner_mailing": ["ADD1", "CITY", "STATE", "ZIP"],
                "sale_price": "SALEP"},
    },
    # --- 2026-08-19: Anderson SC (city-of-Anderson ArcGIS, 114,516 parcels) ---
    "Anderson": {  # TMS is the board id; layer has owner+mailing+situs+value+sale
        "url": "https://gis.cityofandersonsc.com/arcgis/rest/services/WaterUtilities/County_Parcels/FeatureServer/0/query",
        "id_fields": ["TMS"],
        "map": {"owner": "OWNER", "address": "PHYS_ADDR",
                "market_value": "MRKT_VALUE", "acreage": None,
                "living_sqft": None, "land_use": None,
                "sale_price": "SALE_PRICE"},
    },
    # =====================================================================
    # 2026-09-21 COUNTY-BREADTH ENTRIES  (docs/county_breadth_research_2026-09-21.md)
    #
    # These eight SC counties had NO parcel cache, which is why their leads carry 0%
    # mailing, value and address. Each entry was fetched LIVE the same day: the count is
    # the server's returnCountOnly, the field map was checked against one real row, and
    # field population was measured on a 200-row sample spread across the layer. The
    # weekly refresh (scripts/refresh_parcel_cache.py) still re-verifies completeness
    # (downloaded == returnCountOnly) before a cache file is ever replaced.
    #
    # NOT ADDED, and why (all in the research doc): Richland (custom Leaflet/PHP viewer,
    # no ArcGIS REST), Kershaw (open Parcels_view is geometry + acres only), Marion /
    # Williamsburg / Clarendon / Marlboro (WTH "tgis" viewer, no REST), Edgefield /
    # Fairfield (qPublic behind a Cloudflare challenge), Dorchester (open, but see the
    # research doc: verified and held back).
    # =====================================================================
    "Florence": {
        # 70,098 parcels. TMS is the dashed 5-2-3 form ("00001-04-001") and TMSNODASH the
        # same digits; both are indexed. OWNERNAME is the owner. ADD2 is the mailing
        # street line and ADD3 the city/state/zip line ("LYNCHBURG            SC29080",
        # state glued to the ZIP -- _tidy_mailing splits it). ADD1 (27% populated) is a
        # second name or "C/O ..." line, NOT address, and is left out on purpose: the
        # first live dry-run stored "CRANFORD RANDY A 4001 BYRNES BLVD FLORENCE SC 29506"
        # with it in. ADDR_SITE is the situs, populated on ~74% of
        # parcels. TOTBDGVAL is the BUILDING value only (land is not published on this
        # layer), so it is deliberately NOT mapped to market_value or tax_value: a
        # building-only figure would understate every improved parcel's ARV.
        "state": "SC",
        "url": "https://services1.arcgis.com/40L6yX6OtdCifNez/arcgis/rest/services/County_Tax_Parcel/FeatureServer/0/query",
        "id_fields": ["TMS", "TMSNODASH"],
        "map": {"owner": "OWNERNAME", "address": "ADDR_SITE",
                "owner_mailing": ["ADD2", "ADD3"],
                "acreage": "CALCULATED_ACREAGE"},
    },
    "Charleston": {
        # 197,677 parcels on the county's ENERGOV self-service map service (open, no
        # token; maxRecordCount 1000, resultOffset paging verified). PID is the 10-digit
        # parcel id ("5830600047"). OWNER1/OWNER2 are the owners, MAIL_* the split mailing
        # block, APPRAISAL = LAND_APPR + IMP_APPR = total appraised market value (checked:
        # 285,200 + 819,900 = 1,105,100). The parcel layer has NO situs; the county's
        # address points (70,072 of them, same service, keyed by PID, one per unit with
        # a UNIT column) fill it for the ~35% of parcels that have a structure address.
        "state": "SC",
        "url": "https://gisccapps.charlestoncounty.org/arcgis/rest/services/ENERGOV/energov_css/MapServer/4/query",
        "id_fields": ["PID"],
        "map": {"owner": ["OWNER1", "OWNER2"],
                "owner_mailing": ["MAIL_ST_NO", "MAIL_ST_NAME", "MAIL_ST_TYPE",
                                  "MAIL_2ND_ADDR", "MAIL_2ND_ADDT", "MAIL_CITY",
                                  "MAIL_STATE", "MAIL_ZIP"],
                "market_value": "APPRAISAL", "acreage": "ACREAGE",
                "land_use": "CLASS_CODE", "sale_price": "SALE_PRICE",
                "sale_date": "DOC_DATE"},
        "address_overlay": {
            "url": "https://gisccapps.charlestoncounty.org/arcgis/rest/services/ENERGOV/energov_css/MapServer/0/query",
            "id_fields": ["PID"],
            "address": "WHOLE_ADDRESS",
            "unit": "UNIT",
        },
    },
    "Berkeley": {
        # 123,050 parcels on the county's public "internet" map service, layer 4 (layers
        # 4 and 5 are the same polygons drawn yellow and black). O_TMS is the 10-digit
        # TMS. OwnerName plus StreetAddress1/2, City, StateProvince, Zip are the MAILING
        # block; GIS_Address is the situs (82% over an 800-row sample spread across the
        # layer, but only 49% in one window, so it varies by area). TotalTaxValue tracks recent
        # sale prices at about 1.0x (8 Limetree Ln / Scarlet Oak Ct rows checked:
        # 323,035 vs a 220,000 sale in 2016, 427,110 vs 425,000 in 2021) so it is a market
        # figure, not a 4% assessed one. Berkeley's PayStar rows already carry mail; this
        # adds the VALUE (0% today) and the situs.
        "state": "SC",
        "url": "https://gis.berkeleycountysc.gov/arcgis/rest/services/internet/MapServer/4/query",
        "id_fields": ["O_TMS"],
        "map": {"owner": "OwnerName", "address": "GIS_Address",
                "owner_mailing": ["StreetAddress1", "StreetAddress2", "City",
                                  "StateProvince", "Zip"],
                "market_value": "TotalTaxValue", "acreage": "TotalAcres",
                "sale_price": "SalePrice", "sale_date": "SaleDate"},
    },
    "Aiken": {
        # 103,207 parcels for the WHOLE COUNTY (TaxDistrict values run from
        # "UNINCORPORATED" to "NORTH AUGUSTA CITY"), served by the City of Aiken's
        # ArcGIS Server PublicGIS service, layer 13. The county itself sells its GIS data
        # and hides the assessor map behind qPublic, so this city-hosted layer is the
        # only open bulk source; if it disappears the county has none. PARCEL_ASR is the
        # dashed county TMS ("108-14-04-009"), PARC_NO an older spaced form. AssessedValue
        # is a 4-6% ratio figure and is deliberately NOT mapped.
        "state": "SC",
        "url": "https://gis.cityofaikensc.gov/arcgis/rest/services/PublicGIS/MapServer/13/query",
        "id_fields": ["PARCEL_ASR", "PARC_NO"],
        "map": {"owner": "OwnerName", "address": "LocationAddress",
                "owner_mailing": ["OwnerMailingAddress", "OwnerMailingCity",
                                  "OwnerMailingState", "OwnerMailingZip"],
                "market_value": "TotalMarketValue", "acreage": "Acres",
                "land_use": "PropertyClassType", "sale_price": "SalePrice",
                "sale_date": "SaleDate"},
    },
    "Greenwood": {
        # 39,553 parcels on the county's own ArcGIS Server, CAMA layer 9: a full CAMA
        # record with situs, owner, mailing, market and tax value and building sqft.
        # PIN is dashed ("6913-674-230"). MailAddress is the street line and
        # MailCityState "GREENWOOD, SC 29648-0000". TaxValue_Total (65,600 vs
        # MarketValue_Total 74,000 on the sample) is the capped appraisal, not the 4-6%
        # assessed figure, so it is safe as tax_value. DeedAcres is only ~4% populated.
        "state": "SC",
        "url": "https://www.greenwoodsc.gov/arcgis/rest/services/Operational_Layers/CAMA/MapServer/9/query",
        "id_fields": ["PIN"],
        "map": {"owner": "Owner", "address": "SiteAddress",
                "owner_mailing": ["MailAddress", "MailCityState"],
                "market_value": "MarketValue_Total", "tax_value": "TaxValue_Total",
                "acreage": "DeedAcres", "living_sqft": "SqFt", "land_use": "PropType",
                "sale_date": "PurchaseDate"},
    },
    "Hampton": {
        # 14,871 parcels, published by the county's own ArcGIS Online account
        # (hamptoncountyscgis), layer 1. Same CAMA export shape as Saluda, Barnwell and
        # Calhoun. Tot_Market_Appr / Tot_Number_Acres are comma-formatted strings
        # ("4,229,310") that _map_val parses. Address1/Address2/ZIP_Code are the OWNER
        # MAILING block (ZIP_Code is a clean 5-digit string here, unlike Saluda's
        # ZIP*10000+ZIP4 integer). Street_Number_E911 is only ~52% populated, so situs is
        # often just a street name. Instrmnt_Dt is a bare YYYYMMDD string and is not
        # mapped (see Calhoun). Board parcel_ids: Hampton has ZERO rows today, so the
        # board's format is unknown; the layer's TMS carries a trailing dot
        # ("009-00-00-001.") which normalisation strips to the 10-digit form.
        "state": "SC",
        "url": "https://services8.arcgis.com/6eabNhFouHU5vuYk/arcgis/rest/services/Parcels_Published_view/FeatureServer/1/query",
        "id_fields": ["Map_Number", "Parcel_polygons_TMS"],
        "map": {"owner": ["Name1", "Name2"],
                "address": ["Street_Number_E911", "Street_Name_E911"],
                "owner_mailing": ["Address1", "Address2", "ZIP_Code"],
                "market_value": "Tot_Market_Appr", "acreage": "Tot_Number_Acres",
                "sale_price": "Consideration"},
    },
    "Chester": {
        # 22,300 parcels (the county holds more; treat as partial until a delinquent list
        # proves otherwise) on the county's ArcGIS Online org (rjackson_ChesCnty),
        # Parcels_10_7_24. "Chester" is in DUAL_STATE_COUNTIES, so state="SC" is what
        # keeps this from ever sharing a file with an NC lookup. Name / Map_Number are the
        # dashed TMS WITH its trailing sub-parcel suffix ("047-00-00-066-000").
        # Name_1/Name_2 are owners; Mailing_Ad, Mailing__1 ("CHESTER      SC") and
        # Zip_Code are the mailing block. Land and building appraisals are separate
        # fields (Appraised_ = land, Appraised1 = building; verified on a row with
        # buildings: 84,200 + 58,400), so market_value is their {"sum": ...}. There is NO
        # situs on this layer, and the county's address points carry no parcel key.
        "state": "SC",
        "url": "https://services8.arcgis.com/7uCc8YS9s04rg0sr/arcgis/rest/services/Parcels_10_7_24/FeatureServer/0/query",
        "id_fields": ["Map_Number", "Name"],
        "map": {"owner": ["Name_1", "Name_2"],
                "owner_mailing": ["Mailing_Ad", "Mailing__1", "Zip_Code"],
                "market_value": {"sum": ["Appraised_", "Appraised1"]},
                "acreage": "DEED_ACRES"},
    },
    "Greenville": {
        # 244,178 parcels. The county MOVED this data: the GreenvilleJS/Map_Layers_JS
        # service that greenville_hard_distress.py reads (243,750 parcels, verified
        # 2026-08-03) now answers HTTP 500 "Service ... not found" and the server root
        # lists only a geocoder. Its replacement is arcgis3/.../GreenvilleNJ/QueryLayers
        # (open, no token, maxRecordCount 2000), found by the Midlands research pass and
        # re-verified here 2026-09-21. PIN is the 13-digit id ("0001000100100"), the same
        # form as the county's tax-sale roster.
        #
        # Field semantics checked against sale prices: FAIRMKTVAL is the full current
        # market value; TAXMKTVAL is the CAPPED taxable value (a 1998 purchase at 185,000
        # shows TAXMKTVAL 533,790 against FAIRMKTVAL 1,156,060; a 2025 purchase at
        # 3,600,000 shows both at 3,596,450), so they map to market_value and tax_value.
        # STREET/CITY/STATE/ZIP5 are the owner MAILING block; the SITUS is STRNUM + STRPRE
        # + LOCATE (street name) + STRTYP + STRSUF. DESCR is a legal description, NOT a
        # street ("PH2", "UNIT B"), so it is never used for the address.
        "state": "SC",
        "url": "https://www.gcgis.org/arcgis3/rest/services/GreenvilleNJ/QueryLayers/MapServer/0/query",
        "id_fields": ["PIN"],
        "map": {"owner": ["OWNAM1", "OWNAM2"],
                "address": ["STRNUM", "STRPRE", "LOCATE", "STRTYP", "STRSUF"],
                "owner_mailing": ["STREET", "CITY", "STATE", "ZIP5"],
                "market_value": "FAIRMKTVAL", "tax_value": "TAXMKTVAL",
                "acreage": "TACRES", "living_sqft": "SQFEET", "land_use": "PROPTYPE",
                "sale_price": "SLPRICE", "sale_date": "DEEDDATE"},
    },
}

# schema columns of the local `parcels` table, in insert order
# OWNER_MAILING IS THE POINT OF THE 2026-09-10 ADDITION. Measured that day: 10 of the 14
# cached county layers publish an owner MAILING address, and this schema had no column for
# it, so every one of them was fetched and thrown away. SC owner contact coverage runs
# 8-18% against NC's 50-89% and the per-county coverage matrix names it the binding
# constraint in every SC county -- while the mailing address sat in a layer already being
# downloaded. sale_price/sale_date are added for the same reason: 9 layers carry them and
# the sold-comp pool has no SC half.
_COLS = ("owner", "address", "owner_mailing", "market_value", "tax_value", "acreage",
         "living_sqft", "land_use", "sale_price", "sale_date")
_NUMERIC = {"market_value", "tax_value", "acreage", "living_sqft"}


_US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT "
    "NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
_STATE_ZIP_GLUE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2})(\d{5}(?:-?\d{4})?)$")


def _squash(s: str) -> str:
    """Collapse runs of whitespace. Several county layers space-pad fixed-width
    columns INSIDE the value ("CHESTER               SC", "LN      "), and a padded
    address is a different dedupe key from the same address unpadded."""
    return re.sub(r"\s+", " ", s).strip()


def _tidy_mailing(s: str) -> str:
    """Florence serves the city/state/zip line as "LYNCHBURG            SC29080" (state
    glued to the ZIP). Insert the missing space, but only when the glued token is a
    real two-letter US state code at the very end of the string."""
    m = _STATE_ZIP_GLUE.search(s)
    if m and m.group(1) in _US_STATE_CODES:
        return s[:m.start()] + f"{m.group(1)} {m.group(2)}"
    return s


def _num(val) -> "float | None":
    """A source cell as a float, tolerating comma thousands separators and a leading
    currency sign (Calhoun/Hampton serve "4,229,310"). None when it is not a number."""
    if val is None or isinstance(val, bool):
        return None
    try:
        cleaned = val.replace(",", "").replace("$", "").strip() if isinstance(val, str) else val
        f = float(cleaned)
    except (ValueError, TypeError):
        return None
    return None if f != f else f


def _map_val(rec: dict, col: str, spec):
    """Resolve one schema column from a source row. `spec` is a source field name,
    or a LIST of fields joined with spaces (for split situs like STREETNUM+STREETNAME),
    or a dict {"sum": [f1, f2]} for a NUMERIC column the county publishes as two parts
    (Chester serves land and building appraisals in separate fields), or None (column
    not available for this county). Numeric columns are coerced to float."""
    if spec is None:
        return None
    if isinstance(spec, dict):
        if col not in _NUMERIC:
            return None                # a sum is only meaningful for a number column
        total = None
        for f in spec.get("sum") or ():
            n = _num(rec.get(f))
            if n is not None:
                total = (total or 0.0) + n
        return total if total and total > 0 else None
    if isinstance(spec, list):
        parts = []
        for f in spec:
            v = rec.get(f)
            s = "" if v is None else str(v).strip()
            if s and s not in ("0", "0.0"):
                parts.append(s)
        val = _squash(" ".join(parts)) or None
        if val and col == "owner_mailing":
            val = _tidy_mailing(val)
    else:
        val = rec.get(spec)
        # Strip here too. The LIST branch above strips every part, but a single-field
        # spec did not, so a layer that space-pads its columns stored the padding:
        # Colleton serves "1809 MITCHELL ST" with 24 trailing spaces. A padded address
        # is a different dedupe key from the same address unpadded, and it exports and
        # prints with the padding intact.
        if isinstance(val, str):
            val = _squash(val) or None
    if col in _NUMERIC and val not in (None, ""):
        try:
            # Calhoun (found 2026-09-15) serves Tot_Market_Appr/Sale_Price as
            # comma-formatted strings ("15,700"), which plain float() rejects
            # outright -- silently dropping every value field on that layer to
            # None. Strip thousands-separator commas and a leading currency
            # sign before parsing; harmless on every other county's plain
            # numeric strings, which have neither.
            cleaned = val.replace(",", "").replace("$", "").strip() if isinstance(val, str) else val
            return float(cleaned)
        except (ValueError, TypeError):
            return None
    if col == "sale_date" and val not in (None, ""):
        return _iso_date(val)
    return val


def _iso_date(val):
    """ArcGIS esriFieldTypeDate comes back as epoch MILLISECONDS, so York's
    DateSold would have been stored as the literal string '1747267200000' — a
    date field holding a 13-digit number, which every consumer would either
    render raw or silently fail to parse. Text date fields (Anderson's
    `saledatetx`) pass through untouched.

    Negative values are real: they are pre-1970 sales, which is ordinary for
    long-held property, so they convert rather than being dropped as bad data.
    """
    if isinstance(val, bool):
        return None
    n = None
    if isinstance(val, (int, float)):
        n = val
    elif isinstance(val, str) and val.strip().lstrip("-").isdigit():
        n = int(val.strip())
    if n is None:
        return val.strip() if isinstance(val, str) else val   # text date — leave the value, trim padding
    # Don't gate on magnitude: epoch-ms for a sale in the few years BEFORE 1970 is
    # a small negative number, and long-held property makes those ordinary. Gate on
    # whether the RESULT is a plausible sale year instead.
    if 1850 <= n <= 2100:
        return None                     # a bare year; Jan 1 of it would be invented
    # 0 is ArcGIS's universal null-date placeholder and small junk values land on
    # it too, so anything within ~4 months of the epoch is refused. That forfeits
    # only sales in late 1969 / early 1970 — vanishingly rare — and in exchange no
    # row ever gets a fabricated 1970-01-01 sale date.
    if abs(n) < 10 ** 10:
        return None
    try:
        d = datetime.fromtimestamp(n / 1000, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None
    return d.isoformat() if 1850 <= d.year <= 2100 else None


def _norm_id(v) -> str:
    # whole-number floats (ArcGIS often returns internal PKs as 122973.0) -> "122973",
    # so they match a board id stored as "122973" instead of corrupting to "1229730".
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v or "")
    # drop a trailing .0 ONLY from a PURE float-string ("122973.0"); never from a punctuated
    # parcel number like a Spartanburg GISParcelNumber "1234-56-7890.00" (those zeros are real).
    if re.fullmatch(r"\d+\.0+", s):
        s = s[: s.index(".")]
    return re.sub(r"[^0-9a-z]", "", s.lower())


def _id_variants(v) -> set[str]:
    """Every normalized form a parcel id might appear as, so a 15-digit board PIN
    matches a 10-digit layer PIN and vice-versa (the padded/bare split from dedupe.py)."""
    n = _norm_id(v)
    if not n:
        return set()
    out = {n}
    if len(n) == 15 and n.endswith("00000"):
        out.add(n[:10])                 # 963470749800000 -> 9634707498
    elif len(n) == 10 and n.isdigit():
        out.add(n + "00000")            # 9634707498 -> 963470749800000
    return out


# --- lookup-side id tolerance (2026-09-21) -------------------------------------------------
# _id_variants above is ALSO what refresh_county indexes a cache with, so it must stay
# exactly as built. The two forms below are applied ONLY when reading, in lookup(), and only
# after every exact form has missed, so they can add hits but never change an existing one.
#
#   zero_suffix  a delimited all-zero tail is the "no sub-parcel" marker, i.e. the SAME
#                parcel as the bare id: Darlington "052-00-02-212.000", Anderson
#                "151-06-01-006-000", Forsyth "6844-24-1309.000". The cache holds the bare
#                10-digit form, the board id normalises to 13 digits, so it never matched.
#   zero_pad     a 10+ digit all-numeric PIN written with a different count of trailing
#                zeros than the layer uses: Harnett/Watauga/Transylvania "0546-74-1638" vs
#                "0546741638000", Pender 13 vs 14 digits, Lee 10 vs 12. Bounded to 6 zeros,
#                to ids of 10+ digits (variable-length 5-7 digit internal ids such as
#                Rutherford's Parcel_Number are excluded: "616146" and "6161460" are two
#                different parcels there), and to an UNAMBIGUOUS answer (every candidate row
#                must be the same owner + address + mailing, else no hit).
#
# A sub-parcel with a NON-zero suffix (".01", " 001", "A") is deliberately NOT resolved to its
# parent: the parent's owner and situs can belong to a different lot.
_ZERO_TAIL_RE = re.compile(r"^(.*\d)[.\-\s]+0+$")
_ZERO_PAD_MAX = 6
_ZERO_PAD_MIN_LEN = 10


def _lookup_candidates(v) -> list[tuple[str, str]]:
    """Ordered (normalized id, tier) pairs to try when reading a cache. Tier is 'exact'
    (what _id_variants always produced), 'zero_suffix' or 'zero_pad'."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(k: str, tier: str) -> None:
        if k and k not in seen:
            seen.add(k)
            out.append((k, tier))

    n = _norm_id(v)
    if not n:
        return out
    add(n, "exact")
    for k in sorted(_id_variants(v)):
        add(k, "exact")

    bases: list[str] = []
    s = str(int(v) if isinstance(v, float) and v.is_integer() else (v or "")).strip()
    while True:
        m = _ZERO_TAIL_RE.match(s)
        if not m:
            break
        s = m.group(1)
        base = _norm_id(s)
        if len(base) >= 9 and len(base) >= len(n) - 4:
            bases.append(base)
            for k in sorted(_id_variants(base)):
                add(k, "zero_suffix")

    for base in [n] + bases:
        if len(base) < _ZERO_PAD_MIN_LEN or not base.isdigit():
            continue
        for z in range(1, _ZERO_PAD_MAX + 1):
            add(base + "0" * z, "zero_pad")
            if base.endswith("0" * z) and len(base) - z >= _ZERO_PAD_MIN_LEN:
                add(base[:-z], "zero_pad")
    return out


#: County names that exist in BOTH NC and SC. A cache keyed on the bare name
#: would serve NC Cherokee parcels to SC Cherokee listings and vice versa —
#: wrong owner, wrong address, silently, on a board people bid money off. For
#: these names the state is part of the filename and lookup() REFUSES to guess.
DUAL_STATE_COUNTIES = frozenset({"Cherokee", "Union", "Lee", "Beaufort", "Anson", "Chester"})


def _db_path(county: str, state: str | None = None) -> Path:
    stem = county.lower().replace(" ", "_")
    if county in DUAL_STATE_COUNTIES:
        st = (state or "").strip().upper()
        if st not in ("NC", "SC"):
            raise ValueError(
                f"{county} exists in both NC and SC — a state ('NC'/'SC') is required "
                f"to name its cache, got {state!r}")
        stem = f"{stem}_{st.lower()}"
    return CACHE_DIR / f"{stem}.sqlite"


def cached_counties() -> set[str]:
    out = set()
    for c in PARCEL_LAYERS:
        if c in DUAL_STATE_COUNTIES:
            if any(_db_path(c, st).exists() for st in ("NC", "SC")):
                out.add(c)
        elif _db_path(c).exists():
            out.add(c)
    return out


#: NC counties eligible for the statewide OneMap fallback. All 100 real NC
#: counties, including the four whose name also exists in South Carolina.
#:
#: THE ORIGINAL VERSION OF THIS COMMENT excluded Beaufort, Cherokee, Lee and
#: Union outright: the parcel cache used to be keyed by county NAME with no
#: state, so an NC fallback on a shared name could let an SC lead silently read
#: NC parcel data. That was the right call at the time.
#:
#: FIXED 2026-09-14, and these four added back. _db_path/lookup/nc_onemap_cfg
#: now all require and thread an explicit state for DUAL_STATE_COUNTIES names --
#: a lookup with no state raises or returns None rather than guessing (see
#: test_parcel_cache_state_aware.py) -- and nc_onemap_cfg tags state="NC", so a
#: refresh writes lee_nc.sqlite, never lee.sqlite. With the collision closed at
#: the storage layer, excluding real NC counties was pure loss: Anson (already
#: enabled) had been silently failing to build its cache this whole time,
#: because nc_onemap_cfg omitted the state tag until this same fix. Lee,
#: Cherokee, Union, Beaufort are real NC counties too (35K-118K parcels each on
#: the statewide layer, verified live) and are now enabled on the same basis.
#: SC's halves of these names keep whatever dedicated config they have,
#: unaffected -- a lookup for the SC side still requires state="SC" and cannot
#: reach the NC cache built here.
#:
#: Chester is NOT added: NC has no Chester county -- the statewide layer
#: returns 0 rows for cntyname='Chester', confirmed live. Adding it would build
#: an empty cache that reads as "checked, found nothing" instead of "not a
#: county that exists".
_NC_COUNTY_NAMES = {
    "Alamance", "Alexander", "Alleghany", "Anson", "Ashe", "Avery",
    "Beaufort", "Cherokee", "Lee", "Union",
    "Bertie", "Bladen", "Brunswick", "Buncombe", "Burke", "Cabarrus",
    "Caldwell", "Camden", "Carteret", "Caswell", "Catawba", "Chatham",
    "Chowan", "Clay", "Cleveland", "Columbus", "Craven", "Cumberland",
    "Currituck", "Dare", "Davidson", "Davie", "Duplin", "Durham",
    "Edgecombe", "Forsyth", "Franklin", "Gaston", "Gates", "Graham",
    "Granville", "Greene", "Guilford", "Halifax", "Harnett", "Haywood",
    "Henderson", "Hertford", "Hoke", "Hyde", "Iredell", "Jackson",
    "Johnston", "Jones", "Lenoir", "Lincoln", "Macon", "Madison",
    # "McDowell", NOT "Mcdowell" — this list was built with .title(), which is the
    # third time that call has silently broken a Mc- county here. The board spells
    # it McDowell, so the membership test below missed it and the OneMap fallback
    # never fired for McDowell's 1,772 rows. resolve_layer_cfg now also matches
    # case-insensitively so a future .title() cannot re-break it.
    "Martin", "McDowell", "Mecklenburg", "Mitchell", "Montgomery", "Moore",
    "Nash", "New Hanover", "Northampton", "Onslow", "Orange", "Pamlico",
    "Pasquotank", "Pender", "Perquimans", "Person", "Pitt", "Polk",
    "Randolph", "Richmond", "Robeson", "Rockingham", "Rowan", "Rutherford",
    "Sampson", "Scotland", "Stanly", "Stokes", "Surry", "Swain",
    "Transylvania", "Tyrrell", "Vance", "Wake", "Warren", "Washington",
    "Watauga", "Wayne", "Wilkes", "Wilson", "Yadkin", "Yancey",
}

#: NC OneMap statewide parcels. ONE service, all 100 NC counties, 5,938,900 parcels --
#: verified live 2026-09-10. It carries the two layers the coverage matrix says are thin:
#:
#:   CONTACT   mailadd / munit / mcity / mstate / mzip  = the OWNER MAILING ADDRESS,
#:             populated at 99.6-100% in every NC footprint county measured:
#:               Buncombe 134,741/134,741   Gaston 117,252/117,211
#:               Henderson 75,373/75,373    Rutherford 57,599/57,580
#:               Cleveland 59,964/59,790    Burke 59,374/59,350
#:               Lincoln 56,862/56,862      McDowell 33,449/33,449
#:               Transylvania 31,755/31,755 Polk 18,211/18,063  Mitchell 17,671/17,270
#:             = 662,251 footprint parcels, essentially all of them contactable.
#:   VALUE     parval / landval / improvval, plus saledate, structyear and gisacres.
#:
#: This matters most for BUNCOMBE, LINCOLN and TRANSYLVANIA: their dedicated county layers
#: publish NO mailing field at all, so ~223,000 footprint parcels had no owner mailing
#: available anywhere until this.
NC_ONEMAP_URL = ("https://services.nconemap.gov/secure/rest/services/"
                 "NC1Map_Parcels/FeatureServer/1/query")

#: NC counties whose dedicated layer already carries an owner mailing field. For these the
#: dedicated layer wins -- it is the county's own data and usually richer (heated sqft,
#: condition codes) than the statewide aggregate.
_NC_DEDICATED_WITH_MAILING = {"Rutherford", "Henderson", "Burke", "McDowell", "Cleveland",
                              "Gaston", "Mitchell", "Polk"}


def nc_onemap_cfg(county: str) -> dict:
    """A parcel-cache config for any NC county, served off the statewide layer.

    MUST tag state="NC". Anson, Lee, Cherokee, Union, Beaufort, Chester exist in
    BOTH NC and SC (DUAL_STATE_COUNTIES), and _db_path() requires an explicit
    state for those names to avoid writing a cache neither state can trust.
    Found broken 2026-09-14: this dict omitted "state" entirely, so
    refresh_county's _db_path(county, cfg.get("state")) call raised for Anson --
    the one dual-state county that WAS enabled in _NC_COUNTY_NAMES -- and its
    cache silently never built. The raise was correct behaviour for the missing
    tag; the missing tag itself was the bug.
    """
    return {
        "url": NC_ONEMAP_URL,
        "state": "NC",
        "where": f"cntyname='{county}'",
        "id_fields": ["parno", "altparno", "nparno"],
        "map": {"owner": "ownname", "address": "siteadd",
                "owner_mailing": ["mailadd", "munit", "mcity", "mstate", "mzip"],
                "market_value": "parval", "tax_value": "landval",
                "acreage": "gisacres", "land_use": "parusedesc",
                "sale_price": None, "sale_date": "saledatetx"},
    }


def resolve_layer_cfg(county: str) -> dict | None:
    """Dedicated county layer first, NC OneMap as the statewide fallback.

    The fallback only applies to counties that have no dedicated config, or whose
    dedicated config publishes no mailing address -- Buncombe, Lincoln and Transylvania
    are the three footprint counties in that position.
    """
    cfg = PARCEL_LAYERS.get(county) or _layer_cfg_ci(county)
    if cfg and (cfg.get("map", {}).get("owner_mailing") or county in _NC_DEDICATED_WITH_MAILING):
        return cfg
    canon = _nc_name_ci(county)
    if canon:
        return nc_onemap_cfg(canon)
    return cfg


_NC_NAMES_CI = None
_LAYERS_CI = None


def _nc_name_ci(county: str) -> str | None:
    """Case-insensitive NC-county match, returning the CANONICAL spelling.

    Exists because "McDowell".title() is "Mcdowell" and that mistake has now been
    made three separate times in this codebase. Matching on the lowercased name
    means the next one costs nothing.
    """
    global _NC_NAMES_CI
    if _NC_NAMES_CI is None:
        _NC_NAMES_CI = {n.lower(): n for n in _NC_COUNTY_NAMES}
    return _NC_NAMES_CI.get((county or "").strip().lower())


def _layer_cfg_ci(county: str) -> dict | None:
    global _LAYERS_CI
    if _LAYERS_CI is None:
        _LAYERS_CI = {k.lower(): v for k, v in PARCEL_LAYERS.items()}
    return _LAYERS_CI.get((county or "").strip().lower())


def _src_fields(id_fields, spec_map) -> str:
    """Comma-joined outFields for a layer: its id fields plus every field any map spec
    names. A spec is a field name, a LIST of fields (split situs), or a {"sum": [...]}
    dict (numeric column published in parts)."""
    src: set[str] = set(id_fields)
    for spec in spec_map.values():
        if isinstance(spec, dict):
            src.update(spec.get("sum") or ())
        elif isinstance(spec, list):
            src.update(spec)
        elif spec:
            src.add(spec)
    return ",".join(sorted(src))


async def _download_rows(base: str, where: str, out_fields: str):
    """Count-verified bulk download of one ArcGIS layer. Returns (rows, expected).

    COUNT-DRIVEN pagination: keep pulling until we've collected `exp` rows. Advance by
    the actual number returned (some servers return < _PAGE per page), and retry a page
    up to 3x on a transient empty/error response instead of ending the loop early (which
    is what silently truncated Burke @30k / Laurens @22.9k on the first pass).
    Raises RuntimeError("count: ...") when the expected count cannot be read.
    """
    from .http_client import get_text
    # A STATEWIDE layer needs a per-county filter. NC OneMap publishes all 5,938,900 NC
    # parcels in one service, so its config carries where=cntyname='<County>' and the
    # count check and every page must both use it -- counting 5.9M and paging one county
    # would never terminate.
    where_q = quote(where, safe="")
    # expected count first (completeness check)
    try:
        exp = json.loads(await get_text(f"{base}?where={where_q}&returnCountOnly=true&f=json",
                                        timeout=40, impersonate=True)).get("count")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"count: {str(e)[:80]}") from e

    rows, offset, empties = [], 0, 0
    while exp is None or len(rows) < exp:
        url = (f"{base}?where={where_q}&outFields={out_fields}&returnGeometry=false"
               f"&resultOffset={offset}&resultRecordCount={_PAGE}&f=json")
        try:
            data = json.loads(await get_text(url, timeout=90, impersonate=True))
            feats = data.get("features") or []
        except Exception:  # noqa: BLE001 — transient; retry this same offset
            feats = []
        if not feats:
            empties += 1
            if empties >= 3:
                break            # genuinely no more rows at this offset — stop
            continue
        empties = 0
        rows.extend(f["attributes"] for f in feats)
        offset += len(feats)     # advance by what we actually got, not a fixed page size
        if offset > 3_000_000:
            break
    return rows, exp


def _complete(rows, exp) -> bool:
    """COMPLETENESS GATE: never replace the cache with a short download."""
    return exp is not None and abs(len(rows) - exp) <= max(2, int(exp * 0.001))


def _unit_key(unit) -> tuple:
    """Sort key that puts a parcel's own street address ahead of an apartment row.

    "No unit" sorts first; otherwise the lowest unit wins, compared naturally so unit
    "2" precedes "10". Horry publishes one address point per unit (242,675 points), and
    a parcel-level situs must be the building's address, not "APT 4118"'s.
    """
    u = "" if unit is None else str(unit).strip()
    if u.lower() in ("", "0", "none", "null", "nan"):
        return (0, ())
    parts = re.split(r"(\d+)", u.lower())
    return (1, tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p))


def build_address_overlay(rows, ocfg: dict) -> dict[str, tuple]:
    """Index a SITUS-ADDRESS layer by every normalized id variant of its parcel key.

    Some counties publish the parcel polygon and the situs on DIFFERENT layers, keyed
    by the same PIN/TMS: Horry's parcel layer (MapServer/24) has no address field at all
    while layer 22 carries 242,675 address points keyed by PIN and TMS, and Charleston's
    parcel layer has none while its address points carry PID. The primary parcel layer
    was cached and its situs thrown away, leaving those counties' leads without one.

    Returns {id_variant: (unit_key, address)}. When several points share a parcel the
    smallest (unit_key, address) wins, so the choice is deterministic and prefers the
    row with no unit / the lowest unit.
    """
    spec = ocfg["address"]
    ufield = ocfg.get("unit")
    idx: dict[str, tuple] = {}
    for r in rows:
        addr = _map_val(r, "address", spec)
        if not addr:
            continue
        cand = (_unit_key(r.get(ufield)) if ufield else (0, ()), addr)
        for f in ocfg["id_fields"]:
            for k in _id_variants(r.get(f)):
                cur = idx.get(k)
                if cur is None or cand < cur:
                    idx[k] = cand
    return idx


def overlay_address(keys, overlay) -> "str | None":
    """Best overlay address for a parcel known under `keys` (any id variant), or None."""
    best = None
    for k in keys:
        cand = overlay.get(k)
        if cand is not None and (best is None or cand < best):
            best = cand
    return best[1] if best else None


async def refresh_county(county: str) -> dict:
    """Bulk-download + verify + replace the cache for one county. Returns a status dict."""
    cfg = resolve_layer_cfg(county)
    if not cfg:
        return {"county": county, "ok": False, "error": "no config"}
    base = cfg["url"]
    out_fields = _src_fields(cfg["id_fields"], cfg["map"])
    t0 = time.time()
    try:
        rows, exp = await _download_rows(base, cfg.get("where", "1=1"), out_fields)
    except RuntimeError as e:
        return {"county": county, "ok": False, "error": str(e)}

    if not _complete(rows, exp):
        return {"county": county, "ok": False, "downloaded": len(rows), "expected": exp,
                "error": "incomplete — cache NOT replaced"}

    # OPTIONAL SITUS OVERLAY (see build_address_overlay). Held to the same completeness
    # gate as the primary layer: a short overlay would silently REGRESS a cache that had
    # addresses last week, so an incomplete one leaves the existing cache in place.
    overlay: dict[str, tuple] = {}
    ocfg = cfg.get("address_overlay")
    if ocfg:
        o_fields = _src_fields(ocfg["id_fields"], {"address": ocfg["address"],
                                                   "unit": ocfg.get("unit")})
        try:
            o_rows, o_exp = await _download_rows(ocfg["url"], ocfg.get("where", "1=1"), o_fields)
        except RuntimeError as e:
            return {"county": county, "ok": False, "error": f"address overlay {e}"}
        if not _complete(o_rows, o_exp):
            return {"county": county, "ok": False, "downloaded": len(rows), "expected": exp,
                    "overlay_downloaded": len(o_rows), "overlay_expected": o_exp,
                    "error": "address overlay incomplete, cache NOT replaced"}
        overlay = build_address_overlay(o_rows, ocfg)
        del o_rows

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _db_path(county, cfg.get("state")).with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE parcels(id TEXT, owner TEXT, address TEXT, "
                "owner_mailing TEXT, market_value REAL, tax_value REAL, acreage REAL, "
                "living_sqft REAL, land_use TEXT, sale_price REAL, sale_date TEXT)")
    m = cfg["map"]
    recs = []
    addr_i = _COLS.index("address")
    overlay_filled = 0
    for r in rows:
        keys: set[str] = set()
        for f in cfg["id_fields"]:
            keys |= _id_variants(r.get(f))
        if not keys:
            continue
        vals = [_map_val(r, c, m.get(c)) for c in _COLS]
        if overlay and not vals[addr_i]:
            oa = overlay_address(keys, overlay)
            if oa:
                vals[addr_i] = oa
                overlay_filled += 1
        vals = tuple(vals)
        recs.extend((k, *vals) for k in keys)   # index the parcel under each id variant
    con.executemany("INSERT INTO parcels VALUES(" + ",".join("?" * (1 + len(_COLS))) + ")", recs)
    con.execute("CREATE INDEX idx_id ON parcels(id)")
    con.commit(); con.close()
    tmp.replace(_db_path(county, cfg.get("state")))   # atomic overwrite-in-place
    status = {"county": county, "ok": True, "downloaded": len(rows), "expected": exp,
              "seconds": round(time.time() - t0, 1),
              "mb": round(_db_path(county, cfg.get("state")).stat().st_size / 1e6, 1)}
    if ocfg:
        status["overlay_addresses"] = overlay_filled
    return status


_CONN: dict[str, sqlite3.Connection] = {}


def lookup(county: str, parcel_id: str, state: str | None = None) -> Optional[dict]:
    """Local join: return {owner,address,market_value,tax_value,acreage,living_sqft} or None.

    `state` is REQUIRED for the county names in DUAL_STATE_COUNTIES. Without it
    this returns None rather than guessing which state's parcel layer to read.
    """
    return lookup_with_tier(county, parcel_id, state)[0]


def lookup_with_tier(county: str, parcel_id: str,
                     state: str | None = None) -> tuple[Optional[dict], Optional[str]]:
    """lookup() plus WHICH id form matched: 'exact' (the forms this module has always
    tried), 'zero_suffix' or 'zero_pad' (see _lookup_candidates), or None on a miss.
    Scripts use the tier to report how many hits the tolerance added."""
    try:
        p = _db_path(county, state)
    except ValueError:
        return None, None   # dual-state name, caller had no state — refuse to guess
    if not p.exists() or not (parcel_id or "").strip():
        return None, None
    ckey = p.name
    con = _CONN.get(ckey)
    if con is None:
        con = _CONN[ckey] = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    sel = "SELECT " + ",".join(_COLS) + " FROM parcels WHERE id=?"
    pad_rows: list[tuple] = []
    for k, tier in _lookup_candidates(parcel_id):
        try:
            row = con.execute(sel, (k,)).fetchone()
        except sqlite3.OperationalError:
            return None, None   # stale-schema cache (pre-land_use column) — weekly refresh rebuilds it
        if not row:
            continue
        if tier == "zero_pad":
            pad_rows.append(row)     # never take the first: prove there is only one parcel
            continue
        return {c: v for c, v in zip(_COLS, row) if v not in (None, "")}, tier
    if pad_rows:
        ident = {(r[0], r[1], r[2]) for r in pad_rows}   # owner, address, owner_mailing
        if len(ident) == 1:
            return {c: v for c, v in zip(_COLS, pad_rows[0]) if v not in (None, "")}, "zero_pad"
    return None, None
