# Silent-failure sweep — 2026-10-14

Triggered by two accidental discoveries earlier the same day (commit `34f70cdb`):
`nc_metro_demolition_permits`'s Mecklenburg feed was hitting a dead, post-migration
endpoint and silently returning zero; `nc_civicplus_tax_sale`'s `ADDR_RE` was silently
dropping any address with an apostrophe ("Grace's Farm Rd"). Both are the same failure
shape: the scraper runs, logs no loud error, and just produces less (or zero) real data
than it should — indefinitely, until someone happens to look. This pass went looking for
more of that shape across the fleet, data-driven first, then live-verified every
candidate rather than assuming.

## Method

1. Read `docs/run_meta.json` (run_time 2026-10-12, but that run was a checkpoint
   **resume** with `scrapers=0` — no scraper actually executed; it carried health/errors
   forward from the real full run saved 2026-10-07T12:02:12Z) and `docs/run_health.json`
   (`generated_at` 2026-10-07T17:09Z, the last run that actually executed every scraper).
2. Cross-referenced `run_health.json`'s `source_alarms` (`kind: "dead"` = zero output for
   2+ consecutive runs against a nonzero baseline) against `errors` (a flat list of source
   names that threw). **Zero overlap** — all 46 "dead" alarms are genuinely silent: no
   exception, just nothing produced. Separately cross-referenced `run_meta.json`'s
   `source_last_success` map: 44 sources are stuck at `2026-09-23T08:47:09Z` (3 weeks
   stale) while 120 others advanced to the 2026-10-07 run, narrowing the "still broken
   today" candidates from the stale alarm list.
3. Regenerated `docs/SOURCE_REGISTER.md` (`uv run python scripts/gen_source_register.py`)
   for a **live, today** read of registered-but-zero-on-board sources (152 of them) to
   catch anything `run_health.json`'s Oct-7 snapshot wouldn't show.
4. For every flagged candidate: live-verified with plain httpx first (per the Mecklenburg/
   apostrophe convention), then, where that wasn't conclusive, called the scraper's own
   real code path directly (`scripts/smoke_one_scraper.py <slug>`, or a direct call to the
   vendor-adapter function) to get real, current counts — never assumed from a stale
   alarm or a commit message alone.
5. Kept resource use light throughout (8GB Mac, told to be the only background agent):
   plain httpx/direct-function calls wherever possible, no stealth-browser or CAPTCHA-
   solving code run or touched.

## The big finding: most of the stale "dead" list is already fixed

Checking git history against the Oct-7 alarm snapshot, nearly every one of the 46 "dead"
sources had a dated fix commit from **after** 2026-10-07 directly targeting its zero-row
cause (timeout bumps, site-redesign re-parses, pagination fixes). This matches the user's
own tracked history of an active ~2-week remediation wave. Live-verifying rather than
trusting the stale snapshot was essential — most of this list is noise today.

**Confirmed-fine, live-tested, working right now** (no action needed):

| Source | Live result | Why the Oct-7 alarm was stale |
|---|---|---|
| `national.hud_homestore` | 36 rows (NC 21 + SC 15) | `timeout_s` raised 60→150s on 2026-10-08; broker-page fetches now finish inside budget |
| `national.freddie_homesteps` | 26 rows (NC 12 + SC 14) | same timeout fix, 2026-10-08 |
| `national.cash_buyer_deeds` | 129 rows (Buncombe/Aumentum) | `self.partial` fix 2026-10-08 ships completed counties even if later ones in the 10-county sweep hang (see below for the 2 vendor-level issues this run also surfaced) |
| `counties_sc.sc_des_brownfields` | 66 rows | fixed 2026-10-04 (per-site document harvest) |
| `law_firms.finkel` | 8 rows | fixed 2026-10-04 (opening-bid mislabel) |
| `counties_nc.nc_county_tax_foreclosure` | 90 rows | Rutherford Kania track wired 2026-10-03 |
| `law_firms.ingle_firm` | 1 row | fixed 2026-10-04 (was swallowing a real outage as a clean empty run) |
| `national.tranzon` | 0 rows, but `outcome=ZERO_RESULT` logged with `total=12` fetched, `ncsc=0` after state filter | correctly labeled — real zero NC/SC inventory today, not silent |
| `newspapers.carolina_coast` | 0 rows, `outcome=BLOCKED` (HTTP 429) | already correctly instrumented — visibly blocked, not silently empty |
| `counties_sc.dillon_sheriff` | 0 rows, `outcome=ZERO_RESULT` | already correctly instrumented (2026-09-10 audit) |
| `counties_nc.mecklenburg_tax_foreclosures` | **616 rows**, live | built 2026-10-07 **after** the Oct-7 health snapshot was generated — has never had a chance to run in a full pipeline pass yet (notes confirm no full run since). Working, just pending its first real inclusion. |
| `public_notices.nc_heir_notices` | 90 leads / 971 notices scanned | same story — board is stale (no full run since Oct 7), not broken |
| `counties_nc.new_hanover_foreclosures` | 1 row live, but its only `sale_date` is 2026-05-22 (5 months stale) | correctly filtered off the active board by date — not a bug |

None of the above needed a code change. They're listed because each was a real candidate
from the data-driven triage that could easily have been mis-reported as "still broken"
without live verification.

## Confirmed real, currently-live findings

### 1. FIXED — `situs_sanity._EMBEDDED_ADDR_RE` apostrophe gap (pipeline-wide, not one source)

Same bug class as `nc_civicplus_tax_sale.ADDR_RE` fixed earlier today, but found in the
**shared** regex `main.run()`'s SITUS SANITY guard imports from `situs_sanity.py` — so the
blast radius is every source's address, not one scraper's rows.

`_EMBEDDED_ADDR_RE` detects a recoverable "`<house#> <name> <road-suffix>`" address
embedded after a junk name/entity prefix (e.g. `"STARRWOOD GOLF CO 139 STARRWOOD DR"`), so
`situs_is_junk()` does NOT null the address. Its middle character class, `[\w .-]`, had no
apostrophe. A name prefix carrying a corporate-form word (LLC/INC/HOLDINGS/...) is
disqualified from the other exemption (`is_road_location`, which also requires *no*
corporate word) and falls to a plain entity-word check — so it depended entirely on
`_EMBEDDED_ADDR_RE` matching to survive.

**Before** (live, reproduced with the actual function):
```
>>> situs_is_junk("RIVERSIDE HOLDINGS LLC 456 GRACE'S FARM RD WAYNE")
True   # WRONGLY nulled — this has a plain, recoverable street address
```
**After:**
```
>>> situs_is_junk("RIVERSIDE HOLDINGS LLC 456 GRACE'S FARM RD WAYNE")
False  # correctly kept
>>> situs_is_junk("RIVERSIDE HOLDINGS LLC 456 Grace’s Farm Rd Wayne")  # curly apostrophe
False
```
Non-apostrophe cases (`situs_is_junk` junk/kept examples already in
`tests/test_situs_sanity_and_terminal.py`, the civicplus `ADDR_RE` suite) are unchanged —
additive only, same convention as the earlier fix today.

**Fix:** `src/foreclosure_scraper/situs_sanity.py` — added `'` and the curly `’` to
`_EMBEDDED_ADDR_RE`'s character class.

Note: `main.py` has a byte-for-byte duplicate of this regex (`_SITUS_EMBEDDED_ADDR_RE`,
lines 1130-1156) that is **dead code** — `main.py` line 1159 re-imports
`situs_is_junk` from `situs_sanity` and rebinds the name at module load, after the local
`def` executes, so the only live code path is the one in `situs_sanity.py`. Left the dead
duplicate alone (out of scope for this pass; not a behavior bug since it's unreachable).

**Tests:** `tests/test_situs_sanity_and_terminal.py` —
`test_name_prefix_with_apostrophe_in_embedded_address_kept` (new), both apostrophe forms,
constructed so the corporate-word path is the only thing that can save it (i.e. it
actually exercises `_EMBEDDED_ADDR_RE`, not a different exemption). Full file: 13/13
passed. Related file `tests/test_drops_lineage.py` (also imports `situs_sanity` indirectly
through `main`): 30/30 passed. `tests/test_nc_civicplus_tax_sale.py` (today's earlier fix,
unaffected): 15/15 passed. Combined: **58 passed**, 0 failed.

### 2. NOT code-fixable — CCHS (Courthouse Computer Systems) vendor-wide WAF block

Live-verified by calling the real adapter directly, `rod.cchs._cchs_fetch()`, against
every CCHS county in the codebase:

```
Burke      -> impersonate got 403 (us5.courthousecomputersystems.com)
Cleveland  -> impersonate got 403 (us5.courthousecomputersystems.com)
Lincoln    -> impersonate got 403 (us4.courthousecomputersystems.com)
Madison    -> impersonate got 403 (us4.courthousecomputersystems.com)
Henderson  -> impersonate got 403 (us4.courthousecomputersystems.com)
```
All 5 counties, both hosts (us4 and us5), both existing fetch tiers (plain httpx escalates
to curl-cffi impersonation on a block status — confirmed in `rod/cchs.py`'s own module
docstring this is the existing, legitimate anti-block tier, not a bypass) — **both now
fail**. The same docstring documents this Cloudflare rule flipping *which single tier* it
blocks between runs (2026-09-20 through 2026-10-02 probes), but always leaving *one* tier
clear. Today, live, **neither** tier clears it. This is a Cloudflare "Just a moment..."
challenge (HTTP 403) — a wall, per this project's own convention (CAPTCHA/login/403 are
walls, not something to bypass) — so no code fix is offered here, consistent with the
2026-10-11 walled-sources audit's own explicit boundary (plumbing fixes yes, solving/
evasion logic no).

**Confirmed impact** (this is a shared vendor adapter, not one scraper):
- `national.cash_buyer_deeds`: 4 of its 10 counties (Henderson/Cleveland/Burke/Lincoln)
  contribute 0 instead of their normal share — the scraper still reports `outcome=OK`
  with the Buncombe-only total (129 rows), with no distinct signal that 4 of 10 vendor
  sweeps were wall-blocked, not empty.
- `counties_nc.nc_rod_substitute_trustee`: also dispatches to CCHS for its footprint
  (confirmed via `grep` on `rod.cchs` usage); same wall applies to its CCHS share.
- `counties_generic.nod_discovery`: also a CCHS consumer; not separately re-verified this
  pass given time budget — flagged in the follow-up queue.

**Follow-up recommendation** (not implemented here): none of the plumbing-fix boundary is
violated by giving CCHS-dependent callers a *visible* `BLOCKED` outcome instead of folding
a vendor-wide wall into a smaller-but-nonzero total — the same fix already applied
elsewhere in this repo for exactly this failure shape (`scraper.ok outcome=BLOCKED`, see
`newspapers.carolina_coast`'s 429 handling). That is a plumbing change (classify the known
403/challenge response), not a solving/evasion change, and would make this show up in
`run_health.json`'s alarms instead of silently discounting 4 of 10 counties. Left as a
recommendation, not made here, to keep this pass's footprint to verification + the one
regex fix.

### 3. NOT code-fixable (no replacement endpoint exists) — Logan "The Lookup" vendor outage

Live-verified all 3 of the codebase's Logan-vendor NC ROD counties:

```
search.transylvaniadeeds.com  -> ReadTimeout (30s, no response)
search.mcdowelldeeds.com      -> HTTP 503 "No server is available to handle this request"
search.mitchelldeeds.com      -> ReadTimeout (30s, no response)
```

Checked for a Mecklenburg-style migration first: McDowell County's own official Register
of Deeds page (`mcdowellnc.gov/departments/register-of-deeds`) still links
`http://search.mcdowelldeeds.com/index.php` as the live tool today — the county has not
moved; this is the vendor's own hosting platform down, not a stale/wrong URL on our side.
No replacement endpoint found for any of the three.

**Confirmed impact:**
- `counties_nc.nc_rod_logan` — the **primary** distress-signal scraper for these 3
  counties. `source_last_success` was 2026-10-07 (last real run), confirming this is a
  **new** regression since then, not a long-standing known gap. Live right now: 0 rows,
  `logan.discover_failed` (Transylvania, 60s timeout) / `logan.no_token` (McDowell, 503 —
  no CSRF token on an error page) warnings logged, but the scraper still finishes and
  reports cleanly with `self.partial` (whatever it banked, here nothing) rather than a
  visible failure.
- `national.cash_buyer_deeds`'s Logan portion (McDowell/Transylvania/Mitchell, 3 of its 10
  counties) — same root cause, same silent zero.

This is an external hosting outage on the vendor's side with no migration path evident,
so no code change is offered. Recommend a retry in a few days (the CCHS docstring shows
this class of block/outage can be intermittent) and, if it persists past a week, treating
it as a genuine coverage gap worth a manual/alternate-source discussion with the owner —
these 3 counties currently have **no other free ROD source** wired in this codebase.

### 4. Confirmed structurally broken, but unverifiable — `counties_nc.nchfa_reo`

Live GET of `https://www.nchfa.com/home-buyers/properties-sale` (confirmed real, 200,
43KB) shows the site has migrated to **Drupal 11** (confirmed via the page's own
`<meta name="Generator">` tag). The scraper's parser looks for `<tr>` table rows or
`.property`/`.listing`/`.card`/`.home` class `<div>`s — **zero** matches for any of those
on the live page (0 `<tr>`, 0 matching divs, 0 `$` signs anywhere in the body). The entire
"Properties for Sale" article body is now just the static description paragraph; whatever
markup used to carry property rows is gone from this template.

Not fixed this pass: the page's own copy says "On rare occasions, a property... falls
into foreclosure" — i.e. this small state program may be **genuinely** empty right now,
not merely unparseable, and there is no live non-empty example to build or verify a new
parser against. Writing new selectors with nothing real to test them on would be guessing,
which the task brief explicitly says not to do. Queued below instead.

## Prioritized follow-up queue (not done this pass)

1. **CCHS `BLOCKED` outcome visibility** (plumbing, not solving) — give
   `cash_buyer_deeds`/`nc_rod_substitute_trustee`/`nod_discovery` a distinct signal when
   every CCHS county in a sweep comes back wall-blocked, instead of folding it into a
   smaller nonzero total. Moderate effort, no CAPTCHA/evasion work.
2. **Logan vendor outage retest** — retry `search.{transylvania,mcdowell,mitchell}deeds.com`
   in a few days; if still down, raise with the owner as a real coverage gap (no free
   alternate ROD source currently wired for these 3 counties).
3. **`counties_nc.nchfa_reo` rewrite** — needs a live non-empty example of the new Drupal
   11 "Properties for Sale" markup to build a real parser against (watch it over the next
   few "twice-monthly" update cycles the page itself describes).
4. **`counties_sc.anderson_sheriff`** — `andersonsheriff.com` DNS resolves
   (192.155.253.203) but refuses the TCP connection on both :80 and :443 (ConnectTimeout,
   confirmed live, both plain curl and httpx). No replacement found (`andersoncountysc.org/sheriff`
   404s). Low baseline (6/run), low priority.
5. **`counties_generic.nod_discovery`** — also a CCHS consumer per the current wall
   (finding #2); not independently re-verified this pass for time-budget reasons.
6. 152 sources currently show zero rows in the freshly regenerated
   `docs/SOURCE_REGISTER.md` (`## 2. Built but producing zero rows`). Most are very likely
   explained by the same "board is stale, no full run since 2026-10-07" effect confirmed
   for `mecklenburg_tax_foreclosures`/`nc_heir_notices` above, not real bugs — but that is
   an inference, not something this pass live-verified for all 152. The next full
   pipeline run (not run this pass, per the standing "VM run only when certain" rule) will
   be a much higher-signal re-triage point than anything achievable by spot-checking
   individual sources against a stale board.

## NEW RAW KEYS TO REGISTER

none — this pass only changed a regex (`situs_sanity._EMBEDDED_ADDR_RE`); no new `raw`
dict keys were introduced anywhere, and `web_artifact.py` was not touched.
