# Audit 2026-10-09, area top80_register_other: Cott eSearch, BIS, Tyler and Marlboro registers

Group: the top-80 build-list items whose register is Cott Systems eSearch (county-hosted, v4, guest),
Business Information Services (Forsyth, Davidson), Tyler (Durham Self-Service, Johnston EagleWeb) or
the older Cott eSearch (Marlboro SC). Ranks 16, 23, 25, 29, 30, 46, 50, 54, 57, 58, 64, 65, 71, 75.
Counts only; no names, parcels or notice text in this file.

## 1. What was measured and how

All live reads: ordinary browser headers, 2 s between two requests to a host in every probe (the
production adapters pace at 1.6 s, `nc_polite.MIN_GAP_S`, asserted by tests/test_nc_rod_chain.py: lead
to decide whether 1.6 meets the 2 s rule), one request at a time per host, guest click-through only.

| probe | result |
|---|---|
| per-owner name search, 6 real board owners on each of 14 NC counties + Marlboro SC | 90 of 90 answered `ok` (Forsyth, Davidson, Durham, Johnston, Onslow, Pitt, Alamance, Alexander, Pamlico, Polk, Edgecombe, Rutherford, Graham, Nash, Marlboro) |
| generic_rod with the new status interface, 5 board owners + 2 made-up names per county, 15 counties | 75 lookups: 28 with instruments, 46 `screened_none_found` (30 of those are the made-up names; 16 real owners with nothing indexed), 0 errors |
| marriage index, 3 common names on 8 Cott counties | Onslow 55 marriage rows, Pamlico 2, Edgecombe 2, Rutherford 8; Alamance/Alexander 0 under "All" (their MARRIAGES index only answers when selected: see CottV4Marriage) |
| per-owner marriage search with Index Type = MARRIAGES, 3 names, 6 counties | owner-matched blocks 3/3 in each of the six |
| county-wide lien sweep (adverse kinds), Nash since 2025-01-01 | 62 windows, 94 adverse instruments (82 foreclosure, 12 judgment), 145 s |
| county-wide sweeps, 5 counties x lien + marriage, 40 real board owners each, since 2025-04-01 | 975 s (three of the five share one host, so their requests queue); lien: 188 none_found, 5 found, 1 possible, 6 unmatchable of 200; marriage: 146 no_match, 1 possible, 13 unmatchable of 160 |
| lien sweeps, Alexander, Pamlico, Graham, Polk since 2026-04-01 | 15 windows, 40 s each, 12 / 4 / 1 / 7 adverse instruments |
| marriage sweeps, Alamance and Alexander since 2026-06-01, Pamlico since 2026-04-01 | 459 / 68 / 36 licences; paging checked on one window (149 counted, 149 read, 149 distinct) |
| Rowan sign-in page, one GET | still a challenge page (also 2026-10-07): wall |
| Forsyth `vital/login.php`, one GET | a login page: wall |
| Davidson, 4 common names (558 instruments) | 0 marriage rows although the form lists a MARRIAGE code: no source |

Not verified: a full first sweep back to 2020 (the sweeps are newest window first and cached, so a short
budget claims a shorter window; the stamp always states the window); Tyler (Durham, Johnston) and the BIS
counties have no date or type sweep here (only the per-owner search, capped at 30 lookups a county a
run); Marlboro the same.

## 2. Defects found

| defect | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|
| a clean empty register answer left the row unstamped, so a county with a working adapter read 0% "checked" | 16 counties, 0% on the 10/9 checkpoint although 90 of 90 live lookups answered | enrichment_generic_rod cannot tell "searched, nothing" from "fetch failed" | the Cott v4, Tyler, Polk (rod/cott) and Marlboro modules now report a status (`search_by_name_status`), which the top80_register_ors change to generic_rod stamps as `screened_none_found` | tests/test_register_checks_top80.py (status interface, a Cott county end to end) | top80-other-none-found-shape, top80-other-county-silent |
| 10 counties x 150 to 9,300 rows could never be lien-checked by a 30-lookup-a-run name search | 48 cells of this group | per-owner cap | rod/cott_sweep.py: the Cott Date Range search read once by adverse kind and window, matched offline (rod/county_sweeps.py); stamps `rod_lien_sweep` for the window read | tests/test_cott_sweep.py (14) | top80-other-sweep-shape |
| the marriage index of six Cott tenants was never read | Onslow, Alamance, Alexander, Pamlico, Edgecombe, Rutherford: 12,582 board rows | the retired marriage enricher read only Aumentum tenants | the MARRIAGES index swept by date (county-wide) and searched by name for rows the sweep left | same | top80-other-marriage-bound |
| the kind selection of the Date Range tab is consumed by a search | first sweep returned the whole county (22,248 rows, "types 3") | a list selection is an auto-postback and the server forgets it after a search | the selection is posted again before every window; a test pins the order | test_the_kind_selection_is_posted_before_every_window | - |
| a results grid pages at 10 to 500 rows by tenant (Alamance 10) | marriage windows of 149 rows read 10 | tenant default | results-per-page raised to its maximum, `Page$N` postbacks for the rest; a window over 1,500 rows is split | test_paging_reads_every_row... | - |
| Rowan counted as a free guest-button county in the walls register although its sign-in page is a challenge page | 4,287 rows | stale note | card nc_rowan_cott, the two sentences listing it as free corrected | tests/test_build_owner_manual.py | top80-other-config-consistent |

## 3. Items: built / walled / verdicts

| rank | cell | verdict |
|---|---|---|
| 30 Onslow liens, 54 Alamance/Alexander/Pamlico/Polk liens, 64 Graham/Nash liens | liens (check) | BUILT: county-wide sweep, proven live on all ten counties; was sourced-not-built, now built-but-low-yield until a run stamps the rows |
| 58 marriage Alamance, Alexander, Edgecombe, Pamlico, Rutherford | marriage_license | BUILT: marriage sweep + per-owner MARRIAGES search, proven live on all five (and Onslow) |
| 58 Polk, 65 Pitt marriage | marriage_license | VERDICT no source known: the guest search Index Type list has no marriage, birth or death index (2026-10-09) |
| 71 Davidson marriage | marriage_license | VERDICT no source known (also recorded by top80_register_ors): the form lists a MARRIAGE code, 0 of 558 instruments for 4 common names |
| 16 Forsyth liens, 25 Davidson liens (BIS) | liens | BUILT earlier (nc_ors, ON): this pass adds the status interface + clean-empty stamp; per-owner only (30 a county a run), so the cell stays built-but-low-yield |
| 23 Durham, 50 Johnston liens (Tyler) | liens | same: nc_tyler ON, status interface added, per-owner only |
| 75 Marlboro liens (Cott eSearch SC) | liens | same: sc_cott_esearch ON, status interface added, per-owner only |
| 29 Rowan liens, 46 Rowan atty_rod_lien_checked, 65 Rowan marriage | liens, atty_rod_lien_checked, marriage_license | WALLED (challenge page, re-fetched 2026-10-09); card nc_rowan_cott with the manual steps; the cube reads the matrix verdict |
| 57 Forsyth marriage | marriage_license | WALLED (Vital Records login); card nc_forsyth_vital |

Cube effect on the 48 cells of the group's counties (computed from gap_list_2026-10-09.csv with the new
code, not a board re-run): 18 sourced-not-built -> built-but-low-yield, 5 -> no source known, 4 -> walled,
3 unchanged (Durham, Johnston, Marlboro marriage: not top-80 items), 18 already built-but-low-yield stay
until a run stamps the rows. Rows with an owner name the matcher cannot use (3% to 8% in the live
samples) stay unchecked, so a swept cell approaches but does not reach 100%.

## 4. Open items

- Run cost: the cotthosting.com tenants (eight counties) share one host, so their sweeps queue. Measured
  975 s for five counties x lien + marriage over 1.5 years; the default is since 2020-01-01 under a
  1,800 s per-county budget, newest window first, cached in data/county_sweeps/ (git-ignored: it must
  persist on the VM between runs or every run restarts at today).
- Tyler (Durham, Johnston), BIS (Forsyth, Davidson) and Marlboro have no date/type sweep built: not
  attempted this pass.
- rod/county_sweeps.py (the CCHS/Kofile group's module) is imported here; it was uncommitted when this
  pass was written.

## 5. Seen outside this area

- tests/test_prerun_gate.py::test_frozen_keys_known_in_the_real_profile counts 22 frozen keys against 24
  in the profile (another group's change).
- docs/OWNER_MANUAL_LANES.md and the Desktop manual were regenerated for the two new cards.
