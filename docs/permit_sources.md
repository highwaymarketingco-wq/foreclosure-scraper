# Permit / Demolition / Condemnation data sources — footprint sweep

Discovery date: 2026-08-13. READ-ONLY probe of city/county sites + ArcGIS REST
directories. No CAPTCHA-solving, no robots-Disallow rides.

Goal: OPEN, FREE, no-login **distress-relevant** permit signals only. Routine
permits (deck/HVAC/reroof) are noise. Valuable = **DEMOLITION** (teardown),
**CONDEMNATION / unsafe / dangerous-structure** orders, **FIRE / major
structural rebuild**, and **EXPIRED / stalled / open-past-due** permits
(abandoned mid-project). Every row wants ADDRESS + permit type + status/date.

Already-built (do NOT rebuild): `asheville_str_permits` (gis.ashevillenc.gov,
SKIP Asheville), `hendersonville_vacant_structures`, `henderson_code_violations`,
`spartanburg_condemned` (county CAMA cond=DL), `spartanburg_city_condemned` (PDF),
`spartanburg_vacant`, plus `counties_generic/arcgis_distress_layers.py` which
already carries `lincoln_code_violations` (STATUS='Open'), `spartanburg_property_cleanup`,
`spartanburg_infill_eligible`, and the Helene damage-assessment layers for
Buncombe/Transylvania/Burke/Pickens.

## Rankings — confirmed-open, net-new distress-permit endpoints

1. **New Hanover County (Wilmington), NC — Building Permits FeatureServer.**
   Demolition permits + expired/stalled status. HEADLINE. Live-confirmed.
2. (No other footprint jurisdiction exposed an open, queryable demolition/
   condemnation permit layer at probe time — see WALLED table.)

Adjacent gold-standard pattern (OUT of footprint, note only, do not add):
Charlotte/Mecklenburg `gis.charlottenc.gov/arcgis/rest/services/HNS/` publishes
`CodeEnforcementOrderstoDemolish`, `CodeEnforcementCasesAll`,
`CodeEnforcementNewAndOpenCases` MapServers — the template to look for elsewhere.

## Table

| Jurisdiction | Endpoint (…/query or portal) | Access | Address field | Type field | Distress filter | Live-confirmed? | Net-new vs built |
|---|---|---|---|---|---|---|---|
| **New Hanover Co / Wilmington NC** | `https://gis.nhcgov.com/server/rest/services/Thematic/BuildingPermits/FeatureServer/0/query` | **open ArcGIS** | NUMBER + STREET + DIR + TYPE + CITY + ZIPCODE | `PERMIT_TYPE`, `WORK_CLASS` | DEMO: `WORK_CLASS LIKE '%Demolition%'` (also `PERMIT_TYPE LIKE '%Demo%'`). EXPIRED/stalled: `PERMIT_STATUS='Expired'`. FIRE/structural: filter `WORK_CLASS`/`PERMIT_TYPE` for structural. Dates: EXPIRATION_DATE, ISSUE_DATE, APPLICATION_DATE | **YES** — returned rows e.g. "NHC Residential Demolition / Demolition / Expired / SEA LILLY"; exceededTransferLimit=true (paginate) | **NET-NEW** |
| New Hanover alt layer | `.../Thematic/EnergovPermitsPlans` (same server) | open ArcGIS (unprobed) | — | — | secondary to BuildingPermits above | no | net-new (redundant) |
| Gaston Co / Gastonia NC | GIS root `gis.gastoncountync.gov/publicgis/rest/services` (PublicGIS folder has NO permit/code/demolition layer); permits via Tyler **EnerGov Citizen Self-Service** portal | **WALLED** | n/a | n/a | GIS `EnerGov` folder returns `{"error":499,"Token Required"}`; PublicGIS folder = parcels/zoning only | probed | walled (net-new blocked) |
| Cleveland Co / Shelby NC | `gis.clevelandcounty.com/arcgis/rest/services` (Zoning FeatureServer only) | **WALLED / FOIA** | n/a | n/a | no permit/code/demolition layer published; permits via Building Inspections office | probed | blocked |
| McDowell Co / Marion NC | `co-mcdowell-nc.smartgovcommunity.com` (SmartGov public portal) | open portal (JS, no bulk) | per-permit page | per-permit | portal search only; no ArcGIS layer; not bulk-queryable | portal errored on probe | net-new only via portal scrape |
| Rutherford Co NC | `ncrutherfordcountycd.govbuilt.com` (GovBuilt portal) | open portal (no bulk) | per-permit | per-permit | portal only; already have `rutherford_tax` | not probed live | low value |
| Anderson Co SC | County = **OpenGov** permit portal; City of Anderson = **ViewPoint Cloud** portal | open portal (no bulk/ArcGIS) | per-permit | per-permit | no open FeatureServer found | probed (search) | net-new only via portal scrape |
| Cherokee Co / Gaffney SC | `services6.arcgis.com/dpaY3zboICQILFY5/.../Cherokee_County_Parcels_/FeatureServer` (parcels only) | GIS parcels open; permits WALLED/FOIA | parcel only | n/a | no code/permit/demolition layer; permits via Building Safety office | probed | blocked |
| Charleston Co + City SC | County `gisccweb.charlestoncounty.org/arcgis/rest/services` (HTTP 500 at probe); City `gis.charleston-sc.gov/arcgis/rest/services` (External folder = EnerGov **geocoders** only); permits via City **EnerGov CSS** "Permit Viewer Map" | **WALLED** | n/a | n/a | no queryable permit/code FeatureServer surfaced; city permit data behind EnerGov CSS viewer | probed | blocked |
| Beaufort Co SC | Beaufort County Connect (SeeClickFix-style app); building via Building Inspections | **FOIA / portal** | n/a | n/a | no ArcGIS permit/code layer surfaced | probed (search) | blocked |
| City of Wilmington NC (separate from county) | `data-wilmingtonnc.opendata.arcgis.com` hub + public "Active Code Enforcement Cases" list | open hub, endpoint **UNCONFIRMED** | likely | likely | hub references a Code Enforcement Cases layer but no live `/query` FeatureServer resolved (not in ArcGIS Online public search) — needs manual hub lookup | **NO** | potential net-new (follow-up) |
| Union / Laurens / Georgetown / Colleton SC; Lincolnton / Morganton-Burke / Brevard-Transylvania NC | — | **FOIA / portal** | — | — | no open permit/demolition ArcGIS layer surfaced (Lincoln code-viol + Transylvania/Burke damage already built) | probed (search) | blocked |

## Build note for New Hanover

New scraper `counties_nc/new_hanover_demolition_permits.py` on the
`arcgis_webmap.query_features` helper. Two passes on the one layer:
- `where=WORK_CLASS LIKE '%Demolition%'` → demolition/teardown leads (highest value).
- `where=PERMIT_STATUS='Expired'` (optionally AND a structural/rebuild WORK_CLASS)
  → abandoned mid-project leads.
Enumerate `outFields` explicitly (never `*`): PERMIT_NUMBER, PERMIT_TYPE,
WORK_CLASS, PERMIT_STATUS, NUMBER, STREET, DIR, TYPE, CITY, ZIPCODE,
APPLICATION_DATE, ISSUE_DATE, EXPIRATION_DATE, VALUATION. Layer paginates
(exceededTransferLimit=true) so loop resultOffset. Some STREET values are null —
keep the row only if a usable address assembles, else drop.
