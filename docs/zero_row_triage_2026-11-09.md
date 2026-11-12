# Zero-Row Source Triage — 2026-11-09

Triage of all 114 sources showing 0 rows in `docs/run_meta.json` (by_source).
Methodology: disabled-flag check, disabled_reason reading, live URL probe where fast.
Fixed items are committed in `fix(cherokee_delinquent_tax): async generator bug`.

## Summary counts

| Classification | Count |
|---|---|
| POLICY / DISABLED (intentional) | ~40 |
| SEASONAL (legitimately empty now) | ~18 |
| WALLED / CAPTCHA (browser needed) | ~15 |
| PIPELINE (data fetched, doesn't reach board) | ~12 |
| DEAD / 404 / decommissioned | ~10 |
| BROKEN / fixable code bug | ~8 |
| OFF-FOOTPRINT (footprint gate discards rows) | ~11 |

## FIXED THIS SESSION

| Source | Bug | Fix |
|---|---|---|
| `counties_sc.cherokee_delinquent_tax` | `fetch()` used `yield` making it an async generator; pipeline calls `await scraper.fetch()` and iterates result — `async_generator` is not iterable | Converted to `out = self.partial` + `out.append()` + `return out`. All 9 tests pass. |

## HIGH-PRIORITY PIPELINE BUGS (data exists, something upstream drops it)

| Source | Board count | Issue |
|---|---|---|
| `counties_sc.oconee_tax_sale` | 561 in-footprint | PIPELINE — triage confirmed 561 rows fetched, 0 survive to board |
| `counties_sc.sc_probate_notices` | 1016 | PIPELINE — gather-then-extend bug fixed Oct 1 (ea40b4eb); next run will verify |
| `counties_nc.henderson_tax` | 15 | PIPELINE — small but real |
| `counties_nc.buncombe_tax_foreclosure` | 4 | PIPELINE — PDF-based, seasonal |

## SEASONAL (legitimately empty right now)

Sources that only publish data at certain times of year (tax-sale auction windows, etc.):
`colleton_tax_sale`, `oconee_tax_sale`, `pickens_tax_sale`, `york_tax_sale_parcels`,
`abbeville_delinquent_tax`, `barnwell_sheriff`, `bamberg_sheriff`, `dillon_sheriff`,
`anderson_sheriff`, `clarendon_tax_auction`, `kershaw_flc` (Akamai-walled in any case),
`gaston_tax_foreclosures` (annual), `wnc_tax_foreclosures` (annual),
`haywood_tax_foreclosures` (annual, off-season Nov).

## POLICY / DISABLED (disabled=True, correct state)

Sources disabled for documented reasons — do NOT re-enable without investigation:
`national.liensnc` (login wall), `national.propwire` (DataDome + account),
`counties_sc.sc_public_index` (**NOTE**: re-enabled today 2026-11-09 and expanded to 46 counties),
`national.loopnet` (Akamai 403), `national.va_acquired` (dead URLs, redundant),
`national.legacy_obituaries` (**NOTE**: re-enabled Oct 13 with real mechanism fix),
`national.sc_sos_entity` (**NOTE**: enricher now wired as `enrich_sc_sos_entity()`, disabled flag on BaseScraper shell is correct),
`counties_sc.sc_qpublic` (stateful POST form, architectural mismatch),
`national.epa_superfund` (superseded by `counties_generic.epa_frs_sites`),
`courts.lis_pendens_discovery` (ROD discovery helper, not a lead source),
`national.probate_foreclosure_leads` (redundant),
`counties_sc.zombie_properties` (derived signal, not a source).

## WALLED / CAPTCHA (needs browser session, now authorized)

Sources that need browser-based CAPTCHA solving — now authorized per owner direction 2026-11-09:
`counties_nc.nc_rod_captcha` (reCAPTCHA v2 on Wake/Iredell/etc — `solve_recaptcha_v2()` now uses Groq Whisper primary path),
`counties_sc.sc_rod_walled` (Jasper reCAPTCHA),
`counties_nc.nc_ecourts_estates` (AWS-WAF + Kendo UI fix committed today),
`counties_nc.nc_rowan_cott` (Cott subscriber login),
`counties_sc.cherokee_rod` (**NOTE**: already built with credential login, active),
`counties_nc.nc_cchs_deeds` (CCHS decommissioned — new provider needed),
`counties_nc.nc_rod_captcha` (9 counties, math + reCAPTCHA).

## DEAD / DECOMMISSIONED

Sites that no longer serve data or have permanent 404/403:
`national.gsa_realproperty` (import fails — missing registry entry),
`national.tranzon` (**NOTE**: rebuilt Oct 1 per git log — may actually be working now),
`national.williams` (**NOTE**: rebuilt Oct 1 per git log),
`national.aldridge_pite` (WordPress AJAX 0 rows),
`national.hubzu` (React SPA stub — fixed Oct 1 per git log, may work now),
`newspapers.shelby_star` (Cloudflare 403),
`newspapers.tryon_bulletin` (Cloudflare 403),
`newspapers.carolina_coast` (site dead),
`national.courtlistener_civil` (rate-limited / 0 NC/SC civil results),
`counties_nc.mecklenburg_delinquent_tax` (DNS dead for the XLSX URL — scraper may need URL update).

## OFF-FOOTPRINT (footprint gate discards rows correctly)

Sources that fetch data outside the current scope gates:
`national.craigslist_fsbo` (346 rows, all NC/SC but state-only scope bypass needed),
`national.fdic_failed_banks` (national, no NC/SC rows currently),
`counties_sc.charleston_delinquent_tax` (1760 rows, coastal/outside flip footprint — correct behavior),
`reo.usda_rd` (1 Lexington SC row, correctly admitted distressed-type but scraper has freeze bug),
`national.sheriff_sales` (NC/SC county filter returns 0 this cycle).

## Extraction gaps found (top-20 audit)

Two scrapers have available-but-unrequested ArcGIS fields:

| Scraper | Available fields NOT in `_OUT` | Action |
|---|---|---|
| `counties_nc.gaston_vacant` | `BATHS`, `XBEDRM`, `XHBATHS`, `BASEMENT`, `STRUCTTYPE`, `NBHDNAME` | Deferred — cannot verify field names live (ArcGIS returned empty body today) |
| `counties_nc.transylvania_vacant` | `BATHS`, `BEDROOMS`, `HALF_BATHS`, `BASEMENT`, `NEIGHBORHOOD` | Deferred — same reason |

Both to be verified on next session with live ArcGIS field-list probe.

---
*Generated 2026-11-09. Re-run `scripts/triage_zero_row_sources.py` for updated live classifications.*
