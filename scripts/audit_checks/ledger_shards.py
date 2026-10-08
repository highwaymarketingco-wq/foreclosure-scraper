"""Verification-ledger size and integrity invariant (audit 2026-10-09, area ledger_shards).
docs/audit_2026-10-09/ledger_shards.md has the measurements.

  ledger-layout   every ledger in docs/handoff/verification (verification.ledger.check_layout).
                  A violation: a single-file ledger over FILE_MAX_BYTES (48 MiB; save() shards
                  a ledger before that, so one there means a writer bypassed it, on its way to
                  the repo's 95 MiB commit gate: tax_lien.json was 0.7 MB on 10/7 and 23 MB
                  on the evening of 10/8), a shard over the 8 MiB cap, a shard whose sha256 differs from its
                  manifest, a shard the manifest does not list, a listed shard that is missing,
                  or a shard directory with no readable manifest. A single file between the
                  shard cap and FILE_MAX_BYTES is not a violation; the detail says to run
                  scripts/ledger_migrate.py --apply.

The check reads the ledger directory, not the rows: feed() only counts them. Memory: one shard's
bytes at a time.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

SAMPLE = 8


class LedgerLayout:
    name = "ledger-layout"
    max_violations = 0

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory
        self.rows = 0

    def feed(self, row: dict) -> None:
        self.rows += 1

    def finish(self) -> dict:
        from foreclosure_scraper.verification import ledger as L

        d = Path(self.directory or os.environ.get("VERIFICATION_LEDGER_DIR")
                 or _REPO / "docs" / "handoff" / "verification")
        reps = L.check_layout(d)
        issues = [f"{name}: {why}" for name, rep in sorted(reps.items()) for why in rep["issues"]]
        advice = [f"{name}: {why}" for name, rep in sorted(reps.items()) for why in rep["advice"]]
        layouts: dict[str, int] = {}
        for rep in reps.values():
            layouts[rep["layout"]] = layouts.get(rep["layout"], 0) + 1
        largest = max((max(rep.get("file_bytes") or 0, rep.get("shard_bytes_max") or 0)
                       for rep in reps.values()), default=0)
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(layouts.items()))
        detail = (f"{len(reps)} ledgers in {d.name}/ ({kinds}); largest file {largest:,} bytes, "
                  f"shard cap {L.SHARD_MAX_BYTES:,}, single-file limit {L.FILE_MAX_BYTES:,}")
        if issues:
            detail += " | " + "; ".join(issues[:SAMPLE])
        if advice:
            detail += " | advice: " + "; ".join(advice[:SAMPLE])
        return {"name": self.name, "checked": len(reps), "violations": len(issues),
                "max_violations": self.max_violations, "ok": len(issues) <= self.max_violations,
                "detail": detail}


def make_checks() -> list:
    return [LedgerLayout()]
