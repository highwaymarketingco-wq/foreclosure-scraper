# Master plan: the next run is the one that is right (owner's brief, 2026-10-08)

## The owner's asks, restated (checklist; status in the right column, kept current)
| # | Ask | Status |
|---|-----|--------|
| 1 | Walled / CAPTCHA sources: a manual that says exactly what the owner does, per county, city, source, nationwide; changes flagged | Generated from data (walls_register.json); regenerated after the last audit agents; new cards: 5 refuse-the-VM-address counties |
| 2 | Know whether another corrective run is needed | Yes: ONE run on the fixed pin after the gate, canary and wave 2 pass; late ledger changes go through the quick re-score (reconcile), not a re-run |
| 3 | Every fix/correction since the meetings with Hope, the lawyer and the fact-checking session, recorded | docs/board_versions/CHANGELOG.md ("Defects found later") + audit reports |
| 4 | The 82-column x 146-county CSV to 100% (field = filled, signal = checked, walled / no source = a verdict) | gap_matrix cell classes; wave 1 closed the biggest classes; wave 2 closes accuracy |
| 5 | Every listing fact-checked; non-issues removed; only leads we can call about empathetically, hand to the lawyer, clear title, sell | verification sweep (tax), block_binding, call-ready gate (wave 2 F) |
| 6 | Line up with Logan Fullmer's book and podcasts | mapped in the owner reply; call-ready lanes (wave 2 F) |
| 7 | Concrete timelines | in the owner replies; revised after each wave |
| 8 | Audit everything: pipeline, data extracted, process, data NOT processed, every source pulled everything, every image and PDF analyzed; per source, per row, per column, per strategy; no data issues; more sources, signals and counties if needed; only one more full or tail run | wave 1 (done) + wave 2 (running) |
| 9 | A run must not be outdated when it starts | prerun_gate + run_profile.json + canary + audit suite + compare_boards HOLD thresholds |
| 10 | Keep and verify everything added in the last run; lose nothing | additions ledger (wave 2 A) + best-of-both restoration (wave 2 B) + run_profile gate |
| 11 | Always compare versions; notes of improvements and regressions per iteration | scripts/compare_boards.py + docs/board_versions/ |

## Wave 1 (done, reports in this folder)
block_binding, drops_lineage, source_completeness, documents_images, pipeline_gate, version_compare, repo_health, ledger_shards.

## Wave 2 (running)
- A additions_verify: every source, enricher and re-enabled approach added since 10/1: did it run, how many rows, how accurate, is it published, is it in run_profile.json.
- B regressions: every HOLD blocker of the gated_d42058b3 comparison root-caused and fixed; the 3,405 good values the live board holds restored; duplicates; unexplained missing rows.
- C valuation: ARV / comps accuracy (implausible moves, 1,599 lost comps).
- E court and notice signals: accuracy of lis pendens, foreclosure, divorce, probate/estate, bankruptcy, upset bid, tax sale; rechecks at the source where the verification framework can.
- F call-ready: the gate per lane, lawyer evidence sheet, Fullmer mapping, published as columns.
- Later: D column accuracy of the field columns by sampling against primary sources; G owner-vs-roll contradictions and fused rows.

## Gate to the next run (all must hold)
1. scripts/prerun_gate.py passes (pin == HEAD, pushed, full suite green on that code, CI green, ledgers committed, no sweep mid-write, manual current, memory projection under the kill line, run_profile.json matches vm_lib flags).
2. scripts/audit_suite.py passes on the last checkpoint after a reconcile.
3. Canary run passes (4 counties, every enricher produced output).
4. Owner says go.
After the run: compare_boards against the live board: PASS or an explicit accept per blocker; then publish.
