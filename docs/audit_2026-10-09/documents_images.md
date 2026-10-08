# Audit 2026-10-09: documents and images (area `documents_images`)

The owner's standard: no notice PDF, deed image, scanned page or listing photo the board holds a
URL for is left unread. Measured on the published 10/7 board (350,013 rows, manifest run_time
2026-10-07T17:09Z), the 10/6-10/7 full-run log on the VM (read with grep, nothing run there) and
the Mac's daily vision logs of 10/6, 10/7 and 10/8.

## 1. What was measured and how

* `scripts/doc_image_inventory.py --no-ledger` (one streamed pass, ~50 s, 270 MB peak, counts
  only) wrote `documents_images_inventory.json` beside this file: every document and image URL
  by category, source and county, what became of it, and the backlog with its reason. The
  classifier is `src/foreclosure_scraper/doc_inventory.py`, shared with the enricher, the ledger
  and the audit check, so the count, the queue and the gate mean the same thing.
* `scripts/audit_suite.py --only documents_images` runs the invariants (section 2).
* Accuracy: every document read on the board that still downloads was read by me against the
  extracted values (22 scanned notices, 6 text-layer PDFs, the rosters behind 17 roster
  matches). Per-record tables with names are private: `~/Desktop/Audit_2026-10-09/
  documents_images/accuracy_table.tsv` (and `sample_rows.json`, the fetched files).

### Inventory (rows of the 10/7 board)

| category | rows | read | backlog and reason |
|---|---|---|---|
| per-lead notice documents the doc OCR reads | 207 | 27 | 178 never reached before the 900 s cut or failed without a mark; 2 in a field the old reader did not look at |
| Dorchester BillTrax notice links | 988 | 0 | an Angular viewer, plain HTTP gets the app shell (the bill's fields are already on the row from the BillTrax API) |
| roster PDFs the rows were parsed from (20 shared documents) | 12,494 | read by the scraper | 6,522 rows with no address whose roster the doc OCR address pass never read (it ran after the per-lead loop inside the cut budget): nc_county_pdf_delinquent_tax 5,746, florence 483, buncombe 150, fairfield 59, calhoun 45, charleston_mie 23 |
| deed / plat image links from Henderson's GIS layer | 1,258 (2,458 URLs) | 0 | no reader; the host is the Courthouse Computer Systems install `rod/doc_images` reaches only through its stealth path |
| assessor property-record cards | 2,839 | 2,125 parsed | 714 rows hold a card URL with nothing parsed (asheville_str_permits 159, buncombe_elderly 117, greenville_unpaid_tax 81, buncombe_delinquent 74); cause not investigated |
| NC DEQ Laserfiche document searches | 41,557 | n/a | a folder search, not a document |
| recorded deed-of-trust images (resolved at run time, no URL held) | 64,664 eligible in 11 counties | 22 rows (Burke 6, Transylvania 16) | 10/7 run: 393 searched, 0 images, only Lincoln and Burke reached (the first two counties took the whole 400 cap); 9 counties never searched |
| rows with a gradable image | 34,760 | 20,870 graded, 10,186 with the grade in `condition_tier` | 2,273 inside the 2,500 cap but left when the breaker stopped the pass; 11,379 past `VISION_MAX_LISTINGS`; 238 fetch-failed markers. HOT 5, WARM 2,765 |
| ...best image an assessor photo | 8,487 | 915 | Gaston vacant 6,039 rows, 102 graded |
| ...best image a listing photo | 4,787 | 2,001 | |
| ...best image street level | 3,246 | 1,086 | |
| ...aerial only | 18,240 | 16,868 | |

Hard-coded caps and per-run limits (before this audit): doc OCR read ONE document per lead
(`uniq[:1]`), `DOC_OCR_MAX` 2,500 leads, `DOC_OCR_BUDGET_S` 2,400 s but `main._await_capped`'s
900 s default around it, aggregate detection by exact URL with `DOC_OCR_MAX_SHARE` 3, 12 MB
silently truncated, 3 pages / 20,000 characters of a text PDF; dot OCR `FORECLOSURE_DOT_OCR_MAX`
400, `_COUNTY_MAX` 200, `_BUDGET_S` 1,800 (+120 grace), sweep 300 s, 3 candidates, refresh 30 days;
vision `VISION_MAX_LISTINGS` 2,500 (main), `VISION_MAX_SECONDS` 1,800 in main but 5,400 inside the
module (one variable, two defaults), 7 photos (5 real), 3 MB, fetch pause after 20 and STOP after
100 consecutive rows without a downloadable photo, 10 strikes / 5 hard fails / 8 attempts, yield
stop under 100 graded an hour after 20 minutes, fetch-fail marker 2 retries / 14 days; photos
`FORECLOSURE_PHOTO_MAX_TARGETS` 2,500 and 2,400 s but the same 900 s outer cut (with_address_photos,
assessor_photo, streetview and with_images were all cut on 10/7).

## 2. Defects, fixes, tests, invariants

| # | defect | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|---|
| 1 | vision stops within minutes every run | 10/7 VM: 39 graded of 2,500 in 165 s; Mac daily 10/6, 10/7, 10/8: 3, 1, 60 graded | 2,908 rows hold ONLY dashboard-hosted relative paths (`parcel_photos/...`); `_fetch_image_bytes` sent them to httpx, every one failed, 1,399 of them sit in queue places 300-2,500, so the 100-in-a-row breaker fired | a relative path is read from `docs/`, else from the published site; a 200 HTML page is not a photo. Breaker unchanged | `test_vision_relative_photos_and_ledger.py` | `images-hot-warm-graded` (10/7: 2,659 of 12,069 HOT/WARM rows unread, max 5%) |
| 2 | every run redoes the first N and never reaches the rest | doc OCR, dot OCR and vision failures left no mark | no record of an attempt | the processed-documents ledger (below) | `test_doc_ledger_and_reads.py`, `test_dot_ocr_ledger_and_share.py` | `docs-per-lead-doc-outcome` (10/7: 169 of 207, max 2%), `docs-processed-has-ledger-entry` (0 after the seed) |
| 3 | the roster address pass never ran | 6,522 rows, 18 rosters | it ran after the per-lead loop, and main cut the phase at 900 s (`enrich.time_capped phase=doc_ocr` 06:21:05) | roster pass FIRST with its own 600 s share, needs no model key; skips a roster no lead needs | `test_roster_pass_runs_first...`, `..._without_any_model_key` | `docs-roster-rows-read` (10/7: 5,083 rows; 0 allowed) |
| 4 | dot OCR searched 2 of 11 counties | 9 counties, 45,115 eligible rows never searched | counties ran in first-appearance order, each up to 200 of the 400 cap | equal share per county (best lead's county first), lead value inside a county, `left_for_next_run` | `test_every_configured_county_gets_a_share...`, `test_best_leads_are_searched_first...` | `docs-dot-county-attempted` (10/7: 9 of 11) |
| 5 | dot OCR fallback crashed a county | any county where Gemini answered without a result while an NVIDIA/Mistral key is set | `blocks` bound only in the all-keys-quota branch: UnboundLocalError, the rest of the county dropped | bound before the Gemini loop | `test_a_gemini_answer_without_a_result...` | the ledger outcome per search |
| 6 | a sale list read as its first entry | 5 of 34 per-lead reads contradict the row's case number; 2 put another case's owner or defendant in a column (Anderson, Pickens) | lists referenced by 3 or fewer rows count as per-lead documents | a read binds only when its case number (else house number) agrees with the row; old reads that do not are set aside and their unvouched column fills undone (`revise_columns`) | `test_a_sale_list_read...`, `test_enricher_never_applies...`, `test_enricher_sets_aside_an_old_read...` | `docs-ocr-binds-to-row` (10/7: 5) |
| 7 | roster lot numbers stamped as house numbers | 11 of 11 checkable roster addresses wrong (8 Florence lot/tract numbers, 1 Buncombe neighbour on a merged line, 2 McDowell owner names that are addresses / a parcel with a letter suffix) | `_ADDR_IN_ROW` took "LOT 43 MEETING ST" as 43; substring parcel match | numbers after LOT/TRK/BLK/#/&... rejected, a match through a parcel number rejected, whole-token parcel match; old stamps re-verified against the roster line (10/7 replay: 11 cleared, 6 untouched because the roster changed) | `test_lot_numbers_are_not_house_numbers`, `test_a_parcel_id_matches_a_whole_token_only`, `test_reverify_clears...` | `docs-roster-rows-read` + the ledger's `rows_filled` |
| 8 | notices to creditors: deadline read as sale date, the representative's address as the property | 9 of 9 dated notices to creditors; 1 address | prompt | prompt names `claims_deadline`; `normalize_parsed` moves the date and drops the address for a creditor notice | `test_notice_to_creditors...` | ledger values (no `sale_date` on a creditor notice) |
| 9 | non-judgment figures in `judgment_amount` | 1 row (an auction's $5,000 earnest-money deposit) | any amount filled it | only a judgment or lien document type fills it; `amount_kind` kept in `raw.doc_ocr` | parametrized test | `docs-ocr-tax-not-judgment` |
| 10 | dense scanned notice misread | 1 of 22 (case number, house number and name each one character off) | an 84 x 251 pt cropped page sent as a PDF | a small scanned page goes to the model as a ~2,400 px PNG (not re-measured: no model call made in this audit) | `test_small_scanned_page_rasterizes_large` | ledger re-read (old reads are v1) |
| 11 | format handling | HTML notice pages sent as JPEG; TIFF not converted; spreadsheets sent to models | none | HTML read as text, TIFF to PNG, office files recorded `unsupported_format` | format tests | ledger outcome |
| 12 | doc OCR used the paid Anthropic fallback when a key was set | unknown | default | off unless `DOC_OCR_ALLOW_PAID=1` (dot OCR too) | `test_paid_fallback_needs_the_owner_opt_in` | n/a |
| 13 | Gemini 503 ("high demand") retried on every key | 20 errors in the 900 s of 10/7 | treated as a plain error | one 503 ends Gemini for that document; 3 in a row pause Gemini 120 s | `test_gemini_overload_stops_the_key_chain` | n/a |

**The processed-documents ledger** (`src/foreclosure_scraper/doc_ledger.py`,
`docs/handoff/documents/{doc_ocr,dot_ocr,vision}.json`, same style as the verification ledger:
schema 1, one sorted entry per line, atomic, merge-safe save). Keys are hashes of the normalized
URL (cache busters ignored), of the image set, or of state+county+owner for a deed-of-trust
search. Entries hold outcome, extractor version, timestamps, attempts, content hash, size,
host, source slug, county, field names extracted and columns filled, and only public values
(amounts, dates, case numbers, document type, grade). Names and addresses read off a document go
to the git-ignored `data/doc_ledger/<lane>.private.json` (the data/heirs pattern) and are used
only to re-apply a read to a row that lost it. A document read by this version is never fetched
again; a failure waits (fetch 2 days, provider 1 day, ungraded image set 30 days, no deed found
30 days, doubling to 30); a document whose bytes another URL already served reuses that read;
order is HOT, WARM, score, intent, sale date. Seeded from the 10/7 board
(`scripts/doc_ledger_tool.py seed`): 28 notices + 4 rosters + 20 owner searches under v1 (so the
next run re-reads them once under the new rules), 18,376 graded image sets.

Accuracy (all available; every type had fewer than 30):

| type | sample | owner | address | amount | date | case |
|---|---|---|---|---|---|---|
| scanned notices (Column / NC notices) | 22 documents | 21/22 | 9/11 | none extracted | 18/18 dates read right, but 9 were claims deadlines labelled sale date (9/18 as a sale date) | 20/21 |
| text-layer PDFs (sale lists, an auction package) | 7 reads | 3/6 | 5/7 | 0/1 (a deposit) | 5/5 checkable | 4/6 |
| roster address matches | 18 (11 checkable) | n/a | 0/11 | n/a | n/a | n/a |
| deed-of-trust images (dot OCR) | 22 | not re-checked: the images come only through the vendor sessions in `rod/doc_images` | | | | |
| vision grades | 20,870 | not measured (no ground truth); 11,724 came from one NIM model | | | | |

End to end (published row vs read): owner 24 of 33 equal on the row (2 of those 24 were another
lead's read), 9 rows kept their own value, case number 27 of 32, sale date never written (by design;
see defect 8), amount 1 (wrong, now gated), dot OCR `loan_amount` on 22 of 22 rows, vision grade
in `condition_tier` on 10,186 of 20,870 graded rows (the rest LOW confidence, by design). Keys
that must be published: `raw.doc_ocr` (kept whole, now carries `_v`, `_filled`,
`claims_deadline`, `amount_kind`), `raw.dot_ocr`, `raw.loan_amount`, `raw.rod_docs`,
`raw.vision` (detail sidecar), `raw.vision_fetch_failed`: all already in RAW_KEEP.
`raw.doc_ocr_rejected` is deliberately internal (the ledger holds the outcome).

## 3. Open items

* **Wiring (lead):** main.py doc_ocr call needs `default_s=` its own budget + grace (defect 3);
  the same for `with_address_photos` (2,400 s inside a 900 s cut). The ledger files must reach
  the next run's checkout: the VM run writes them in its checkout; commit them with the publish,
  or merge the VM copy on the Mac with `scripts/doc_ledger_tool.py merge`.
* **Owner:** `VISION_MAX_LISTINGS` (11,379 gradable rows past the cap; the Mac daily pass cannot
  write its results: the board is 2,652 MB, over the 2,300 MB patch ceiling, so 132 grades sit in
  `logs/vision_pending_patches.json`); `VISION_MAX_SECONDS` 1,800 vs 5,400; `DOC_OCR_ALLOW_PAID`.
* **Wall / policy:** Henderson deed and plat images (stealth-only host, not extended);
  BillTrax notice viewer (needs a browser, low value); Laserfiche searches (a new source lane, not
  a document reader).
* **Not verified:** dot OCR accuracy; vision accuracy; the high-resolution re-read of dense
  notices (no model call made); why 714 assessor card URLs were not parsed; the 6 Florence roster
  stamps whose parcels are no longer on the current roster.
* No model key is missing: the 10/7 pool had Gemini (9 keys), NVIDIA, Groq, Mistral, Cloudflare.

## 4. Seen outside this area

* `column_legal_notices`: `street_address` holds notice text ("Having qualified as the
  Administrator of the Est", "or this notice will be pl"); two different estates' notices were
  merged on that shared fake address (Onslow).
* `public_notices.nc_notices_counties`: a row's notice PDF is another estate's (case differs).
* Pickens / Anderson sale-list rows: `street_address` built from a case number and a plaintiff
  fragment ("01196 NATIONST", "00468 CARD").
* 817 rows name a photo file absent from `docs/` on the Mac (mostly the street-view cache); the
  two sampled are also 404 on the published site.
* 5 rows carry a doc OCR read whose document field a merge replaced (untraceable).
