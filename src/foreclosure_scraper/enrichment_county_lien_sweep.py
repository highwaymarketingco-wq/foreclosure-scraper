"""raw['rod_lien_sweep'] (adverse instruments recorded against the owner, plus 'screened, none found')
and, for Beaufort NC, raw['marriage_license'], from county-wide register sweeps by document type and
date window (rod/county_sweeps.py).

Audit 2026-10-09, top-80 build list, register platforms CCHS classic / CCHS LRSearch / GovOS
CountyFusion / GovOS-Kofile PublicSearch: liens (ranks 31, 32, 34, 45), atty_rod_lien_checked
(49, 53) and marriage licences (79). The per-owner readers are capped at 30 lookups a county a run
against 2,900 to 3,900 board rows a county; one county-wide read serves every row.

  * Orange, Stanly, Surry NC (CCS classic ASP on a county-run server), Beaufort NC (CCS LRSearch),
    Sumter SC (GovOS CountyFusion), Oconee SC (GovOS/Kofile PublicSearch): every board row with a
    usable owner name gets raw['rod_lien_sweep'], status 'found' (an exact-name match), 'possible'
    (surname and first name only) or 'none_found' ('screened, none found', for window_from ..
    window_to only: an older lien is not claimed absent, and only adverse instrument types were asked
    for: lien, judgment, lis pendens, foreclosure, tax lien; it is not a mortgage check).
  * Beaufort NC marriage licences: the register's Marriages index swept by date (about 275 licences a
    year), matched to person owners; raw['marriage_license'] gets the newest licence naming the owner
    or a dated {'status': 'no_match'}; a licence found by another source is never overwritten by a
    no_match.
  * The stamp is rewritten every run (the sweep is cheap once cached: data/county_sweeps/, git-ignored),
    so a new lien shows up. A wall, an error or a sweep that covered nothing stamps nothing.

ON by default (FORECLOSURE_COUNTY_LIEN_SWEEP=0 turns it off, FORECLOSURE_COUNTY_MARRIAGE_SWEEP=0 the
marriage part); plain HTTP and one WebSocket, no browser. FORECLOSURE_COUNTY_SWEEP_BUDGET_S (default
900 s) bounds each county's register reads; FORECLOSURE_COUNTY_SWEEP_SINCE (default 2016-01-01) is how
far back it goes. Counties run side by side (each its own host; every request is paced per host).
"""
from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable

import structlog

from .models import Listing
from .rod import county_sweeps as CS

log = structlog.get_logger()
_stats_lock = threading.Lock()

ENV_FLAG = "FORECLOSURE_COUNTY_LIEN_SWEEP"
ENV_MARRIAGE = "FORECLOSURE_COUNTY_MARRIAGE_SWEEP"


@dataclass(frozen=True)
class Job:
    kind: str                                  # "lien" | "marriage"
    factory: Callable[[], CS.Reader]


#: (state, county) -> the sweeps run for it. A new platform county is one line here.
SWEEP_COUNTIES: dict[tuple[str, str], tuple[Job, ...]] = {
    **{("NC", c): (Job("lien", (lambda c=c: CS.CchsClassicReader(c))),)
       for c in ("Orange", "Stanly", "Surry", *CS.HOSTED_CCHS)},
    ("NC", "Beaufort"): (Job("lien", lambda: CS.LrSearchReader("Beaufort")),
                         Job("marriage", lambda: CS.MarriageReader("Beaufort"))),
    ("SC", "Sumter"): (Job("lien", lambda: CS.CountyFusionReader("Sumter")),),
    ("SC", "Oconee"): (Job("lien", lambda: CS.PublicSearchReader("oconee")),),
}


def _county_key(li: Listing) -> tuple[str, str]:
    return ((li.state or "").upper(), (li.county or "").replace(" County", "").strip().title())


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _since() -> date:
    try:
        return date.fromisoformat(os.environ.get("FORECLOSURE_COUNTY_SWEEP_SINCE", CS.DEFAULT_SINCE))
    except ValueError:
        return date.fromisoformat(CS.DEFAULT_SINCE)


def _stamp_county(key: tuple[str, str], lis: list[Listing], budget_s: float, since: date, stats: dict) -> None:
    for job in SWEEP_COUNTIES[key]:
        if job.kind == "marriage" and os.environ.get(ENV_MARRIAGE, "1") == "0":
            continue
        entry = {"county": key[1], "state": key[0], "kind": job.kind}
        with _stats_lock:
            stats["counties"].append(entry)
        try:
            reader = job.factory()
            index, res = CS.sweep(reader, since=since, budget_s=budget_s)
        except Exception as exc:  # noqa: BLE001 - one county never stops the pass
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            with _stats_lock:
                stats["not_stamped"] += len(lis)
            log.warning("county_sweep.failed", county=key[1], kind=job.kind, error=entry["error"])
            continue
        entry.update({"platform": res.platform, "windows_read": res.windows_read,
                      "instruments_new": res.instruments_new, "index_size": res.index_size,
                      "window_from": res.window_from, "window_to": res.window_to, "types": res.types,
                      "walled": res.walled, "error": res.error, "budget_exhausted": res.budget_exhausted})
        if res.walled or res.error or not res.window_from:
            with _stats_lock:
                stats["not_stamped"] += len(lis)
            log.warning("county_sweep.no_stamp", county=key[1], kind=job.kind, walled=res.walled, error=res.error)
            continue
        counts = {"found": 0, "possible": 0, "none_found": 0, "no_match": 0, "unmatchable": 0}
        for li in lis:
            owner = (li.owner_name or "").strip()
            if job.kind == "lien":
                stamp = CS.stamp_for(index.match(owner), res)
                target = "rod_lien_sweep"
            else:
                stamp = CS.marriage_stamp(index.match(owner, keep_parties=True), owner, res, key[1])
                target = "marriage_license"
            if stamp is None:
                counts["unmatchable"] += 1
                continue
            if not isinstance(li.raw, dict):
                li.raw = {}
            prior = li.raw.get(target)
            if target == "marriage_license" and isinstance(prior, dict) and stamp.get("status") == "no_match" \
                    and (prior.get("spouse_name") or prior.get("license_date")):
                continue                       # a licence found elsewhere stands
            li.raw[target] = stamp
            counts[stamp["status"]] = counts.get(stamp["status"], 0) + 1
        entry["stamped"] = counts
        with _stats_lock:
            for k, v in counts.items():
                stats[f"{job.kind}_{k}"] = stats.get(f"{job.kind}_{k}", 0) + v


async def enrich_county_lien_sweep(listings: list[Listing]) -> dict:
    if os.environ.get(ENV_FLAG, "1") == "0":
        return {"skipped": f"disabled ({ENV_FLAG}=0)"}
    by_county: dict[tuple[str, str], list[Listing]] = {}
    for li in listings:
        k = _county_key(li)
        if k in SWEEP_COUNTIES and (li.owner_name or "").strip():
            by_county.setdefault(k, []).append(li)
    if not by_county:
        return {"skipped": "no listing in a swept county"}
    stats: dict = {"targets": sum(len(v) for v in by_county.values()), "not_stamped": 0, "counties": [],
                   "started": datetime.now(timezone.utc).isoformat()}
    budget_s = _env_float("FORECLOSURE_COUNTY_SWEEP_BUDGET_S", 900.0)
    since = _since()
    await asyncio.gather(*(asyncio.to_thread(_stamp_county, k, lis, budget_s, since, stats)
                           for k, lis in sorted(by_county.items())))
    log.info("county_sweep.done", **{k: v for k, v in stats.items() if k != "counties"})
    return stats
