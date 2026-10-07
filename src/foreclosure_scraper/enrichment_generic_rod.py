"""Generic ROD lien-existence enricher for COTT + Kofile + Acclaim platforms.

These rod modules all expose a ``search_by_name(state, county, name)`` function
that returns ``list[RodDoc]`` — same interface as CCHS. This enricher wraps all
three into one pass, attaches ``raw['rod']`` in the same shape as CCHS/Gaston,
and is default-ON. Disable per-platform via env vars.

Coverage added:
  - Polk NC        → COTT       (228 listings, 0% ROD)
  - Pickens SC     → Acclaim    (2,824 listings, 7% ROD)
  - Oconee SC      → Kofile     (1,675 listings, 0% ROD)
  - Union SC       → COTT RecordRoom (501 listings, 0% ROD)  [if search_by_name added]

Note: Logan ROD (McDowell/Mitchell/Transylvania NC, Laurens SC) only has
discover_recent_nods(), not search_by_name — covered by rod_name_index enricher.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Optional

import structlog

from .models import Listing
from .rod.classify import classify_rod_docs, is_stale, refresh_windows
from .name_normalize import first_last_parts

log = structlog.get_logger()

# (state, county) -> (module_name, env_flag[, default])
# Acclaim (Pickens SC) and cott_recordroom (Union SC) only have discover_recent_nods,
# not search_by_name — they're covered by rod_name_index enricher instead.
# The optional third element is the flag's default when the env var is unset: "1" (on, the
# original entries) or "0" (off until the owner turns the platform on). The NC platform adapters
# added 2026-10-07 (rod/nc_cott_v4.py, ...) are proven live on test searches but their yield on
# board leads is not, so they ship OFF; set the platform's flag to 1 to run them. Those modules
# also expose chain() (the deed chain + lien picture), read by enrichment_rod_chain.py from this
# same registry. Their per-run cap is NC_ROD_MAX_LOOKUPS_PER_COUNTY (default 30), enforced inside
# the adapter whatever _MAX_PER_COUNTY below says.
ROD_CONFIG = {
    ("NC", "Polk"):          ("cott",  "FORECLOSURE_COTT_ROD"),
    ("SC", "Oconee"):        ("kofile", "FORECLOSURE_KOFILE_ROD"),
    # Cott eSearch v4, guest name index with no sign-in (rod/nc_cott_v4.py)
    ("NC", "Alexander"):     ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Graham"):        ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Granville"):     ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Jackson"):       ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Jones"):         ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Nash"):          ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Pamlico"):       ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Wayne"):         ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    # the same app behind the vendor's no-credential 'Sign in as a Guest' button (a click-through)
    ("NC", "Alamance"):      ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Edgecombe"):     ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Halifax"):       ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Lenoir"):        ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Onslow"):        ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Pitt"):          ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Rutherford"):    ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Scotland"):      ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Wilson"):        ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    # 'The Lookup' (Logan / BIS) name index (rod/nc_lookup.py). Clay, Haywood, Yancey are also read
    # by enrichment_rod_lookup (raw['rod_lookup']) and Transylvania, McDowell, Mitchell by the
    # rod/logan.py NOD sweep; neither writes raw['rod'], so these entries add, not replace.
    ("NC", "Avery"):         ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    ("NC", "Bertie"):        ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    ("NC", "Columbus"):      ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    ("NC", "Macon"):         ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    ("NC", "Robeson"):       ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    ("NC", "Clay"):          ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    ("NC", "Haywood"):       ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    ("NC", "Yancey"):        ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    ("NC", "Transylvania"):  ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    ("NC", "McDowell"):      ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    ("NC", "Mitchell"):      ("nc_lookup", "FORECLOSURE_NC_LOOKUP_ROD", "0"),
    # BIS 'Online Record System' name index, NC side (rod/nc_ors.py; the SC counties on the same
    # platform are read by enrichment_rod_name_index)
    ("NC", "New Hanover"):   ("nc_ors", "FORECLOSURE_NC_ORS_ROD", "0"),
    ("NC", "Davidson"):      ("nc_ors", "FORECLOSURE_NC_ORS_ROD", "0"),
    ("NC", "Forsyth"):       ("nc_ors", "FORECLOSURE_NC_ORS_ROD", "0"),
    ("NC", "Guilford"):      ("nc_ors", "FORECLOSURE_NC_ORS_ROD", "0"),
    # Courthouse Computer Systems classic search on a county-run server (rod/nc_cchs_classic.py).
    # The vendor-hosted us3/us4/us5 tenants answer an ordinary browser with a Cloudflare challenge
    # and are left to a person.
    ("NC", "Orange"):        ("nc_cchs_classic", "FORECLOSURE_NC_CCHS_CLASSIC_ROD", "0"),
    ("NC", "Stanly"):        ("nc_cchs_classic", "FORECLOSURE_NC_CCHS_CLASSIC_ROD", "0"),
    ("NC", "Surry"):         ("nc_cchs_classic", "FORECLOSURE_NC_CCHS_CLASSIC_ROD", "0"),
}

#: chain()-only registrations: counties whose lien existence another enricher already writes
#: (Buncombe: enrichment_aumentum_rod; Polk: the cott entry above) but whose deed chain comes from
#: an NC platform adapter. enrichment_rod_chain.py reads these together with ROD_CONFIG.
CHAIN_ONLY_CONFIG = {
    ("NC", "Buncombe"):      ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
    ("NC", "Polk"):          ("nc_cott_v4", "FORECLOSURE_NC_COTT_ROD", "0"),
}

# SC platform adapters (2026-10-07; see docs/county_records/sc_rod_platform_clusters.md). Same
# entry shape and the same chain() result shape as the NC ones, so enrich_generic_rod (raw['rod'])
# and enrichment_rod_chain (raw['rod_chain']) read them unchanged. Per-run cap
# SC_ROD_MAX_LOOKUPS_PER_COUNTY (default 30) is enforced inside the adapters (rod/sc_polite.py).
SC_ROD_CONFIG = {
    # GovOS (Kofile) PublicSearch (rod/publicsearch.py); Oconee's raw['rod'] stays on rod/kofile.py
    ("SC", "Greenville"):    ("publicsearch", "FORECLOSURE_SC_PUBLICSEARCH_ROD", "0"),
}
SC_CHAIN_ONLY_CONFIG = {
    ("SC", "Oconee"):        ("publicsearch", "FORECLOSURE_SC_PUBLICSEARCH_ROD", "0"),
}
ROD_CONFIG.update({k: v for k, v in SC_ROD_CONFIG.items() if k not in ROD_CONFIG})
CHAIN_ONLY_CONFIG.update({k: v for k, v in SC_CHAIN_ONLY_CONFIG.items() if k not in CHAIN_ONLY_CONFIG})


def platform_enabled(entry: tuple) -> bool:
    """Whether a registry entry's platform flag is on (env var, else the entry's default)."""
    env_flag = entry[1]
    default = entry[2] if len(entry) > 2 else "1"
    return os.environ.get(env_flag, default) != "0"

_MORTGAGE_N = {"DT", "DOT", "DOFTR", "MORT", "MTG", "MORTGAGE", "DEEDOFTRUST"}
_ADVERSE_N = {"LIEN", "TAXLIEN", "TAX", "JUDG", "JUDGMENT", "LP", "LISP",
              "EXECUTION", "FCL", "NOS", "CLAIM", "STLIEN", "FEDTAXLIEN"}

_EMPTY = {
    "instrument_count": 0, "kinds": {}, "has_mortgage": False,
    "has_adverse_lien": False, "adverse_types": [],
    "mortgage_count": 0, "satisfaction_count": 0,
    "open_mortgages_est": 0, "instruments": [], "source": "generic_rod",
}

_CONCURRENCY = int(os.environ.get("GENERIC_ROD_CONCURRENCY", "3"))
_MAX_PER_COUNTY = int(os.environ.get("GENERIC_ROD_MAX_PER_COUNTY", "150"))


def _name_parts(owner: str):
    fl = first_last_parts(owner)   # Title Case FIRST-LAST court/probate names
    if fl is not None:
        return fl
    o = re.sub(r"[^A-Za-z, ]", " ", owner or "").upper()
    o = re.sub(r"\s+", " ", o).strip()
    if not o:
        return "", ""
    if "," in o:
        a, b = o.split(",", 1)
        return a.strip(), (b.strip().split(" ")[0] if b.strip() else "")
    toks = o.split(" ")
    return toks[0], (toks[1] if len(toks) > 1 else "")


def _owner_doc(doc, last: str, first: str) -> bool:
    blob = f"{getattr(doc, 'grantor', '') or ''} {getattr(doc, 'grantee', '') or ''}".upper()
    return bool(last) and last in blob and (not first or first in blob)


def _get_module(module_name: str):
    """Lazily import the ROD module."""
    try:
        import importlib
        mod = importlib.import_module(f"foreclosure_scraper.rod.{module_name}")
        return mod
    except ImportError:
        return None


async def enrich_generic_rod(listings: list[Listing]) -> dict:
    """Search ROD by owner name for COTT/Kofile/Acclaim counties.

    Attaches raw['rod'] in the same shape as CCHS enricher so the dashboard
    and equity engine read it uniformly.
    """
    now = datetime.now(timezone.utc)
    hot_days, base_days = refresh_windows("FORECLOSURE_GENERIC_ROD", 7, 2)

    # Group targets by (state, county) -> module
    targets_by_county: dict[tuple[str, str], list[Listing]] = {}
    for li in listings:
        key = (li.state or "", (li.county or "").strip())
        if key not in ROD_CONFIG:
            continue
        if not li.owner_name:
            continue
        if not is_stale(li, now, hot_days, base_days):
            continue
        targets_by_county.setdefault(key, []).append(li)

    stats = {"counties": 0, "targets": 0, "searched": 0,
             "with_instruments": 0, "with_mortgage": 0, "with_adverse": 0}

    for (state, county), targets in targets_by_county.items():
        entry = ROD_CONFIG[(state, county)]
        module_name, env_flag = entry[0], entry[1]
        if not platform_enabled(entry):
            log.info("generic_rod.skipped", county=county, reason=f"disabled ({env_flag}=0 or default off)")
            continue

        mod = _get_module(module_name)
        if mod is None:
            log.warning("generic_rod.no_module", county=county, module=module_name)
            continue

        if not hasattr(mod, "search_by_name"):
            log.warning("generic_rod.no_search_by_name", county=county, module=module_name)
            continue
        search_fn = mod.search_by_name

        # Cap per county
        if len(targets) > _MAX_PER_COUNTY:
            targets = targets[:_MAX_PER_COUNTY]

        stats["counties"] += 1
        stats["targets"] += len(targets)
        log.info("generic_rod.county_start", county=county, module=module_name,
                 targets=len(targets))

        sem = asyncio.Semaphore(_CONCURRENCY)

        async def one(li: Listing) -> None:
            owner = li.owner_name or ""
            last, first = _name_parts(owner)
            if not last:
                return
            async with sem:
                try:
                    docs = await search_fn(state, county, owner, max_docs=80)
                except Exception as exc:
                    log.debug("generic_rod.search_fail", county=county,
                              owner=li.owner_name[:40], error=str(exc)[:80])
                    docs = []
                stats["searched"] += 1

            if not docs:
                return  # fetch failed -> leave unstamped, retry next run

            mine = [d for d in docs if _owner_doc(d, last, first)]
            if not mine:
                return

            summ = classify_rod_docs(mine, "generic_rod") if mine else dict(_EMPTY)
            summ["fetched_at"] = now.isoformat()
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["rod"] = summ

            stats["with_instruments"] += 1
            if summ.get("has_mortgage"):
                stats["with_mortgage"] += 1
            if summ.get("has_adverse_lien"):
                stats["with_adverse"] += 1

            await asyncio.sleep(0.3)

        await asyncio.gather(*(one(li) for li in targets))

    log.info("generic_rod.done", **stats)
    return stats
