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
import time
from datetime import datetime, timezone
from typing import Optional

import structlog

from .models import Listing
from .rod.classify import classify_rod_docs, imminent, is_stale, refresh_windows
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
    # Tyler Technologies register search (rod/nc_tyler.py): Self-Service (Durham), EagleWeb
    # (Johnston). Wake (Self-Service with a reCAPTCHA) is left to a person.
    ("NC", "Durham"):        ("nc_tyler", "FORECLOSURE_NC_TYLER_ROD", "0"),
    ("NC", "Johnston"):      ("nc_tyler", "FORECLOSURE_NC_TYLER_ROD", "0"),
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
# Defaults from a yield check on 4 real board owners per platform (2026-10-07, counts only):
# PublicSearch Greenville 4/4 chains (about 15 s a lookup) and AcclaimWeb Horry 4/4 owners found
# (2 with a deed) are ON; Online Record System (Laurens 2/4, one lookup 200 s) and ACPASS
# (Anderson 1/4) are OFF until the owner turns them on.
SC_ROD_CONFIG = {
    # GovOS (Kofile) PublicSearch (rod/publicsearch.py); Oconee's raw['rod'] stays on rod/kofile.py
    ("SC", "Greenville"):    ("publicsearch", "FORECLOSURE_SC_PUBLICSEARCH_ROD", "1"),
    # 'Online Record System' (rod/sc_online_record_system.py). The first eight are also read by
    # enrichment_rod_name_index (raw['rod_name_index'], no chain); none of them had raw['rod'].
    ("SC", "Abbeville"):     ("sc_online_record_system", "FORECLOSURE_SC_ORS_ROD", "0"),
    ("SC", "Barnwell"):      ("sc_online_record_system", "FORECLOSURE_SC_ORS_ROD", "0"),
    ("SC", "Berkeley"):      ("sc_online_record_system", "FORECLOSURE_SC_ORS_ROD", "0"),
    ("SC", "Colleton"):      ("sc_online_record_system", "FORECLOSURE_SC_ORS_ROD", "0"),
    ("SC", "Dorchester"):    ("sc_online_record_system", "FORECLOSURE_SC_ORS_ROD", "0"),
    ("SC", "Florence"):      ("sc_online_record_system", "FORECLOSURE_SC_ORS_ROD", "0"),
    ("SC", "Georgetown"):    ("sc_online_record_system", "FORECLOSURE_SC_ORS_ROD", "0"),
    ("SC", "York"):          ("sc_online_record_system", "FORECLOSURE_SC_ORS_ROD", "0"),
    ("SC", "Laurens"):       ("sc_online_record_system", "FORECLOSURE_SC_ORS_ROD", "0"),
    ("SC", "Lancaster"):     ("sc_online_record_system", "FORECLOSURE_SC_ORS_ROD", "0"),
    # Harris AcclaimWeb by name (rod/acclaim_names.py); rod/acclaim.py's Pickens date sweep is separate
    ("SC", "Horry"):         ("acclaim_names", "FORECLOSURE_SC_ACCLAIM_ROD", "1"),
    ("SC", "Pickens"):       ("acclaim_names", "FORECLOSURE_SC_ACCLAIM_ROD", "1"),
    # ACPASS by name, 7/1/1974-2/20/2026 (rod/anderson_acpass_rod.py). Later deeds are in a
    # bot-checked system a script may not read; every chain result says so (after_index).
    ("SC", "Anderson"):      ("anderson_acpass_rod", "FORECLOSURE_SC_ACPASS_ROD", "0"),
    # the county's own document search (rod/greenwood_docsearch.py); 2 of 6 real board owners gave a
    # chain and a third the owner's liens, about 5 s a lookup (2026-10-07)
    ("SC", "Greenwood"):     ("greenwood_docsearch", "FORECLOSURE_SC_GREENWOOD_ROD", "1"),
    # Cott RecordRoom by name (rod/sc_recordroom.py) and the older Cott eSearch (rod/sc_cott_esearch.py);
    # real board owners 2026-10-07: Union 1 chain + 3 owners' liens of 6, Marlboro 2 chains of 5
    ("SC", "Union"):         ("sc_recordroom", "FORECLOSURE_SC_RECORDROOM_ROD", "1"),
    ("SC", "Marlboro"):      ("sc_cott_esearch", "FORECLOSURE_SC_COTT_ESEARCH_ROD", "1"),
}
SC_CHAIN_ONLY_CONFIG = {
    ("SC", "Oconee"):        ("publicsearch", "FORECLOSURE_SC_PUBLICSEARCH_ROD", "1"),
    # 'The Lookup' over plain HTTP (rod/sc_lookup.py); raw['rod'] stays on enrichment_spartanburg_rod.
    # Proven 4/4 chains on real board owners 2026-10-07 (one to four minutes a chain).
    ("SC", "Spartanburg"):   ("sc_lookup", "FORECLOSURE_SC_LOOKUP_ROD", "1"),
}
ROD_CONFIG.update({k: v for k, v in SC_ROD_CONFIG.items() if k not in ROD_CONFIG})
CHAIN_ONLY_CONFIG.update({k: v for k, v in SC_CHAIN_ONLY_CONFIG.items() if k not in CHAIN_ONLY_CONFIG})

#: NC registers searched in a headless browser (rod/nc_render.py): run by enrichment_nc_rod_render
#: (Spartanburg-style: capped per run by each platform's *_ROD_MAX, idempotent, skips rows that
#: already carry raw['rod']), NOT by enrich_generic_rod; enrichment_rod_chain reads them for the
#: chain. Same entry shape, all OFF until the platform flag is 1.
RENDER_ROD_CONFIG = {
    # Harris 'ROD Web Access' (rod/nc_harris.py); Moore runs it too but answered with HTTP 403
    ("NC", "Mecklenburg"):   ("nc_harris", "FORECLOSURE_NC_HARRIS_ROD", "0"),
    ("NC", "Carteret"):      ("nc_harris", "FORECLOSURE_NC_HARRIS_ROD", "0"),
    # Logan 'Public Records' Blazor (rod/nc_logan_blazor.py); proven live: Catawba, Cumberland, Union
    ("NC", "Catawba"):       ("nc_logan_blazor", "FORECLOSURE_NC_LOGAN_BLAZOR_ROD", "0"),
    ("NC", "Cumberland"):    ("nc_logan_blazor", "FORECLOSURE_NC_LOGAN_BLAZOR_ROD", "0"),
    ("NC", "Union"):         ("nc_logan_blazor", "FORECLOSURE_NC_LOGAN_BLAZOR_ROD", "0"),
    ("NC", "Cabarrus"):      ("nc_logan_blazor", "FORECLOSURE_NC_LOGAN_BLAZOR_ROD", "0"),
    ("NC", "Chatham"):       ("nc_logan_blazor", "FORECLOSURE_NC_LOGAN_BLAZOR_ROD", "0"),
    ("NC", "Sampson"):       ("nc_logan_blazor", "FORECLOSURE_NC_LOGAN_BLAZOR_ROD", "0"),
    ("NC", "Wilkes"):        ("nc_logan_blazor", "FORECLOSURE_NC_LOGAN_BLAZOR_ROD", "0"),
    # Logan 'Remote Access' (Visual WebGui search, rod/nc_logan_remote.py); proven live: Davie,
    # Yadkin, Vance
    ("NC", "Davie"):         ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
    ("NC", "Yadkin"):        ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
    ("NC", "Vance"):         ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
    ("NC", "Martin"):        ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
    ("NC", "Cherokee"):      ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
    ("NC", "Anson"):         ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
    ("NC", "Bladen"):        ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
    ("NC", "Ashe"):          ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
    ("NC", "Northampton"):   ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
    ("NC", "Warren"):        ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
    ("NC", "Swain"):         ("nc_logan_remote", "FORECLOSURE_NC_LOGAN_REMOTE_ROD", "0"),
}


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

# RUN SHAPE (audit 2026-10-09, additions_verify). The 10/8 run read the enabled counties one after
# another in board order inside the ROD group's 900 s cap: 5 counties started (Rutherford,
# Greenville, Edgecombe, Anderson, Laurens) of about 60 enabled, 114 leads stamped, and the cap
# cancelled the phase so not even its counts reached the run's stats. Now:
#   * counties run side by side, GENERIC_ROD_COUNTY_CONCURRENCY at a time (default 8). Each county
#     is its own register host and the adapters' paced client holds a per-host lock, so this never
#     puts two requests on one host;
#   * the counties holding the most imminent leads (HOT or an auction within 30 days) go first;
#     inside a county imminent leads first, then leads never read before;
#   * FORECLOSURE_GENERIC_ROD_BUDGET_S (default 840 s, under the 900 s group cap) ends the pass with
#     its counts returned; no lookup starts after it;
#   * in a county whose adapter also gives the deed chain (enrichment_rod_chain, when
#     FORECLOSURE_ROD_CHAIN=1), this pass takes at most GENERIC_ROD_MAX_PER_CHAIN_COUNTY leads
#     (default 10): the adapters cap lookups per county per run (NC_ROD_MAX_LOOKUPS_PER_COUNTY /
#     SC_ROD_MAX_LOOKUPS_PER_COUNTY, 30) and the cap is shared by both callers, so a 150-lead pass
#     here would leave the deed chain nothing in every such county.
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


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
             "with_instruments": 0, "with_mortgage": 0, "with_adverse": 0,
             "disabled_counties": 0, "budget_exhausted": False, "chain_share_capped": 0,
             "screened_none_found": 0}
    budget_s = _env_float("FORECLOSURE_GENERIC_ROD_BUDGET_S", 840.0)
    county_conc = max(1, _env_int("GENERIC_ROD_COUNTY_CONCURRENCY", 8))
    chain_share = max(0, _env_int("GENERIC_ROD_MAX_PER_CHAIN_COUNTY", 10))
    chain_counties: set = set()
    if os.environ.get("FORECLOSURE_ROD_CHAIN", "0") == "1":
        try:
            from .enrichment_rod_chain import chain_registry
            chain_counties = set(chain_registry())
        except Exception:  # noqa: BLE001 - the share is an optimisation, never a reason to stop
            log.warning("generic_rod.chain_registry_failed", exc_info=True)
    t0 = time.monotonic()
    county_sem = asyncio.Semaphore(county_conc)

    def _out_of_time() -> bool:
        if time.monotonic() - t0 > budget_s:
            stats["budget_exhausted"] = True
            return True
        return False

    async def one_county(state: str, county: str, targets: list[Listing]) -> None:
        entry = ROD_CONFIG[(state, county)]
        module_name, env_flag = entry[0], entry[1]
        if not platform_enabled(entry):
            stats["disabled_counties"] += 1
            log.info("generic_rod.skipped", county=county, reason=f"disabled ({env_flag}=0 or default off)")
            return

        mod = _get_module(module_name)
        if mod is None:
            log.warning("generic_rod.no_module", county=county, module=module_name)
            return

        if not hasattr(mod, "search_by_name"):
            log.warning("generic_rod.no_search_by_name", county=county, module=module_name)
            return
        search_fn = mod.search_by_name
        status_fn = getattr(mod, "search_by_name_status", None)

        # imminent leads first, then leads never read before, then the rest (board order kept)
        targets = sorted(targets, key=lambda li: (not imminent(li, now),
                                                  isinstance(li.raw, dict) and bool(li.raw.get("rod"))))
        cap = _MAX_PER_COUNTY
        if (state, county) in chain_counties and chain_share < cap:
            cap = chain_share
            if len(targets) > cap:
                stats["chain_share_capped"] += 1
        if len(targets) > cap:
            targets = targets[:cap]

        async with county_sem:
            if _out_of_time() or not targets:
                return
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
                    if _out_of_time():
                        return
                    status, truncated = None, False
                    try:
                        if status_fn is not None:
                            docs, status, truncated = await status_fn(state, county, owner, max_docs=80)
                        else:
                            docs = await search_fn(state, county, owner, max_docs=80)
                    except Exception as exc:
                        log.debug("generic_rod.search_fail", county=county,
                                  owner=li.owner_name[:40], error=str(exc)[:80])
                        docs, status = [], "error"
                    stats["searched"] += 1

                mine = [d for d in docs if _owner_doc(d, last, first)] if docs else []
                if not mine:
                    # 2026-10-09 (top80 register group): a module that reports its status lets a clean
                    # "searched, nothing indexed under this name" be recorded as a checked negative
                    # (raw['rod'] with instrument_count 0 and screened_none_found, the same shape as
                    # enrichment_nc_rod_render's clean no-match). Walls, caps, errors, an unparsable
                    # name and a truncated pick list stay unstamped and are retried next run.
                    if status == "ok" and not truncated:
                        summ = dict(_EMPTY)
                        summ.update({"fetched_at": now.isoformat(), "screened_none_found": True,
                                     "platform": module_name})
                        if not isinstance(li.raw, dict):
                            li.raw = {}
                        li.raw["rod"] = summ
                        stats["screened_none_found"] += 1
                    return  # fetch failed (or screened and stamped above)

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

    # the counties holding the most imminent leads first, then the most leads
    order = sorted(targets_by_county.items(),
                   key=lambda kv: (-sum(1 for li in kv[1] if imminent(li, now)), -len(kv[1]), kv[0]))
    try:
        await asyncio.gather(*(one_county(s, c, t) for (s, c), t in order))
    except asyncio.CancelledError:
        log.warning("generic_rod.cancelled", **stats)
        raise

    log.info("generic_rod.done", **stats)
    return stats
