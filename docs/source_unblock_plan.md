# Source Unblock Plan

One actionable plan merged from two triage passes (forensic-doc classification of `docs/blocked_sources_forensic.md` + the repo/memory dead-end mining). Deduped to the most specific action per source. Compliance line is fixed: fingerprinting stealth (curl_cffi / StealthyFetcher / camoufox running the page's own JS) and open-API / stale-token reverse-engineering are permitted as compliant public-search; defeating a CAPTCHA, login, WAF bot-check, ToS scraper-prohibition, or spending money is NOT.

Buckets, most valuable first inside each:
1. BUILD_NOW — mine to build + test autonomously (no bypass, no paid).
2. GATHER_THEN_PARSE — human loads/saves in their own browser; I pre-build the offline parser so each drop ingests instantly.
3. LICENSED_OR_FOIA — licensed vendor export / FOIA / NC voter file; I ingest the returned file. PII rows marked.
4. DEAD — unreachable at any price (or covered elsewhere / re-probe transient).

Last updated 2026-07-01.

---

## 1. BUILD_NOW

Mine to build and live-test now. No CAPTCHA/login/WAF/ToS/paid bypass — only open-API discovery, stale-token/handshake re-establishment, key normalization, render passes, timeboxing, and OCR of free images.

| Source | What I'll build | Effort | Risk |
|---|---|---|---|
| **LOGS / Shapiro & Ingle NC foreclosure Power BI feed** (`wabi-us-north-central-h-primary-api.analysis.windows.net`, resourceKey `10e35a6c-…`, modelId 452995) | `querydata` POST (`SemanticQueryDataShapeCommand`) + DSR/DM0 decoder (C/R/Ø bitmask); split `SALE_DATE` inline status ("01/02/25 Cancelled Until 07/21"); Window→~30k for full ~501 rows. Statewide docket, richer than the existing `law_firms.ingle_firm` HTML `Sales.aspx`. | M | Low — open tokenless JSON API; only work is the decoder. **Partial-overlap dedup** with built `ingle_firm.py` (same successor firm) — join on case#/address, keep Power BI as the deeper feed. |
| **Cherokee SC tax balance** (qPayBill/portal) | Parcel-format normalizer (board's 13-digit numeric → portal's dashed), then auto-pull balance. Helper in `enrichment_tax_owed.py` / `enrichment_qpaybill_tax.py`. | S | Low — portal works; pure join-key engineering. |
| **Spartanburg / Greenville / Buncombe / Gaston / Cherokee / Cleveland / Anderson jail bookings** (net-new incarceration lane) | Wire remaining rosters into `enrichment_jail_bookings.py`: Buncombe CentralSquare P2C (`buncombecountyso.policetocitizen.com/api/Inmates/23`, XSRF-token handshake, 540 in custody); Gaston New World Aegis WebForms (`tepsweb.cityofgastonia.com`, `__VIEWSTATE`); Greenville SC LANSA WEBEVENT postback (`app.greenvillecounty.org/cgi-bin/lansaweb` — highest SC jail pop). Age (not DOB) on some → lean on name+age. | M | Low–Med — open JSON / postback handshakes, no login/CAPTCHA. Buncombe live-verified 2026-07-01; Gaston/Greenville need a browser-captured postback sequence. |
| **Kofile / Oconee SC ROD** (`oconee.sc.publicsearch.us`) | Discover the real Typesense/Algolia-style XHR endpoint + payload via network tab (current `/api/search` guess returns non-JSON → `[]`); replace params in `rod/kofile.py` `search_by_name` / `discover_recent_nods`, hit via existing curl_cffi tier. | M | Med — SPA over a bot-protected-but-not-CAPTCHA/login backend. **If the real XHR turns out to be signed/token-gated per-request, it moves to GATHER.** |
| **Aumentum ROD — Buncombe / Gaston** (`registerofdeeds.buncombenc.gov`, `deeds.gastongov.com`) | Re-capture current `__VIEWSTATE`/`__EVENTVALIDATION`/session handshake + `SrchName.aspx`/`SrchDocType.aspx` POST field names live; rebuild `rod/aumentum.py` parser. Unblocks the "ROD off" facets (mechanic liens, distribution deeds, HOA liens). | M | Low–Med — stale-parser rebuild; search has no login/CAPTCHA (reCAPTCHA only gates paid images, per the working sibling `enrichment_gaston_rod.py`). |
| **Post-sale Trustee's Deed sweep (NC deed-stamp → sale price)** | Extend each ROD vendor's `discover_recent_nods()` to also sweep post-sale doc types (`AUMENTUM_POST_SALE_DOC_TYPES` already defined) + capture the consideration column; `rod/deed_stamp.py` + `RodDoc.consideration_amount` are built. Feeds `enrichment_foreclosure_sold_comps` (NC only). | S | Low — builds on tested primitives; **depends on Aumentum/CCHS ROD being back on**, so sequence after the ROD rebuild. |
| **DOT-principal OCR** (loan amount from free ROD image) | New `enrichment_dot_ocr`: render ROD → fetch free `view_image` PDF → OCR page 1 "principal sum of $X". Reuse `enrichment_doc_ocr.py` + `rod/logan_render.py`. Spartanburg Logan images are free (application/pdf, no cart/login). | M | Low — images confirmed free; OCR stack exists. |
| **Spartanburg Logan per-owner + DOT-image OCR** | Keep the per-owner `logan_render.search_by_name_render` path (~25s/owner, capped); wire the free deed-of-trust image → OCR for loan amount. Book alpha suffix uses a dash ("149D"→"149-D"). | S | Low — per-owner render already works; bulk stays server-side-broken (not mine to fix). |
| **SC per-parcel sqft / sale-price cards** (Pickens/Oconee/Charleston) | Per-parcel qPublic CARD scrape (`assessor_cards/*`, curl_cffi chrome, no CAPTCHA) for heated sqft + sale-price history; add a **Charleston ProVal/CAMA adapter** (`sc-charleston.publicaccessnow.com`, IM.aspx→OWS module load) reusing the `assessor_cards/georgetown_sc.py` "Total Finished Living Area" regex — net-new sqft for the ~18% address-less Charleston parcels. + `enrichment_footprint_sqft.py` / `scripts/build_sc_footprints.py` for bulk sqft. | M | Low–Med — per-parcel cards live-verified; Charleston ProVal module load is the one unfinished step. |
| **NC PTS Cloud delinquent-tax — tenant subdomain enumeration** | Enumerate `*.ncptscloud.com` tenant subdomains for remaining in-scope NC counties (Cleveland/Gaston/Polk/Transylvania may live on a PTS subdomain even though their own SPA portals wall); re-poll Rutherford/Burke each cycle (auto-lands when blobs post). Unauthenticated JSON+CSV API. | S | Low — open API; Madison/Henderson already pull ~2,992. |
| **Lincoln NC CCHS ROD (us4/LincolnNC2 MVC install)** | Map the us4 ASP.NET-MVC search flow (distinct from the dead us5 classic-ASP `SearchService.asp`), add Lincoln to `nc_rod_substitute_trustee.py` SOURCES (line 73 explicitly omits it as un-wired). | M | Med — different install than the decommissioned us5; needs live flow mapping. |
| **Lincoln NC delinquent-tax** (`lincolncountytax.com`) | Dedicated parser for the separate platform. **Verify overlap with the existing PDF scraper first — may be marginal.** | S | Low — no wall noted; value gated by dedup. |
| **GovDeals real property — re-key** (`maestro.lqdt1.com`) | Re-extract the live `x-api-key` + payload from the current `main.<hash>.js` Angular bundle; send via curl_cffi `impersonate=chrome` (Akamai layer already solved per `project_govdeals_akamai_bypass`). Update `nc_govdeals_real_property.py` and un-disable. | S | Low — stale-token re-key. **Reconcile:** memory says re-enabled 2026-07-01 but forensic + in-code `disabled_reason` say "dead key" — re-verify live and correct the stale strings. |
| **USDA RD resales** (`scrapers/reo/usda_rd.py`) | Add a per-step timeout / budget-bail to the JSP session 3-step flow and re-enable. It's a perf hang (froze 2h47m under concurrency), not a wall. | S | Low — engineering timebox, pattern per `project_fc_fullrun_hang`. |
| **Fannie HomePath REO re-resolver** | Address→current-`propertyUuid` re-resolver so deep links stay live (bbox search JSON API already works; ~58/1057 uuids rotate stale). Pattern off `enrichment_parcel_lookup.py`. | S | Low — search API confirmed live in-repo. |
| **Sunbelt / Transworld / WeSellRestaurants** (business-scraper) | Add a Scrapling render tier to the broker adapters (HTTP 200 but client-hydrated grid, raw HTML has no price/cash-flow); smoke-test then enable. | S | Low — normal render-tier engineering. |
| **SC DEW UI-tax lien registry** (`uitax.dew.sc.gov`) — **misclassification fix** | None to build — `enrichment_dew_liens.py` already hits the real WCF endpoint (`TaxLienRegistry.svc/SearchTaxLienRegistry`) with the static SecurityKey and pulls ~8,000 SC liens. **Correct the forensic doc's CANT entry.** Optional: enable the `Export_All_Ind="Y"` full-dump path (currently falls back to surname sweep on WCF timeout). | S | Low — already running; low ROI (employer UI-tax liens). |
| **SC civil money judgments — Upstate** (deferred / if-asked) | Extend `sc_public_index_lis_pendens.py` camoufox form-drive with a bounded 60-day CP money-judgment sub-type filter. | S | Low tech / **Rule-610 bulk-use caution + low lead quality → leave deferred unless authorized.** |
| **Reddit MCP wiring** | Config step to wire the Reddit MCP server; interim use `lite.duckduckgo.com site:reddit.com` sequential (per `project_hwm_reddit_intel_tooling`). | S | Low — config, no bypass; **currently non-functional until wired.** |
| **Already done — keep operational (no build):** GSA `/our-listing/` HTML index; Gaston ROD lien-existence (`enrichment_gaston_rod.py`); Column legal-notice API (client-side filter fix); ZLS/Zacchaeus render tier; Crexi MF general channel; SC PublicIndex lis-pendens lane (~233 leads); Aldridge Pite NC (disclaimer-Referer plain GET — **forensic "0 rows" is stale**). | — | — | — |

---

## 2. GATHER_THEN_PARSE

Human-in-the-loop. Operator loads/saves in their own browser (compliant public-search of their own session); I pre-build the offline parser so each drop ingests instantly. No automation against the gated site.

| Source | Your gather recipe (url + settings + file to save) | Parser I'll pre-build | Lane / value |
|---|---|---|---|
| **NC eCourts — Estates** | `portal-nc.tylertech.cloud/Portal/.../29` → Smart Search → Location=`<county>`, Category=Estates, blank name + date range → Ctrl-S results-list HTML to repo root. | Existing `scripts/parse_nc_ecourts_export.py` ingests as-is; no new code. | Probate heirs. Also covered compliantly via Column — gather only for counties Column misses. |
| **NC eCourts — Divorce** | **Check the open Judgment Search JSON lane first** (`enrichment_nc_divorce.py`, per `project_nc_ecourts_endpoint_split` — divorce revived there). If a county isn't covered: same portal → Smart Search → Civil ▸ District ▸ Domestic, blank name + date range → Ctrl-S. | Extend `scripts/parse_nc_ecourts_export.py` to the domestic result table if columns differ. | Divorce distress. JSON lane is preferred; gather is the fallback. |
| **NC eCourts — power-of-sale / SP foreclosure** | Same portal → Smart Search → Special Proceeding / foreclosure category, blank name + date range → save results HTML. | Extend `scripts/parse_nc_ecourts_export.py` with the SP result-row shape. | Foreclosure filings behind the AWS-WAF grid (unsolvable by the vision solver). |
| **SC PublicIndex — broad civil+criminal sweep (6-lane)** | `publicindex.sccourts.org/<County>/PublicIndex/` → accept disclaimer → set Court Type + Case Sub-Type per the 6-lane recipe, Date-Type=Case Filed, name blank → Ctrl-S each. **Do NOT ask me to add new automated lanes** (F5/Shape + ToS scraper-prohibition; existing lis-pendens lane stays frozen, not widened). | Existing `ingest_sc_publicindex_export.py` / `parse_publicindex_export.py` (imports no HTTP client by design). | Broad SC civil-distress; the sanctioned scaled path is manual-save. |
| **SC PublicIndex — Common Pleas / General Sessions rosters** | Same portal RosterSelection.aspx → pick a non-MIE RosterCode (MJURY/MNOJ/PDIA/PDPL/PDSA/PDST/PDTR) → save. Only MO (foreclosure) is scraped today; these civil-distress roster types are exposed but untapped. Manual-save to stay inside the no-new-bypass-lane policy. | Extend `ingest_sc_publicindex_export.py` for the roster-table shape. | Net-new SC civil-distress avenue never tapped. |
| **SC PublicIndex — per-case DETAIL (TMS + judgment $)** | Within the live PublicIndex session, click a case → save the rendered detail page HTML (detail is `__doPostBack`-only, dead in a bulk static save). Operator saves detail for top leads only. | Small detail parser extending `parse_publicindex_export.py` / `enrichment_case_detail.py` to pull TMS + judgment $. | Dollar figure + TMS on priced top leads. |
| **SC SoS entity owner** (`businessfilings.sc.gov`) | Search entity → solve the CAPTCHA in your browser → save the entity detail page. Operator does this per-entity for top leads. | Add a saved-page parser branch in `enrichment_sos_agent.py` (NC path already runs free via stealth). | Entity-owner contact for SC LLC-held parcels (SC is CAPTCHA-gated; NC isn't). |
| **SC LLR contractor roster** (`verify.llronline.com`) | Open in a real (non-headless) Chrome, run the roster search, save/export the 1217-row result (stateless curl_cffi returns 0; session seats only via the full JS click-flow). | Offline parser for the saved roster. FOIA template already at `docs/sc_llr_foia_request.md` as an alternate route. | Contractor/service-source roster; interactive-only gate. |
| **Anderson SC tax balance** (`acpass.andersoncountysc.org`) | Open portal, search parcel, save the balance page. Per-parcel for top leads (bulk is auth-gated 403; no automated login). | Extend `enrichment_tax_owed.py` to ingest an operator-pasted/saved balance. | Taxes-owed on top Anderson leads. |
| **Pickens SC tax balance** | qPublic Pickens per-parcel CARD → balance/sales section (no bulk qPayBill). | Existing `scripts/probe_pickens_card.py` / `assessor_cards/*` per-parcel path. | Taxes-owed + sqft/sales on top Pickens leads. |
| **PropWire export** | Log into your own free PropWire account → run the foreclosure filter → export CSV. Do NOT automate against the site (DataDome + account gate). Skip-trace tier is third-party PII. | Existing `scripts/ingest_contacts.py` (contact_ingest). | Foreclosure inventory from your own account; **PII (skip-trace tier).** |
| **ncnotices.com gated probate body (if ever needed)** | Use ncnotices.com (already scraped) for the list; for one specific top lead, manually view the gated detail body (I Agree + reCAPTCHA) and save it. | Existing ncnotices.com render path; one-off body paste. | Rare — only when a specific lead's PR/DOD is needed. |

---

## 3. LICENSED_OR_FOIA

Data is legally/structurally absent to a free scraper. Route = licensed vendor export, FOIA, or the NC voter file. I ingest the returned file; I never scrape the ban-automation PII sites.

| Source | Data | Route | What I ingest |
|---|---|---|---|
| **Consumer people-search** (TruePeopleSearch/FastPeopleSearch/Radaris/Whitepages) — **PII** | Owner mobile phone | **Never scrape** (Cloudflare + ToS ban). Compliant scaled channel = NC voter file (`enrichment_voter_phone.py`, ~69% phone) + absentee/mailing-mismatch direct mail. Licensed skip-trace export if operator buys one. | NC voter-phone join now; licensed CSV via `scripts/ingest_contacts.py` if purchased. |
| **Forward phone / skip-trace APIs** (batchskiptracing/Spokeo/SearchBug) — **PII** | Owner phone (~$0.22–0.45/hit) | Licensed non-FCRA "locate to transact" API, only if authorized. | CSV via `scripts/ingest_contacts.py`. |
| **Owner email** — **PII** | Owner email | Third-party PII, paid-only. Mail instead; ingest only from a licensed source. | Licensed export only. |
| **Paid data brokers** (PropStream/ATTOM/Regrid-premium/RentCast/NCOALink) — **PII** | Owner contact, mailing, phone | All paid/trial-only; NCOALink $15k+/yr. Free ceiling = GIS mailing + absentee flag (`enrichment_owner_mailing.py`). | Licensed CSV if bought; otherwise the free ceiling only. |
| **OpenCorporates API / NC SoS bulk** | Entity ownership at scale | Paid token / paid data-subscription. Per-profile NC SoS stealth (`enrichment_sos_agent.py`) covers the free need. | Licensed export only; keep per-profile path. |
| **SC Family Court divorce (case-level/bulk)** | Divorce filings | Existing partial FCCMS name-search (`enrichment_sc_divorce.py`); comprehensive = paid UniCourt/Trellis only if authorized. | Licensed export if bought. |
| **NC/SC clerk SP-file debt $** | Power-of-sale debt figure (not online; statute keeps it out of the notice) | FOIA Clerk of Superior Court (NC) / Clerk+MIE (SC); request electronic CSV/Excel. Templates in `docs/foia_court_records.md`. | One-off ingest of the returned file. |
| **Owner mortgage payoff / current loan balance** | Live payoff (servicer-held, mid-month) | Effectively absent. Proxy = judgment/opening-bid $, or OCR the recorded DOT for original principal (`enrichment_doc_ocr.py`, `enrichment_amount_owed.py` cascade). | Proxy only; no ingest. |
| **Spartanburg CAMA FTP + SC bulk CAMA extract** | Bulk SaleAmount + heated sqft (blank on every free SC layer) | Email `Assessor@spartanburgcounty.org` (FTP is SPARTNET IP-firewalled; won't store creds). | One-off ingest into `scripts/build_sc_assessor_cama.py`. |
| **Cherokee SC ROD / Cott RecordRoom (Rutherford/Polk) / AcclaimWeb+Logan document IMAGES (some counties)** | Recorded-image lien $ behind subscriber wall | Paid subscriber account per vendor. Where images are free (Spartanburg Logan) I OCR them; Union via `cott_recordroom.py` already works for named probate. | OCR the free-image counties; licensed access elsewhere. |
| **GBP review_count** | Review count (stripped in unauthenticated context) | Paid Places API/scraper, off-policy. Free alt = YellowPages parser + rating/utm=gbp proxy. | YellowPages parse in the service-source path. |
| **Fannie/Freddie MF REO / CMBS special-servicing (Trepp/CRED-iQ)** | Multifamily REO + distress | Broker-gated / paid subscription. | Licensed export only; Crexi is the free MF source. |
| **LiensNC / code-enforcement / vacant registries / demolition orders** | Code-enforcement + vacancy signals | Mandatory login (LiensNC) / no free feed. FOIA per county; template `scripts/foia_vacant_demolition.py`. | One-off ingest of FOIA response. |
| **Apify Reddit actors / Bright Data / SearchAtlas White Label (sa-2) / SearchAtlas KRT quota (sa-2)** | Reddit intel + agency tooling | Operator actions: fix Apify billing; authorize+fund Bright Data; upgrade sa-2 to Pro; wait for KRT billing-cycle reset or buy quota (`get_quota(service="all")`). | Re-check once operator clears each gate. |

---

## 4. DEAD

Unreachable at any price, structurally absent, decommissioned, or redundant/covered-elsewhere. Some are transient re-probes.

| Source | Why it's unreachable at any price |
|---|---|
| SC deed-stamp → sale price; SC recorded $/sqft comps; SC foreclosure sold comps | §12-24-70: exempt distressed deeds state no value; AcclaimWeb omits consideration. Structurally absent for SC (NC deed-stamp path stays). |
| Universal ~13% explicit-debt ceiling | Debt data not public; free and paid tools hit the same ~13% ceiling. Proxy estimates only. |
| SC magistrate/summary-court eviction rosters (bulk); SC Probate portal | No portal exposes them; magistrate courts county-operated/in-person. Probate = obituaries + Gannett heirs pipeline instead. FOIA is the only eviction route. |
| Buncombe / Charleston deeds SELECT-ALL | Server-side defect — `switchIC()` never populates the instrument-type container, SQL-errors. Harvest CAMA distress from ArcGIS instead. |
| CCHS ROD us5 (Burke/Cleveland/Henderson classic-ASP) | Decommissioned — search endpoints IIS-404, only default.asp survives. (Lincoln's us4 MVC install is BUILD_NOW; the rest need new-provider discovery.) |
| homesales.gov; irsauctions.gov; US Marshals; Foreclosure.com; LoopNet (res/biz/MF); auction.com MF; HUD MF; Hubzu | Decommissioned (HTTP 000) / 403 / hard-WAF / login-gated / structurally empty in-footprint / SPA stub. US Marshals + Foreclosure.com + Hubzu redundant with Bid4Assets/GSA/Zillow/etc. |
| DealStream; BusinessesForSale.com; Murphy Business; Anderson SC business-license roster; Mewborn & DeSelms | DataDome 403 / Cloudflare 403 (do-not-rechase) / 503 (re-probe) / no roster published / Cloudflare (Onslow covered via Column). |
| Korn Law Firm; Rogers Townsend 2nd lane; RAS Crane; Tromberg-Morris-Poulin / Marinosci; Meares; Aldridge Pite (per-firm build); 6 no-list firms | Parked domain (re-probe for rebrand) / Sucuri-walled secondary lane (primary PDFs still deliver) / out-of-footprint (CA/GA/TN/TX) / dead redirect / covered via county MIE rosters. |
| publicnoticesc.com; scpublicnotices.com advanced search; ncpublicnotices.com; per-notice RSS/JSON; legacy.com/echovita/tributearchive | Cloudflare challenge / server 500 (popular-search path works) / NXDOMAIN (use ncnotices.com) / no feed exists / Cloudflare-403 (obituaries via Gannett + funeral-home RSS). |
| reddit.com direct (WebFetch/WebSearch/.json); DuckDuckGo lite/html / Bing / Mojeek | Crawler-blocked / CAPTCHA + rate walls. Use Brave `site:reddit.com` first, DDG-lite sequential as confirm. |
| SearchAtlas PPC connector (Tillmann live) | Holds only stale/paused StoryArc campaigns (acct 67136); read live state via browser at waynseoteam → We Are Your Neon MCC. |
| **Re-probe transient (not truly gone):** Cherokee SC / Spartanburg / Laurens / Union delinquent-tax pages (403 / CivicEngage 404 URL-move / DNS); Pickens delinquent-tax (post-sale-only, keep `_is_post_sale_pdf()` filter); Beaufort SC (WAF + coastal, out of core focus) | Cloudflare 403 / CMS-migration URL drift / DNS failure / no pre-sale list / WAF. Re-discover URL or re-probe each cycle; if a static pre-sale list returns, promote to BUILD_NOW. |

---

## Recommended first sprint

### Top 6 BUILD_NOW to build immediately (highest value × lowest risk)
1. **LOGS / Shapiro & Ingle Power BI feed** — statewide NC foreclosure docket, open tokenless API, decoder is the only work (~1–2h). Biggest net-new volume.
2. **Cherokee SC tax balance (key normalize)** — S effort, unblocks taxes-owed (a documented pipeline gap) on a working portal by fixing a join-key format.
3. **Jail bookings — Buncombe (P2C) + Greenville (LANSA) + Gaston (WebForms)** — net-new incarceration lane; Buncombe is a live-verified open JSON API (540 in custody) buildable today, Greenville is the highest-value SC jail.
4. **Aumentum ROD rebuild (Buncombe/Gaston)** — stale-handshake rebuild that unblocks three downstream facets (mechanic/HOA/distribution liens) AND is the prerequisite for the post-sale Trustee's Deed sweep.
5. **GovDeals re-key + USDA RD timebox** — two quick S wins (stale-token re-key; per-step budget-bail) that flip two disabled REO scrapers back on and reconcile the contradictory `disabled_reason` strings.
6. **SC DEW misclassification fix + Fannie HomePath re-resolver** — DEW is already built (correct the forensic doc, optional full-dump toggle); Fannie needs only an address→uuid re-resolver over a live search API. Both low-risk cleanups.

**Honesty flag:** Kofile/Oconee ROD is listed BUILD_NOW but is the one item most likely to slip to GATHER — if the discovered XHR is per-request signed/token-gated rather than a plain open search endpoint, it becomes a human-gather lane. Validate the network capture before committing build time.

### Top 5 GATHER_THEN_PARSE parsers to pre-build (so the human can start gathering)
1. **NC eCourts export parser** (`parse_nc_ecourts_export.py`) — extend to Estates + Divorce + SP-foreclosure result-row shapes; one parser covers three high-value court lanes behind the unsolvable AWS-WAF grid.
2. **SC PublicIndex export/detail parser** (`ingest_sc_publicindex_export.py` + `parse_publicindex_export.py`) — the 6-lane broad sweep + the per-case detail (TMS + judgment $) + the untapped Common Pleas/General Sessions roster shape.
3. **SC SoS saved-entity parser branch** (`enrichment_sos_agent.py`) — ingest the operator's CAPTCHA-cleared SC entity page; pairs with the already-free NC path.
4. **SC LLR roster parser** — offline parser for the 1217-row saved contractor roster.
5. **PropWire CSV ingest** (`scripts/ingest_contacts.py`) — confirm it cleanly ingests a PropWire foreclosure export (data tier only; skip-trace tier is PII and stays out).
