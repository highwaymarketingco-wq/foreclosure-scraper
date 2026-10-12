# Verification handoff plan: this pipeline and the walled-source platform

Written 2026-10-11. Audience: the team running the separate platform the owner has authorized to
check CAPTCHA, Cloudflare and login-protected sources on his behalf. Everything here is concrete:
file paths, field names, and today's real counts.

## (a) The design in one paragraph

There are two engines and one result. This pipeline does the broad collection (about 350,000
listings across NC and SC) and the polite verification: it re-checks each listing's claim (a tax
debt, a court case, a sale) against the claim's own public source, at most one request at a time
per host, and it never gets around a CAPTCHA, a bot check or a login. Whenever a listing's source
is walled, this pipeline records that honestly as a `wall` verdict and moves on. Your platform does
the walled-source collection and the bypass-capable checks. You do not re-scrape broadly: you take
the punch list this pipeline exports (one row per stuck listing, with its parcel id, case number and
address already resolved), check exactly those listings, and write your answers into the SAME
ledger files in the SAME format. The next run of this pipeline attaches your answers to the
listings automatically. One ledger, not two systems.

## (b) The ledger contract (both sides write this)

Source of truth: `src/foreclosure_scraper/verification/ledger.py` and `core.py`. Use that code to
read and write if you can (`Ledger.load(signal, strict=True)`, `Ledger.record(row, result, ...)`,
`Ledger.save()`); it enforces every rule below. If you write the files yourself, follow this
exactly.

### Where

    docs/handoff/verification/<signal>/manifest.json     the commit point for one signal
    docs/handoff/verification/<signal>/NNN.json          shards (000.json, 001.json, ...)
    docs/handoff/verification/<signal>.json              older single-file layout (still read)

One ledger per signal (`tax_lien`, `court_wall`, `divorce`, `lien_registry_wall`, `nc_ecourts_case`,
...). Today every ledger on disk is sharded. The directory can be moved with the environment
variable `VERIFICATION_LEDGER_DIR`.

### Manifest (`manifest.json`)

    {"kind": "verification_ledger_manifest", "version": 1,
     "schema": 1, "signal": "<signal>", "generated_at": "<UTC ISO>", "host": "<writer host>",
     "counts": {"rows", "confirmed", "refuted", "stale", "unconfirmed", "wall"},
     "last_run": {...free-form run notes...},
     "hash": "int.from_bytes(sha256(entry_key.encode('utf-8')).digest()[:8], 'big') % buckets",
     "buckets": <power of two, 1..4096>, "shard_max_bytes": 8388608, "rows": <total entries>,
     "shards": [{"file": "000.json", "bucket": 0, "rows": <n>, "bytes": <n>, "sha256": "<hex>"}, ...]}

An entry lives in the shard numbered `bucket_of(entry_key) = first 8 bytes of sha256(entry_key),
big-endian, mod buckets`. A shard whose sha256 or row count differs from the manifest, a shard the
manifest does not list, or a key in two shards is an integrity error: writers refuse such a ledger.
Write every shard first (temp file + rename), the manifest last.

### Shard (`NNN.json`)

Plain JSON, one entry per line, keys sorted, entries sorted by key:

    {
    "kind": "verification_ledger_shard",
    "signal": "<signal>",
    "bucket": 0,
    "buckets": 1,
    "rows": {
    "<entry key>": {<entry>},
    ...
    }
    }

### Entry key and keys

The key is the listing's PROPERTY identity, strongest first (`core.row_keys()`):

    parcel:<STATE>:<county lowercased>:<parcel id normalized>   e.g. parcel:SC:laurens:9061317047
    addr:<STATE>:<county>:<normalized house-numbered address>   only with a real house number
    case:<STATE>:<county>:<normalized case number>              e.g. case:SC:laurens:2026cp3000782
    row:<32-hex fingerprint>                                    only when none of the above exists

The entry is keyed by the first and stores all of them in `keys`; a listing is matched on any key
exactly one entry claims, never to an entry holding a different parcel. Case-scoped signals
(`bankruptcy_stay`, `jail_booking`) prefix each key with a hashed case id:
`<kind>:<16 hex>@parcel:...`. The punch list gives you `ledger_key` and `row_keys` ready to use, so
you never have to compute a key yourself.

### Entry

    {"keys": ["parcel:...", "addr:...", "case:..."],
     "row": {"state", "county", "parcel_id", "street_address", "listing_type", "source"},
     "latest": {"signal": "<signal>",
                "verdict": "confirmed" | "refuted" | "stale" | "unconfirmed" | "wall",
                "evidence": {...what the source said, structured; "reason" is a short code...},
                "source": "<host or source name>",
                "checked_at": "2026-10-09T01:12:52Z",
                "verifier_version": "<version string>",
                "verifier": "<module or tool name>"},
     "history": [{"verdict", "checked_at", "verifier", "verifier_version"}, ...],   at most 6
     "last_attempt": {"verdict", "checked_at"},
     "checks": <int>, "first_checked_at": "<UTC ISO>",
     "ttl_days": <float>, "governs": ["<scorer signal names>", ...],
     "case": "<case id>"   (case-scoped signals only)}

Verdicts mean exactly this (`core.py`):

- `confirmed`: the source shows the claim is true today.
- `refuted`: the source shows the claim is false, with no sign it was ever true.
- `stale`: the claim WAS true and no longer is (bill paid, case closed).
- `unconfirmed`: checked, the source could not decide. Says nothing about the claim.
- `wall`: cannot be checked by this pipeline's code (CAPTCHA, bot check, login, terms).

Rules every writer must keep:

- Times are UTC ISO with a Z, second precision.
- Never drop an entry. Never put names, phone numbers or notice text in `row` or keys: the ledger is
  published in a public repository. `row` omits `owner_name` (and `street_address` for `court_wall`
  and `lien_registry_wall`).
- A decisive answer (`confirmed`/`refuted`/`stale`) always becomes `latest`, and the old `latest`
  moves to `history`. A non-decisive answer never replaces a decisive `latest` that is still within
  its TTL; it goes to `history` and `last_attempt` only.
- `refuted` and `stale` take the claim out of the listing's score until `checked_at + ttl_days`.
  `governs` names which scorer signals they remove; copy the value already in the entry (or the
  verifier's `GOVERNS`) unless the owner agrees a different one. `confirmed`, `unconfirmed` and
  `wall` change no score.
- For a walled signal (`court_wall`, `divorce`, `lien_registry_wall`) write your verdict into that
  same signal's ledger, on the entry named by `ledger_key`; set `verifier` to your tool's name
  and `verifier_version` to its version, and put what you read in `evidence` (short, structured;
  include `"reason"` and the URL you checked as `"url"`). A verifier name this pipeline does not
  know keeps its `ttl_days` from the entry.

## (c) The punch list

Made by `uv run python scripts/export_wall_punchlist.py` (read-only, no network, about 40 s and
380 MB peak on today's board). Files:

    data/handoff/wall_punchlist.json         JSON array, one object per listing (not in git)
    data/handoff/wall_punchlist.csv          the same rows; list fields joined with "|"
    docs/handoff/wall_punchlist_summary.json counts only, no identities (in git)

Running it twice on the same board and ledgers gives byte-identical files.

Fields:

| field | meaning |
|---|---|
| `category` | `wall` (walled, for you) or `uncovered` (no checker of any kind exists yet; separate, see below) |
| `signal` | the ledger to write your answer into |
| `wall_state` | `recorded` (ledger says `wall`), `unconfirmed_blocked` (ledger says `unconfirmed` and its evidence shows a block: login redirect, HTTP 401/403, a blocked circuit), `not_yet_labelled` (a walled checker covers it; the label is not yet written) |
| `wall_path` | which walled lane it needs, see the table below |
| `wall_reason` | the plain reason the source is walled |
| `verifier` | the checker that labelled it |
| `ledger_key`, `row_keys` | the entry to write; every identity key of the listing |
| `state`, `county`, `parcel_id`, `case_number`, `street_address`, `listing_type` | the listing as resolved |
| `source` | the scraper that produced the listing (tells you which of your tools maps to it) |
| `source_url` | the URL the listing came from; `checked_url` the URL a check used, when recorded |
| `last_attempted_at`, `first_checked_at`, `checks` | when this pipeline last tried (empty for `not_yet_labelled`) |
| `tier` | HOT / WARM / COLD: check HOT first |

The `wall_path` values and what each one needs:

| wall_path | source | what blocks code |
|---|---|---|
| `sc_publicindex` | SC Judicial Public Index (lis pendens, foreclosure, judgment claims outside Charleston) | the site's edge refuses scripts (bot check) |
| `divorce_sc_wall` | SC Public Index divorce cases | terms restrict automated querying |
| `sc_notice_body` | scpublicnotices.com notice bodies | Cloudflare check and a CAPTCHA |
| `nc_sp` | NC eCourts special proceeding (power-of-sale foreclosure) file | picture CAPTCHA before every search |
| `nc_est` | NC eCourts estate file | picture CAPTCHA before every search |
| `liensnc_login` | LiensNC registry | the owner's own login |
| `sc_lien_registries` | SC DEW / SCDOR lien registries | key accepted only from the rendered page |
| `avalon_tax` | Rutherford County NC tax bill search | HTTP 403 to cloud addresses, CAPTCHA in a browser |

A sample row (address left out here; the real file has it):

    {"category": "wall", "signal": "court_wall", "wall_state": "recorded",
     "wall_path": "sc_publicindex",
     "wall_reason": "SC Judicial Public Index: the site's edge refuses scripts (bot check)",
     "verifier": "court_walls", "ledger_key": "parcel:SC:laurens:9061317047",
     "row_keys": ["parcel:SC:laurens:9061317047", "addr:SC:laurens:<address>",
                  "case:SC:laurens:2026cp3000782"],
     "state": "SC", "county": "Laurens", "parcel_id": "9061317047",
     "case_number": "2026-CP-30-00782", "street_address": "<address>",
     "listing_type": "lis_pendens", "source": "counties_sc.sc_public_index",
     "source_url": "https://publicindex.sccourts.org/Laurens/PublicIndex/CaseDetails.aspx?CaseNum=2026-CP-30-00782",
     "checked_url": "", "last_attempted_at": "2026-10-09T01:12:52Z",
     "first_checked_at": "2026-10-09T01:12:52Z", "checks": 1, "tier": "WARM"}

Not in the list: listings a polite checker covers, whether already checked or still waiting their
turn (this pipeline checks those itself), and `unconfirmed` answers caused by a source being briefly
down (HTTP 503, an error page, a timeout). Those retry here after 6 hours; they are not walls.

The `uncovered` category is a build list, not a wall list: no checker of any kind exists yet for
those listings' claims (code-enforcement feeds, contamination registries, open-data lists and
similar). Most are reachable politely; they wait for a checker on this side. Do not treat them as
yours unless the owner says so.

## (d) The cycle

1. This pipeline's sweep runs (`scripts/verification_sweep.py`): every listing it can reach
   politely is checked; walled ones get `wall`.
2. The punch list is exported (`scripts/export_wall_punchlist.py`).
3. Your platform reads `data/handoff/wall_punchlist.json`, checks exactly those listings using the
   resolved parcel / case / address, and writes each answer into
   `docs/handoff/verification/<signal>/` in the format of section (b), as a decisive verdict where
   the source decides it and `unconfirmed` where it does not.
4. The next nightly run attaches your verdicts to the listings automatically
   (`verification.apply.apply_verification`, no change needed on either side); a `refuted` or
   `stale` verdict takes the claim out of the lead's score from that run on.
5. The next export no longer lists a listing that has a decisive verdict. Repeat.

A decisive verdict you write is never overwritten by this pipeline's `wall` label: the ledger keeps
a decisive answer as `latest` until its TTL runs out.

## (e) Today's numbers (board of 350,013 listings, ledgers as of 2026-10-09)

231,920 listings in the export: 72,360 `wall` and 159,560 `uncovered`.

Walled listings by signal:

| signal | listings |
|---|---|
| `lien_registry_wall` | 61,520 |
| `court_wall` | 5,741 |
| `divorce` | 5,099 |

By walled lane:

| wall_path | listings |
|---|---|
| `liensnc_login` | 44,392 |
| `sc_lien_registries` | 8,599 |
| `avalon_tax` | 8,529 |
| `divorce_sc_wall` | 5,099 |
| `sc_publicindex` | 3,506 |
| `nc_est` | 1,965 |
| `nc_sp` | 155 |
| `sc_notice_body` | 115 |

By state of the label: 1,274 `recorded` (the court-wall labels the HOT/WARM sweep wrote on
2026-10-09), 71,086 `not_yet_labelled`, 0 `unconfirmed_blocked` (no polite check was blocked in the
current ledgers; 1,927 tax answers that failed on a 503 or an error page are retries, not walls).

Top counties for walled listings: NC Rutherford 8,803, NC Wake 5,480, NC Mecklenburg 4,679,
SC Spartanburg 3,641, SC Charleston 3,284, NC Brunswick 3,134, SC Horry 1,672, NC Durham 1,635,
SC Pickens 1,456, NC Johnston 1,455 (1,848 NC rows carry no county).

Note on the largest lane: the 44,392 LiensNC rows are "appointments of lien agent" for
construction projects, not tax liens (see `lien_registry_wall.py`). Ask the owner whether they are
worth checking at all before spending effort there.

## (f) What this pipeline will and will not do

It will NOT: fetch a walled site, solve or get around a CAPTCHA, a bot check or a Cloudflare
challenge, sign in anywhere, or run any bypass code (existing or new).

It WILL: run its polite sweep, export the precise per-listing punch list above, read the ledgers
your platform writes and apply those verdicts automatically on the next run, and re-export on
request, or on a schedule once this cycle has been proven out end to end.

## (g) How the broad walled-source collection wires into the standing pipeline and runs automatically

Today the broad walled collection is `scripts/run_walled_sources.py` (37 walled sources, one JSON
file per source in `data/walled_output/`). It belongs to the other platform: this pipeline does not
change, extend or run its CAPTCHA / WAF code. Once the other platform confirms its 5 open fixes are
done and the script is safe to run unattended (idempotent, resumable, bounded memory, never writes
the board), it becomes an optional phase exactly like every other optional enricher:

1. **A flag, off by default.** `FORECLOSURE_WALLED_BROAD` (default `0`; explicit opt-in, the same
   convention as the other browser-heavy flags in `deploy/oracle/run_profile.json`, e.g.
   `FORECLOSURE_NC_HARRIS_ROD: "0"`), and a budget `FORECLOSURE_WALLED_BROAD_BUDGET_S` (suggested
   `3600`). Both get declared in `deploy/oracle/run_profile.json` in the same commit that exports
   them from `deploy/oracle/vm_lib.sh` (the pre-run gate fails otherwise). Note the role: the
   walled sources answer 403 to the cloud VM's address (see `avalon_tax` above), so the flag is
   meant for the Mac role; leave it `0` in the VM profile unless the owner decides otherwise.
2. **A wrapper, never an import.** This pipeline only ever calls a small wrapper module
   (`src/foreclosure_scraper/enrichment_walled_broad.py`, to be added with the wiring) whose
   `async def enrich_walled_broad(listings) -> dict` returns `{"skipped": "flag off"}` unless the
   flag is `1`, and otherwise starts `scripts/run_walled_sources.py` as a SEPARATE PROCESS
   (`asyncio.create_subprocess_exec`, its own process group) with the budget passed in, kills the
   process group when the budget plus a 120 s grace runs out, and returns counts read from
   `data/walled_output/_summary.json`. It never imports any of the other platform's modules into
   this process, so no bypass logic ever runs inside this pipeline. Turning its output into board
   listings is a separate, plain ingest step on this side (the same pattern as
   `scripts/ingest_fresh_court_leads.py`): read the JSON files, build listings, let the normal
   dedupe merge them.
3. **The call site.** In `src/foreclosure_scraper/main.py`, inside `run_enrich_tail()`, directly
   above the comment line `# Per-listing verification verdicts (docs/HANDOFF.md item 66). The Mac's`
   (the block that calls `apply_verification(enriched)`), the lead adds:

       try:
           from .enrichment_walled_broad import enrich_walled_broad
           s = await _await_capped(
               enrich_walled_broad(enriched), "walled_broad",
               default_s=int(float(os.environ.get("FORECLOSURE_WALLED_BROAD_BUDGET_S", "3600")) + 180))
           if s and "skipped" not in s: enrichment_stats["walled_broad"] = s
       except Exception:
           log.error("walled_broad.failed", traceback=traceback.format_exc())

   This is the same shape as the `register_lien_sweep` and `county_lien_sweep` calls already in
   `run_enrich_tail()`. Placing it above `apply_verification` means that run's verdicts are applied
   after it.

The owner or the lead applies these lines (same as every other enricher wired this week); this
document does not change `main.py`. Precondition: the other platform's written confirmation that the
5 fixes are in and the script meets the four conditions above.

## (h) Automatic trigger between the verification sweep and the deep-dive

Built on this side (2026-10-11): `scripts/verification_sweep.py` now ends every real run (not
`--dry-run`) by running `scripts/export_wall_punchlist.py --ready-marker` as a separate process,
after the ledgers are saved and published. No manual step: sweep, then a fresh punch list, every
time. `VERIFY_PUNCHLIST_EXPORT=0` turns it off; `VERIFY_PUNCHLIST_TIMEOUT_S` (default 1800) caps it;
a failed export is printed and never fails the sweep. A sweep pointed at a non-default ledger
directory writes its export beside that directory, never over the real files.

The marker the other platform watches:

    data/handoff/wall_punchlist.ready

written atomically (temp file + rename) only after both punch-list files are complete:

    {"kind": "wall_punchlist_ready", "format_version": 1,
     "generated_at": "2026-10-12T00:16:28Z",
     "json": "<abs path>/data/handoff/wall_punchlist.json",
     "csv": "<abs path>/data/handoff/wall_punchlist.csv",
     "punchlist_sha256": "<sha256 of wall_punchlist.json>",
     "listings": 231920, "by_category": {"uncovered": 159560, "wall": 72360},
     "board_rows": 350013}

How to consume it: poll the file (or watch it) for a change; read it; if `punchlist_sha256` equals
the last one you processed, do nothing (same ledger state, same list); otherwise process the JSON it
names, then remember that hash. `generated_at` changes on every sweep; the hash changes only when
the list does.

Building the watcher that launches the deep-dive when a new marker appears is the other platform's
job, on its side. Its results go back into the ledgers (section b), and the next sweep's export
drops every listing they decided.
