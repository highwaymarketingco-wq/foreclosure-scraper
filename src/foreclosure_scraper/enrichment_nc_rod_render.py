"""raw['rod'] (lien existence by owner name) for the NC counties whose register is searched in a
headless browser (RENDER_ROD_CONFIG in enrichment_generic_rod: Harris 'ROD Web Access', Logan's
Blazor and Remote Access apps). The Spartanburg precedent (enrichment_spartanburg_rod): a browser
lookup costs tens of seconds, so the pass is

  * capped per run: each platform's own FORECLOSURE_NC_<PLATFORM>_ROD_MAX lookups per county
    (default 30), enforced inside the adapter, so the chain step shares the same budget;
  * idempotent: a lead that already carries raw['rod'] is skipped (a clean no-match is stamped too,
    so it is not searched again every run);
  * auction-soonest first, and bounded by a wall-clock budget FORECLOSURE_NC_ROD_RENDER_BUDGET_S
    (default 3600 s): leads not reached stay unstamped for the next run;
  * OFF unless the platform's flag is 1 (FORECLOSURE_NC_HARRIS_ROD, ...).

A county that answers with a wall, or reaches its cap, is left for the rest of the run.
raw['rod'] has the same shape as every other ROD enricher (rod.classify.classify_rod_docs).
"""
from __future__ import annotations

import asyncio
import importlib
import os
import time
from datetime import datetime, timezone
from typing import Iterable

import structlog

from .enrichment_generic_rod import RENDER_ROD_CONFIG, platform_enabled
from .models import Listing
from .rod.classify import classify_rod_docs, imminent
from .rod.nc_chain import names_owner, parse_owner, to_rod_doc

log = structlog.get_logger()


def _empty(source: str) -> dict:
    return {"instrument_count": 0, "kinds": {}, "has_mortgage": False, "has_adverse_lien": False,
            "adverse_types": [], "mortgage_count": 0, "satisfaction_count": 0, "open_mortgages_est": 0,
            "instruments": [], "source": source}


async def enrich_marriage_render(listings: Iterable[Listing], *, t0: float, budget_s: float) -> dict:
    """raw['marriage_license'] for the Harris counties (Mecklenburg, Carteret): the register's own Marriage
    index, same guest browser session as the real-estate search (rod/nc_harris.marriage_search). OFF unless
    FORECLOSURE_NC_HARRIS_MARRIAGE=1 AND the Harris platform flag is on. Persons only; a lead that already
    carries raw['marriage_license'] is skipped; a clean "no licence under this name" is stamped
    {status: no_match, checked_at}; walls, caps, errors and a result page longer than the rows read (the
    owner may be on page 2) stay unstamped."""
    from .rod import nc_harris
    out = {"marriage_targets": 0, "marriage_searched": 0, "marriage_found": 0, "marriage_no_match": 0}
    if os.environ.get(nc_harris.MARRIAGE_FLAG, "0") != "1":
        return out
    now = datetime.now(timezone.utc)
    by_county: dict[str, list[Listing]] = {}
    for li in listings:
        key = ((li.state or "").upper(), (li.county or "").strip())
        entry = RENDER_ROD_CONFIG.get(key)
        if entry is None or entry[0] != "nc_harris" or not platform_enabled(entry):
            continue
        if isinstance(li.raw, dict) and li.raw.get("marriage_license"):
            continue
        who = parse_owner(li.owner_name or "")
        if who is None or who.entity:
            continue
        by_county.setdefault(key[1], []).append(li)
    for county, targets in sorted(by_county.items()):
        targets.sort(key=lambda li: not imminent(li, now))
        for li in targets:
            if time.monotonic() - t0 > budget_s:
                return out
            who = parse_owner(li.owner_name)
            out["marriage_targets"] += 1
            res = await asyncio.to_thread(nc_harris.marriage_search, county, who)
            out["marriage_searched"] += 1
            if res.status in ("walled", "capped"):
                break
            if res.status != "ok":
                continue
            hit = nc_harris.marriage_license_from(res.rows, who, county)
            if not isinstance(li.raw, dict):
                li.raw = {}
            if hit:
                li.raw["marriage_license"] = hit
                out["marriage_found"] += 1
            elif res.found is not None and res.found <= len(res.rows):
                li.raw["marriage_license"] = {"status": "no_match", "checked_at": now.isoformat(),
                                              "source": "harris_marriage_index"}
                out["marriage_no_match"] += 1
    return out


async def enrich_nc_rod_render(listings: Iterable[Listing]) -> dict:
    listings = list(listings)
    budget_s = float(os.environ.get("FORECLOSURE_NC_ROD_RENDER_BUDGET_S", "3600"))
    t0 = time.monotonic()
    now = datetime.now(timezone.utc)
    by_county: dict[tuple[str, str], list[Listing]] = {}
    for li in listings:
        key = ((li.state or "").upper(), (li.county or "").strip())
        if key not in RENDER_ROD_CONFIG or not (li.owner_name or "").strip():
            continue
        if isinstance(li.raw, dict) and li.raw.get("rod"):
            continue                                     # idempotent: already has a lien read
        by_county.setdefault(key, []).append(li)

    stats = {"counties": 0, "targets": 0, "searched": 0, "stamped": 0, "with_instruments": 0,
             "with_mortgage": 0, "with_adverse": 0, "errors": 0, "disabled_counties": 0,
             "walled_counties": [], "capped_counties": [], "budget_exhausted": False}
    for (state, county), targets in sorted(by_county.items()):
        entry = RENDER_ROD_CONFIG[(state, county)]
        if not platform_enabled(entry):
            stats["disabled_counties"] += 1
            continue
        mod = importlib.import_module(f"foreclosure_scraper.rod.{entry[0]}")
        adapter = mod.ADAPTER
        stats["counties"] += 1
        targets.sort(key=lambda li: not imminent(li, now))
        for li in targets:
            if time.monotonic() - t0 > budget_s:
                stats["budget_exhausted"] = True
                break
            who = parse_owner(li.owner_name)
            if who is None:
                continue
            stats["targets"] += 1
            try:
                res = await asyncio.to_thread(adapter.search, county, who, "both", None)
            except Exception as exc:  # noqa: BLE001 - one lead never kills the pass
                log.warning("nc_rod_render.failed", county=county, error=f"{type(exc).__name__}: {str(exc)[:120]}")
                stats["errors"] += 1
                continue
            stats["searched"] += 1
            if res.status in ("walled", "capped"):
                stats[f"{res.status}_counties"].append(county)
                break
            if res.status != "ok":
                stats["errors"] += 1
                continue                                 # unstamped: retried next run
            mine = [r for r in res.records if names_owner(who, r.grantors) or names_owner(who, r.grantees)]
            source = f"nc_render:{adapter.platform}"
            summ = (classify_rod_docs([to_rod_doc(r, state, county, adapter.platform) for r in mine], source)
                    if mine else _empty(source))
            summ["fetched_at"] = now.isoformat()
            if res.truncated:
                summ["truncated"] = True
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["rod"] = summ
            stats["stamped"] += 1
            if mine:
                stats["with_instruments"] += 1
                stats["with_mortgage"] += bool(summ.get("has_mortgage"))
                stats["with_adverse"] += bool(summ.get("has_adverse_lien"))
        if stats["budget_exhausted"]:
            break
    stats.update(await enrich_marriage_render(listings, t0=t0, budget_s=budget_s))
    log.info("nc_rod_render.done", **{k: v for k, v in stats.items() if not isinstance(v, list)},
             walled=stats["walled_counties"], capped=stats["capped_counties"])
    return stats
