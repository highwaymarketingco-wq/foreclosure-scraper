"""Marriage-index check from the county register (Cott eSearch v4 guest search, MARRIAGES index).

Audit 2026-10-09, top-80 build list ranks 58 and 65 (marriage_license over Cott registers). The
enricher that used to fill raw['marriage_license'] (enrichment_marriage_license) is retired: it read
only the Aumentum tenants through an impersonating adapter. Six Cott v4 tenants publish the county's
marriage index in the same guest search the lien lookups use (Onslow, Alamance, Alexander, Pamlico,
Edgecombe, Rutherford: the 'Index Type' list says MARRIAGES, code MAR). This pass runs the same
paced, click-through-only name search with that one index selected (rod/register_checks.CottV4Marriage)
for the person owners of those counties:
  a marriage row naming the owner -> raw['marriage_license'] {spouse_name, license_date, book, page,
                                     match_confidence, searched_name, source, checked_at}
  an ok, untruncated, empty answer -> {'status': 'no_match', 'checked_at', 'source'} (screened, none found)
  walled / capped / too_many / error / truncated list -> nothing written, retried next run.
Counties whose register carries no marriage index, or hides it behind a login or a challenge, are
never searched or stamped (rod/register_checks.MARRIAGE_VERDICTS holds the live evidence).

The lien side of these registers ('screened, none found' on raw['rod']) is enrichment_generic_rod's
own stamp: the Cott v4, Tyler, Polk (rod/cott) and Marlboro (sc_cott_esearch) modules now report a
status (search_by_name_status), which is what lets it tell a clean empty answer from a failed fetch.

COUNTY-WIDE SWEEPS (the part that reaches every row). The per-owner searches above are capped at 30 a
county a run, against 800 to 9,300 board rows a county. rod/cott_sweep.py reads each county's Date Range
search once by kind and window (adverse kinds for liens, the MARRIAGES index for licences; a few dozen
requests for several years, cached in data/county_sweeps/) and rod/county_sweeps.py matches every board
owner to it offline: raw['rod_lien_sweep'] (found / possible / none_found for the window swept only,
adverse kinds only) and raw['marriage_license'] (found / possible / no_match for the window swept). Ten
counties for liens (Onslow, Pitt, Alamance, Alexander, Pamlico, Polk, Edgecombe, Rutherford, Graham, Nash),
six of them for marriages. Rowan is a challenge page and is not swept. The per-owner marriage search runs
only for rows the sweep left without a block. Flags: FORECLOSURE_REGISTER_SWEEP (default 1),
FORECLOSURE_REGISTER_SWEEP_BUDGET_S (the whole sweep phase, per county thread, split between its lien and
marriage reads; default 1800), FORECLOSURE_REGISTER_SWEEP_SINCE
(default 2020-01-01).

COST. 1.6 s between two requests to a host, one at a time per host, a click-through only, a per-county
cap of NC_ROD_MAX_LOOKUPS_PER_COUNTY (30) on the marriage platform's own budget, the whole pass under
FORECLOSURE_REGISTER_CHECKS_BUDGET_S. Flag FORECLOSURE_REGISTER_CHECKS (default 1) and the Cott
platform flag FORECLOSURE_NC_COTT_ROD both gate it.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import date, datetime, timezone
from typing import Any

import structlog

from .models import Listing
from .rod import county_sweeps as CS
from .rod import cott_sweep as CW
from .rod import register_checks as RC
from .rod.classify import imminent
from .rod.nc_chain import parse_owner

log = structlog.get_logger()

ENV_FLAG = "FORECLOSURE_REGISTER_CHECKS"
COTT_FLAG = "FORECLOSURE_NC_COTT_ROD"
MAX_PER_COUNTY = int(os.environ.get("REGISTER_CHECKS_MAX_PER_COUNTY", "40"))
BUDGET_S = float(os.environ.get("FORECLOSURE_REGISTER_CHECKS_BUDGET_S", "900"))
COUNTY_CONCURRENCY = int(os.environ.get("REGISTER_CHECKS_COUNTY_CONCURRENCY", "6"))


def marriage_lookup(county: str, owner: str):
    """(status, records, truncated, OwnerName). Blocking; a person owner only."""
    who = parse_owner(owner)
    if who is None or who.entity:
        return "noname", [], False, None
    res = RC.MARRIAGE_ADAPTER.search(county, who, "both", None)
    return res.status, list(res.records), bool(res.truncated), who


def _apply(li: Listing, status: str, records: list, trunc: bool, who, county: str, now_iso: str, stats: dict) -> None:
    if status != "ok" or who is None:
        stats["unchecked_" + (status if status in ("walled", "capped", "too_many") else "error")] += 1
        return
    if not isinstance(li.raw, dict):
        li.raw = {}
    block = RC.marriage_block(records, who, county=county, now_iso=now_iso)
    if block:
        li.raw["marriage_license"] = block
        stats["match"] += 1
    elif trunc:
        stats["truncated_not_stamped"] += 1          # a truncated list cannot prove "no marriage"
    else:
        li.raw["marriage_license"] = RC.no_match_block(now_iso)
        stats["no_match"] += 1


SWEEP_FLAG = "FORECLOSURE_REGISTER_SWEEP"
DEFAULT_SINCE = "2020-01-01"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _since() -> date:
    try:
        return date.fromisoformat(os.environ.get("FORECLOSURE_REGISTER_SWEEP_SINCE", DEFAULT_SINCE))
    except ValueError:
        return date.fromisoformat(DEFAULT_SINCE)


def sweep_jobs(county: str) -> list[tuple[str, Any]]:
    """[(kind, reader factory)] swept for one county."""
    jobs: list[tuple[str, Any]] = []
    if county in CW.LIEN_COUNTIES:
        jobs.append(("lien", lambda c=county: CW.CottLienReader(c)))
    if county in RC.MARRIAGE_ADAPTER.counties:
        jobs.append(("marriage", lambda c=county: CW.CottMarriageReader(c)))
    return jobs


def _stamp_county(county: str, lis: list[Listing], budget_s: float, since: date, stats: dict) -> None:
    """budget_s is this county's whole sweep time; each of its jobs (lien, marriage) gets an equal share."""
    jobs = sweep_jobs(county)
    per_job = max(30.0, budget_s / max(1, len(jobs)))
    for kind, factory in jobs:
        entry = {"county": county, "kind": kind}
        stats["sweeps"].append(entry)
        try:
            index, res = CS.sweep(factory(), since=since, budget_s=per_job)
        except Exception as exc:  # noqa: BLE001 - one county never stops the pass
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            stats["sweep_not_stamped"] += len(lis)
            log.warning("register_sweep.failed", county=county, kind=kind, error=entry["error"])
            continue
        entry.update({"windows_read": res.windows_read, "instruments_new": res.instruments_new,
                      "index_size": res.index_size, "window_from": res.window_from, "window_to": res.window_to,
                      "types": res.types, "walled": res.walled, "error": res.error,
                      "budget_exhausted": res.budget_exhausted})
        if res.walled or res.error or not res.window_from:
            stats["sweep_not_stamped"] += len(lis)
            log.warning("register_sweep.no_stamp", county=county, kind=kind, walled=res.walled, error=res.error)
            continue
        counts: dict[str, int] = {}
        for li in lis:
            owner = (li.owner_name or "").strip()
            if kind == "lien":
                stamp, target = CS.stamp_for(index.match(owner), res), "rod_lien_sweep"
            else:
                stamp, target = CS.marriage_stamp(index.match(owner, keep_parties=True), owner, res, county), "marriage_license"
            if stamp is None:
                counts["unmatchable"] = counts.get("unmatchable", 0) + 1
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
        for k, v in counts.items():
            stats[f"sweep_{kind}_{k}"] = stats.get(f"sweep_{kind}_{k}", 0) + v


async def enrich_register_checks(listings: list[Listing]) -> dict:
    stats: dict[str, Any] = {k: 0 for k in (
        "counties", "targets", "searched", "match", "no_match", "truncated_not_stamped", "unchecked_walled",
        "unchecked_capped", "unchecked_too_many", "unchecked_error", "disabled_counties", "sweep_not_stamped")}
    stats["budget_exhausted"] = False
    stats["sweeps"] = []
    if os.environ.get(ENV_FLAG, "1") == "0":
        stats["disabled"] = True
        return stats
    if os.environ.get(COTT_FLAG, "0") == "0":         # the Cott platform's own switch (vm_lib exports 1)
        stats["disabled_counties"] = len(CW.LIEN_COUNTIES)
        return stats
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # 1. county-wide sweeps: every board row of a swept county
    swept: dict[str, list[Listing]] = {}
    for li in listings:
        co = (li.county or "").replace(" County", "").strip()
        if (li.state or "").upper() == "NC" and co in CW.LIEN_COUNTIES and (li.owner_name or "").strip():
            swept.setdefault(co, []).append(li)
    if swept and os.environ.get(SWEEP_FLAG, "1") != "0":
        budget_s, since = _env_float("FORECLOSURE_REGISTER_SWEEP_BUDGET_S", 1800.0), _since()
        await asyncio.gather(*(asyncio.to_thread(_stamp_county, c, lis, budget_s, since, stats)
                               for c, lis in sorted(swept.items())))

    # 2. the per-owner marriage search, for the rows the sweep left without a block
    by_county: dict[str, list[Listing]] = {}
    for li in listings:
        co = (li.county or "").replace(" County", "").strip()
        if (li.state or "").upper() != "NC" or co not in RC.MARRIAGE_ADAPTER.counties or not li.owner_name:
            continue
        if isinstance(li.raw, dict) and li.raw.get("marriage_license"):
            continue                                  # a match or a dated no-match already
        by_county.setdefault(co, []).append(li)

    t0 = time.monotonic()
    sem = asyncio.Semaphore(max(1, COUNTY_CONCURRENCY))

    def out_of_time() -> bool:
        if time.monotonic() - t0 > BUDGET_S:
            stats["budget_exhausted"] = True
            return True
        return False

    async def one_county(county: str, rows: list[Listing]) -> None:
        rows = sorted(rows, key=lambda li: not imminent(li, now))[:MAX_PER_COUNTY]
        async with sem:
            if out_of_time():
                return
            stats["counties"] += 1
            stats["targets"] += len(rows)
            for li in rows:
                if out_of_time():
                    return
                try:
                    status, recs, trunc, who = await asyncio.to_thread(marriage_lookup, county, li.owner_name or "")
                except Exception as exc:  # noqa: BLE001 - a lookup never kills a run
                    log.debug("register_checks.marriage_failed", county=county, error=str(exc)[:80])
                    status, recs, trunc, who = "error", [], False, None
                if status == "noname":
                    continue                          # an entity owner: a marriage check does not apply
                stats["searched"] += 1
                _apply(li, status, recs, trunc, who, county, now_iso, stats)
                if status == "walled":
                    break

    order = sorted(by_county.items(), key=lambda kv: (-sum(1 for li in kv[1] if imminent(li, now)), -len(kv[1]), kv[0]))
    try:
        await asyncio.gather(*(one_county(c, r) for c, r in order))
    except asyncio.CancelledError:
        log.warning("register_checks.cancelled", **stats)
        raise
    log.info("register_checks.done", **stats)
    return stats
