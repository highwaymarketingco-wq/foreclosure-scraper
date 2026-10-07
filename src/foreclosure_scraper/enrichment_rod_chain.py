"""raw['rod_chain']: the deed chain and lien picture per lead, for the NC counties whose register a
platform adapter reads (rod/nc_cott_v4.py, ...). The shape is documented in rod/nc_chain.py: the
last deed into the owner plus up to three earlier conveyances (book/page, recording date, type,
grantor, grantee, the index's short description), and the deeds of trust, satisfactions, lis
pendens, substitutions of trustee and foreclosure notices that name the owner.

SWITCHES (all OFF by default)
  FORECLOSURE_ROD_CHAIN=1          master switch for this enricher
  <platform flag>=1                each platform's own flag from the registry
                                   (FORECLOSURE_NC_COTT_ROD, ...), shared with enrich_generic_rod
  FORECLOSURE_ROD_CHAIN_DEPTH      earlier conveyances to walk back (default 3)
  FORECLOSURE_ROD_CHAIN_REFRESH_DAYS / _REFRESH_HOT_DAYS   re-read after 30 / 7 days
  NC_ROD_MAX_LOOKUPS_PER_COUNTY    the adapters' per-run cap (default 30 name searches per county;
                                   a chain spends 1 + one per link walked)
  FORECLOSURE_ROD_CHAIN_BUDGET_S   wall-clock budget for the pass (default 1800): no new lead is
                                   started after it; leads not reached stay unstamped for next run

POLITENESS: counties run one after another, leads within a county one after another, through
the adapters' paced client (>= 1.6 s per host, one request at a time). A county that answers with
a wall, or reaches the cap, is left for the rest of the run; its leads stay unstamped and are
retried on a later run.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import time
from datetime import datetime, timezone
from typing import Iterable

import structlog

from .enrichment_generic_rod import CHAIN_ONLY_CONFIG, RENDER_ROD_CONFIG, ROD_CONFIG, platform_enabled
from .models import Listing
from .rod.classify import imminent

log = structlog.get_logger()

_STOP_COUNTY = ("walled", "capped")
_RETRY_LATER = ("walled", "capped", "error")


def chain_registry() -> dict[tuple[str, str], tuple]:
    """(state, county) -> registry entry, for every entry whose module has chain()."""
    out: dict[tuple[str, str], tuple] = {}
    for key, entry in {**ROD_CONFIG, **RENDER_ROD_CONFIG, **CHAIN_ONLY_CONFIG}.items():
        mod = _module(entry[0])
        if mod is not None and hasattr(mod, "chain"):
            out[key] = entry
    return out


def _module(name: str):
    try:
        return importlib.import_module(f"foreclosure_scraper.rod.{name}")
    except ImportError:
        return None


def _age_days(li: Listing, now: datetime) -> float | None:
    rc = (li.raw or {}).get("rod_chain") if isinstance(li.raw, dict) else None
    fa = (rc or {}).get("fetched_at")
    if not fa:
        return None
    try:
        dt = datetime.fromisoformat(fa)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 86400.0


def _due(li: Listing, now: datetime, hot_days: float, base_days: float) -> bool:
    age = _age_days(li, now)
    return age is None or age >= (hot_days if imminent(li, now) else base_days)


async def enrich_rod_chain(listings: Iterable[Listing]) -> dict:
    if os.environ.get("FORECLOSURE_ROD_CHAIN", "0") != "1":
        return {"skipped": "disabled (set FORECLOSURE_ROD_CHAIN=1)"}
    now = datetime.now(timezone.utc)
    base_days = float(os.environ.get("FORECLOSURE_ROD_CHAIN_REFRESH_DAYS", "30"))
    hot_days = float(os.environ.get("FORECLOSURE_ROD_CHAIN_REFRESH_HOT_DAYS", "7"))
    depth = int(os.environ.get("FORECLOSURE_ROD_CHAIN_DEPTH", "3"))
    budget_s = float(os.environ.get("FORECLOSURE_ROD_CHAIN_BUDGET_S", "1800"))
    t0 = time.monotonic()
    registry = chain_registry()

    by_county: dict[tuple[str, str], list[Listing]] = {}
    for li in listings:
        key = ((li.state or "").upper(), (li.county or "").strip())
        if key not in registry or not (li.owner_name or "").strip():
            continue
        if _due(li, now, hot_days, base_days):
            by_county.setdefault(key, []).append(li)

    stats = {"counties": 0, "targets": 0, "stamped": 0, "with_last_deed": 0, "with_prior": 0,
             "with_open_dot_est": 0, "with_lis_pendens": 0, "with_substitution": 0,
             "walled_counties": [], "capped_counties": [], "errors": 0, "disabled_counties": 0,
             "budget_exhausted": False}
    for (state, county), targets in sorted(by_county.items()):
        entry = registry[(state, county)]
        if not platform_enabled(entry):
            stats["disabled_counties"] += 1
            continue
        mod = _module(entry[0])
        stats["counties"] += 1
        targets.sort(key=lambda li: not imminent(li, now))       # auctions soonest first
        for li in targets:
            if time.monotonic() - t0 > budget_s:
                stats["budget_exhausted"] = True
                break
            stats["targets"] += 1
            try:
                res = await asyncio.to_thread(mod.chain, county, li.owner_name, state=state, depth=depth)
            except Exception as exc:  # noqa: BLE001 - one lead never kills the pass
                log.warning("rod_chain.failed", county=county, error=f"{type(exc).__name__}: {str(exc)[:120]}")
                stats["errors"] += 1
                continue
            status = res.get("status")
            if status in _RETRY_LATER:
                if status == "error":
                    stats["errors"] += 1
                if status in _STOP_COUNTY:
                    stats[f"{status}_counties"].append(county)
                    break
                continue
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["rod_chain"] = res
            stats["stamped"] += 1
            liens = res.get("liens") or {}
            stats["with_last_deed"] += bool(res.get("last_deed"))
            stats["with_prior"] += bool(res.get("prior_instruments"))
            stats["with_open_dot_est"] += bool(liens.get("open_deeds_of_trust_est"))
            stats["with_lis_pendens"] += bool(liens.get("lis_pendens"))
            stats["with_substitution"] += bool(liens.get("substitutions_of_trustee"))
    log.info("rod_chain.done", **{k: v for k, v in stats.items() if not isinstance(v, list)},
             walled=stats["walled_counties"], capped=stats["capped_counties"])
    return stats
