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


def _dir() -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR


def save(listings: list[Listing], phase: str, *, extra: Optional[dict] = None) -> bool:
    """Atomically checkpoint the full board. Never raises — a failed checkpoint
    must not take down a run that is otherwise fine."""
    if not ENABLED or not listings:
        return False
    t0 = time.monotonic()
    try:
        d = _dir()
        payload = [li.model_dump(mode="json") for li in listings]

        # Temp file in the SAME directory so os.replace is atomic (a rename
        # across filesystems is not). A crash mid-write leaves the previous
        # checkpoint intact.
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        os.close(fd)
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, d / BOARD_FILE)

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
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            records = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        log.warning("checkpoint.load_failed",
                    error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return None
    out: list[Listing] = []
    for rec in records:
        try:
            out.append(Listing.model_validate(rec))
        except Exception:  # noqa: BLE001 - one bad row must not void the resume
            continue
    m = manifest() or {}
    log.info("checkpoint.loaded", leads=len(out), phase=m.get("phase"),
             age_h=round(age, 1) if age is not None else None,
             dropped=len(records) - len(out))
    return out or None


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
