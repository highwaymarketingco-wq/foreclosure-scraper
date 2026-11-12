# SC owner phone and email: what free, public, legal routes exist (research, 2026-09-21)

Scope: attach a phone number or email to an SC property owner using only free, public, legal sources. Everything below was checked by fetching on 2026-09-21 unless it says otherwise. Nothing was purchased, no message was sent, no board write or board load was done, no CAPTCHA or challenge was bypassed. Requests were one at a time with a sleep between them.

## 1. Bottom line

1. **No free, public, legal route gets SC phone coverage above about 1 percentage point.** The three big candidates are dead for phone: the SC voter file has no phone column and costs $25 to $2,500, the SC Secretary of State filing search sits behind reCAPTCHA and shows no phone or email even when it works, and none of 13 readable SC county parcel layers has a phone field.
2. **The SC phone number on the board today is mostly wrong, not just low.** In the rows I read, 217 of 224 SC phones (97 percent) come from `enrichment_sc_voter_xref` (a first-name plus last-name match against the NC voter file). Only 3 of those 217 owners have an NC mailing address, 201 mail to an SC address, and for 159 (73 percent) the voter name that was matched does not appear in the row's current owner name. These are stranger phones. Section 2 has the numbers. The honest usable SC phone rate on this sample is 7 of 1,815 rows (0.4 percent), and those 7 are agent, attorney and listing contacts, not owner numbers.
3. **`scripts/enrich_board.py` still calls `enrichment_free_phones` (line 762)**, which drives a stealth browser at TruePeopleSearch and FastPeopleSearch. Both are excluded (Section 5, route 10). The docs say the module is dormant on purpose; the script disagrees.
4. **The only lever that moves SC phone by double digits is paid skip tracing.** Verified price: Tracerfy $0.02 per successful result, no charge for misses. SC HOT (668) costs at most $13. SC HOT plus WARM (23,623) costs at most $472 for the numbers. Expected lift is roughly +18 to +23 points of all SC rows if the match rate is 60 to 75 percent (an assumption, not measured for SC).
5. **Mail is the better free channel and it is fixable.** Mailing address is the taxpayer-of-record address, a fact, not a guess. Three SC counties (Laurens, Union, Oconee) publish mailing addresses on layers we already query and could add about 3 to 4 points of SC mail coverage. Sending is not free ($0.65 postage per postcard before print).
6. **One legal item the owner should decide, not me:** S.C. Code 30-2-50 bars using personal information obtained from a state or local government for commercial solicitation. It covers assessor mailing addresses, which the board already carries, as much as it would cover a purchased voter file. Section 4.
7. **I built nothing.** No route cleared "clearly viable". Section 9 explains and gives the spec for the one thing I would build next (an identity gate for the existing xref phones).

## 2. The SC phone on the board is mostly unreliable

Method: the first 2,000 rows of `docs/listings.json.gz` through `iter_board_rows` (no `load_board`). 1,815 are SC. This window is not random: 1,231 are `spartanburg_vacant`, 528 `cherokee_delinquent_tax`, 27 bankruptcy, the rest small. Treat the counts as evidence of a defect, not as board-wide rates.

| Measure | Value |
|---|--:|
| SC rows read | 1,815 |
| SC rows with `raw.owner_phone` | 224 (12.3%) |
| of those, source `ncsbe_voter_xref` | 217 |
| of those, source `homeharvest_agent` (listing agent) | 6 |
| of those, source `notice_contact_attorney` | 1 |
| xref rows whose owner mails to an SC address | 201 (93%) |
| xref rows whose owner has an NC mailing address | 3 (1.4%) |
| xref rows where the matched voter first+last name is in the current `owner_name` | 58 (27%) |
| xref rows where it is NOT in `owner_name` | 159 (73%) |
| xref rows where it is nowhere in owner_name, defendant, owner_cluster, owner_mailing, skip_trace | 129 (59%) |
| xref rows where the current owner is an entity (LLC, Inc, a VFW post) | 37 (17%) |
| xref phone area codes that are NC | 175 (81%) |
| xref phone area codes that are SC (803, 843, 864) | 5 (2%) |

Two examples of the entity problem, no personal names: a VFW post owner carries a phone matched to a personal name unrelated to the post, and an "LLC" owner carries one matched to a different personal name. The module cannot produce these from the current owner name, so the phone was stamped when `owner_name` held something else. Two candidate causes, not established: (a) `enrich_board.py` runs `sc_voter_xref` (step 3ag-bis) before the owner-mailing resolver promotes assessor owner names, and the non-clobber check (`if raw.get("owner_phone"): continue`) then keeps the stale phone; (b) the 2026-09-14 note in `docs/WEEKEND_LOOP_QUEUE.md` said the lane was left unrun pending a decision, but the phones are on the published board, so it ran afterward through `enrich_board.py` or `merge_voter_footprints.py`.

Why the lane cannot be right even when the name matches: an active NC voter has to live in NC. A Spartanburg owner who receives tax mail at a Spartanburg address and shares a first and last name with one voter in 13 western NC county files is, in almost every case, a different person. The 2026-09-14 note measured an 8.1 percent match rate on a random 1,500 rows and flagged this; only 47 of 121 matches were even in NC-border counties.

The NC name-plus-county-unique fallback in `enrichment_voter_phone.py` (matches 2 and 4) has the same weakness for NC absentee owners. I did not measure it.

To size this on the full board (one read-only pass, about 7 seconds and 295 MB, the owner's call, not mine): count rows where `state == "SC"` and `raw.owner_phone.source == "ncsbe_voter_xref"`.

## 3. How phones get onto the board today

| Lane | State | Source | What it needs | Result |
|---|---|---|---|---|
| NC voter file, name plus address | NC | NCSBE bulk file, `full_phone_number` column, 13 footprint county files cached in `data/ncvoter/` (dated Jun 28) | owner-occupant whose name and house number and street match an ACTIVE voter | high precision, about 69% of NC voters carry a phone per the module docstring |
| NC voter file, name plus county unique, fuzzy | NC | same | one voter with that name in the county | lower precision, catches absentees |
| County-published owner phone | NC | Buncombe Accela ParcelOwner (73,965 rows with phone), Lincoln taxpayer table | parcel id | parcel join, no name guessing; Buncombe reads 65% phone |
| Surfaced contacts | NC and SC | attorney and trustee phones in notices, HomeHarvest listing-agent phones | already on the page | contact is an agent, not the owner |
| `liensnc` | NC | lien-agent appointment filings | n/a | 46,989 rows at 100% phone and mail. Lead-checked 2026-09-21 on three rows: the phone and email come from the filing's own owner block (owner_text), so it is the OWNER's phone, typically a builder or developer, not the filer. NC reads 61% with it and 20% without |
| SC voter xref | SC | NC voter file, name only | unique name in NC | see Section 2 |

NC works because NCSBE publishes a free statewide file (522,471,884 bytes, HEAD on `s3.amazonaws.com/dl.ncsbe.gov/data/ncvoter_Statewide.zip`) whose layout has a phone column (`layout_ncvoter.txt`: `full_phone_number varchar(12)`), plus one county that publishes its own owner table. SC has neither.

From the audit (section 15, 09-21 board): SC 77,036 rows, phone 2%, mail 37%. NC without `liensnc` 46,041 rows, phone 20%, mail 79%. SC footprint counties run 3% to 9% phone.

## 4. Legal frame (read this before any SC outreach)

**S.C. Code 30-2-50(A)** (fetched from scstatehouse.gov/code/t30c002.php): a person or private entity shall not knowingly obtain or use personal information obtained from a state agency, a local government, or another political subdivision of the State for commercial solicitation directed to any person in this State. Penalty, 30-2-50(D): misdemeanor, fine up to $500, imprisonment up to one year, or both.

- **Personal information** (30-2-30(1)) includes name, home address and home telephone number.
- **Commercial solicitation** (30-2-30(3)) means contact by telephone, mail or email "for the purpose of selling or marketing a consumer product or service". Four exclusions: credit union membership, continuing education notices, banking, insurance and securities services under Gramm-Leach-Bliley, and political contact using voter registration data.
- Agencies must put a notice on every records request. The SC Election Commission list-sale page and the LLR list request form both carry it.
- Open question I cannot answer: whether a cash offer to buy a house is "selling or marketing a consumer product or service". The buyer side arguably is not, the foreclosure-relief framing arguably is. This is a question for SC counsel. It applies to assessor mailing addresses already on the board, not only to anything new.
- Federal datasets (FMCSA, NPPES, FCC) and OpenStreetMap are not "state agency, local government, or political subdivision of the State" sources, so 30-2-50 does not reach them on its face. TCPA, National DNC and CAN-SPAM still apply to any call, text or email.

I am not a lawyer and this is not legal advice.

## 5. Route by route

Coverage column: matches or hits on the 20-lead sample in Section 6 unless stated. Verdicts: VIABLE, PARTIAL, WALLED, EXCLUDED.

| # | Route | URL checked | What it returns | Coverage | Legal and access | Verdict |
|--:|---|---|---|---|---|---|
| 1 | SC Election Commission voter list | scvotes.gov/resources/sale-of-voter-registration-lists/ | Name, address, race, gender, date of birth, reg number and date, county, precinct, districts, vote history. **No phone, no email.** $25 base; $25 plus $1 per 200 records for 5,001 to 50,000; $275 to 75,000; then $275 plus $75 per 25,000, capped at $2,500 (3,424,156 voters). CSV download. | 0 phones | Buyer must be a registered SC voter (7-3-20(D)(13)). Page carries the 30-2-50 notice. | WALLED for phone |
| 2a | SC probate index | southcarolinaprobate.net/search/ (WebFetch), greenvillecounty.org/appsas400/Probate/ | Case number, case name, party, type, filing date, county, appointment date, claim deadline, status. No address or phone in the index. Filings sit behind a copy shopping cart. | 0 phones | No login or captcha stated. `curl` with a real User-Agent got HTTP 403 from southcarolinaprobate.net, so I stopped there. | WALLED for phone (useful for heir names only) |
| 2b | Register of Deeds | not re-fetched today; prior repo work (`project_rod_document_images`, `project_sc_deed_ocr_yield`) | Grantor and grantee names, images; images are scanned and carry no owner phone | n/a | Deed images are free; OCR yields loan amount and address, not phone | WALLED for phone |
| 3 | SC Secretary of State filings | businessfilings.sc.gov/BusinessFiling/Entity/Search | Registered agent and registered office, per sos.sc.gov. **No phone, no email.** Page HTML loads `recaptcha/api.js` with a `g-recaptcha` container and the string "captcha, please search again". No bulk file or API is described on sos.sc.gov. | 0 | reCAPTCHA is a wall. There is no SC equivalent of the NC agent enricher that avoids it, and even without it the record has no phone. | WALLED |
| 4 | County assessor and treasurer layers | 15 ArcGIS layers the repo already queries (list below) | Owner, mailing, situs, values. Field metadata (`?f=json`) checked for `phone|tel|fax|mobile|cell|email|contact`. | 13 readable layers, **0 phone or email fields** (2 unreadable: Calhoun timed out, Charleston layer 1 returned no field list) | Free, public, but 30-2-50 applies | WALLED for phone, useful for mail |
| 5a | SC LLR license lists | llr.sc.gov/res/PDF/Licensee List Request - RBC.pdf | $10 per board list, by check to a PO box, with a signed intended-use statement citing 30-2-50. Fields not stated on the form. Online lookup (verify.llronline.com) redirect-looped on fetch. | not sampled | Manual, mailed check, attestation | WALLED (also tiny: only licensed owners) |
| 5b | SC Notary search | search.scsos.com/notaries (per web search) | Name, county, commission expiry. No phone. | 0 | Public | WALLED for phone |
| 5c | SC Bar directory | scbar.org find-a-lawyer returned 404 on fetch | Not verified | n/a | n/a | UNVERIFIED, negligible |
| 5d | SC courts Public Index, C-Track | publicindex.sccourts.org returned HTTP 400 on fetch | Per search results, Judicial Department terms bar screen scraping and automated repeated querying; litigation over this is in the public record | n/a | Terms wall | EXCLUDED |
| 6a | FCC ULS amateur licenses | data.fcc.gov/download/pub/uls/complete/l_amat.zip (197,768,321 bytes, not downloaded); daily file `daily/l_am_mon.zip` (17,154 bytes) inspected then deleted | `EN.dat` has phone and email columns in the layout. In the 124-row daily file: **0 phone values, 0 email values** | 0 of 124 | Federal, public | WALLED in practice (columns empty) |
| 6b | NPPES NPI Registry (health providers) | npiregistry.cms.hhs.gov/api/?version=2.1 | Practice and mailing address with `telephone_number`. Tested: a common-name query returned 5 SC providers, all with phones, different people. | 0 of 14 sampled persons returned any SC candidate | Federal, public, free, JSON | PARTIAL, low yield, needs city corroboration |
| 6c | FMCSA Company Census | data.transportation.gov/resource/az4n-8mr2.json (Socrata, no key) | `legal_name, dba_name, phone, cell_phone, email_address, phy_city`. **SC: 62,750 records, 61,284 with phone (98%), 43,695 with email (70%).** | 0 exact matches of 20; 3 name-only candidates, none city-corroborated | Federal, public, free | PARTIAL, low yield, phone and email |
| 6d | USPS | see route 7 | Address standardization, no phone. USPS Addresses v3 is no longer free (repo note). | n/a | n/a | WALLED for phone |
| 7 | Owner mailing address as the channel | SC assessor rolls, `data/sc_parcel_mailing.db` | Taxpayer mailing address | SC board 37%; sample 1,261 of 1,815 (69%, Spartanburg-heavy) | 30-2-50 applies | VIABLE (channel), see Section 7 |
| 8 | Email from public business filings | SC SoS (none), FMCSA (70% of SC carriers), FCC (0 of 124) | Only FMCSA carries email at any scale | 0 of 20 | Federal | PARTIAL, negligible |
| 9a | OpenStreetMap by address | overpass-api.de (count queries) | Business phone tags. A bbox covering Spartanburg and neighbors: 2,202 features with `phone` or `contact:phone` against 224,063 with an address housenumber. | about 1% of addressed objects, and a business line, not an owner | ODbL, attribution and share-alike. Overpass rejected a browser User-Agent with HTTP 406; a descriptive tool User-Agent worked. | PARTIAL, negligible |
| 9b | Overture Maps Places | docs.overturemaps.org places schema | Schema has `phones` and `emails`. License CDLA Permissive 2.0 (Foursquare part Apache 2.0) per web search. Not sampled: needs a parquet read of SC. | not sampled | Free | PARTIAL, unsampled, business-at-address only |
| 10 | People-search sites | truepeoplesearch.com/terms returned HTTP 403 titled "Captcha Challenge"; fastpeoplesearch.com/terms loaded | FastPeopleSearch terms bar copying "by automated means using bots, spiders, or web scraping tools" without written consent | n/a | Challenge plus ToS | EXCLUDED |

Layers probed in route 4 (field metadata only): Oconee CitizenServe/5 and PARCELDATA_owner_Assr/1, Beaufort EnerGov/1, Anderson County_Parcels/0 and NewPropertyViewer/5, Sumter Sumter_City_County/7, Georgetown GCGIS_Energov/2, Laurens TaxParcel/5, Spartanburg CAMA_Parcels/0 (99 fields), Saluda PublicWebsite_Pro/4 (99 fields), Pickens_Open_data/6, Union UNION_SC_PARCELS_WFL1/2, Horry parcelapp/24. The only name hits were `GisFile_MailingAdd` and `DBO.ParcelLandRecords.area` (false positives).

Building-permit and EnerGov layers are the SC analog of Buncombe's Accela table. The two EnerGov layers probed (Beaufort, Georgetown) are parcel tables with no contact fields. I did not find an SC permit layer that publishes applicant phone.

## 6. The 20-lead sample

Drawn at random with a fixed seed from distinct owner names in the 2,000-row read (14 persons, 6 entities). Bias: Spartanburg vacant and Cherokee delinquent tax only, because those are the first rows in the file. Owner names are omitted here on purpose.

| Check | Persons (14) | Entities (6) |
|---|--:|--:|
| Mailing address already on row | 7 of 14 (Cherokee rows have none) | 6 of 6 |
| Existing phone on row | 2 (both `ncsbe_voter_xref`, both unrelated names) | 1 (`ncsbe_voter_xref`, unrelated name) |
| NPPES SC candidates (exact first and last) | 0 | not run |
| FMCSA SC name candidates | 3 name-only, 0 corroborated by city | 1 name-only ("CRF" vs a carrier called CRF Transport), 0 corroborated |
| NC-voter match with same house and street (NC-mailed rows only) | 0 of 31 NC-mailed SC rows in the 2,000-row read | not run |
| SC voter file, probate, SoS, county layers, ULS | 0 phone fields available | 0 |

One entity query in my probe (a "C.L.C." name) returned 20 junk FMCSA rows because the punctuation cleanup left single letters; I discarded it and it is not counted as a candidate.

## 7. Mail as the contact channel

Coverage today: SC 37% on the board (audit section 15). Cherokee 8%, Union 40%, Anderson 42%, Laurens 46%, Spartanburg 55%, Pickens 69%, Oconee 68% (audit section 4a). The local assessor cache `data/sc_parcel_mailing.db` holds only Spartanburg (180,137 rows, 180,042 with a mailing address) and Anderson (113,406 rows, all with one).

What is available for the weak counties (field metadata, this session):

| County | Layer | Mailing fields | Status |
|---|---|---|---|
| Laurens | Pebble/TaxParcel/MapServer/5 | `Mailing_Address`, `Mailing_City_State_ZIP` | free, public |
| Union | UNION_SC_PARCELS_WFL1/FeatureServer/2 | `Address_1..3` (need to confirm they are mailing, not situs) | free, public; repo notes say the county site is WAF-blocked |
| Oconee | PARCELDATA_owner_Assr/MapServer/1 | `owner_street`, `owner_citystate`, `owner_zip` | free, public |
| Pickens | Pickens_Open_data/6 | none on this layer | needs another source |
| Cherokee | qPublic only per `enrichment_owner_mailing.py` | n/a | Cloudflare Turnstile per repo memory, do not attempt |

Arithmetic, assuming these three reach 90% mail like Spartanburg vacant: Laurens 3,203 x (0.90 - 0.46) = 1,410, Union 1,368 x (0.90 - 0.40) = 684, Oconee 3,309 x (0.90 - 0.68) = 728. Total about 2,820 rows, which is +3.7 points of the 77,036 SC rows. Anderson (42% on the board against a cache with all 113,406 owners) looks like a join problem rather than a source problem, worth a separate look.

Cost to actually mail (verified today): USPS domestic postcard $0.65 from July 12, 2026, up from $0.61 (about.usps.com newsroom, 2026-04-09). Lob all-in postcards start at $0.905 (Developer, $0/mo), $0.645 (Startup, $260/mo) and $0.615 (Growth, $550/mo). PropStream lists direct mail "from 57 cents/postcard". Per 1,000 pieces that is $570 to $905 before you count who you mail. TrueNCOA at $20 per file is in `docs/path_to_100.md` and was not re-checked.

Mail beats every free phone route on accuracy (recorded taxpayer address) and coverage (37% against under 1%), and loses on cost per contact and on the 30-2-50 question.

## 8. Ranked recommendation and expected lift

Lift is in percentage points of all 77,036 SC rows. "Usable" means a number that plausibly belongs to the owner.

| Rank | Action | Cost | Expected lift | Confidence |
|--:|---|---|---|---|
| 1 | Quarantine SC `ncsbe_voter_xref` phones (see Section 9 spec). Reported SC phone falls, usable SC phone does not change. | $0 | reported up to about -1.5 points, usable 0 | high that the phones are unreliable (Section 2); the size of the drop is an estimate that assumes most of the board's 2% is xref, which I did not count |
| 2 | Remove or gate the `enrichment_free_phones` call at `scripts/enrich_board.py:762` | $0 | 0 | high |
| 3 | Ingest Laurens, Union, Oconee mailing addresses for the weak counties | $0 (engineering) | +3 to +4 points of SC MAIL | medium, assumes 90% ceiling |
| 4 | Exact-name-plus-city matcher against FMCSA census (phone and email) and NPPES, corroborated by city | $0 (engineering) | +0.1 to +0.3 phone, +0.05 to +0.2 email | low. 0 of 20 in sample. A 0 of 20 result cannot rule out a low single-digit rate. |
| 5 | Corroborated NC voter match for NC-mailed SC owners (name plus mailing house and street) | $0 (engineering) | 0 to +0.2 | low. 0 of 31 in sample. |
| 6 | OSM or Overture business phone by address for commercial parcels | $0 | up to +0.3 | low, unsampled for Overture |
| 7 | Paid skip trace of SC HOT plus WARM through the existing `contact_ingest` lane or an API | see Section 10 | +18 to +23 points if 60 to 75% match (assumption) | medium on cost, low on SC match rate |

Realistic free ceiling for SC phone: under 1 point above the honest 0.4 percent baseline. The free routes are worth building only for the mail lift (rank 3) and as a quality gate (rank 1).

## 9. What I built, and the spec for what I would build

Built: nothing. Ranks 4 to 6 are viable in the sense that they are free and legal, but each returned 0 hits in its sample, so none is "clearly viable". I wrote no module and no tests, and I did not touch any file other than this one.

The item I would build next, if you say go, is a gate rather than a route: `src/foreclosure_scraper/enrichment_sc_phone.py` with `xref_identity_verdict(li) -> "corroborated" | "unverified" | "contradicted"`, and `flag_unverified_xref_phones(listings, apply=False) -> stats`. Rules:

- `contradicted`: matched voter first and last name is not a substring of the current `owner_name`, or the current owner is an entity (LLC, INC, CORP, POST, TRUST, ASSOCIATION, CHURCH).
- `corroborated`: `owner_mailing.mail_state == "NC"` AND the mailing house number plus street token equals the voter's residential street key (this reuses `_street_key` and the index from `enrichment_voter_phone.py`).
- everything else `unverified`.
- With `apply=True` set `owner_phone["identity_check"]` to the verdict and `owner_phone["do_not_dial"] = True` for anything not `corroborated`. Default is report-only counts. It never writes the board; the pipeline decides whether to persist.
- Offline tests with hand-built `Listing` objects, no network.

Estimated effort: small. It needs your yes because it changes what the operator sees as "SC phone".

## 10. Paid options, prices verified 2026-09-21, nothing bought

| Vendor | What | Verified price | Source |
|---|---|---|---|
| Tracerfy | Normal skip trace (name plus address in): phones and emails | $0.02 per hit, misses free | tracerfy.com/pricing raw HTML |
| Tracerfy | Advanced trace (address only), returns owner, phones, emails, mailing | $0.04 per hit | same |
| Tracerfy | Parcel (APN) trace; enhanced trace; phone intelligence with DNC flags | $0.10 per hit; $0.30 per hit; $0.10 per hit | same |
| Tracerfy | DNC scrub, federal and state | $0.02 per phone | same |
| Tracerfy | Plans | Growth $700/mo (50,000 credits), Scale $1,500/mo, Business $3,000/mo; pay-as-you-go credits never expire; free account, no card | tracerfy.com/pricing (WebFetch) |
| PropStream | Essentials $99/mo, Pro $199/mo, Elite $699/mo; annual $81, $165, $583 per month | skip tracing 12 cents per contact on Essentials, 10 cents on Pro (WebFetch); Connect add-on $30/mo, free skip tracing; direct mail from 57 cents per postcard | propstream.com/pricing raw HTML |
| PropStream | Repo note in `docs/path_to_100.md`: no API and terms forbid our pipeline use, so operator-export lane only | n/a | repo |
| BatchData (batchskiptracing.com) | Skip tracing plan, pay per matched record | Growth $3,000/mo for 100,000 records, Professional $7,500/mo | batchskiptracing.com/pricing raw HTML |
| Lob | Postcards | $0.905, $0.645, $0.615 per piece by tier | lob.com/pricing/print-mail (WebFetch) |
| USPS | Domestic postcard stamp | $0.65 from July 12, 2026 | about.usps.com newsroom |
| SC Election Commission | Voter list, no phone column | $25 to $2,500 | scvotes.gov |
| SC LLR | Licensee list | $10 per board list, by mailed check | llr.sc.gov PDF |

Cost of the recommended paid step, for the numbers only, at $0.02 per hit with misses free:

| Scope | SC rows | Cost if every row hits | At 60% match | At 75% match |
|---|--:|--:|--:|--:|
| HOT | 668 | $13 | $8 | $10 |
| HOT plus WARM | 23,623 | $472 | $283 | $354 |

Add $0.02 per phone for a DNC scrub, about the same again. The 60 to 75% match rate is the range quoted for a comparable vendor in `docs/path_to_100.md`. I did not test any vendor's SC match rate, so run a 25-lead pilot first (about $0.50).

## 11. Decisions for the owner

1. Approve quarantining `ncsbe_voter_xref` SC phones (Section 9). Until then, no one should dial an SC row whose phone source is `ncsbe_voter_xref`.
2. Get an SC counsel opinion on 30-2-50 for outbound mail and calls built on assessor data, or accept the exposure knowingly. This governs mail as much as phone.
3. Approve a small paid pilot: 25 SC HOT leads through Tracerfy for about $0.50, then decide on HOT (about $13) and HOT plus WARM (about $470 plus DNC scrub).
4. Decide whether `scripts/enrich_board.py:762` (`enrichment_free_phones`) should be removed, since it contradicts the "dormant" note and drives people-search sites that are excluded.
5. Decide whether to spend engineering on the Laurens, Union and Oconee mail ingest (rank 3), the only free lever with a real payoff.

## 12. Limits of this research

- The board sample is the first 2,000 rows only (per the instruction not to do a full pass), so it over-represents Spartanburg vacant and Cherokee. The Section 2 counts show a defect exists and how it looks; they are not board-wide rates.
- WebFetch summaries were used for several pages (SC probate, Lob, PropStream tier text, Tracerfy plans). Where I could, I confirmed with raw HTML (Tracerfy per-hit prices, PropStream tiers, BatchData tiers, SC statute text, SC voter page, USPS newsroom). Two PropStream figures in the WebFetch text were garbled ("142% more value"); I used the raw HTML for those.
- Not verified: SC Bar directory (404), SC Public Index page (HTTP 400, terms taken from search results), LLR online lookup (redirect loop), Calhoun and Charleston parcel layers, the FCC bulk file beyond one 124-row daily file, Overture Places coverage, and any vendor's SC match rate.
- The Register of Deeds row rests on earlier repo work, not a fetch today.
- Temporary files (the FCC daily file and downloaded pages) were kept under the session scratchpad; the FCC file was deleted.
