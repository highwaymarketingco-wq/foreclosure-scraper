# Road to 100 — Signal-Specific and Coastal-County Alternates

Written 2026-08-12. Scope: close the signals that are concentrated in one county
(senior exemption = 100% Buncombe, code-enforcement = Asheville/Spartanburg only)
and the thinner coastal counties, using FREE + PUBLIC + COMPLIANT sources or
MANUAL-save lanes only. No CAPTCHA solving, no robots-Disallow riding, no
people-search PII.

Every source below was probed live this pass (1-2 GET probes each) or read out
of the existing scraper code. Live-probe results are dated inline.

Style: no em dashes.

---

## Executive summary

Two of the five signal gaps turned out to be **already solved for free** and the
task premise on them is stale:

- **Bankruptcy is not a wall.** CourtListener/RECAP (tokenless, free) is the
  single largest source on the board at 4,215 rows, covering all four footprint
  districts (ncwb, nceb, ncmb, scb). PACER is paid; the free RECAP archive is
  live and wired. Nothing to build. See section 3.
- **Jail bookings already reach Henderson and Gaston.** Both were built
  2026-07-31 (Henderson = Southern Software Citizen Connect, full DOB; Gaston =
  Tyler New World InmateInquiry, full DOB), on top of Buncombe, Cleveland,
  Lincoln, Cherokee SC, Anderson SC. See section 4.

One gap is **harder than the ledger assumed and is largely a data-availability
wall**, verified by probing 9 parcel layers this pass:

- **Senior/disabled/veteran exemption rolls beyond Buncombe do not exist in the
  public parcel GIS.** Buncombe is the outlier. Every other county I probed
  exposes only ORGANIZATIONAL exemptions (government, religious, nonprofit) and
  AGRICULTURAL present-use deferrals, never the elderly/disabled/veteran
  homestead EXCLUSION. The exclusion names a resident's age or disability, so
  counties suppress it. The generic reader returns zero because the field is
  absent, not because of a bug. Free path is FOIA to the county tax office; the
  automated lane is a wall. See section 1.

Two are genuine free BUILD opportunities:

- **Coastal SC probate** via southcarolinaprobate.net (no CAPTCHA, no ToS
  prohibition) already reaches Georgetown, Colleton and Dorchester — all coastal
  and all currently unwired. Only Charleston is live (250). See section 5.
- **Coastal NC delinquent-tax full roll** stays a per-county probe, but three of
  five coastal NC counties already carry partial tax_lien leads.

### Top 5 free sources found this pass

1. **southcarolinaprobate.net — Georgetown / Colleton / Dorchester SC probate**
   (signal: probate/estates; coastal SC). Free, no CAPTCHA, no ToS wall. Same
   platform as the live Charleston feed (`sc_probate_net.py`), just unwired
   counties. Carries decedent + personal-representative MAILING address.
2. **Onslow NC parcel layer DEFERRED/EXEMPT fields** (signal: agricultural
   present-use deferral, NOT senior). 1,469 parcels with deferred value, live
   2026-08-12. A different motivated-seller cut (land owners) than intended, but
   free and property-keyed. Useful as an enrichment/land-lead flag, not a senior
   substitute.
3. **CourtListener/RECAP bankruptcy** (signal: bankruptcy; whole footprint).
   Already built at 4,215 rows; named here because it is the free answer to
   "is there any free bankruptcy coverage" — yes, comprehensively.
4. **Henderson + Gaston jail rosters with full DOB** (signal: incarceration
   skip-trace). Already built; the two highest-population footprint jails that
   publish DOB in full.
5. **County tax-assessor elderly/disabled EXCLUSION roll via FOIA** (signal:
   senior exemption; every county). NC G.S. 105-277.1 exclusion applications are
   public record; they are simply not published online. This is the only
   compliant path to diversify off the 100%-Buncombe concentration, and it is a
   records request, not a scrape.

### Signals that stay hard-walled with no free automated option

- **Senior/disabled/veteran exemption in any county except Buncombe** — the
  parcel GIS does not carry it (PII suppression). FOIA only. (WALL for scraping.)
- **Code-enforcement / condemnation / demolition beyond the six already built**
  (Asheville, Henderson, Hendersonville, Spartanburg county + city, Spartanburg
  vacant) — no free open feed found for Gaston, Cleveland, New Hanover,
  Charleston, Greenville SC, Wilmington. Lives in Accela Citizen Access,
  SeeClickFix (robots-walled) or municipal search portals. FOIA / manual only.
- **NC coastal estates** (Brunswick/Pender/Onslow/Carteret/Dare) — only in NC
  eCourts Smart Search, AWS-WAF walled. Manual save-and-ingest lane only.
- **Horry + Berkeley SC probate** — not on southcarolinaprobate.net; routes back
  to ToS-walled PublicIndex.

---

## 1. Senior / disabled / veteran exemption — the concentration risk

**Current state:** `counties_nc.buncombe_elderly` = 3,548 leads, 100% Buncombe,
~20% of the board on one county's roll. The gap ledger proposed pointing the
generic parcel reader at other counties' ArcGIS layers "that carry the field".

**Finding (probed live 2026-08-12): the field does not exist publicly outside
Buncombe.** Buncombe's `property_bc_dis/MapServer/1` uniquely exposes an
`Exempt` column with the statutory exclusion codes ELD (65+), DIS (disabled),
BLD (blind), VET (disabled veteran). No other footprint parcel layer I probed
carries that. What they carry instead is either organizational full-exemption
codes or agricultural present-use deferral, neither of which is a senior signal.

| County | Layer probed | Exemption-type field | What it actually holds | Senior signal? |
|---|---|---|---|---|
| Buncombe NC | `gis.buncombecounty.org/.../property_bc_dis/MapServer/1` | `Exempt` | **ELD / DIS / BLD / VET** | **YES (the only one)** |
| Gaston NC | `gis.gastoncountync.gov/.../Parcels/FeatureServer/11` | `EXEMPT_COD` | GOV, REL, CLMI, UTL, HIS, EDNG, POL, CEM (organizational) | no |
| Henderson NC | `gisweb.hendersoncountync.gov/.../Parcels/FeatureServer/0` | `EXEMPTION_DESC` | "NONPRO HOME OWNERS", "Govern-Fed,St,Local", "Religous", "PUBLIC SERVICE" (organizational) | no |
| Onslow NC | `maps.onslowcountync.gov/.../MapServer/7` | `DEFERREDVALUE`, `TOTALEXEMPTIONS` | 1,469 parcels deferred, all `LANDUSEFLAG='U'` = present-use agricultural | no (ag) |
| Lincoln NC | `arcgisserver.lincolncountync.gov/.../MapServer/0` | `LANDEFERRED` | land present-use deferral | no (ag) |
| McDowell NC | `services9.arcgis.com/ETP7IuCigkUz7iI9/.../McDowell_Parcels/0` | none | no exemption field | no |
| Cleveland NC | `gis.clevelandcounty.com/.../Basemap/Parcels/MapServer/0` | none | no exemption field | no |
| Polk NC | `services1.arcgis.com/23uf7jKvz6SRPFWJ/.../TaxParcels/0` | none | no exemption field | no |
| Carteret / Brunswick / Pender NC | (coastal parcel layers) | none | no exemption field | no |
| Mecklenburg NC | `meckgis.mecklenburgcountync.gov/.../FeatureServer/0` | none | no exemption field | no |

**Why:** the elderly/disabled/veteran exclusion is tied to a named individual's
age or disability status, so it is PII-adjacent. Most counties deliberately omit
it from the public parcel service. Buncombe publishing it is the anomaly, not the
norm. Chasing it county-by-county in GIS will keep returning zero.

**Compliant paths:**

- **FOIA / public-records request (the real answer).** NC G.S. 105-277.1
  (elderly/disabled exclusion) and 105-277.1C (disabled-veteran exclusion)
  applications and approvals are public record at the county tax office. Request
  the "elderly/disabled homestead exclusion roll" or "tax relief roll" per
  county. This is a records request, not a scrape. Status: MANUAL/FOIA lane,
  scaffold exists conceptually alongside `scripts/foia_vacant_demolition.py`.
- **Do not diversify by chasing this field.** Treat Buncombe elderly as a
  Buncombe-specific asset. Reduce the 20% concentration risk by GROWING OTHER
  signals (probate, tax, foreclosure, jail) in other counties, which is already
  the direction of every other item here. The concentration shrinks as the
  denominator grows.

Access method for the one that works (Buncombe): open ArcGIS REST query,
`where=Exempt IN ('ELD','DIS','BLD','VET')`, no auth. **Live/confirmed: YES**
(the running scraper). All other counties: **confirmed ABSENT 2026-08-12.**

---

## 2. Code enforcement / condemnation / vacant / demolition

**Current state (already built):** Asheville code-enforcement, Asheville STR
permits (640), Henderson code violations (156), Hendersonville vacant structures
(50), Spartanburg county vacant (3,310), Spartanburg county condemned (1,658),
Spartanburg city condemned (90). All ArcGIS-backed.

**Finding (probed live 2026-08-12):** no additional free open code-enforcement
feed found for the counties that lack one. Probed and came up empty:

| County / city | Probe | Result |
|---|---|---|
| New Hanover NC | `gis.nhcgov.com/server/rest/services` filtered for code/violation/condemn/demo | none |
| Gaston NC | `gis.gastoncountync.gov/publicgis/rest/services` | no code-enforcement service published |
| Charleston SC | `gisportal.charleston-sc.gov` + `gis.charlestoncounty.org` | no reachable open code layer |
| Greenville SC | `gcgis.org/arcgis/rest/services` folders | StormWater/Utilities/PavementMgmt only, no code |
| Wilmington NC | city site | code cases not in an open feed |

Code enforcement in these counties lives in **Accela Citizen Access**,
**SeeClickFix** (robots-Disallows ClaudeBot per `blocked_sources_forensic.md`),
or a municipal permit-search portal that requires a per-case search. None is a
free bulk feed.

**Note on a false lead:** Gaston's parcel layer has a `VacantImpro` field, but
it is Vacant-LAND vs has-a-building (probed: {Improved, Vacant}), not
abandoned/distressed structure. Not the code-enforcement signal.

**Compliant path:** FOIA to each city/county code-enforcement or building
department for the active-violations, condemnation and demolition lists.
`scripts/foia_vacant_demolition.py` is the existing scaffold for this lane.
Status: **broader code-enforcement stays a WALL for free automated feeds;**
MANUAL/FOIA only, consistent with the gap ledger.

---

## 3. Bankruptcy — free coverage confirmed, not a wall

**Answer to "is there any free footprint coverage": yes, comprehensively.**

`national.courtlistener_bankruptcy` reads the CourtListener/RECAP archive
tokenless and free: `GET courtlistener.com/api/rest/v4/search/?type=r`. It is the
**largest single source on the board at 4,215 rows** and spans all four
footprint districts: ncwb, nceb, ncmb, scb. PACER itself is paid; the free RECAP
mirror is the compliant alternate and it is already wired.

- Signal filled: bankruptcy (Ch. 7/11/13, plus 363 real-property sales via the
  Schedules doc).
- Counties covered: whole footprint (district-level, resolved to county via the
  debtor's Schedules property address).
- Access method: open REST, no key.
- **Live/confirmed: YES.**

Nothing to build. The only open items are the three code fixes already listed in
`gap_ledger.md` section 2.7 (add ncmb, use the keyless `/search/` path, read the
party+Schedules address).

---

## 4. Jail bookings — already expanded; remaining candidates

**Current state (built):** `national.jail_bookings` covers Buncombe NC
(CentralSquare P2C), Cleveland NC (P2C jqGrid), Lincoln NC (CentralSquare
jqGrid), **Henderson NC (Southern Software Citizen Connect, full DOB on
182/182), Gaston NC (Tyler New World InmateInquiry, full DOB on 695/695)**,
Cherokee SC + Anderson SC (Zuercher). Henderson and Gaston were added
2026-07-31, so the task premise ("expand to Henderson, Gaston") is already met.

- Signal filled: incarceration (name + booking date + charge + DOB where
  published). DOB is the skip-trace lift.
- Access method: each vendor's own public JSON/HTML XHR, no auth/CAPTCHA;
  robots checked and fail-closed.
- **Live/confirmed: YES.**

**Excluded per instruction:** Cherokee/Anderson SC were named as
robots-disallowed, but the built module reaches them via the **Zuercher Portal
JSON API** (a different host from any robots-walled page), and they are producing
(2 leads Anderson). Left as-is; not re-touched.

**Remaining free candidates (not yet built, lower priority):** Spartanburg SC
jail host is offline (documented in the module), no substitute. No open
JSON roster found for the coastal counties this pass. Rutherford / Burke / Polk /
Transylvania NC were not probed for a vendor tenant this pass and are the next
place to look if jail coverage is widened.

---

## 5. Probate / estates for coastal counties

### Coastal SC — a free BUILD opportunity

southcarolinaprobate.net (the aggregator behind the live Charleston feed) has
**no robots.txt, no CAPTCHA and no ToS prohibition** (confirmed in the discovery
sweep and re-read 2026-08-12). Its county dropdown includes these COASTAL
counties that are currently unwired:

- **Georgetown SC** (coastal, in footprint) — not producing today
- **Colleton SC** (coastal, in footprint) — not producing today
- **Dorchester SC** (Charleston metro, coastal) — not producing today
- Charleston SC — **live, 250 leads** (`sc_probate_net.py`)

**NOT covered by the aggregator:** Horry SC and Berkeley SC (both coastal). They
run their own probate courts that route back to `publicindex.sccourts.org`,
which is ToS-walled. Manual save-and-ingest only.

- Signal filled: probate/estates, with decedent + personal-representative
  MAILING address (the thinnest field in the engine).
- Access method: extend `sc_probate_net.py` to the Georgetown/Colleton/
  Dorchester dropdown values; same surname-sweep code, no new pattern.
- **Live/confirmed: platform live 2026-08-12; the three counties are UNWIRED,
  not blocked.** BUILD_NOW candidate.

Caveat: also carried are Barnwell, Bamberg, Aiken, Chester, Kershaw, Lancaster,
Marlboro, Orangeburg, Saluda, Sumter, Florence (Florence is Pee Dee, near-coastal)
if the footprint ever widens.

### Coastal NC — manual lane only

Estates for Brunswick, Pender, Onslow, Carteret and Dare NC live only in NC
eCourts Smart Search, which is AWS-WAF walled (escalating image CAPTCHA). No
open-JSON backdoor (the Judgment Search JSON that serves lis-pendens and divorce
does not carry estates). Free signals that DO reach these counties:

- **Column legal-notice API** (`column_legal_notices`) — creditor/estate notices.
- **Gannett obituaries + funeral-home RSS** — death signal to the heir-parcel
  name index.
- **`nc_heir_estate_parcels`** — GIS owner-name sweep for "HEIRS"/"ESTATE OF"
  retitled parcels (already runs the coastal county layers).

Manual path: operator solves the eCourts human-check in a browser, saves the
Smart Search estates result page, feeds `scripts/parse_nc_ecourts_export.py`.
Status: **estates automation = WALL; obituary + heir-parcel + Column = partial
free coverage; manual save-and-ingest for the docket itself.**

---

## 6. Per-coastal-county 12-signal checklist

Signals: (1) foreclosure (2) pre-foreclosure/lis-pendens (3) sale rosters +
upset bids (4) tax delinquency (5) tax liens (6) probate/estates (7) divorce
(8) bankruptcy (9) liens (10) code-enforcement/vacant (11) senior exemption
(12) absentee/cash-buyer.

Legend: **Y** = free source live/wired · **~** = partial or manual-lane free ·
**GAP+** = free source exists, just needs wiring (build) · **W** = wall, no free
automated path · **FOIA** = records-request lane only.

### Brunswick NC (coastal, 66 leads)
| # | Signal | State | Free/manual lane |
|---|---|---|---|
| 1 | foreclosure | ~ | law-firm feeds (Hutchens/Brock) + NC upset-bid; county roster thin |
| 2 | lis-pendens | Y | NC eCourts Judgment JSON (122 leads, top coastal county) |
| 3 | sale rosters/upset | ~ | `nc_upset_bids` statewide |
| 4 | tax delinquency | GAP+ | probe Brunswick for a PTS `bcpwa` tenant or self-host PDF (coastal, low pri) |
| 5 | tax liens | ~ | rides delinquent roll once #4 lands |
| 6 | probate/estates | ~ | Column + obits + heir-parcel; docket = eCourts wall |
| 7 | divorce | GAP+ | add FAM-Divorce to NC Judgment JSON (statewide fix) |
| 8 | bankruptcy | Y | CourtListener/RECAP (nceb) |
| 9 | liens | ~ | ROD index (no free coastal ROD wired yet) |
| 10 | code-enf/vacant | W | no free feed; FOIA |
| 11 | senior exemption | W | parcel layer has no exclusion field; FOIA |
| 12 | absentee/cash-buyer | ~ | `cash_buyer_deeds` pattern + parcel owner-vs-situs mismatch |

### Pender NC (coastal, 12 leads)
| # | Signal | State | Lane |
|---|---|---|---|
| 1 foreclosure | ~ | law-firm + upset-bid statewide |
| 2 lis-pendens | Y | NC eCourts Judgment JSON |
| 3 sale/upset | ~ | `nc_upset_bids` |
| 4 tax delinquency | ~ | tax_lien already flowing (6); full roll = PTS probe |
| 5 tax liens | ~ | partial live |
| 6 probate | ~ | Column + obits + heir-parcel; docket wall |
| 7 divorce | GAP+ | FAM-Divorce config add |
| 8 bankruptcy | Y | RECAP (nceb) |
| 9 liens | ~ | ROD not wired |
| 10 code-enf/vacant | W | FOIA |
| 11 senior exemption | W | Pender parcel layer has no exclusion field (probed) |
| 12 absentee/cash | ~ | owner-vs-situs mismatch |

### Onslow NC (coastal, 50 leads)
| # | Signal | State | Lane |
|---|---|---|---|
| 1 foreclosure | ~ | distressed + law-firm |
| 2 lis-pendens | Y | NC eCourts Judgment JSON (83 leads) |
| 3 sale/upset | ~ | `nc_upset_bids` |
| 4 tax delinquency | ~ | tax_lien flowing (10); full roll = PTS probe |
| 5 tax liens | ~ | partial live |
| 6 probate | ~ | Column + obits + heir-parcel (5 probate leads) |
| 7 divorce | GAP+ | FAM-Divorce config add |
| 8 bankruptcy | Y | RECAP (nceb) |
| 9 liens | ~ | ROD not wired |
| 10 code-enf/vacant | W | FOIA |
| 11 senior exemption | W | parcel layer has DEFERREDVALUE but it is AGRICULTURAL (probed); no senior field |
| 12 absentee/cash | ~ | Onslow parcel owner-vs-situs |

### Carteret NC (coastal, 10 leads)
| # | Signal | State | Lane |
|---|---|---|---|
| 1 foreclosure | ~ | distressed (2 foreclosure leads) |
| 2 lis-pendens | Y | NC eCourts Judgment JSON |
| 3 sale/upset | ~ | `nc_upset_bids`; `carolina_coast` RSS (2 leads) |
| 4 tax delinquency | GAP+ | PTS tenant probe pending |
| 5 tax liens | GAP+ | with #4 |
| 6 probate | ~ | Column + obits; docket wall |
| 7 divorce | GAP+ | FAM-Divorce config add |
| 8 bankruptcy | Y | RECAP (nceb) |
| 9 liens | ~ | ROD not wired |
| 10 code-enf/vacant | W | FOIA |
| 11 senior exemption | W | Carteret parcel layer has NO exemption field (probed) |
| 12 absentee/cash | ~ | owner-vs-situs |

### Dare NC (coastal, 13 leads)
| # | Signal | State | Lane |
|---|---|---|---|
| 1 foreclosure | ~ | 4 foreclosure leads; `coastland_times` RSS (1) |
| 2 lis-pendens | Y | NC eCourts Judgment JSON (3) |
| 3 sale/upset | ~ | `nc_upset_bids` |
| 4 tax delinquency | ~ | tax_lien flowing (3); full roll probe |
| 5 tax liens | ~ | partial live |
| 6 probate | ~ | Column + obits (3 probate leads) |
| 7 divorce | GAP+ | FAM-Divorce config add |
| 8 bankruptcy | Y | RECAP (nceb) |
| 9 liens | ~ | ROD not wired; Dare parcel = GeoServer WFS, address gap |
| 10 code-enf/vacant | W | FOIA |
| 11 senior exemption | W | no exclusion field |
| 12 absentee/cash | ~ | owner-vs-situs (high second-home rate here) |

### Charleston SC (coastal, 312 leads)
| # | Signal | State | Lane |
|---|---|---|---|
| 1 foreclosure | Y | `charleston_mie` master-in-equity roster (60) |
| 2 lis-pendens | ~ | SC PublicIndex LP = ToS wall; manual save-ingest |
| 3 sale/upset | Y | MIE rosters (SC has 1-yr redemption, no upset) |
| 4 tax delinquency | ~ | `charleston_delinquent_tax` (balance in list PDF); currently 0-row, re-check |
| 5 tax liens | Y | SC state tax lien join (5) + FLC |
| 6 probate | Y | `sc_probate_net` (250, +PR mailing) |
| 7 divorce | W | SC Family Court not on public portal; manual |
| 8 bankruptcy | Y | RECAP (scb) |
| 9 liens | ~ | HOA parsed (2); broader ROD blocked on rebuild |
| 10 code-enf/vacant | W | Charleston open GIS not reachable this pass; FOIA |
| 11 senior exemption | W | no exclusion field; FOIA |
| 12 absentee/cash | ~ | high-value 2nd-home market; owner-vs-situs + cash-deed |

### Georgetown SC (coastal, 396 leads)
| # | Signal | State | Lane |
|---|---|---|---|
| 1 foreclosure | ~ | FLC + law-firm |
| 2 lis-pendens | ~ | PublicIndex wall; manual |
| 3 sale/upset | ~ | FLC list |
| 4 tax delinquency | Y | list AUTO (`georgetown_civicengage`, 408); balance per-parcel manual |
| 5 tax liens | Y | SC state tax lien + FLC |
| 6 probate | **GAP+** | **southcarolinaprobate.net Georgetown dropdown — free, unwired (build)** |
| 7 divorce | W | SC Family Court; manual |
| 8 bankruptcy | Y | RECAP (scb) |
| 9 liens | ~ | georgetowndeeds.com Online Record System honours date window + carries Amount (enricher built, not wired as lead source) |
| 10 code-enf/vacant | W | FOIA |
| 11 senior exemption | W | SCDOT parcel token-walled; no exclusion field; FOIA |
| 12 absentee/cash | ~ | owner-vs-situs |

### Horry SC (coastal, 45 leads)
| # | Signal | State | Lane |
|---|---|---|---|
| 1 foreclosure | Y | `horry_flc` FLC xlsx (23) |
| 2 lis-pendens | ~ | PublicIndex wall; manual |
| 3 sale/upset | Y | FLC list |
| 4 tax delinquency | Y | balance in FLC xlsx (year-stamped URL) |
| 5 tax liens | Y | SC state tax lien (14, top county) + FLC |
| 6 probate | W | NOT on southcarolinaprobate.net; PublicIndex wall; manual |
| 7 divorce | W | SC Family Court; manual |
| 8 bankruptcy | Y | RECAP (scb) |
| 9 liens | ~ | ROD not wired |
| 10 code-enf/vacant | W | FOIA |
| 11 senior exemption | W | no exclusion field; FOIA |
| 12 absentee/cash | ~ | very high 2nd-home/investor rate; owner-vs-situs |

### Colleton SC (coastal, 1 lead)
| # | Signal | State | Lane |
|---|---|---|---|
| 1 foreclosure | ~ | FLC + law-firm |
| 2 lis-pendens | ~ | PublicIndex wall; manual |
| 3 sale/upset | ~ | FLC |
| 4 tax delinquency | ~ | `colleton_tax_sale` built, 0-row; treasurer per-parcel |
| 5 tax liens | ~ | SC state tax lien join |
| 6 probate | **GAP+** | **southcarolinaprobate.net Colleton dropdown — free, unwired (build)** |
| 7 divorce | W | SC Family Court; manual |
| 8 bankruptcy | Y | RECAP (scb) |
| 9 liens | ~ | colletondeeds.com ignores date window (returns whole index head) — refused; ROD not usable for fresh |
| 10 code-enf/vacant | W | FOIA |
| 11 senior exemption | W | no exclusion field; FOIA |
| 12 absentee/cash | ~ | owner-vs-situs |

**Coastal takeaways:**
- The one free BUILD that touches multiple coastal counties is **SC probate
  (Georgetown, Colleton, Dorchester)** — same code as the live Charleston feed.
- **Divorce (all coastal) closes for free in NC only**, via the FAM-Divorce
  config add to the NC Judgment JSON already scheduled in the gap ledger. SC
  coastal divorce stays a wall (Family Court off-portal).
- **Senior exemption is a wall in every coastal county** — none exposes the
  exclusion field (probed Onslow, Carteret, Brunswick, Pender; SC via
  token-walled SCDOT). FOIA only.
- **Code-enforcement is a wall in every coastal county** — no free feed found.
- **Bankruptcy is free-covered in every coastal county** via RECAP.

---

## Sources for this pass

All ArcGIS field probes run 2026-08-12 with `?f=json` metadata + bounded sample
queries (no bulk pull). southcarolinaprobate.net county list read from the search
page. Built-source facts read from `src/foreclosure_scraper/scrapers/national/
jail_bookings.py`, `.../counties_nc/buncombe_elderly.py`,
`.../enrichment_arcgis.py`, and the source register.
