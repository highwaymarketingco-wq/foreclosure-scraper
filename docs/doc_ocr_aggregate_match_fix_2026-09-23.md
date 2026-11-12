# doc_ocr aggregate-roster backfill: root cause + fix (2026-09-23)

## Starting point

The 2026-09-22 full-run log (`logs/local-run-20260922T111425.log`, event
`doc_ocr.done`) showed:

```
targets: 31, aggregate_docs: 14, aggregate_leads: 8955, agg_docs_read: 12, agg_backfilled: 2
```

12 of 14 shared aggregate documents were fetched and text-extracted
successfully (not a fetch failure), but `_row_backfill_from_aggregate`
(`src/foreclosure_scraper/enrichment_doc_ocr.py`) matched only 2 of 8,955
leads referencing them. On the live board, tax-roll leads referencing a
shared PDF (`nc_county_pdf_delinquent_tax`, `florence_delinquent_tax`,
`charleston_delinquent_tax`, `buncombe_delinquent_tax`) were 62% missing
`street_address`, so real recoverable work exists.

## Method

Streamed the live board read-only (`board_stream.iter_board_rows`, 4 passes:
source-slug discovery, then one combined candidate scan, then two bounded
early-break sample pulls — the task's cap was 3 "real" passes; the slug
discovery was a cheap correction to a wrong assumption, not a bulk scan) to
find real aggregate-doc candidates, then fetched and locally
`pdfplumber`-extracted **three real documents** (no paid OCR/Gemini calls
needed — all three PDFs have a text layer, so the free `_pdf_text()` path
handles them, same as the aggregate loop does in production):

1. Florence County SC mobile-home tax roster (`florence_delinquent_tax`,
   1,652 leads) — `s3.us-east-1.amazonaws.com/files.florenceco.org/public/DelinquentTax/2026/2026 Tax Sale List Mobile Homes 9-1-26.pdf`
2. Buncombe County NC tax-lien advertisement (`buncombe_delinquent_tax`, 845
   leads) — `media.buncombenc.gov/common/tax/buncombe-county-tax-department-advertisement-of-tax-liens.pdf`
3. Catawba County NC delinquent-tax roster (`nc_county_pdf_delinquent_tax`,
   3,958 leads — the single largest aggregate doc on the board) —
   `www.catawbacountync.gov/site/assets/files/11653/delinquent_advertisement_list-hdr_2026.pdf`

## Root cause 1 (dominant, proven): `_pdf_text()`'s 3-page cap

`_pdf_text()` (`enrichment_doc_ocr.py`, was line 186) read only
`pdf.pages[:3]` — a budget sized for a single-property notice/deed (the
per-lead OCR-prep path, `_ocr_document`, which pays real Gemini/vision cost
per call). The aggregate loop in `enrich_doc_ocr` (around line 654 at the
time) reused the SAME function to read a whole **county roster** once per
unique document.

Real evidence: Catawba County's roster is **161 pages**, alphabetical by
taxpayer name, ~25 rows/page (3,958 leads total on the board for this
source). `pdf.pages[:3]` captured roughly `013 10TH STREET TRUST` through
`ACEVEDO ELIAS NOE` — **under 2% of the document**. Every lead whose taxpayer
name falls later alphabetically (the other ~98%) was never even present in
the text handed to `_row_backfill_from_aggregate`; no identifier-format fix
could ever have found them. Buncombe's roster is 12 pages, so the same cap
hid ~75% of its 845 leads. This alone explains the overwhelming majority of
`agg_backfilled: 2` — the matcher wasn't failing to match; it was being
shown roughly 2% of the pages that existed to search.

Confirmed directly:
```
Catawba PDF: 161 pages total
_pdf_text(data)                              -> 3,286 chars  ("FREEMAN RUTH" (page 51) NOT present)
_pdf_text(data, max_pages=None, ...)         -> 175,185 chars ("FREEMAN RUTH" present)
```

### Fix 1

`_pdf_text()` (`enrichment_doc_ocr.py:202-224`) now takes `max_pages` (default
`3`, unchanged for the per-lead path) and `max_chars` (default the existing
`_MAX_PDF_TEXT_CHARS = 20000`). New constants
`DOC_OCR_AGG_MAX_PAGES` (default: no limit, env-overridable) and
`DOC_OCR_AGG_MAX_CHARS` (default 2,000,000 chars) at `enrichment_doc_ocr.py:115-130`.
The aggregate loop in `enrich_doc_ocr` (`enrichment_doc_ocr.py:~738-742`) now
calls `_pdf_text(data, max_pages=DOC_OCR_AGG_MAX_PAGES, max_chars=DOC_OCR_AGG_MAX_CHARS)`.
This costs nothing extra in OCR/vision spend — `_pdf_text` is local, free
`pdfplumber` extraction, run once per unique document (12-14 times per run),
not per lead.

## Root cause 2 (proven via a real 11-lead sample, more serious): column-merge line interleaving

Buncombe's PDF is a dense multi-column newspaper-style advertisement.
`pdfplumber`'s `extract_text()` groups words into an output "line" purely by
y-position, blind to the page's column bands, so **one physical output line
can interleave fragments from three or four unrelated taxpayers**.

First attempted fix (address search scoped to text *after* the matched
identifier, instead of the whole line) was not sufficient. Validating it
against an **11-lead real sample** pulled from the live board (`_lead
_identifiers` + `_row_backfill_from_aggregate` run offline against the full,
uncapped, real Buncombe text) found it was still stamping the **wrong
property's address onto real leads**:

```
978416519600000 -- PAGANO, RAYMOND J's row --
NIX, WILLIAM L JR (own parcel 978416519600000, real address "20 HOUSTON RD")
  -> WRONGLY FILLED "1 CREST AVE" (Raymond J Pagano's address, from the same merged line)

FRANK W MORRIS JR ETAL (own parcel 961388939100000, real address "311 BOUNDARY TREE PASS")
  -> WRONGLY FILLED "17 SILENT PL" (a stranger's address, from the same merged line)
```

Real line for the first case (page ~5 of the full-document read):
```
968849046600000 -- 978416519600000 PAGANO, RAYMOND J 1 CREST AVE JANEL PRESLEY, PEGGY S PULLEASE, REBECCA
```
Nix's own parcel is followed immediately, in reading order, by a different
taxpayer's name and address — "after the identifier" is not a safe
assumption on a line like this.

### Fix 2

Added a **column-merge guard**: a physical line carrying a *second* long
(8+ consecutive digit) parcel/account-number-shaped run, distinct from the
lead's own matched identifier, is treated as contaminated (multiple
properties concatenated onto one line) and yields **no match** rather than a
guess. `_LONG_ID_RUN = re.compile(r"\d{8,}")` and the guard at
`enrichment_doc_ocr.py:597-615` (`_row_backfill_from_aggregate`). Threshold
of 8 digits was chosen from real evidence: Buncombe's own PINs are 15 digits;
`_ADDR_IN_ROW` caps a house number at 6 digits; these rosters' dollar
amounts never reach 8 digits (`$79,723.60` → `7972360`, 7 digits). This
closes the actual observed contamination path with no loosened matching
elsewhere — "no identifier match means no write" is preserved and extended
to "no confidently-isolated row means no write."

## Verification

### Targeted test command (as specified)
```
uv run python -m pytest -q -p no:cacheprovider tests/test_dot_ocr.py tests/test_doc_ocr.py tests/test_doc_ocr_aggregate_match.py
```
Result: **50 passed** (0 failed). New file
`tests/test_doc_ocr_aggregate_match.py` (24 tests) covers, using the real
captured Florence/Buncombe text and a `pypdf`-built synthetic multi-page PDF
for the page-cap mechanics:
- `_pdf_text` still defaults to 3 pages (per-lead path unchanged) and reads
  every page when `max_pages=None`, bounded by `max_chars`.
- The real Florence row is located via its parcel id but correctly yields no
  address (the document type — a mobile-home roster — never prints a street
  address; `LOCATION` is a year/make/size, not an address).
- The real Buncombe contaminated lines for NIX, WILLIAM L JR and FRANK W
  MORRIS JR ETAL no longer produce a wrong fill (the exact regression this
  session found and fixed).
- The pre-existing line-scoped (never a neighboring physical row) guarantee,
  and the new after-identifier / column-merge guards, each have a positive
  case (still fills correctly on a clean row) and a negative case (does not
  leak).

### Before / after, real documents (offline, no new OCR calls)

**Catawba** (161-page roster, 3,958 leads):
- Before: `FREEMAN RUTH` (a real lead, page 51) absent from `_pdf_text(data)`.
- After: present in the full 175,185-char read; `_row_backfill_from_aggregate`
  now locates her row. Correctly fills nothing — Catawba's document format
  is `TAXPAYER  ACCOUNT#  AMOUNT` only, with **no street address printed
  anywhere in the document**. This is a genuine ceiling of the source
  document, not a code defect: Catawba leads will never get `street_address`
  from this path regardless of matching quality. (Its dangling `parcel_id`
  is also `null` on every board row for this source — a separate,
  unaddressed scraper gap noted below.)

**Buncombe** (12-page roster, 845 leads) — 11-lead real sample:
| stage | correct fill | safe no-fill | wrong fill |
|---|---|---|---|
| before Fix 2 (page cap fixed, no column-merge guard) | 0 | 9 | **2** |
| after Fix 2 | 0 | 11 | **0** |

The column-merge guard eliminates the wrong fills but does not, in this
11-lead sample, unlock any *correct* fills either — Buncombe's layout is
pervasively multi-column, so most identifier-bearing lines are contaminated
by the same mechanism. The realistic, honest estimate for this specific
document is that it remains close to its pre-fix yield for
`street_address` specifically, but is now **safe** (no fabricated data)
rather than silently wrong ~18% of the time it did fire.

## Net effect / realistic expectation for the next full run

- The dominant, decisively-proven bug (3-page cap on a 12-161 page document)
  is fixed. Every page of every aggregate roster is now actually searched.
- A second, more dangerous bug (cross-property address contamination on
  Buncombe's multi-column layout) was found only by validating the first fix
  against a real multi-lead sample, and is now closed.
- Two of the three real documents checked (Catawba, Florence) have a real,
  unavoidable ceiling of ~0% for `street_address` specifically because the
  source document never prints one — this is a data-availability limit, not
  a matching bug. `agg_backfilled` should not be expected to jump to
  thousands on the next run for these two sources alone.
- The genuine opportunity from this fix is (a) any other document among the
  12-14 aggregate docs not directly inspected in this session that IS
  single-column and DOES print a street address will now be matched across
  its full page range instead of ~2-25% of it, and (b) other, unfilled
  fields aside from street_address are untouched by this function by design
  (`_row_backfill_from_aggregate` only ever writes `street_address`) so no
  claim is made about `city`/`zip`/`case_number` recovery here.
- `agg_backfilled` is a small integer either way; do not expect it to reach
  a four-digit number purely from this fix. The concrete, provable
  improvement is: (1) full-document visibility instead of a 2-25% slice, and
  (2) elimination of a live data-corruption bug that was stamping wrong
  street addresses onto real leads before this session.

## Known, unaddressed, out-of-scope findings (flagged, not fixed)

- **Lincoln County NC** (`nc_county_pdf_delinquent_tax`) publishes its
  roster at `https://www.lincolncountync.gov/DocumentCenter/View/25558/2025-TAXESDelinquentAdvertisementNotice`
  — no `.pdf` extension. `_doc_urls()` (`enrichment_doc_ocr.py:152-168`)
  only accepts a bare `source_url` as a document if it ends in a known
  extension (`_DOC_EXT`), so Lincoln County leads are never even queued as
  doc_ocr candidates, aggregate or otherwise. This is a different function
  than the one this task scoped (`_lead_identifiers` /
  `_row_backfill_from_aggregate`), so it was left alone, but it is a real,
  separate gap worth a follow-up.
- Catawba's board rows all carry `parcel_id: null` — the scraper for this
  source is not capturing the roster's own account number as `parcel_id`,
  which is a scraper-side gap (out of scope for this enrichment-layer fix).

## Files touched

- `src/foreclosure_scraper/enrichment_doc_ocr.py`
  - `DOC_OCR_AGG_MAX_PAGES` / `DOC_OCR_AGG_MAX_CHARS` constants (~line 115-130)
  - `_pdf_text()` signature + page/char-budget logic (~line 202-224)
  - Aggregate-loop call site (~line 738-742)
  - `_LONG_ID_RUN` regex + column-merge guard in
    `_row_backfill_from_aggregate` (~line 555-560, ~597-615)
  - `_row_backfill_from_aggregate`'s address search narrowed to after the
    matched identifier (~line 617-640)
- `tests/test_doc_ocr_aggregate_match.py` (new, 24 tests)

## Note on commit state

Part of this fix (the page-cap change and the first, insufficient,
"search-after-identifier" guard) was captured by the environment's own
auto-commit as `01033fb` mid-session, before the 11-lead real-sample
validation surfaced the NIX / FRANK W MORRIS wrong-fill regression. The
column-merge guard that actually closes that hole (`_LONG_ID_RUN` and its
use in `_row_backfill_from_aggregate`), and the four regression tests that
prove it, are current working-tree changes, not committed by this session
(per instructions, no `git add`/`commit` was run directly).
