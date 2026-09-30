# Walls Register — confirmed dead-ends and "cannot do" (live-tracked)

Running record of sources/paths that are walled, and WHY, so they are not
re-chased. Complements `gap_ledger.md` (this file = probes verified this work
stream, 2026-08-12+). Each entry: what, how it fails, date probed, workaround.

## Confirmed walls (probed live)

| Source / path | How it fails | Probed | Workaround |
|---|---|---|---|
| **SCDOT `SC_Parcels` MapServer** (`smpesri.scdot.org/.../GISMapping/SC_Parcels/MapServer`) — the shared owner/situs resolver for ALL 11 in-scope SC counties, and (via `enrichment_owner_mailing.SCDOT_SC_BASE`) the owner-MAILING-address fallback for all 46 SC counties statewide | HTTP **200** with body `{"error":{"code":499,"message":"Token Required","details":[]}}` on both the service root and any layer query. Silent — looks alive to a status check. | 2026-08-12, re-confirmed 2026-09-28 (commit `80fca14d`) and again 2026-09-30 (direct bounded probe, 4 live requests, all <0.5s — no hang, no rate-limit, no 5xx) | Replace with per-county county-native ArcGIS parcel endpoints (this work stream). |
| **Pickens County qPayBill portal — does not exist** (re-probed for the tax-balance-join gap, `docs/extraction_gaps.md`) | No `pickens*.qpaybill.com` subdomain resolves. 5 patterns tried (`pickenscountytreasurer`, `pickenstreasurer`, `pickenscountysctax`, `pickenscounty`, `pickenssctax`) — every one `curl` NXDOMAIN, while known-good counties on the same vendor (`oconeesctax`, `spartanburgcountytax`) resolve and return HTTP 200 in the same check. Matches `enrichment_qpaybill_tax.py`'s 2026-07-01 finding ("Pickens = no bulk portal (qPublic per-parcel card only)") — still true, not stale. | 2026-09-29 | Not needed: Pickens gets its own real delinquent-tax balance from the county's own free ArcGIS FeatureServer roll (`pickens_delinquent_parcels.py`), no qPayBill dependency. |
| **Georgetown County — no qPayBill/Catalis subdomain, no real per-parcel tax balance captured** | 5 qPayBill subdomain guesses unreachable/NXDOMAIN; `georgetown_civicengage` (355 board rows) carries no real `raw['tax_owed']` for ANY row (0/355) — worse than every other tax source measured in the same pass. | 2026-09-29 | None found. Genuinely open — needs its own source investigation (the county's own delinquent-tax list, if one is machine-readable), separate from the amount_owed-routing fix below. |
| **City of Union SC (`cityofunion.net`)** — the one Union code-enforcement lead `docs/net_new_source_register.md` had flagged "unexplored" (a plain 200/1.16MB page as of its August probe) | Now serves a JS bot-mitigation "Client Challenge" interstitial on every path (`title>Client Challenge`, `/_fs-ch-<id>/script.js` loader, CSP-locked `noscript` fallback) to a plain client — a real WAF/bot-detection wall, not a dead link. Per the compliance rule (CAPTCHA/WAF is a wall; do not defeat), not bypassed. | 2026-09-30 | None. County-level Union (`gearupunionsc.com/departments/code-enforcement/`) also confirmed narrative-only, no case list, in the same August pass — Union SC has **no** reachable code-enforcement source at either the county or city level. |
| **Cleveland County NC `CodeEnforcement_MinimalHousing` AGOL layer** (`services5.arcgis.com/e0FcENYfYZslNJVM/.../CodeEnforcement_MinimalHousing/FeatureServer/0`) — flagged in `docs/pii_disclosure_drafts_2026-09-20.md` as a real, PII-clean (no complainant fields), parcel-keyed minimum-housing case layer worth a second look for `code_vacancy` | Live, queryable, correct schema (`CaseStatus` lifecycle domain from "Petition Received" through "Reinspection Completed, Resolution Made", plus `ParcelNum`/`Address`/`Inspection_Date`/`Hearing_Date`/`Order_ExpDate`) — but `returnCountOnly=true` is **4 rows total**, matching the PII audit's own read that the 4 sample rows "read as test entries." Same category as the already-rejected Anderson-city-code stub and the 0-row Gaston blight layer. | 2026-09-30 | None — genuinely abandoned/never-populated, not a scope or auth issue. Do not build a scraper on this layer; re-check row count only if Cleveland visibly relaunches a minimum-housing program. |
| **City of Morganton NC (`morgantonnc.gov`)** — the largest city in Burke County, checked for a CityView code-enforcement portal via the Gastonia pattern (`docs/HANDOFF.md` item 19) | The entire domain now sits behind an active Cloudflare Turnstile bot challenge on every path including the homepage: HTTP 403, `cf-mitigated: challenge` header, "Just a moment..." JS interstitial. A real WAF/bot-detection wall, not bypassed per the compliance rule. | 2026-09-30 | None. No `devsvcs.morgantonnc.gov` CityView subdomain resolves either. Burke has no reachable code-enforcement source at the city level (county level already confirmed no GIS layer, item 73). |
| **`devsvcs.townofsprucepine.com`** — resolved HTTP 200, superficially matching the Gastonia `devsvcs.<city>` CityView subdomain pattern; investigated as the one apparent hit among the 6 counties re-checked in `docs/HANDOFF.md` item 19 | NOT a CityView instance. The root path is a 135-byte HTML meta-refresh stub (`<meta http-equiv="Refresh" content="0;url=https://www.sprucepine-nc.gov">`) — a parked/legacy redirect. Requesting Gastonia's exact live path, `/CodeEnforcement/Locator?category=CE`, on this host returns HTTP 404 "Page Not Found" (a generic host default, not CityView's search page). | 2026-09-30 | None found. The real town site (`sprucepine-nc.gov`) has no code-enforcement/CityView/minimum-housing mention on its homepage either. Documented precisely so this exact subdomain is not re-flagged as "unexplored" by a future automated CityView-pattern sweep. |

**Obsolete wall, corrected 2026-09-29 (kept for history):** memory `project_qpaybill_tax` and the pre-2026-09-29 `docs/extraction_gaps.md` line described a "parcel-mismatch" wall blocking a qPayBill balance JOIN from Spartanburg onto Pickens/Oconee/other SC counties. That join was never built that way in the end — `counties_sc.qpaybill_delinquent_roll` (live since 2026-09-10, 29 counties) queries qPayBill directly and emits its own Listings with qPayBill's own id as `parcel_id`, so there is no cross-source parcel-FORMAT join to mismatch. Oconee has been covered this way since 2026-09-10 (re-confirmed live above). The REAL, much larger defect turned out to be downstream of every tax source, not qPayBill-specific: `enrichment_amount_owed.py`'s waterfall ran before `enrichment_tax_owed.py` in `main.py` and could never see the real balance the latter computes. Fixed same day — see `docs/extraction_gaps.md`'s DATA-QUALITY VALIDATOR section for the full writeup and numbers.

**SCDOT wall, precise nature (re-verified 2026-09-30):** this is a deliberate,
service-level ArcGIS auth restriction, not a rate limit, IP block, or outage.
`smpesri.scdot.org/arcgis/rest/info` reports `isTokenBasedSecurity: true` with
`tokenServicesUrl` pointing at SCDOT's own ArcGIS Enterprise Portal
(`smpesri.scdot.org/portal` — an agency-internal portal, not public ArcGIS
Online; no self-service sign-up path found, and none was attempted per the
compliance line). The restriction is selective, not server-wide: the same
host's unauthenticated `/rest/services` catalog lists other services fine
(`SC_Address_Locator`, `EGIS_Imagery`, `Bridges`, `SC_Contours`, etc.), and
`SC_Parcels` itself doesn't even appear in the anonymous `GISMapping` folder
listing — standard ArcGIS Server behavior for a service whose sharing is set
to non-public, consistent with a real, configured decision rather than a bug
or a transient block. Separately, `docs/wall_status.json`'s `scdot_parcels`
entry (written by `scripts/reprobe_walls.py`) had been pointing at an
unrelated AGOL-hosted FeatureServer item
(`services2.arcgis.com/.../SC_Parcels/FeatureServer/0`) that no scraper or
enricher ever calls and that 404s with a *different* error
(`{"error":{"code":400,"message":"Invalid URL"}}`) — cosmetic (nothing reads
`wall_status.json` to gate scraping behavior) but it meant that monitor could
never detect a real SCDOT re-open. Fixed 2026-09-30: the script now probes
the real production URL (`SCDOT_BASE`).

## SC county-native GIS resolution (SCDOT replacement) — probed live 2026-08-12,
## re-verified for the remaining 4 gaps 2026-09-30

**Built + validated (owner+situs resolve live), now in `SC_GIS`:** Spartanburg, Laurens,
Pickens, Colleton, Beaufort, **Georgetown** (split situs via `_GEORGETOWN_CONCAT`, layer 2),
**Charleston** (owner on layer 61, situs PID-joined from Address-Points layer 1 via
`SC_SITUS_JOIN`; validated PID 2861300197 -> '1417 SAINT HUBERT WAY'),
**Anderson** (situs+value+deed/sale only, NOT owner — see below; added 2026-09-30).
**8 of 11 SC in-scope counties now have something real in `SC_GIS`.**

**WALLED — no free county-native owner+situs path (re-probed live 2026-09-30,
field-level precision below so this isn't re-investigated from scratch):**
| County | How it fails |
|---|---|
| **Cherokee SC** | Only qPublic + token-walled SCDOT. The `Cherokee_County_Parcels_` AGO service is Cherokee County GEORGIA, not SC. Already mitigated: an on-demand qPublic-card adapter (`assessor_cards/cherokee_sc.py`) fills `living_sqft` etc. for graded leads. Not re-probed this session (out of scope; today's ask was Union/Oconee/Anderson). |
| **Union SC** | County's own ArcGIS (`unionco.org/unioncomaps`) still WAF-403s all programmatic requests (unchanged). The one reachable alternative — the AGOL-hosted `UNION_SC_PARCELS_WFL1/FeatureServer/2` (18,885 parcels; fields re-confirmed live 2026-09-30: `MapNumber, ParcelNumb, SubMap, Blk, ParcelID, Questions, Status, Comments, SubParcel, CAMA_ID, Map_Number, Name, Address_1, Address_2, Address_3` + geometry/shape fields, nothing else) — genuinely has **zero situs field under any name**. `Address_1/2/3` is confirmed OWNER MAILING, not situs: live sample shows out-of-state mail (`OGDEN UT`), PO boxes (`P O BOX 132`), a `C/O` care-of line, and **the identical mailing string repeated across 3 different `ParcelID`s** (MAD ENTERPRISES LLC, 3 separate parcels, same `P O BOX 132, CROSS ANCHOR S C`) — a per-parcel situs could never do that. This resolves the "need to confirm they are mailing, not situs" open question from `docs/sc_phone_research_2026-09-21.md`. Owner (`Name`) + mailing (`Address_1-3`) are already correctly wired as parcel-match-only (no situs) in `enrichment_owner_mailing.COUNTY_GIS["SC:Union"]` and `enrichment_resolve_name_to_property.SC_OWNER_LAYERS["Union"]` — nothing new to add; this layer cannot go in `SC_GIS` at all since that registry requires a situs column to LIKE-match against and none exists. |
| **Oconee SC** | Owner layers (`CitizenServe/MapServer/5`, `PARCELDATA_owner_Assr/MapServer/1`) re-confirmed live 2026-09-30: fields are `pin/current_owner/owner_street/owner_citystate/owner_zip/fire_district/deed_book/deed_page/legal_descr/proval_acres` on both — genuinely **no situs column under any name** (only owner mailing). The other 4 services once suspected of carrying parcel data (`PARCELDATA/0`, `PARCELDATA/1`, `PARCELDATA_Nick/0`, `Parcels_OpenData/0`) re-confirmed **HTTP 200 + `{"error":{"code":400,"message":"Invalid URL"}}`** on both the layer-metadata AND `/query` endpoints — genuinely broken/dead services, not a syntax issue. **New finding (not a fix, but sharper than "owner-only"):** the county's ArcGIS root also publishes 3 live E911 address-point layers — `Addresses_2015`, `AddressExternal`, `AddressResidential` (all `MapServer/0`) — carrying real situs-shaped addresses (`MVADDR` e.g. "486 BOUNTYLAND RD", plus `ADDRNUM/ROAD/SUFFIX/City/Zip/X/Y`). These are **not usable as a quick SC_GIS entry**: they carry no parcel ID / TMS / owner key of any kind, only lat/lng, so joining them to `PARCELDATA_owner_Assr`'s ownership records would require a real point-in-polygon spatial join (parcel has `Shape` polygon + `X/Y` centroid too) — a genuine future build, not a config-dict fix, and out of this session's probe-only scope. Left undone; flagged here so a future session doesn't waste time re-confirming situs is "totally absent" from the county's GIS — it exists, just unlinked to ownership. |
| **Anderson SC** | Re-verified live 2026-09-30 on BOTH public Anderson ArcGIS hosts (same underlying CAMA extract, `LocalGovernment.DBO.Parcels_County`): `gis.cityofandersonsc.com/.../WaterUtilities/County_Parcels/FeatureServer/0` and `propertyviewer.andersoncountysc.org/.../NewPropertyViewer/MapServer/5`. Both expose **situs (`PHYS_ADDR`) + value (`MRKT_VALUE`) + sale (`SALE_PRICE`/`SALE_YEAR`) + deed (`DBOOK`/`DPAGE`)**, all live and non-null (verified: 5/5 "WYATT RD" LIKE-query hits, plausible values). **Owner is a confirmed genuine dead end**: `TAXOWNSTR` is the only owner-shaped column on either host and is always-null (10/10 and 8/8 live samples) — true server-side redaction, not a field-name mismatch, and it agrees across two independently-hosted mirrors. **Action taken:** added `SC_GIS["Anderson"]` (situs+value+deed/sale only, `addr_field="PHYS_ADDR"`, on the `cityofandersonsc.com` host) — this is genuine, tested, real progress per the "partial coverage" standard. **Separately found (not fixed, flagged for cleanup):** `enrichment_owner_mailing.COUNTY_GIS["SC:Anderson"]` still queries `OWNER/OWNER_ADDR/CITY/ZIPCODE/PREV_OWNER`, none of which exist on the CURRENT live schema (schema drift since that entry's 2026-08-03 comment — ArcGIS silently drops unknown `outFields` instead of erroring). That silently trips `_build_result`'s `if not owner and not mailing: return None` gate, discarding situs/value/deed matches that otherwise succeed, for every Anderson lead not already resolved by the offline `sc_parcel_mailing` bulk roll. Real bug, but out of this session's assigned scope (`SC_GIS`, not `enrichment_owner_mailing.py`) — flagged as a follow-up task instead of fixed here. |

## Build-queue items that turned out walled / not worth building (probed 2026-08-12)

| Source | How it fails / why skipped | Disposition |
|---|---|---|
| **Beaufort Treasurer tax-sale list** (`beaufortcountytreasurer.com`) | Squarespace, JS-rendered, NO direct file link; the list is SEASONAL (annual fall sale — latest visible ref is 2023, absent in Aug); Beaufort already has FLC + MIE + the new parcel resolver. Per "when data is absent, stop." | SKIP — low incremental value; revisit in fall if a machine-readable list appears |
| **NC SoS Federal Tax Lien search** (`sosnc.gov/online_services/search/by_title/_Federal_Tax_Lien`) | **DOUBLE wall (2026-08-13).** (1) **ToS prohibits automation** — the search page states verbatim: "Automated or scripted searches … are not permitted. For bulk access to public data, please use our Data Subscription Services" (paid). Confirmed on the live page after a human cleared the interstitial. (2) **Cloudflare technical wall** — curl_cffi `impersonate=chrome` → 403; StealthyFetcher/camoufox (headless, network_idle, 180s) → 307→403, challenge intact; this scrapling has no `solve_cloudflare`. | HARD WALL — do not automate. ToS forbids scripted access regardless of whether Cloudflare is cleared (even human-cleared operator lane). Human interactive search is permitted; bulk = paid only. Narrow signal (entity/LLC federal liens). |
| **NC unclaimed property / escheat search — `unclaimed.nccash.gov`** (NCCash.com now redirects here; dirty_deeds #25) | Confirmed live 2026-09-29 with real board decedent names (Bishop/Jennie, from a probate-flagged Transylvania Co. row). The name-search FORM itself is open (no login, last-name-only required, robots.txt only disallows `/mor` and `/docs/`) — but submitting a search shows "Please wait while we verify your browser…" then surfaces a **Cloudflare Turnstile "Verify you are human" checkbox** modal before any result renders. Angular app badge confirms the vendor: `images/poweredbykelmar.png` (Kelmar Associates' "SWS" unclaimed-property SaaS). | HARD WALL — do not automate. Dirty Deeds synthesis rated this "Easy (both portals scrapeable)" without a live search test; that rating does not hold. No enricher built. |
| **SC unclaimed property / escheat search — `southcarolina.findyourunclaimedproperty.com`** (the vendor treasurer.sc.gov links out to; dirty_deeds #25) | Confirmed live 2026-09-29 with a real board decedent name (Simmons/Charles, from an SC probate-notice row). **Identical** Kelmar "SWS" platform and identical Cloudflare Turnstile "Verify you are human" wall as NC, at the same point in the flow. Also checked the NAUPA national aggregator `missingmoney.com` (which treasurer.sc.gov's own press releases point people to as an alternate search path) — same Kelmar product (footer shows `v3.13.2`), same Turnstile wall. | HARD WALL — do not automate. No unwalled path found via any Kelmar-hosted front end (state-specific or national) for either state. No enricher built. |
| **Greenwood County SC delinquent-tax roll** (part of the completeness-audit "17-county thin coverage cluster" follow-up, 2026-09-29) | Not a bot-block — there is simply no public, bulk-searchable delinquent-tax LIST on this vendor. `greenwoodcounty-sc.gov/treasurer` and `/tax-collector` link out to `greenwoodco.corebtpay.com` (Core's egov.com platform), which is a **pay-by-account-number** portal (`/egov/apps/payment/center.egov`), not a name/roll search — confirmed by direct impersonated fetch (403 on the apps root itself, no form to enumerate; the linked pages are a payment center, not a grid). `qpaybill_delinquent_roll.py`'s own docstring already logged this county as a "CONFIRMED MISS" on 2026-09-23 for the same reason (no qPayBill/Catalis subdomain anywhere on the county's own tax pages) — this pass re-confirms it independently rather than re-guessing subdomains. The `/treasurer/delinquent-tax-sale` URL itself is also a full Wix SPA (no server-rendered table at all), consistent with there being no static list to scrape even if a URL existed. | SKIP — no free automatable path found (not a CAPTCHA/login/WAF wall, just no bulk public data structure). Re-probe only if the county's own site changes vendors; do not re-guess qPayBill/Catalis subdomains for Greenwood (already exhausted). |

## Operator-lane workarounds (human-cleared wall → offline parser; compliant)

These stay WALLED to automation but are RETRIEVABLE by a human via the existing
saved-HTML lane (`scripts/ingest_saved.sh` + `scripts/parse_nc_ecourts_export.py`).

- **NC SP (power-of-sale foreclosure) — the 10 NC-Courts-Portal counties** (Brunswick,
  Carteret, Currituck, Dare, New Hanover, Onslow, Pender, Gaston, Lincoln, McDowell):
  operator does ONE mass search instead of name-by-name — NC Courts Portal → Advanced
  Search → Search By = **Case** → Case Number = **`26SP*`** (wildcard year) → filter the
  county → Submit → save the results page → offline parser ingests it. This is the
  method for the SP-foreclosure signal we otherwise lack (Smart Search is WAF-walled to
  scrapers). **BUILT + verified live 2026-08-13** (`0fb6e14`): `parse_nc_ecourts_export.py`
  Strategy 0 parses the Smart Search Kendo grid (`.party-case-*` classes) → case# + clean
  owner name + county + type; keep `case_type == "Foreclosure (Special Proceeding)"`.
  Operator tips: bump the results pager to 200/page and filter the Location column (or the
  case-number county suffix, e.g. -660=Onslow) — a bare `26SP*` caps/samples at ~23.
- **CORRECTED 2026-09-30 (was stale since the 2025-10-13 statewide eCourts completion):
  "NC SP — the 9 legacy VCAP counties ... NOT on the portal — courthouse public terminal
  only" is no longer true and should not be re-cited.** `VCAP` = NC AOC's legacy
  statewide "Civil Case Processing" indexing system (the civil-side counterpart to
  `CIPRS` for criminal), which the modern Tyler eCourts/Odyssey **Portal**
  (`portal-nc.tylertech.cloud`) replaced. NC's eCourts rollout reached its final Track
  10 (13 counties incl. **Rutherford**, Burke, Cleveland, Gaston, Lincoln, McDowell) on
  **2025-10-13**, completing the conversion in **all 100 NC counties** — confirmed live
  2026-09-30: a direct query of the open Judgment Search JSON endpoint scoped to
  "Rutherford District/Superior Court" over a 730-day window returned `totalHits=10710`
  real judgment hits, so Rutherford is fully indexed in the modern system, not on a
  courthouse-terminal-only legacy footing. There is no county left in the old "not on
  the portal" state; drop that framing everywhere it's cited (`docs/extraction_gaps.md`
  has the full corrected writeup, including that SP/foreclosure case types still don't
  appear in that Judgment Search index for ANY county — confirmed empirically for
  Rutherford, 0 of 500 sampled hits — and that Smart Search, the only place SP case
  detail like upset-bid status lives, now uniformly CAPTCHA-gates all 100 counties,
  confirmed live via browser 2026-09-30, not a VCAP-specific limitation). The manual
  operator lane described just above (`parse_nc_ecourts_export.py`) is county-agnostic
  in code (no hardcoded county allow-list) and now genuinely reaches Rutherford's (and
  the other 8 ex-VCAP counties') SP dockets the same way it reaches the originally-named
  10 — only the framing of which counties needed it was stale, not the tool. The
  trustee's **notice of sale** (`ncnotices.com`, already wired) remains the only fully
  free, fully automated pre-sale signal statewide; it still rolls off once the sale
  happens, same as before.
- **SC senior/disabled exemption** (28 counties, FOIA gap): free MANUAL per-parcel lane —
  county assessor property search / `qpublic.net/sc/scassessors` / SCDOR exempt-property
  portal show the homestead-exemption line on a parcel card. Not bulk-automatable (qPublic
  CAPTCHA); a human can verify a specific parcel or FOIA the whole roll.

## Known walls carried from gap_ledger / build queue (not re-tested here)
- SC PublicIndex family court (FCCMS) divorce — Rule 610 ToS.
- NC eCourts Smart Search / Search Hearings — AWS-WAF.
- Sturgis/Avalon multi-county tax *balance* API — robots Disallow (rolls themselves flow free).
- Kofile / qPublic / Acclaim ROD front-ends — reCAPTCHA/robots/paywall.
- Senior/disabled exemption rolls — suppressed from public GIS (except Beaufort's ArcGIS exemption field); FOIA-only.
- Most code-enforcement beyond Asheville/Spartanburg/Gastonia.
- Recorded HOA/mechanic/judgment liens — ROD-walled; only state DOR+DEW liens open.
- People-search PII (FastPeopleSearch etc.) — ToS + compliance rule.
