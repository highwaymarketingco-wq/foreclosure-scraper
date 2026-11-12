# Restoring the board and the local-only state

Written 2026-09-21 (audit O5). Before this there was no written procedure. The board survives a lost disk (every published board is a commit on GitHub); the databases, CRM state, keys and schedules do not, unless they are backed up.

Two separate things can need restoring:

1. **A bad board**: a wrong write landed, or the payload set is torn or mixed. Restore from git. Section 1.
2. **The Mac itself**: a lost or wiped disk. Restore from a backup plus a fresh clone. Section 2.

## 0. Rules that make a restore safe

- **A board is a set of files that only make sense together.** Index `i` is the join across the board (the parts `docs/listings_part_NNN.json.gz`, formerly one `listings.json.gz`), `listings_detail.json`, `listings_slim.json` and `detail_shards/`. Restoring some of them from one commit and some from another hands one property's comps and vision to another property's address, with no error. Always restore all of them from ONE commit.
- **The plain `docs/listings.json` beats its `.gz` twin (the parts)** in `read_board_json` unless the manifest says otherwise. It is gitignored, so `git checkout <commit> -- docs/` does not replace it. Leaving a newer plain file beside older parts restores nothing. The restore script moves the plain twins away first, and the current board parts too (a commit with four parts restored over a tree with six would leave two strays the manifest does not list).
- **Nothing may hold the board lock.** `restore_board.sh` refuses (exit 75) while a job holds it and takes the lock itself for the duration. If a job is running, wait for it; do not remove the lock by hand unless the holder is dead (`cat logs/.board.lock/pid`, `ps -p <pid>`).
- **Restore first, publish later.** The script changes the working tree only. It stages, commits and pushes nothing.

## 1. Restoring a bad board from git

```sh
cd ~/foreclosure-scraper
scripts/restore_board.sh --list 20          # last 20 commits that touched the board, with sizes
scripts/restore_board.sh <commit>           # asks you to type RESTORE
scripts/restore_board.sh <commit> --yes     # no prompt (for scripts)
```

Pick the newest commit **before** the bad write. The `--list` output shows each commit's subject (`daily vision: 635 listings scored`, `Scheduled SOS pass`, and so on) and the size of the board files (the sum of the parts, with the part count, or the single `listings.json.gz` for a commit from before the payload split); a sudden drop in size or row count is the tell. A commit from before the split restores the single file and removes the parts; a commit after it restores exactly that commit's parts.

What the script does, in order:

1. Refuses while any board writer holds the lock; otherwise holds it for the whole restore.
2. Moves `docs/listings.json`, `listings_detail.json`, `listings_slim.json`, every `docs/listings_part_NNN.json.gz` and `docs/detail_shards/` into `backups/pre-restore-<stamp>/` (a rename, not a delete) and copies the current `.gz` twins and manifest there too.
3. Restores from that one commit: the board parts (or the single `listings.json.gz` for a pre-split commit), the two other `.gz` twins, the whole `detail_shards/` directory, `run_meta.json`, `run_health.json` and `board.manifest.json` (when the commit has them).
4. Prints the sha256 of each restored file and checks the manifest that came with the commit: `MATCHES`, `MISMATCH`, or `no manifest in this commit` (commits before 2026-09-21 have none).
5. Warns if the restored board is more than 10% below `docs/board_highwater.json`.

### After the script

```sh
.venv/bin/python scripts/board_manifest.py --verify     # hashes every file against the manifest
```

- **`MATCHES` and `--verify` ok:** the set is consistent. Continue.
- **`no manifest`:** the commit predates the manifest. Loading works with the legacy checks. Seal it once you have looked at it: `.venv/bin/python scripts/board_manifest.py --rebuild`.
- **`MISMATCH`:** the manifest committed with that commit disagrees with its own files, which means a publisher staged the payload without the manifest. The files are likely fine; check with `--verify`, then `--rebuild`. (`BOARD_MANIFEST_SKIP=1` loads without checking.)
- **The count guard will refuse the next write** if the restored board is more than 10% below the high-water mark (`docs/board_highwater.json`, 175,941 on 2026-09-15). Run the next writer once with `BOARD_ALLOW_SHRINK=1`, or lower the mark by editing that file.

### Publishing the restored board

Deliberate and separate. Under the lock, stage with the shared payload list so the manifest goes too:

```sh
scripts/with_board_lock.sh restore_publish -- sh -c '. scripts/board_payload.sh && board_payload_add "$PWD" && git commit -m "Restore board to <commit>" && echo committed'
git push origin main            # outside the lock; the publish helper's timeout and retries are in scripts/publish_helper.sh
```

Restoring the board on GitHub itself is just this commit: the site serves whatever `main` holds.

### The rolling local backups

`backups/` keeps the last three pre-write copies of `listings*.json` (and `backups/pre-restore-*` from this script). They are a convenience, not a plan: after a busy day they all span about 90 minutes. Use git for anything older.

### If git itself is the problem

`git fsck` first. Loose objects (the local `.git` was 18 GB on 2026-09-21, 13.7 GB of it loose) are not corruption; `git gc` repacks them and touches no history. A fresh `git clone` of the GitHub repo gives every committed board; only the local-only files below are missing.

## 2. Restoring the Mac

What exists only on this Mac, and where the nightly backup puts it (`scripts/backup_local_state.sh`, default `~/Documents/foreclosure-backups/<YYYYmmdd-HHMMSS>/`, newest 7 kept, unchanged files hard-linked):

| What | In the snapshot | Notes |
|---|---|---|
| `data/sc_parcel_mailing.db`, `sc_footprints.db` (2.5 GB), `parcel_inventory.db`, `sc_cama.db` | `data/...` | SQLite files are copied with `sqlite3 .backup` (consistent) |
| `data/notice_pdfs/`, `data/ncvoter/` | `data/...` | |
| `data/checkpoint/board.json.gz` | `data/checkpoint/` | last full-run checkpoint |
| `docs/crm.json` | `docs/` | CRM state for 18,280 leads; not in git |
| harvest outputs and event log | `logs/*.json`, `logs/*.jsonl` | the qPayBill harvest files are here |
| launchd plists | `LaunchAgents/` | also recorded verbatim in `deploy/mac/installed-2026-09-21/` |
| `.secrets/`, `.env` | `secrets.tar.gz.enc` | encrypted, see below; never plaintext |

The default destination is on the same disk as the data. It covers a deleted or corrupted file, not a dead SSD. To survive the disk, run the backup with `BACKUP_DEST` pointing at an external drive or a synced folder, or copy the newest snapshot there.

Order of a rebuild on a new Mac:

1. Install `uv`, `git`, the GitHub CLI; `git clone` the repo; `uv sync --frozen --inexact` (add `--extra ocr` if the `pyproject.toml` patch was applied and you use OCR).
2. Copy the newest snapshot's `data/`, `docs/crm.json` and `logs/*.json*` into place.
3. Restore the secrets (below).
4. `scripts/install_launchd.sh` (a dry run that prints what it would install), then `--apply`. The templates are in `deploy/mac/`; the five originals are in `deploy/mac/installed-2026-09-21/`.
5. Re-create the keychain item for the backup passphrase (section 3) so the nightly backup can encrypt again.
6. `.venv/bin/python scripts/board_manifest.py --verify`.

## 3. The secrets archive

`secrets.tar.gz.enc` holds `.secrets/` and `.env`, encrypted with `openssl enc -aes-256-cbc -pbkdf2 -iter 200000`. The passphrase lives only in the macOS keychain, item **service `foreclosure-backup-passphrase`, account = your login name**. It is never read from a file or an argument, and never logged.

Create the item once, typing the passphrase yourself:

```sh
security add-generic-password -a "$USER" -s foreclosure-backup-passphrase -w
```

Restore (from inside the repo, with the snapshot path filled in):

```sh
security find-generic-password -a "$USER" -s foreclosure-backup-passphrase -w \
  | { read -r p; openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass fd:3 3<<<"$p" \
      -in ~/Documents/foreclosure-backups/<stamp>/secrets.tar.gz.enc | tar xzf -; }
```

**Keep the passphrase somewhere that survives the Mac** (a password manager). The keychain lives on the same disk as everything else: if the disk dies, the archive is unreadable without a copy of the passphrase. If the keychain item is missing when the backup runs, the secrets are simply not backed up and the job's event says `secrets=no_passphrase`.

Keys that were exposed or that you cannot recover are cheaper to re-issue than to hunt for; the audit lists the services (Gemini, Anthropic, Google service account, Gmail app password, Groq, NVIDIA, Cloudflare).

## 4. Failure cases

| Symptom | Cause | Do |
|---|---|---|
| `REFUSING to restore: board-writer active (...)` | A job holds the lock | Wait, or confirm the holder is dead and remove `logs/.board.lock` |
| `BoardIntegrityError: ... does not match board.manifest.json` on load | A torn or mixed payload set, or a stale manifest | `scripts/board_manifest.py --verify` to see which file; restore from a commit, or `--rebuild` if you have checked the files |
| The dashboard shows the old board after a restore | The commit is not pushed, or Pages has not deployed | `git status -sb`, then `gh run list --workflow=pages.yml --limit 3` |
| `COUNT GUARD` refuses the next write | Restored board is over 10% below the high-water mark | `BOARD_ALLOW_SHRINK=1` once, or edit `docs/board_highwater.json` |
| A phone shows one lead's comps under another's address | Payload files from two commits | Restore again from ONE commit; the script removes the stray shards for you |
| `cp -c` or hard links fail on an external drive | Backup destination is a different filesystem | The backup falls back to copying; it just costs more disk |

## 5. Rehearsal

Run a restore on a scratch clone before you need one:

```sh
git clone https://github.com/highwaymarketingco-wq/foreclosure-scraper /tmp/restore-drill && cd /tmp/restore-drill
scripts/restore_board.sh --list 5
scripts/restore_board.sh <a recent commit> --yes
.venv/bin/python scripts/board_manifest.py --verify   # needs a venv; or read the sha256 lines the script prints
```

`tests/test_ops_shell.py` rehearses the same steps on a synthetic repo every time it runs. Nobody has yet run it against the real 12.7 GiB history; the first real drill is worth doing on a scratch clone, not the live tree.
