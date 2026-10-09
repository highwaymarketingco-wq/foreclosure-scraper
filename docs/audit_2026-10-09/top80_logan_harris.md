# Audit 2026-10-09, area top80_logan_harris: Logan Systems and Harris Recorder registers

Owner chose to build the top 80 of the ranked build list. This group: the 9 items (15 cells) of rank <= 80
whose source is a register on Logan Systems (Public Records "Remote Access Site" Blazor, "The Lookup",
v1.3.14) or Harris Recorder (AcclaimWeb, the Aumentum "ROD Web Access" in Moore). Ranks 10, 18, 26, 40, 41,
44, 52, 67, 73.

## 1. What was measured, and how

Owners sampled from the published board (streamed, ids and counts only; peak RSS under 300 MB). All live
calls paced (1.6 s or more a host, one request at a time, ordinary browser User-Agent). Chromium for the
Logan Blazor measurements: one browser at a time, closed after every lookup.

| platform | counties | live | result |
|---|---|---|---|
| Harris AcclaimWeb, per-owner name search (existing) | Horry | 6 owners | 5 had instruments; 5.8 to 11.6 s a lookup; capped 30 lookups a county a run, so 11,841 rows can never all be read this way |
| Harris AcclaimWeb, county-wide document-type sweep (NEW) | Horry, Pickens | 800 board owners (400 + 400), 22 months of register data each | Horry 10,940 adverse instruments, Pickens 401; 5 s a month of data; 799 rows stamped: 31 found, 10 possible, 758 screened none found, 1 unusable name; whole pass 219 s |
| Logan Public Records Blazor (browser; existing adapter) | Cabarrus, Chatham, Cumberland, Sampson, Union, Catawba | 2 owners each (12) | 20 s a lookup with a result, 47 s when nothing is indexed (the adapter waits 30 s before believing zero); Cumberland 2 of 2 empty; Chromium 245 to 290 MB; 900 s fits about 26 lookups against 10,292 rows |
| Logan "The Lookup" | Transylvania, Spartanburg | search page read | land-record indexes only (deeds, mortgages, liens, plats, UCC); no marriage index |
| Harris AcclaimWeb document types | Horry (143 types), Pickens (199) | form read | no marriage or vital type (Pickens has only a death certificate type) |
| Aumentum "ROD Web Access" | Moore | 1 browser visit | landing 200, then a Cloudflare challenge page after the disclaimer click: wall confirmed 2026-10-09 12:10 and not retried |

Repeat: `uv run pytest tests/test_top80_logan_harris.py`; the sweep alone:
`uv run python -c "from datetime import date; from foreclosure_scraper.rod import lien_sweep as L; print(L.sweep_county('Horry', since=date(2026,1,1))[1])"`.

## 2. Defects found and fixed

| defect | scale | cause | fix | test | invariant |
|---|---|---|---|---|---|
| the Horry/Pickens lien check could never reach most rows | 6,442 Horry + 5,124 Pickens owner rows on the board (11,841 rows by the build list) against 30 lookups a county a run | only a per-owner name search existed (about 9 s each) | `rod/lien_sweep.py` + `enrichment_register_lien_sweep.py`: one county-wide read of the adverse-lien document types by month, matched to every owner offline; stamp `raw['rod_lien_sweep']` | tests/test_top80_logan_harris.py | `top80-lien-sweep-coverage` (ratchet 11,566 owner rows unstamped), `-shape`, `-county-only`, `-name-fit` |
| a clean "nothing found" is not a claim about all time | design | a sweep covers a window, not the register's whole history | the stamp carries `window_from`/`window_to` and is `none_found` for that window only; the sweep goes newest month first, so a budget that ends early claims only the months read | same | `top80-lien-sweep-shape` (window dates ordered, none_found beside no instrument) |
| a middle initial or a "JR" made a first-name match look certain | 65 of 149 matched Horry owners were name-only (84 exact) | suffixes are dropped from index names | every hit carries `fit`: parcel (register parcel number equals the row's), exact (surname, first name, middle initial agree) or name; `found` needs parcel or exact, otherwise `possible` | same | `top80-lien-sweep-name-fit` |
| cube counted the sweep as no check | design | `liens`' check was `raw.rod` only | `gap_matrix.checked_columns` and `rod_checked` read a dated `rod_lien_sweep` | same | same |

Satisfactions and releases are not swept: the stamp lists the lien instruments recorded in the window, not
whether they were later satisfied (a title check wants the history; the satisfaction is a separate read).
The sweep is not a mortgage check.

## 3. Item by item

Built, ON in the next run (flag `FORECLOSURE_SC_LIEN_SWEEP=1`, budget `FORECLOSURE_LIEN_SWEEP_BUDGET_S=600`;
plain HTTP, cached in `data/lien_sweep/`, git-ignored):
- rank 10 Horry liens (1 cell, 11,841 rows). Also covers Pickens liens (not in the top 80).
  The first run reads newest month first until its budget (about 5 s a month: 100+ months fit), later runs
  read only the new months.

Built before this audit, measured, kept OFF (browser-only; the whole group would need about 6 times the 900 s
budget even at 20 s a lookup, and the Blazor adapter spends 47 s on a name with nothing indexed):
- rank 18 Cabarrus, Chatham, Cumberland liens (3 cells, 10,292 rows) and rank 52 Sampson, Union liens
  (2 cells, 2,826 rows): `FORECLOSURE_NC_LOGAN_BLAZOR_ROD` stays 0. The owner can turn it on with a time
  budget: `FORECLOSURE_NC_ROD_RENDER_BUDGET_S` (default 3600 s) allows about 105 lookups, 30 a county a run.
  A date sweep is not possible here: the Blazor Instrument Date grid lists instruments with no party names.
  These 5 cells stay open (cost), not closed.

Verdict, no free source (cell closed; matrix `rod.column_access.marriage_license = none`, with the
how_verified note per county):
- rank 26 Spartanburg and rank 40 Transylvania (The Lookup has land-record indexes only; the county issues
  licenses elsewhere).
- rank 44 Horry and rank 67 Pickens (AcclaimWeb has no marriage type; SC marriage licenses are issued by
  the Probate Court, a separate system outside this register).
- rank 41 Cabarrus, Catawba, Chatham, Cumberland (4 cells): the Full System lists a Marriage index (dates
  back to 1855) but its name search reaches the land index only; the Marriage index can be picked on the
  Instrument Date tab, which returns 38 marriage instruments for one week of Cabarrus as instrument number,
  book and page with no party names. An owner cannot be looked up, and a browser sweep of the years
  needed is hours.

Walled (cell closed as walled; matrix access `blocked` already recorded):
- rank 73 Moore liens: Cloudflare challenge page after the disclaimer click, re-checked 2026-10-09 12:10 with
  one browser visit; not retried, not worked around. Manual step: open rod.moorecountync.gov in an ordinary
  browser, click the disclaimer link, and search the owner by hand (the register is also in person at the
  Carthage office).

Cells: 15 in the set. Closed by this work: 1 (Horry liens, as the run stamps rows) + 8 marriage verdicts + 1
walled (Moore) = 10. Open: the 5 browser-only Logan liens (cost).

## 4. Open items and not verified

- Browser-only Logan liens: an owner decision on run time (see above). Cost per record is measured on 12
  lookups, not a full county.
- The sweep window starts at `FORECLOSURE_LIEN_SWEEP_SINCE` (2016-01-01); older liens are not claimed absent.
- Pickens has far fewer adverse instruments than Horry (401 in 22 months); not cross-checked against another
  source.
- Parcel numbers were empty in every swept Horry row of the live check (no `parcel` fit occurred); matching
  is by name until the register fills them.
- No marriage index of the SC Probate Courts was read (outside this group; southcarolinaprobate.net answered
  HTTP 403 in the sibling group's check).
- Outside the area: `tests/test_prerun_gate.py::test_the_real_profile_matches_vm_lib_and_the_real_code`
  fails on another group's module (`enrichment_county_lien_sweep`, no wiring line or reason recorded).

## 5. Wiring (main.py is the lead's)

File `src/foreclosure_scraper/main.py`, in `run_enrich_tail`, right after the `nc_rod_render` try/except
(anchor: `log.error("nc_rod_render.failed", traceback=traceback.format_exc())`):

```python
    try:
        from .enrichment_register_lien_sweep import enrich_register_lien_sweep
        _lien_sweep_s = float(os.environ.get("FORECLOSURE_LIEN_SWEEP_BUDGET_S", "600")) + 180
        s = await _await_capped(enrich_register_lien_sweep(enriched), "register_lien_sweep", default_s=_lien_sweep_s)
        if s and "skipped" not in s: enrichment_stats["register_lien_sweep"] = s
    except Exception:
        log.error("register_lien_sweep.failed", traceback=traceback.format_exc())
```

The module is declared in `deploy/oracle/run_profile.json` `unwired_wire_pending`; once the lines are in, tidy
that entry (the gate says so). `raw['rod_lien_sweep']` is in RAW_KEEP (web_artifact.py). The board's
`_SLIM_RAW`/dashboard are untouched (the key is for the cube and the attorney sheet, not the dashboard).
