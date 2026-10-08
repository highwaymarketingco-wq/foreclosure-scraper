"""Ingest the Mac's stealth-scraper hand-off file (cloud-split deploy).

In the cloud split (see foreclosure_scraper.source_split), the residential-IP
stealth scrapers run on the Mac, which writes their leads to
``docs/handoff/stealth_leads/`` (manifest.json + one JSON Lines shard per source,
see foreclosure_scraper.stealth_handoff_store) and pushes it. The datacenter VM's
normal run picks that up HERE, as an ordinary source, so those leads flow through
the same enrichment + merge + publish path as everything else. The legacy single
file ``docs/handoff/stealth_leads.json`` is still read when no manifest exists (or
it is the newer of the two), so a checkout from before the 2026-10-09 switch to
shards still ingests: the single file had reached 93.8 MiB, 1.2 MiB under the
repo's 95 MiB commit gate.

Each lead keeps its ORIGINAL source (sc_public_index, nc_sos_ucc, ...) — the
orchestrator only fills ``source`` when it is blank — so board provenance stays
correct; this scraper's slug is just the transport.

Datacenter-safe (reads a local file, no browser) so it runs on the VM and is
skipped on the Mac (FORECLOSURE_ROLE=mac). Missing/absent/stale file = leads or
zero, never a hard error.

FOUND 2026-10-04 (HERMES extraction-completeness audit, batch 18), the
exact "silently reporting for N+ weeks" class the audit protocol calls out
by name. The repo's own `docs/handoff/stealth_leads.json` is dated
`generated_at: 2026-09-01T23:20:57Z` -- 32+ DAYS stale as of today, 10x
past this module's own 72h "stale but still ingest" advisory threshold.
Root cause is NOT in this file: `deploy/mac/install_stealth_schedule.sh`
describes a daily 06:00 launchd job that is supposed to run
`scripts/run_stealth_sources.py` on this Mac and push the hand-off, but
`launchctl list | grep stealth` returns NOTHING and
`~/Library/LaunchAgents/com.highway.foreclosure.stealth-handoff.plist`
does not exist on this machine -- the schedule was never (re-)installed,
or was removed, and `logs/mac-stealth.log`'s last line is also dated
Sep 1, confirming the writer side simply has not run since. This lines up
with this project's own tracked `project_oracle_vm_revival` status (the
Oracle VM side of this exact cloud split has been idle since 9/3 and was
"built but never turned on") -- so this is a known, already-tracked
infrastructure gap, not a new hidden one, and NOT something this batch
re-enables unilaterally: flipping the Mac-side scheduler back on is an
operational change with real side effects (unattended scraper runs +
automatic git pushes) that overlaps with that already-in-progress revival
effort, not a scraper code fix. Flagged in this session's memory update
instead. What IS fixed here, safely and with zero operational side
effects: `fetch()` used to log this exact situation at the same
`log.warning` level as an ordinary few-hours-stale file, indistinguishable
in run output from a routine, healthy staleness blip -- a severely stale
(7+ days) file now also sets `self.last_outcome = OUTCOME_PARTIAL` with an
explicit reason, so a run-outcome scan (the same kind of scan that caught
this) surfaces it immediately instead of requiring someone to open the
JSON file and read `generated_at` by hand.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import structlog

from ... import stealth_handoff_store as store
from ...base_scraper import BaseScraper, OUTCOME_PARTIAL
from ...models import Listing

log = structlog.get_logger()

# <repo-root>/docs/handoff/stealth_leads.json — resolved relative to this file
# so it works the same on the Mac and the VM regardless of CWD.
# parents[4] = repo root: this file is 4 levels under it
# (scrapers/national/stealth_handoff.py -> scrapers/national -> scrapers ->
# foreclosure_scraper -> src -> repo root). Was parents[3] (= src/, one level
# too shallow), so this scraper always looked for src/docs/handoff/... (never
# existed) and silently returned [] on every run -- found 2026-09-15 via live
# zero-row audit; the real file at docs/handoff/stealth_leads.json (7,270
# leads from the Mac's residential-IP stealth scrapers) was never read.
_HANDOFF_ROOT = Path(__file__).resolve().parents[4] / "docs" / "handoff"
# The legacy single file (read as a fallback) and the sharded hand-off (preferred).
_HANDOFF = store.legacy_file(_HANDOFF_ROOT)
_HANDOFF_DIR = store.shard_dir(_HANDOFF_ROOT)
# Past this age we still ingest (stale stealth leads beat none) but warn loudly.
_STALE_HOURS = float(os.environ.get("HANDOFF_STALE_HOURS", "72"))
# FOUND 2026-10-04 (batch 18, see module docstring): a plain log.warning at
# the SAME level whether the file is 4 hours or 4 weeks past _STALE_HOURS
# makes a severe, ongoing outage (the real Sep 1 -> Oct 4 case) blend into
# routine staleness noise. Past THIS age (7 days, chosen as clearly "the
# pipeline feeding this is broken" rather than "a bit late"), also flip
# self.last_outcome so a run-outcome scan surfaces it without anyone having
# to open the JSON and read generated_at by hand.
_SEVERE_STALE_HOURS = float(os.environ.get("HANDOFF_SEVERE_STALE_HOURS", str(24 * 7)))


class StealthHandoffScraper(BaseScraper):
    slug = "national.stealth_handoff"
    name = "Stealth hand-off (Mac -> VM cloud split)"
    category = "handoff"
    expected_min_count = 0        # 0 is legitimate (Mac may not have pushed yet)
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        # HANDOFF_FILE overrides the location: a legacy single file, a manifest.json, or the
        # shard directory.
        override = os.environ.get("HANDOFF_FILE")
        if override:
            p = Path(override)
            if p.is_dir() or p.name == store.MANIFEST:
                return self._read_sharded(p if p.is_dir() else p.parent)
            return self._read_legacy(p)

        manifest_path = _HANDOFF_DIR / store.MANIFEST
        if manifest_path.exists():
            m = store.read_manifest(manifest_path)
            if m is not None:
                if _HANDOFF.exists() and _is_newer(store.peek_generated_at(_HANDOFF),
                                                   m.get("generated_at")):
                    # Only an old writer can produce this (the new one deletes the legacy
                    # file): read whichever hand-off is the newer one.
                    log.warning("stealth_handoff.legacy_newer_than_shards",
                                legacy=str(_HANDOFF), shards=str(_HANDOFF_DIR))
                    return self._read_legacy(_HANDOFF)
                return self._read_sharded(_HANDOFF_DIR, m)
            log.warning("stealth_handoff.manifest_unreadable", path=str(manifest_path))
            if not _HANDOFF.exists():
                self._partial(f"hand-off manifest {manifest_path} is unreadable and no legacy "
                              f"file exists; no stealth leads ingested")
                return []
            self._partial(f"hand-off manifest {manifest_path} is unreadable; ingested the "
                          f"legacy file {_HANDOFF.name} instead (older data)")
        return self._read_legacy(_HANDOFF)

    # ------------------------------------------------------------------ helpers
    def _partial(self, reason: str) -> None:
        self.last_outcome = OUTCOME_PARTIAL
        self.last_reason = (f"{self.last_reason}; {reason}"
                            if getattr(self, "last_reason", "") else reason)

    def _note_freshness(self, gen: object) -> None:
        """Freshness is advisory only: a stale hand-off is still ingested."""
        if not gen:
            return
        try:
            age_h = (datetime.now(timezone.utc)
                     - datetime.fromisoformat(str(gen))).total_seconds() / 3600
            (log.warning if age_h > _STALE_HOURS else log.info)(
                "stealth_handoff.age", hours=round(age_h, 1), stale_after=_STALE_HOURS)
            if age_h > _SEVERE_STALE_HOURS:
                # FOUND 2026-10-04 (batch 18): surface this distinctly
                # from routine staleness -- see module docstring.
                self.last_outcome = OUTCOME_PARTIAL
                self.last_reason = (
                    f"hand-off file is severely stale ({age_h / 24:.1f} days old, "
                    f"generated_at={gen}) -- the Mac-side scheduled job "
                    f"(scripts/run_stealth_sources.py) does not appear to be "
                    f"running; ingesting the stale data anyway"
                )
                log.warning("stealth_handoff.severely_stale", days=round(age_h / 24, 1),
                            generated_at=gen)
        except Exception:  # noqa: BLE001
            pass

    def _validate(self, rows: Iterable[object]) -> list[Listing]:
        out: list[Listing] = []
        bad = 0
        for d in rows:
            try:
                out.append(Listing.model_validate(d))
            except Exception:  # noqa: BLE001 - skip a malformed row, keep the rest
                bad += 1
        if bad:
            log.warning("stealth_handoff.some_invalid", dropped=bad, kept=len(out))
        return out

    def _read_legacy(self, path: Path) -> list[Listing]:
        if not path.exists():
            log.info("stealth_handoff.absent", path=str(path),
                     note="Mac has not pushed a hand-off yet (or single-host run)")
            return []
        try:
            payload = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001 - a bad file must not fail the run
            log.warning("stealth_handoff.unreadable", path=str(path), error=str(exc)[:200])
            return []

        rows = payload.get("leads", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            log.warning("stealth_handoff.bad_shape", type=type(rows).__name__)
            return []

        self._note_freshness(payload.get("generated_at") if isinstance(payload, dict) else None)
        out = self._validate(rows)
        log.info("stealth_handoff.ingested", leads=len(out), layout="legacy_file",
                 sources=len({(li.source or "?") for li in out}))
        return out

    def _read_sharded(self, directory: Path, manifest: dict | None = None) -> list[Listing]:
        m = manifest if manifest is not None else store.read_manifest(directory)
        if m is None:
            log.warning("stealth_handoff.manifest_unreadable", path=str(directory))
            self._partial(f"hand-off manifest in {directory} is absent or unreadable; "
                          f"no stealth leads ingested")
            return []
        self._note_freshness(m.get("generated_at"))
        stats: dict[str, int] = {}
        out = self._validate(store.iter_shard_rows(directory, m, stats))
        lost = stats.get("shards_missing", 0) + stats.get("shards_corrupt", 0)
        if lost or stats.get("count_mismatch") or stats.get("lines_bad"):
            log.warning("stealth_handoff.shard_problems", **stats)
        if lost:
            self._partial(f"{lost} of {len(m.get('shards') or [])} hand-off shards missing or "
                          f"corrupt ({stats.get('shards_missing', 0)} missing, "
                          f"{stats.get('shards_corrupt', 0)} corrupt); ingested the rest")
        log.info("stealth_handoff.ingested", leads=len(out), layout="shards",
                 shards=stats.get("shards_read", 0), manifest_count=m.get("lead_count"),
                 sources=len({(li.source or "?") for li in out}))
        return out


def _is_newer(a: object, b: object) -> bool:
    """True when ISO timestamp a is strictly later than b (False when either is unparseable)."""
    try:
        return datetime.fromisoformat(str(a)) > datetime.fromisoformat(str(b))
    except (TypeError, ValueError):
        return False
