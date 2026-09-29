# Walls Register — confirmed dead-ends and "cannot do" (live-tracked)

Running record of sources/paths that are walled, and WHY, so they are not
re-chased. Complements `gap_ledger.md` (this file = probes verified this work
stream, 2026-08-12+). Each entry: what, how it fails, date probed, workaround.

## Confirmed walls (probed live)

| Source / path | How it fails | Probed | Workaround |
|---|---|---|---|
| **SCDOT `SC_Parcels` MapServer** (`smpesri.scdot.org/.../GISMapping/SC_Parcels/MapServer`) — the shared owner/situs resolver for ALL 11 in-scope SC counties | HTTP **200** with body `{"error":{"code":499,"message":"Token Required"}}` on both the service root and any layer query. Silent — looks alive to a status check. | 2026-08-12 | Replace with per-county county-native ArcGIS parcel endpoints (this work stream). |

## SC county-native GIS resolution (SCDOT replacement) — probed live 2026-08-12

**Built + validated (owner+situs resolve live), now in `SC_GIS`:** Spartanburg, Laurens,
Pickens, Colleton, Beaufort, **Georgetown** (split situs via `_GEORGETOWN_CONCAT`, layer 2),
**Charleston** (owner on layer 61, situs PID-joined from Address-Points layer 1 via
`SC_SITUS_JOIN`; validated PID 2861300197 -> '1417 SAINT HUBERT WAY').
**7 of 11 SC in-scope counties restored from the dead SCDOT.**

**WALLED — no free county-native owner+situs path (probed live):**
| County | How it fails |
|---|---|
| **Cherokee SC** | Only qPublic + token-walled SCDOT. The `Cherokee_County_Parcels_` AGO service is Cherokee County GEORGIA, not SC. |
| **Union SC** | County ArcGIS (`unionco.org/unioncomaps`) WAF-403s all programmatic requests; "Tax Parcels" webmap has no parcel layer; viewer is proprietary WTH. |
| **Oconee SC** | `arcserver2.oconeesc.com/.../PARCELDATA_owner` has owner (`current_owner`) but only a MAILING address — NO situs. Owner-only, can't fill property address. |
| **Anderson SC** | `NewPropertyViewer/MapServer/5` has situs (`PHYS_ADDR`)+value+deed but owner (`TAXOWNSTR`) is masked/always-null — cannot resolve by name. |

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
- **NC SP — the 9 legacy VCAP counties** (Buncombe, Burke, Cleveland, Henderson, Hyde,
  Mitchell, Polk, Rutherford, Transylvania): NOT on the portal — courthouse public
  terminal only for the full docket. BUT the trustee's **notice of sale** is legally
  published, so `ncnotices.com` (already wired) covers the sale-stage subset automatically.
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
