# Board versions: what improved and what regressed, iteration to iteration

Rule (owner, 2026-10-08): a new board replaces the live one only after it is compared with it and
is better; every iteration gets an entry here. Counts only (public-safe). Read percentages with
care: when the board grows (new leads with few fields) the share of ALL rows with a phone can
fall while the number of rows with a phone rises. Judge by row counts first, then by the share
among HOT/WARM leads and among rows present in both boards.

## 2026-10-07 board (first publish of the rebuilt VM run, 350,013 rows) vs 2026-10-01 board (219,143 rows)
Source: docs/gap_matrix/county_signal_coverage_2026-10-01_baseline.csv and ..._2026-10-07.csv,
row-weighted. Rows with the value, 10/1 -> 10/7:

Improved: owner name 193,711 -> 323,942; street address 159,628 -> 256,309; parcel id 145,886 ->
186,169; assessed value 128,771 -> 175,267; lot size 112,627 -> 163,883; phone 66,285 -> 81,296;
tax-lien flag 97,401 -> 116,202; tax-sale flag 41,843 -> 47,115; "distressed" flag 28,077 ->
108,243; tax aging surfaced 1,598 -> 99,586; deed chain with history 35,340 -> 79,851; heir/estate
692 -> 4,647; estate lead 1,039 -> 4,903; divorce notice 6,676 -> 7,227.

Flat (no growth; same source set): email 47,005 -> 46,987; builder distress 20,306 -> 20,299;
LiensNC related 16,009 -> 15,999.

Looked like regressions but are dilution (rows grew 60 percent): phone 30.2% -> 23.2% of all rows,
parcel id 66.6% -> 53.2%, tax-lien flag 44.4% -> 33.2%.

Known defects present in the 10/7 board that were found afterwards (2026-10-08): 20,185 rows carry
another parcel's county tax debt (14,067 wrong balances), see
docs/audit_2026-10-09/ and src/foreclosure_scraper/tax_binding.py; the "2+ years and $500" flag was
inflated (checked against the county sites: Buncombe 17% hold, Spartanburg 71%, Darlington 22 of 22).

## Next entry: the board from the gated run pinned d42058b3 (389,122 leads at the gis checkpoint,
383,373 at dot_ocr) vs the live 10/7 board. To be written by scripts/compare_boards.py output.
