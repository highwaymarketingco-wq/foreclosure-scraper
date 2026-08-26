# MASTER: Gaps, Walls, Skip-Tracing, and the Manual Lanes

**One doc, everything.** What the engine cannot get and why, what a human does by hand and the exact steps, what is genuinely missing on the board, and the hard rules. Built 2026-08-18 against the live committed board (`data/checkpoint/board.json.gz`, 40,702 leads) and the forensic wall reference. Where a number is a live count it is stated as such. Style: no em dashes, colons and parentheses only.

**Read this first, then `docs/blocked_sources_forensic.md` for the row-level detail (123 rows).** This doc is the map. The forensic doc is the territory.

---

## 0. THE HARD RULES (never break, no matter who asks)

1. **FREE and PUBLIC only.** Everything the robots pull is free public data reached through ordinary public search. No paid APIs, no paid unblockers (Bright Data, residential proxies), no paid CAPTCHA solvers, no paid skip-trace, no paid broker data (PropStream, ATTOM, OpenCorporates, NCOALink, Trepp, UniCourt, Trellis). If it costs money to get, it is out of scope for the automated engine. The operator may buy data as a business decision, but the engine does not.
2. **The compliance line.** Fingerprinting stealth that runs the page's own JS (curl_cffi impersonate, StealthyFetcher / patchright) is permitted. Defeating a CAPTCHA, a login wall, a WAF bot-check, or a ToS scraper-prohibition is NOT, even when directed to. A smarter model does not change this. The wall is code plus policy, not horsepower.
3. **No logins the robot holds.** The engine does not log in behind a wall or store credentials to sustain automation. The human operator, as the account holder, may log in and save pages by hand (the manual lane, Section 5). The robot only parses what the human saved.
4. **DEAD means "dead the day it was probed," not "dead forever."** Re-verify every DEAD / CANT source live before believing it. This session alone, two sources on the dead list (irsauctions.gov, Meares) turned out live. Do not let a July stamp stop a re-probe.

---

## 1. SKIP-TRACING AND CONTACTABILITY (the #1 ceiling, and it must stay free)

Contactability is the single biggest cap on the engine, and it is a compliance ceiling, not a missing source. You cannot buy your way past it inside the rules, so the whole design is free-channel skip-tracing.

### Live yields on the board
| Field | Fill | Meaning |
|---|---:|---|
| owner_mailing | 74.5% | The scaled outbound channel. Direct mail reaches 3 of 4 leads. |
| skip_trace ran | 71.0% | Attempted on most leads. |
| **owner_phone yielded** | **21.4%** | Only 1 in 5 leads gets a real phone, free. This is the wall. |

### The free skip-trace channels that ARE wired (do not rebuild these)
- **`enrichment_voter_phone.py`** — NC voter file (NCSBE free bulk download). `full_phone_number` column ~69% populated. Matches owner-OCCUPANT by name AND street, near-zero false positives. This is the one free, ToS-clean personal-phone source. Absentee owners will not match here by design.
- **`enrichment_county_phone.py`** — County-published owner phone + mailing on open ArcGIS tables, parcel-keyed. Buncombe Accela ParcelOwner table = 135,079 owner rows, 73,965 with a phone, straight parcel join. Beats the voter lane for absentee / LLC / trust / estate owners. Config-driven, add counties as their tables surface.
- **`enrichment_owner_mailing.py` / `sc_parcel_mailing.py` / `mailing_shape.py`** — Owner mailing address from county GIS, the direct-mail spine. Absentee / out-of-state mismatch is both a distress signal AND the reason mail is the primary channel.
- **`enrichment_skip_trace.py`** — Provider-pluggable, default `tax_records_only` (FREE, cross-references defendant name + property to county tax records). Paid providers exist as plug points but are OFF and stay off.
- **`contact_ingest.py`** — Ingests contact data the OPERATOR exports by hand from their own free account (e.g. a free PropWire export). Compliant because the human pulls it.

### What is WONT (paid or bot-walled skip-trace, do not chase)
TruePeopleSearch, FastPeopleSearch, Radaris, Whitepages: all Cloudflare-403 or paywall-teaser + ToS ban on automation. PropWire skip-trace: DataDome + account-gated third-party PII. These have a working bypass or a checkout button, which is exactly why they are off-limits. The compliant answer is direct mail + the free voter/county phone lanes above.

### The honest takeaway
Phone caps around 21% free. Mail reaches 74%. To lift phone you would have to either cross the paid/PII line (not allowed) or the operator pulls contacts by hand from their own accounts (`contact_ingest.py`). Hermes cannot raise this with more sources.

---

## 2. THE LIVE GAPS ON THE BOARD (what is actually thin, with real numbers)

Board = 40,702 leads. NC 22,872 / SC 17,830. These are the current committed-board fill rates (the running job lifts CAMA / phone / resolver further when it lands).

### Solved (do not spend time here)
| Field | Fill |
|---|---:|
| Street address | 98.0% |
| Owner name | 92.5% |
| Valuation computed (raw.calc) | 91.3% |
| Grade / intent score | 77-91% |

### The real ceilings (this is where the work is)
| Field | Fill | Why it is stuck |
|---|---:|---|
| **owner_phone** | **21.4%** | Contactability wall (Section 1). Free channels only. |
| Owner mailing | 74.5% | The workaround: mail, not phone. |
| **Resolved parcel** | **72.5%** | ~11k leads not welded to a hard parcel. Name→parcel matching ceiling ~25-30%. Code problem, not a source. |
| **Real CAMA building specs** | **32.0%** | 2/3 of valuations lean on proxies → noisy ARV. The assessor-card grind lifts this. SC exempt-deed sqft is ABSENT. |
| **Equity known** | **30.2%** | Needs value + loan/lien. Debt side is partly ABSENT. |
| tax_owed $ | 37.3% | Delinquent dollar figure. Partly extraction gap, partly ABSENT (NC power-of-sale debt). |
| amount_owed | 61.8% | Judgment / assessed / opening-bid derived. |
| Vision (photo condition) | 32.7% | Bounded by photo supply. |

### Per-county coverage — NO HOLES (verified against config.py allow-list)

The footprint is exactly **18 counties** (the allow-list in `src/foreclosure_scraper/config.py`; everything else is denied, many by explicit user direction). Do NOT invent target counties. The list:
- **SC (7):** Spartanburg, Anderson, Pickens, Oconee, Cherokee, Union, Laurens
- **NC (11):** Rutherford, Cleveland, Henderson, Polk, Gaston, Buncombe, Transylvania, McDowell, Lincoln, Mitchell, Burke

**Every in-scope county has board coverage. There are zero county holes.** Counts: Spartanburg 9,224 / Buncombe 6,836 / Rutherford 4,952 / Pickens 2,850 / McDowell 2,282 / Lincoln 1,612 / Oconee 1,691 / Henderson 1,569 / Anderson 1,275 / Laurens 952 / Cherokee 606 / Union 495 / Gaston 361 / Cleveland 271 / Polk 236 / Transylvania 228 / Burke 212 / Mitchell 142. The lowest (Mitchell, Burke, Transylvania, Polk, Cleveland) are thin because they are small rural counties, not because a source is missing.

**Explicitly DENIED, do not build (per user direction):** Greenville SC, Horry SC (Myrtle Beach), Haywood/Madison/Yancey NC, Mecklenburg + all Charlotte-adjacent + eastern/coastal NC (New Hanover, Brunswick, Onslow, etc.), Newberry/Greenwood/Abbeville SC. If a source only serves these, skip it.

### Distress-signal coverage (the catalog is broad; the thin ones are walled)
Present and healthy: recorded_debt (22,806), absentee (13,377), tax_delinquent (12,331), tax_lien (11,442), distressed_condition (6,273), probate/estate (5,698), vacant (3,488), tax_sale (3,268), lis_pendens (2,736), out_of_state (2,566), code_enforcement (939), condemned (734), STR-lapsed (581), foreclosure_sale (521), incarceration (243), storm_damage (174), bankruptcy (148), divorce (92), upset_bid (84).
Thin or missing signals, and why: **eviction** (SC magistrate rosters ABSENT, Section 4), **divorce** (only 92, NC-only; SC Family Court is access-restricted), **builder_distress** (LiensNC, manual lane), **bankruptcy_stay** (built this cycle). The gaps in the signal catalog are the ABSENT-walled ones, not buildable ones.

### The extraction gaps (buildable yield sitting on the floor)
~25 scrapers fetch data then drop it (phones, values, parcel_ids, names not persisted). Queue lives in `docs/extraction_gaps.md`. This is free yield already being fetched, just not saved. Higher ROI than hunting a new source.

### The missing layer that is not a source at all
**No act-on-it layer.** The engine produces and grades leads; nothing fires them into outbound (no CRM, no mail-merge, no dialer handoff). This is a separate build (the n8n idea in the notes), not something more sources close.

---

## 3. WONT — a bypass exists, we refuse it (compliance choice)

These have a working bypass or a checkout button. We decline. The operator can pull them by hand (Section 5) or pay, as a business choice.

| Source | The wall | Your manual step |
|---|---|---|
| SC PublicIndex broad sweep | ToS bars automated/repetitive querying; Rule 610 is per-held-case; F5 + CAPTCHA | Manual save per county → `scripts/ingest_publicindex_files.py` |
| NC eCourts power-of-sale lane | Real browser works but rides a human-solved AWS-WAF CAPTCHA | Manual save → offline parser |
| Consumer people-search (phone) | Cloudflare-403 / paywall + ToS ban | Direct mail + free voter/county phone (Section 1) |
| PropWire | DataDome + account-gated PII | Export from your own free PropWire account → `contact_ingest.py` |
| Cott RecordRoom (Rutherford/Polk ROD) | Subscriber login | Paid subscriber, or Union probate via `cott_recordroom.py` |
| Cherokee / AcclaimWeb ROD images | Subscriber / login wall | Paid, or skip |
| SC SoS entity search | CAPTCHA | NC SoS is free (`enrichment_sos_agent`); SC by hand |
| GSA realestatesales.gov JSON API | 302 → login | Not needed, the HTML `/our-listing/` index works |
| US Marshals real property | 403 | Covered via Bid4Assets |
| Sites whose robots.txt names ClaudeBot / GPTBot | robots Disallow | SeeClickFix (511 cases), Transylvania Times TNCMS (2,301 notices): do not scrape |
| Kofile / Oconee ROD, Anderson ACPASS, Rutherford Sturgis/Avalon | robots Disallow: / | Manual, or per-parcel by hand |
| landwatch / land.com | Akamai (robots.txt itself 403s) | Skip; land covered via landandfarm/landsofamerica |

---

## 4. CANT / DEAD / ABSENT — technical wall, dead site, or data that does not exist

### CANT (technical, no free path found; a paid unblocker MIGHT crack some)
| Source | Blocker | Your step |
|---|---|---|
| NC eCourts Smart Search estates + divorce | AWS-WAF escalating image-grid CAPTCHA (vision solver clears 2, WAF issues more) | Manual save, or skip estates (permanent) |
| Cherokee SC delinquent tax | Cloudflare 403 | Re-probe each cycle |
| Spartanburg / Laurens delinquent-tax URLs | 404 (CivicEngage CMS migration) | Re-probe; find new URL |
| Union SC delinquent tax | DNS failure | Re-probe |
| Anderson tax balance (ACPASS) | 403 auth-gated | Per-parcel by hand |
| **SCDOT SC_Parcels** | now token-walled, silent 200 + error | Situs resolver degraded; parcel-cache (`project_parcel_cache`) is the workaround |
| CCHS ROD (Burke/Lincoln/Cleveland/Henderson) | DECOMMISSIONED, IIS-404 | Find county's new provider |
| PropWire, mewborn_deselms | DataDome / Cloudflare 403 | Onslow covered via Column |
| DealStream, BusinessesForSale | DataDome / Cloudflare 403 | none |
| LoopNet (res + MF), auction.com MF | hard 403 / login | Crexi (only free MF source) |

### DEAD (decommissioned; re-verify before trusting, per Rule 4)
homesales.gov (HTTP 000), US Marshals (403), GSA `/api/properties` (302 login), SBA REO (no portal), dead GovDeals API key (HTTP 400, re-discover from live JS bundle), Gaston "delinquent taxes" doc (a library flyer), Burke NCPTS delinquent tenant (now zero blobs).
**Proven-stale this session:** irsauctions.gov (now live, built), Meares / mpa-sc.com (now live, built). Re-probe the rest.

### ABSENT (structurally not published; nobody free or paid extracts what does not exist)
| Data | Why | Only route |
|---|---|---|
| SC deed sale price on exempt deeds | SC §12-24-70 states no value | Per-parcel qPublic CARD, or paid CAMA extract |
| NC power-of-sale debt $ | Statute puts only terms/deposit/upset in the notice | Clerk's office in person |
| SC magistrate eviction rosters | County-operated, no free bulk feed; portal exposes only Circuit types | FOIA Chief Magistrate, or LSC data-share (civilcourtdata@lsc.gov) |
| Live mortgage payoff balance | Servicer PII | The servicer only |
| SC Family Court divorce | Separate access-restricted system, not on the public portal | Paid UniCourt/Trellis, or newspaper classifieds |
| SC heated sqft / SaleAmount on free GIS | Blank across every free SC layer | qPublic card, or paid extract |
| Structured investor buy-box | Does not exist as a feed | Built by hand (curated registry) |

---

## 5. THE MANUAL LANE (what the human operator does by hand, step by step)

The compliant pattern for every walled source: the OPERATOR (as account holder / human) opens the site, runs the search, saves the page or exports CSV, drops the file in a folder, and an offline parser ingests it. The robot never logs in or defeats the wall.

### LiensNC (builder / investor distress) — `scripts/ingest_liensnc.py`
1. Log in at apps.liensnc.com. Run **Advanced Search by county + date range** (last ~90 days). No keyword needed, just county.
2. In results, the **"Active Related Filings? = Yes"** column flags the clusters (over-leveraged flippers, contractors lining up).
3. For a Yes-project, open the **Related Filings Report** (Action menu) → **DOWNLOAD → CSV**. This lists every contractor on that project.
4. Drop the CSV (or save the results page as HTML) into a folder → run `ingest_liensnc.py`. Clusters are tagged `builder_distress`.

### SC PublicIndex — `scripts/ingest_publicindex_files.py`
1. Log in, search per county (lis pendens, foreclosure, probate, tax).
2. Save the results page (Ctrl-S, "Webpage, HTML only"). Note: saved HTML has the LIST, not per-case detail (detail is dead `__doPostBack` JS). Save a detail page only when you need one specific dollar amount.
3. Drop → parse offline.

### NC eCourts — offline parser
Open Judgment Search (JSON, lis-pendens + divorce) works. Smart Search (estates) is WAF-walled. Save what you can, parse offline.

### Operator run buttons (no terminal)
Desktop "Run Foreclosure Engine.app" (`gui_run.sh`), "Ingest Saved Court Pages.app" (`ingest_saved.sh`), Tue/Fri weekly popup (`prompt_run.sh`). Board-writer mutex prevents an ingest colliding with a full run.

---

## 6. WHAT "100%" ACTUALLY MEANS (the honest ceiling)

County coverage is already COMPLETE (all 18 in-scope counties have leads, Section 2). So Hermes's remaining source work is NOT filling county holes. It is: working the extraction-gaps queue (data already fetched then dropped), and re-verifying the DEAD/CANT list to recover any source that has come back online. That is real but bounded work.

The larger ceiling is NOT sources at all, and Hermes cannot close it with scrapers:
1. **Contactability** capped ~21% phone / 74% mail (free-only ceiling).
2. **Resolver** at 72.5% parcel (matching-code ceiling ~25-30% on name→parcel).
3. **Valuation depth** at 32% real specs / 30% equity (the assessor-card grind + the SC ABSENT sqft wall).
4. **ABSENT data**: debt $, mortgage payoffs, magistrate evictions, exempt-deed prices, SC family-court divorce. Permanent, unfixable at any budget inside the rules.
5. **The act-on-it layer**: a separate build, not a source.

So the honest statement: after Hermes sorts sources you are source-complete and county-complete, not engine-complete. Anyone who says "sources done = 100%" is wrong by about 30%, and that 30% is where the deals actually get worked.

---

## 7. DOC MAP (where the detail lives)

- **`docs/blocked_sources_forensic.md`** — 123 rows, the row-level authority: Source | Category | Bypass that would work | Exact error | Why | Your manual step.
- `docs/SOURCE_REGISTER.md` Section 4 — the WONT/CANT/ABSENT/DEAD index into the above.
- `docs/manual_source_inventory.md` — definitive count of every walled/manual portal x county x signal.
- `docs/manual_playbook_and_limits.md` — Part 2: exact click-paths, what each save gives you, where to drop the file.
- `docs/honest_operator_manual.md` — walls re-probed live (~65 endpoints).
- `docs/operator_playbook_liensnc_and_bankruptcy.md` — LiensNC + bankruptcy cross-reference, step by step.
- `docs/extraction_gaps.md` — the fetch-but-drop queue.
- `docs/hermes_blueprint.md` — the full engine brief for a zero-context agent.

**Currency note:** these carry different probe dates (blueprint 2026-07-03, honest-manual 2026-07-31, register Section 4 through 2026-08-06, this doc 2026-08-18). Treat dates as "true when probed." Re-verify DEAD/CANT before acting.
