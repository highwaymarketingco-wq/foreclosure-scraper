# Phone gate: edits needed in files owned by other agents (2026-09-21)

The gate itself is done and described in `docs/phone_gate_2026-09-21.md`. It stamps four additive keys on `raw.owner_phone`: `identity_check`, `do_not_dial`, `do_not_dial_reason`, `role`. `RAW_KEEP["owner_phone"] = "*"` already carries them into the board. Nothing downstream can see them until the slim projection and the dashboard are changed. I did not touch any file below. Symbols are named instead of line numbers because these files are being edited right now.

## 1. `src/foreclosure_scraper/web_artifact.py` (required)

In `_SLIM_RAW`, the `owner_phone` entry is `("phone", "source", "needs_dnc_scrub")`. The slim board is what the dashboard list, the "has phone" filter and the CSV export read, so the flags are dropped there. Change it to:

```python
"owner_phone": ("phone", "source", "needs_dnc_scrub", "do_not_dial", "do_not_dial_reason", "identity_check", "role"),
```

`_SLIM_RAW` and `_LEAN_RAW` in `docs/dashboard.js` must stay identical (`tests/test_board_slim.py` parses the JS and asserts equality), so change both in the same commit. `_SHARD_SKIP_RAW` is derived from `_SLIM_RAW`, so the detail shards keep the whole block and need nothing.

Optional, same reason: `_SLIM_RAW["free_phones"]` and `_SLIM_RAW["sc_voter_xref"]` could add `"do_not_dial"`. Both blocks are empty on the board today (0 rows carry either).

## 2. `docs/dashboard.js` (required)

Add one helper that mirrors `enrichment_sc_phone.owner_phone_block_reason`, then use it in the three places that read `raw.owner_phone`.

```js
// Mirrors enrichment_sc_phone.owner_phone_block_reason: why a phone must not be offered as the OWNER's number.
const _XREF_SRC = new Set(["ncsbe_voter_xref", "sc_voter_xref"]);
const _AGENT_SRC = new Set(["homeharvest_agent", "homeharvest_office", "notice_contact_attorney", "ocr_legal_notice"]);
const _AGENT_MATCH = new Set(["attorney", "attorney_in_notice", "trustee", "listing_agent"]);
function ownerPhoneBlock(op) {
  if (!op || !op.phone) return "no_phone";
  if (op.do_not_dial) return op.do_not_dial_reason || "do_not_dial";
  const src = String(op.source || "");
  if (src !== "liensnc_filing") {                       // the owner's own number, never demoted
    if (src === "free_phones" || /people_?search|truepeople|fastpeople/i.test(src)) return "people_search_walled";
    if (op.role === "agent" || _AGENT_SRC.has(src) || src.startsWith("raw.")
        || _AGENT_MATCH.has(String(op.match || "").toLowerCase())) return "agent_contact";
  }
  if (_XREF_SRC.has(src) && op.identity_check !== "corroborated")
    return "sc_xref_identity_" + (op.identity_check || "unchecked");
  return null;
}
```

* The contact filter: `if (contact === "phone" && !r.owner_phone) return false;` becomes `if (contact === "phone" && ownerPhoneBlock(r.owner_phone)) return false;`, and in the `contactable` line replace `r.owner_phone` with `!ownerPhoneBlock(r.owner_phone)`.
* The detail card (`const _op = (l.raw && l.raw.owner_phone) || {};`): when `ownerPhoneBlock(_op)` is set, render the number struck through or under a "DO NOT DIAL: <reason>" badge, and never in the "call" style. An agent phone should read "Listing agent / attorney line, not the owner".
* The CSV export (the `cols` list with `"owner_phone", "phone_source", "phone_needs_dnc"` and the row `owner_phone: op.phone || ""`): write `owner_phone` blank when `ownerPhoneBlock(op)` is set, and add a `phone_block_reason` column so the flagged number is not silently lost. Without this the dashboard CSV, the one export I cannot reach, still emits the 1,667 flagged phones.

`tests/js/` has only `io_guard.test.mjs` and `lead_state.test.mjs`; a test for `ownerPhoneBlock` against the same cases as `tests/test_sc_phone_gate.py::test_block_reason_covers_every_lane_and_fails_closed_on_an_unstamped_xref_phone` would keep the two in step.

## 3. `src/foreclosure_scraper/distress_score.py` (no change)

Its `contactable` flag is built from `owner_mailing` only (the `mailable` variable), not from any phone. Nothing there counts a phone, so nothing there needs the gate.

## 4. Other files that touch phones

| File | Owner | What to change |
|---|---|---|
| `scripts/enrich_board.py` | another agent | The people-search step is already off unless `ENABLE_FREE_PHONES=1`, so the wall holds. Two ordering notes: `sc_voter_xref` (step 3ag-bis) appears before the owner-mailing resolver (the research doc's suspected cause of stale phones, not confirmed), so a phone written there has no mailing address to corroborate against and is stored unverified; the second call (step 3bq) re-gates it on every run, so no change is required, but moving 3ag-bis after the mailing resolver would corroborate on the first run. `dnc_scrub` (3bi) runs before 3bq, so phones 3bq writes are scrubbed on the next run (`hourly_refresh` also runs it). |
| `scripts/run_sc_voter_xref_corroborated.py` | nobody | Superseded by the gate. It stamps `corroboration = "nc_mailing_address"` after `enrich_sc_phone_xref`, a weaker rule than the street match (of its 32 tagged phones, 3 are corroborated, 26 unverified, 3 contradicted). It is safe to leave, since the gate flags whatever it writes, but the tag will contradict `identity_check`. Retire it or make it skip the tag when `do_not_dial` is set. |
| `scripts/coverage_100_ledger.py` (the `if op.get("phone") or ...` phone count) and `scripts/county_coverage_matrix.py` (`phone = op.get("phone") or ...`) | another agent | Count a phone only when `usable_owner_phone(raw)` is truthy (`from foreclosure_scraper.enrichment_sc_phone import usable_owner_phone`). Their phone columns are the ones that report SC at 2.4% and NC at 60.5%; after the gate the honest figures are 0.005% and 60.3%. |
| `src/foreclosure_scraper/enrichment_line_type.py` | another agent | It sets `line_type` and `tcpa_class` on every `owner_phone`, and the pipeline comment says landlines become "the compliant call lane". Skip a block where `owner_phone_block_reason(op)` is set, or a flagged xref phone can be classed as a landline to call. |
| `scripts/merge_voter_footprints.py` | nobody | Calls `enrich_sc_phone_xref`, so it gets the gate with no edit. |
| `src/foreclosure_scraper/enrichment_free_phones.py` | another agent | Still writes `source = "free_people_search"` when enabled. The gate flags those rows do_not_dial, but the module writes the phone first. Leave the env gate in `enrich_board.py` as the real control. |

## 5. After the operator runs `--apply`

`docs/phone_gate_2026-09-21.md` section 5 has the command and the check. The slim board and the dashboard only show the new flags after items 1 and 2 above ship and the board is republished.
