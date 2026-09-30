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
