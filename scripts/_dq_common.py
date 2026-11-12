"""Shared plumbing for the 2026-09-21 board data-quality fix scripts.

Not a script. Every fix script (fill_address_from_parcel, backfill_missing_county,
quarantine_flip_leaks, promote_ptscloud_block, undo_resolver_middle_conflicts, ...) follows the
same contract, taken from join_parcel_cache_to_board / repair_burke_storm_damage_parcels:

  * the default run is a DRY RUN. It streams docs/listings.json.gz through
    board_stream.iter_board_rows (about 300 MB, seconds), keeps only counters and a few samples,
    and never touches the board.
  * --apply calls run_apply(), below, which takes board_lock, builds a working set of Listing
    objects (see _light_rows()), mutates them FILL-ONLY via the script's own apply_rows(), asserts
    the row count is unchanged, backs up anything it replaced under backups/, and lands the result
    via web_artifact.patch_existing_rows() -- migrated 2026-10-01 off load_board()/write_artifact()
    (docs/HANDOFF.md item 21/22) because that whole-board load+rewrite no longer fits this board's
    size. apply_rows() itself did not change; see run_apply()'s own docstring for what did and
    why two of its ten would-be callers (undo_resolver_middle_conflicts.py,
    repair_parcel_from_address.py) are excluded from this migration.
  * --rows-file PATH replays a saved JSONL extract instead of the live board (dry run only). It is
    how the tests and offline development avoid a second pass over the board.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Iterable, Iterator

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

BACKUPS = REPO / "backups"

#: listing types that are "flips": something you could bid on or buy today (main._FLIP_LISTING_TYPES).
FLIP_TYPES = frozenset({"foreclosure_sale", "auction", "sheriff_sale", "hoa_sale", "reo"})


def norm_county(county) -> str:
    """'Rutherford County' -> 'Rutherford'. Empty for None."""
    return str(county or "").replace(" County", "").replace(" county", "").strip()


def county_in_state(county, state) -> bool:
    """True when (county, state) is a real NC or SC county pair. The parcel caches are keyed by
    county NAME, so this is the guard that stops an NC name on an SC lead reading NC parcels."""
    from foreclosure_scraper.validation import NC_COUNTIES, SC_COUNTIES, normalize_county
    c = norm_county(county)
    if not c or c.lower() == "statewide":
        return False
    c = normalize_county(c)
    st = str(state or "").upper()
    return (c in NC_COUNTIES) if st == "NC" else (c in SC_COUNTIES) if st == "SC" else False


def footprint() -> frozenset[tuple[str, str]]:
    """The 18 flip-footprint counties as (STATE, lowercase name), from config.ALL_COUNTIES."""
    from foreclosure_scraper.config import ALL_COUNTIES
    return frozenset((c.state.upper(), c.name.lower()) for c in ALL_COUNTIES)


def iter_rows(rows_file: str | None = None) -> Iterator[dict]:
    """The live board (constant memory) or a saved JSONL extract."""
    if rows_file:
        with open(rows_file) as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
        return
    from foreclosure_scraper.board_stream import iter_board_rows
    yield from iter_board_rows(REPO / "docs" / "listings.json.gz")


def lt_str(listing_type) -> str:
    """ListingType enum or plain string -> its string value."""
    return str(getattr(listing_type, "value", listing_type) or "")


def missing_raw_keep(keys: Iterable[str]) -> list[str]:
    """Raw keys that write_artifact would silently drop (web_artifact._slim_raw is a TOTAL
    allowlist). An --apply that stamps a key outside it would report success and persist nothing,
    so every apply path calls this first and refuses to run when it is non-empty."""
    from foreclosure_scraper import web_artifact as wa
    out = []
    for k in keys:
        probe = wa._slim_raw({k: {"probe": 1}})
        if k not in probe:
            out.append(k)
    return out


def require_raw_keep(keys: Iterable[str]) -> None:
    miss = missing_raw_keep(keys)
    if miss:
        raise SystemExit(
            "REFUSING TO APPLY: raw key(s) " + ", ".join(repr(k) for k in miss) + " are not in "
            "web_artifact.RAW_KEEP, so write_artifact would drop them silently. Register them "
            "(RAW_KEEP, and _SLIM_RAW / dashboard.js _LEAN_RAW if the dashboard should see them) "
            "first. See docs/data_quality_fixes_2026-09-21.md, section 'RAW_KEEP registrations'.")


def assert_raw_keep(keys: Iterable[str]) -> None:
    """Library-safe form of require_raw_keep: raises RuntimeError (not SystemExit) so a driver that chains
    several apply_rows calls in one process gets a normal exception before any row is touched."""
    miss = missing_raw_keep(keys)
    if miss:
        raise RuntimeError(
            "raw key(s) " + ", ".join(repr(k) for k in miss) + " are not in web_artifact.RAW_KEEP, so "
            "write_artifact would drop them silently. Register them first (docs/data_quality_fixes_2026-09-21.md, "
            "'RAW_KEEP registrations').")


#: raw sub-keys where setting the value to None is PROVEN equivalent to the key being absent --
#: every consumer in src/ + scripts/ + docs/dashboard.js reads it with .get()/isinstance()
#: truthiness, never a bare `"key" in raw` membership test (verified 2026-10-01 by grep; see the
#: migration commit that introduced this set). This is the ONLY form of raw-key removal
#: run_apply() can safely emulate, because patch_existing_rows() merges raw via plain
#: dict.update() -- it can set a key's value, never delete the key outright (see its docstring).
#: quarantine_flip_leaks.py's self-correcting "stamp cleared" undo is the one caller among the
#: ones migrated here that removes a raw key at all, and 'scope' is exactly this verified case
#: (distress_score.OUT_OF_FOOTPRINT is read via `r.get("scope") == ...`, nothing tests presence).
#: Any OTHER raw-key deletion (e.g. undo_resolver_middle_conflicts.py's / repair_parcel_from_
#: address.py's blanking of raw['owner_mailing'], which mailing_shape.py DOES presence-test) is
#: refused loudly below rather than silently emulated -- see run_apply()'s docstring.
_RAW_DELETE_SAFE_AS_NONE = frozenset({"scope"})


def _light_rows(docs: Path) -> list:
    """The board as Listing objects, fully validated exactly like web_artifact.load_board() does
    per row (real enums, real type coercion -- not model_construct()'s raw passthrough, so every
    apply_fn's existing field reads/writes behave identically) but sourced from
    board_stream.iter_board_rows() instead of web_artifact._iter_board_records(): no lazy-detail
    sidecar (vision/comps/cama/foreclosure_sold_comps/rent_comps) is merged into raw.

    That sidecar merge is load_board()'s dominant memory cost (see its own docstring: ~2.8 GB
    peak RSS for 170K rows, WITH the merge) and none of this module's callers read or write a
    LAZY_DETAIL_KEYS field (confirmed by grep across all nine run_apply() callers when this was
    migrated 2026-10-01) -- the gap is safe here. This is still a FULL materialization (every row
    held in memory at once, same as load_board()), just without that one dominant cost; it is not
    constant-memory the way board_stream.iter_board_rows() alone is, and its real peak RSS against
    the current, much-grown board has NOT been measured live (memory conditions at migration time
    -- ~63 MB free, 76% swap used -- matched the same unsafe-to-test regime noted in
    sos_agent_refresh.py's/patch_vision_gemini.py's own 2026-09-30 migration). A supervised live
    dry run (RSS watchdog, BOARD_PATCH_ALLOW_LARGE=1 if needed) is recommended follow-up before
    trusting this at full board size; synthetic-fixture tests only cover correctness, not memory.

    Malformed rows are dropped and counted exactly like load_board(), reusing its own class/
    thresholds, so a run_apply() caller never silently loses rows either."""
    import os as _os
    from foreclosure_scraper import web_artifact as wa
    from foreclosure_scraper.board_stream import iter_board_rows
    from foreclosure_scraper.models import Listing
    out: list = []
    dropped = 0
    total = 0
    for total, rec in enumerate(iter_board_rows(docs / "listings.json.gz"), start=1):
        try:
            out.append(Listing.model_validate(rec))
        except Exception:  # noqa: BLE001 - counted below, same contract as load_board()
            dropped += 1
    rate = (dropped / total) if total else 0.0
    if dropped:
        limit = float(_os.environ.get("BOARD_LOAD_MAX_DROP_RATE", "0.001"))
        if rate > limit and _os.environ.get("BOARD_LOAD_ALLOW_DROPS", "").strip().lower() not in ("1", "true", "yes"):
            raise wa.BoardLoadDropError(
                f"run_apply dropped {dropped:,} of {total:,} rows ({rate:.3%}) building its "
                f"working set, over the {limit:.3%} limit. BOARD_LOAD_ALLOW_DROPS=1 proceeds "
                f"anyway (the dropped rows are simply not candidates for this fix)."
            )
    return out


def _snapshot_rows(rows: list) -> list[tuple]:
    """Pre-mutation snapshot of each row: (dedupe_key() computed BEFORE apply_fn runs -- the
    identity patch_existing_rows() must match on, since a fix may itself rewrite an identity
    field like county/parcel_id/street_address -- a JSON-mode dump of every OTHER top-level
    field, and a deep copy of raw, since several apply_fn's mutate a raw sub-dict in place
    (e.g. map_account_ids_to_parcels.py's `li.raw["qpaybill_roll"][...] = ...`) rather than
    reassigning li.raw itself, which a shallow copy would not catch)."""
    import copy
    out = []
    for li in rows:
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a row too malformed to key is simply unpatchable
            key = None
        scalars = li.model_dump(mode="json", exclude={"raw"})
        raw_copy = copy.deepcopy(li.raw) if isinstance(li.raw, dict) else None
        out.append((key, scalars, raw_copy))
    return out


def _diff_raw(before, after, *, owner: str) -> dict:
    """{raw sub-key: new value} for everything apply_fn changed on one row's raw dict, diffing
    the pre-mutation deep copy against the post-mutation dict. A key apply_fn ADDED or CHANGED is
    carried as its new value (patch_existing_rows() merges this via raw.update()); a key apply_fn
    REMOVED is only representable as an explicit None (there is no delete in that merge), which is
    safe ONLY for _RAW_DELETE_SAFE_AS_NONE -- anything else raises loudly rather than silently
    leaving a stale key (None) or dropping the removal (omitting it) on the written board."""
    before = before or {}
    after = after or {}
    out: dict = {k: v for k, v in after.items() if before.get(k) != v}
    removed = set(before) - set(after)
    unsafe = removed - _RAW_DELETE_SAFE_AS_NONE
    if unsafe:
        raise RuntimeError(
            f"{owner}: apply_fn removed raw key(s) {sorted(unsafe)!r} from a row. The migrated "
            f"run_apply() writes through web_artifact.patch_existing_rows(), which only MERGES "
            f"raw sub-keys (plain dict.update()) and has no delete primitive -- setting the value "
            f"to None instead of removing the key is not safe for an unverified key (at least "
            f"'owner_mailing' is read via a literal `\"owner_mailing\" in raw` presence test in "
            f"src/foreclosure_scraper/mailing_shape.py, which None would not satisfy the same way "
            f"an absent key does). This script needs its own dedicated board_stream/"
            f"patch_existing_rows migration (like sos_agent_refresh.py's), not the shared "
            f"_dq_common.run_apply() helper -- see docs/HANDOFF.md item 21/22."
        )
    for k in removed & _RAW_DELETE_SAFE_AS_NONE:
        out[k] = None
    return out


def _diff_to_patches(rows: list, pre: list[tuple], *, owner: str) -> dict[str, dict]:
    """Build patch_existing_rows()'s `patches` dict from what apply_fn actually changed, by
    comparing each row's post-mutation state against the snapshot _snapshot_rows() took before
    apply_fn ran. Rows apply_fn left untouched (the overwhelming majority -- these are FILL-ONLY
    passes over a ~220K-row board) contribute nothing, so the write is exactly as small as the
    real change, same as every already-migrated run_apply()-style script this week."""
    patches: dict[str, dict] = {}
    for li, (key, before_scalars, before_raw) in zip(rows, pre):
        if key is None:
            continue
        update: dict = {}
        after_scalars = li.model_dump(mode="json", exclude={"raw"})
        for k, v in after_scalars.items():
            if before_scalars.get(k) != v:
                update[k] = v
        raw_update = _diff_raw(before_raw, li.raw if isinstance(li.raw, dict) else None, owner=owner)
        if raw_update:
            update["raw"] = raw_update
        if update:
            patches[key] = update
    return patches


def run_apply(owner: str, apply_fn, required_keys, backup_name: str) -> int:
    """The single-script --apply skeleton, migrated 2026-10-01 off load_board()/write_artifact()
    (see docs/HANDOFF.md item 21/22): preflight, board_lock, build the working set, apply_rows,
    assert the row count, write the backup, land the result via web_artifact.patch_existing_rows()
    instead of a whole-board write_artifact(). `apply_fn(rows, dry_run=False)` is UNCHANGED --
    same list[Listing] in, same in-place FILL-ONLY mutation contract, same counter dict out (which
    may carry a '_backup' payload, popped here and written under backups/) -- only how `rows` is
    built and how the result is written changed.

    WHY THIS WORKS WITHOUT APPLY_FN CHANGING. load_board() was expensive for two separate reasons:
    merging the lazy-detail sidecar into every row's raw (none of this module's apply_fn's touch
    those keys -- _light_rows() drops that merge) and holding a list[Listing] for the whole board
    at once (apply_fn's that build a board-wide index, e.g. backfill_missing_county.build_evidence()
    scanning `rows` for already-known counties before resolving the rest, need random/repeat
    access to the SAME row objects their mutation pass later touches -- there is no way to satisfy
    that without materializing the list; see the migration commit for why a true constant-memory
    per-row dispatch was not viable here). So this keeps the full-list materialization but drops
    the sidecar merge, then replaces the write: instead of re-validating and re-serializing the
    WHOLE board (write_artifact), a snapshot taken before apply_fn runs is diffed against each
    row's post-mutation state (_diff_to_patches()) to find exactly which rows changed and how, and
    only THOSE land via patch_existing_rows() -- the same safe write every other migration this
    week uses.

    WHAT THIS CANNOT DO. A fix whose apply_fn deletes a raw sub-key outside
    _RAW_DELETE_SAFE_AS_NONE (undo_resolver_middle_conflicts.py, repair_parcel_from_address.py --
    both blank raw['owner_mailing'], read via a presence test elsewhere) raises loudly from
    _diff_to_patches() rather than silently corrupting that key's absence into an explicit None.
    Those two scripts still need their own dedicated migration; this one does not attempt it.
    """
    require_raw_keep(required_keys)
    from foreclosure_scraper.web_artifact import (
        _raise_if_board_too_large_to_patch, board_lock, patch_existing_rows,
    )
    docs = REPO / "docs"
    with board_lock(REPO, owner=owner):
        # Fail before the expensive full-list build, not after -- the same ceiling
        # patch_existing_rows() itself re-checks before writing, reused here as an early guard
        # since this helper is a full-list read plus a patch-style write, not pure streaming.
        _raise_if_board_too_large_to_patch(docs)
        rows = _light_rows(docs)
        n = len(rows)
        pre = _snapshot_rows(rows)
        res = apply_fn(rows, dry_run=False)
        backup = res.pop("_backup", None)
        assert len(rows) == n, "a fix must never change the row count"
        patches = _diff_to_patches(rows, pre, owner=owner)
        print_counter(res, f"board rows: {n:,}")
        if backup:
            print("backup:", write_backup(backup_name, backup))
        stats = patch_existing_rows(
            patches, {owner: {k: v for k, v in res.items() if v}}, docs_dir=docs)
        # patch_existing_rows() returns existing=None/total_after=None, without touching the
        # board at all, when `patches` is empty (nothing for this pass to change) -- the common,
        # expected case on a re-run of an idempotent fix.
        existing = f"{stats['existing']:,}" if stats["existing"] is not None else "(no patch attempted)"
        print(f"wrote board: patched {stats['applied']:,} of {len(patches):,} changed row(s) "
              f"({n:,} scanned, existing board: {existing}, not_found={stats['not_found']:,})")
    return 0


def write_backup(name: str, payload) -> Path:
    """Write what an --apply replaced or removed to backups/<name>_<stamp>.json."""
    BACKUPS.mkdir(exist_ok=True)
    p = BACKUPS / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    p.write_text(json.dumps(payload, default=str))
    return p


def print_counter(c, title: str | None = None) -> None:
    if title:
        print(title)
    for k, n in sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        print(f"  {n:>8,}  {k}")
