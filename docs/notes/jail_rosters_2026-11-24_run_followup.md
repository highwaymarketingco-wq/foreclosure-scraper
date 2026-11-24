# jail_rosters --apply run, 2026-11-24 — results and a narrow follow-up

## What ran

`backfill_jail_rosters.py --apply` across all 61 ROSTERS counties (43 NC + 18 SC),
~03:41-05:10 EST. Real results (commit 57ee238):
- 117 new leads flagged, 282 refused as middle-name conflicts (correct safety behavior)
- 961 previously-flagged leads re-checked: 5 cleared, 159 marked left-the-roster
  (87 kept as a possible prison-transfer after a 60+ day stay)
- 1,076 board rows patched across 47 part files; 3 matches correctly refused for
  sharing only a source_url with no stronger identity
- 789 requests sent, 0 hosts pushed back

## Gap-matrix effect: partial, and the split is informative

Re-ran gap_matrix.py after. Two different layers behaved differently for the same
counties (checked Scotland/Dorchester/Pasquotank/Anson as a sample, all confirmed
processed in the per-county output table):

- `jail_booking` (the **verify** layer, `ran=True` now): correctly picked up the
  real hits this run produced — now reads "run the jail_booking sweep over the N
  unverified hit rows" (32/31/2/1 for the four sampled counties). This is real,
  correct progress — those rows will get picked up by verification_sweep.py's
  jail_booking signal same as any other.
- `jail_booking_new` (a separate **check** layer): still reads "nothing landed
  here" for the same four counties, unchanged from before the run.

## Why `jail_booking_new` didn't move — not chased down, flagging precisely

`enrichment_jail_bookings.match_rosters()`'s `_stamp_screen()` (added 2026-10-16,
gap-sweep wave 3) does write a per-county sentinel (`raw["jail_booking_screen"]`)
the first time it sees a healthy-roster county with no hit for a given listing,
specifically so a healthy-but-all-negative screen still counts as checked.
`gap_matrix.py` line ~1909 does read `raw.get("jail_booking_screen")`. Both ends
exist and look correctly wired on inspection — but `jail_booking_new`'s own Spec
(separate from `jail_booking`'s) evidently checks something `_stamp_screen`'s
write doesn't satisfy for these counties. Did NOT trace `jail_booking_new`'s exact
Spec/producers tuple in gap_matrix.py this session — that's the concrete next
step, not re-deriving everything above.

Two live hypotheses, unconfirmed:
1. `jail_booking_new`'s Spec expects a *recent* stamp (e.g. checked_at within some
   window) and gap_matrix.py ran before/shortly-after the backfill in a way that
   missed it — unlikely given the verify-layer DID pick up fresh hits from the
   same run, but worth ruling out with a second gap_matrix.py pass.
2. `jail_booking_new` tracks a genuinely different signal shape (e.g. "booked in
   the last N days" vs "ever booked") that `_stamp_screen`'s generic no-match
   sentinel was never meant to satisfy, and the gap_matrix next_action text for
   `jail_booking_new` is simply imprecise/copy-pasted from `jail_booking`'s own
   wording rather than describing a real actionable gap.

## Also noted, not a jail_rosters bug: some counties never got a healthy fetch

Transylvania/Guilford/Sumter/Greenville still read "nothing landed here" on
*both* layers — these likely had a vendor fetch failure or empty response this
run (not a "pushed back" host, just not healthy), so `_stamp_screen` correctly
declined to claim them screened. A retry scoped to just the counties that didn't
get a healthy fetch (not all 61 again) would be the efficient way to mop these up
— check `idx.healthy` per county in a future run rather than re-running everything.

## Operational lesson already captured in the loop prompt, not repeating here

`backfill_jail_rosters.py` holds `board_lock` for its entire run (not released
between counties), which stalled `backfill_incarceration.py`'s NC/SC for about an
hour when run concurrently — see this session's loop history. Prefer per-county/
per-batch lock scoping for any future job this long, if the codebase supports it.
