# Audit 2026-10-09, area top80_register_ors: Online Record System, Aumentum/Harris Recorder, Charleston ROD

Owner chose to build the top 80 of the ranked build list. This group: the 17 items (24 cells) of rank <= 80
whose source is the Online Record System (NameSearch/NamePick/NameDisplay, NC and SC), the Aumentum Recorder
web access (Mecklenburg, Moore) or the Charleston County ROD.

## 1. What was measured, and how

All live calls polite (>= 2 s a host, one request at a time, ordinary browser User-Agent), samples of board
owners from the published board (streamed, 283 MB peak), ids and counts only. Most of the readers already
existed; the cube listed these cells as "sourced-not-built" because its `liens` producers did not name the
register registry, and because a lookup that found nothing was never recorded (it left the row unstamped).

| platform | counties | live lookups | result |
|---|---|---|---|
| NC Online Record System | Davidson, Forsyth, Guilford | 7 + 7 + 7 | Davidson 7 ok (5 with nothing indexed under the name); Forsyth 7 ok (2 to 42 s each); Guilford 4 ok then HTTP 403 on 3 (the adapter stops the county for the run; a single request a minute later was 200) |
| SC Online Record System | Barnwell, Berkeley, Dorchester, Georgetown, Florence, York, Lancaster, Colleton | 4 each (32) | 32 ok; 13 of 32 had nothing indexed under the owner's name; 2 to 55 s each |
| Harris ROD Web Access (browser) | Mecklenburg | 6 real estate + 6 marriage | peak 549 MB (browser plus python), 15 to 43 s a lookup; 3 of the first 6 real-estate lookups were reported as errors (defect below) |
| Charleston ROD | Charleston | form page only | wall recorded 2026-10-07 (results viewer reCAPTCHA); not passed |

Repeat: `uv run python scripts/gap_matrix.py ...` (cube), `uv run pytest tests/test_top80_register_ors.py`.

## 2. Defects found and fixed

| defect | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|
| a clean "searched, nothing indexed under this name" left the row unstamped (retried every run, never counted as checked) | live: 5 of 7 Davidson, 13 of 32 SC lookups | `search_by_name` returned `[]` for no hit, wall, cap and failure alike | `search_by_name_status` on the NC platform base, `nc_ors`, `sc_chain.run_search_status`, `sc_online_record_system`; `enrichment_generic_rod` stamps `raw['rod']` with `instrument_count` 0, `screened_none_found`, `fetched_at` only for status ok and not truncated | tests/test_top80_register_ors.py | `top80-register-negative-shape`, `top80-register-county-silent` |
| Harris "0 records found" page read as an error | 3 of 6 Mecklenburg lookups | the count regex needed a "(" before the number; the live empty page has none ("; 0 records found", "begins with X 0 records found") | `nc_harris.parse_results`, `no_records` | same | `top80-register-county-silent` |
| cube said "sourced-not-built" for readers that exist | 11 cells | `liens` producers did not name `enrichment_generic_rod.py` (the county registry) | producers list; `gap_matrix.source_status(..., col)` takes a per-column verdict | same | `top80-register-config-consistent` |

## 3. Item by item

Built, ON in the next run (flags already ON in run_profile.json and vm_lib.sh): rank 11 Guilford, 16 Forsyth,
25 Davidson (NC ORS); 24 Barnwell/Berkeley/Dorchester/Georgetown, 48 Florence, 66 York, 77 Lancaster (SC ORS).
10 cells; they close to "checked" row by row as lookups land: cap 30 per county per run, imminent leads first.

Built, OFF (browser-only, measured not cheap: 15 to 43 s and 540 MB a lookup, 13,960 Mecklenburg owners):
rank 7 Mecklenburg liens (`FORECLOSURE_NC_HARRIS_ROD`), rank 33 Mecklenburg marriage licences (new
`nc_harris.marriage_search`, the register's own Marriage index in the same guest session, flag
`FORECLOSURE_NC_HARRIS_MARRIAGE`, added to run_profile.json and vm_lib.sh at 0). Live: 6 marriage lookups,
1 licence found and 5 clean "none". 2 cells.

Walled (verdict, cell closed as walled): rank 13, 20, 56 Charleston (results viewer loads reCAPTCHA; matrix
`rod.access` now captcha; manual lane already in the owner manual); rank 73 Moore (Cloudflare HTTP 403 on the
disclaimer postback; matrix access blocked). Marriage licences: rank 47 Guilford and 57 Forsyth (the "Vital
Search" button goes to `vital/login.php`, a username and password form); rank 69 SC Barnwell, Berkeley,
Colleton, Dorchester, Georgetown (marriage licences are issued by the probate court; the register has no
marriage instrument type; southcarolinaprobate.net answered HTTP 403 on 2026-10-09). 9 cells.

No free source (verdict): rank 71 Davidson marriage (the name index lists a MARRIAGE type but 0 of 191
instruments for a common name were marriages). 1 cell.

## 4. Open items and not verified

- Coverage is capped, not complete: 30 lookups a county a run (`NC_ROD_MAX_LOOKUPS_PER_COUNTY`,
  `SC_ROD_MAX_LOOKUPS_PER_COUNTY`) against 1,200 to 9,300 owners a county; Forsyth took up to 42 s a lookup.
  Raising the cap is an owner decision on run time.
- Guilford's HTTP 403 after the fourth lookup: cause not established (rate limit or bot rule); it was not retried
  or worked around. Lookups there may stop early each run.
- A "none found" is by owner name only; an owner indexed under a different spelling or a trust name reads as
  none. It says "screened, no instrument under this name", not "no lien".
- Not re-verified today: the Charleston reCAPTCHA (relied on the 2026-10-07 check; a plain POST of the search form returned the form page again, so the
  results could not be seen without the page's own script) and the Moore 403.
- Outside the area: `tests/test_prerun_gate.py::test_the_real_profile_*` fail on two other agents' new modules
  (gis_fill, enrichment_register_checks, no reason recorded); not mine.
