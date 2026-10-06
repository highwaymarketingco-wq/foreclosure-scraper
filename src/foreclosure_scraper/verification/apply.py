"""The VM side: attach raw['verification'] from the ledgers to the run's listings. No network.

main.py's run_enrich_tail() calls apply_verification(enriched) right before score_board, so
the nightly run and the enrich-only resume path (they share that tail) both get it, and the
scorer sees the verdicts on the same run. It never raises: a missing directory, an unreadable
ledger or a bad row is logged and the run carries on. VERIFICATION_APPLY=0 turns it off.

WHAT A ROW GETS. raw['verification'] is a list, one record per signal (the spec's schema,
VERIFICATION_PIPELINE_SPEC.md section 1), each the ledger entry's `latest` plus:
    expires_at   checked_at + TTL_DAYS of the verifier that produced it (the registry's
                 current value when that module still exists, else the TTL the entry stored)
    governs      the scorer signal names a refuted/stale verdict removes (same precedence)
Records for signals no ledger covers are left as they are. A row is matched to a ledger entry
on any of its row_keys() that exactly one entry claims (ledger.Ledger.find).
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog

from .core import SUPPRESSING, expires_at, is_expired, records_of, row_keys, utc_now
from .ledger import ledger_dir, load_all

log = structlog.get_logger()


def _verifier_meta() -> dict[str, Any]:
    try:
        from .registry import discover
        return {v.name: v for v in discover()}
    except Exception:  # noqa: BLE001 - the stored values are the fallback
        return {}


def attachable(entry: dict, meta: Optional[dict] = None) -> Optional[dict]:
    """The record a row carries for this ledger entry, or None when the entry has none."""
    lat = entry.get("latest")
    if not isinstance(lat, dict) or not lat.get("verdict"):
        return None
    rec = dict(lat)
    v = (meta or {}).get(rec.get("verifier") or "")
    ttl = v.ttl_days if v is not None else entry.get("ttl_days")
    gov = list(v.governs) if v is not None else list(entry.get("governs") or [])
    rec["expires_at"] = expires_at(rec.get("checked_at"), ttl)
    rec["governs"] = gov
    return rec


def apply_verification(listings: Iterable, directory: Optional[Path] = None,
                       now: Optional[datetime] = None) -> dict:
    d = Path(directory or ledger_dir())
    counts: dict[str, Any] = {"dir": str(d), "status": "ok", "signals": {}, "rows": 0,
                              "records": 0, "suppressing": 0, "unreadable": {}}
    try:
        if os.environ.get("VERIFICATION_APPLY") == "0":
            counts["status"] = "disabled"
            log.info("verification_apply.disabled")
            return counts
        ledgers, bad = load_all(d)
        counts["unreadable"] = bad
        for name, err in bad.items():
            log.warning("verification_apply.unreadable", file=name, error=err)
        if not ledgers:
            counts["status"] = "absent" if not d.is_dir() else "empty"
            log.info("verification_apply.nothing", dir=str(d), status=counts["status"])
            return counts
        meta = _verifier_meta()
        now = now or utc_now()
        active = [(sig, led) for sig, led in sorted(ledgers.items()) if led.rows]
        for sig, led in active:
            counts["signals"][sig] = {"entries": len(led.rows), "attached": 0}
            led.index()
        for li in listings:
            try:
                keys = None
                found: dict[str, dict] = {}
                for sig, led in active:
                    if keys is None:
                        keys = row_keys(li)
                    _, entry = led.find(keys)
                    if entry is None:
                        continue
                    rec = attachable(entry, meta)
                    if rec is not None:
                        found[sig] = rec
                if not found:
                    continue
                raw = li.raw if isinstance(getattr(li, "raw", None), dict) else None
                if raw is None:
                    li.raw = raw = {}
                keep = [r for r in records_of(raw) if r.get("signal") not in found]
                raw["verification"] = sorted(keep + list(found.values()),
                                             key=lambda r: str(r.get("signal")))
                counts["rows"] += 1
                for sig, rec in found.items():
                    s = counts["signals"][sig]
                    s["attached"] += 1
                    s[rec["verdict"]] = s.get(rec["verdict"], 0) + 1
                    counts["records"] += 1
                    if rec["verdict"] in SUPPRESSING and not is_expired(rec, now):
                        counts["suppressing"] += 1
            except Exception as exc:  # noqa: BLE001 - one bad row never stops the step
                counts["row_errors"] = counts.get("row_errors", 0) + 1
                if counts["row_errors"] <= 3:
                    log.warning("verification_apply.row_failed",
                                error=f"{type(exc).__name__}: {str(exc)[:160]}")
        log.info("verification_apply.applied", **{k: v for k, v in counts.items()
                                                    if k not in ("unreadable",)})
    except Exception as exc:  # noqa: BLE001 - this step must never fail the run
        counts["status"] = "error"
        counts["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        log.error("verification_apply.failed", error=counts["error"])
    return counts
