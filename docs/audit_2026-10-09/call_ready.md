# Audit 2026-10-09: call_ready (wave 2 F)

The gate itself, the lanes, tiers, counts, the attorney's list and the Fullmer mapping are in
[docs/call_ready.md](../call_ready.md). This is the audit report in the brief's format.

## 1. What was measured and how

* `call_ready.call_ready(row, today)` over every row of two boards, with the nine verification ledgers
  on disk on 2026-10-08 attached to each row the way `verification.apply` does it on the VM
  (`scripts/call_list_daily.LedgerAttacher`: `Ledger.find` on the row's property keys, case-scoped
  signals by case id):
  * the live board (the 2026-10-07 publish, 350,013 rows): `uv run python scripts/call_list_daily.py`
    (one pass, about 70 s, 420 MB peak);
  * the pre_publish checkpoint saved 2026-10-08 21:03 UTC (383,378 rows):
    `uv run python scripts/call_list_daily.py --count-only --board <checkpoint dir>` (about 85 s,
    215 MB peak).
* The invariants were run over the live board with the gate stamped in-process (what the board looks
  like once the wiring lands): all five checks passed with 0 violations (`call-ready-present` 350,013
  rows, `call-ready-call-evidence` 660 worked rows, `call-ready-no-dead-owner-call` 10,386 lane A rows,
  `call-ready-public-safe` and `call-ready-recompute` 350,013 rows each; 65 s). On today's published
  board, without the wiring, `call-ready-present` fails on every row, as it should.
* The hand-made pilot sheet (173 rows, 169 distinct parcels; 13 excluded) was compared with the new list
  parcel by parcel.

## 2. Defects found

| Class | Scale | Cause | Fix | Test | Invariant |
|---|---|---|---|---|---|
| Estate leads with no property | live: 1,696 lane B rows (1,439 with nothing else missing), 2,952 lane C rows; checkpoint: 6,007 lane B | newspaper probate notices (SC: Pickens, Cherokee and Laurens papers; NC notices) carry a decedent and a representative but no parcel and no address | the gate keeps them in research (`no_property_on_row`); without this and the next condition, 916 live lane B rows read as mail-ready, with them 3 | `test_lane_b_without_a_property_is_research` | `call-ready-call-evidence` (estate_lead_without_property) |
| Estate parcel that is someone else's | live: 33 lane B, 305 lane C rows (`decedent_not_tied_to_parcel`) | a parcel resolved from the representative's mailing address (`raw.parcel_from_address` on SC public-notice probate rows): the county roll owner of that parcel is another person | the dead owner must be the county roll's owner of the parcel (first and last name); the notice row's own owner name proves nothing | `test_lane_b_needs_the_county_roll_to_name_the_dead_owner` | `call-ready-call-evidence` (decedent_not_tied) |
| Pilot sheet: phones that are not the owner's | 6 attorney phones (`attorney_in_notice`), 6 uncorroborated NC voter cross-reference phones and 5 others naming another person or an agent were on the pilot (17 parcels) | the pilot did not apply `owner_phone_block_reason` | lane A needs a phone a closer may dial; these leads move to mail | `test_a_phone_of_another_person_is_never_dialed` | `call-ready-call-evidence` (phone_blocked_or_absent) |
| Pilot sheet: placeholder mailing addresses | 5 pilot rows ("UNKNOWN ... 99999"), 27 pilot rows whose mailing is another property's record | no mailing sanity rule | `mailing_sane` + `block_binding` on owner_mailing are lane A conditions | `test_mailing_sanity`, `test_bad_mailing_keeps_a_tied_phone_out_of_tier_a` | `call-ready-recompute` |
| Pilot sheet: one wrong exclusion | 1 row | a voter-file name written "LAST,FIRST" without a space was read as another person | the gate uses `block_binding.name_tokens` | covered by the lane A tests | - |
| No DNC scrub in the run | `raw.dnc_scrub` on 0 of 350,013 live rows; no `data/dnc_registry.csv` | `enrich_dnc_scrub` is called only by `hourly_refresh.py`, never by `main.run`; the registry file was never loaded | published as `dnc` = not_scrubbed and listed (`dnc_not_scrubbed`); a registered number never reaches tier A or B | `test_dnc_registered_phone_goes_to_mail` | `call-ready-call-evidence` (dnc_registered) |
| The gate is not on the board | 0 rows | new | `raw.call_ready` in RAW_KEEP, `_SLIM_RAW`, `_LEAN_RAW`, dashboard filter and export; main.py wiring lines in docs/call_ready.md | `tests/test_call_ready.py` | `call-ready-present` (fails until wired, by design) |

## 3. Open items

* Wiring (owner of main.py: the lead): two `stamp_board` calls, lines in docs/call_ready.md.
* Lane A growth needs county tax checks: 3,816 live lane A rows (5,297 on the checkpoint) have a
  dialable phone and wait only on the county site; 3,547 of the live ones are in counties with no tax
  checker (Lincoln 1,566, Rutherford 1,231, McDowell 633, Transylvania 93, Cleveland 16, Burke 8). No
  source built yet (source / verification area).
* Lane C (the attorney's list) is complete for 0 leads: the board never holds the latest deed's own
  legal description (`quiet_title_intake.py` reads it live, per parcel), deed chains are mostly a single
  GIS last sale, NC estate files are behind a CAPTCHA (a person's lane), and an obituary search that
  finds nothing leaves no dated record. Wall / no source for the estate files; not enough time for
  storing a negative obituary check.
* Estate status: no closing date on any source; "open" is a notice seen within a year (owner decision
  if a different window is wanted).
* DNC: an owner step (FTC registration, `data/dnc_registry.csv`), then `enrich_dnc_scrub` in the run.
* SC phones: 1 SC lead reaches a call tier on the live board (SC phone coverage is the known wall).

## 4. Seen outside this area

* `enrich_dnc_scrub` is not called by `main.run` (only `hourly_refresh.py`).
* `parcel_from_address` on SC public-notice probate rows resolves the representative's mailing address,
  not the decedent's property (resolver / source area).
* `tests/test_audit_suite.py::test_the_real_checks_dir_loads` failed at the time of writing on
  `scripts/audit_checks/additions.py` (another agent's file, in progress).
* Lincoln, Rutherford, McDowell, Transylvania, Cleveland and Burke have no tax_lien verifier
  (Transylvania is on ITSPublic: one `PORTALS` entry in `tax_lien_itspublic.py`).
