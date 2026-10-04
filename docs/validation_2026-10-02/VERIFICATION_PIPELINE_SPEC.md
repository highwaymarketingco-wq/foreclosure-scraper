# From sampled validation to permanent, per-lead verification

## What changed since FINDINGS.md

FINDINGS.md (2026-10-02) and the follow-up round (2026-10-03, probate/heir +
comps) answered "how accurate is signal type X, roughly" via sampling —
good for prioritizing fixes, not good enough for a dialer deciding whether
to call THIS specific lead today. The owner's explicit ask now: **every
listing carries the same depth of live verification Boone St (50 Boone St,
the Wofford demo property) got manually** — not a statistic about leads
like it, a real, current, evidence-backed verdict on that row itself,
produced by the actual production pipeline, continuously, not a one-shot
audit run by a separate session.

This is a real scope jump: ~50-60-row samples per type → every row of every
type, board-wide (~219K rows total), on an ongoing basis as the board
changes. Treat this as its own project with its own architecture, not a
bigger version of the existing validator scripts run as-is.

## Architecture

### 1. New field: `raw.verification`

Per-row, a list of verification records, one per distinct claim the row
carries (a row can have more than one signal — e.g. `tax_lien` +
`builder_distress` — each gets its own entry):

```python
raw["verification"] = [
    {
        "signal": "tax_lien",
        "checked_at": "2026-10-04T12:00:00Z",
        "verdict": "confirmed" | "refuted" | "stale" | "unconfirmed" | "wall",
        "evidence": {...},       # whatever the verifier actually found, structured
        "source": "tax.buncombenc.gov",
        "verifier_version": "v1",
    },
    ...
]
```

`unconfirmed` = checked, source didn't have enough to decide either way.
`wall` = genuinely can't be checked by code (NC eCourts, NC SOS) — label it
honestly rather than silently treating it as either confirmed or refuted.

### 2. One verifier module per signal type — evolve, don't rewrite

Every validator built in `docs/validation_2026-10-02/scripts/` and
`docs/validation_2026-10-03/scripts/` already proves the live endpoint, the
parsing, and the matching logic for its type. The work here is turning each
`sample_N_and_report()` script into a `verify_one(row) -> VerificationResult`
function callable on a single row, then wiring that into the pipeline. Reuse
map, in rough priority order (highest lead volume / clearest existing proof
first):

| Signal | Source script to evolve | Proven endpoint | Status |
|---|---|---|---|
| `tax_lien` | `validate_tax_lien_buncombe.py` | `tax.buncombenc.gov/Parcel/Details/{pin}` | Buncombe-proven; needs one adapter per NC/SC tax-vendor family (nc_ptscloud, qpaybill, etc.) to go statewide |
| `bankruptcy_stay` | `validate_bankruptcy_namematch.py` | CourtListener `format=json` search | Proven, `name_normalize.party_middle_verdict()` ready to wire in |
| `code_enforcement`/`vacancy` | `validate_code_enforcement.py` | Henderson + Gastonia ArcGIS/CityView (already fixed in code per HANDOFF items 48/55) | Per-county category taxonomy must be live-verified before wiring each new county, same as Gastonia was |
| `builder_distress` | `validate_builder_distress_v2.py` | Buncombe ROD (Cott v4, `rod/aumentum.py`) | Proven; already fixed at the scoring level (HANDOFF item 47) — this would add per-row evidence on top of the now-correct scoring |
| `jail_booking` | `validate_live.py` (+ `collect_candidates.py`) | County jail rosters, 10 counties/vendors already mapped | Proven; `party_middle_verdict()` NOT yet wired into `jail_bookings.py` — do that first |
| `elderly_disabled` | `validate_elderly_disabled_buncombe.py` | tax + `enrichment_nc_voter_lookup.py` | Proven, voter-lookup tool already committed, not yet wired into scoring |
| `divorce` (SC) | divorce validator + `enrichment_sc_divorce.py` | SC Public Index | Root-cause fix (HANDOFF item 50) landed; re-verify against the fixed matching before trusting verdicts here |
| `lis_pendens`/`foreclosure_sale` | `validate_lis_pendens_buncombe.py` | Buncombe ROD (legacy ASP.NET WebForms, full POST protocol documented in the script) | Proven for Buncombe; parcel-ID format gap (`enrichment_lis_pendens_resolver.py`) blocks most non-Buncombe rows from even being checkable |
| `probate`/`heir_estate` | `validate_probate_heir_buncombe.py` | ROD DEATHS index (`ddlIndexType=DTH`) + transfer history + voter lookup | Proven 2026-10-03; heir-name coverage gap (`task_c638bfb4`) limits what fraction of rows can get the voter-liveness check |
| `comps` | `validate_comps_buncombe.py` + `crosscheck_comps_arcgis_live_snapshot.py` | Spatialest record card + ArcGIS live attributes | Proven 2026-10-03, already 93.7% accurate — lowest-priority to verify continuously, but wire in for drift detection |

NC eCourts-dependent checks (the underlying case for a lis pendens/divorce,
heir discovery beyond already-named parties) stay a real wall. No code
closes that — see "The honest gap" below.

### 3. This cannot be a blocking full-pipeline step — incremental by design

~219K rows × live HTTP per signal type is not something that runs inside a
normal pipeline cycle. Required:

- **Prioritize by tier.** Verify HOT/WARM leads first — those are the ones
  about to be called. COLD/dead-end leads can wait or never get checked.
- **Cache with a TTL, don't re-check every run.** Most of these facts (a
  death, a bankruptcy filing, a recorded lien) don't change day to day.
  Stamp `checked_at` and re-verify on a cadence (30-90 days is reasonable to
  start; tune per signal — a `code_enforcement` case status probably needs
  checking more often than a death record) rather than on every pipeline
  run. `verification_ttl` per signal type, same pattern `signal_freshness.py`
  already uses elsewhere in this codebase.
- **Resumable background sweep, not a pipeline stage.** A dedicated script
  (same safe-streaming pattern as the rest of this project:
  `web_artifact._iter_board_records()` to read, `patch_existing_rows()` to
  write, never `load_board()`/`write_artifact()` on this machine) that works
  through the verification backlog over hours/days, checkpointed so it can
  stop and resume. Politeness is already handled — `http_client.py`'s
  per-host throttle protects every live source this touches.
- **Scoring should USE the verdict, not just display it.** A `confirmed`
  verdict on a row's primary signal is real evidence a caller can trust —
  surface it visibly (a badge, same as the existing tier system) and
  consider it in HOT/WARM eligibility. A `refuted` verdict should actively
  demote or suppress the row, not sit there unused the way most of the
  false-positive findings in FINDINGS.md currently do even after the
  underlying matching bug gets fixed. `wall`/`unconfirmed` should read
  honestly as "not independently verifiable," never as if it passed.

### 4. The honest gap

NC eCourts (CAPTCHA-walled) and NC Secretary of State (separate bot-check)
are real walls no verifier here closes. They're exactly the step that found
Boone St's 9th heir and confirmed he was still alive — the single most
valuable finding of that whole investigation — and nothing in this spec
replicates it at scale. Two honest options, not mutually exclusive:

1. **Label it, don't fake it.** Rows whose verification depends on an
   eCourts fact get `verdict: "wall"` with a note on what specifically is
   unverifiable — never silently treated as confirmed.
2. **A human-assisted on-demand lane.** For a specific lead someone's about
   to act on (the Boone St pattern), a tool that queues the eCourts check
   and pauses for a human to clear the CAPTCHA once, the same way this
   session did it live — not a bulk/background thing, a per-lead button for
   when it actually matters (handing a case to Wofford, about to make an
   offer).

   **BUILT (2026-10-04):** `src/foreclosure_scraper/verification_human_lane.py`
   (core logic) + `scripts/verify_lead_human_assisted.py` (operator CLI), scoped
   to the two highest-priority types above (`probate`/`heir_estate`,
   `lis_pendens`/`divorce`), covering both NC eCourts Smart Search and NC SOS.
   Never solves the CAPTCHA — queues it, opens the real search for a human, and
   stops until a saved page is handed back. Not yet wired to a board write; see
   that module's docstring and `docs/HANDOFF.md`.

## What this is NOT

Not a request to re-run the existing validators with a bigger N. Not
something to build as more scratchpad scripts in a research session. This
is permanent pipeline code — `raw.verification`, a verifier per signal type
wired into `main.py` or a dedicated scheduled sweep, scoring changes to use
the verdicts, and the incremental/TTL/politeness design above. It belongs
with whoever owns `main.py` and the enrichment pipeline day to day, with the
proven scripts in `docs/validation_2026-10-02/` and
`docs/validation_2026-10-03/` as the starting point for each verifier, not
something to rebuild from scratch.
