# The call-ready gate

The owner's goal: when we call, there is a real, checked problem we can talk about with the owner (or
the family) with empathy, nobody's time is wasted, and the lead can go to the attorney, be cleaned up
(title, payoffs) and be sold through an agent. This page says, per lane, what has to be true before a
lead is called, mailed or researched, how many leads are there today, and what keeps the rest out.

Code: `src/foreclosure_scraper/call_ready.py` (pure, no network). Published on every row as
`raw.call_ready`. Daily closers' list: `scripts/call_list_daily.py`. One-page evidence sheet per lead:
`scripts/lead_evidence_sheet.py`. Invariants: `scripts/audit_checks/call_ready.py`. Tests:
`tests/test_call_ready.py`, `tests/test_audit_checks_call_ready.py`.

## Lanes (the path a lead takes; one primary lane per row)

| Lane | For | Every condition below must hold |
|---|---|---|
| **A** owner call: delinquent tax | a living owner who owes county property tax | the county's own tax site **confirmed** late years and an amount on the row's **own parcel**, checked **within 30 days**, by a checker version without the known wrong-parcel defects; balance at least $25 and at least one completed late year; **not paid, not sold at a tax sale, no bankruptcy** on record; the owner of record is an **individual** (no company, trust, estate or government) with **no death record**; a **phone a closer may dial** (tied to the record, or a name match flagged as such; never an agent's, a people-search result, a do-not-dial or a DNC-registered number); a **sane mailing address** on the county record (a number or box and a ZIP or state; not "UNKNOWN", not 99999, not another property's or person's record) |
| **B** heir lane: open estate | a dead owner whose estate is open | the owner of record is dead **on a record** (the roll's HEIRS / ESTATE / DECEASED wording, a probate record or notice, McDowell's deceased-owner roll, the county death index); the row names a **property** (a parcel or a numbered street address); the **county roll owner of that parcel is the dead person** (first and last name); a **probate record with a personal representative** (or an heir with a stated relation) seen **within 365 days** (older: "check the clerk's index"); no deed recorded after the death |
| **C** quiet-title lawyer lane | a dead owner, no estate on file (the title sits in the dead owner's name) | the same death and property conditions as B, no open estate, and **the attorney's intake list complete, every item sourced** (next section) |
| **D** foreclosure flip | a foreclosure, auction, sheriff or HOA sale in the **18 original counties** (`config.in_scope`) | the sale date is ahead **or** the upset-bid window is open; the source **re-listed it within 7 days** (or a court bid lookup did); not pulled, withdrawn, dismissed, postponed or stayed; the register of deeds does not show the foreclosure ended |
| **E** mail only | a checked issue and no phone to dial | a confirmed county tax balance (same tax conditions as A) or a confirmed code-enforcement / vacant-structure case; a sane mailing address; no dialable phone, or the owner is a company or trust (written to, not called) |

A row that fits none of these (no tax, estate, title or sale lead, or a government owner) gets lane "",
tier D and the reason. Nothing is ever removed from the board: a lead that fails a condition stays,
ranked, with the list of what is missing.

## Tiers (how ready the lead is)

| Tier | Meaning | When |
|---|---|---|
| **A** | call now | every condition of the lane holds and the phone is **tied to the property's record**: the matcher matched the parcel id or the owner's name AND the property's address, or `block_binding` binds the phone to the parcel / address, or it is the row's own source's record |
| **B** | call, confirm identity first | the conditions hold but the phone matches the owner **by name only** (voter file, name + county): the first sentence of the call confirms the person |
| **C** | mail | the conditions hold and the contact is a mailing address (lane E; a representative's address in lane B; heirs care-of in lane C) |
| **D** | research | at least one condition is not met; `unmet` says which, in order |

The Do Not Call scrub: no registry file is loaded today (`data/dnc_registry.csv` is absent; `raw.dnc_scrub`
is on 0 rows of the live board), so every phone's `dnc` is `not_scrubbed` and `dnc_not_scrubbed` is
listed. It is a dial-time step and does not lower the tier; a phone the scrub marks `registered` or
`do_not_dial` is never in tier A or B (the lead moves to mail).

## The published block (`raw.call_ready`, public-safe)

`{v, lane, tier, rank, reason, unmet, checks, phone, dnc, mail, facts, lawyer, as_of}`; a row with no
lane carries only `{v, lane: "", tier: "D", unmet}`.

* `reason`: one sentence in plain words built only from checked facts ("Buncombe County's tax site
  showed $4,321 past due over 3 years on this parcel when checked on 2026-10-06. The phone on file is
  tied to this property's record."), or "Not ready: <the first unmet condition>".
* `unmet`: condition codes (`call_ready.UNMET_WORDS` has the words; the dashboard export, the CSV and
  the evidence sheet print them). `call_ready.hard_unmet()` leaves out the informational ones.
* `checks`: `[{check, result, on, source}]`: the county tax site, the death index and deeds, the
  bankruptcy court, the sale list, the register of deeds, code / vacancy registers; each with its date.
* `phone` (tied / name_match_only / other_record / not_owner / unlinked / none), `dnc`, `mail`
  (ok / missing / other_record / malformed), `facts` (years and balance from the check, sale window and
  days, the death record kinds, estate status, heir-candidate count), `lawyer` (lanes B and C).
* No names, phones, e-mails, ages or heir details: those stay in their own published blocks (owner
  names and phones are already public by the owner's decision; heir candidates only in their
  published form) and in the private CSV and sheets.

Dashboard: the "Contact / Signal" filter has "Call-ready: call (tier A or B)", "call now", "confirm
identity first", "mail", "research" and one entry per lane. The CSV export gains `call_lane, call_tier,
call_rank, call_reason, call_unmet, call_checked_on`. Rows published before the gate show blanks.

## The attorney's intake list (lanes B and C)

`src/foreclosure_scraper/lawyer_lane.py` (audit 2026-10-09, docs/audit_2026-10-09/lawyer_lane.md). Each item
is published as the ISO date it was sourced, or `missing` (a script could supply it and has not), `walled`
(a person has to pull it) or `n/a`. A lane C lead is ready only when every item is sourced AND dated.

| Item | Sourced and dated when | Gap |
|---|---|---|
| parcel number | a usable parcel id on the row (dated by the row's last sighting) | address-only rows |
| legal description off the latest deed | `raw.deed_latest`: the latest deed from a register chain BOUND to this parcel (the county parcel record cites its book/page, or it was recorded within 31 days of the parcel's last sale), with the register index's description, dated when the register was read | the full metes-and-bounds text is only on the deed image (paywalled or bot-checked; a person pulls it); a chain found by name only is never used |
| deed chain | a bound register chain with an earlier conveyance, or the death-index/deeds check's complete chain | counties with no register adapter |
| taxpayer of record | the tax site check matched the owner, or the county roll on the row agrees with the owner | |
| possible heirs | a personal representative, or an heir candidate with a publishable relation and a dated source | no free heir source outside obituaries and probate notices |
| records checked: register / tax / probate / obituaries | a dated register read (chain, name index, death-index check); the tax_lien check; a probate record or notice, or a dated estate-index search (`raw.probate_search`); an obituary, a survivor list, or a dated search that found none (`raw.obituary_search`) | NC estate files are behind a CAPTCHA (`walled`: the owner searches eCourts); per-lead obituary lookups are off by the owner's decision |

`scripts/lawyer_packages.py` merges the board, the live intake sheet (`scripts/quiet_title_intake.py`) and
what the owner pulled by hand (`~/Desktop/Call_Sheets/lawyer/owner_inputs/<PIN>/items.json`, walls register
card `lawyer_owner_pulls`) and writes the package for every lead that is then complete.

## Ranking (Fullmer: order, never a filter)

`rank` 0-100 orders leads inside a tier: years delinquent (`fullmer_rank.delinq_ripeness_points`: year 1
is early, year 2 the base, ramping to the 15-year peak; up to 40), the confirmed balance (up to 15; the
$10,000 production filter tops it), margin against the fixed curative cost (`raw.fullmer.margin_coverage`:
4x or more 15, 2x or more 8, unknown 4), county-appraised value (up to 10), four owners or fewer (5), exit
liquidity (up to 6), and for lane D the days to the sale (up to 9). Fullmer ranks and never deletes
(about thirty leads per deal, book p. 109; sellers who said no come back, pp. 107-123), so no
threshold here drops a lead.

## Counts (2026-10-08, with the ledgers on disk attached)

Rows by lane and tier. Live board: the 2026-10-07 publish, 350,013 rows. Checkpoint: the pre_publish
checkpoint saved 2026-10-08 21:03 UTC, 383,378 rows. Both judged on 2026-10-08 with the nine
verification ledgers as they stood that evening (`scripts/call_list_daily.py`; a tax sweep was still
adding checks, so a rerun an hour later moved lane A by a few rows).

| Lane | Tier A (call now) | Tier B (confirm identity) | Tier C (mail) | Tier D (research) |
|---|---|---|---|---|
| A owner call: delinquent tax | 351 / 345 | 269 / 264 | - | 9,766 / 10,434 |
| B heir lane: open estate | 0 / 0 | 0 / 0 | 3 / 7 | 1,799 / 6,271 |
| C quiet-title lawyer lane | 0 / 0 | 0 / 0 | 0 / 0 | 17,439 / 21,484 |
| D foreclosure flip | 11 / 15 | 21 / 22 | 21 / 42 | 1,409 / 1,385 |
| E mail only | - | - | 5,181 / 5,155 | 91,647 / 111,703 |
| no lane | | | | 222,096 / 226,251 |

(live / checkpoint). The closers' list from the live board, one row per property: **620** (lane A:
350 tier A, 267 tier B; lane B: 3 to mail). All in NC but one SC lane A tier B lead (SC phone coverage is
the known wall). Of the 169 distinct parcels on the hand-made pilot sheet (173 rows): 57 stay tier A,
19 move up from B to A (phone tied by parcel or name + address), 32 stay B, 7 move from A to B (name
match only); 37 drop to research (27 mailing address is another property's record, 5 placeholder
"UNKNOWN ... 99999" mailings, 5 no unique ledger match or the check could not decide) and 17 leave
the owner-call lane because no phone a closer may dial is left (6 attorney phones and 6 uncorroborated
voter cross-reference phones were on the pilot as if they were the owner's; 5 others name another
person or an agent).

### What keeps the rest out

The condition that ALONE keeps a row out of a better tier (live / checkpoint):

| Lane | Single blocker | Rows |
|---|---|---|
| A | the county tax site was never checked | 3,816 / 5,297 |
| A | the county shows it paid / never owed | 288 + 131 / 325 + 161 |
| A | mailing address is another property's or person's record | 133 / 109 |
| A | check undecided; balance under $25 | 79, 78 / 85, 78 |
| B | the notice names no property | 1,439 / 1,744 |
| B | no county roll owner to tie the dead person to the parcel; the roll names someone else | 31, 20 / 38, 14 |
| C | (lane C rows miss several items at once: 8,341 live rows lack all but the parcel; 5 checkpoint rows lack only the obituary check) | |
| D | no sale date and no upset window on a sale-type row | 634 / 628 |
| D | sale date passed, no window | 81 / 53 |
| E | the county tax site was never checked | 24,075 / 44,763 |
| E | check undecided; no mailing address | 1,936, 1,898 / 1,936, 1,666 |

Lane A's 3,816 unchecked rows by county (live; checkpoint in brackets): Lincoln 1,566 (2,522),
Rutherford 1,231 (1,255), McDowell 633 (721), Henderson 242 (239), Transylvania 93 (94), Buncombe 19
(21), Cleveland 16 (15), Burke 8 (8), Onslow 1 (415). Lincoln, Rutherford, McDowell, Transylvania,
Cleveland and Burke have no tax checker at all (Transylvania is on ITSPublic: one portal entry in
`tax_lien_itspublic.py`); Henderson (PTS Cloud), Buncombe and Onslow (ITSPublic) have one and the sweep
has not reached those rows.

### What the audits must fix to grow the lists (largest first)

1. **County tax checkers** for Lincoln, Rutherford and McDowell (then Transylvania, Cleveland, Burke)
   and a full Henderson / Onslow sweep: about 3,800 live lane A rows (5,300 on the checkpoint) wait on
   that check alone, and 24,000 lane E mail rows.
2. **Tie probate notices to a property** (the county roll owner named as the decedent): 1,439 live
   lane B rows (1,744 on the checkpoint) have a representative and nothing else missing.
3. **The attorney's list on the board**: the latest deed's book / page and legal description (deed
   chain from the register of deeds), a dated probate check (NC estate files: a person's lane), and a
   dated obituary check even when nothing is found. Today 0 lane C leads are complete.
4. **Sale dates** on 634 sale-type rows in the original counties.
5. **The DNC registry file** (an owner step), so tier A and B numbers can be dialed without a manual
   scrub.

## Fullmer's ten underwriting items (Dirty Deeds ep 019) mapped to the board

He numbers eight and names nine categories in the episode; "ownership structure" and "owner
profiles" are counted apart, as his closing recap does. He scores each on money and time, and says
sizing up a deal takes 20 to 30 minutes.

| # | Item | Field on the board (and its role here) | Gap |
|---|---|---|---|
| 1 | Ownership structure (one owner, many, entity, trust, estate) | `raw.entity_type` (gate: lane A needs an individual; entity / trust to lane E; estate to B / C); `raw.fullmer.owner_count` (rank: four or fewer) | owner count is read off the roll's name string; fractional heir shares are not counted |
| 2 | Owner profiles (a few minutes on obituaries, relatives, public profiles) | `raw.obituary`, `raw.heir_candidates` (obituary survivors, published relations only), `raw.owner_mailing.absentee / out_of_state`, `raw.tenure` | no social or professional profile lookup (a person does it; the evidence sheet links the obituary) |
| 3 | Access to owners and whereabouts | `call_ready.phone` (tied / name match), `dnc`, `mail` (sanity of the county's mailing address), the probate notice's representative address | no heir phones by design; no locator for a missing heir (the private investigator is a person's step) |
| 4 | Early entry and equity (let them name the number, buy a big share first) | `raw.equity`, `raw.calc.as_is_value / offer_*` | share-by-share pricing of a fractional interest is not modeled |
| 5 | Title defects and solutions (taxes, open or missing probate, chain breaks, unreleased mortgages, fraudulent deeds) | the tax check (`raw.verification` tax_lien, gate of lane A), the death / estate facts (lanes B and C), `raw.deed_chain.summary.chain_breaks`, `raw.title_risk`, the attorney's list | unreleased ("zombie") mortgages: the register's mortgage index is read for Gaston only (`raw.rod`); no failed-lender (FDIC) lookup |
| 6 | Judgments and liens (same person? past the statute of limitations?) | `raw.liens`, `raw.sc_state_tax_lien`, `raw.irs_lien`, judgment blocks; `block_binding` keeps another person's lien off the row | the age against the roughly 10-year limit is not computed; NC judgment search is behind a CAPTCHA (a person's lane) |
| 7 | Litigation (stay out unless a tax suit or a foreclosure) | bankruptcy (gate: lane A blocks it), lis pendens / foreclosure (lane D), court signals | other civil suits are not indexed (NC eCourts: a person's lane) |
| 8 | Demand and liquidity (metro size, weeks to sell) | `raw.fullmer.liquidity` (rank) | market tiers are by metro, set by hand in `fullmer_rank.MSA_TIER` |
| 9 | Financial model (as-is value minus taxes, ~10% to sell, the seller's payout, curative cost) | `raw.calc.as_is_value / est_gross_margin`, `raw.fullmer.margin_coverage` against the three-tier curative estimate (rank: 2x to 5x) | curative tiers are estimates (`fullmer_rank` docstring), not quotes from the attorney |
| 10 | Risk of loss (a tax or mortgage foreclosure can wipe the position out; deadlines) | lane D window and days to the sale, `sold_at_tax_sale` (unmet in A), `raw.tax_sale_status`, `raw.upset_bid`, the SC redemption deadline | NC tax-foreclosure suits and surplus proceeds are not tracked |

His ranking ideas are inputs to `rank`, never filters: ripeness by years delinquent (book p. 38 and
p. 108: two or three years behind; year one is too early), margin against a fixed curative cost (the
$50,000 margin against a $10,000-30,000 legal budget is two to five times; book p. 35, ep 021), and
never delete (book pp. 107-123: sellers who said no come back; about 30 leads per deal, p. 109). The
opener on the sheet follows ep 021 and the book (p. 61): ask whether it is a bad time, say plainly who
you are (a local real estate operator, not an attorney), name the problem from the record, ask for
five minutes.

## Wiring (main.py, `run_enrich_tail`; not edited here)

After verification.apply, restore_verified_tax and the late block_binding scrub, before the final
scoring. Anchor: the line `        log.error("vacant_landuse.failed", traceback=traceback.format_exc())`
(the end of the vacant-land-use step, right before the `# Stacked-distress score` comment). Insert after it:

```python
    # Call-ready gate (call_ready.py, docs/call_ready.md): lane, tier, reason and unmet conditions per
    # row, read off the checks verification.apply attached, restore_verified_tax and the block_binding
    # scrub above. Pure, no network, never drops a row.
    try:
        from .call_ready import stamp_board as _call_ready_stamp
        enrichment_stats["call_ready"] = _call_ready_stamp(enriched)
    except Exception:
        log.error("call_ready.failed", traceback=traceback.format_exc())
```

Heir candidates (`enrich_heir_candidates`) and the Fullmer rank (`rank_board`) run after
`score_board`, so at the first call a row carries the previous run's copies of both. A second, identical
call after `rank_board` makes lane B / C's heir item and the rank current (idempotent). Anchor: the
line `        log.error("fullmer_rank.failed", traceback=traceback.format_exc())`; insert after it:

```python
    try:
        from .call_ready import stamp_board as _call_ready_stamp
        enrichment_stats["call_ready_final"] = _call_ready_stamp(enriched)
    except Exception:
        log.error("call_ready_final.failed", traceback=traceback.format_exc())
```

`scripts/reconcile_board.py` runs the same tail, so a reconcile re-stamps the gate with that day's
ledgers. The hourly refresh does not: a DNC scrub that lands between runs shows on the next run or
reconcile.

## Using the daily list and the evidence sheet

```
uv run python scripts/call_list_daily.py
```
writes to `~/Desktop/Call_Sheets/`: `Call_List_<date>.csv` (lane A tiers A and B, lane B tiers A to C,
one row per property, tier A first then rank), `Call_List_<date>_not_ready.csv` (lane A / B rows at
tier D with the reasons) and `Call_List_<date>_summary.json` (the counts in this page). It keeps the
pilot sheet's columns (same names) and adds lane, tier, rank, reason, unmet, DNC status, the checks with
dates, the county tax link, the estate contact, heir candidates, the attorney's list and the command for
the evidence sheet. It reads the live board and today's ledgers; `--board <dir>` reads a board or a
checkpoint; `--count-only` prints the counts and writes nothing. About 70 s and 420 MB on the Mac.

```
uv run python scripts/lead_evidence_sheet.py --parcel <parcel id> [--parcel ...] [--county <name>]
uv run python scripts/lead_evidence_sheet.py --from-csv ~/Desktop/Call_Sheets/Call_List_<date>.csv --top 20
```
writes one page per lead (HTML and PDF) to `~/Desktop/Call_Sheets/sheets/<date>/`: the reason, every
check with its result, date and link, the owner and contact checks, the estate and heir candidates, the
attorney's list with what the board holds for each item, where to look in the county (the county
records matrix), the call opener, the before-dialing steps and the unmet conditions. Both scripts refuse
to write inside the repository.

## Not verified / open

* The DNC scrub: no registry file; every phone is `not_scrubbed` (an owner step: register with the
  FTC and save the list as `data/dnc_registry.csv`).
* The 7-day status recheck of lane D trusts the row's `last_seen` (the run that last saw the sale);
  a sale pulled after that run shows as live until the next run.
* "Estate open" is a notice seen within a year; the board has no estate closing date.
* The tie of a phone to the record uses the matcher's own key (parcel id, name + address); a phone
  that one owner's family shares across rows of different owners is flagged on the CSV, not lowered.
* The counts were computed on the live board of 2026-10-07 and the pre_publish checkpoint of
  2026-10-08, both with the ledgers on disk on 2026-10-08 attached the way verification.apply does.
