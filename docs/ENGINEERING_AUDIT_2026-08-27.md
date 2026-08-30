# Engineering Audit — 2026-08-27

Audit of the 7 concerns in `CLAUDE_ENGINEERING_BRIEF.md`, done READ-ONLY against the live code while a pipeline run is in progress (no `uv sync`, no board loads, no edits — so nothing collides with the run). Every claim below was verified against the actual source, with file:line. Ordered by impact, matching the brief's own priority.

Verified ground truth: 235 scraper modules, 144 enrichment modules, ~139.5K LOC, `main.py` 3,077 lines, board `docs/listings.json` 528 MB. The brief's file names and line counts all check out (one exception: `ingest_all.py` is not in `src/` — likely a `scripts/` helper). `models.py` referenced in the brief resolves to `src/porsche_scraper/models.py`; the engine's real model is `src/foreclosure_scraper/models.py` — confirm the brief meant the latter.

---

## 1. Silent-failure audit (THE #1 issue — confirmed, with the exact mechanism)

**The 72K-drop bug is real and I found the precise chain.** `main.py:947-957`:

```python
persist_applied = False
if os.environ.get("FULLRUN_PERSIST", "1") != "0":
    try:
        from .board_persist import merge_prior_board
        deduped, persist_stats = merge_prior_board(deduped)
        persist_applied = persist_stats.get("prior_count", 0) > 0
    except Exception:
        log.error("board_persist.failed", traceback=traceback.format_exc())   # <-- swallow
```

When `merge_prior_board()` raises (e.g. dedupe timeout on 116K combined), `deduped` keeps its fresh-only ~22K value AND `persist_applied` stays `False`. The code then runs the *first-run* pulled-sales path (`main.py:970`) as if no prior board existed, enriches 22K, and publishes. Exit 0. 72K gone. The code comment even calls this "FALLS BACK to fresh-only behavior" — the fallback is the bug: losing 72% of the board must HALT, not proceed.

**Why the count-guard didn't save you (a SECOND bug):** the guard exists at `web_artifact.py:1451-1466` and does refuse a >10% shrink — BUT it compares against the CURRENT on-disk board. If a prior bad run already published 22K, the guard's baseline is now 22K, so the next 22K run looks flat and passes. The guard measures run-over-run drift, not drift from the true high-water mark. It cannot catch a drop that already happened.

**Census:** 1,148 `except Exception` blocks, 1,868 `try:` blocks, only 126 `raise`. 0 bare `except:` and 0 `except: pass` (good — the swallows all log). The problem is not silent-silent; it is **log-and-continue around phases that should be fatal.**

**The fix pattern (structured, three tiers):**
1. Define a `CriticalPhaseError`. Wrap ONLY the phases whose failure means a bad board — `merge_prior_board`, `dedupe` (arguably), `write_artifact` — so that on failure they **re-raise and the process exits non-zero**, never publishing.
2. Keep log-and-continue for per-listing / per-source enrichers (a Zillow crash losing one field is fine).
3. Make the distinction EXPLICIT: a phase is either `@critical` (halts) or `@best_effort` (logs). Right now every phase is best-effort by default, which is exactly backwards for the 3 that matter.
4. Fix the guard: persist a `board_highwater.json` (max count ever published). The guard compares against the high-water mark, not the last (possibly-poisoned) board. A drop below `highwater * 0.85` halts unless `BOARD_ALLOW_SHRINK=1`.

Highest-ROI change in the whole codebase. Two files: `main.py` (re-raise the 3 critical phases) + `web_artifact.py` (high-water guard).

---

## 2. Architecture — is scrape → dedupe → merge → enrich → publish sound?

**The flow is sound and is the correct shape for a record-linkage pipeline.** The ordering is right (dedupe before enrich so you never enrich a row you'll discard; merge prior before enrich so carried enrichment suppresses re-work). Two structural risks:

- **The board is a single 528 MB JSON list held fully in memory** (see #4). This is the root constraint behind #1, #3, and #4 all at once — the O(n²) dedupe, the OOM kills, and the all-or-nothing merge are all downstream of "the whole board is one Python list."
- **Enrichment is a long linear chain of 144 modules mutating one shared list.** That is fine for correctness but means a single wedged network phase stalls everything (the `_await_capped` wrapper at `main.py:730` is the right mitigation — keep using it on every network phase).

Recommendation: keep the flow; change the STORE (see #4). Moving the board to SQLite fixes the memory, the O(n²), and enables the incremental validation in #6 — one change, three problems.

---

## 3. Algorithmic complexity

**dedupe is already fixed** (blocking indexes, `dedupe.py`, 94K went from hang → 168s). Your worry about cross-block misses is valid: keying on zip means the same property with two different zips lands in different blocks and never compares. Mitigation: block on a coarser key (county+state) OR a normalized-street-prefix, and accept that dedupe is best-effort recall, not perfect.

**Nested-loop scan across 144 modules — the quadratic smells to check** (loop-inside-loop over a listings-like collection): `distress_score.py` (3), `enrichment_comps.py` (2), `enrichment_bankruptcy_property.py` (1), `enrichment_helene_damage.py` (1), `enrichment_geocode.py` (1), `enrichment_fema_disaster.py` (1), `enrichment_parcel_lookup.py` (1). `foreclosure_dot_com.py` (4) and `ncpublicnotices.py` (2) are scrapers over small per-page sets — not board-scale, safe.

The real risk is any enricher that, for each of N listings, scans a list of M others (comps, bankruptcy name cross-ref). At 94K those are the next "infinite hang." **The fix is the same every time:** build a dict/index once (by parcel, by normalized name, by county) and look up in O(1) inside the loop, instead of scanning. Priority check order: `enrichment_comps.py`, `enrichment_bankruptcy_property.py`, `distress_score.py`.

---

## 4. Memory — 8 GB, 528 MB board, growing

The board as one JSON list is the ceiling. Loading 528 MB of JSON into dicts is ~2-3 GB; dedupe structures add 1-2 GB; that is your OOM. (Confirmed live: an inline `json.load` of the board got OS-killed this session.)

**Recommended: move the board to SQLite** (`board.db`), one row per listing, `raw` as a JSON column, indexes on parcel_id / county / source / street. Payoffs:
- Enrichers stream/iterate rows in batches instead of holding 94K in RAM — memory goes from GB to tens of MB.
- Dedupe blocks become `SELECT ... WHERE county=? ` — the DB does the blocking.
- `#6` validation becomes cheap SQL (`SELECT source, count(*)`).
- Publish still writes the JSON/`.gz` the dashboard reads, generated by streaming from the DB.

Interim (if a full SQLite migration is too big right now): use `ijson` to stream-parse the board instead of `json.load`, and process enrichment in batches of ~5K with explicit `del` + `gc.collect()` between. This is a band-aid; SQLite is the real answer and it also unblocks #3 and #6.

Profiling: run one phase under `python -m tracemalloc` or `memray` on a 5K-row synthetic board (not the full board) to find the specific enrichers that balloon — `enrichment_vision.py` (1,675 lines, image bytes) is the prime suspect.

---

## 5. Testing without the 5-7h run

The single most valuable change for the fix-break-fix loop: **a `--phase enrich` mode that runs enrichment on the EXISTING board without re-scraping.** Most of the 5-7h is scraping; the bugs you keep hitting (merge, dedupe, ARV) are all post-scrape. If you can run enrich→publish on a saved board snapshot, a test cycle drops from hours to minutes.

Unit tests to add (fast, no network, synthetic 20-row fixtures):
- `dedupe()` — two known-dup rows collapse to one; two distinct rows stay two; cross-zip same-property case (documents the known blocking limitation).
- `merge_prior_board()` — prior 100 + fresh 20 with 5 overlaps = 115, fresh fields win, prior enrichment carried. **This is the test that would have caught the 72K bug**: assert output >= prior_count when a prior board exists.
- `valuation/calc.py` ARV — the 5 fixed bugs each get a regression test (garbage comp rejected, acreage PPSF ceiling, ARV multiplier bounds 2.5/3.5). Assert ARV/assessed ratio stays < 3.0 on a fixture.
- `distress_score.py` — a fixture with each of the 27 flag types fires exactly its flag.

Put a `conftest.py` fixture that builds a 20-listing synthetic board once. These run in <5s and catch every regression class you've hit this week.

---

## 6. Data-validation framework (post-run quality gate)

Build `scripts/validate_board.py` that runs after publish (or on any board file) and EXITS NON-ZERO on failure, so `run_local.sh` can gate the git push on it:

- **Count integrity:** board >= high-water * 0.85 (ties to #1's high-water file).
- **Source coverage:** every source that produced N>0 last run produced >0 this run; flag any that went to 0 (the source-health email already computes this — reuse it).
- **Field completeness:** % with address / owner / assessed / coords, vs prior run; flag a >10-point drop.
- **Value sanity:** count rows where ARV/assessed > 3.0 or ARV > $2M on assessed < $500K; flag if that count spikes.
- **Dup rate:** count exact (parcel_id, source) duplicates; should be ~0 after dedupe.

Emit a JSON report + a one-line PASS/FAIL. Wire it into `run_local.sh` before `git push` so a bad board never publishes. This is the automated version of your manual spot-check, and it is the safety net that makes #5's fast iteration safe.

---

## 7. Dependency management (pyproject / uv sync)

Confirmed: `pyproject.toml` declares 33 deps; the venv has extras (easyocr, imageio, scikit-image, opencv, etc.) that enrichers import but that aren't declared, so `uv sync` prunes them and breaks the venv — which is why the run script calls `.venv/bin/python3.12` directly.

**Fix:** declare the extras. Two clean options:
- Add them to `[project.optional-dependencies]` under a group like `enrichment = [...]`, install with `uv sync --extra enrichment`. Keeps core install lean.
- Or, simplest and safest for a single-machine pipeline: add all runtime imports to the main `dependencies` list so `uv sync` is always a no-op-safe. Pin versions to what's installed now (`uv pip freeze` → reconcile) so a sync never upgrades mid-project.

Method: `.venv/bin/pip freeze > /tmp/have.txt`, diff against pyproject, add every actually-imported-but-undeclared package. Then `uv sync` is safe and `run_local.sh` can go back to `uv run`. **Do this while NO run is active** (it mutates the venv).

---

## Priority order (what to do, in order)

1. **#1 critical-phase halt + high-water guard** — stops the 72K-drop class forever. 2 files. Do first.
2. **#6 validate_board.py gating the push** — the net that makes everything else safe.
3. **#5 `--phase enrich` mode + unit tests** — turns 5-7h cycles into minutes.
4. **#4 SQLite board** — the structural fix that also resolves #3 and most of #4/#6. Bigger lift; schedule it deliberately.
5. **#3 index the 3 quadratic enrichers** — before the board grows enough to hang them.
6. **#7 pyproject** — quick, but do it when no run is active.
7. **#2** — no structural change needed; it is the sum of the above.

All findings are read-only observations; nothing here was edited, and the running pipeline was not touched.
