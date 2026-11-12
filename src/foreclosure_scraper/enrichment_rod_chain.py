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
  FORECLOSURE_COUNTY_DEED_REF      (default 1) for a chain whose row has no county deed book/page,
                                   read the parcel's deed reference from NC OneMap (SC: the
                                   county's own parcel layer, six counties) first
                                   (county_deed_ref.py, one request, 2 s apart) so it can be bound
  FORECLOSURE_ROD_CHAIN_BUDGET_S   wall-clock budget for the pass (default 1800): no new lead is
                                   started after it; leads not reached stay unstamped for next run

  ROD_CHAIN_COUNTY_CONCURRENCY     counties read at the same time (default 8; each county is its
                                   own register host, so this never puts two requests on one host)

POLITENESS: leads within a county run one after another, through the adapters' paced client
(>= 1.6 s per host, one request at a time, per-host lock shared by every caller in the process).
Counties are different hosts, so up to ROD_CHAIN_COUNTY_CONCURRENCY of them run side by side. A
county that answers with a wall, or reaches the cap, is left for the rest of the run; its leads stay
unstamped and are retried on a later run.

BINDING (audit 2026-10-09, additions_verify). A chain is found by the OWNER'S NAME, so its newest
deed can be that owner's deed for another parcel, and it misses a later deed in which the owner
sold. Checked against county and NC OneMap parcel records on 30 sampled 10/8 chains: 14 right, 10
another parcel's deed, 6 missing a later deed. Each result now carries raw['rod_chain']['binding']
from the lead's OWN parcel record (raw['gis']['last_sale'] date, the county's last sale):
  sale_date       the chain's last deed was recorded within 31 days (the same year when the county
                  gives a year only) of the parcel's last sale: the chain is this parcel's;
  contradicted    the parcel's last sale is more than 31 days AFTER the chain's last deed (the
                  chain missed a later deed), or the chain's last deed is more than 31 days after
                  the parcel's last sale and older than 180 days (another parcel's deed; a deed
                  newer than 180 days can postdate the parcel record and is not judged): the
                  status becomes 'unbound', so nothing that reads status 'ok' takes it as the
                  lead's chain;
  book_page       (audit 2026-10-09, lawyer_lane) the county parcel record on the row cites the
                  chain's last deed by book and page (raw['gis']['last_sale'] book/page): this
                  parcel's deed. A different book/page recorded on the parcel's sale date is a
                  same-day deed for another parcel: name_only, reason book_page_differs;
  name_only       no parcel sale date to judge by, or the owner conveyed a deed after the chain's
                  last deed (rod/nc_chain.py conveyed_out_since: this parcel or another one was
                  sold): a candidate found by name, not confirmed.

ORDER (audit 2026-10-09, additions_verify): counties holding the most imminent leads (HOT or an
auction within 30 days) go first, then the counties with the most leads. The 10/8 run read the
counties one after another in ALPHABETICAL order: the 1,800 s budget ended inside the sixth county
(Alamance, Alexander, Avery, Bertie, Buncombe, Clay) and 52 enabled counties got nothing, every run
the same six. If the phase is cancelled by the caller's cap, the counts so far are logged
(rod_chain.cancelled) instead of being lost.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import time
from datetime import date, datetime, timezone
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


def _iso_day(v) -> tuple[date | None, bool]:
    """(date, year_only) from 'YYYY-MM-DD', 'YYYYMMDD' or an ISO datetime; Jan 1 reads as a year."""
    s = str(v or "").strip()
    d = None
    for fmt, n in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
        try:
            d = datetime.strptime(s[:n], fmt).date()
            break
        except ValueError:
            continue
    if d is None:
        return None, False
    return d, (d.month == 1 and d.day == 1)


def _needs_deed_ref(li: Listing, state: str, now: datetime) -> bool:
    """An NC lead (or an SC lead in a county_deed_ref.SC_LAYERS county) with a parcel id whose row has
    no county deed book/page and no
    raw['county_deed_ref'] read in the last 30 days (FORECLOSURE_COUNTY_DEED_REF=0 turns it off)."""
    from .county_deed_ref import SC_LAYERS
    if os.environ.get("FORECLOSURE_COUNTY_DEED_REF", "1") != "1" or not li.parcel_id \
            or not (state == "NC" or (state == "SC" and str(li.county or "").strip().title() in SC_LAYERS)):
        return False
    from .lawyer_lane import county_deed_ref
    ref = county_deed_ref(li)
    if ref.get("book") and ref.get("page"):
        return False
    cdr = (li.raw or {}).get("county_deed_ref") if isinstance(li.raw, dict) else None
    if isinstance(cdr, dict):
        d, _ = _iso_day(cdr.get("fetched_at"))
        if d and (now.date() - d).days < 30:
            return False
    return True


def bind_chain(li: Listing, res: dict, now: datetime | None = None) -> dict:
    """How the chain's last deed ties to the lead's own parcel record (see BINDING above)."""
    now = now or datetime.now(timezone.utc)
    ld = res.get("last_deed") if isinstance(res.get("last_deed"), dict) else {}
    rec, _ = _iso_day(ld.get("recorded"))
    # the county record's last sale: raw['gis']['last_sale'], completed by raw['county_deed_ref']
    # (the parcel layer's own deed reference, county_deed_ref.py) where the row lacks one
    from .lawyer_lane import county_deed_ref, same_book_page
    ls = county_deed_ref(li)
    sale, year_only = _iso_day(ls.get("date"))
    sold_since = [d.get("recorded") for d in (res.get("conveyed_out_since") or []) if isinstance(d, dict)]
    # the county parcel record cites a deed book and page: the strongest tie (audit 2026-10-09,
    # lawyer_lane). The same book/page is this parcel's deed whatever the dates say; a different
    # one recorded on the parcel's sale date is a same-day deed for another parcel (not bound).
    bp = same_book_page(ld.get("book"), ld.get("page"), ls.get("book"), ls.get("page"))
    if bp is True and not sold_since:
        return {"status": "book_page", "parcel_last_sale": ls.get("date") or None,
                "deed_recorded": rec.isoformat() if rec else None}
    if rec is None or sale is None:
        b = {"status": "name_only", "parcel_last_sale": ls.get("date") or None}
        if sold_since:
            b["reason"] = "owner_conveyed_since_last_deed"
            b["conveyed_out_since"] = sold_since
        return b
    out = {"parcel_last_sale": sale.isoformat(), "deed_recorded": rec.isoformat()}
    if sold_since:
        # the parcel record may predate the outgoing deed: not confirmed, and say why
        out["conveyed_out_since"] = sold_since
        if year_only and rec.year == sale.year or (not year_only and abs((rec - sale).days) <= 31):
            return {"status": "name_only", "reason": "owner_conveyed_since_last_deed", **out}
    if year_only:
        if rec.year == sale.year:
            if bp is False:
                return {"status": "name_only", "reason": "book_page_differs", **out}
            return {"status": "sale_date", "precision": "year", **out}
        gap = (rec.year - sale.year) * 365
    else:
        gap = (rec - sale).days
        if abs(gap) <= 31:
            if bp is False:
                return {"status": "name_only", "reason": "book_page_differs", **out}
            return {"status": "sale_date", "precision": "day", **out}
    if gap < 0:
        return {"status": "contradicted", "reason": "parcel_sold_after_chain_deed", **out}
    if (now.date() - rec).days <= 180:
        return {"status": "name_only", "reason": "deed_newer_than_parcel_record", **out}
    return {"status": "contradicted", "reason": "deed_newer_than_parcel_sale", **out}


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
             "budget_exhausted": False, "bound_sale_date": 0, "name_only": 0, "unbound": 0}
    try:
        county_conc = max(1, int(os.environ.get("ROD_CHAIN_COUNTY_CONCURRENCY", "8")))
    except ValueError:
        county_conc = 8
    sem = asyncio.Semaphore(county_conc)

    def _out_of_time() -> bool:
        if time.monotonic() - t0 > budget_s:
            stats["budget_exhausted"] = True
            return True
        return False

    async def one_county(state: str, county: str, targets: list[Listing]) -> None:
        entry = registry[(state, county)]
        if not platform_enabled(entry):
            stats["disabled_counties"] += 1
            return
        async with sem:
            if _out_of_time():
                return
            mod = _module(entry[0])
            stats["counties"] += 1
            targets.sort(key=lambda li: not imminent(li, now))       # auctions soonest first
            for li in targets:
                if _out_of_time():
                    break
                stats["targets"] += 1
                try:
                    # the lead's parcel id, for adapters whose chain() takes one (Anderson SC: flags a
                    # vesting deed newer than its online index from the county parcel layer)
                    _code = getattr(mod.chain, "__code__", None)
                    _kw = {"parcel_id": li.parcel_id} if _code is not None and "parcel_id" in _code.co_varnames else {}
                    res = await asyncio.to_thread(mod.chain, county, li.owner_name, state=state, depth=depth, **_kw)
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
                if status in ("ok", "partial") and res.get("last_deed") and _needs_deed_ref(li, state, now):
                    # the parcel layer's own deed reference, so the chain can be bound to the parcel
                    from .county_deed_ref import fetch as fetch_deed_ref
                    ref = await asyncio.to_thread(fetch_deed_ref, state, county, li.parcel_id)
                    stats["county_deed_ref"] = stats.get("county_deed_ref", 0) + bool(ref)
                    if ref:
                        li.raw["county_deed_ref"] = ref
                if status == "ok":
                    b = bind_chain(li, res, now)
                    res["binding"] = b
                    if b["status"] == "contradicted":
                        res["status"] = "unbound"
                        stats["unbound"] += 1
                    elif b["status"] in ("sale_date", "book_page"):
                        stats["bound_sale_date"] += 1
                    else:
                        stats["name_only"] += 1
                li.raw["rod_chain"] = res
                # the attorney's latest deed (raw['deed_latest']) from a chain bound to the parcel;
                # removes a stale or unbound one (lawyer_lane.stamp_deed_latest, no network)
                try:
                    from .lawyer_lane import stamp_deed_latest
                    stats["deed_latest"] = stats.get("deed_latest", 0) + stamp_deed_latest([li], now)["deed_latest"]
                except Exception as exc:  # noqa: BLE001
                    log.warning("rod_chain.deed_latest_failed", error=f"{type(exc).__name__}: {str(exc)[:120]}")
                stats["stamped"] += 1
                liens = res.get("liens") or {}
                stats["with_last_deed"] += bool(res.get("last_deed"))
                stats["with_prior"] += bool(res.get("prior_instruments"))
                stats["with_open_dot_est"] += bool(liens.get("open_deeds_of_trust_est"))
                stats["with_lis_pendens"] += bool(liens.get("lis_pendens"))
                stats["with_substitution"] += bool(liens.get("substitutions_of_trustee"))

    # counties holding the most imminent leads first, then the most leads (not alphabetical)
    order = sorted(by_county.items(),
                   key=lambda kv: (-sum(1 for li in kv[1] if imminent(li, now)), -len(kv[1]), kv[0]))
    try:
        await asyncio.gather(*(one_county(s, c, t) for (s, c), t in order))
    except asyncio.CancelledError:
        log.warning("rod_chain.cancelled", **{k: v for k, v in stats.items() if not isinstance(v, list)},
                    walled=stats["walled_counties"], capped=stats["capped_counties"])
        raise
    log.info("rod_chain.done", **{k: v for k, v in stats.items() if not isinstance(v, list)},
             walled=stats["walled_counties"], capped=stats["capped_counties"])
    return stats
