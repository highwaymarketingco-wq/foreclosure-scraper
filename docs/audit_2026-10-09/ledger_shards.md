# Audit 2026-10-09: ledger_shards

The per-signal verification ledgers (`docs/handoff/verification/<signal>.json`) were one file
each, rewritten whole on every save. `tax_lien.json` grew from 0.7 MB (10/7) to 23.5 MB (10/8
evening, 15,000+ entries) and is headed past the repo's 95 MiB commit gate. This change lets a
ledger live as a directory of shards, keeps reading the single file, and adds the migration.

## 1. What was measured and how

All on copies in a scratch directory. The live ledger was only read: copied twice, and once
checked read-only by the new audit check.

| copy | single file | entries | layout after migration |
| --- | --- | --- | --- |
| 18:27 | 23,236,097 bytes | 15,130 | 16 buckets, 16 shards: min 1,363,573 / median 1,463,383 / max 1,516,109 bytes, manifest 4,685 bytes |
| 18:29 | 23,265,657 bytes | 15,149 | 16 shards, max 1,519,112 bytes |

- **Round trip.** All 15,130 entry lines on disk in the shards are byte-identical to the single
  file's lines. The parsed rows are equal, and so are `generated_at` and `last_run`.
- **Speed.** The migration took 0.7 s. A strict load of the shards takes 0.2 s.
- **A re-check of one entry** rewrote one shard (1,452,479 bytes) and left the other 15
  untouched (same inode and mtime). The save took 0.3 s.
- **`scripts/ledger_migrate.py` peak RSS:** 217 MB for the dry run, 307 MB for `--apply`.
- **Projection (arithmetic, not measured).** The largest shard is 1.04 times the mean. At that
  ratio, 16 buckets stay under the 8 MiB cap until about 123 MiB in total, past the projected
  full coverage of about 104 MiB.

## 2. Defects

### L1. A ledger was one file, rewritten whole, with no ceiling
- **Scale:** 1 ledger now (`tax_lien`); the other 8 are under 0.3 MB.
- **Cause:** `Ledger.save` wrote every entry into `<signal>.json`.

**The new layout** (`src/foreclosure_scraper/verification/ledger.py`, LAYOUTS):
- `<signal>/manifest.json` holds the old header fields plus `version`, `buckets`, the hash rule
  and one entry per shard (file, bucket, rows, bytes, sha256).
- `<signal>/NNN.json` is plain JSON in the single file's own line layout.
- An entry's shard is `sha256(entry key)[:8] mod buckets`.
- `buckets` is a power of two sized for about 2 MiB per shard. It doubles (every bucket splits in
  two) before any shard passes 8 MiB.
- Only shards whose bytes changed are rewritten. Each one goes through a temp file and a rename,
  and the manifest is written last.

**Reading:**
- `Ledger.load` reads either layout. When both exist it merges them with the existing merge
  rules: newer `checked_at` wins, keys are unioned, address-scoped entries stay separate.
- `load_all` does the same, so `apply` and `gap_matrix` get it too.

**Writing:**
- A save keeps the layout the ledger was loaded in, and a new ledger is written as shards.
- A single file that would pass 48 MiB is written as shards.
- The other layout is removed only after it has been merged in. An unreadable copy is never
  removed.

**Integrity:**
- These count as integrity problems: a shard whose sha256 differs from the manifest, an unlisted
  shard, a key in two shards, and a missing or unreadable shard.
- Writers refuse such a ledger.
- Read-only callers load what they can and report the rest.
- A partly read ledger refuses to save.

**Git hand-off:** `publish_ledgers` and the new `commit_ledgers` stage both layouts' paths,
deletions included. They never stage a temp file and never use a directory pathspec.

**Readers updated:** `scripts/gap_matrix.py` (load_ledger_index), `scripts/prerun_gate.py`
(check_ledgers ages) and `scripts/quiet_title_layups.py`. The sweep, recheck, case-scope
migration and human lane already go through `Ledger.load`/`save`/`publish_ledgers`.

**Migration:** `scripts/ledger_migrate.py`. It runs as a dry run by default; `--apply` converts
the ledgers, `--commit` makes a local pathspec commit. It is idempotent and takes the sweep's
run lock.

**Tests:** `tests/test_verification_ledger_shards.py` (15 tests, made-up rows). They cover:
- the round trip and new ledgers written as shards
- the single-file fallback and the 48 MiB switch
- mixed layouts
- never removing an unmerged or unreadable file
- two writers through the sweep's `_save`, including address scoping
- one re-check rewriting one shard
- the 8 MiB cap and bucket splitting
- hash mismatch and unlisted-shard detection
- partial reads
- the publish commit (shards plus the removed file, nothing else)
- the readers
- the audit check
- the migration: dry run, lock, byte-identical apply, idempotent, re-seal

Two existing assertions changed because a new ledger is now a shard directory. The `gap_matrix`
fixture gained `"kind"`. 597 tests in 23 related files pass.

**Invariant:** `ledger-layout` (`scripts/audit_checks/ledger_shards.py`) fails on:
- a single file over 48 MiB
- a shard over 8 MiB
- a sha256 mismatch
- an unlisted or missing shard
- a shard directory without a manifest

A single file between 8 and 48 MiB is reported as advice. On the live directory today it is OK,
with the advice to migrate `tax_lien`.

## 3. Open items
- **Migration not run on the live ledger.** A sweep is writing it. Once the sweep has stopped
  and committed:
  1. `uv run python scripts/ledger_migrate.py` (dry run)
  2. `uv run python scripts/ledger_migrate.py --apply --commit`
- **Version skew.** A VM checkout older than this code reads only `*.json` and would miss a
  sharded ledger. The VM checks out code and data at one commit, and the migration commit comes
  after the code commit, so this only matters for a pin set before the code.
- **A full sweep still changes every shard.** The rows it checks hash across all buckets. The
  saving is per re-check, plus smaller blobs. Git pack growth was not measured.
- **`scripts/ledger_stats` does not exist.** Grep found no such script.
- **Not affected:** `compare_boards`, `carry_publish_state`, the publish scripts and the other
  audit checks read `raw.verification` on the board, not the ledger files.

## 4. Outside this area
- The running sweep's final `publish_ledgers` (the old code in memory) runs `git push origin main`.
  That push will carry every local commit on `main`, these included.
- The sweep's `_save` re-reads the whole ledger from disk every 10 rows. This predates the
  change; at today's size it costs 0.2 s per save.
