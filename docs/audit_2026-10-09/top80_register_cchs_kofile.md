# Audit 2026-10-09, area top80_register_cchs_kofile: Courthouse Computer Systems, GovOS CountyFusion, GovOS/Kofile PublicSearch

Owner chose to build the top 80 of the ranked build list. This group: the 15 items (32 cells) of rank <= 80 whose
source is a register on Courthouse Computer Systems (classic ASP and LRSearch), GovOS CountyFusion or GovOS/Kofile
PublicSearch (ranks 28, 31, 32, 34, 43, 45, 49, 53, 61, 62, 63, 72, 76, 78, 79).

## 1. What was measured, and how

All live calls polite (>= 1.6 s a host through nc_polite / sc_polite, one request at a time per host, an ordinary
browser User-Agent, every reply wall-checked), board owners sampled with `board_stream.iter_board_rows` (289 MB peak,
one pass at a time), ids and counts only; no owner name is in the repo. Repeat the sweeps with
`uv run python -c "import asyncio; from foreclosure_scraper.enrichment_county_lien_sweep import enrich_county_lien_sweep"`
on a list of board rows, or per county `rod.county_sweeps.sweep(reader, since=date(2016,1,1))`.

What the 10/7 survey recorded as walled or unbuilt, re-read on 2026-10-09:

| platform | counties | what is really there |
|---|---|---|
| CCS LRSearch | Beaufort NC | open: no login, CAPTCHA or challenge. The 10/7 "challenge marker" is Cloudflare's passive browser beacon (`/cdn-cgi/challenge-platform/scripts/jsd/main.js`) on the landing page; the shared wall detector reads the string "challenge-platform" as a challenge page. The search pages answer 200. The same site has an open Marriages index (last, given, date; no login) |
| CCS classic ASP, vendor-hosted | Caldwell, Camden, Caswell, Chowan, Currituck, Dare, Duplin, Franklin, Gates, Hertford, Hyde, Montgomery (+ Madison, Lincoln, Henderson, Burke, Cleveland) | `application.asp` (the frame page) is the Cloudflare 403; `realestatesearch.asp` and `SearchService.asp`, the two pages the search itself uses, answered a plain request with 200 and real XML on 17 of 17 tenants (all swept end to end), no challenge, no cookie from `application.asp`. Their pages also carry the passive beacon |
| CCS classic ASP, county-run | Orange (also Stanly, Surry) | plain 200 throughout; the dictionary has 191 kinds, 7 adverse; no marriage kind |
| GovOS CountyFusion | Sumter SC | the "Login as Guest" button takes no username or password (public=true, empty boxes, the Cott precedent ruled a click-through 2026-10-07), then a plain Accept on the disclaimer; no CAPTCHA or challenge; the All Names form accepts a blank name with a document-type list and a date window |
| GovOS/Kofile PublicSearch | Oconee SC | the root page embeds the 154 document-type options; the WebSocket accepts `docTypes` with `recordedDateRange` (8 adverse types, 8,436 instruments in ten years) |

## 2. Defects found and fixed

| defect | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|
| the shared wall detector reads Cloudflare's passive jsd beacon as a challenge page | Beaufort and every vendor-hosted CCS page (their landing and search pages all carry it): 17 counties, 25,000+ board rows recorded as walled | `wall_reason` / `detect_wall` match `challenge-platform` anywhere in a 200 page | `rod/county_sweeps.BeaconBlindSession`: a 200 reply whose only brush with Cloudflare is that beacon path has it neutralised before the wall check; any "Just a moment" title, cf-chl token, `_cf_chl_opt`, CAPTCHA widget, non-200 status or other marker is passed through untouched. The shared detector is not edited | `test_beacon_blind_client_*`, `test_shared_wall_detector_reads_the_passive_beacon_as_a_challenge` | `top80-sweep-county-silent` |
| liens / atty_rod_lien_checked could not reach 3,000+ rows a county | Orange 2,887, Sumter 3,533, Oconee 3,689, Beaufort 3,550 owner rows (+ Lincoln 18,436, Henderson 3,788, Hyde 2,652 ...) | the per-owner readers are capped at 30 lookups a county a run | county-wide adverse-instrument sweeps by document type and date window, matched to every board owner offline (`rod/county_sweeps.py`, `enrichment_county_lien_sweep.py`); the cube reads `raw['rod_lien_sweep']` (`gap_matrix.rod_checked`) | `tests/test_top80_register_cchs_kofile.py` | `top80-sweep-stamp-shape` |
| a "screened, none found" with no window would read as "no lien ever" | design | the sweep covers adverse types in a date window only | the stamp carries `window_from..window_to`, `adverse_types`; a window the register said was too big is bisected; a day that still overflows, a wall, an error or an exhausted budget shortens the claimed window or stamps nothing | `test_read_back_*`, `test_sweep_*` | `top80-sweep-stamp-shape` |
| owner strings with a trailing comma ("DOE JOHN A,") parsed to nothing | 6 of 60 sampled Beaufort owners | the name parser gives up on the comma | `county_sweeps.clean_owner` strips trailing commas and semicolons before matching | `test_party_index_*` | (counted in unmatchable) |

## 3. Live proof (2026-10-09, cold caches, counts only)

County-wide sweeps, 2016-01-01 to 2026-10-09, run through the production readers; "sample" = 40 to 60 board owners
drawn at random from the published board (owner names stay out of the repo), stamped by the production matcher.

| county | platform | requests (windows) | seconds | adverse instruments read | document types asked for | sample result |
|---|---|---|---|---|---|---|
| Orange NC | CCS classic, county-run | 11 | 44 | 327 | 7 | 57 none_found, 1 found, 2 unmatchable (of 60) |
| Beaufort NC liens | CCS LRSearch | 11 | 39 | 397 | 4 | 52 none_found, 8 unmatchable (of 60; 6 of the 8 were owner strings ending in a comma, now cleaned) |
| Beaufort NC marriages | LRSearch Marriages index | 11 | 29 | 3,031 licences | 1 | 37 no_match, 1 possible, 22 not a person (of 60) |
| Sumter SC | GovOS CountyFusion | 59 | 395 | 2,395 | 20 | 57 none_found, 2 found, 1 possible (of 60) |
| Oconee SC | GovOS/Kofile PublicSearch | 11 (about 90 pages) | 282 | 8,357 | 8 | 55 none_found, 1 found, 4 possible (of 60) |
| Hertford, Gates, Franklin, Hyde, Montgomery, Chowan, Caldwell, Currituck, Caswell, Camden | CCS classic, vendor-hosted | 11 each | 32 to 56 | 219, 140, 16, 44, 160, 146, 788, 344, 159, 111 | 2 to 12 | 0 walled, 0 errors; 40 none_found of 40 in most, 2 possible Camden, 1 possible Caldwell, 1 found Montgomery |
| Lincoln, Henderson, Madison, Burke, Cleveland, Dare, Duplin | CCS classic, vendor-hosted | 11 each | 44 to 66 | 553, 552, 167, 633, 883, 362, 389 | 5 to 22 | Lincoln 5 found of 40, Henderson 4 of 40, Madison 1, Burke 3, Cleveland 2 found + 2 possible, Dare/Duplin none |
| Stanly, Surry NC | CCS classic, county-run | 11 each | 45 | 434, 400 | 7, 6 | Surry 1 found of 40 |

Name readers (new, in the generic registry, ON): Sumter by owner name, 9 lookups, 9 ok with instruments (214 in all),
about 6 s a lookup once the 15 s guest session is held, plus one deed-chain call (4 searches, last deed found, 6 deeds of
trust and 7 satisfactions). Beaufort by owner name, 9 lookups, 9 ok: 2 with instruments (88), 7 a clean "nothing indexed
under this name" (the register's verified index starts 1995-01-01, so an owner who has held the parcel since before
that has nothing under their name; the status ok lets the generic pass record it as a checked negative).

Cold cost of the pass: Sumter 395 s, Oconee 282 s, every other county 29 to 66 s; later runs re-read the newest 14 days
and the new end only (about 2 to 4 requests per county plus the 15 s CountyFusion sign-in). The 23 counties hold 51,499
board rows (Lincoln 18,436, Henderson 3,788, Oconee 3,689, Beaufort 3,550, Sumter 3,533, Orange 2,887, Hyde 2,652 ...).

## 4. Item by item

Built, ON in the next run (flags in run_profile.json and vm_lib.sh, wiring line in unwired_wire_pending):
rank 31 and 49 Beaufort (liens, atty_rod_lien_checked: sweep + name reader, 3,879 owner rows); 32 Oconee liens (sweep, 3,765);
34 and 53 Sumter (sweep + name reader, 3,612); 43 and 62 Gates, Hertford, Hyde, Montgomery (hosted CCS sweep, 4,191);
45 Orange liens (sweep, 2,891); 61 Franklin and Madison liens (2,401); 63 and 72 Caldwell, Camden, Caswell, Chowan, Currituck
(2,949); 79 Beaufort marriage licences (Marriages index swept, 3,424). 27 cells. They close to "checked" row by row as the
run stamps raw['rod_lien_sweep'] / raw['marriage_license'] (the cube reads both; `gap_matrix.rod_checked`).

No free source (verdict, cell closed; matrix `rod.column_access.marriage_license = none`): rank 28 Lincoln, 76 Greenville,
78 Franklin, Henderson, Madison. 5 cells. The CCS classic application has no marriage instrument kind (dictionaries read
2026-10-09: Lincoln 214 kinds, Henderson 1,371, Madison 145, Franklin 158, Orange 191, and 12 more tenants; none has a marriage
or licence kind; the office's "Marriage Licenses" page is a fee and procedure page). Greenville: SC marriage licences are issued by
the Probate Court; the PublicSearch register has no marriage type and the county's free Probate Case Search lists estate and
guardianship party types only. The same verdict is written for the other CCS tenants whose marriage cell sits in the cube
(Gates, Hertford, Hyde, Montgomery, Caldwell, Camden, Caswell, Chowan, Currituck): 9 more cells.

Walled: none of this group's items are walled any more. The 10/7 verdicts were two false positives (the passive Cloudflare
beacon, and the frame page standing for the whole application).

Dropped: nothing.

## 5. Open items and not verified

- A sweep reads ADVERSE instrument types only (lien, judgment, lis pendens, foreclosure, tax lien) and only the window on the
  stamp. In NC many liens and judgments are filed with the clerk of court, not the register, so low counts in the NC counties
  (Franklin 16 instruments in ten years) are real, and a `none_found` means "no adverse instrument indexed under this name in
  the register", not "no lien" and not "no mortgage".
- Matching is by owner name (surname, first name, middle initial), no parcel: a namesake can read as `found`. Every hit keeps
  its `fit` (exact or name) and the instrument's book, page and type so a person can open it. 6 of 60 Beaufort owner strings
  and 2 of 60 Orange strings could not be turned into a name query at all (stamped nothing, not "none found").
- The name readers (Sumter, Beaufort) are capped at 30 lookups a county a run (`FORECLOSURE_SC_COUNTYFUSION_ROD_MAX`,
  `FORECLOSURE_NC_LRSEARCH_ROD_MAX`); coverage of the mortgage and deed picture stays partial, the adverse check does not.
  They inherit the shared parser's guess of name order; Beaufort's 1995 index start makes long-held parcels read as empty.
- The vendor-hosted CCS tenants answer the data pages today. Cloudflare's rule is per-path and can change: the reader walls the
  county for the run on the first challenge, 403 or CAPTCHA and stamps nothing. Not re-tested after 2026-10-09.
- Not checked: the counties' full instrument lists for adverse kinds I did not match by name (a "NOTICE" kind, for example);
  Greenville PublicSearch (not swept: its lien cells are not in the top 80 and are 0.7% checked); Alleghany to Washington (the nine
  hosted-search tenants in the wall card, a different application); Camden's lien cell uses its us4 application
  (the matrix address is its us5 landing page).
- Cost on the VM: a cold first run adds about 10 minutes of paced reads (hosts in parallel, Sumter and Oconee longest); the cache
  `data/county_sweeps/` (git-ignored) must survive between runs or every run is cold.
- Outside the area: `tests/test_prerun_gate.py` fails on other agents' new modules (enrichment_onemap_sweeps has no wiring or
  reason recorded; frozen-keys count differs by 2); `tests/test_audit_checks_tax_checkers_2.py::test_a_county_with_no_checker...`
  fails on the current working tree (Chowan is no longer unrecorded) - not mine.

## 6. Wiring (lead)

main.py, in the register block right after the `enrich_register_lien_sweep` try/except (or after the `enrich_nc_rod_render`
try/except if that is not in yet):

    try:
        from .enrichment_county_lien_sweep import enrich_county_lien_sweep
        s = await _await_capped(enrich_county_lien_sweep(enriched), "county_lien_sweep",
                                default_s=float(os.environ.get("FORECLOSURE_COUNTY_SWEEP_BUDGET_S", "900")) + 240)
        if s and "skipped" not in s:
            enrichment_stats["county_lien_sweep"] = s
    except Exception:
        log.error("county_lien_sweep.failed", traceback=traceback.format_exc())

The same text is in `deploy/oracle/run_profile.json` `unwired_wire_pending.enrichment_county_lien_sweep`. The Sumter and Beaufort
name readers need nothing: they are in `enrichment_generic_rod.ROD_CONFIG`.
