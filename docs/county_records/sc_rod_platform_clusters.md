# SC register of deeds: counties by platform, what a script reads, where a person is needed

Built 2026-10-07 from `county_records_matrix.json` (45 SC counties; McCormick is missing from the
matrix) plus live checks the same day. Every check was read-only and polite (at least 1.6 s between
requests to one host, one request at a time, an ordinary browser User-Agent). No CAPTCHA, login,
paywall or bot check was touched; where one stands, the county is in the person-needed list below.

What the attorney needs per listing, and what the adapters return (`chain()`, the shared
`raw['rod_chain']` shape, same keys as `rod/nc_chain.py`):

* lien existence: mortgages (`liens.deeds_of_trust`, kind `mortgage`; SC uses mortgages), satisfactions,
  lis pendens, foreclosure notices and other liens (judgments, tax, mechanics, HOA) that name the owner,
  each with book/page, date, type, grantor, grantee; an estimate of mortgages still open since the last deed;
* the deed chain: the last deed into the owner and up to 3 earlier deeds, each with book/page, recording
  date, type, grantor, grantee and the index's short description, walked back by grantor name.

A name index matches names, not parcels: a namesake can appear, so every result carries that caveat.

## Platforms ranked by counties unlocked

Counted over the SC counties whose register is open or behind a plain disclaimer click and has a free
name search. "Before" is the repo on the morning of 2026-10-07.

| rank | platform | counties | before | now (adapter, flag, default) |
|---|---|---|---|---|
| 1 | Online Record System (NameSearch / NamePick / NameDisplay) | Abbeville, Barnwell, Berkeley, Colleton, Dorchester, Florence, Georgetown, Laurens, Lancaster, York (10) | 8 read for lien rows only, no chain, and 5 of those 8 returned nothing (the http bug below); Laurens and Lancaster not read | all 10 with chain: `rod/sc_online_record_system.py`, `FORECLOSURE_SC_ORS_ROD`, OFF |
| 2 | GovOS (Kofile) PublicSearch | Greenville, Oconee (2) | Oconee lien rows (`rod/kofile.py`); Greenville not read | both with chain: `rod/publicsearch.py`, `FORECLOSURE_SC_PUBLICSEARCH_ROD`, ON (Greenville in the lien registry, Oconee chain-only) |
| 3 | Harris AcclaimWeb | Horry, Pickens (2; Clarendon is walled) | Pickens: recent-recordings distress sweep only; Horry not read | both by owner name with chain: `rod/acclaim_names.py`, `FORECLOSURE_SC_ACCLAIM_ROD`, ON |
| 4 | ACPASS (county-built) | Anderson (1; index ends 2026-02-20) | power-of-attorney and court-order type sweep only | by owner name with chain and the gap flag: `rod/anderson_acpass_rod.py`, `FORECLOSURE_SC_ACPASS_ROD`, OFF |
| 5 | Logan 'The Lookup' (render) | Spartanburg (1) | lien existence by render (`enrichment_spartanburg_rod.py`) | unchanged; a `chain()` on top of `rod/logan_render.py` is the next step |
| 6 | Cott RecordRoom | Union (1) | recent-recordings sweep (`rod/cott_recordroom.py`) | not built (one county) |
| 7 | Cott eSearch (guest) | Marlboro (1) | not read | not built (one county; images paid) |
| 8 | County-built document search | Greenwood (1), Charleston (1) | not read | not built (one county each; Greenwood is the best free index in SC, deeds to 1897) |
| 9 | GovOS CountyFusion (guest click) | Sumter (1) | not read | not built (one county; Lexington's tenant needs an account) |

Defaults come from a yield check on four real board owners per platform (chain run, counts kept only):
PublicSearch Greenville 4 of 4 chains at about 15 s a lookup, Oconee 2 of 4; AcclaimWeb Horry 4 of 4 owners
found, 2 with a deed; Online Record System Laurens 2 of 4, one lookup took 200 s; ACPASS Anderson 1 of 4.

Board leads in the counties now read (owner name present, 2026-10-07): Horry 6,442; Greenville 5,257;
Pickens 5,124; Oconee 3,401; Laurens 2,925; Berkeley 2,786; Anderson 2,709; Florence 2,095; Colleton 1,711;
Dorchester 1,712; Barnwell 1,222; Lancaster 1,169; Georgetown 818; York 803 (Abbeville not counted).

## Findings from the live checks

* **Online Record System over http drops the search.** Five hosts are published as `http://` and answer
  the NamePick POST with a 302 to `https://`; the client follows it as a GET without the form, and the
  register lists the first 2,000 names of the whole index whatever name was typed. That is why
  `enrichment_rod_name_index.DATE_FILTER` recorded Abbeville, Berkeley, Colleton, Dorchester and Florence
  as "ignores the date window", and why its name lookups there always hit the 2,000 cap and returned
  nothing. Both modules now use https; over https Abbeville honoured a September window. The DATE_FILTER
  values stay False (bulk sweep refused) until each is re-measured.
* **Online Record System sides.** `tor_last_name` with `search_each=on` searches either side;
  `tee_last_name` is the grantee side. The display page carries a sortable table with explicit Grantor
  and Grantee columns, so no second request is needed for the other party.
* **PublicSearch ordering.** Without `sort=desc, sortBy=recordedDate` Oconee answers in no date order,
  so the last deed can fall off the first page; the adapter asks newest first. A one-role search keeps
  the query key `parties` with `{"grantee": [...]}` inside; a top-level `grantee` key is silently ignored
  and returns every document in the window.
* **ACPASS is a browse, and people are 'LAST, FIRST'.** The name box lists the index from the typed name
  onward. Typed "SMITH JOHN" it starts after every "SMITH, ..." person; typed "SMITH, JOHN" it lands on
  them. Rows show the matched party, its role (grantor, grantee, mortgagor, ...) and the type; the other
  party of a deed comes from its detail page.
* **Pickens files non-conveyances under 'DEED ...' labels** (DEED EASEMENT, DEED NOTICE, ...). Only its
  conveyance codes (DEED, D/DIST, D/FORECLOSE, D/PER REP, D/DEV, D/NO FEE, D/EXEMPT, D/INDENT, D/TRANS)
  count as deeds in the chain.
* **SC lis pendens are mostly court filings.** Horry indexes NOTICE OF FORECLOSURE and LIS PENDENS in the
  register; Pickens and Oconee have no lis pendens type. The court side is the SC Public Index, which
  forbids automated querying (left to a person).

## Anderson after 2026-02-20 (the gap)

ACPASS holds 7/1/1974 to 2/20/2026. Since 2/21/2026 Anderson records in Ingenuity 'Online Services'
(sc.ingcountyapps.com/anderson_rod). Its terms ban bots (a terms-only limit the attorney cleared), so the
site was opened once to see whether a script may read it. It may not: every page loads
`Scripts/botdetect.js`, which grades the browser (webdriver flag, headless user agent, no languages, a
tampered eval) and posts the verdict in a hidden field (`ctl00$hdnBotResult`) before the land-record
lookup is offered, and the site says it monitors for automated use. A script that filled that field
itself would be defeating a bot check, so nothing reads it.

What the adapter does instead: every Anderson chain result carries `index_through: 2026-02-20` and an
`after_index` block naming the site and the reason a person is needed. Given a parcel id
(`chain(..., parcel_id=TMS)`), it reads the county parcel layer's current deed reference (DBOOK, DPAGE,
SALE_YEAR, explicit fields only, through `drop_sensitive`) and sets `after_index.newer_deed_likely` when
that deed is from 2026 and is not the last deed ACPASS shows: a person then reads that one deed in
Ingenuity.

## Person needed (walled or not online)

| county | platform | the wall |
|---|---|---|
| Anderson (deeds since 2026-02-21 only) | Ingenuity 'Online Services' | client-side bot check posted before the lookup |
| Bamberg, Cherokee, Chester, Chesterfield, Dillon, Edgefield, Fairfield | Neumo (formerly Avenu) GRIDS | the public search redirects to `account/login` with a password form (all 7 checked 2026-10-07); accounts may not be created |
| Hampton, Kershaw, Newberry, Williamsburg | Neumo Records Management | free account login (Kershaw and Williamsburg terms also ban robots; Newberry and Williamsburg images paid) |
| Lee | Neumo Records Management | paid subscription ($5/day) plus login |
| Aiken | county ROD search | Cloudflare challenge |
| Beaufort | NewVision BrowserView | CAPTCHA on every search |
| Jasper | Courthouse Computer Systems | CAPTCHA at entry |
| Clarendon | Harris AcclaimWeb | automated reads blocked (the same adapter would serve it if the block were lifted) |
| Darlington | Cott RECORDhub | account / subscription |
| Saluda | Cott RecordHub | unreachable; account platform |
| Lexington | GovOS CountyFusion | account only since 2026-01-01 |
| Orangeburg | county 'Register Of Deeds Remote Access Site' | free account login |
| Calhoun | TitleSearcher | paid subscription |
| Richland | county Online Data Services | paid subscription |
| Allendale, Marion | none | no online index; books at the Clerk of Court |
| McCormick | not in the matrix | not checked |

## Per-county status (SC)

| county | platform | what a script reads now |
|---|---|---|
| Abbeville | Online Record System | chain + liens (`sc_online_record_system`, OFF) |
| Aiken | county search behind Cloudflare | person |
| Allendale | none | person |
| Anderson | ACPASS to 2026-02-20; Ingenuity after | chain + liens to 2026-02-20 (`anderson_acpass_rod`, OFF); later deeds: person |
| Bamberg | Neumo GRIDS | person (login) |
| Barnwell | Online Record System | chain + liens (`sc_online_record_system`, OFF) |
| Beaufort | NewVision BrowserView | person (CAPTCHA) |
| Berkeley | Online Record System | chain + liens (`sc_online_record_system`, OFF) |
| Calhoun | TitleSearcher | person (paid) |
| Charleston | county document search | not built |
| Cherokee | Neumo GRIDS | person (login) |
| Chester | Neumo GRIDS | person (login) |
| Chesterfield | Neumo GRIDS | person (login) |
| Clarendon | Harris AcclaimWeb | person (blocked) |
| Colleton | Online Record System | chain + liens (`sc_online_record_system`, OFF) |
| Darlington | Cott RECORDhub | person (account) |
| Dillon | Neumo GRIDS | person (login) |
| Dorchester | Online Record System | chain + liens (`sc_online_record_system`, OFF) |
| Edgefield | Neumo GRIDS | person (login) |
| Fairfield | Neumo GRIDS | person (login) |
| Florence | Online Record System | chain + liens (`sc_online_record_system`, OFF) |
| Georgetown | Online Record System | chain + liens (`sc_online_record_system`, OFF) |
| Greenville | GovOS PublicSearch | chain + liens (`publicsearch`, ON) |
| Greenwood | county document search | not built |
| Hampton | Neumo | person (login) |
| Horry | Harris AcclaimWeb | chain + liens (`acclaim_names`, ON) |
| Jasper | CCHS | person (CAPTCHA) |
| Kershaw | Neumo | person (login) |
| Lancaster | Online Record System | chain + liens (`sc_online_record_system`, OFF) |
| Laurens | Online Record System | chain + liens (`sc_online_record_system`, OFF) |
| Lee | Neumo | person (paid) |
| Lexington | GovOS CountyFusion | person (account) |
| Marion | none | person |
| Marlboro | Cott eSearch | not built |
| Newberry | Neumo | person (login) |
| Oconee | GovOS PublicSearch | liens (`kofile`) + chain (`publicsearch`, ON) |
| Orangeburg | county remote access site | person (account) |
| Pickens | Harris AcclaimWeb | chain + liens (`acclaim_names`, ON); distress sweep (`acclaim`) |
| Richland | county Online Data Services | person (paid) |
| Saluda | Cott RecordHub | person |
| Spartanburg | Logan 'The Lookup' (render) | liens (`enrichment_spartanburg_rod`); chain not built |
| Sumter | GovOS CountyFusion (guest) | not built |
| Union | Cott RecordRoom | distress sweep only; chain not built |
| Williamsburg | Neumo | person (login) |
| York | Online Record System | chain + liens (`sc_online_record_system`, OFF) |

## Live proof (2026-10-07; a made-up common surname, nothing saved)

| platform | county | narrow window (SMITH, either side / grantee side) | full chain on a made-up name |
|---|---|---|---|
| PublicSearch | Greenville | 2026-09-01..10: 38 / 15 documents, book/page and description on all | ok: last deed, 3 earlier, liens |
| PublicSearch | Oconee | 18 / 11 documents | ok: last deed, 3 earlier, liens |
| Online Record System | Laurens | 2026-09: 18 / 5 | ok in 30 s |
| Online Record System | Lancaster | 2026-09: 16 / 5 | ok in 136 s (a very common name) |
| Online Record System | Georgetown, Abbeville, Florence | 9, 3 (after the https fix), 16 | not run |
| AcclaimWeb | Horry | 2026-09: 29 / 26 (all grantee rows 'To') | ok: last deed, 3 earlier, liens, 4 foreclosure notices |
| AcclaimWeb | Pickens | 2026-09: 23 / 23 | ok: last deed, 3 earlier, liens |
| ACPASS | Anderson | (one county) | ok: last deed and liens; the walk stopped at a six-grantor deed, as designed |

## Running it

Both enrichers are already called from `main.py` (`enrich_generic_rod` in the ROD lien group,
`enrich_rod_chain` after it). Switches:

* `FORECLOSURE_SC_PUBLICSEARCH_ROD`, `FORECLOSURE_SC_ACCLAIM_ROD` (default 1),
  `FORECLOSURE_SC_ORS_ROD`, `FORECLOSURE_SC_ACPASS_ROD` (default 0): per platform, shared by both enrichers.
* `FORECLOSURE_ROD_CHAIN=1`: the chain enricher's master switch (default off) for `raw['rod_chain']`.
* `SC_ROD_MAX_LOOKUPS_PER_COUNTY` (default 30): owner lookups per county per run; the owner search
  `enrich_generic_rod` makes is cached and reused by the chain enricher without a second lookup.
* `SC_ROD_MIN_GAP_S` can only raise the 1.6 s gap.

Not wired: the Anderson parcel flag needs the lead's parcel id passed to `chain()`
(`enrichment_rod_chain` calls `mod.chain(county, owner, state=..., depth=...)`; adding
`parcel_id=li.parcel_id` for modules whose `chain` takes it turns the flag on).
