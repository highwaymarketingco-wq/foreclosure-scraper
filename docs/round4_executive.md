I'll write the executive layer directly from the six blocks provided.

**ROUND 4 DISCOVERY — EXECUTIVE SUMMARY**

---

## 1. DID THE PORTAL RE-SWEEP INVALIDATE EARLIER WORK?

**Partially. Rounds 1-3 undercounted, but not catastrophically.**

Seven of eleven NC counties run an ArcGIS Enterprise Portal whose item index was never queried: Buncombe, Gaston, Gastonia (city), Burke, Morganton (city), Lincoln, Transylvania. The pointer that finds them is `owningSystemUrl` on any on-prem REST root.

**Counties with services genuinely hidden from their REST folder listing: 5 of 11.**

| County portal | Hidden services | Nature |
|---|---|---|
| Morganton | 16 | Includes an entire second server host, `gis.morgantonnc.gov/image` |
| Transylvania | 11 | All cross-host (Brevard AGOL, NC DEQ, NC OneMap, NPS) |
| Buncombe | 6 | All return 499 Token Required — visible but walled |
| Burke | 5 | CitizenReporter FS+MS, map-metrics services |
| Spartanburg SC | 16 | All ImageServers on a second `/image` adaptor |
| Anderson SC | 15 | Geocoders, GP tools, Cartegraph tiles; `Municipal` folder is token-walled |
| Pickens SC | 1 | A hosted view absent from the public REST root |
| Gaston / Lincoln / Gastonia / Oconee / Laurens / Cherokee | 0 | Parity |

**What this actually exposed:** the portal-only delta is mostly *item types* (Web Maps, Dashboards, Experiences, Vector Tile Packages), not new data. Gaston's 249-item index yielded zero hidden services. Buncombe's 6 hidden services are all token-walled. The real net-new data came from the **AGOL hosted FeatureServer roots** (2,879 services, none linked from any county page), not from the portal indexes themselves.

**Verdict:** rounds 1-3 undercounted by roughly **25-40 usable sources**, concentrated in Burke (21,879 vacant parcels, 1,963 gov-owned), Buncombe (2.89M tax-history rows, 466K grantor/grantee, 4,043 geocoded jail bookings), Mitchell (4,557 parcels), and the Spartanburg `/image` adaptor. The **method** reproduces; the **prior counts** were low but the prior conclusions were not wrong.

**Query-form gotcha that caused the original miss:** `q=*` returns `total:0` on every portal tested. So do `q=owner:*` and `q=title:*`. Only `q=type:"Feature Service"` and `q=-type:"Code Attachment"` work anonymously. Earlier rounds almost certainly ran `q=*`, got zero, and concluded the index was empty.

---

## 2. VENDOR PATTERNS THAT PROPAGATED

**Sturgis/Avalon — the round's biggest single find. Propagates to 7 footprint counties net-new.**

The vendor publishes its own client directory with tenant GUIDs, which is the discovery endpoint the last three rounds were missing:

```
POST http://www.sturgisdigital.com/service.asmx/getClients
body: {"state":"NC"} | {"state":"SC"}     → 42 NC rows, 79 SC rows
```

Every GUID drops into `https://d1ebsyxxbc7tep.cloudfront.net/data/{GUID}/Wildfire/Records`.

| County | Total bills | UNPAID | Extra |
|---|---|---|---|
| Burke NC | 3,581,293 | 87,532 | |
| Oconee SC | 3,102,995 | 54,753 | 11,664 Tax Sale, 31,879 Delinquent |
| Spartanburg SC | 2,024,619 | 171,208 | 49 Tax Sale |
| Rutherford NC | 1,174,225 | 95,902 | already scraped |
| Cleveland NC | 1,115,654 | 127,037 | |
| Lincoln NC | 939,928 | 95,422 | |
| Pickens SC | 654,097 | 66,086 | 1,444 Tax Sale, 35,285 Delinquent |
| Gaston NC | 155,607 | 29,732 | |

Cherokee SC and Laurens SC resolve but return Total=0 (payments-only deployments). Six adjacent out-of-footprint NC tenants also verified live.

**Spartan probate — did NOT propagate.** Exhaustive negative: all 46 SC counties x 5 path suffixes on `govcloud2`, plus all 46 on `govcloud1`. Only **Anderson, Berkeley, Calhoun** exist. Every footprint SC county except Anderson returns hard 404. Agency-ID rule is derivable (`{2-digit county alpha code}500`) but there are only three tenants to derive for. **Do not retry this.**

**southcarolinaprobate.net — coverage on paper only.** 18 counties in the dropdown, but only Oconee and Cherokee are in-footprint, and the existing scraper's own docstring records that both return "no records." Those courts do not feed the index.

**Utility-phone layers and business-license phone/email:** not covered in the blocks provided. **UNVERIFIED — no propagation testing was reported for these two patterns in round 4.**

---

## 3. NEWSPAPER APIs

**Open WordPress REST, with real legal-notice yield: 2 papers.**

| Paper | County | Endpoint | Yield |
|---|---|---|---|
| **Pickens County Courier** | Pickens | `https://www.yourpickenscounty.com/wp-json/wp/v2/posts?categories=8&per_page=50` | **2,666 posts back to 2010-11-26.** Newest 200 contain 49 Notice-to-Creditors + 41 Legal Notice posts. Newest NTC alone = 17 estates with Estate, Date of Death, Case Number, PR name, **PR mailing address**. Legals carry foreclosure summons, wills-filed, towing liens |
| **Laurens County Advertiser** | Laurens | `https://www.laurenscountyadvertiser.net/wp-json/wp/v2/posts?categories=7486` | **1 rolling post = 330 estates** (79,859 chars): 330 case numbers, 332 PRs, 426 addresses, 97 attorneys. Plus 2,344 obituaries at cat 17 |

**Open REST, zero legal yield: 3 papers.** Tryon Daily Bulletin (Polk) cat 263 is real but holds 3 stale posts from 2015-2017 and no legals; obituaries cat 35 = 5,677. The Journal Online (Anderson) is open but has zero notices. Greenville Journal has no legal category at all.

**Gaffney Ledger (Cherokee):** `/wp/v2/posts` returns `[]` even unfiltered. Media lane only.

**Walls:** Gannett Presto WAF returns uniform 403 including on `/robots.txt` across 7 papers / 7 counties (Asheville, Hendersonville, Gaston, Shelby, Spartanburg, Anderson, Greenville). Six papers are TownNews/BLOX with no `/wp-json/`. Four papers DNS-fail.

**Blocking issue, needs a policy call not a code fix:** Laurens disallows `anthropic-ai` and `Claude-Web` but not `ClaudeBot`. The six TownNews sites disallow `ClaudeBot` specifically. **No single user-agent satisfies both.** Two live sources are stalled on this.

**Method correction that invalidates any `search=`-based build:** `X-WP-Total` from a `search=` query is not a notice count. WordPress core search is fuzzy OR-match across title and content. `thejournalonline.com?search=tax+sale` returns 373, all school-board editorial. Every count above was validated by fetching post bodies.

**Highest-value single build in round 4:** the Pickens Courier scraper. One endpoint, no auth, clean JSON, ~15 years deep, roughly 800+ decedents with PR mailing addresses in the newest 200 posts alone. That is the name-to-contact spine the resolver has been starved for. Parse by title prefix, split body on `Estate:`, read labeled fields. Do not filter with `search=`.

---

## 4. GREENVILLE VERDICT

**Net-new: 10 usable sources + 6 classified walls.** Six are genuine discoveries absent from every repo doc: Ownership History (1,127,578 rows), Assessment History (5,276,520 rows), Site Addresses (306,949 points), 4 free geocoders including a parcel-ID locator, the Tyler ROD migration, and the City of Greenville AGOL org (163 services, no distress layers).

**Leads it would add: ~32,800 distinct properties**, all live-queried.

| Segment | Count |
|---|---|
| Delinquent (TOTTAX>0, PAIDDATE null) | 5,014 |
| Absentee (mailing outside county) | 25,627 |
| Overlap | -918 |
| Probate decedents 2023-2026 | 12,284 raw, ~3,100-3,700 after name-to-parcel match |
| Foreclosure adverts | 722 banked, ~170/yr flow |
| **Total** | **≈32,800** |

Hard-distress core is **~8,500** (5,014 delinquent + ~3,400 matched probate + 170/yr foreclosure). The 25,627 absentee figure is an ownership signal, not distress, and should not be counted as leads.

**RECOMMENDATION: expand, but scoped and legally gated.**

Build the **parcel + tax-sale + MIE-advert trio** (~1 day). Defer probate until the name-to-parcel resolver improves past its 25-30% ceiling.

The reason this beats deepening the existing 18 counties: the Master-in-Equity foreclosure adverts publish **total judgment debt against a TMS that joins cleanly to the parcel roll**. Join verified end to end: `0560.12-01-076.00` → strip punctuation → PIN `0560120107600` → `CHILDS KATRINA`, FMV $330,050 vs judgment $242,079.31 = **$88K equity computed with zero deed OCR**. That directly attacks the engine's worst metric, equity coverage at 11.7%. It works here precisely *because* the ROD is walled: the newspaper prints what the deed would have told you. Deepening the existing 18 means grinding deed-of-trust OCR county by county for the same result.

**The gate:** Greenville is SC, so **§30-2-50** applies — the misdemeanor bar on using local-government records for commercial solicitation, already flagged in `honest_operator_manual.md` as needing an SC attorney's opinion. Adding the largest SC county concentrates exposure in exactly the jurisdiction where that question is unresolved. **Hold all SC mail volume until counsel rules.** Building the ingest is fine; mailing is not.

---

## 5. DEED MINING

**Counties supporting keyless date+type ROD sweep without a name: ONE verified, and it is robots-walled.**

| County | Platform | Date+type, no name? | Blocker |
|---|---|---|---|
| **Anderson SC** | ACPASS county CGI | **YES** (only verified) | `robots.txt` = `Disallow: /` — operator policy wall |
| Pickens SC | Harris AcclaimWeb | YES structurally | Requires accepting a disclaimer POST; **not accepted, not mine to accept** |
| Buncombe NC | Aumentum eSearch v4 | NO — guest menu is Quick Name Search only | Name required |
| Polk NC | Cott/Aumentum v4 | NO | Name required |
| Rutherford NC | Cott/Aumentum v4 | NO | 302 to login — contradicts docs, previously thought open |
| Cleveland NC | CCHS classic ASP | NO | 404 |

Anderson's working shape: `POST https://acpass.andersoncountysc.org/deedmain.cgi` with a mandatory `QryType`, then cursor-paged via `POST https://acpass.andersoncountysc.org/dedtypen.cgi` carrying `daten` + `instrnon`. **Without the cursor endpoint any sweep truncates at 25 rows** — the prior "25 rows" reading was page 1 of an unknown total.

**Earliest-firing instrument: HOA LIEN (code 193), 193 records.** It carries delinquent dues plus a street address in the free-text DESCRIPTION, and it fires before tax delinquency and long before foreclosure. Suppress with code 184 (MISC HOA SAT) when the lien is satisfied.

**Second-highest value per row: COURT ORDER (code 195), 17 records, finite.** Contains `ORDER ESTABLISHING HEIRS`, `ORDER DETERMINING HEIRS`, `ORDER QUIET TITLE` — the highest-value rows on the entire board.

Also live: MORTMODIFY (189) as a recorded-workout delinquency proxy, POA (020) for incapacity/absentee, MH AFF CERT (132) and MH SEV AFF (135).

**Three premise corrections that matter:**

1. The **Amount field is empty** on every detail page sampled (8 pages, spanning DEED / MORT / HOA LIEN / COURT ORDER). Dollar figures live only on the scanned image. This confirms the existing repo finding at `blocked_sources_forensic.md:175`.
2. **No PR / EST / EXECUTOR / HEIR role tags exist.** Only GRANTOR/GRANTEE and MORTGAGOR/MORTGAGEE. The estate signal is carried in free-text DESCRIPTION.
3. **"144 codes" is a legacy vocabulary, not 144 facets.** 38 tested over 24 months: 16 return rows, 22 return zero.

**Keep the memory note "lien and distribution-deed mining is BLOCKED" — but for a harder reason than recorded.** It is not waiting on a ROD rebuild. The instruments **do not exist in this ROD**: no code for mechanics lien (SC routes to Clerk), tax lien, lis pendens (Clerk, §15-11-10), foreclosure deed (recorded as generic DEED, value-exempt under §12-24-40(13)), deed of distribution, deed in lieu, or notice of default. Substitution of trustee **cannot exist** — SC is a judicial-foreclosure mortgage state with no deed of trust and no trustee. That is an NC-only instrument.

---

## 6. ROUND-4 SCOREBOARD + RUNNING TOTAL

| Round | Sources |
|---|---|
| R1 | 251 |
| R2 | ~234 |
| R3 | 278 raw |
| **R4** | **~185 raw / ~120 net-new after dedupe** |
| **Running total** | **~948 raw, ~830 net distinct (approximate)** |

R4 breakdown by block:

| Block | Raw | Net-new |
|---|---|---|
| NC portal re-sweep + AGOL roots | ~55 | ~25-40 |
| SC filtered-directory re-sweep | ~24 | ~8 |
| Spartan probate + Sturgis | ~30 | ~25 (Sturgis 7 in-footprint + ~20 out) |
| Newspaper APIs | ~20 | ~6 usable |
| Greenville | ~16 | 10 usable + 6 walls |
| Deed mining | ~24 | 16 live codes + 1 verified sweep county |

**Flag on the running total:** the R1-R3 counts are "raw sources touched," and R4 proved that at least three prior entries were misclassified (Rutherford ROD marked open is actually login-walled; `thejournalonline.com` listed under "no API" has open REST; `yourpickenscounty.com` filed as a static HTML page is a 2,666-post archive). **The cumulative figure is directionally useful and should not be quoted as precise.** A dedupe pass against the registry would move it.

---

## 7. HONEST GAPS — AND SHOULD DISCOVERY STOP?

**Yes. Discovery should stop, or drop to a maintenance cadence.** Round 4 is the inflection point.

The evidence: R4's genuinely new *categories* number two (Sturgis tax-bill API, newspaper legal-notice REST). Everything else was depth on known categories or corrections to prior entries. The correction-to-discovery ratio inverted this round — R4 spent as much effort disproving prior claims as finding new ones. That is the signature of a search that has converged.

**What remains open, ranked:**

1. **The crawler-identity policy call.** Two live newspaper sources are blocked by conflicting robots directives with no UA that satisfies both. This is a decision, not a discovery task. **Blocking.**
2. **The §30-2-50 SC attorney opinion.** Unresolved since `honest_operator_manual.md`. Now gates ~32,800 Greenville leads plus all existing SC mail volume. **Blocking, and it has grown more expensive with every SC county added.**
3. **The Pickens Acclaim disclaimer.** A structurally-open date+type ROD sweep sits behind a terms click-through that an agent should not accept. **Operator decision.**
4. **The Anderson `Disallow: /`.** Same shape. The one county with a working keyless deed sweep has posted a blanket crawl exclusion. **Operator decision.**
5. **Name-to-parcel resolver ceiling at 25-30%.** This now caps Greenville probate (12,284 → ~3,400), Pickens Courier NTC output, and the Laurens 330 estates. **This is the highest-leverage engineering work left, and it is worth more than any further discovery.** Every source found in R4 that yields names rather than parcels is throttled by it.
6. **Equity coverage at 11.7%.** The MIE-advert judgment-debt join is the first proven no-OCR path to fixing it. Whether that pattern exists outside Greenville is untested.
7. **Utility-phone and business-license phone/email propagation.** Named in the brief but **not covered in any round-4 block — UNVERIFIED, no testing reported.** If these matter, they are the one legitimate remaining discovery item.

**Recommended next move: stop hunting, start building.** The board has more sources than the pipeline can act on. The binding constraints are now (a) two legal/policy decisions the operator must make, and (b) the resolver's name-to-parcel ceiling. Neither is solved by finding a 949th source.

**Housekeeping:** nothing was written to the repo across any round-4 block, no git operations ran, and the engine was not run. No CAPTCHA or WAF was bypassed; Gannett's 403, the robots walls, and the disclaimer gates were classified and left alone. No sensitive PII was encountered — the Notice-to-Creditors records carry decedent name, date of death, case number, and adult PR name and mailing address, all statutorily published under SCPC 62-3-801. Probe harness at `/private/tmp/claude-502/-Users-cashhigh-Desktop/f9f41c0e-c1d7-4991-a803-581317d111fe/scratchpad/probe.py`; full 144-code dump at `/private/tmp/claude-502/-Users-cashhigh-Desktop/f9f41c0e-c1d7-4991-a803-581317d111fe/scratchpad/and_deeda.cgi_SearchType_L.html`.