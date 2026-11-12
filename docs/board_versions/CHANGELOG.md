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

## 2026-10-08 board (gated_d42058b3, 383,378 rows) vs 2026-10-07 board (350,013 rows)
Source: scripts/compare_boards.py, record docs/board_versions/2026-10-08_gated_d42058b3.json. Verdict HOLD. Rows with the value, 2026-10-07 -> 2026-10-08:

Improved: owner name 323,941 -> 356,803; parcel id 186,166 -> 228,279; mailing address 140,751 -> 215,029; atty taxpayer of record 157,273 -> 205,281; lot size 163,884 -> 190,018; tax-lien flag 116,203 -> 137,786; tax balance 116,213 -> 136,599; tax aging surfaced 99,585 -> 118,373; deed chain with history 79,852 -> 117,416; atty deed chain fetched 79,852 -> 117,416; atty legal description 86,106 -> 98,208; late tax years 51,374 -> 91,592; phone 81,294 -> 87,512; owner cluster 65,705 -> 76,268; beds baths 14,327 -> 15,503; lt lis pendens 14,827 -> 15,001; name heirs 8,135 -> 11,487; atty heir candidates 6,883 -> 10,187.

Flat: email 46,987 -> 46,978; atty deed ref 34,960 -> 35,194; builder distress 20,297 -> 20,297; liensnc related 16,000 -> 16,000; sc state tax lien 9,168 -> 9,188; divorce notice 7,228 -> 7,255; vacant 4,660 -> 4,661; two year delinquent 1,288 -> 1,292; storm damage 1,250 -> 1,247; name deceased 629 -> 627.

Looked like regressions but are dilution or rows leaving: street address 73.23% -> 70.76% of all rows (256,310 -> 271,297 rows); assessed value 50.07% -> 48.44% of all rows (175,266 -> 185,703 rows); "distressed" flag 30.93% -> 29.45% of all rows (108,243 -> 112,892 rows); living area 27.82% -> 26.14% of all rows (97,379 -> 100,221 rows); tax-sale flag 13.46% -> 12.55% of all rows (47,117 -> 48,123 rows); lt_elderly_disabled 4,322 -> 4,261 (rows that left the board; rows in both 1.25% -> 1.23%); lt_foreclosure_sale 825 -> 797 (rows that left the board; rows in both 0.23% -> 0.22%).

Real regressions: comps: HOT+WARM rows: 40.77% -> 26.63% (18,560 -> 17,710 rows); atty_rod_lien_checked: HOT+WARM rows: 4.8% -> 2.71% (2,185 -> 1,805 rows); divorce: HOT+WARM rows: 4.6% -> 3.07% (2,094 -> 2,043 rows); multi_year_delinquent_tax: HOT+WARM rows: 5.85% -> 3.08% (2,662 -> 2,048 rows); source:counties_nc.rutherford_tax: 5,109 -> 4,468 rows (87%); missing rows by reason: {'folded_into_another_row': 1, 'unexplained': 581}; source:counties_nc.buncombe_delinquent_tax: 1,182 -> 827 rows (70%); missing rows by reason: {'folded_into_another_row': 1}; source:counties.multi_year_delinquent_tax: 1,115 -> 436 rows (39%); missing rows by reason: {}; source:law_firms.kania: 177 -> 150 rows (85%); missing rows by reason: {}; source:counties_sc.sc_catalis_delinquent_roll: 63 -> 53 rows (84%); missing rows by reason: {}; lost:tax_levy_year: 712 of 63,186 rows in both lost their tax_levy_year (1.13%); lost:comps: 1,599 of 69,706 rows in both lost their comps (2.29%); audit:drops-situs-road-nulled: 0 -> 82 violations (newly not ok); audit:pipeline-row-valued: 0 -> 5 violations (newly not ok); audit:pipeline-countyless-national: 0 -> 18 violations (newly not ok); audit:source-county-floor: 0 -> 5 violations (newly not ok); artifact: Pages site would be about 969 MB (>= 950 MB: the build fails).

Defects found later: in the gated run's code (pin d42058b3) and its data, found by the 2026-10-08/09 audits and fixed after the pin (they take effect in the next run): copied county tax debts on 20,185 rows (tax_binding); property and person blocks that are another row's record on 42,618 rows (block_binding); the SC tax roll scraper finished 11 of 29 counties (qPayBill timeout); grades computed before equity on 20% of rows; verification and the tax restore ran after the valuation; owner tenure ran before SC sale dates; 8% of nulled short parcel ids were the county's own; the vision reader stopped after 100 failed local photos; Pages deploys failed over the 950 MB limit from 2026-10-08 11:46 UTC (docs/handoff/ now excluded).
