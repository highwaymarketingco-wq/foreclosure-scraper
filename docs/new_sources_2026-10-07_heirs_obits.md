# Heirs and obituaries: sources, walls and board counts (2026-10-07)

The attorney's ask: tax notices often go to a dead person; for those parcels he needs the taxpayer
of record and the potential heirs, and obituaries are one of the records he checks. This page
lists what was built, every source checked (open and built, open and not built, walled), and the
board counts. It holds counts only: no owner, decedent or relative names, no page content.

## What was built

| Piece | File | What it does |
|---|---|---|
| Text parsing | `src/foreclosure_scraper/obituary_text.py` | Obituary "survived by" lists into named relatives with the relation the obituary states; unnamed counts ("seven grandchildren") stay counts; in-laws ("and husband Bob") and the predeceased are kept apart. Notice to Creditors: decedent, case number, date of death, each executor / administrator / personal representative, with an address only when the notice prints one (a c/o attorney address is labelled). |
| Obituary match | `src/foreclosure_scraper/enrichment_obituary_match.py` | Links an obituary decedent to a lead: the quiet_title full-name rule (`full`; `middle_initial`; `given_surname` with its stated reason), the decedent's residence county (or the publisher's / cemetery's county, said so), and date checks (birth year, elderly exemption, a purchase after the death date). Exactly one death must fit; otherwise `ambiguous`, recorded and not attached. A no-middle-name fit on a lead with no other sign of death is ambiguous. Writes `raw['obituary_match']`. |
| Heir candidates | `src/foreclosure_scraper/enrichment_heir_candidates.py` | For leads whose roll or records say the owner died (HEIRS / ESTATE OF / DECEASED on the roll, a probate notice or record, an obituary, a confirmed death entry), `raw['heir_candidates']` = `[{name, relation, source_kind, source_url, source_date, confidence_note, label: "candidate"}]` (+ `address` for a representative only when the notice printed it). `source_kind`: `obituary_survivor`, `probate_notice_personal_representative`, `probate_record_personal_representative`, `court_notice_named_heir`, `county_record`. |
| Private store | `src/foreclosure_scraper/heirs_store.py` | `data/heirs/` (gitignored): `obituary_store.jsonl.gz` (every obituary/memorial seen, with survivors), `heir_candidates.jsonl.gz` (the names board: lead, taxpayer of record, candidates, obituary match), `lookups.json`, `findagrave_locations.json`. |
| Feed reader | `scrapers/public_notices/obituary_feeds.py` | 6 open paper / funeral-home feeds (below). |
| Echovita reader | `scrapers/public_notices/echovita_obituaries.py` | NC + SC statewide listings, newest first; obituary pages for footprint counties first, capped. |
| SC estate notices | `scrapers/public_notices/publicnoticesc_estates.py` | The SC Press Association portal's two estate presets that `publicnoticesc.py` never runs. |
| Name lookups | `src/foreclosure_scraper/obituary_lookup.py` | For dead-owner leads with no attached obituary: Echovita city search and Find a Grave county search by the owner's name, capped, never repeated within 45 days. |
| Shared fetcher | `scrapers/public_notices/_obit_common.py` | >= 1.6 s between requests to one host, an ordinary browser User-Agent, no impersonation; a CAPTCHA / challenge / login / 401-403 / 402 / 429 stops that host for the run. |

**Privacy choice (public board).** `raw['heir_candidates']`, `raw['obituary_match']` and the
scrapers' `raw['obituary_private']` hold private people's names and are NOT in RAW_KEEP: they never
reach the published board. The only new published key is `raw['heir_candidates_summary']`, a
whitelist of `count`, `by_source_kind`, `deceased_signals`, `obituary_match`
(attached / ambiguous) and `label`: counts and flags, no names. Names are in the private file above.
New obituary rows publish the decedent block only (decedent, dates, residence, publisher,
`survivor_names_parsed` as a number).

Two notes on wall detection, both narrow and both on pages that were fully served (HTTP 200, no
challenge interstitial): Cloudflare's passive detection script is not a challenge; and a CAPTCHA
widget inside a share-by-email or comment `<form>` is not a gate when the obituary text is on the
page outside the form (the form is never submitted). A CAPTCHA in front of the content is a wall.

## Sources: open and built

| Source | URL | What it gives | Coverage | Live proof 2026-10-07 |
|---|---|---|---|---|
| Echovita listings | `https://www.echovita.com/us/obituaries/nc?page=N` (and `/sc`) | Name, residence city, dates, age; obituary page: schema.org Person (birth/death date) + full text | NC + SC statewide, all counties, ~24 a page, newest first | 24 listing pages: 576 obituaries (288 NC, 288 SC); 77 in footprint counties; 121 with a city the city tables do not place in a county; 120 obituary pages read: 73 with a survivor list, 757 survivor names parsed |
| Tryon Daily Bulletin | `https://www.tryondailybulletin.com/category/obituaries/feed/` | Full text in the feed | Polk NC | 10 obituaries, 10 with survivors |
| The Laurens County Advertiser | `https://www.laurenscountyadvertiser.net/category/obituaries/feed/` | Full text in the feed | Laurens SC | 10, 9 with survivors |
| The Edgefield Advertiser | `https://www.edgefieldadvertiser.com/category/obituaries/feed/` | Excerpt; article page has the text | Edgefield SC | 10, 10 with survivors (9 article pages) |
| Groce Funeral Home | `https://www.grocefuneralhome.com/?feed=rss2&post_type=ltobits` | Excerpt; obituary page has the text | Buncombe NC | 10, 10 with survivors (10 pages) |
| Watauga Democrat (TownNews RSS) | `https://www.wataugademocrat.com/search/?f=rss&t=article&c=obituaries&l=50` | Name + date only (article pages answer 403) | Watauga NC | 49 |
| Avery Journal-Times (TownNews RSS) | `https://www.averyjournal.com/search/?f=rss&t=article&c=obituaries&l=50` | Name + date only | Avery NC | 48 |
| Feeds total | | | | 137 obituaries; 39 with a survivor list; 334 survivor names |
| SC Press Association estate presets | `https://www.scpublicnotices.com/Search.aspx`, Popular Searches 30 "Notice to Creditors" and 23 "Probate Notices" | Grid preview (~250 characters): decedent and ES case number on about one row in six; county from the case number | SC statewide, 46 counties, ~60-day window | 3 pages a preset: 300 notices, 26 named estates (25 with case numbers), representative never visible |
| Echovita name search | `https://www.echovita.com/us/obituaries/<st>/<city>?q=<First Last>&s=1` | Cards for that city whose name or text matches | Any NC/SC city | see board measurement |
| Find a Grave memorial search | `https://www.findagrave.com/memorial/search?firstname=&middlename=&lastname=&locationId=county_N` | Name, birth-death dates, cemetery 'City, County, State'; memorial page: dates, biography (often a pasted obituary), family links | Any county; the county filter needs the site's own location id (two state browse pages, cached) | see board measurement. Family links point to other memorials (people who died), so they are counted, never candidates. robots.txt disallows /memorial/search; the owner's rule is that robots.txt is not a wall. |

Already read before today and unchanged: `funeral_home_rss.py` (11 Frazer / ltobits feeds, names
and dates), `sc_probate_notices.py` (Pickens, Laurens, Cherokee papers: decedent, case number,
representative and printed address), `nc_notices_counties.py` / `ncpublicnotices.py` (ncnotices.com
estate notices, grid previews), `sc_probate_net.py` (SC probate index: representative),
`nc_heir_estate_parcels.py` (county rolls with HEIRS / ESTATE entries and co-owners).

## What `publicnoticesc.py` misses

It runs one preset, "Foreclosures" (value 4), and keeps 7 Upstate counties. The portal's own
dropdown also has "Notice to Creditors" (30) and "Probate Notices" (23): the statewide list of
estates being opened (about 1,000 notices each per 60 days, 20 pages of 50). Now read by
`publicnoticesc_estates.py`, preview only: the representative's name and address always sit past
the preview cut, and Details.aspx is behind the click-through terms and a Turnstile CAPTCHA (not
fetched). A person opens the Details link, passes the CAPTCHA, and reads the representative.
ncnotices.com has the same Details gate; its estate previews are already read by
`nc_notices_counties.py`.

## Sources: open, not built (yet)

| Source | URL | Why not built | Next step |
|---|---|---|---|
| Dignity Memorial | `https://www.dignitymemorial.com/obituaries` | Open today (HTTP 200; an older note said Akamai 403). The server page embeds the latest 50 obituaries nationwide with 200-character teasers; location filtering happens in the site's client-side search API, which was not reached | Find the search API the page calls; obituary pages not yet probed |
| Pickens County Courier | `https://www.yourpickenscounty.com/category/obituaries/feed/` | Open, but each post is a weekly round-up ("Obituaries 10-7-26") holding several obituaries | A per-obituary splitter for the round-up page |
| Salisbury Post | `https://www.salisburypost.com/category/obituaries/feed/` | Open; the category carries news headlines, not obituaries | none |
| Bladen Journal | `https://www.bladenjournal.com/category/obituaries/feed/` | Open; items have empty or surname-only titles | none |
| Frazer funeral-home feeds | `HOST/feed` (e.g. the 9 Frazer hosts in `funeral_home_rss.py`) | Feeds open to an ordinary request; the obituary pages (the text with survivors) answered HTTP 403 (Cloudflare) on the one checked | Echovita often republishes the same obituary with its text |

## Sources checked and walled (not built; nothing was solved or worked around)

| Source | URL | What is behind it | Coverage | What a person can do by hand |
|---|---|---|---|---|
| Legacy.com | `https://www.legacy.com/us/obituaries/local/north-carolina/asheville` | Cloudflare "Just a moment..." challenge, HTTP 403 | National; hosts the obituary sections of many papers (e.g. the Gaffney Ledger's obituaries page is Legacy-powered) | Search by first + last name and state on legacy.com in a browser |
| Gannett papers (USA Today network) | `https://www.citizen-times.com/obituaries/` and blueridgenow.com, gastongazette.com, shelbystar.com, goupstate.com, greenvilleonline.com, independentmail.com | HTTP 402 "Access Restricted" on the obituary list page (all 7 checked) | Buncombe, Henderson, Gaston, Cleveland NC; Spartanburg, Greenville, Anderson SC | Open the paper's obituary page in a browser (often routed to Legacy) |
| Tribute Archive | `https://www.tributearchive.com/` | Cloudflare challenge, HTTP 403 (also on robots.txt) | National funeral-home aggregator | Browser search by name |
| Everloved | `https://www.everloved.com/` | Cloudflare challenge, HTTP 403 | National memorial pages | Browser search |
| Transylvania Times obituaries | `https://www.transylvaniatimes.com/obituaries` -> `obituaries.transylvaniatimes.com` | Cloudflare challenge, HTTP 403 | Transylvania NC | Browser |
| News-Record & Sentinel (TownNews) | `https://www.newsrecordandsentinel.com/search/?f=rss&t=article&c=obituaries` | HTTP 402 | Madison NC | Browser |
| TownNews papers answering HTTP 429 to a first, single request | themountaineer.com (Haywood NC), mcdowellnews.com (McDowell NC), morganton.com (Burke NC), thesylvaherald.com (Jackson NC), thedigitalcourier.com (Rutherford NC), newstopicnews.com (Caldwell NC), hickoryrecord.com, statesville.com, journalpatriot.com, lincolntimesnews.com, mitchellnews.com, upstatetoday.com (Oconee SC), indexjournal.com (Greenwood SC), onlinechester.com, journalscene.com, myhorrynews.com, scnow.com, timesanddemocrat.com | HTTP 429 on the first polite request (the RSS `?f=rss&t=article&c=obituaries` path); treated as a bot gate, not retried with a browser fingerprint | Several footprint counties (Haywood, McDowell, Burke, Rutherford, Oconee) | Open the paper's obituaries section in a browser |
| HTTP 403 | greertoday.com, theitem.com (Sumter SC), richmondobserver.com | Block page | Greer, Sumter, Richmond | Browser |
| Frazer funeral-home obituary pages | e.g. `https://www.cecilmburtonfuneralhome.com/obituary/<slug>` | Cloudflare HTTP 403 on the obituary page (feed is open) | 9 Frazer hosts | Open the obituary in a browser |
| SC Press Association Details.aspx | `https://www.scpublicnotices.com/Details.aspx?ID=<n>` | Click-through Terms of Use + Cloudflare Turnstile CAPTCHA | SC statewide | Open, agree, pass the CAPTCHA, read the representative |
| ncnotices.com Details.aspx | `https://www.ncnotices.com/Details.aspx?ID=<n>` | "I Agree" + reCAPTCHA | NC statewide | Same |
| NC eCourts estates | `https://portal-nc.tylertech.cloud/` (Estates search) | CAPTCHA in front of the search (see quiet_title adapters) | NC statewide estates | Search the decedent's name in a browser; the estate file names the representative and often lists heirs |

Also unreachable today: sysoon.com (TLS error), obitree.com (empty 114-byte page),
ancientfaces.com (HTTP 202 interstitial), uniondailytimes.com (no obituary feed), and five WordPress
paper hosts that refused the connection (yanceycountynews, crossroadschronicle, polkcountynewsjournal,
thecherokeeone, thetimesexaminer).

## Board measurement (one pass via `iter_board_rows`, 2026-10-07)

Method: `iter_board_rows` over the published board (350,013 rows, one pass, 46 s,
peak memory 286 MB). The pass kept every dead-owner lead (`deceased_signals`) and every individual-owner row
whose surname + given name is an obituary decedent's, and fed the board's own 334 obituary
rows into the private store. Then `match_rows` and `enrich_heir_candidates` ran on the kept rows against the
private store: 1,076 obituary / memorial records (today's live feed + Echovita reads, the board's
obituary rows, and one capped name-lookup sample). Names went only to the private file; below are counts.

The name-lookup sample: 120 footprint dead-owner leads (owners with a middle name first),
Echovita city search + Find a Grave county search: 29 fitting records, 14
with a survivor list. Partway through, Echovita answered a Cloudflare challenge page: the lookup recorded it
as walled and asked Echovita nothing more that run (Find a Grave continued). Keep `OBITUARY_LOOKUPS` small.
The measurement then ran a second time without lookups after one fix (a probate-index row's `defendant`
field holds the personal representative and was being read as the decedent); these are the second run's counts.

**Totals.** Dead-owner leads: **18,567** in NC + SC
(7,253 in the 18 footprint counties). Death signals (a lead can carry several):
roll HEIRS / ESTATE / DECEASED 14,020; probate notice or record
4,962; obituary 399;
confirmed death entry 17.

Obituary matches: **65 attached** (name fit: full 57,
middle initial 6, given + surname 2);
by source: Find a Grave search 27, Echovita search
25, board Gannett obituary rows 7,
Echovita listing 4, funeral-home RSS
2. 8 of the attached leads had
no other sign of death (the obituary is the first). **11 ambiguous**, recorded and not attached
(1 on a dead-owner lead; the rest are a given + surname fit with no middle name
on a roll that does not say the owner died).

Heir candidates: **3,690 dead-owner leads** carry at least one,
**4,115 candidates** in all: personal representatives from published estate notices
2,015; county-roll co-owners and care-of names
1,629; probate-index representatives
243; obituary survivors
225; court-notice named heirs
3. The other 14,877
dead-owner leads have the taxpayer of record only; for them the next sources are the walled ones above
(eCourts estate files, Legacy, the paywalled papers), which a person checks by hand.

Per county (dead-owner leads after the match; a lead's obituary columns count matches, the candidate columns count names):

| County | Dead-owner leads | Obituary attached | Ambiguous | Newly dead (obit match) | Leads with candidates | Candidates | Obit survivors | Notice PRs | Probate-index PRs | Court-notice heirs | County-record names |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Footprint (18 counties)** | 7253 | 62 | 1 | 7 | 1813 | 2196 | 225 | 1086 | 0 | 0 | 885 |
| Gaston NC | 1325 | 2 | 0 | 0 | 15 | 33 | 20 | 4 | 0 | 0 | 9 |
| Lincoln NC | 1226 | 15 | 0 | 0 | 21 | 51 | 33 | 0 | 0 | 0 | 18 |
| Pickens SC | 839 | 11 | 0 | 0 | 565 | 590 | 23 | 558 | 0 | 0 | 9 |
| Rutherford NC | 795 | 6 | 0 | 5 | 106 | 170 | 0 | 0 | 0 | 0 | 170 |
| McDowell NC | 675 | 21 | 1 | 0 | 467 | 575 | 107 | 66 | 0 | 0 | 402 |
| Buncombe NC | 332 | 2 | 0 | 0 | 39 | 64 | 20 | 4 | 0 | 0 | 40 |
| Transylvania NC | 315 | 0 | 0 | 0 | 10 | 10 | 0 | 0 | 0 | 0 | 10 |
| Laurens SC | 300 | 0 | 0 | 0 | 143 | 143 | 0 | 140 | 0 | 0 | 3 |
| Cherokee SC | 266 | 0 | 0 | 0 | 237 | 237 | 0 | 237 | 0 | 0 | 0 |
| Spartanburg SC | 201 | 2 | 0 | 1 | 67 | 78 | 12 | 59 | 0 | 0 | 7 |
| Polk NC | 193 | 0 | 0 | 0 | 46 | 46 | 0 | 0 | 0 | 0 | 46 |
| Henderson NC | 164 | 0 | 0 | 0 | 24 | 38 | 0 | 0 | 0 | 0 | 38 |
| Cleveland NC | 140 | 0 | 0 | 0 | 15 | 15 | 0 | 0 | 0 | 0 | 15 |
| Oconee SC | 114 | 0 | 0 | 0 | 13 | 68 | 0 | 0 | 0 | 0 | 68 |
| Union SC | 106 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| Burke NC | 97 | 1 | 0 | 0 | 41 | 66 | 0 | 18 | 0 | 0 | 48 |
| Anderson SC | 87 | 2 | 0 | 1 | 2 | 10 | 10 | 0 | 0 | 0 | 0 |
| Mitchell NC | 78 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| **All NC + SC** | 18567 | 65 | 1 | 8 | 3690 | 4115 | 225 | 2015 | 243 | 3 | 1629 |
| Catawba NC | 711 | 0 | 0 | 0 | 49 | 49 | 0 | 39 | 0 | 0 | 10 |
| Forsyth NC | 690 | 0 | 0 | 0 | 149 | 169 | 0 | 94 | 0 | 0 | 75 |
| Charleston SC | 530 | 0 | 0 | 0 | 127 | 127 | 0 | 0 | 125 | 0 | 2 |
| New Hanover NC | 341 | 0 | 0 | 0 | 2 | 2 | 0 | 2 | 0 | 0 | 0 |
| Washington NC | 338 | 0 | 0 | 0 | 35 | 35 | 0 | 0 | 0 | 0 | 35 |
| Onslow NC | 334 | 0 | 0 | 0 | 44 | 49 | 0 | 11 | 0 | 0 | 38 |
| Guilford NC | 331 | 0 | 0 | 0 | 125 | 125 | 0 | 125 | 0 | 0 | 0 |
| Bertie NC | 300 | 0 | 0 | 0 | 21 | 21 | 0 | 0 | 0 | 0 | 21 |
| Colleton SC | 299 | 0 | 0 | 0 | 11 | 11 | 0 | 0 | 0 | 0 | 11 |
| Williamsburg SC | 267 | 0 | 0 | 0 | 4 | 4 | 0 | 0 | 0 | 0 | 4 |
| Barnwell SC | 237 | 0 | 0 | 0 | 21 | 21 | 0 | 0 | 0 | 0 | 21 |
| Berkeley SC | 233 | 0 | 0 | 0 | 28 | 28 | 0 | 0 | 0 | 0 | 28 |
| Sumter SC | 227 | 0 | 0 | 0 | 10 | 10 | 0 | 0 | 0 | 0 | 10 |
| Hyde NC | 223 | 0 | 0 | 0 | 4 | 6 | 0 | 0 | 0 | 0 | 6 |
| Johnston NC | 211 | 2 | 0 | 0 | 121 | 121 | 0 | 117 | 0 | 0 | 4 |
| Robeson NC | 207 | 0 | 0 | 0 | 11 | 11 | 0 | 11 | 0 | 0 | 0 |
| Rockingham NC | 193 | 0 | 0 | 0 | 102 | 102 | 0 | 102 | 0 | 0 | 0 |
| Cabarrus NC | 185 | 0 | 0 | 0 | 151 | 151 | 0 | 151 | 0 | 0 | 0 |
| Gates NC | 182 | 0 | 0 | 0 | 8 | 8 | 0 | 0 | 0 | 0 | 8 |
| Pitt NC | 166 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Orange NC | 152 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Durham NC | 145 | 0 | 0 | 0 | 9 | 9 | 0 | 3 | 0 | 0 | 6 |
| Brunswick NC | 144 | 0 | 0 | 0 | 13 | 13 | 0 | 0 | 0 | 0 | 13 |
| Perquimans NC | 142 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| Iredell NC | 141 | 0 | 0 | 0 | 61 | 61 | 0 | 61 | 0 | 0 | 0 |
| Dorchester SC | 132 | 0 | 0 | 0 | 99 | 99 | 0 | 0 | 99 | 0 | 0 |
| Scotland NC | 131 | 0 | 0 | 0 | 38 | 38 | 0 | 38 | 0 | 0 | 0 |
| Alamance NC | 130 | 0 | 0 | 0 | 6 | 6 | 0 | 2 | 0 | 0 | 4 |
| Richmond NC | 124 | 0 | 0 | 0 | 10 | 10 | 0 | 10 | 0 | 0 | 0 |
| Beaufort NC | 123 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| Sampson NC | 116 | 0 | 0 | 0 | 30 | 30 | 0 | 30 | 0 | 0 | 0 |
| Mecklenburg NC | 106 | 0 | 0 | 0 | 26 | 26 | 0 | 9 | 0 | 0 | 17 |
| Florence SC | 105 | 0 | 0 | 0 | 11 | 11 | 0 | 11 | 0 | 0 | 0 |
| Anson NC | 102 | 0 | 0 | 0 | 29 | 29 | 0 | 19 | 0 | 0 | 10 |
| Carteret NC | 98 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Randolph NC | 96 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Bladen NC | 95 | 0 | 0 | 0 | 4 | 4 | 0 | 4 | 0 | 0 | 0 |
| Cumberland NC | 92 | 0 | 0 | 0 | 2 | 2 | 0 | 2 | 0 | 0 | 0 |
| Edgecombe NC | 91 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Haywood NC | 91 | 0 | 0 | 0 | 23 | 23 | 0 | 0 | 0 | 0 | 23 |
| Franklin NC | 85 | 0 | 0 | 0 | 7 | 7 | 0 | 0 | 0 | 0 | 7 |
| Chatham NC | 85 | 0 | 0 | 0 | 16 | 27 | 0 | 1 | 0 | 0 | 26 |
| Person NC | 84 | 0 | 0 | 0 | 12 | 12 | 0 | 0 | 0 | 0 | 12 |
| Caswell NC | 83 | 0 | 0 | 0 | 2 | 2 | 0 | 1 | 0 | 0 | 1 |
| Newberry SC | 81 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| Currituck NC | 78 | 0 | 0 | 0 | 7 | 7 | 0 | 0 | 0 | 0 | 7 |
| Northampton NC | 77 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Craven NC | 76 | 0 | 0 | 0 | 2 | 2 | 0 | 2 | 0 | 0 | 0 |
| Pender NC | 76 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Harnett NC | 74 | 0 | 0 | 0 | 29 | 29 | 0 | 0 | 0 | 0 | 29 |
| Stanly NC | 73 | 0 | 0 | 0 | 34 | 34 | 0 | 0 | 0 | 0 | 34 |
| Davie NC | 71 | 0 | 0 | 0 | 13 | 13 | 0 | 0 | 0 | 0 | 13 |
| Hertford NC | 70 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Greene NC | 70 | 0 | 0 | 0 | 55 | 55 | 0 | 0 | 0 | 0 | 55 |
| Rowan NC | 69 | 0 | 0 | 0 | 17 | 17 | 0 | 2 | 0 | 0 | 15 |
| Jackson NC | 68 | 0 | 0 | 0 | 10 | 10 | 0 | 0 | 0 | 0 | 10 |
| Granville NC | 66 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Caldwell NC | 64 | 0 | 0 | 0 | 18 | 18 | 0 | 0 | 0 | 0 | 18 |
| Wake NC | 63 | 0 | 0 | 0 | 2 | 2 | 0 | 2 | 0 | 0 | 0 |
| Marlboro SC | 62 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Clay NC | 62 | 0 | 0 | 0 | 38 | 38 | 0 | 0 | 0 | 0 | 38 |
| Avery NC | 61 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Pasquotank NC | 61 | 0 | 0 | 0 | 32 | 32 | 0 | 1 | 0 | 0 | 31 |
| Marion SC | 59 | 0 | 0 | 0 | 51 | 51 | 0 | 51 | 0 | 0 | 0 |
| Calhoun SC | 57 | 0 | 0 | 0 | 13 | 14 | 0 | 0 | 0 | 0 | 14 |
| Lexington SC | 57 | 0 | 0 | 0 | 3 | 3 | 0 | 0 | 0 | 0 | 3 |
| Chowan NC | 56 | 0 | 0 | 0 | 13 | 13 | 0 | 0 | 0 | 0 | 13 |
| York SC | 55 | 0 | 0 | 0 | 22 | 22 | 0 | 0 | 19 | 0 | 3 |
| Tyrrell NC | 53 | 0 | 0 | 0 | 11 | 12 | 0 | 0 | 0 | 0 | 12 |
| Jones NC | 51 | 0 | 0 | 0 | 32 | 32 | 0 | 0 | 0 | 0 | 32 |
| Greenville SC | 50 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Horry SC | 48 | 1 | 0 | 1 | 2 | 4 | 0 | 1 | 0 | 3 | 0 |
| Greenwood SC | 46 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Columbus NC | 44 | 0 | 0 | 0 | 10 | 10 | 0 | 10 | 0 | 0 | 0 |
| Halifax NC | 42 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Georgetown SC | 41 | 0 | 0 | 0 | 10 | 10 | 0 | 0 | 0 | 0 | 10 |
| Jasper SC | 36 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Lee SC | 29 | 0 | 0 | 0 | 2 | 2 | 0 | 0 | 0 | 0 | 2 |
| Bamberg SC | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Orangeburg SC | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Wilson NC | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Darlington SC | 21 | 0 | 0 | 0 | 8 | 8 | 0 | 7 | 0 | 0 | 1 |
| Beaufort SC | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Cherokee NC | 20 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| Nash NC | 15 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Davidson NC | 14 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Abbeville SC | 13 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| Madison NC | 12 | 0 | 0 | 0 | 2 | 2 | 0 | 0 | 0 | 0 | 2 |
| Union NC | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Clarendon SC | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Lee NC | 11 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Lenoir NC | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Kershaw SC | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Watauga NC | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Chesterfield SC | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Dillon SC | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Surry NC | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Allendale SC | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Martin NC | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Moore NC | 6 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| Lancaster SC | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Graham NC | 6 | 0 | 0 | 0 | 2 | 2 | 0 | 0 | 0 | 0 | 2 |
| Yancey NC | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Yadkin NC | 4 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Saluda SC | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Edgefield SC | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Wilkes NC | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Stokes NC | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Hampton SC | 4 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| Richland SC | 4 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| Fairfield SC | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Hoke NC | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Duplin NC | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Vance NC | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| McCormick SC | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Wayne NC | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Warren NC | 3 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Dare NC | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Ashe NC | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Pamlico NC | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Montgomery NC | 2 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| Chester SC | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Alleghany NC | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Camden NC | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Macon NC | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Aiken SC | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Pipeline wiring (not yet in main.py)

See the report for the exact order. In short, after `enrich_liensnc_posthumous` (the other
cross-listing joins): `enrich_obituary_lookups` (network, off unless `OBITUARY_LOOKUPS=<n>`),
then `enrich_obituary_match`, then `enrich_heir_candidates`. The three new scraper slugs
(`public_notices.obituary_feeds`, `public_notices.echovita_obituaries`,
`public_notices.publicnoticesc_estates`) need `main.DATELESS_OK_SOURCES`, as
`funeral_home_rss` does, or `_active_only` drops every row (an obituary has no sale date).
