"""Ingest the Mac's stealth-scraper hand-off file (cloud-split deploy).

In the cloud split (see foreclosure_scraper.source_split), the residential-IP
stealth scrapers run on the Mac, which writes their leads to
``docs/handoff/stealth_leads.json`` and pushes it. The datacenter VM's normal
run picks that file up HERE, as an ordinary source, so those leads flow through
the same enrichment + merge + publish path as everything else.

Each lead keeps its ORIGINAL source (sc_public_index, nc_sos_ucc, ...) — the
orchestrator only fills ``source`` when it is blank — so board provenance stays
correct; this scraper's slug is just the transport.

Datacenter-safe (reads a local file, no browser) so it runs on the VM and is
skipped on the Mac (FORECLOSURE_ROLE=mac). Missing/absent/stale file = leads or
zero, never a hard error.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing

log = structlog.get_logger()

# <repo-root>/docs/handoff/stealth_leads.json — resolved relative to this file
# so it works the same on the Mac and the VM regardless of CWD.
_HANDOFF = Path(__file__).resolve().parents[3] / "docs" / "handoff" / "stealth_leads.json"
# Past this age we still ingest (stale stealth leads beat none) but warn loudly.
_STALE_HOURS = float(os.environ.get("HANDOFF_STALE_HOURS", "72"))


class StealthHandoffScraper(BaseScraper):
    slug = "national.stealth_handoff"
    name = "Stealth hand-off (Mac -> VM cloud split)"
    category = "handoff"
    expected_min_count = 0        # 0 is legitimate (Mac may not have pushed yet)
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        path = Path(os.environ.get("HANDOFF_FILE", _HANDOFF))
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

        # Freshness — advisory only; we still ingest a stale file.
        gen = payload.get("generated_at") if isinstance(payload, dict) else None
        if gen:
            try:
                age_h = (datetime.now(timezone.utc)
                         - datetime.fromisoformat(gen)).total_seconds() / 3600
                (log.warning if age_h > _STALE_HOURS else log.info)(
                    "stealth_handoff.age", hours=round(age_h, 1), stale_after=_STALE_HOURS)
            except Exception:  # noqa: BLE001
                pass

        out: list[Listing] = []
        bad = 0
        for d in rows:
            try:
                out.append(Listing.model_validate(d))
            except Exception:  # noqa: BLE001 - skip a malformed row, keep the rest
                bad += 1
        if bad:
            log.warning("stealth_handoff.some_invalid", dropped=bad, kept=len(out))
        log.info("stealth_handoff.ingested", leads=len(out),
                 sources=len({(li.source or "?") for li in out}))
        return out
