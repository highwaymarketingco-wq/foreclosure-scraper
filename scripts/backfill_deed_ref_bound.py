#!/usr/bin/env python3
"""One-time repair for top80-fill-deed-ref-bound (audit 2026-10-18 gap-sweep continuation).

Two mechanisms published ~978 rows (1,453 violations) whose raw['county_deed_ref'] /
raw['county_legal'] names a DIFFERENT parcel than the row's own identity, both already fixed in
gis_fill.py / enrichment_court_owner_verify.py for FUTURE writes (commits e34f72cb, 6ebfaf1b,
both 2026-10-17 -- a day after this board's run_time of 2026-10-16T20:24:46Z) but unable to
retroactively heal what is already published:

  1. "wrong parno echoed" -- row.parcel_id is still set. gis_fill.fetch_nc()/fetch_nc_like()
     used to unconditionally echo a feature's `parno` field as provenance even when the row's
     own pin actually matched the feature's `altparno` -- a feature can carry BOTH ids for the
     SAME parcel. The deed/legal CONTENT was always correct; only the written 'parno' id was a
     foreign-looking value. Fix: re-run the CURRENT (already-fixed) fetch_nc() / fetch_nc_like()
     against the row's own parcel_id, confirm the re-fetched book/page (deed) or text (legal)
     is IDENTICAL to what's already published (proving this is purely the parno-echo bug and not
     some other data problem), and only then correct the block's 'parno' field in place.
     Anything that doesn't re-confirm this way (layer no longer has the parcel, content
     disagrees) is left alone and reported, never guessed at.

  2. "stale block after a court-verify strip" -- row.parcel_id is already null (correctly
     cleared by enrichment_court_owner_verify._strip_property). PROPERTY_SIGNAL_BLOCKS used to
     omit county_deed_ref / county_legal / gis_fill, so a strip that ran before the 2026-10-17
     fix left those three blocks behind, still naming the old (wrong) parcel. Fix: move exactly
     those three keys (whichever are present) into raw['unbound_property_blocks'], the same
     move _strip_property(blocks=True) does today -- no network, no guessing, a pure data move.

BOARD I/O REWRITE (2026-10-18, follow-up to resolver_backfill_parcel.py/task pattern): this
originally called load_board(REPO / "docs"), building the WHOLE board (437,170 rows) into a
list[Listing] before classifying anything. web_artifact.py's own BOARD_LOAD_MAX_SOURCE_MB
comment records that materialization at 10-25+ GB real footprint on boards half this size -- and
on the Oracle VM tonight load_board() refused outright (BoardLoadTooLarge, board source measured
at 4,985 MB against the 1,200 MB ceiling, confirmed not a stale-manifest false positive). Neither
mechanism's DECISION logic changed here -- classify()/_other_parcel()/corrected_parno()/
_fetch_live()/_nc_county() are the same functions, already covered by this file's own synthetic
tests and a prior live validation against 12 real rows -- only how the board is read and written:

  * Phase 1 streams the published board exactly once via board_stream.iter_board_rows() (the
    same constant-memory reader scripts/audit_checks/regressions.py and source_completeness.py
    already use safely against this exact board), with a cheap dict-level pre-filter (does this
    row's raw even carry county_deed_ref or county_legal at all?) before paying for a
    Listing.model_construct() -- resolver_backfill_parcel.py's own _collect_targets() pattern.
    Each surviving candidate gets a lightweight, UNVALIDATED Listing (model_construct(), the
    same _APPEND_SIG_FIELDS trick append_new_rows()/patch_existing_rows() themselves use) so
    classify()/corrected_parno()/_nc_county() and Listing.dedupe_key() all work unchanged. Only
    the ~978 candidates are ever materialized this way, never the other 436,000+ rows.
  * Phase 2 builds a `patches` dict (Listing.dedupe_key() -> field updates) from what Phase 1
    found, then lands it with ONE web_artifact.patch_existing_rows() call under board_lock() --
    never load_board()/write_artifact().

RAW-UPDATE GOTCHA (same one scripts/strip_jail_booking_new_name_only_low_cross_county.py and
scripts/backfill_derivation_flags.py already hit): patch_existing_rows()'s own docstring is
explicit that a `raw` key in a patch is MERGED into the row's existing raw dict (dict.update()),
never replacing it -- there is no way to ask it to DELETE a key. Mechanism 2's "move aside" is
therefore represented the same way those two prior scripts represent a stripped key: the three
raw keys are set to None in the patch (every reader of them -- _other_parcel(), gis_fill.needs(),
etc. -- already treats a falsy/None block exactly like an absent one) while their ORIGINAL values
are carried into raw['unbound_property_blocks'] in the same patch, so nothing is actually lost --
just not physically popped out of the dict the way the in-memory version of this script once did.

SUPERVISED WRITE. patch_existing_rows() has its own separate ceiling (BOARD_PATCH_MAX_SOURCE_MB,
2,300 MB) that this board (4,985 MB) is also over. Rather than quietly setting
BOARD_PATCH_ALLOW_LARGE=1 and hoping, main() refuses the real write unless --allow-large is
passed AND wraps the actual patch_existing_rows() call -- the only part of this script that
write-locks and mutates the live board -- in a child process a watchdog polls (wall-clock timeout
and /proc/<pid>/status VmRSS + VmHWM, the Linux counterpart of this codebase's own "never trust
one memory signal alone" doctrine) and can SIGKILL. See _run_patch_supervised()'s docstring.

Usage:
    python scripts/backfill_deed_ref_bound.py --dry-run
    python scripts/backfill_deed_ref_bound.py --allow-large
"""
from __future__ import annotations

import argparse
import contextlib
import multiprocessing as mp
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import gis_fill as G  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_court_owner_verify import PROPERTY_SIGNAL_BLOCKS  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

#: the three keys this backfill moves for a stale-strip row -- exactly the gis_fill-owned subset
#: of PROPERTY_SIGNAL_BLOCKS (the task at hand; the other PROPERTY_SIGNAL_BLOCKS keys are not
#: this check's business and a different sweep already covers lincoln_bulk et al.).
_GIS_FILL_KEYS = ("county_deed_ref", "county_legal", "gis_fill")
assert set(_GIS_FILL_KEYS) <= set(PROPERTY_SIGNAL_BLOCKS), "PROPERTY_SIGNAL_BLOCKS no longer covers these keys"

#: fetch_nc / fetch_nc_like batch size, same constant gis_fill.py's own pipeline uses
BATCH = G.BATCH

#: identity + raw fields enough to build a lightweight, UNVALIDATED Listing for
#: classify()/corrected_parno()/_nc_county()/dedupe_key() -- append_new_rows()'s/
#: patch_existing_rows()'s own model_construct() trick, reused here for the same reason: it
#: avoids Listing.model_validate()'s cost over rows that are not even candidates.
_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw",)


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _raw(li: Any) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


def _aliases(pin: Any) -> set[str]:
    return set(G.pin_aliases(pin))


def _other_parcel(block: Any, own_pin: Any) -> bool:
    """True when `block` is a county_deed_ref / county_legal dict naming a parno that is not an
    alias of `own_pin` -- the exact condition scripts/audit_checks/top80_fill.py's Bound check
    flags (source restricted to nc_onemap / *_parcel_layer, same as that check)."""
    if not isinstance(block, dict) or not block.get("parno"):
        return False
    src = str(block.get("source") or "")
    if src != "nc_onemap" and not src.endswith("_parcel_layer"):
        return False
    return not (_aliases(block["parno"]) & _aliases(own_pin))


def classify(li: Any) -> Optional[str]:
    """'wrong_parno' | 'stale_strip' | None (not a violation this script repairs)."""
    raw = _raw(li)
    hit = any(_other_parcel(raw.get(k), li.parcel_id) for k in ("county_deed_ref", "county_legal"))
    if not hit:
        return None
    return "stale_strip" if not li.parcel_id else "wrong_parno"


def _nc_county(li: Any) -> str:
    co = G.county_name(li)
    if str(li.state).upper() == "NC":
        from foreclosure_scraper.quiet_title.adapters.nc_onemap import canonical_county
        co = canonical_county(co) or co
    return co


def _fetch_live(county: str, pins: list[str]) -> dict[str, dict]:
    """{pin: matched} for every pin found by the current fetch_nc(), falling back to
    fetch_nc_like() (the real pipeline's second pass) for the pins the exact pass misses.
    Pins the layer never answers for at all (down, closed, truly not found) are left out."""
    found: dict[str, dict] = {}
    todo = list(pins)
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        got = G.fetch_nc(county, chunk)
        if got is None:
            continue
        for p in chunk:
            m = got.get(p)
            if m is not None:
                found[p] = m
    missing = [p for p in todo if p not in found]
    for i in range(0, len(missing), G.LIKE_BATCH):
        chunk = missing[i:i + G.LIKE_BATCH]
        got = G.fetch_nc_like(county, chunk)
        if got is None:
            continue
        for p in chunk:
            m = got.get(p)
            if m is not None:
                found[p] = m
    return found


def corrected_parno(block: Any, matched: Optional[dict], own_pin: Any) -> Optional[str]:
    """The live-refetched parno to replace `block['parno']` with, or None when the re-fetch does
    not clearly confirm the parno-echo mechanism for THIS block (no match, content disagrees, or
    the new parno still doesn't alias own_pin) -- caller must then leave the row untouched."""
    if not isinstance(block, dict) or matched is None:
        return None
    new_parno = matched.get("parno")
    if not (_aliases(new_parno) & _aliases(own_pin)):
        return None
    if "book" in block or "page" in block:  # county_deed_ref shape
        d = matched.get("deed")
        if not isinstance(d, dict) or d.get("book") != block.get("book") or d.get("page") != block.get("page"):
            return None
    else:  # county_legal shape
        if matched.get("legal") != block.get("text"):
            return None
    return new_parno


# ===========================================================================
# Phase 1: stream the board once, classify, collect candidates -- never load_board().
# ===========================================================================

def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], dict[str, Listing], int, int]:
    """Stream the published board exactly once (board_stream.iter_board_rows()) and return
    ({dedupe_key: light_listing} for wrong_parno, ditto for stale_strip, total rows streamed,
    ambiguous-identity candidates excluded).

    A dedupe_key seen on MORE than one violating candidate means the board already has (at
    least) two DIFFERENT rows sharing one identity. patch_existing_rows() would apply whichever
    ONE patch gets built under that key to EVERY board row matching it (its own documented
    "same identity is the same property" semantics) -- correct for a patch whose VALUE is the
    same regardless of which matching row it lands on (e.g. a parcel_id resolved from lat/lon),
    but NOT safe here: both of this script's mechanisms derive the patch value from the row's
    OWN existing raw content, which can legitimately differ between two rows that merely share
    an identity (one's county_deed_ref could be fresh, the sibling's stale or absent). Landing
    one row's content-derived correction on its sibling would silently corrupt the sibling's
    data. So, same "skip and count, never guess" discipline as every other unconfirmed case in
    this script: every candidate under an ambiguous key is excluded from `patches` entirely,
    counted, and left exactly as published -- not guessed at by picking one arbitrarily."""
    wrong_parno: dict[str, Listing] = {}
    stale_strip: dict[str, Listing] = {}
    total = 0
    seen: dict[str, int] = {}
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        raw = rec.get("raw")
        if not isinstance(raw, dict) or not (raw.get("county_deed_ref") or raw.get("county_legal")):
            continue
        li = _light(rec)
        kind = classify(li)
        if kind is None:
            continue
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a row too malformed to key is simply unpatchable
            continue
        seen[key] = seen.get(key, 0) + 1
        (wrong_parno if kind == "wrong_parno" else stale_strip)[key] = li

    ambiguous = {k for k, n in seen.items() if n > 1}
    for key in ambiguous:
        wrong_parno.pop(key, None)
        stale_strip.pop(key, None)
    return wrong_parno, stale_strip, total, len(ambiguous)


def _build_wrong_parno_patches(candidates: dict[str, Listing], c: Counter) -> dict[str, dict]:
    """Mechanism 1. Groups confirmed NC/nc_onemap candidates by county, re-fetches each county's
    pins live ONCE, and returns {dedupe_key: {"raw": {...}}} for every block corrected_parno()
    can confirm -- unconfirmed blocks are counted and left out, never guessed at."""
    patches: dict[str, dict] = {}
    by_county: dict[str, list[tuple[str, Listing]]] = {}
    for key, li in candidates.items():
        if str(li.state).upper() != "NC":
            c["wrong_parno_skip_non_nc_state"] += 1
            continue
        raw = _raw(li)
        if any(str((raw.get(k) or {}).get("source") or "") not in ("nc_onemap",)
               for k in ("county_deed_ref", "county_legal") if _other_parcel(raw.get(k), li.parcel_id)):
            c["wrong_parno_skip_non_nc_onemap_source"] += 1
            continue
        by_county.setdefault(_nc_county(li), []).append((key, li))

    for county, items in sorted(by_county.items()):
        pins = sorted({str(li.parcel_id).strip() for _, li in items})
        matched_by_pin = _fetch_live(county, pins)
        for key, li in items:
            pin = str(li.parcel_id).strip()
            matched = matched_by_pin.get(pin)
            raw = _raw(li)
            raw_patch: dict = {}
            for rkey in ("county_deed_ref", "county_legal"):
                block = raw.get(rkey)
                if not _other_parcel(block, li.parcel_id):
                    continue
                new_parno = corrected_parno(block, matched, li.parcel_id)
                if new_parno is None:
                    c[f"wrong_parno_skip_unconfirmed_{rkey}"] += 1
                    continue
                raw_patch[rkey] = {**block, "parno": new_parno}
                c[f"wrong_parno_fixed_{rkey}"] += 1
                c[f"wrong_parno_fixed_county:{county}"] += 1
            if raw_patch:
                patches[key] = {"raw": raw_patch}
    return patches


def _build_stale_strip_patches(candidates: dict[str, Listing], c: Counter) -> dict[str, dict]:
    """Mechanism 2. No network: moves whichever of _GIS_FILL_KEYS are present into
    raw['unbound_property_blocks'], represented as the three keys set to None (see this module's
    docstring's RAW-UPDATE GOTCHA -- patch_existing_rows() can only merge a raw update, never
    delete a key) plus the moved values folded into unbound_property_blocks, preserving whatever
    that key already held."""
    patches: dict[str, dict] = {}
    for key, li in candidates.items():
        raw = _raw(li)
        moved = {k: raw[k] for k in _GIS_FILL_KEYS if raw.get(k) is not None}
        if not moved:
            continue
        existing_ubpb = raw.get("unbound_property_blocks")
        raw_patch: dict = {k: None for k in moved}
        raw_patch["unbound_property_blocks"] = {
            **(existing_ubpb if isinstance(existing_ubpb, dict) else {}),
            **moved,
        }
        patches[key] = {"raw": raw_patch}
        c["stale_strip_fixed"] += 1
        c[f"stale_strip_fixed_county:{li.county}"] += 1
    return patches


# ===========================================================================
# Phase 2: supervised patch_existing_rows() -- the only part of this script that write-locks
# and mutates the live board.
# ===========================================================================

def _parse_proc_status_text(text: str) -> tuple[Optional[float], Optional[float]]:
    """(VmRSS MB, VmHWM MB) parsed out of a /proc/<pid>/status-shaped string. Pure and
    OS-independent so it is unit-testable without a real /proc filesystem."""
    rss = hwm = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if line.startswith("VmRSS:"):
            try:
                rss = float(parts[1]) / 1024.0  # kB -> MB
            except ValueError:
                pass
        elif line.startswith("VmHWM:"):
            try:
                hwm = float(parts[1]) / 1024.0
            except ValueError:
                pass
    return rss, hwm


def _read_proc_status_mb(pid: int) -> tuple[Optional[float], Optional[float]]:
    """(VmRSS MB, VmHWM MB) for `pid` via /proc/<pid>/status -- (None, None) when unavailable
    (process already exited, or this host has no /proc, e.g. the Mac this script is developed
    on). The dual RSS + kernel-tracked high-water-mark read is the Linux counterpart of this
    codebase's established dual-signal watchdog discipline (RSS via `ps`, physical footprint via
    `sample -f`, on macOS -- see BOARD_LOAD_MAX_SOURCE_MB's comment in web_artifact.py for why a
    single memory signal was once trusted and turned out wrong); VmHWM catches a spike this
    loop's own polling interval might otherwise straddle."""
    try:
        text = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return None, None
    return _parse_proc_status_text(text)


def _watchdog_should_kill(elapsed_s: float, rss_mb: Optional[float], hwm_mb: Optional[float], *,
                          timeout_s: float, mem_ceiling_mb: float) -> Optional[str]:
    """Pure decision function: the kill reason string, or None to keep waiting. Separated out of
    _run_patch_supervised()'s polling loop so the kill logic itself is unit-testable without any
    real process or /proc access."""
    if elapsed_s > timeout_s:
        return f"wall-clock timeout ({timeout_s:.0f}s) exceeded (elapsed={elapsed_s:.1f}s)"
    if rss_mb is not None and rss_mb > mem_ceiling_mb:
        return f"VmRSS {rss_mb:.0f} MB exceeded the {mem_ceiling_mb:.0f} MB ceiling"
    if hwm_mb is not None and hwm_mb > mem_ceiling_mb:
        return f"VmHWM {hwm_mb:.0f} MB exceeded the {mem_ceiling_mb:.0f} MB ceiling"
    return None


def _patch_worker(patches: dict, summary: dict, docs_dir: str, allow_large: bool,
                  result_queue: "mp.Queue") -> None:
    """The child-process entrypoint: exactly ONE patch_existing_rows() call, nothing else. Runs
    in its own process (spawned by _run_patch_supervised()) so the parent's watchdog can SIGKILL
    it without touching this process's own state. BOARD_PATCH_ALLOW_LARGE is set here, in the
    CHILD only, and only when the caller explicitly asked for it (--allow-large) -- never forced
    unconditionally, so a run against a board that is NOT oversized still gets the real ceiling
    check."""
    if allow_large:
        os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
    try:
        stats = patch_existing_rows(patches, summary, docs_dir=docs_dir)
        result_queue.put(("ok", stats))
    except BaseException as exc:  # noqa: BLE001 - must report, never hang the parent
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _run_patch_supervised(patches: dict, summary: dict, docs_dir: Path, *,
                          timeout_s: float, mem_ceiling_mb: float, allow_large: bool,
                          poll_s: float = 1.0) -> tuple[dict, dict]:
    """Run patch_existing_rows() -- the only part of this script that write-locks and mutates
    the live board -- in a CHILD PROCESS, polling /proc/<pid>/status (_read_proc_status_mb()) on
    an interval and SIGKILL-ing it if _watchdog_should_kill() says to (wall-clock timeout or a
    VmRSS/VmHWM memory ceiling). The board_lock() the caller already holds is inherited by the
    child via os.environ (multiprocessing's "spawn" start method passes the parent's environment
    through), so require_board_lock() inside patch_existing_rows() still sees it held.

    Raises RuntimeError if the child is killed, exits non-zero, or produces no result.
    Returns (patch_existing_rows()'s own stats dict, {peak_rss_mb, peak_vmhwm_mb, elapsed_s,
    killed_reason})."""
    ctx = mp.get_context("spawn")
    q: "mp.Queue" = ctx.Queue()
    proc = ctx.Process(target=_patch_worker, args=(patches, summary, str(docs_dir), allow_large, q))
    proc.start()
    start = time.monotonic()
    peak_rss = peak_hwm = 0.0
    killed_reason: Optional[str] = None
    try:
        while proc.is_alive():
            elapsed = time.monotonic() - start
            rss, hwm = _read_proc_status_mb(proc.pid)
            if rss is not None:
                peak_rss = max(peak_rss, rss)
            if hwm is not None:
                peak_hwm = max(peak_hwm, hwm)
            killed_reason = _watchdog_should_kill(
                elapsed, rss, hwm, timeout_s=timeout_s, mem_ceiling_mb=mem_ceiling_mb)
            if killed_reason:
                proc.kill()
                break
            time.sleep(poll_s)
    finally:
        proc.join(timeout=60)
    report = {"peak_rss_mb": peak_rss, "peak_vmhwm_mb": peak_hwm,
              "elapsed_s": time.monotonic() - start, "killed_reason": killed_reason}
    if killed_reason:
        raise RuntimeError(
            f"patch_existing_rows watchdog killed the child process: {killed_reason}. {report}")
    if proc.exitcode != 0:
        raise RuntimeError(
            f"patch_existing_rows child process exited with code {proc.exitcode}: {report}")
    try:
        status, payload = q.get(timeout=30)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"patch_existing_rows child produced no result: {exc}. {report}") from exc
    if status != "ok":
        raise RuntimeError(f"patch_existing_rows child raised: {payload}. {report}")
    return payload, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true",
                    help="Override BOARD_PATCH_MAX_SOURCE_MB (BOARD_PATCH_ALLOW_LARGE=1) in the "
                         "supervised child process, when the board's measured source size is "
                         "over that ceiling. Pass this only for a SUPERVISED run -- the watchdog "
                         "below (--patch-timeout-s / --patch-mem-ceiling-mb) is what actually "
                         "keeps it safe, not this flag alone.")
    ap.add_argument("--patch-timeout-s", type=float, default=1200.0,
                    help="Wall-clock kill-switch (seconds) for the patch_existing_rows() child "
                         "process. Default 20 minutes.")
    ap.add_argument("--patch-mem-ceiling-mb", type=float, default=16000.0,
                    help="VmRSS/VmHWM kill-switch (MB) for the patch_existing_rows() child "
                         "process. Default 16,000 MB.")
    args = ap.parse_args()

    docs = REPO / "docs"

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="deed_ref_bound_backfill")
    with lock:
        wrong_parno, stale_strip, total_rows, ambiguous = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        print(f"wrong_parno candidates: {len(wrong_parno):,}   stale_strip candidates: {len(stale_strip):,}")

        c: Counter = Counter()
        c["skipped_ambiguous_dedupe_key"] = ambiguous
        if ambiguous:
            print(f"excluded as ambiguous-identity (shared dedupe_key with another "
                  f"candidate, never guessed at): {ambiguous:,}")

        patches: dict[str, dict] = {}
        patches.update(_build_wrong_parno_patches(wrong_parno, c))
        patches.update(_build_stale_strip_patches(stale_strip, c))

        print("\nby kind:")
        for k, v in sorted(c.items()):
            if ":" not in k:
                print(f"    {k:40} {v:,}")
        print("\nby county (fixed only):")
        for k, v in sorted(c.items()):
            if ":" in k:
                print(f"    {k:40} {v:,}")
        print(f"\npatches staged: {len(patches):,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0
        if not patches:
            print("\nnothing to do.")
            return 0

        size_state = board_patch_size_state(docs)
        if not size_state["ok"] and not args.allow_large:
            print(f"\nREFUSING: {size_state['reason']}. Re-run with --allow-large once the "
                  f"supervised watchdog (--patch-timeout-s / --patch-mem-ceiling-mb) is wired "
                  f"the way you want it -- see patch_existing_rows()'s BOARD_PATCH_ALLOW_LARGE "
                  f"docstring in web_artifact.py for what 'supervised' means.")
            return 1

        stats, watchdog = _run_patch_supervised(
            patches, dict(c), docs,
            timeout_s=args.patch_timeout_s, mem_ceiling_mb=args.patch_mem_ceiling_mb,
            allow_large=args.allow_large,
        )
        print(f"\nwatchdog: peak VmRSS {watchdog['peak_rss_mb']:.0f} MB, "
              f"peak VmHWM {watchdog['peak_vmhwm_mb']:.0f} MB, wall {watchdog['elapsed_s']:.1f}s")
        print(f"wrote board: patched {stats['applied']:,}/{len(patches):,} rows "
              f"(existing board: {stats['existing']:,}, not_found: {stats['not_found']:,}, "
              f"duplicate_key_matches: {stats['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
