"""raw['rod_lien_sweep'] (adverse liens recorded against the owner, plus 'screened, none found') for
the counties whose register can be swept by document type: Horry and Pickens SC (Harris AcclaimWeb).

Audit 2026-10-09 top-80 build list: liens (Horry rank 10, 11,841 rows; Pickens marriage_license
rank 67 is a different cell, see docs/audit_2026-10-09/top80_logan_harris.md). The per-owner name
search of rod/acclaim_names.py is capped at 30 lookups a county a run, so most rows of these
counties never had a register lien check. This pass reads the register once, county-wide, by
document type and date window (rod/lien_sweep.py: about 10 s per year of data, cached), and
matches every board owner to the swept instruments offline.

  * every board row of a swept county with a usable owner name gets raw['rod_lien_sweep'];
  * status 'found' (a parcel number or surname + first name + middle initial agree), 'possible'
    (surname and first name only) or 'none_found' ('screened, none found', for window_from ..
    window_to only: an older lien is not claimed absent);
  * the stamp is rewritten every run (the sweep is cheap once cached), so a new lien shows up and
    a satisfied one is not re-claimed (satisfactions are not swept; the lien instrument stays as
    history, which is what a title check wants to see);
  * ON by default (FORECLOSURE_SC_LIEN_SWEEP=0 turns it off); wall-aware (RodWalled stamps nothing);
    FORECLOSURE_LIEN_SWEEP_BUDGET_S (default 600 s) bounds the register reads and the sweep runs
    newest month first, FORECLOSURE_LIEN_SWEEP_SINCE (default 2016-01-01) is how far back it goes.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone

import structlog

from .models import Listing
from .rod import lien_sweep as LS

log = structlog.get_logger()

DEFAULT_SINCE = "2016-01-01"


def _parcel(li: Listing) -> str | None:
    return getattr(li, "parcel_id", None)


def _owner(li: Listing) -> str:
    return (li.owner_name or "").strip()


def _sweep_and_stamp(targets_by_county: dict[str, list[Listing]], budget_s: float, since: date,
                     stats: dict) -> None:
    per_county = max(60.0, budget_s / max(1, len(targets_by_county)))
    today_s = datetime.now(timezone.utc).date().isoformat()
    for county, lis in targets_by_county.items():
        index, res = LS.sweep_county(county, since=since, budget_s=per_county)
        stats["counties"].append({"county": res.county, "months_read": res.months_read,
                                  "months_cached": res.months_cached, "instruments_new": res.instruments_new,
                                  "index_size": index.size, "window_from": res.window_from,
                                  "window_to": res.window_to, "walled": res.walled, "error": res.error,
                                  "budget_exhausted": res.budget_exhausted})
        if res.walled or res.error or not res.window_from:
            stats["not_stamped"] += len(lis)
            log.warning("lien_sweep.no_stamp", county=res.county, walled=res.walled, error=res.error)
            continue
        for li in lis:
            hits = index.match(_owner(li), _parcel(li))
            stamp = LS.stamp_for(hits, res, today_s)
            if stamp is None:
                stats["unmatchable"] += 1
                continue
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["rod_lien_sweep"] = stamp
            stats["stamped"] += 1
            stats[stamp["status"]] += 1


async def enrich_register_lien_sweep(listings: list[Listing]) -> dict:
    """Stamp raw['rod_lien_sweep'] on every listing of a swept county. Returns the run stats."""
    stats: dict = {"counties": [], "targets": 0, "stamped": 0, "found": 0, "possible": 0, "none_found": 0,
                   "unmatchable": 0, "not_stamped": 0}
    if os.environ.get(LS.ENV_FLAG, "1") == "0":
        return {"skipped": f"{LS.ENV_FLAG}=0"}
    by_county: dict[str, list[Listing]] = {}
    for li in listings:
        if not _owner(li) or not LS.is_sweep_county(li.state or "", li.county or ""):
            continue
        by_county.setdefault((li.county or "").replace(" County", "").strip(), []).append(li)
        stats["targets"] += 1
    if not by_county:
        return {"skipped": "no listing in a swept county"}
    try:
        since = date.fromisoformat(os.environ.get("FORECLOSURE_LIEN_SWEEP_SINCE", DEFAULT_SINCE))
    except ValueError:
        since = date.fromisoformat(DEFAULT_SINCE)
    try:
        budget_s = float(os.environ.get("FORECLOSURE_LIEN_SWEEP_BUDGET_S", "600"))
    except ValueError:
        budget_s = 600.0
    await asyncio.to_thread(_sweep_and_stamp, by_county, budget_s, since, stats)
    log.info("lien_sweep.done", **{k: v for k, v in stats.items() if k != "counties"})
    return stats
