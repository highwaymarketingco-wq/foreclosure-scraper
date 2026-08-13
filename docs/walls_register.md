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

## Operator-lane workarounds (human-cleared wall → offline parser; compliant)

These stay WALLED to automation but are RETRIEVABLE by a human via the existing
saved-HTML lane (`scripts/ingest_saved.sh` + `scripts/parse_nc_ecourts_export.py`).

- **NC SP (power-of-sale foreclosure) — the 10 NC-Courts-Portal counties** (Brunswick,
  Carteret, Currituck, Dare, New Hanover, Onslow, Pender, Gaston, Lincoln, McDowell):
  operator does ONE mass search instead of name-by-name — NC Courts Portal → Advanced
  Search → Search By = **Case** → Case Number = **`26SP*`** (wildcard year) → filter the
  county → Submit → save the results page → offline parser ingests it. This is the
  method for the SP-foreclosure signal we otherwise lack (Smart Search is WAF-walled to
  scrapers). Verify the parser handles the results-grid format against a real saved page.
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
