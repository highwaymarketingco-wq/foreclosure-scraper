# Daily vision job repair, 2026-09-21

Scope: the 09:30 job `scripts/run_daily_vision.sh` -> `scripts/patch_vision_gemini.py`, and the
worker pool it drives, `enrich_with_vision()` in `src/foreclosure_scraper/enrichment_vision.py`
(the weekly full run in `main.py` uses the same pool, so it gets the same repair).

Everything below marked "live" was measured on 2026-09-21 between 14:20 and 15:20 EDT through this
repo's own backend classes, with the production prompt and real listing photos from
`docs/parcel_photos`. Nothing here touched the board: no `load_board`, no `write_artifact`, no
publish. Marked "mocked" means an offline test with fake backends or a fake clock.

## 1. Root cause

The pool did not collapse to one worker because of one bug. Seven independent faults stacked up, and
the last healthy lane was too slow to matter.

1. 16 of the 29 configured lanes were dead before the run started, and each one still consumed five
   listings before it retired. GitHub Models (8 lanes) was fully retired by GitHub on 2026-07-30.
   Mistral (4 lanes) answers HTTP 402 "Check your subscription" on every model. Three NVIDIA models
   are end-of-life (HTTP 410, 2026-08-25 and 2026-08-26).
2. Retirement was forever. A backend that looked bad for a few minutes had its worker `return`, and
   nothing ever brought it back. There was no half-open state and no re-admission. So `live_workers`
   only ever went down.
3. Daily-cap 429s were handled like per-minute 429s: ten strikes with a fixed 70 second cooldown
   is 12 minutes of doing nothing per lane, then retirement. That is what happened to all nine
   Gemini keys (retired 11:03 to 11:11), Cloudflare (11:28) and Groq (11:26).
4. Gemini was using one model. Free-tier quota is per project per model, and `gemini-2.5-flash` is
   capped at 20 requests per day per project (429 body: `GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
   `limit: 20`, measured live). Nine keys on one model is at most 180 calls a day; the pass scored 63
   to 76. The keys are independent projects (verified: some keys answered while others were at their
   daily cap), so this is not a shared quota, it is the same small quota nine times. Every other
   Gemini model has its own bucket and was unused.
5. One sequential worker per lane, 90 second timeouts. The only healthy lane
   (`nvidia:ising-calibration-1.5-31b`) ran one call at a time and timed out 30 times on 9/21 (45
   minutes of idle waiting). It scored 350 of the day's 515.
6. No stop rule. From 11:36 to 14:41 (3 h 05 m) the pool ran on one lane, holding the board lock,
   scoring about 95 an hour. Nothing in the pass looked at `live_workers`.
7. A second silent drain. The worker skipped any row whose photos could not be downloaded
   (`if not payloads: continue`) without counting it, so a network outage popped and dropped the
   whole queue at about 100 rows a second and the pass "finished" with nothing left. Evidence:
   the 9/20 log's last heartbeat (13:16:04) shows `queue=4406`, and 45 seconds later `vision.done`
   reports `unscored_remaining=0` with no `listing_given_up` events; the same log has `ConnectError`
   on two lanes, and the ops audit records a `Could not resolve host` push failure from that run at
   13:21. The 9/14 pass shows the same signature: 4,472 targets, queue 4,377 to 2,725 in one minute
   on only 36 more attempts, 0 give-up events, 54 scored, done in 16 minutes. The 9/14 cause of the
   unfetchable photos is not determined (dead URLs or network); the drain mechanism is.

Also found: nothing ordered targets by HOT or WARM, and rows with only a basemap image were sent to a
model that can only return a null tier.

The memory note "Vision pool repair DONE" (dead NIM models fixed earlier) is stale: that fix held
for one month and the pool decayed again on 08/25 to 08/26 and 07/30.

## 2. Per-backend health, from the logs

Source: `logs/daily-vision-20260914..20260921*.log` (9/15, 9/16, 9/18 are full-run days and skip;
9/19 has no log). "Scored" is `by_backend` from each `vision.done` line.

| Lane (as configured) | 9/14 | 9/17 | 9/20 | 9/21 | Error class on 9/21 | Verdict |
|---|---|---|---|---|---|---|
| gemini#1..9, model gemini-2.5-flash | 15 | 64 | 76 | 63 | 429 daily cap (20 per project) then 10 x 70s cooldown, retired 11:03-11:11; 51 x 503 "high demand" | Quota bound, one model only |
| github:* (8 lanes) | 0 | 0 | 0 | 0 | 410 x5 each, retired within 90 s ("retirement brownout") | Dead. Service retired 2026-07-30 |
| mistral:* (4 lanes) | 0 | 0 | 0 | 0 | 402 x5 each, retired within 2 s | Dead. No active subscription |
| nvidia:nemotron-nano-12b-v2-vl | 0 | 0 | 0 | 0 | 410 x5 (EOL 2026-08-26) | Dead |
| nvidia:inkling | 0 | 0 | 0 | 0 | 410 x5 (EOL 2026-08-25) | Dead |
| nvidia:llama-3.1-nemotron-nano-vl-8b | 0 | 0 | 0 | 0 | 410 x5 (EOL 2026-08-26) | Dead |
| nvidia:llama-3.2-90b-vision | 0 | 4 | 0 | 0 | 5 x timeout at 90 s, retired 10:49 | Too slow (60-93 s) |
| nvidia:nemotron-3-nano-omni | 3 | 37 | 2 | 8 | 25 x 503 "Worker local total request limit reached (16/16)", retired 10:56 | Works when the host has capacity |
| nvidia:ising-calibration-1.5-31b | 17 | 426 | 340 | 350 | 30 x timeout (90 s each), never retired | The workhorse, one call at a time |
| groq (qwen/qwen3.8-27b) | 1 | 28 | 32 | 16 | 10 x 429, retired 11:26 | Daily token cap, see section 3 |
| cloudflare (mistral-small-3.1-24b) | 18 | 200 | 185 | 78 | 10 x 429, retired 11:28 | Daily 10,000 neuron cap |
| **Total scored** | **54** | **759** | **635** | **515** | | |

Pool size over time on 9/21: `live_workers` 20 at 10:42, 12 at 11:00, 3 at 11:18, 1 from 11:36 to
14:41. 186 `vision.api_error` warnings and 132 `vision.backend_cooldown` sleeps (70 s each). Run time
4 h 00 m on 9/21, 3 h 12 m on 9/20, 4 h 00 m on 9/17. The 9/14 run ended at 16 minutes because the
queue was emptied by photo-fetch skips (item 7 above), not by scoring.

## 3. What is alive today (live, 2026-09-21)

Production prompt, real listing photos (photo A a maintained bungalow, photo B a cluttered
brick ranch), through `_GeminiBackend` and `_OpenAICompatBackend`. A model counts only if
`_parse_json_response` returned a dict with a real `condition_tier`.

### Gemini (per key, per model; free tier limits read from 429 bodies)

| Model id | Answered | Latency seen | Limits observed | Notes |
|---|---|---|---|---|
| gemini-3.5-flash-lite | yes (cosmetic, MEDIUM) | 0.9 to 3.5 s when the API is quiet; 15 to 35 s and one 60 s timeout in a later loaded window | 15 per minute; no daily 429 after 350 sequential calls on one key (probe stopped there, so the daily limit is above 350) | Best lane. 56 ok of 61 attempts in the live pool run (2 timeouts, one 503, one 504). `gemini-flash-lite-latest` is an alias of it and shares the bucket (the 429 body names `gemini-3.5-flash-lite`), so it is not registered separately |
| gemini-3.1-flash-lite | yes (move_in_ready, HIGH) | 7 to 84 s | 15 per minute; daily limit not reached (63 ok in 75 calls) | Erratic: 31 ok of 57 attempts in the live pool run (503, 504, timeouts) |
| gemini-2.5-flash-lite | yes (cosmetic, HIGH) | 2 to 6 s; 32 s once | 10 per minute, 20 per day per project (measured) | 503 and 504 heavy: 20 ok of 49 attempts in the live pool run |
| gemini-2.5-flash | yes | 1.7 to 26 s | 20 per day per project (measured), 10 per minute | The old default. Tiny quota |
| gemini-3-flash-preview | yes (cosmetic, MEDIUM) | 20 to 26 s | 5 per minute | Slow, low quota, kept last: 16 ok of 43 attempts in the live pool run |
| gemini-3.5-flash | yes | 31 to 38 s, then 503 | 5 per minute | Not registered: 503 "high demand" |
| gemini-3.6-flash, 3.7-flash, 3.8-flash | no | 503 or 60 s timeout | | Not registered |
| gemma-4-26b-a4b-it, gemma-4-31b-it (Gemini API) | no | 9 to 49 s | | HTTP 200 with empty text. Not registered |

Model ids that exist for these keys (41 `generateContent` models listed): the ones above plus image,
tts and pro variants that are not cheap vision graders.

### NVIDIA NIM (one key; 81 models in `GET /v1/models`, 4 of them usable)

| Model id | Answered | Latency | Notes |
|---|---|---|---|
| nvidia/ising-calibration-1.5-31b | yes, both photos (move_in_ready HIGH, major HIGH) | 9.3 to 17.7 s | 6 simultaneous calls: 5 ok, 1 none, no 429. Live pool: 43 ok of 46 attempts in 8.5 min with 3 workers |
| google/gemma-4-31b-it | yes, both photos (cosmetic, major) | 10 to 16 s | New. 6 simultaneous: 5 ok. Live pool: 24 ok of 32 (5 ReadTimeout) |
| meta/muse-glimmer-30b | yes, but "cosmetic" on both photos | 13 to 32 s | New. 6 simultaneous: 6 ok. Live pool: 34 of 34. Weak spread, back of the rotation |
| nvidia/nemotron-3-nano-omni-30b-a3b-reasoning | yes when it has capacity | 3.6 s to 503 | "Worker local total request limit reached (16/16)". Live pool: 8 ok of 13 |
| meta/llama-3.2-90b-vision-instruct, moonshotai/kimi-k3, z-ai/glm-5.3-flash | no | read timeout at 92 to 93 s | Removed |
| meta/llama-3.2-11b-vision-instruct | answers, null tier | 22 s | Not registered |
| nemotron-3.5-lightning-30b-a3b, poolside/laguna-xs-2.1, z-ai/glm-5.3 | no | 400 or 500 | "multimodal processing is not enabled" |
| moonshotai/kimi-k2.6, google/gemma-3-12b-it, nvidia/cosmos-reason2-8b, nvidia/nemotron-nano-3-30b-a3b | no | 404 | Not entitled to this key |

### Everything else

| Provider | Result |
|---|---|
| Groq `qwen/qwen3.8-27b` | Works (2.4 s, real tier). Limits from headers and a 429 body: 1,000 requests per day, 8,000 tokens per minute, **200,000 tokens per day** (429 said `Limit 200000, Used 199997`, retry in about 18 minutes). At about 5.4k tokens a call that is roughly 37 scored listings a day. Kept, but expect it to contribute little |
| Cloudflare `@cf/mistralai/mistral-small-3.1-24b-instruct` | Answered earlier the same day (78 scored). Now 429 code 4006 "used up your daily free allocation of 10,000 neurons". Resets 00:00 UTC (20:00 EDT), so it is available again at the next 09:30 run |
| GitHub Models | 503 HTML page from `models.github.ai` for both `/catalog/models` and `/inference/chat/completions`. GitHub's changelog: fully retired 2026-07-30. Permanently dead, now off by default |
| Mistral | 402 "Check your subscription" on `ministral-3b-latest` (and the other three, in the pool run). Off by default |
| OpenRouter | Not testable: no `openrouter_api_key.txt` is configured. Free vision models exist behind a free key with no card, so this is the one untried free lane (operator action, not done here) |

## 4. What changed

All in `src/foreclosure_scraper/enrichment_vision.py` unless stated. Line numbers are as of this commit.

| Change | Where |
|---|---|
| Half-open circuit breaker, one per backend, shared by that backend's workers. States closed, open (banned until `reopen_s`, then exactly one probe), disabled. 410/402/401/403/404 and daily 429 disable for the run; per-minute 429 backs off; N consecutive hard failures or 429s ban; a success re-admits. A permanent disable cannot be undone by a late failure from a peer worker | `_LaneHealth`, line 1325 |
| Error classes: `QuotaExhausted` now carries `retry_after` and `daily`; new `BackendDisabled`; `_is_daily_quota`, `_retry_after_seconds`, `_safe_body` (strips the account id NVIDIA echoes in 404 bodies from logs) | lines 935, 954, 979, 985, 1002 |
| 429 back-off: exponential from `VISION_BACKEND_COOLDOWN`, capped at `VISION_BACKEND_MAX_BACKOFF`, +0 to 25% jitter, honours the provider's own retry-after (Gemini "retry in 14.6s", `Retry-After` header) | `_LaneHealth.record_quota` |
| Timeouts: provider call 90 s to `VISION_CALL_TIMEOUT` (60), per-listing 150 s to `VISION_ITEM_TIMEOUT` (90), Gemini gets a per-request http timeout, per-listing attempts capped at `VISION_MAX_ATTEMPTS` (8) instead of `len(backends) + 2` | lines 197, 1088, 1154, 1940 |
| Gemini pool is one lane per (key, model), model order rotated per key, one concurrency gate per key (`VISION_GEMINI_KEY_CONCURRENCY`, 2), lanes paced from each model's free-tier RPM, opening calls staggered | `GEMINI_POOL_MODELS` 132, `GEMINI_MODEL_RPM` 141, `_GeminiBackend` 1088, `_build_backends` 1478 |
| NVIDIA lane list replaced with the four models that answered; concurrent workers per NIM lane (3, omni 1, muse 2) sharing one breaker | `NVIDIA_VISION_MODELS` 881, `NVIDIA_DEFAULT_WORKERS` 898, `_OpenAICompatBackend.workers` 1154 |
| GitHub Models and Mistral no longer registered unless `VISION_ENABLE_GITHUB=1` / `VISION_ENABLE_MISTRAL=1` | lines 1522, 1558 |
| Ordering: photo rows first, then HOT, then WARM, then the rest, then sale date. Rows with no real photo are skipped (`VISION_INCLUDE_NO_PHOTO=1` restores them). The old priority was a nested function; it is now module level and tested | `_distress_tier` 1655, `_vpri` 1663, `enrich_with_vision` 1796 |
| Yield stop (`_YieldMonitor`): live backends at or below 2 for 15 minutes, or fewer than 100 scored per hour over the trailing 15 minutes after a 20 minute warm-up. Graceful: in-flight calls finish, partial progress is kept | `_YieldMonitor` 1691, wired in the watchdog at 2271 and 2283 |
| Wall clock: default 90 minutes via `vision_max_seconds()`; `VISION_MAX_SECONDS=0` is unlimited; unparseable falls back to 90 minutes, never to unlimited. The watchdog cancels workers that ignore the deadline | `vision_max_seconds` 169 |
| Bound on decoded images in RAM (8 GB Mac): `VISION_MAX_INFLIGHT` (24) | line 1967 |
| Photo-fetch outage guard: rows with no downloadable photo are counted (`no_image` in `vision.done`); 20 in a row across the pool pauses workers 15 s, 100 in a row stops the pass with `stop_reason=image_fetch_failing` and keeps the queue for the next run | lines 1962-1965, 2118 |
| Observability: heartbeat now logs `live_workers` (backends able to take work), `banned`, `disabled`, `scored_per_hour`; end-of-run `vision.backend_stats` per backend and `vision.done` gains `stop_reason` and `elapsed_s`; `_LAST_RUN` holds the same for tests | watchdog, `_LAST_RUN` 1768 |
| `scripts/patch_vision_gemini.py`: wall-clock cap from `vision_max_seconds()` (the old `float(env or 14400) + 120` armed a 2 minute kill when the env was `0`); start-up log now says how many un-scored rows have a photo and how many are HOT or WARM; folded in the ops patch (`load_board(..., max_drop_rate=1.0)` in the recovery path, `docs/board.manifest.json` staged with the payload, push deferred to the wrapper or run with retries) | lines 33, 40, 88-90, 160, 187, 279, 286 |
| Two existing test fixtures set `VISION_BACKEND_REOPEN_SECONDS=0` so they keep pinning the legacy retire-for-the-run rule | `tests/test_vision_queue_resilience.py`, `tests/test_vision_flaky_lane_recovery.py` |

The ops agent's yield stop in `patch_vision_gemini.py` was not carried over: this one lives inside
the pool, sees the real lane state, stops gracefully, applies to every caller, and is at least as
strict (same 100 per hour and 15 minute window, same 20 minute warm-up, same
`VISION_YIELD_STOP=0` switch, same env names). The live-workers rule was replaced by the version
here because the old count (unfinished worker tasks) would stay high once banned lanes stop
exiting; this one counts backends that can take work.

## 5. Verified live versus mocked

Live (real endpoints, 2026-09-21):

- Every backend in section 3, one production-prompt call each, on two photos for the finalists.
- The whole repaired pool, 400 synthetic listings (cached photos, 10% HOT, 20% WARM), 511 seconds,
  wall clock 480: 232 scored across 51 lanes. 12 lanes were disabled by daily caps during the run
  (Cloudflare neurons, all nine Gemini 2.5-flash lanes, one 2.5-flash-lite lane, Groq tokens), 11 of
  them on their first or second call. 55 of the 120 HOT and WARM
  rows were scored in that window (the queue order put them first; the rest were still in flight).
- Real Mistral lanes through the pool: each disabled after exactly one call (HTTP 402).
- Real GitHub Models lanes through the pool: five consecutive failures, banned, would be probed
  again in 10 minutes.
- Concurrency: 6 simultaneous calls per NIM lane all answered.

Mocked (offline, `tests/test_vision_pool_repair.py`, 60 tests, plus the 78 existing vision tests):

- Half-open re-admission (unit, fake clock, and inside a pool with a lane that fails twice then
  recovers), one probe per window for a still-dead lane, failed probe re-opens the ban.
- 410/402/401/403/404 disable after one call and the held listing is not lost or charged an attempt;
  a disabled lane is never probed; real response bodies for 410, 402, 404 (account id redacted from
  logs), 429 with `Retry-After`, Gemini per-minute versus per-day 429 bodies.
- 429 back-off is exponential, jittered, capped, honours retry-after; consecutive 429s ban; daily 429
  disables.
- Ordering (HOT, WARM, others, photo before tier, no-photo skipped, cap keeps HOT).
- Yield stop (collapse rule, timer reset on recovery, tiny pools exempt, rate rule after warm-up,
  never on an empty queue, `VISION_YIELD_STOP=0`), wall clock default and override, early exit of
  a collapsed pool and of a low-yield pool.
- A long streak of unfetchable photos stops the pass and keeps the queue; isolated dead URLs are
  just skipped and counted.
- Worker concurrency, shared breaker across workers, Gemini lane construction (rotation, per-key
  gate, pacing, stagger), GitHub and Mistral off by default.

Not exercised live: a banned lane actually coming back after 10 minutes (no live lane tripped
during the 8.5 minute run), and the yield stop on a real collapse. Both are covered by the mocked
tests only.

## 6. Expected scored per hour

Measured, live pool run: 232 scored in 511 s, which extrapolates to about 1,600 an hour. Of those,
120 came from Gemini lanes and 107 from NVIDIA lanes (about 750 an hour from NIM alone). Compare
9/21: 147 scored by 11:00 (19 minutes, about 460 an hour), then about 95 an hour on the lone
ising lane (222 at 11:36, 515 at 14:41).

Do not plan on 1,600. The test used one local photo per listing, so it excluded image download time,
and real listings send up to five photos to the Gemini lanes (more tokens, slower). Gemini lanes
also spend their daily buckets early. A defensible planning range for the 90 minute run is 900 to
1,600 scored (about 600 to 1,000 an hour), against 371 to 759 in four hours before. The NIM lanes
alone clear the 100 an hour yield floor by a factor of seven.

## 7. Exact env defaults

Wrapper (`scripts/run_daily_vision.sh`, already patched by the ops agent) exports
`VISION_MAX_SECONDS=5400`, `VISION_INTER_CALL_DELAY=4`, `VISION_BACKEND_STRIKES=10`,
`VISION_BACKEND_COOLDOWN=70`, `VISION_MAX_LISTINGS=15000`, `VISION_USE_OLLAMA=0`. These agree with
the code defaults below.

| Variable | Default | Meaning |
|---|---|---|
| `VISION_MAX_SECONDS` | 5400 | Wall clock, 0 = unlimited |
| `VISION_YIELD_STOP` | 1 | 0 disables both yield rules |
| `VISION_YIELD_LIVE_MIN` / `VISION_YIELD_LIVE_S` | 2 / 900 | Stop when live backends stay at or below this for this long |
| `VISION_MIN_SCORED_PER_HOUR` / `VISION_YIELD_WINDOW_S` / `VISION_YIELD_WARMUP_S` | 100 / 900 / 1200 | Low-yield rule |
| `VISION_BACKEND_REOPEN_SECONDS` | 600 | Ban length before the half-open probe; 0 = legacy retire for the run |
| `VISION_BACKEND_STRIKES` | 10 | Consecutive 429s that ban a lane |
| `VISION_BACKEND_HARD_FAILS` | 5 | Consecutive timeouts/5xx/parse failures that ban a lane |
| `VISION_BACKEND_COOLDOWN` / `VISION_BACKEND_MAX_BACKOFF` | 70 / 300 | 429 back-off base and cap (seconds) |
| `VISION_CALL_TIMEOUT` / `VISION_ITEM_TIMEOUT` | 60 / 90 | Provider call and per-listing timeouts |
| `VISION_MAX_ATTEMPTS` / `VISION_MAX_REQUEUE` | 8 / 2 | Per-listing attempt cap and same-lane retries |
| `VISION_MAX_INFLIGHT` | 24 | Calls in flight at once |
| `VISION_GEMINI_KEY_CONCURRENCY` | 2 | In-flight calls per Gemini key |
| `GEMINI_VISION_MODELS` | `gemini-3.5-flash-lite,gemini-2.5-flash-lite,gemini-3.1-flash-lite,gemini-2.5-flash,gemini-3-flash-preview` | Lane models per key |
| `NVIDIA_VISION_MODELS` | ising-calibration-1.5-31b, gemma-4-31b-it, muse-glimmer-30b, nemotron-3-nano-omni | NIM lanes |
| `VISION_NIM_WORKERS` | 3 | Workers per NIM lane (omni 1, muse 2) |
| `VISION_START_STAGGER_S` | 1.5 | Gap between opening calls |
| `VISION_INCLUDE_NO_PHOTO` | 0 | 1 also sends basemap-only rows |
| `VISION_ENABLE_GITHUB` / `VISION_ENABLE_MISTRAL` | off | Re-enable the two dead providers |
| `VISION_FETCH_PAUSE_AFTER` / `VISION_FETCH_PAUSE_S` / `VISION_FETCH_STOP_AFTER` | 20 / 15 / 100 | Consecutive photo-fetch failures that pause, then stop the pass |
| `VISION_STALL_SECONDS` / `VISION_HEARTBEAT_SECONDS` / `VISION_STOP_GRACE_SECONDS` | 360 / 60 / 30 | Unchanged stall abort, heartbeat and stop grace |

## 8. Not done, and what to watch

- OpenRouter: needs a free key from the operator. It is the only free vision provider not in the
  pool. Drop the key in `.secrets/openrouter_api_key.txt` (the wrapper already loads it).
- Mistral needs an active subscription to come back; GitHub Models is gone for good.
- Groq and Cloudflare are capped by daily token and neuron budgets, not by anything a code change
  can lift (about 37 and about 200 scored a day).
- `enrichment_doc_ocr.py` defaults its model to `GEMINI_VISION_MODEL` (`gemini-2.5-flash`, 20 per
  day per project). It shares the constant, so it has the same tiny quota. Not changed here.
- After the first repaired run, read `vision.backend_stats` and `vision.done` (`stop_reason`) in the
  log. A `stop_reason` of `wall_clock` with a healthy `scored_per_hour` is the good case.
- `run_daily_vision.sh` still says 4 hours in one old comment; the export is correct (5400).
