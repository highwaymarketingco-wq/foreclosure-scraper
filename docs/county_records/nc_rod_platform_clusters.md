# NC register of deeds: platform clusters, what is read, and where a person is needed

Built 2026-10-07 (two rounds the same day) from `county_records_matrix.json` (NC entries: `rod.platform`, `access`, `free_name_search`,
`images_free`, `legal_description_in_index`, `we_already_read`) and a live check of each family the same day
(plain HTTP, an ordinary browser User-Agent, at least 1.6 s between requests to a host, stopping at the first
CAPTCHA, login page or challenge). The goal: for every county whose register a plain script can read for free,
read per lead the lien picture (deeds of trust, satisfactions, lis pendens, substitutions of trustee) and the
deed chain (the last deed plus up to three earlier conveyances: book/page, recording date, type, grantor,
grantee, the index's short description) for the attorney's quiet-title work.

How the columns are counted:

* **in scope**: `rod.access` is `open` or `disclaimer_click` and `rod.free_name_search` is `yes`.
* **read before**: `we_already_read.rod` is `yes` or `partial`.
* **unlock**: in scope minus read before.
* **scriptable today**: what the live check found for a plain script (not a person in a browser).

## Ranking

| rank | platform family | in scope | read before | unlock | scriptable today (live 2026-10-07) | built |
|---|---|---|---|---|---|---|
| 1 | Cott Systems eSearch (v4 and older), guest name index | 20 | 2 | 18 | 17: 8 open as a guest, 9 more through the vendor's no-credential "Sign in as a Guest" button; Rowan walled (challenge marker) | `rod/nc_cott_v4.py`: 17 counties (+ chain for Buncombe, Polk) |
| 2 | Courthouse Computer Systems classic ASP (`SearchService.asp`) | 20 | 5 | 15 | 3 on county-run servers; the 12 on the vendor's us3/us4/us5 servers answer with a Cloudflare challenge | `rod/nc_cchs_classic.py`: 3 counties |
| 3 | Logan Systems "Remote Access" (classic ASP site, Visual WebGui search) | 11 | 0 | 11 | all 11 open; the name search is a Visual WebGui app, read in a headless browser | `rod/nc_logan_remote.py`: 11 counties (3 proven by a search) |
| 4 | Logan Systems Public Records (server-side Blazor) | 7 | 0 | 7 | all 7 open; the search runs over a websocket, read in a headless browser | `rod/nc_logan_blazor.py`: 7 counties (3 proven by a search) |
| 5 | "The Lookup" (Logan / BIS PHP) | 11 | 6 | 5 | all 11 | `rod/nc_lookup.py`: 11 counties (5 new) |
| 6 | BIS "Online Record System" (PHP NameSearch) | 4 | 0 | 4 | all 4 | `rod/nc_ors.py`: 4 counties |
| 7 | Harris "ROD Web Access" (Aumentum Recorder) | 3 | 1 | 2 | Mecklenburg and Carteret open (Infragistics forms, read in a headless browser); Moore answered the disclaimer postback with HTTP 403 | `rod/nc_harris.py`: 2 counties (both proven) |
| 8 | Tyler Technologies (EagleWeb / Self-Service) | 2 | 0 | 2 | Johnston (EagleWeb) and Durham (Self-Service) open over plain HTTP; Wake's search shows a reCAPTCHA | `rod/nc_tyler.py`: 2 counties (both proven) |
| 9 | CCHS LRSearch (MVC) | 1 | 0 | 1 | Beaufort walled: challenge marker on the vendor's us5 host | |
| 10 | CCHS newer hosted version (CCS) | 1 | 0 | 1 | Watauga walled: challenge marker on the vendor's us3 host | |

Round one built what plain HTTP reads: Cott (17), The Lookup (11, 5 new), the Online Record System (4), CCHS
classic on county servers (3). Round two (below) followed board value: Tyler, Harris, then Logan's Blazor and
Remote Access apps in a headless browser.

## Board value of the counties still unread before round two (2026-10-07)

One read-only pass over the published board (`board_stream.iter_board_rows`, counts only; 350,013 rows, 241,423
NC). Rows per family, open counties only, the three largest first:

| family | board rows (with an owner name) | largest counties | walled, not counted |
|---|---|---|---|
| Logan Public Records (Blazor) | 17,474 (16,229) | Catawba 7,547, Cumberland 3,436, Union 2,221 | Lee 789, Hoke 499 (access not established) |
| Harris ROD Web Access | 16,688 (14,729) | Mecklenburg 15,820, Carteret 868 | Moore 1,340 (HTTP 403) |
| Tyler | 7,530 (6,621) | Durham 5,030, Johnston 2,500 | Wake 10,553 (reCAPTCHA) |
| Logan Remote Access | 3,944 (3,386) | Davie 480, Yadkin 478, Vance 433 | |

For scale, the round-one counties hold 63,129 board rows (Cott 27,808, Online Record System 26,747, CCHS
classic 4,574, The Lookup 4,000). Together the 51 newly read counties hold 108,765 NC board rows.

## Counties by family

| family | counties in scope (* read before) | out of scope in the matrix |
|---|---|---|
| Cott eSearch | Alamance, Alexander, Buncombe\*, Edgecombe, Graham, Granville, Halifax, Jackson, Jones, Lenoir, Nash, Onslow, Pamlico, Pitt, Polk\*, Rowan, Rutherford, Scotland, Wayne, Wilson | |
| CCHS classic ASP | Burke\*, Caldwell, Camden, Caswell, Chowan, Cleveland\*, Currituck, Dare, Duplin, Franklin, Gates, Henderson\*, Hertford, Hyde, Lincoln\*, Madison\*, Montgomery, Orange, Stanly, Surry | |
| Logan Remote Access | Anson, Ashe, Bladen, Cherokee, Davie, Martin, Northampton, Swain, Vance, Warren, Yadkin | |
| Logan Public Records (Blazor) | Cabarrus, Catawba, Chatham, Cumberland, Sampson, Union, Wilkes | Hoke, Lee (access not established) |
| The Lookup | Avery, Bertie, Clay\*, Columbus, Haywood\*, Macon, McDowell\*, Mitchell\*, Robeson, Transylvania\*, Yancey\* | |
| Online Record System | Davidson, Forsyth, Guilford, New Hanover | |
| Aumentum Recorder | Carteret, Mecklenburg\*, Moore | |
| Tyler | Durham, Johnston | Wake (reCAPTCHA) |
| CCHS LRSearch | Beaufort | Craven, Harnett (reCAPTCHA), Gaston (Cloudflare) |
| CCHS newer hosted | Watauga | Alleghany, Pasquotank, Pender, Perquimans, Person, Richmond, Rockingham, Tyrrell, Washington (Cloudflare); Randolph, Stokes (reCAPTCHA) |
| Inttek Recording-Pro | | Brunswick (math question on the sign-in) |

## What this work reads now

51 counties newly read, all behind default-off flags until the owner turns them on.

Plain HTTP (run by `enrich_generic_rod`, registry `ROD_CONFIG`):

* Cott eSearch v4 (`FORECLOSURE_NC_COTT_ROD`): Alexander, Graham, Granville, Jackson, Jones, Nash, Pamlico, Wayne
  (open as a guest), and Alamance, Edgecombe, Halifax, Lenoir, Onslow, Pitt, Rutherford, Scotland, Wilson (behind
  the "Sign in as a Guest" button, which asks for no username, password or account and was ruled a click-through
  on 2026-10-07: the adapter posts that button with the username and password boxes empty, exactly as a
  browser does, and walls the county if a credential, a CAPTCHA, a challenge or a second sign-in page appears).
* The Lookup (`FORECLOSURE_NC_LOOKUP_ROD`): Avery, Bertie, Columbus, Macon, Robeson.
* Online Record System (`FORECLOSURE_NC_ORS_ROD`): Davidson, Forsyth, Guilford, New Hanover.
* CCHS classic on county servers (`FORECLOSURE_NC_CCHS_CLASSIC_ROD`): Orange, Stanly, Surry.
* Tyler (`FORECLOSURE_NC_TYLER_ROD`): Durham (Self-Service), Johnston (EagleWeb; a guest search lists at most 50
  results, reported as truncated at 50).

Headless browser (`rod/nc_render.py`, the Spartanburg precedent; run by `enrichment_nc_rod_render`, registry
`RENDER_ROD_CONFIG`; each platform capped per run by its own `*_ROD_MAX`, default 30 lookups per county):

* Harris ROD Web Access (`FORECLOSURE_NC_HARRIS_ROD`, cap `FORECLOSURE_NC_HARRIS_ROD_MAX`): Mecklenburg, Carteret.
* Logan Blazor (`FORECLOSURE_NC_LOGAN_BLAZOR_ROD`, cap `FORECLOSURE_NC_LOGAN_BLAZOR_ROD_MAX`): Catawba, Cumberland,
  Union (proven); Cabarrus, Chatham, Sampson, Wilkes (same app, landing page checked, not yet proven by a search).
* Logan Remote Access (`FORECLOSURE_NC_LOGAN_REMOTE_ROD`, cap `FORECLOSURE_NC_LOGAN_REMOTE_ROD_MAX`): Davie, Yadkin,
  Vance (proven); Anson, Ashe, Bladen, Cherokee, Martin, Northampton, Swain, Warren (landing page checked; Bladen
  and Warren enter at `opening.asp`).

The deed chain (and, where no per-owner lien read existed, the lien picture) is added for 8 counties read
before: Buncombe and Polk (Cott), Clay, Haywood, Yancey, Transylvania, McDowell, Mitchell (The Lookup).

Each adapter exposes `search_by_name(state, county, name)` (the shared interface of
`enrichment_generic_rod.py`) and `chain(county, owner_name)`, whose result shape is documented in
`src/foreclosure_scraper/rod/nc_chain.py`. Document images are never opened. Index descriptions are short
(a lot, a subdivision, a township or a book/page reference), not the full legal description, which stays on
the deed image.

## Live proof (2026-10-07, a common surname in a narrow date window, nothing saved)

| adapter | county | window | what the page showed | what the parser returned |
|---|---|---|---|---|
| Cott v4 | Nash | 06/01-06/10/2026 | "returned 4 results" | 4 rows; grantors, grantees, type, book/page, Ref column match the cells |
| Cott v4 | Graham | 05/01-06/30/2026 | "returned 3 results" | 3 rows; the 06/01-06/10 window showed the register's own "returned 0 results" |
| Cott v4 | Alexander, Granville, Jackson, Jones, Pamlico, Wayne | form only | guest search form, no wall | |
| Cott v4, guest button | Edgecombe | 09/01-09/05/2026 | sign-in page, guest button, then "returned 1 results" | 1 row; Ref column read |
| Cott v4, guest button | Onslow | 09/01-09/05/2026 | "returned 5 results" | 5 rows (the index also lists marriages; they classify as other) |
| Cott v4, guest button | Pitt | 09/01-09/05/2026 | "returned 8 results" | 8 rows |
| Cott v4, guest button | Alamance, Halifax, Lenoir, Rutherford, Scotland, Wilson | form only | the button led to the guest search form, no wall | |
| The Lookup | Avery | 09/01-09/15/2026 | 6 names; 3 ticked, 5 documents | 5 instruments; codes classified from the county's own code list |
| The Lookup | Columbus | 09/01-09/15/2026 | 17 names; 3 ticked, 3 index rows | 2 instruments (a two-borrower deed of trust folded into one) |
| The Lookup | Bertie, Macon, Robeson | disclaimer only | "The Lookup" search page, no wall | |
| Online Record System | New Hanover | 09/01-09/05/2026 | 9 names; 3 ticked, 3 rows | 3 rows with role, reverse party, cross-reference, instrument number |
| Online Record System | Davidson | 09/01-09/05/2026 | 7 names; 3 ticked, 4 rows | 4 rows; categories DEEDS / MORTGAGE read from the county's list |
| Online Record System | Forsyth, Guilford | disclaimer only | search form, no wall | |
| CCHS classic | Orange | 09/01-09/10/2026 | 16 party rows, the reply's own document count 6 | 6 documents |
| CCHS classic | Surry | 09/01-09/10/2026 | 5 party rows, document count 3 | 3 documents |
| CCHS classic | Stanly | application page only | open, no wall | |
| Tyler Self-Service | Durham | 09/01-09/05/2026 | 3 result items | 3 documents; doc no, book type, book, page, type, grantor and grantee lists, legal |
| Tyler EagleWeb | Johnston | 09/01-09/05/2026 | "2 results" | 2 documents; an ", LLC" lender kept as one name |
| Harris (browser) | Carteret | 09/01-09/05/2026 | "38 records found", 2 pages | 38 rows read over both pages, grantor / grantee side from NAME_TYPE |
| Harris (browser) | Mecklenburg | 09/01-09/02/2026 | "8 records found" | 8 rows with book, page, instrument number |
| Logan Blazor (browser) | Catawba | 09/01-09/05/2026 | Directory (6), Index Detail (11) | 11 rows |
| Logan Blazor (browser) | Cumberland | 09/01-09/05/2026 | Directory (18), Index Detail (25) | 25 rows |
| Logan Blazor (browser) | Union | 09/01-09/05/2026 | Directory (3), Index Detail (1) | 1 row (Instrument # read) |
| Logan Remote Access (browser) | Vance | 08/01-09/30/2026 | 10 names | 10 detail rows, all in the window |
| Logan Remote Access (browser) | Davie | 08/01-09/30/2026 | 24 names | 25 detail rows, flagged truncated (fewer rows drawn than the names' entries) |
| Logan Remote Access (browser) | Yadkin | 08/01-09/30/2026 | 25 names | 31 detail rows, flagged truncated (25 names fill the grid) |

A made-up surname that cannot exist returned an empty pick list on The Lookup ("Pick List", no names) and
"0 Names Found" on the Online Record System; both read as a clean "nothing found", not as an error.

## Person needed

| county | platform | what stops a script | seen |
|---|---|---|---|
| Rowan | Cott eSearch (guest button) | its sign-in page carried a challenge marker; the county stopped there and was not fetched again | live |
| Caldwell, Camden, Caswell, Chowan, Currituck, Dare, Duplin, Franklin, Gates, Hertford, Hyde, Montgomery | CCHS classic on the vendor's us3/us4/us5 servers | Cloudflare 403 challenge on `application.asp`, the page a browser opens after the disclaimer | live on Caldwell (us3), Franklin and Hertford (us4), Gates (us5) |
| Alleghany, Pasquotank, Pender, Perquimans, Person, Richmond, Rockingham, Tyrrell, Washington | CCHS hosted search | Cloudflare check | matrix |
| Randolph, Stokes | CCHS newer hosted version | reCAPTCHA gate | matrix |
| Greene, Iredell, Craven, Harnett | CCHS LRSearch | reCAPTCHA gate | matrix |
| Beaufort | CCHS LRSearch (us5) | challenge marker on the first page | live |
| Watauga | CCHS newer hosted version (us3) | challenge marker on the first page | live |
| Gaston | CCHS LRSearch | Cloudflare check (partly read by `enrichment_gaston_rod.py`) | matrix |
| Wake | Tyler Self-Service | reCAPTCHA | matrix |
| Moore | Harris ROD Web Access | HTTP 403 on the disclaimer postback (the page carries Cloudflare's beacon) | live |
| Brunswick | Inttek Recording-Pro | arithmetic question on the sign-in | matrix |

Ruling applied 2026-10-07: a "Sign in as a Guest" button that asks for no username, password or account is a
click-through, like a disclaimer accept; it opened 9 of the 10 Cott sign-in tenants (Rowan walled). Burke,
Cleveland, Henderson, Lincoln and Madison are read today by `rod/cchs.py` through a TLS-fingerprint switch; the
new adapters do not do that.

## Not walled, not yet proven or built (the next round)

* Prove by a live search the configured browser counties not yet searched: Cabarrus, Chatham, Sampson, Wilkes
  (Blazor); Anson, Ashe, Bladen, Cherokee, Martin, Northampton, Swain, Warren (Remote Access).
* Lee and Hoke (Logan Blazor per the matrix, access not established): check, then add to the Blazor adapter.
* Mecklenburg before March 1990 (meckrodhistorical.com) is scanned index books, not a typed index: a person.
* The Logan Remote Access and Blazor detail grids draw only the rows in view; a long owner history is reported
  as truncated rather than scrolled.

## Switches and wiring

| step | function | where in a run | switches (all OFF by default) |
|---|---|---|---|
| lien existence, plain HTTP | `enrichment_generic_rod.enrich_generic_rod` | the ROD group (wired in `main.py`) | `FORECLOSURE_NC_COTT_ROD`, `FORECLOSURE_NC_LOOKUP_ROD`, `FORECLOSURE_NC_ORS_ROD`, `FORECLOSURE_NC_CCHS_CLASSIC_ROD`, `FORECLOSURE_NC_TYLER_ROD`; cap `NC_ROD_MAX_LOOKUPS_PER_COUNTY` (30) |
| lien existence, browser | `enrichment_nc_rod_render.enrich_nc_rod_render` (async) | after the ROD group, on its own (one browser at a time); not yet wired | `FORECLOSURE_NC_HARRIS_ROD`, `FORECLOSURE_NC_LOGAN_BLAZOR_ROD`, `FORECLOSURE_NC_LOGAN_REMOTE_ROD`; caps `*_ROD_MAX` (30 each); budget `FORECLOSURE_NC_ROD_RENDER_BUDGET_S` (3600) |
| deed chain | `enrichment_rod_chain.enrich_rod_chain` | after the lien steps (wired in `main.py`) | `FORECLOSURE_ROD_CHAIN=1` plus each platform's flag; `FORECLOSURE_ROD_CHAIN_DEPTH` (3), `FORECLOSURE_ROD_CHAIN_BUDGET_S` (1800), refresh `FORECLOSURE_ROD_CHAIN_REFRESH_DAYS` (30) / `_HOT_DAYS` (7) |

## Politeness and safety, as built

`rod/nc_polite.py` is the only transport: plain `requests`, the quiet-title intake's browser headers, at least
1.6 s between two requests to one host from anywhere in the process, one request per host at a time, a per-run
cap of `NC_ROD_MAX_LOOKUPS_PER_COUNTY` (default 30) name searches per county shared by every caller, and a
wall (CAPTCHA, login page, challenge, 401/402/403/407/429/503) ends that county for the run with nothing
retried. `rod/nc_render.py` drives a fresh headless Chromium guest session per lookup through the same rules:
an ordinary desktop Chrome User-Agent, no stealth settings, images and fonts not fetched, every navigation and
server action paced on the same per-host clock and wall-checked, one browser in the process at a time, one
lookup at a time per county. Every adapter is tested on hand-written pages (made-up names) for the parse, an
empty answer, an error page and a blocked page; the browser adapters through the real page wrapper with a
scripted fake browser page.
