# HANDOFF — current state of play

**Updated 2026-08-12.** Read this first in a new session, then go straight to
work. Everything below is either verified or explicitly marked unverified.

Keep this file current. It exists so a fresh session costs one file read instead
of an hour of rediscovery, and so long sessions can be abandoned cheaply.

---

## Where the board is

- ~38,500 leads, all confirmed seen within 7 days.
- ARVs on 25,338; max bids on 20,434.
- 3,809 leads carry a contradicted-ARV flag and correctly publish **no** bid, no
  verdict and no equity.
- `merge_prior_board` handles pulled-then-relisted correctly: `pulled_sale`
  counter, 4-miss retention, and on reappearance it clears the counter while
  preserving enrichment.

## What is running right now

A full engine run started **2026-08-11 13:24** and is at **~23 hours**. It is
**not hung** — it is in the final GIS phase doing FEMA flood-zone lookups **one
lead at a time**. That is the current binding constraint on run time and is the
next thing worth fixing (see Do Next).

Prior known hang: `run_local.sh` at 8.5h from geocode-at-1/sec plus a comps
CPU-spin. Same family of problem.

---

## Register of deeds — the current, corrected picture

This was wrong until 2026-08-12 and the correction matters.

### Two platforms, not one

| | The Lookup | Online Record System |
|---|---|---|
| entry | `index.php?Accept=Accept` | `NameSearch.php?Accept=Accept` |
| search | `content.php` (**GET**) | `NamePick.php` → `NameDisplay.php` (POST) |
| amount in index | no | **yes** |
| counties | clay, haywood, yancey (NC) | 8 SC |
| reader | `enrichment_rod_lookup.py` | `enrichment_rod_name_index.py` |

A previous commit recorded **12 counties on one platform**. Nine of them run the
SC platform and return **404 with a 16-byte body** to the Lookup reader, which
reads as "county has no records". Georgetown — the only one of the twelve with
board coverage (409 leads) — was among the nine, so that enricher enriched
nothing. All twelve answered HTTP 200 to the accept step.

### Wrong-state hosts — a standing trap

`<county>deeds.com` never states its state and county names repeat:

- **hendersondeeds.com is Henderson County KENTUCKY**
- **wilsondeeds.com is Wilson County TENNESSEE**

Both were one step from adoption as NC sources on pattern match alone.
`scripts/build_county_registry.py` now carries a `state_confirmed` check.

### What is open

- **`counties_nc.wnc_rod_foreclosure_starts`** (NEW, working): substitutions of
  trustee in **Clay, Haywood, Yancey NC** — three core counties that held zero
  leads. In NC an `S/T` is what *starts* a power-of-sale foreclosure, recorded
  before the notice of hearing reaches the clerk, so every other NC foreclosure
  source here is downstream of it. Validated live: 3 leads in a 4-day window.
- **8 SC counties**, name lookup only. Bulk date-range works on **Barnwell and
  Georgetown only**; the other five return the head of the whole index (exactly
  2000 parties for any window, including one day) so `bulk_by_date` refuses them.
  Both working counties are outside the core footprint, so the capability is
  built and documented but not wired as a lead source.

### Traps that look like success

- **One document is many rows.** The index emits a row per party and batching
  repeats a document once per batch. A raw 3-day Haywood window is **8,528 rows
  and 133 documents**. Dedupe on (date, book, type).
- **The pick list caps at 1000.** Haywood returned exactly 1000 parties for 21
  days vs 385 for 3. `bulk_by_date` halves a capped window and reads both halves.
- **The lead is the natural-person GRANTOR.** Servicer, lender and two trustees
  are all parties to the same instrument; without filtering, the lead reads
  "U.S. BANK TRUST, NATIONAL ASSOCIATION".

### Closed dead ends — do not re-attempt

- **`received_from`** on The Lookup: eight parameter variants, all 0 bytes.
- **Permitium** (18 NC counties): an ordering counter for certified copies. No
  name index, no date search. Counting it as coverage inflates recorders by 40%.
- **Bertie NC**: 2,617-byte disclaimer loop, still walled.

Full derivation: [`ROD_PORTAL_ACCESS.md`](ROD_PORTAL_ACCESS.md).

---

## Do next, in order

1. **Batch or cap the per-lead GIS enrichers** (FEMA flood zone, geocode). One
   request per lead is why a full run cannot finish overnight. Highest leverage
   item on the list.
2. **Wire `wnc_rod_foreclosure_starts` into a scheduled run** and confirm its
   leads survive a board merge.
3. **York SC** date-window behaviour is *undetermined*, not walled — it timed
   out repeatedly on a 470 KB page. Retry with a longer timeout.
4. **15 bespoke recorder platforms** still unclassified: alamance, beaufort
   NC+SC, cumberland, gates, guilford, henderson, lincoln, montgomery, orange,
   perquimans, warren, wilson, chester SC. Beaufort SC = Tyler, Wilson =
   TitleSearcher (paid).
5. **104 counties** have no recorder located by pattern. A miss is recorded as
   "not found", never "does not exist".
6. **`americanlandrecords.com`** (Anderson SC recorder) unmapped.
7. SC court URL patterns absent from the registry (NC's 100 are exact).

---

## Reference

| doc | what |
|---|---|
| `ROD_PORTAL_ACCESS.md` | both recorder platforms, full request recipes |
| `SOURCE_REGISTER.md` | every source with URL, gate, cost, cadence |
| `COUNTY_SYSTEMS_REGISTRY.md` | 146 counties × 4 systems, accessibility recorded not filtered |
| `OPERATIONS.md` | how to run the engine |
| `gap_ledger.md` | what cannot be done and why |
| `path_to_100.md` | costed blueprint; 3 hard walls |

## Scripts worth knowing

| script | what |
|---|---|
| `board_selfcheck.py` | 9 invariants, exit 1 on breach, plus a movement report |
| `recompute_valuation.py` | 40-second offline valuation recompute |
| `build_county_registry.py` | 146-county system sweep |
| `discover_linked_systems.py` | crawls county sites for systems we do not use |
