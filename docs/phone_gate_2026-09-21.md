# SC phone identity gate (built and measured 2026-09-21)

This is the gate that `docs/sc_phone_research_2026-09-21.md` section 9 specified. It is built, tested offline, and measured on the live board with streaming dry runs. **Nothing has been applied to the board.** The exact command is in section 5.

## 1. The result in four lines

1. The SC phone lane holds 1,671 phones, all from `enrichment_sc_voter_xref` (a first-name plus last-name match against the NC voter file). After the gate **4 are corroborated, 1,401 are unverified and 266 are contradicted.** 1,667 get `do_not_dial`.
2. Honest SC owner-phone coverage goes from **1,873 rows (2.4%) to 4 rows (0.005%)**. The other 1,869 were 1,667 unverified or contradicted voter matches and 202 listing-agent, attorney and office numbers that were never the owner's.
3. NC barely moves: **60.5% to 60.3%** (255 agent phones out). Excluding `liensnc`, NC goes **20.2% to 19.7%**, and to **11.4%** if the 3,810 name-only NC voter fallbacks are also not trusted (they are not gated today, see section 6).
4. The first 3,000 rows of today's board give 217 xref phones and 159 contradicted (73%), the same counts the research reported for its 2,000-row window. That window is not representative: across the whole board it is 266 of 1,671 (16%) contradicted and 1,401 (84%) unverified, because the first rows are the `spartanburg_vacant` block, whose owner names were promoted after the phones were stamped.

## 2. The rules

`src/foreclosure_scraper/enrichment_sc_phone.py`

`xref_identity_verdict(li) -> "corroborated" | "unverified" | "contradicted"`, for a phone whose source is `ncsbe_voter_xref` (or a `raw.sc_voter_xref` block).

| Verdict | Rule |
|---|---|
| contradicted | The owner is an entity or estate, or the matched voter's first and last name are not both tokens of the current `owner_name`. Entity detection is `name_normalize.is_entity` (LLC, INC, CORP, CO, LP, LLP, TRUST, ASSOCIATION, CHURCH, MINISTRIES, HOLDINGS, PROPERTIES, PARTNERS and the rest of its marker set) plus a small supplement it lacks: ESTATE, HEIRS, DECEASED, POST, LODGE, CLUB, SOCIETY, HOA, SCHOOL, COUNTY, "CITY/TOWN/STATE OF". POST and LODGE count only after the first token because both are surnames; "LIFE ESTATE" is treated as a living person. |
| corroborated (i) | The owner mails to an NC address whose house number plus first street token equals the voter's residential street key (`_street_key` from `enrichment_voter_phone`), and the voter record carries the stored phone. A provable middle-initial conflict (John B at the house where John A votes) vetoes it. |
| corroborated (ii) | The lead is in NC, the owner name agrees with the voter including the middle initial (`party_middle_verdict == "agrees"`), the voter's county is the lead's county, and the voter record carries the stored phone. |
| unverified | Everything else, including a name match with an SC mailing address, no mailing address at all, or no voter record for the stored phone. |

Two judgment calls beyond the spec, both in the safe direction:

* Path (ii) requires the **lead to be in NC**. The voter file is NC-only, so an SC lead can never share a county with a voter, but Union, Cherokee and Lee exist in both states. A bare county-name comparison would corroborate a stranger across the line. 146 of the 1,671 xref phones sit in SC Union and Cherokee. In practice path (ii) cannot fire on SC rows.
* The middle-initial veto on path (i) (1 row today).

`flag_unverified_xref_phones(listings, apply=False) -> stats` is report-only by default. With `apply=True` it sets `owner_phone["identity_check"]` and, for anything not corroborated, `do_not_dial = True` plus `do_not_dial_reason = "sc_xref_identity_<verdict>"`. The phone value is kept. A corroborated phone whose flag the gate itself set is cleared again; a flag anyone else set is never cleared. It is idempotent (second run changes 0).

`flag_lane_phones(listings, apply=False)` adds the lane rules that need no voter data:

| Lane | Sources | Treatment |
|---|---|---|
| owner's own number | `liensnc_filing` | kept, never touched |
| NC voter xref | `ncsbe_voter_xref`, `sc_voter_xref` | the gate above |
| people search (walled) | `free_people_search`, `enrichment_free_phones`, anything with people-search in the name, every `raw.free_phones` entry | `do_not_dial` |
| agent | `homeharvest_agent`, `homeharvest_office`, `notice_contact_attorney`, `ocr_legal_notice`, `raw.*` text scans | `role = "agent"`, never counted as owner contact |
| everything else | `ncsbe_voter`, county-published (Buncombe, Lincoln) | unchanged |

`owner_phone_block_reason(op)` and `is_owner_phone_usable(op)` are the one predicate every consumer uses. **They fail closed**: an xref phone with no `identity_check` is blocked, so a legacy phone that was never stamped is not exported before `--apply` runs.

Memory: the gate does not call `enrichment_voter_phone._build_index()`, which holds every active NC voter in several dicts and has no middle names. It scans the 13 cached `data/ncvoter/*.txt` files once (1,279,962 rows) and keeps only the voters whose name is being checked.

## 3. Measured on the live board

Board `docs/listings.json.gz` (88,098,890 bytes, mtime Sep 21 10:10), 170,066 rows, read through `board_stream.iter_board_rows`. One full dry run takes 13 seconds. The scheduled job may rewrite the board, so the counts move a little between runs.

`before` = the row has `raw.owner_phone.phone` (what the dashboard counts as "has phone"). `after gate` = a phone that may be offered as the owner's number. `strict` = after gate, minus NC name-only voter fallbacks.

| Segment | Rows | Before | After gate | After, strict |
|---|--:|--:|--:|--:|
| **SC** | 77,036 | 1,873 (2.4%) | **4 (0.005%)** | 4 |
| SC HOT | 668 | 119 (17.8%) | 0 | 0 |
| SC WARM | 22,955 | 1,307 (5.7%) | 4 (0.02%) | 4 |
| **NC** | 93,030 | 56,309 (60.5%) | **56,054 (60.3%)** | 52,244 (56.2%) |
| **NC without liensnc** | 46,041 | 9,320 (20.2%) | **9,065 (19.7%)** | 5,256 (11.4%) |
| NC liensnc only | 46,989 | 46,989 (100%) | 46,989 (100%) | 46,988 |
| NC HOT | 1,413 | 434 (30.7%) | 405 (28.7%) | 272 (19.2%) |
| NC WARM | 50,269 | 42,353 (84.3%) | 42,154 (83.9%) | 39,911 (79.4%) |

"liensnc" is a row whose `source` contains `liensnc` (`liensnc` and `counties_generic.liensnc`). Other phone carriers (the lien report's owner contact, skip trace, outreach, ingested contact) add 1 SC row and 4 NC rows and are not gated here.

### Phones per source

| State | Phone source | Phones | Treatment |
|---|---|--:|---|
| NC | `liensnc_filing` | 47,131 | kept, the owner's own number |
| NC | `ncsbe_voter`, name + address | 3,147 | kept |
| NC | `ncsbe_voter`, name only (county-unique, fuzzy county-unique) | 3,810 | kept, **not gated** (section 6) |
| NC | `buncombe_accela` | 1,860 | kept, county-published parcel join |
| NC | `lincoln_taxpayer` | 106 | kept, county-published parcel join |
| NC | `ocr_legal_notice`, `homeharvest_agent`, `notice_contact_attorney`, `homeharvest_office` | 151, 92, 8, 4 | role agent (255) |
| SC | `ncsbe_voter_xref` | 1,671 | the gate |
| SC | `homeharvest_agent`, `ocr_legal_notice`, `homeharvest_office`, `notice_contact_attorney` | 111, 87, 3, 1 | role agent (202) |
| any | people search (`free_people_search`) | 0 | none on the board, the rule covers future rows |

### The 1,671 xref phones

| Verdict | Phones | Reason |
|---|--:|---|
| corroborated | 4 | owner mails to the voter's NC street |
| unverified | 1,401 | 1,400 name matches with no corroboration, 1 middle-initial conflict |
| contradicted | 266 | 180 matched voter name not in the current owner name, 86 entity or estate owner |

Where those owners mail: no mailing address on file 855, SC 710, NC 47, other states 59. Of the 47 NC mailers, 4 street-match the voter, 37 do not, 6 are contradicted.

By county (corroborated / unverified / contradicted): Spartanburg 3 / 530 / 210, Pickens 1 / 329 / 13, Oconee 0 / 124 / 23, Anderson 0 / 111 / 3, Laurens 0 / 78 / 16, Cherokee 0 / 73 / 0, Union 0 / 73 / 0, Charleston 0 / 38 / 0, Georgetown 0 / 33 / 0, Sumter 0 / 11 / 1, Beaufort 0 / 1 / 0.

The earlier guarded run (`scripts/run_sc_voter_xref_corroborated.py`, commit 728fcec) tagged 32 phones `corroboration = nc_mailing_address` on the rule "owner mails to any NC address". Under the street rule 3 of those 32 are corroborated, 26 are unverified and 3 are contradicted.

The 855 rows with no mailing address are the ones most likely to improve: when the assessor mailing resolver fills a mailing address, a re-run of the gate can promote a phone from unverified to corroborated (the gate clears only flags it set itself). No SC mailing address can ever corroborate, because an owner who mails to SC is not shown to live in NC.

## 4. What changed

New:

* `src/foreclosure_scraper/enrichment_sc_phone.py` (the gate, the lane rules, the shared predicate)
* `scripts/flag_unverified_sc_phones.py` (dry run by default; `--apply` uses `board_lock`, `load_board`, `write_artifact` as `scripts/resolve_anderson_from_roll.py` does)
* `tests/test_sc_phone_gate.py` (55 tests, offline)
* this file and `docs/phone_gate_handoff_2026-09-21.md`

Changed:

* `src/foreclosure_scraper/enrichment_sc_voter_xref.py`: every match is written fail-closed (`do_not_dial True`, `identity_check unverified`) and the gate then clears it only on evidence. Entity and estate owners are never matched. Phones stored by earlier runs are re-checked on every run, because owner names are promoted from the assessor after this step runs. Returns the old counters plus `skipped_entity`, `regated`, `corroborated`, `unverified`, `contradicted`, `do_not_dial`.
* `src/foreclosure_scraper/enrichment_dnc.py`: a phone that must not be dialed is recorded `do_not_dial` (or `not_owner_contact` for an agent) with a `block_reason` and never `clear`. A scrub result from before a phone was gated is downgraded; a phone whose block is lifted is re-scrubbed; a new phone on an already-scrubbed listing is now scrubbed too (it was skipped before). It also stamps the lane rules, so `hourly_refresh` and `enrich_board` tag agent and people-search phones with no extra step.
* `src/foreclosure_scraper/campaign_export.py`: the SMS export and the `has_phone` filter skip blocked owner phones.
* `src/foreclosure_scraper/api_server.py`: the `has_phone` filter skips them, and `/api/leads` marks a blocked `owner_phone` with `dialable: false`, `do_not_dial` and `block_reason` (on a copy).
* `src/foreclosure_scraper/workflow_engine.py`: the `has_phone` trigger ignores them.
* `src/foreclosure_scraper/analytics_dashboard.py`: the phone KPI counts usable owner phones only.
* `scripts/build_skiptrace_worksheet.py`: `phone_we_have_free` is blank unless the phone is usable.

Files I could not change (owned by others) are listed with the exact edits in `docs/phone_gate_handoff_2026-09-21.md`. The important one: `web_artifact._SLIM_RAW["owner_phone"]` and `dashboard.js _LEAN_RAW.owner_phone` do not carry the new flags, so until they change the dashboard cannot see `do_not_dial`.

## 5. Apply it

Run as the only board process (about 3 GB, `load_board`). `board_lock` refuses if another writer holds the lock.

```
cd /Users/cashhigh/foreclosure-scraper && uv run python scripts/flag_unverified_sc_phones.py --apply
```

Expected output, from the dry run: `xref_phones 1671`, `corroborated 4`, `unverified 1401`, `contradicted 266`, `do_not_dial 1667`, and lane rules `agent_tagged 457` (255 NC + 202 SC), `walled_flagged 0`. It asserts the row count is unchanged before it writes.

Check it worked with one more dry run (13 seconds, streams only):

```
uv run python scripts/flag_unverified_sc_phones.py
```

The "ALREADY STAMPED ON THE BOARD" line should read `xref phones 1,671: identity_check 1,671, do_not_dial 1,667` and `agent phones 457: role tagged 457`. The coverage table does not change, because it recomputes the verdict from the data. A second `--apply` reports `changed 0`.

Nothing is deleted: every phone value stays, and the flags are additive keys on `owner_phone` (`identity_check`, `do_not_dial`, `do_not_dial_reason`, `role`). To undo, drop those four keys.

## 6. Decisions and limits

* **NC name-only voter fallbacks are not gated.** 3,810 NC phones (`ncsbe_voter` with match `name+county-unique` or `fuzzy:soundex+county-unique`) rest on a name being unique among voters with a phone in one county, with no address check. That is the same weakness as the SC lane, milder because the voter lives in the property's county. The gate does not touch them because the request was about the xref lane. They are 5,256 of NC's 9,065 non-liensnc phones, so the honest NC-without-liensnc figure is between 11.4% and 19.7% depending on how far you trust them. Gating them needs the matched voter's name, which `match` does not record for that lane; it would be re-derived from `owner_name`.
* **The voter files are dated Jun 28.** A voter who moved or re-registered since then is invisible, so corroboration can be missed but not invented.
* **The verdict is a name-and-address test, not proof.** "Corroborated" means an NC mailing address that is the voter's residence, a strong signal, not certainty. It still needs the national DNC scrub before anyone dials.
* **Counts move.** The scheduled job rewrites the board. The figures above are the 10:10 board.
* **Streaming budget.** Three full streaming passes were used (one discovery pass to learn the source vocabulary, two measurement passes) plus three truncated smoke runs of 3,000 to 60,000 rows.
* `enrichment_line_type` still classifies a blocked phone's line type and TCPA class, which could show a flagged xref phone as a "landline call lane" in the dashboard. Handoff item.
