# Engineering Briefing: Real Estate Data Pipeline — Architecture Audit Request

## Project Overview

I have a large Python data pipeline (164,000+ LOC, 642 files) that aggregates, deduplicates, enriches, and publishes public real estate records for North Carolina and South Carolina. The system collects structured data from 209 source modules (county assessor portals, court record systems, public notice feeds, government auction sites, GIS/ArcGIS endpoints), merges them into a unified board of ~94,000 property records, runs 144 enrichment modules (deed chain analysis, title risk scoring, lien stacking, bankruptcy matching, FEMA flood zones, Census geocoding, fair-market valuations, etc.), and publishes the results as a static dashboard to GitHub Pages.

I'm running this on a constrained machine: **8 GB RAM, ~6 GB free disk, macOS 26.1, Python 3.12 in a virtualenv**.

## What I've Done This Past Week

### Commits (git log)
```
e613835 Dashboard: 41,225 listings from 85+ sources (LiensNC 50K, NC eCourts 3.9K, publicnoticesc 1.8K, RECAP 1K, bankruptcy enriched)
570f0dc CourtListener bankruptcy ingest: +1,600 dockets via search API
757df6e dashboard regen: 34,486 scoped listings, 70.3% red-flagged, safeguards live
103e8da dashboard regen: 37,462 listings, 19,889 contactable, red flags rebuilt
289daf6 Scheduled SOS pass: +NC entity registered-agent contacts
b4c1a76 daily vision: 13989 listings scored
1fbf377 100% ALL FIELDS: coords/sqft/flood/amount_owed/assessed/equity/tax_aging/2yr_delinquent=100%, red flags 27 types 45k flags, board restored to 53,851
651be0b title search: 24-step pipeline — deed chains, liens, probate, bankruptcy, FEMA, code enforcement, red flags
342c07f equity: +23,205 via assessed-value payoff estimate. Equity 31.7% → 74.8%
19d905e Board: 53,851 listings (+20,606 PTSCloud NC)
```

### Key Files Modified
| Date | File | What Changed |
|------|------|-------------|
| Aug 27 | `board_persist.py` | Terminal grace period 45→365 days (was dropping 47K valid records) |
| Aug 27 | `dedupe.py` | Added blocking indexes to fix O(n²) fuzzy matching hang |
| Aug 27 | `valuation/calc.py` | Fixed 5 ARV (After-Repair Value) calculation bugs |
| Aug 27 | `enrichment_comps.py` | Added price-band filter to reject garbage comparables |
| Aug 27 | `main.py` | Fixed source scope filter that was silently dropping 43K LiensNC records |
| Aug 27 | `ingest_all.py` | Same source scope fix |
| Aug 26 | `enrichment_bankruptcy_property.py` | GIS name cross-reference for bankruptcy matching |
| Aug 26 | `web_artifact.py` | Count guard — blocks publish if board shrinks >15% |
| Aug 26 | `http_client.py` | 8GB-safe browser management — single reusable instance |

## Architecture

```
209 scraper modules → ingest → board (94K records)
                                      ↓
                           carryover (fill gaps from prior run)
                                      ↓
                           dedupe (fuzzy matching, was O(n²))
                                      ↓
                           merge_prior_board (merge fresh + prior)
                                      ↓
                           144 enrichment modules (deed chains, title risk,
                             liens, bankruptcy, probate, divorce, tax,
                             FEMA, Census, vision/GIS, comps, ARV)
                                      ↓
                           distress scoring (27 red-flag types)
                                      ↓
                           publish to GitHub Pages (write_artifact)
                                      ↓
                           git push
```

### Key Source Files (by function)

**Orchestration:**
- `main.py` (3,077 lines) — main pipeline orchestrator, carries over prior board, runs dedupe + merge + enrichment + publish
- `workflow_engine.py` (244 lines) — enrichment step sequencing
- `web_artifact.py` (1,630 lines) — publishes compressed board + dashboard to GitHub Pages

**Deduplication & Board Management:**
- `dedupe.py` (187 lines) — fuzzy address matching using rapidfuzz. **JUST PATCHED**: added zip-code and county+state blocking indexes to avoid O(n²) comparisons
- `board_persist.py` (222 lines) — `merge_prior_board()`: loads prior board, merges with fresh scrape, dedupes combined set. **JUST PATCHED**: terminal grace period extended from 45 to 365 days
- `carryover.py` (203 lines) — fills in sources that didn't produce fresh data from prior board

**Valuation:**
- `valuation/calc.py` (2,517 lines) — ARV (After-Repair Value) calculation engine. **5 BUGS FIXED**: (1) garbage comparables not filtered by price band, (2) PPSF ceiling skipped for acreage properties, (3) recorded-ratio comparables ignored, (4) retail list prices used as distressed opening bids, (5) ARV multipliers too aggressive (4.0×/10.0× → 2.5×/3.5×)
- `enrichment_comps.py` (870 lines) — comparable sales analysis. **PATCHED**: Stage 2.5 price-band filter
- `valuation/grading.py` (920 lines) — property condition grading

**Enrichment (144 modules):**
- `enrichment_deed_chain.py` (366 lines) — deed chain analysis
- `enrichment_title_risk.py` (354 lines) — title risk scoring
- `enrichment_lien_stack.py` (101 lines) — lien stacking
- `enrichment_rod_lookup.py` (366 lines) — Register of Deeds lookup
- `enrichment_bankruptcy.py` (252 lines) — bankruptcy matching
- `enrichment_bankruptcy_property.py` (320 lines) — GIS name cross-ref for property
- `enrichment_vision.py` (1,675 lines) — aerial imagery analysis via Gemini
- `enrichment_arcgis.py` (1,241 lines) — ArcGIS attribute enrichment
- `enrichment_gis_attrs.py` (619 lines) — GIS-derived attributes
- `enrichment_equity.py` (608 lines) — equity calculation
- `enrichment_assessor_photo.py` (697 lines) — assessor portal photos
- `enrichment_recorded_sales.py` (834 lines) — recorded sale comparables
- `enrichment_owner_mailing.py` (894 lines) — owner mailing address lookup
- `enrichment_resolve_name_to_property.py` (1,313 lines) — name-to-property resolution
- `enrichment_nc_case_status_tyler.py` (1,159 lines) — NC court case status

**Scrapers (209 modules across 7 categories):**
- `scrapers/counties_nc/` — 43 NC county modules (tax, foreclosure, code violations, ROD)
- `scrapers/counties_sc/` — 56 SC county modules (delinquent tax, FLC, master-in-equity, ROD)
- `scrapers/national/` — 48 national modules (HUD, Fannie, Freddie, USDA, IRS, CourtListener, Zillow, etc.)
- `scrapers/law_firms/` — 14 law firm modules (foreclosure notice publishers)
- `scrapers/newspapers/` — 9 newspaper legal notice modules
- `scrapers/public_notices/` — 5 public notice aggregator modules
- `scrapers/reo/` — 4 REO (Real Estate Owned) modules

**Supporting Infrastructure:**
- `models.py` (351 lines) — data models (Listing dataclass)
- `http_client.py` (480 lines) — HTTP/browser client with WAF bypass
- `parcel_cache.py` (314 lines) — parcel ID caching
- `name_normalize.py` (316 lines) — name normalization for dedup
- `distress_score.py` (521 lines) — 27 distress signal types

---

## My Struggles — Why I Keep Getting Stuck

This is what I need help with. I keep hitting the same patterns of failure, and I need an outside perspective on whether my architecture and process are sound.

### 1. Silent Failure Swallowing (THE BIGGEST PROBLEM)

The single most damaging issue: **critical functions are wrapped in try/except blocks that silently catch errors and continue with degraded output.**

Example from `main.py`:
```python
# Line ~950-953
try:
    merge_prior_board(deduped)
except Exception:
    log.error("board_persist.failed", traceback=traceback.format_exc())
```

When `merge_prior_board()` fails (e.g., timeout on dedup of 116K records), the pipeline **silently continues with only the fresh 22K records instead of the full 94K**. No alert, no halt, no count guard triggers — just 72K records quietly disappear.

**This happened 5 times in a row before I caught it.** Each time I thought the run "succeeded" because it exited 0.

**What I need**: A code audit of ALL try/except blocks in the codebase to find other places where failures are silently swallowed. I need a pattern where critical failures HALT the pipeline, not just log and continue.

### 2. O(n²) Algorithm on Large Datasets

The deduplication function uses rapidfuzz fuzzy matching in a double loop — comparing every record against every other. On 22K records this takes 10-14 minutes and peaks at 4 GB RAM. On 116K records (22K fresh + 94K prior) it's 6.7 billion comparisons and effectively hangs forever.

I just patched it with **blocking indexes** (group by zip code, then by county+state, and only fuzzy-match within blocks). This cut 94K dedupe from "infinite hang" to 168 seconds. But I'm worried about:
- Edge cases where the same property appears with different zip codes (cross-block misses)
- Whether my blocking key choice is optimal
- Whether there are other O(n²) loops hiding in the 144 enrichment modules

**What I need**: An audit of algorithmic complexity across the codebase, especially in record matching, dedup, and enrichment modules. Are there other quadratic loops waiting to blow up as the board grows?

### 3. Memory Pressure on 8 GB RAM

The machine has 8 GB RAM. The board JSON file is 504 MB (94K records). Loading it into Python as a list of dicts uses ~2-3 GB. Running dedupe on it adds another 1-2 GB for the fuzzy matching structures. Running enrichment (especially the vision module that processes aerial images via Gemini API) can spike memory further.

I've had processes peak at 4 GB and get killed by the OS. The current approach of loading the entire board into memory is not sustainable as the board grows.

**What I need**: Recommendations for streaming/chunked processing patterns that work within 8 GB. Should I switch to SQLite for the board? Should I process records in batches? How do I profile and find memory hotspots?

### 4. Virtualenv Management Fragility

The project uses `uv` for dependency management. `uv sync` wants to uninstall 25 packages (easyocr, imageio, etc.) that are needed by enrichment modules but aren't properly declared in `pyproject.toml`. Running `uv run python` triggers `uv sync` automatically, which breaks the venv.

I've been working around this by calling `.venv/bin/python3.12` directly instead of `uv run python`. But this means the run script (`scripts/run_local.sh`) had to be modified.

**What I need**: Help properly structuring `pyproject.toml` so `uv sync` doesn't break things. The 25 "extra" packages need to be declared as optional dependencies or a separate group.

### 5. The Fix-Break-Fix Loop

I keep falling into a pattern:
1. Find a bug (e.g., 22K instead of 94K)
2. Investigate, find root cause
3. Apply a fix
4. Run the pipeline again (5-7 hours)
5. Discover the fix didn't work or introduced a new problem
6. Repeat

Each cycle costs 5-7 hours of pipeline runtime. I've done this 5+ times this week.

**What I need**: A testing strategy that lets me validate fixes WITHOUT running the full 5-7 hour pipeline. Unit tests for critical functions (dedupe, merge_prior_board, ARV calculation). Integration tests with small synthetic datasets. A way to run just the enrichment phase on the existing board without re-scraping.

### 6. Data Quality Verification

After each pipeline run, I need to verify:
- Board count is correct (~94K, not 22K)
- Every source is represented
- No records silently dropped
- ARV values are reasonable (not $1.1M for a $440K property)
- All enrichment fields populated (addresses, owner names, assessed values, etc.)

Currently I do this manually by spot-checking. I've missed problems multiple times because the verification was ad-hoc.

**What I need**: An automated post-run validation suite that checks data quality metrics and flags anomalies. Something like: "ARV/assessed_value ratio > 3.0 → flag for review" or "source X produced 0 records but produced N last time → flag."

---

## What I Need From You (Claude)

1. **Architecture Audit**: Review the pipeline structure. Is the scrape → dedupe → merge → enrich → publish flow sound? Are there better patterns for this kind of record-linkage pipeline?

2. **Silent Failure Audit**: Scan the codebase for try/except blocks that swallow critical errors. Propose a structured error-handling pattern where: (a) critical failures halt the pipeline, (b) non-critical failures log and continue, (c) the distinction is explicit, not implicit.

3. **Algorithmic Complexity Review**: Find all O(n²) or worse loops in the codebase. The dedupe one was obvious, but are there others hiding in the 144 enrichment modules?

4. **Memory Optimization Strategy**: Given 8 GB RAM and a 504 MB board that's growing, what's the right approach? SQLite? Chunked processing? Memory-mapped files? What are the tradeoffs?

5. **Testing Strategy**: How do I build a test suite that catches regressions without running the full pipeline? What should unit tests look like for: dedupe, merge_prior_board, ARV calculation, distress scoring?

6. **Data Validation Framework**: Design a post-run validation suite that checks count integrity, source coverage, field completeness, value reasonableness, and anomaly detection.

7. **Dependency Management**: Help structure `pyproject.toml` properly so `uv sync` doesn't break the venv.

## Environment Details

- **OS**: macOS 26.1 (Darwin)
- **Python**: 3.12.7 in virtualenv at `~/foreclosure-scraper/.venv/`
- **Package Manager**: uv (but `uv sync` breaks things — see above)
- **RAM**: 8 GB (constrained)
- **Disk**: ~6 GB free (constrained)
- **Git**: main branch, pushes to GitHub Pages
- **Dashboard**: Static site published from `docs/` directory
- **Board Storage**: JSON file (`docs/listings.json`, 504 MB, 94K records) + compressed sidecar files

## Key Constraints

- Cannot scale horizontally — single machine, 8 GB RAM
- Pipeline must complete in under 8 hours (currently 5-7 hours)
- Board is growing (~22K → ~54K → ~94K over the past month) — solution must scale
- All data is public records from government sources (county assessor portals, court systems, public notice feeds, government auction sites)
- Output is a static dashboard published to GitHub Pages

## What Would Make the Biggest Impact

If you could only help with ONE thing, it would be the **silent failure audit + structured error handling pattern**. That single issue has caused more wasted time than everything else combined. I spent an entire day running the pipeline 5 times, each time thinking it "succeeded" (exit code 0) when in reality 72K records were silently dropped every time.

---

## UPDATE: Root Causes Found — Two Bugs Behind the 72K-Drop

**Bug 1** (known): `main.py:947-957`. When `merge_prior_board()` throws, the `except` logs and continues — `deduped` stays at the fresh-only 22K, `persist_applied` stays `False`, and the code runs the first-run path as if there were no prior board. It enriches and publishes 22K. Exit 0. The comment literally called it "FALLS BACK to fresh-only" — that fallback IS the bug; losing 72% must halt.

**Bug 2** (the hidden one — why the guard never fired): `web_artifact.py:1451-1466`. The count guard does refuse a >10% shrink, but it compares against the current on-disk board. Once a bad 22K run publishes, the guard's baseline becomes 22K — so the next 22K run looks flat and passes. The guard measures run-over-run drift, not drift from the true high-water mark, so it **structurally cannot catch a drop that already landed**. That's why it ran 5 times "successfully."

### Fixes Applied (3 files, all verified with synthetic tests):

1. **`main.py`** — `merge_prior_board` is now a critical phase: `except` block re-raises instead of log-and-continue. Old "FALLS BACK to fresh-only" comment removed.
2. **`board_persist.py`** — Inner `dedupe_failed` except block also re-raises instead of returning fresh-only. Old `return list(fresh_deduped), stats` fallback removed. Docstring updated.
3. **`web_artifact.py`** — Count guard now reads a persisted high-water mark (`docs/board_highwater.json`) instead of the on-disk board. After a successful write, the high-water mark is updated (only moves UP — a smaller board never lowers it). A poisoned baseline can no longer hide the drop.

### Supporting Data

Census of the codebase: **1,148 `except Exception` blocks, only 126 `raise`** — the whole codebase defaults to best-effort, which is exactly backwards for the 3 phases that matter (merge, dedupe, write_artifact).

### Claude's Priority Recommendations (from audit)

The through-line is one insight: **the board being a single 528 MB in-memory JSON list is the root of problems #1, #3, and #4 at once.** Moving it to SQLite is the structural fix that resolves:
- Memory OOM (no need to load 528 MB into RAM)
- O(n²) enrichers (SQL joins instead of Python loops)
- Validation (cheap SQL queries instead of parsing 528 MB JSON)

**Priority order:**
1. **Critical-phase halt** (DONE — stops the bleeding)
2. **`validate_board.py` push-gate** — automated post-run quality check that blocks git push if board is degraded
3. **`--phase enrich` test mode** — run just enrichment on existing board without re-scraping, turning 5-7h cycles into minutes
4. **SQLite migration** — the structural fix for memory, performance, and validation
5. **`pyproject.toml` fix** — declare 25 "extra" packages properly so `uv sync` doesn't break the venv
