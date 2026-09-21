"""Shared plumbing for the 2026-09-21 board data-quality fix scripts.

Not a script. Every fix script (fill_address_from_parcel, backfill_missing_county,
quarantine_flip_leaks, promote_ptscloud_block, undo_resolver_middle_conflicts, ...) follows the
same contract, taken from join_parcel_cache_to_board / repair_burke_storm_damage_parcels:

  * the default run is a DRY RUN. It streams docs/listings.json.gz through
    board_stream.iter_board_rows (about 300 MB, seconds), keeps only counters and a few samples,
    and never calls load_board or write_artifact.
  * --apply takes board_lock, load_board, mutates Listing objects FILL-ONLY, asserts the row count
    is unchanged, writes the artifact, and backs up anything it replaces under backups/.
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


def run_apply(owner: str, apply_fn, required_keys, backup_name: str) -> int:
    """The single-script --apply skeleton: preflight, board_lock, load_board, apply_rows, assert the row
    count, write the backup, write_artifact. `apply_fn(rows, dry_run=False)` returns a counter dict that may
    carry a '_backup' payload (popped here and written under backups/)."""
    require_raw_keep(required_keys)
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact
    with board_lock(REPO, owner=owner):
        rows = load_board(REPO / "docs")
        n = len(rows)
        res = apply_fn(rows, dry_run=False)
        backup = res.pop("_backup", None)
        assert len(rows) == n, "a fix must never change the row count"
        print_counter(res, f"board rows: {n:,}")
        if backup:
            print("backup:", write_backup(backup_name, backup))
        write_artifact(rows, {owner: {k: v for k, v in res.items() if v}}, docs_dir=REPO / "docs")
        print(f"wrote board: {n:,} rows")
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
