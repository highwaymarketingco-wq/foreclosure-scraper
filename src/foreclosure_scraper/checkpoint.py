"""Crash-durable checkpoints for the long run.

WHY THIS EXISTS
    On 2026-08-06 the Mac rebooted 44.6 hours into a run, one phase short of
    publishing. Everything was lost: the merged 47,090-lead board, plus GIS,
    geocoding, owner resolution, parcel lookup and comps. The published board
    was still three days old.

    Nothing had been written to disk in 44 hours. `merge_prior_board` returns
    the merged list in memory and the only write is `write_artifact` at the very
    end, so any interruption at any point costs the entire run. That is a worse
    defect than anything the run itself contained.

HOW IT WORKS
    `save()` writes the FULL enriched board after each major phase — full
    fidelity, not the slimmed shape `write_artifact` publishes, so a resume
    loses nothing. Writes are atomic (temp file + os.replace), so a crash
    *during* a checkpoint cannot corrupt the previous good one.

    `load()` returns the newest checkpoint if it is fresh enough. The run then
    starts from that board instead of re-scraping and re-enriching from zero.

WHY RESUME DOES NOT NEED PER-PHASE SKIP LOGIC
    The enrichers are already idempotent — they target only leads missing the
    field they fill (gis_attrs ~18% of the board, geocode ~28%, link validation
    caches an "ok" for 7 days, the name resolver marks a lead queried and never
    re-asks). So re-running them over a restored board is cheap: they skip what
    is already done. The expensive thing is the DATA, and that is what is saved.

    That keeps this to a dozen call sites instead of threading skip flags
    through 91 guarded stages, which is where a rewrite would introduce bugs.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()

CHECKPOINT_DIR = Path(os.environ.get("FORECLOSURE_CHECKPOINT_DIR", "data/checkpoint"))
BOARD_FILE = "board.json.gz"
MANIFEST_FILE = "manifest.json"

#: A checkpoint older than this is ignored — resuming onto stale data would
#: silently republish last week's board as if it were fresh.
MAX_AGE_H = float(os.environ.get("FORECLOSURE_CHECKPOINT_MAX_AGE_H", "48"))

#: Set to "0" to disable checkpointing entirely.
ENABLED = os.environ.get("FORECLOSURE_CHECKPOINT", "1") != "0"

#: The phase of a SCORED board that has not been published: main.run_enrich_tail() is done and
#: main.publish_tail() has not run. Written by save_pre_publish() (the gated full run,
#: FULLRUN_STOP_BEFORE_PUBLISH, and scripts/resume_from_checkpoint.py), published later by
#: ``scripts/resume_from_checkpoint.py --publish-only`` (deploy/oracle/vm_resume.sh).
PRE_PUBLISH = "pre_publish"
#: Beside a pre_publish board: the run's publish inputs (summary, enrichment stats, errors, the
#: scoring status, and which of publish_tail's side effects the run would have performed).
STATE_FILE = "resume_state.json"
#: Beside a pre_publish board, when the run publishes a sold pool: its rows, in BOARD_FILE's format.
SOLD_POOL_FILE = "sold_pool.json.gz"

#: Age limit for PUBLISHING a pre_publish checkpoint (2026-10-06). The gated launch stops the full
#: run before publish so a human reviews the scored board first; MAX_AGE_H's 48 h would refuse a
#: board that finished on a Friday evening and was reviewed on Monday (~72 h). 96 h covers that
#: with a day to spare and still refuses last week's board: that one must be re-run, not published
#: as if fresh. FORECLOSURE_PRE_PUBLISH_MAX_AGE_H, or --max-age-h of the resume script, overrides.
PRE_PUBLISH_MAX_AGE_H = float(os.environ.get("FORECLOSURE_PRE_PUBLISH_MAX_AGE_H", "96"))


def _dir() -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR


def _write_rows_gz(path: Path, listings: list[Listing]) -> None:
    """Write ``listings`` to ``path`` as one gzipped JSON array, one row at a time, atomically
    (temp file in the same directory + os.replace). Raises on failure; the old file is kept."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        # One row at a time (2026-10-05): this used to build the full
        # [model_dump(...) for li in listings] list first -- a second full-fidelity
        # copy of the whole board (~270K rows on the VM) alive next to the Listings,
        # at every checkpoint. The bytes are the same json.dump(payload) produced
        # ("[" + ", ".join(rows) + "]", default separators, ensure_ascii).
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            fh.write("[")
            for i, li in enumerate(listings):
                if i:
                    fh.write(", ")
                fh.write(json.dumps(li.model_dump(mode="json")))
            fh.write("]")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(listings: list[Listing], phase: str, *, extra: Optional[dict] = None) -> bool:
    """Atomically checkpoint the full board. Never raises — a failed checkpoint
    must not take down a run that is otherwise fine."""
    if not ENABLED or not listings:
        return False
    t0 = time.monotonic()
    try:
        d = _dir()

        # Temp file in the SAME directory so os.replace is atomic (a rename
        # across filesystems is not). A crash mid-write leaves the previous
        # checkpoint intact.
        _write_rows_gz(d / BOARD_FILE, listings)

        manifest = {
            "phase": phase,
            "count": len(listings),
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "elapsed_s": round(time.monotonic() - t0, 1),
        }
        if extra:
            manifest.update(extra)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        os.close(fd)
        Path(tmp).write_text(json.dumps(manifest, indent=1))
        os.replace(tmp, d / MANIFEST_FILE)

        log.info("checkpoint.saved", phase=phase, leads=len(listings),
                 seconds=manifest["elapsed_s"])
        return True
    except Exception as exc:  # noqa: BLE001 - a checkpoint must never kill the run
        log.warning("checkpoint.save_failed", phase=phase,
                    error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return False


def manifest() -> Optional[dict]:
    try:
        p = CHECKPOINT_DIR / MANIFEST_FILE
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:  # noqa: BLE001
        return None


def age_hours() -> Optional[float]:
    m = manifest()
    if not m or not m.get("saved_at"):
        return None
    try:
        when = datetime.fromisoformat(m["saved_at"])
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() / 3600.0


def load(max_age_h: Optional[float] = None) -> Optional[list[Listing]]:
    """The newest checkpoint, if it exists and is fresh enough. None otherwise."""
    if not ENABLED:
        return None
    p = CHECKPOINT_DIR / BOARD_FILE
    if not p.exists():
        return None
    age = age_hours()
    limit = MAX_AGE_H if max_age_h is None else max_age_h
    if age is not None and age > limit:
        log.warning("checkpoint.too_old", age_h=round(age, 1), limit_h=limit)
        return None
    # Streamed (2026-10-05): json.load of the whole file kept every parsed row dict
    # alive until the last Listing was built -- the decoded board and the validated
    # board at the same time. Now each row is validated and its dict dropped.
    from .board_parts import iter_gz_rows
    from .row_keys import share_keys
    out: list[Listing] = []
    key_cache: dict = {}    # one str per distinct key across rows (row_keys.py)
    seen = 0
    try:
        for rec in iter_gz_rows(p):
            seen += 1
            try:
                out.append(Listing.model_validate(share_keys(rec, key_cache)))
            except Exception:  # noqa: BLE001 - one bad row must not void the resume
                continue
    except Exception as exc:  # noqa: BLE001
        log.warning("checkpoint.load_failed",
                    error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return None
    m = manifest() or {}
    # A streamed decoder stops quietly at a truncated tail where json.load raised, so
    # check the row count the save recorded instead of trusting end-of-stream.
    if isinstance(m.get("count"), int) and seen < m["count"]:
        log.warning("checkpoint.load_failed",
                    error=f"row count {seen} < manifest count {m['count']}")
        return None
    log.info("checkpoint.loaded", leads=len(out), phase=m.get("phase"),
             age_h=round(age, 1) if age is not None else None,
             dropped=seen - len(out))
    return out or None


def archive() -> Optional[Path]:
    """Copy the current checkpoint to ``<checkpoint dir>/../checkpoint_archive/<phase>_<saved_at>/``
    before it is replaced, and return that directory (None when there is nothing to archive or
    too little disk). A copy, never a move: the live checkpoint must stay loadable until the new
    save has atomically replaced it. Idempotent: an archive of the same checkpoint is kept as is.

    Why: save_pre_publish() overwrites the pre-scoring checkpoint (normally ``dot_ocr``). When the
    review of a pre_publish board finds a defect in the scoring tail, copying this archive back to
    the checkpoint directory lets ``scripts/resume_from_checkpoint.py --enrich-only`` redo only
    the tail (hours) instead of the whole run (~20 h). (Moved here from that script, 2026-10-06.)
    """
    m = manifest() or {}
    src = CHECKPOINT_DIR
    board = src / BOARD_FILE
    if not board.exists():
        return None
    tag = f"{m.get('phase', 'unknown')}_{str(m.get('saved_at', 'na')).replace(':', '')}"
    dest = src.parent / "checkpoint_archive" / tag
    if (dest / BOARD_FILE).exists():
        return dest
    free = shutil.disk_usage(src).free
    need = board.stat().st_size * 2 + (1 << 30)
    if free < need:
        log.warning("checkpoint.archive_skipped_low_disk", free_mb=free >> 20, need_mb=need >> 20)
        return None
    dest.mkdir(parents=True, exist_ok=True)
    for name in (BOARD_FILE, MANIFEST_FILE):
        if (src / name).exists():
            shutil.copy2(src / name, dest / name)
    log.info("checkpoint.archived", path=str(dest), phase=m.get("phase"))
    return dest


def _atomic_write_text(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        Path(tmp).write_text(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_pre_publish(st, summary: dict, *, extra: Optional[dict] = None) -> bool:
    """Checkpoint a SCORED board for a later ``scripts/resume_from_checkpoint.py --publish-only``.

    ``st`` is a ``main.TailState`` after ``main.run_enrich_tail()`` (read by attribute: enriched,
    enrichment_stats, errors, scoring_failed, write_sold_pool, sold_pool, write_run_health,
    export_and_email). Shared by the gated full run (``main.stop_before_publish``) and the
    checkpoint resume, so both leave exactly the files ``--publish-only`` consumes:

      board.json.gz + manifest.json   save(st.enriched, "pre_publish"); the manifest also names
                                      the state file and carries a token that pairs the two
      resume_state.json               summary, enrichment_stats, errors, scoring_failed, and
                                      ``publish``: which of publish_tail's side effects (sold
                                      pool, run_health, Sheet export + digest email) the run
                                      would have performed. A resume saves them False (it has no
                                      per-source data); a full run saves them True, so publishing
                                      its checkpoint later does what its own publish would have.
      sold_pool.json.gz               the run's sold pool, only when ``publish.write_sold_pool``

    The checkpoint being replaced is archived first (archive()). Never raises; returns False when
    any part was not written (a False here means: do not publish this board from the checkpoint).
    """
    if not ENABLED or not getattr(st, "enriched", None):
        return False
    try:
        d = _dir()
        archive()
        # A previous board's publish inputs go first, so no crash below can pair this board
        # with another run's summary or sold pool (the token check in load_publish_state()
        # catches the reverse: this run's state beside an older board).
        for name in (STATE_FILE, SOLD_POOL_FILE):
            try:
                (d / name).unlink()
            except FileNotFoundError:
                pass
        token = f"{os.getpid()}-{time.time_ns()}"
        publish = {"write_sold_pool": bool(getattr(st, "write_sold_pool", False)),
                   "write_run_health": bool(getattr(st, "write_run_health", False)),
                   "export_and_email": bool(getattr(st, "export_and_email", False))}
        if not save(st.enriched, PRE_PUBLISH,
                    extra={**(extra or {}), "publish_state": STATE_FILE, "state_token": token}):
            return False
        if publish["write_sold_pool"]:
            _write_rows_gz(d / SOLD_POOL_FILE, list(getattr(st, "sold_pool", None) or []))
        state = {"summary": summary, "enrichment_stats": st.enrichment_stats, "errors": st.errors,
                 "scoring_failed": getattr(st, "scoring_failed", None), "publish": publish,
                 "state_token": token}
        _atomic_write_text(d / STATE_FILE, json.dumps(state, default=str, ensure_ascii=False))
        log.info("checkpoint.pre_publish_saved", leads=len(st.enriched), **publish)
        return True
    except Exception as exc:  # noqa: BLE001 - a checkpoint must never kill the run
        log.warning("checkpoint.pre_publish_save_failed",
                    error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return False


def load_publish_state() -> tuple[dict, Optional[str]]:
    """The publish inputs saved beside the current checkpoint by save_pre_publish():
    ``(state, None)``, or ``({}, reason)`` when they cannot be trusted (the manifest names a state
    file that is missing or unreadable, or one whose token is not this board's). A checkpoint
    saved before 2026-10-06 names no state file: its resume_state.json is read as it is, and its
    absence is not an error (``({}, None)``)."""
    m = manifest() or {}
    p = CHECKPOINT_DIR / STATE_FILE
    named = m.get("publish_state")
    if not p.exists():
        if named:
            return {}, (f"{named} is missing beside this {m.get('phase')!r} checkpoint (its save "
                        f"did not finish): it holds the run's summary and what to publish")
        return {}, None
    try:
        state = json.loads(p.read_text())
    except Exception as exc:  # noqa: BLE001
        return {}, f"{STATE_FILE} is unreadable: {type(exc).__name__}: {str(exc)[:120]}"
    tok = m.get("state_token")
    if tok and state.get("state_token") != tok:
        return {}, (f"{STATE_FILE} belongs to another checkpoint (token "
                    f"{state.get('state_token')!r}, this board's is {tok!r})")
    return state, None


def load_sold_pool() -> Optional[list[Listing]]:
    """The sold pool saved beside a pre_publish board, or None when there is none (or it is
    unreadable). An empty list is a real, empty sold pool."""
    p = CHECKPOINT_DIR / SOLD_POOL_FILE
    if not p.exists():
        return None
    from .board_parts import iter_gz_rows
    try:
        return [Listing.model_validate(rec) for rec in iter_gz_rows(p)]
    except Exception as exc:  # noqa: BLE001
        log.warning("checkpoint.sold_pool_load_failed",
                    error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return None


def clear() -> None:
    """Drop the checkpoint after a successful publish, so the next run starts
    clean rather than resuming onto a board that has already shipped."""
    try:
        if CHECKPOINT_DIR.exists():
            shutil.rmtree(CHECKPOINT_DIR)
            log.info("checkpoint.cleared")
    except Exception as exc:  # noqa: BLE001
        log.warning("checkpoint.clear_failed",
                    error=f"{type(exc).__name__}: {str(exc)[:120]}")
