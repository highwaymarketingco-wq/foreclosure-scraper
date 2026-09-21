# Handoff: scorer changes that need files I do not own, 2026-09-21

The scorer work (see `docs/scoring_fixes_2026-09-21.md`) is complete inside the files I own. These are the exact changes that need main.py, web_artifact.py, the dashboard, the scripts and two enrichers that belong to someone else. Each item says what breaks or stays wrong without it.

## 1. main.py

### 1a. F17: the scorer failure is still swallowed (needed)

`score_board` now raises `ScoreBoardError` after scoring every group it can (a failed group's rows are stamped `score_error` and COLD, so no previous tier survives). The `except Exception` at main.py around line 3009 logs it and carries on, so the run still reports healthy. Replace the block that starts `from .distress_score import score_board` (currently main.py:3000-3010) with:

```python
    try:
        from .distress_score import score_board, ScoreBoardError, LAST_STATS
        _prev_listings = Path(__file__).resolve().parent.parent.parent / "docs" / "listings.json"
        enrichment_stats["distress_stack"] = score_board(enriched, previous_path=_prev_listings)
        enrichment_stats["distress_stack_detail"] = dict(LAST_STATS)   # lane, stale-capped, stay-capped, errors
        log.info("orchestrator.distress_scored", tiers=enrichment_stats["distress_stack"],
                 **{k: v for k, v in LAST_STATS.items() if k != "tiers"})
    except ScoreBoardError as exc:
        # Every group that could be scored was; the failed ones are COLD with score_error.
        # Do not report this run healthy and do not publish it silently.
        enrichment_stats["distress_stack"] = exc.hist
        enrichment_stats["distress_stack_failed"] = {"groups": exc.failed, "first": exc.failures[:3]}
        log.error("distress_score.failed", groups=exc.failed, first=exc.failures[:3])
        # <- add to whatever run-health alarm list the health artifact uses, and make the run
        #    exit non-zero or refuse the board write when this key is present (O4, O10).
    except Exception:
        enrichment_stats["distress_stack_failed"] = {"error": "unexpected"}
        log.error("distress_score.failed", traceback=traceback.format_exc())
```

`LAST_STATS["price_index_error"]` is set when the prior-run price snapshot could not be read (price_cut is then off); worth surfacing in the same alarm list.

### 1b. F8: the actionable window is removed before scoring (not started)

`main.py:1150-1153` partitions `is_sold_pool_candidate` rows out of the active board before `_active_only`. `enrichment_foreclosure_sold_comps.py:142-170` returns True for the 22 named sources when `0 <= days_since <= 180`. Change it to divert only when `days_since` exceeds the state window (14 NC), and keep SC tax sales active with the redemption clock. The scorer already handles both ends correctly (open upset window and SC redemption keep the signal alive; an ended sale is COLD), so this is the last piece that stops the lead from vanishing on sale day. `enrichment_nc_case_status_tyler.py:1141-1148` overwrites `sale_date` with the docket's last event date when a sold price is found; store the true auction date separately or the lifecycle rules read the wrong date.

### 1c. Nothing else needed for signatures

`score_board(enriched, previous_path=...)`, `enrich_bankruptcy_stay`, `enrich_upset_bid`, `enrich_board_quality`, `enrich_lead_signals`, `enrich_strategy_fit`, `compute_flags` and `rank_board` keep their positional signatures; the new arguments (`today`, `now`) are optional keywords. Pipeline order is unchanged. `enrich_bankruptcy_stay` must still run before `score_board` (it does).

## 2. web_artifact.py

- **RAW_KEEP: add `pickens_delinquent` and `vacancy`** (and `vacant` if any writer ever appears). `RAW_KEEP` (web_artifact.py:968) does not carry them, so on any board reloaded from the published files the new `tax_lien_chronic` weight (Pickens, 3+ roll years) and the `vacant_structure` PROPERTY signal (Hendersonville register) cannot fire. They fire on a full run only. A minimal entry for Pickens is `("chronic", "cycle_count")`. `test_raw_keep_covers_enrichers.py` will not catch this because the readers are the scorer, not an enricher.
- **RAW_KEEP: `scope`** (the `flip_outside_footprint` stamp). Already called out in `docs/data_quality_fixes_2026-09-21.md` section 1; the scorer now reads it, so a board that drops the key loses the cap on the next reload.
- `distress_stack` is already `"*"` in RAW_KEEP and `_SLIM_RAW`, so the new fields ship. They are added only when they differ from the default, and `evidence` lists non-record signals only, so the payload cost is small, but it is not zero on a board whose gz is at 84 MiB against the 95 MiB gate. Rough size: a plain lead adds nothing; a lead with a name-based signal adds about 30 bytes; the foreclosure lane adds about 40. Worth a measurement at the next full write.
- `equity` is `"*"`, so `equity.evidenced` ships. `fullmer` is `"*"`, so `lane` and `days_to_event` ship. `signal_stack` slim projection is `("count",)`, which is exactly what the chip reads; `count` now means distinct categories.
- `upset_bid` slim projection is `("in_window", "days_remaining")`. The scorer reads `deadline_iso` when present and falls back to the flag, so a scorer run over slim-only rows treats a frozen `in_window: true` as open. Adding `deadline_iso` to that tuple makes the read-time check exact (F15).

## 3. docs/dashboard.js and docs/index.html

Line numbers below moved while I worked; search by name.

1. **`stageOf`** puts any lead with a truthy `raw.upset_bid` in the "foreclosure" stage. Test `raw.upset_bid && raw.upset_bid.in_window === true` (and the deadline, as `deadlineInfo` does). Same defect as scorer F2.
2. **Tier badge tooltip** (the block that lists signal names): show, from `distress_stack`:
   - `evidence` (an absent entry means record; render name_only and name_joined as "(name match)", inferred as "(inferred)");
   - `stale_reason` ("event ended: ..."), `stay` ("foreclosure stayed by Chapter N bankruptcy"), `lane` plus `days_to_event` ("sale in N days"), `title_status` when `bidder`, and `equity_evidenced === false` ("equity estimated");
   - `uncounted_categories` ("not counted toward the stack").
3. **Bankruptcy banner** ("HIGH-PRIORITY signal"): when `raw.bankruptcy_stay.status === "stayed"` say "sale stayed" and show the resume risk. A `lapsed` stay should not show the banner.
4. **Default sort**: the default is `_grade`. Foreclosure-lane leads with a live deadline should sort first, ordered by `distress_stack.days_to_event` ascending, then the existing key (audit F7). Fullmer also carries `lane` and `days_to_event`.
5. **Chip text**: `signal_stack.count` is now distinct categories, so "N distinct distress signals" reads better as "N distress categories".
6. **`sale_date_passed`** still has no reader on the dashboard. `enrichment_board_quality` sets it; the card should mark the lead.
7. `high_equity` chip: no change needed; the flag is only stamped now when the equity is evidenced.

## 4. board_persist.py

No change required. `board_persist.py:212-213` sets `auction_status = "presumed_withdrawn"` only when the status is empty, so a vanished lead whose last status was "active" keeps that status and only carries `pulled_sale.presumed_withdrawn`. `enrich_board_quality` now downranks on that marker (F2), so the persisted flag is enough. Ageing still counts runs, not days (`board_persist.py:196-216`); the scorer's lifecycle is the day-based backstop.

## 5. enrichment_life_events.py (not in my list; nobody's)

- **Regex (F13):** `_PATTERNS` tags `TRUST` and a bare `ESTATE` as probate, so "ACME REAL ESTATE HOLDINGS LLC" gets `estate_probate`. Change
  `("estate_probate", re.compile(r"\bHEIRS?\b|\bEST(?:ATE)?\s+OF\b|\bESTATE\b", re.I))` to
  `("estate_probate", re.compile(r"\bHEIRS?\b|\bEST(?:ATE)?\s+OF\b", re.I))`, and consider dropping the `trust` and `multiple_heirs` tags from `raw['life_events']` (they are ownership forms). I protected the two readers I own (the chip and strategy fit) with `signal_freshness.owner_names_a_death`, so nothing breaks if this waits, but `enrichment_probate_search.py` also reads the tag and searches probate courts for every LLC with ESTATE in its name.
- **Dead code (F11):** the loop appends `estate_elderly` to `distress_stack.categories`, but this enricher runs before `score_board` (main.py:2773 vs :3000), so it lands on a prior-run dict that is then overwritten. `enrichment_sc_divorce.py:340-344` and `enrichment_nc_divorce.py:270-273` do the same with `divorce`. Delete those appends or run them after the scorer.

## 6. Scripts that call `score_board` and swallow errors

`scripts/daily_api_refresh.py:295-298` wraps `title_risk` and `score_board` in `except Exception ... print("skipped")`, then goes on to publish. With the new behaviour a `ScoreBoardError` means some groups are COLD with `score_error`. Catch `ScoreBoardError` there and abort the write (or at least fail the job). Other callers of `score_board`, each worth a check for a bare `except`: `scripts/completion_pass.py:80`, `scripts/recompute_valuation.py:126`, `scripts/enrich_batch.py`, `scripts/ingest_fresh_court_leads.py:225`, `scripts/patch_distress_score.py:62`, `scripts/enrich_board.py`.

`scripts/owner_mailing_refresh.py:32-48` (`snapshot_for_scoring`, `_MAX_SNAPSHOT_BYTES`) can stay as it is: it hands `score_board` a path that does not exist when the snapshot is large. It is no longer required for memory safety, because `score_board` now only reads the prior-run snapshot when a listing has MLS fields, prefers the small `.gz` sibling, and streams instead of calling `json.loads` on the whole file.

## 7. Things that will look odd at the next rescore

- WARM falls by roughly three quarters and HOT by roughly nine tenths on the sample (`docs/scoring_fixes_2026-09-21.md` section 1); most of WARM is liensnc, and most of the HOT loss is the four new HOT gates (evidenced equity, a record-linked signal, a category of weight 15, name-based signals not stacking). Measure before and after on the real board with the same script that produced the 9/21 tier counts, so the two changes are not blurred.
- `stale_case` is set only for withdrawn cases, as before; it will not appear on the thousands of rows that merely have an old sale date.
- `distress_stack` on a foreclosure lead now carries `bidder` and `title_status`. A foreclosure with no `title_risk` block is WARM at best, so `enrich_title_risk` must have run before `score_board` (it does in main.py and in `daily_api_refresh.py`).
