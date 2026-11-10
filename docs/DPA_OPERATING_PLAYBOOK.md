# DPA-to-Pipeline Operating Playbook

How Distressed Property Advisors' (DPA) curriculum — the 11-Checkpoint Curative
Title Deal Triage Sheet, the SET+PRU Deal Review Framework, and the Call
Framework's fact-extraction sequence — maps onto what `foreclosure-scraper`
actually computes, publishes, and routes today. Built 2026-11-10 by reading
DPA's bootcamp/book/podcast material in full alongside `call_ready.py`,
`distress_score.py`, `valuation/grading.py`, `lawyer_lane.py`, the
`quiet_title/` package, and `docs/OWNER_MANUAL_LANES.md` — every claim below
carries a `file:line` citation back to the actual code or doc, not a summary
of what it's supposed to do.

**How to use this document.** Before calling a lead, read its `raw['call_ready']`
block (Part 3's table tells you exactly what's already answered) and its
`raw['fullmer']`/`raw['distress_stack']` tier. Walk the 11 checkpoints anyway —
most of them are still manual (Part 1 marks exactly which). After the call,
Part 4 tells you where the lead goes next: self-close, mail the PR, the
attorney's intake queue, a manual-lane card, or back on the shelf.

---

## Terminology note — read this once, it governs every section below

- **`call_ready`'s own A–E "lanes" and A–D "tiers" are NOT the DPA Triage
  Sheet.** They're a separate go/no-go gate answering "is there a checked
  issue we can call about today" (`call_ready.py:1-61`). Several of its
  building-block *facts* (tax status, death status, estate status) are
  exactly what the Triage checkpoints and Call Framework need — that's the
  real mapping — but the lane/tier verdict itself does not substitute for
  walking all 11 checkpoints or filling out SET+PRU.
- **Two different "owner/heir count" fields exist on a row, and they are not
  the same field any more:** `raw['fullmer']['owner_count']` (upstream, read
  only by `call_ready.rank()`, never published to the board —
  `call_ready.py:801-802`) is the OLD name-split proxy. As of 2026-11-10,
  `fullmer_rank.py`'s `_owner_count()` now *prefers* the real resolved count
  from `raw['heir_candidates']` when any publishable heir/PR candidate
  exists, and only falls back to the name-split proxy when none does
  (`fullmer_rank.py:300-353`). The *published* count — `raw['heir_candidates']`
  as counted by `estate_fact()` → `facts.heir_candidates` — was always the
  real one (`call_ready.py:459-472, 1063`). Point people at the published
  one; it is now also what internally drives the owner-count risk score.
- **The decedent's name and date of death are computed internally but never
  published** to the public `call_ready` block — `death_fact()`'s own
  docstring marks `_names` "internal; never published" (`call_ready.py:364`),
  and the `facts` dict assembled at `call_ready.py:1052-1065` carries no
  name/date key, only the record-*kind* list (`facts.death_on`). A human
  needs `raw['probate']['date_of_death']` etc. directly.
- **"Contactable" ≠ "receptive."** The pipeline's phone/mail tier
  (`_contact_tier`, `call_ready.py:814-837`) measures whether a phone/address
  is well-linked to the owner. It says nothing about how the owner will
  react on the call.
- **Equity is still ARV-anchored, not FMV-anchored**, even after the
  2026-11-10 `deal_status` fix. That fix only re-pointed the *deal-status
  verdict* (`deal_status`/`deal_message`/`haircut_needed`) onto the as-is/FMV
  anchor (`grading.py:6-17, 470-488`). The equity **percentage/band**
  consumed by `distress_score.py` is unchanged and is explicitly
  `arv − payoff − senior_liens` (`grading.py:336-338`, "GATED ELSEWHERE"
  comment) — the opposite basis from DPA's SET-E field. **Don't read
  `equity_band: "high"` as DPA-compliant FMV equity** — it isn't, yet.
- **A real, as-of-today example of why the `deal_status` fix mattered**:
  3646 Summer Rd, Henderson NC — county appraisal $230,200, but an ARV of
  $1,694,900 (7.4× the anchor) drove a published "GREAT, ROI 192.6%, max bid
  $1,271,200" before the fix (`grading.py:28-35`). After the fix, the same
  flag (`arv_above_anchor`) no longer withholds or distorts the verdict,
  because the verdict is no longer built from ARV at all — it's bid vs. the
  as-is 10/30/50% bands. **The ~470K rows already on the board have not been
  retroactively re-graded** — this is a code fix, not a board-wide backfill;
  a lead you pulled before 2026-11-10 may still show an old ARV-anchored
  grade until it's re-scored.

---

## Part 1 — The 11-Checkpoint Curative Title Deal Triage Sheet

### Checkpoint 1 — Ownership clarity
*CLEAN: single living owner, reachable. CAUTION: multiple owners, all
reachable, or entity with one clear signer. HARD STOP: low equity + >15
owners.*

**Already surfaces:**
- `owner_kind(row)` → `"individual" | "entity" | "trust" | "estate" |
  "government" | "unknown"` (`call_ready.py:287-294`).
- An owner-count figure, now preferring the real resolved heir count when one
  exists (`fullmer_rank.py:300-353`, see Terminology note).

**Still manual:** per-owner reachability on a multi-owner deed; the literal
">15 owners" HARD STOP count; whether an entity has "one clear signer."

---

### Checkpoint 2 — Probate and heirship risk
*CLEAN: alive, or death recent + probate already open under one PR. CAUTION:
deceased, no probate, heirs identifiable/cooperative. HARD STOP: hostile
occupant-owner, estate debts exceed real-estate value, extreme
probate-litigation complexity.*

**Already surfaces — the pipeline's best-automated checkpoint:**
- `death_fact(row)` → `{record: [...], weak: [...], tied, date_of_death,
  _names}` (`call_ready.py:362-436`). `record` kinds: `roll_wording`,
  `probate_record`, `sc_probate_notice`, `deceased_owner_roll`,
  `death_index`, `listing_type`; `weak` kinds: `obituary`,
  `life_event_death`, `heir_summary`.
- `estate_fact(row, today)` → `{open, pr, pr_address, heirs, care_of,
  seen_on}` (`call_ready.py:439-483`), `open` freshness-gated at 365 days
  (`ESTATE_NOTICE_MAX_DAYS`, `call_ready.py:78, 474-479`) — directly
  operationalizes "death recent + probate already open."
- Both publish at `facts.death_on` / `facts.estate` / `facts.heir_candidates`
  (`call_ready.py:1059-1063`).
- Example (Lane B, the module's own documented case,
  `call_ready.py:16-20`): `death_fact → {"record": ["probate_record"],
  "tied": true}`; `estate_fact → {"open": "open", "pr": true, "heirs": 2,
  "seen_on": "2025-06-01"}`.

**Still manual:** hostile occupant-owner; estate debts vs. real-estate value
(no estate balance sheet); probate-litigation complexity; the decedent's name
and date of death (computed but never published — see Terminology note).

---

### Checkpoint 3 — Missing owner risk
*CLEAN: all signers located/responsive. CAUTION: one signer unreachable, cure
path available. HARD STOP: necessary signer unfindable + low equity /
international search.*

**Already surfaces:** `phone_fact(row)` → link status
`tied|name_match_only|other_record|not_owner|unlinked|none`
(`call_ready.py:490-528`); `mailing_fact(row)` → `ok|missing|other_record|
malformed` (`call_ready.py:588-607`); whether at least one estate contact
exists at all (`estate_fact()['pr']`/`['heirs']`).

**Still manual:** a per-signer roster on a multi-heir deed; cure-path
availability for a missing signer; the international-owner HARD STOP.

---

### Checkpoint 4 — Liens, judgments, bankruptcy exposure
*CLEAN: one payoff-able/current mortgage, no judgments/bankruptcy (tax liens
alone still clean). CAUTION: multiple liens, total well under spread. HARD
STOP: liens exceed value, active Ch7/13 w/o trustee approval, IRS liens
stacked on an estate.*

**Already surfaces:**
- `tax_fact(row, today)` → confirmed county delinquent-tax `years`, `total`
  $, `late_years`, `sold_at_tax_sale`, freshness ≤30 days
  (`call_ready.py:225-273`). De minimis floor: balances under $25 don't count
  (`call_ready.py:105`).
- `bankruptcy_fact(row, today)` → `{active, basis}` — directly answers the
  "active Ch7/13" prong (`call_ready.py:610-632`).
- `lawyer_list()`'s `taxpayer`/`rod_checked`/`tax_checked` items confirm
  whether liens have even been checked (`call_ready.py:748-774`).

**Still manual:** a summed "total liens vs. property value" comparison;
whether an active bankruptcy has trustee approval; IRS liens as a
distinctly-tagged signal (only generic `judgment_lien`/`lien_claim`/
`recorded_debt` exist today).

---

### Checkpoint 5 — Access, landlocked, easement issues
*CLEAN: direct public-road frontage. CAUTION: unrecorded easement,
cooperative servient owner. HARD STOP: no legal access, prescriptive-claim-
only, disputed/hostile easement + low equity.*

**Already surfaces:** nothing. No field for "access," "easement,"
"landlock," or "frontage" exists anywhere in `call_ready.py`,
`distress_score.py`, or `grading.py`. **100% human/title-search territory.**

---

### Checkpoint 6 — Chain of title defects
*CLEAN: chain complete/clean 30+ years. CAUTION: one defect, known cure path.
HARD STOP: forged deed, fraud, or complex trespass/quiet-title litigation
needed.*

**Already surfaces:**
- `_latest_deed(raw)` pulls the register's latest deed bound to the parcel
  (`call_ready.py:711-737`).
- `conveyed_after_death(raw, death)` — a real, specific title-defect flag:
  deed recorded *after* the date of death means the estate already conveyed
  it (`call_ready.py:740-745, 963, 129`).

**Still manual:** whether the chain is clean 30+ years (the pipeline only
captures the latest deed); forged-deed/fraudulent-conveyance/scrivener's-
error/missing-spousal-joinder detection by name; whether a found defect has a
known cure path.

---

### Checkpoint 7 — Seller control and authority
*CLEAN: full documented authority. CAUTION: authority exists, needs one more
step. HARD STOP: no authority and won't get it, or misrepresenting
position.*

**Already surfaces:** `owner_kind(row)` tells you what type of party would
need to sign; `estate_fact()['pr']` — whether a named Personal Representative
exists, the closest thing to documented authority the pipeline tracks.

**Still manual:** entity good-standing/registered-agent verification (exists
elsewhere in the codebase via the SoS registered-agent enricher, not read by
`call_ready.py`); trust-trustee verification; power-of-attorney validity;
"misrepresenting their position."

---

### Checkpoint 8 — Estimated timeline to cure
*CLEAN: <60 days. CAUTION: 60–180 days. HARD STOP: >6 months or unknown.*

**Already surfaces:** nothing. `sale_fact()['days']` is a countdown to a
*scheduled auction*, not a curative-title timeline. **100% human/attorney,
once checkpoints 2 and 6 are known.**

---

### Checkpoint 9 — Estimated legal/title friction cost
*CLEAN: <$2,500. CAUTION: $2,500–$25,000. HARD STOP: $25,000+ or
unpredictable/out-of-state litigation.*

**Partially surfaces:** `fullmer_rank.py` computes a margin-vs-fixed-curative-
cost *ratio* (`raw['fullmer'].margin_coverage: 4x strong, 2x acceptable`,
`call_ready.py:55`, consumed at `call_ready.py:796-798`) — but the underlying
**dollar figure and its CLEAN/CAUTION/HARD-STOP banding are never published**
by `call_ready.py`, `distress_score.py`, or `grading.py`.

---

### Checkpoint 10 — Profit potential after cure
*Scored LAST, not first. CLEAN: $50k+ net spread (post-cure, post-carry).
CAUTION: meaningful but tight. HARD STOP: <$50k once honestly modeled.*

**Already surfaces, on two different bases — see the equity caveat above:**
- PRIMARY (as of 2026-11-10): `as_is_value` + the as-is offer band
  (`offer_low`/`offer_target`/`offer_max`), DPA's own 10/30/50% rule
  (`grading.py:6-17, 833-872`).
- `distress_score.py`'s `equity_band` (`high|med|low` + `evidenced`) —
  **still ARV-anchored** (`distress_score.py:1314-1392`).
- SECONDARY, explicitly labeled flip-upside figures: `roi_pct`,
  `max_bid_70`, `wholesale_mao`, `estimated_profit` (`grading.py:313-316`).

**Still manual:** a single published "net profit after ALL curative friction
+ carry" figure the way DPA defines it — the pipeline's profit figures are
flip-rehab-cost-netted, not curative-title-cost-netted; the $50k floor test
itself (no such constant exists in the code).

---

### Checkpoint 11 — The tally
*8+ CLEAN = CALL. 3–5 CAUTION = WORK IT. 1+ HARD STOP anywhere = WALK
(dominates).*

**Already surfaces:** no CLEAN/CAUTION/HARD-STOP tally exists anywhere in the
code. `call_ready`'s lane+tier gate and `distress_score`'s HOT/WARM/COLD tier
are real go/no-go verdicts serving the *same purpose* — a fast final call —
but built from an entirely different, non-overlapping rubric (contactability
+ issue-freshness, or distress-category-stacking + equity-band). **Do not
treat either as a stand-in for walking all 11 checkpoints.** The tally itself
is 100% human, performed after Checkpoints 1–10 — most of which, per above,
are still largely human/attorney work.

---

## Part 2 — Deal Review Framework: SET + PRU

**S — Situs** (state/city, property type, occupancy). Already surfaces:
`has_property(row)` confirms a usable parcel/address; `grading.py`'s
`_location_score()` tiers the county (tier_1: Mecklenburg/Buncombe/
Greenville; tier_2: Spartanburg/Anderson/Henderson/Gaston/Rutherford; tier_3:
13 named rural counties) with median-income context (`grading.py:922-968`).
Missing: occupancy status — no field exists anywhere.

**E — Equity** (FMV minus mortgages/taxes/liens — explicitly NOT ARV).
`raw['distress_stack']['equity_band']` is netted but on the ARV anchor.
`c.as_is_value` is the right FMV-ish anchor but isn't netted against
mortgages/liens. **These two have not been merged** — the single number DPA
wants doesn't exist yet.

**T — Title** (owners of record, heirs, interests, probate status, defects).
The best-covered field by far — everything under Checkpoints 2 and 6, plus
`lawyer_list()`'s full nine-item checklist (`call_ready.py:748-774`).
Missing: fractional ownership-interest percentages per heir (only a count);
DPA's own 6-type title-defect taxonomy classified by name.

**P — Parties** (who wants to sell, ownership %, family dynamics). Barely
surfaces anything — only *how to reach* "the owner" (singular contact path),
never per-party sentiment or ownership sizing. 100% call-time discovery.

**R — Risks** (missing heirs, probate, foreclosure, lawsuits, unknown liens,
title defects, tax sale, family disputes). Most named items surface
individually (see Checkpoints 2/4/6). Missing: "family disputes" and generic
open lawsuits — only specific tracked docket types exist (bankruptcy,
foreclosure/lis pendens, divorce, judgment liens).

**U — Upside** (why pursue, where profit comes from). Surfaces as numbers
only: `rank()`'s combined score, `distress_score`'s stack/equity_band,
`grading.py`'s as-is offer band and secondary ROI figures. Missing: a written
upside narrative.

---

## Part 3 — Call Framework fact-extraction sequence

In DPA's own order (Staged Introduction → Discovery → Build the Gap →
Options → Soft Pitch; hard rule: **never quote a firm price on the first
call**). Each fact annotated with whether the pipeline pre-fills it before
the phone ever rings:

| # | Fact (DPA's order) | Pre-filled? | Source |
|---|---|---|---|
| 1 | Relationship to deceased | Partial — each heir candidate carries a `relation` string | `call_ready.py:459-472` |
| 2 | Deceased owner's name | Computed, never published | `call_ready.py:364, 376-409` |
| 3 | Property address/county/state | **Yes** | `call_ready.py:353-359` |
| 4 | Tax-delinquency status/duration | **Yes — the most completely automated fact in the sequence** | `call_ready.py:225-273, 1054-1055` |
| 5 | Deceased status of each owner of record | Partial — one tied/not-tied verdict, not a per-owner roster | `call_ready.py:416-434` |
| 6 | Full heir list | Partial, as a **count** only; names require reading `raw['heir_candidates']` | `call_ready.py:459-472, 1063` |
| 7 | Probate open/completed status | **Yes**, freshness-gated at 365 days | `call_ready.py:439-483, 1062` |
| 8 | Family cooperation status | No | — |
| 9 | Occupancy status | No | — |
| 10 | Who uses the property / rent collection | No | — |
| 11 | Owner's desired outcome | No — purely conversational | — |
| 12 | Family's self-cure capacity/timeline | No, by DPA's own design (delegated to a human coach) | — |
| 13 | Owner's receptiveness signal | No — don't confuse with the contactability tier, a different concept | `call_ready.py:814-837` |
| 14 | Co-heir count (sizes per-person payout) | **Yes — the cleanest, most directly actionable pre-fill in the whole sequence** | `call_ready.py:459-472, 1063` |

**Net:** of 14 facts, the pipeline pre-fills **3 cleanly** (#3, #4, #7), **4
partially** (#1, #2 internal-only, #5, #6/#14 as a count), and leaves **7
entirely to the live call** (#8–#13, plus the name behind #2). Walk into
Discovery already knowing the address, tax picture, probate posture, and
heir count/split math — everything about cooperation, occupancy, goals, and
receptiveness still has to be asked from scratch.

---

## Part 4 — Routing & handoff: what happens after a lead passes triage

This pipeline's equivalent of DPA's "triage sheet → call → curative action"
chain is the `call_ready` gate: one function that reads a board row's
checked signals and emits a **lane** (what kind of lead this is) and a
**tier** (how ready it is to act on), never a numeric score
(`call_ready.py:9-61`).

### The routing decision table

| Lane | DPA-equivalent | Tier reachable | Next human action |
|---|---|---|---|
| **A** owner call: delinquent tax | Tax-delinquency sourcing, clean-title case | A/B/C | **Self-close.** Call or mail the living owner directly. No curative step. |
| **D** foreclosure flip | Foreclosure/auction category | A/B/C, ranked by days-to-sale | **Self-close.** Call/mail before the sale date or upset-bid deadline, or bid at auction. |
| **E** mail only (no dialable phone, or entity/trust owner) | DPA's entity/trust-ownership note | C | **Self-close by mail.** An entity/trust owner is written to, not called. |
| **B** heir lane: open estate | DPA's dominant death/heirship/probate category, *with* an open estate | C only — no phone path coded | **Doesn't fit a clean bucket** — not self-close, not the attorney's work (title isn't clouded; a PR has standing), not archived. Mail the PR or heir at the probate notice's address. |
| **C** quiet-title lawyer lane | DPA's orphaned-estate / no-probate curative category | C only, once every intake item is sourced | **Hand off to the attorney.** Detailed below. |
| No lane | n/a | D (research) | Sits un-called — nothing is ever deleted. See "Archive" below. |

### Attorney handoff (Lane C)

Lane C fires only when a record-level death signal is on file **and** no
estate is open (`call_ready.py:955`, `death_fact()`/`estate_fact()`) — this
pipeline's exact rendering of DPA's "orphaned estate" pattern.

The attorney — code comments name him Stephen, the agency's own NC+SC
real-estate attorney for quiet-title/probate/affidavit-of-heirship work —
gave a 9-item intake list before he'll open a quiet-title action, encoded
verbatim as `lawyer_lane.ITEMS`:

```
parcel, legal_description, deed_chain, taxpayer, heirs,
rod_checked, tax_checked, probate_checked, obituaries_checked
```
(`lawyer_lane.py:3-9, 43-49`)

A lead is **READY** for him only when every item is sourced *and dated*
(`lawyer_lane.py:447-448`). `scripts/lawyer_packages.py` recomputes this
live, merging three layers per item, latest-sourced-wins:

1. **Automated, no human step.** Board enrichment signals already on the
   row: `raw['deed_latest']` for legal description/deed chain, the tax-lien
   verifier for taxpayer-of-record, `heir_candidates` for heirs, dated
   register/tax/probate/obituary check records
   (`lawyer_lane.py:192-238, 286-444`). **Obituaries are off by policy, not
   by wall** — *"per-lead obituary lookups are off by the owner's
   decision"* (`lawyer_lane.py:441-443`).
2. **Automated once triggered, but the trigger is manual.** Run
   `scripts/quiet_title_intake.py --pin <PIN> --county <County>`:
   `quiet_title/intake.py` builds the records-checked table,
   `quiet_title/fetch.py`'s `PoliteFetcher` paces every request ≥1.6s/host
   and raises `Walled` on any CAPTCHA/login/block page rather than retrying
   around it (`quiet_title/fetch.py:36-57, 113-119`),
   `quiet_title/render.py` writes the HTML+PDF sheet. Output is private,
   outside the repo, at `~/Desktop/Lawyer_Review/intake/<PIN>/`. *"Sends
   nothing to anyone: no email, no upload, no external service"*
   (`scripts/quiet_title_intake.py:15`). Today only Buncombe/Polk NC run
   live register reads; other NC counties read the statewide NC OneMap
   parcel layer; SC isn't covered.
3. **Fully manual.** `<owner-inputs>/<PIN>/items.json` plus saved documents
   under `~/Desktop/Call_Sheets/lawyer/owner_inputs/<PIN>/` — nothing in the
   repo writes to this layer.

When all nine items clear, `scripts/lawyer_packages.py` writes the finished
package (HTML + PDF) to `~/Desktop/Call_Sheets/lawyer/<date>/packages/`.
Nothing lands on the public board either way.

### Manual-lane routing index

When an item comes back `walled` rather than `missing`, a script can't get it
at all — the gap is a specific card in `docs/OWNER_MANUAL_LANES.md`, not an
engineering backlog item:

| `call_ready` unmet code | What's missing | Card |
|---|---|---|
| `lawyer_rod_checked_walled`, `lawyer_deed_chain_walled`, `lawyer_legal_description_walled` | Register of deeds not script-readable | The county's own row in the "Every county at a glance" table (`OWNER_MANUAL_LANES.md:1497-1619`) |
| `lawyer_tax_checked_walled` | County tax site not script-readable | "Tax status for HOT leads" / "SC property cards" (qPublic) |
| `lawyer_probate_checked_walled` | Estate index behind a CAPTCHA, login, or not online | "NC estate lists" (ncnotices.com 26E), "SC probate site" (southcarolinaprobate.net), "Anderson/Lexington probate" |
| `lawyer_heirs` (missing, not walled) | No heir/PR with a stated relation and dated source | "Full text of NC estate and foreclosure notices"; obituaries behind a bot check |
| `estate_status_unknown`, `no_estate_contact` | Probate notice over a year old, or no PR/heir on file | Same NC estate / SC probate cards |
| SC foreclosure/partition/lis pendens/quiet-title case gaps | SC Public Index bot-checked for 45 of 46 counties | "SC Judicial Public Index case lists" |

### Archive / discard: what actually happens

There is no discard step. `stamp_board()` is explicitly "idempotent; rows are
never removed" (`call_ready.py:1071`). A row whose issue resolved (tax paid,
sale pulled, foreclosure ended) just gets `lane: ""`, `tier: "D"` and sits
un-called — re-checked automatically on the usual cadence (tax check expires
at 30 days, sale status at 7 days, estate notice at a year). **"Archive" in
this pipeline means the owner stops dialing a tier-D lead by choice; nothing
in the code does it for him.**

### Phone/email skip-trace: out of scope by design, not a gap

*"Contactability is the single biggest cap on the engine, and it is a
compliance ceiling, not a missing source. You cannot buy your way past it
inside the rules"* (`docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md:45`). Wired,
all free: the NC voter file match, county-published owner-phone GIS tables,
owner mailing address from county GIS, a tax-records-only free skip-trace
provider. TruePeopleSearch, FastPeopleSearch, Radaris, Whitepages, and
PropWire's paid tier are named explicitly as **WONT**, not CANT — *"These
have a working bypass or a checkout button, which is exactly why they are
off-limits"* (`:61-62`). **Where a human plugs it in:** look up a HOT lead's
phone by hand, save a CSV, run `scripts/ingest_contacts.py` ("Phone numbers
for HOT leads" card, `OWNER_MANUAL_LANES.md:229-255`).

### One tool not wired into the above

`quiet_title/layups.py` runs its own five-rule gate (county/state match, two
completed delinquent tax years, no bankruptcy/foreclosure signal, heirs/
estate wording, a single clean parcel) ranked by confirmed heirs-claim first,
then smaller balance first. Invoked only by `scripts/quiet_title_layups.py
--county <County> --top <N>`; prints a ranked list, writes no file. It does
not import `call_ready` and isn't imported by it — it's a human's pre-triage
screen for *which* Lane C candidates to run `quiet_title_intake.py` on, not a
routing decision in its own right.

---

**Sources read in full for this document:** the DPA bootcamp/book extraction
(`master_techniques_criteria_structure.md`, `master_sources_and_signals.md`),
`call_ready.py`, `distress_score.py`, `valuation/grading.py` (post-fix),
`lawyer_lane.py`, `quiet_title/intake.py`, `fetch.py`, `render.py`,
`layups.py`, `scripts/lawyer_packages.py`, `scripts/quiet_title_intake.py`,
`scripts/quiet_title_layups.py`, `docs/OWNER_MANUAL_LANES.md`,
`docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md`.
