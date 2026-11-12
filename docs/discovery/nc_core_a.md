# NC Core A — net-new source discovery: Buncombe, Henderson, Transylvania, Polk, McDowell

Written 2026-08-12. Read-only discovery pass. Scope: hunt NET-NEW, FREE, buildable
lead sources for the 5 counties across all 12 distress signals that are NOT already
wired in `SOURCE_REGISTER.md` and NOT already-documented walls in
`road_to_100_matrix.md` / `road_to_100_alternates_*.md`. Free + public only. No
CAPTCHA solving, no robots-Disallow riding, no people-search PII.

Every candidate below was probed live this pass (marked **[LIVE 08-12]**). Method =
ArcGIS REST catalog + layer `?f=json` metadata and bounded `returnCountOnly` /
`resultRecordCount=5` sample queries (no bulk pull), plus official-site + SERP reads.

Style: no em dashes.

---

## Headline

Two genuine net-new, live, free, buildable tax-delinquency sources found, both on
open county ArcGIS hosted feature services that prior passes looked at only for an
exemption field and never enumerated for tax-balance data:

1. **Buncombe — `Buncombe_County_All_Property_Bills_Unpaid_from_2024` FeatureServer.**
   6,231 unpaid bills, open GET, carries owner + PIN + situs + `levy_year` +
   `original_bill_amount` + `total_due` + `mortgage_co`/`loan_num` +
   `exempt_value`/`deferred_value`. This is far richer than the 1,155-row annual
   advertisement PDF that `counties_nc.buncombe_delinquent_tax` reads today, and it
   is multi-year (matching per-year layers exist for 2023 and a full 2025 billing
   layer). Upgrades Buncombe S4 from a once-a-year PDF snapshot to a live per-year
   unpaid roll, and the `mortgage_co`/`loan_num` columns are a bonus lender signal.

2. **Polk — `TaxParcels` FeatureServer `TOTAL_TAX_OWED` + owner-mailing block.**
   16,677 parcels return `TOTAL_TAX_OWED > 0`, open GET, and the layer carries a
   distinct owner-mailing block (`OWADR1/OWCITY/OWSTA/OWZIPA`) separate from
   `PHYSICAL_STREET_ADDRESS`. Prior signal pass probed this exact layer only for an
   exemption field ("no exemption field") and missed the live tax-balance and
   mailing columns. Closes the Polk S4 `◐fx` cell (currently newspaper-subset only,
   full roll assumed behind the DevNet/BAS SPA wall) and adds owner-mailing for S12
   absentee + mailability.

Everything else probed for these 5 counties confirmed the existing walls (code
enforcement in the three rural counties, senior exemption outside Buncombe, ROD
already wired). No new hard walls; no new false hope.

---

## Per-county net-new source tables

Legend — access: **ArcGIS** = open REST FeatureServer query, no auth. live: probed
this pass. build: **code** = new parser needed · **wiring** = point an existing
reader at it. conf: confidence the source produces the claimed signal.

### Buncombe NC (matrix 79%; open cells S5 TAXL fa, S9 LIEN fx, S10 CODE partial)

| Signal | Source | Exact endpoint | Access | Live? | Code/Wiring | Conf |
|---|---|---|---|---|---|---|
| S4 TAXD | Buncombe unpaid property bills (per-year, 2023 + 2024) | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/ArcGIS/rest/services/Buncombe_County_All_Property_Bills_Unpaid_from_2024/FeatureServer/0/query` (2023 twin: `.../All Property Unpaid Bills from 2023/FeatureServer`) | ArcGIS GET | **[LIVE 08-12]** 6,231 rows; fields owner1_*, pin, address_line1/city/state, levy_year, original_bill_amount, total_due, mortgage_co, loan_num, exempt_value | code (new parser, paginate maxRecordCount 2000 via resultOffset) | HIGH |
| S4 TAXD / all-bills base | Buncombe all property bills 2025 (full billed roll, join key) | `https://services6.arcgis.com/VLA0ImJ33zhtGEaP/ArcGIS/rest/services/Buncombe_County_All_Property_Bills_from_2024/FeatureServer` and `..._from_2025/FeatureServer` | ArcGIS GET | **[LIVE 08-12]** service exists | code | MED (billed, not distress by itself; use as enrichment/join) |

Notes: Buncombe S10 CODE stays PARTIAL. Enumerated the county org
(`services6.arcgis.com/VLA0ImJ33zhtGEaP`) and the storm/appraisal org
(`services.arcgis.com/aJ16ENn1AaqdFlqx`): **no** code-enforcement, nuisance,
condemned, unsafe-structure, vacant, or demolition service is published. Asheville
city code/STR (already built) remains the only open code feed; unincorporated
Buncombe code enforcement is FOIA-only (unchanged). S9 LIEN unchanged: Buncombe ROD
is Aumentum reCAPTCHA-walled; the unpaid-bills `mortgage_co`/`loan_num` is a lender
hint, not a recorded lien.

### Henderson NC (matrix 75%; open cells S5 TAXL fa, S9 LIEN fx, S11 EXEM fx)

| Signal | Source | Exact endpoint | Access | Live? | Code/Wiring | Conf |
|---|---|---|---|---|---|---|
| — | No net-new source found | — | — | — | — | — |

Notes: Henderson is already the best-covered of the 5 on the gap signals: S4 via
`nc_ptscloud_delinquent_tax` (NCPTS bulk, 1,513 rows), S10 via
`henderson_code_violations` (156) + `hendersonville_vacant_structures` (50). S11
EXEM confirmed WALL (parcel layer `EXEMPTION_DESC` holds only organizational codes,
per the 08-12 signal probe; PII suppression, FOIA only). S9 LIEN waits on the ROD
lane like everyone else. Nothing new and free to add here.

### Transylvania NC (matrix 63%; open cells S4 TAXD ◐fx, S5 TAXL fa, S9 LIEN fx, S10 CODE fx, S11 EXEM fx)

| Signal | Source | Exact endpoint | Access | Live? | Code/Wiring | Conf |
|---|---|---|---|---|---|---|
| S12 DISP / mailability | Transylvania parcels (owner-mailing enrichment) | `https://gis.transylvaniacounty.org/server/rest/services/Parcels/MapServer` | ArcGIS GET | **[LIVE 08-12]** service catalog live (parcel MapServer); FeatureServer/0 returned a 500, use MapServer layer | code (confirm owner-mailing fields on a layer query) | LOW-MED |

Notes: Full ArcGIS catalog enumerated
(`gis.transylvaniacounty.org/server/rest/services`): only Parcels, Addresses,
zoning, boundaries, ag-district, precincts. **No** tax, delinquent, code, vacant,
condemned, or demolition service exists. S4 TAXD delinquent roll has no open
automated path: `tax.transylvaniacounty.org` bill search returns a zero-length body
(documented), the ArcGIS parcels layer carries no tax-owed field (unlike Polk), and
the Transylvania Times is TNCMS robots-walled. The only free delinquent channel
stays the `ncnotices.com` advertisement subset (statewide lane, already wired).
S10 CODE = FOIA (no open feed). S11 EXEM = FOIA. S9 LIEN via `search.transylvaniadeeds.com`
(disclaimer-gated open index, 1973-present) is already wired through
`nc_rod_logan` (15 rows) — NOT net-new.

### Polk NC (matrix 63%; open cells S4 TAXD ◐fx, S5 TAXL fa, S9 LIEN fx, S10 CODE fx, S11 EXEM fx)

| Signal | Source | Exact endpoint | Access | Live? | Code/Wiring | Conf |
|---|---|---|---|---|---|---|
| S4 TAXD | Polk TaxParcels live tax-owed balance | `https://services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services/TaxParcels/FeatureServer/0/query?where=TOTAL_TAX_OWED>0` | ArcGIS GET | **[LIVE 08-12]** 16,677 rows > 0; fields TMS, OWNAM1-3, OWADR1/OWCITY/OWSTA/OWZIPA, PHYSICAL_STREET_ADDRESS, TOTAL_TAX_OWED, TOTAL_TAX_VALUE, LAND/BUILDING_VALUE, deed book/page | code (new parser) | MED (live balance, not a delinquent flag; query post-Jan-6 and filter to residential/modest amounts to approximate the delinquent roll) |
| S12 DISP / mailability | Polk TaxParcels owner-mailing (owner-vs-situs) | same layer, `outFields=TMS,OWNAM1,OWADR1,OWCITY,OWSTA,OWZIPA,PHYSICAL_STREET_ADDRESS` | ArcGIS GET | **[LIVE 08-12]** distinct mailing block present | code (same parser) | HIGH |

Notes: this single layer is the Polk win — it is the one small-county parcel layer
in the footprint that exposes a live tax-owed balance AND a full owner-mailing block
on an open endpoint. Caveat on S4: `TOTAL_TAX_OWED` is the current on-the-books
balance, so the top rows are high-value institutional parcels with large current
bills, not distress; the delinquent signal is the residual balance on residential
parcels queried after the Jan-6 delinquency date. Validate seasonality before
trusting it as a standalone distress source; it is unimpeachable as a
mailing/absentee enrichment today. Polk's other org services (`Parcels`,
`Environmental_Health`, `PolkPublicData_view`) carry no tax/code data
(`PolkPublicData_view` is just a county-boundary layer). S10 CODE = no open feed
(FOIA). S11 EXEM = FOIA. S9 LIEN: Polk ROD is Cott/CottHosting reCAPTCHA+login
(walled) — no net-new ROD path.

### McDowell NC (matrix 67%; open cells S5 TAXL fa, S9 LIEN fx, S10 CODE fx, S11 EXEM fx)

| Signal | Source | Exact endpoint | Access | Live? | Code/Wiring | Conf |
|---|---|---|---|---|---|---|
| — | No net-new source found | — | — | — | — | — |

Notes: McDowell S4 already wired via `nc_county_pdf_delinquent_tax` (2,247 rows from
the county advertisement PDF) and upset bids via Kania JSON. Its public GIS is the
`webgis.net/nc/McDowell` vendor (Data Consulting), not an open ArcGIS REST org, so
no ArcGIS tax/code enumeration is possible without a per-parcel search — no bulk
open endpoint. S10 CODE = FOIA (no open feed; rural county). S11 EXEM = FOIA. S9
LIEN via `search.mcdowelldeeds.com` (disclaimer-gated open index) is already wired
through `nc_rod_logan` (13 rows) — NOT net-new.

---

## County x signal cells with NO free automated path (walls confirmed this pass)

| County | Signal | Why | Free fallback that does exist |
|---|---|---|---|
| Henderson, McDowell, Polk, Transylvania | S11 EXEM senior/disabled/veteran | parcel GIS suppresses the exclusion (PII); only Buncombe publishes it | FOIA to county tax office (NC G.S. 105-277.1 roll is public record) |
| McDowell, Polk, Transylvania, Buncombe (unincorporated) | S10 CODE enforcement / condemnation / vacant | no open ArcGIS/permit feed published (catalogs enumerated 08-12) | FOIA to county/city code office; `scripts/foia_vacant_demolition.py` scaffold |
| Buncombe, Polk | S9 LIEN mechanic/judgment/federal-tax (recorded liens) | ROD walled: Buncombe = Aumentum reCAPTCHA, Polk = Cott reCAPTCHA+login | none free for these two; McDowell/Transylvania reachable via disclaimer-gated `search.<county>deeds.com` (already wired via `nc_rod_logan`) |
| Transylvania | S4 TAXD full delinquent roll | bill-search returns zero-length body; no tax field on ArcGIS parcels; Transylvania Times TNCMS robots-walled | `ncnotices.com` advertisement subset only (statewide lane, already wired) |

None of these is a true dead end: every cell has at least the FOIA or statewide
newspaper fallback already documented in the master plan. They are recorded so the
next sweep does not re-chase them as if open.

---

## Sources probed this pass (2026-08-12)

- `services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services` (Buncombe billing org) — catalog + `Buncombe_County_All_Property_Bills_Unpaid_from_2024/FeatureServer/0` fields + count (6,231).
- `services1.arcgis.com/23uf7jKvz6SRPFWJ/arcgis/rest/services` (Polk org) — catalog + `TaxParcels/FeatureServer/0` fields + `TOTAL_TAX_OWED>0` count (16,677) + top-5 sample (Columbus/Tryon NC confirmed).
- `gis.transylvaniacounty.org/server/rest/services` — full catalog (no tax/code/vacant service).
- `www.transylvaniacounty.org/departments/tax-administration`, `tax.transylvaniacounty.org` — no delinquent list; sales posted in Transylvania Times only.
- `www.polknc.gov/collection` — no delinquent list online.
- `search.transylvaniadeeds.com`, `search.mcdowelldeeds.com` — disclaimer-gated open ROD, already covered by `nc_rod_logan`.
- SERP checks for McDowell GIS (webgis.net vendor), Polk NC delinquent tax (wrong-state trap: polktaxes.com / polkcountycollector.com are Polk County FLORIDA), Transylvania tax foreclosure.
