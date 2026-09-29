"""Federal incarceration signal — BOP.gov Inmate Locator name match.

Dirty Deeds Tier B #36 (BOP.gov federal locator). enrichment_incarceration.py
covers NC DAC + SC DOC (state prison) and enrichment_jail_bookings.py covers
county jails (pre-trial / local holds); neither reaches the FEDERAL system. An
NC or SC owner sentenced on a federal charge (drug trafficking, bank fraud, a
gun charge with a federal enhancement...) serves time in the Bureau of Prisons,
not a state or county facility, and is invisible to either existing lane.

Endpoint: https://www.bop.gov/PublicInfo/execute/inmateloc?todo=query&output=json
&nameFirst=<first>&nameLast=<last> — the same JSON XHR the public "Find an
inmate" search page calls. Verified live 2026-09-29 against a real name already
flagged raw['incarceration'] on this board (NC DAC match "RUSSELL HUDSON"):
returned "Captcha":false plus a 2-record InmateLocator array (facility
code/name/type, age, race, sex, release dates). A name with no hits
("Zzqxvv Nonexistentxyz123") returned the same shape with an empty array — a
miss is a clean "answered", not indistinguishable from a block, exactly like NC
DAC's "No offenders found." page. robots.txt Disallow is empty. No login, no
CAPTCHA, no WAF challenge observed. Free, keyless, compliant.

FACILITY TYPE (Tier B #36's other ask): BOP's own faclType code says whether
the record is an actual BOP-run PRISON (FCI/USP/FPC/FCC/CI/SFF —
"federal_prison"), a federal DETENTION center (FDC/MDC/MCC — pretrial /
short-hold, jail-like mail rules) or a community-confinement / RRM office
(halfway house / home-confinement supervision — its own, different,
contactability shape). Unmapped codes fall back to "federal_other" rather than
guessing at a category BOP itself did not document.

IN CUSTODY vs RELEASED: the feed carries no explicit boolean. A record with a
populated actRelDate (actual release date) has already been released; the
current-custody signal is the ABSENCE of one (a live actRelDate-empty record
still shows a projRelDate or nothing at all). A released federal ex-inmate is
not today's-distress the way someone currently locked up is, so this enricher
only sets raw['incarceration'] (the LEGAL weight-8 stack signal distress_score
already reads) when in_custody is True; the full record — including a past
release — still lands in raw['bop_federal'] either way, since who was recently
federally incarcerated is itself useful skip-trace context even once released.

HONEST CAVEAT: identical to enrichment_incarceration.py — a name-only match (no
DOB to disambiguate), so it is a LOW-confidence STACK signal, gated the same
way (exactly one exact last+first hit; 2+ candidates is noise, not a match) and
stamped the same way: an answered miss is remembered in raw['bop_check'] so a
fixed per-run query budget rotates through the board instead of re-asking the
same 150 names forever (mirrors enrichment_incarceration.py's J-01 fix).
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

from .enrichment_incarceration import _name_parts, _owner_of
from .models import Listing

log = structlog.get_logger()

BOP_URL = "https://www.bop.gov/PublicInfo/execute/inmateloc"
BOP_SOURCE = "BOP inmate locator"

# BOP's own facility-type abbreviations (bop.gov/about/facilities), bucketed
# for contactability. Not exhaustive — anything unrecognized is "federal_other"
# rather than a guess.
_FACILITY_TYPE_MAP = {
    "FCI": "federal_prison", "USP": "federal_prison", "FPC": "federal_prison",
    "FCC": "federal_prison", "CI": "federal_prison", "SFF": "federal_prison",
    "FDC": "federal_detention", "MDC": "federal_detention", "MCC": "federal_detention",
    "FTC": "federal_detention",     # Federal Transfer Center — in-transit holding
    "RRM": "community_confinement", "CCM": "community_confinement",
}


def _facility_type(code: Optional[str]) -> str:
    return _FACILITY_TYPE_MAP.get(str(code or "").strip().upper(), "federal_other")


_BLOCK_STATUS = (401, 403, 407, 429)


@dataclass
class _Lookup:
    """One BOP query, with the facts the stamp logic needs (mirrors
    enrichment_incarceration._Lookup)."""
    match: Optional[dict] = None
    answered: bool = False
    blocked: bool = False
    candidates: int = 0


async def _bop_lookup(http: httpx.AsyncClient, last: str, first: str) -> _Lookup:
    """Search the BOP Inmate Locator by name; a match needs EXACTLY ONE exact
    last+first record among the results (a common name returning several is
    noise, not a hit — same gate as NC DAC / SC DOC)."""
    params = {"todo": "query", "output": "json", "nameFirst": first, "nameLast": last}
    try:
        r = await http.get(BOP_URL, params=params, timeout=25.0,
                           headers={"User-Agent": "Mozilla/5.0",
                                    "Accept": "application/json"})
        if r.status_code in _BLOCK_STATUS:
            return _Lookup(blocked=True)
        if r.status_code != 200:
            return _Lookup()
        data = r.json()
    except Exception:
        return _Lookup()
    if not isinstance(data, dict) or "InmateLocator" not in data:
        return _Lookup()                # not the JSON shape we verified — no answer
    if data.get("Captcha"):
        return _Lookup(blocked=True)     # would only trip if BOP ever gates this feed
    recs = data.get("InmateLocator") or []
    exact = [x for x in recs
             if str(x.get("nameLast") or "").strip().upper() == last
             and str(x.get("nameFirst") or "").strip().upper() == first]
    if not exact:
        return _Lookup(answered=True, candidates=len(recs))
    max_results = int(os.environ.get("BOP_MAX_RESULTS", "1"))
    if len(exact) > max_results:
        return _Lookup(answered=True, candidates=len(exact))
    rec = exact[0]
    in_custody = not str(rec.get("actRelDate") or "").strip()
    match = {
        "matched_name": f"{first} {last}",
        "inmate_num": rec.get("inmateNum"),
        "facility_code": rec.get("faclCode"),
        "facility_name": rec.get("faclName"),
        "facility_type": _facility_type(rec.get("faclType")),
        "facility_type_raw": rec.get("faclType"),
        "projected_release_date": rec.get("projRelDate") or None,
        "actual_release_date": rec.get("actRelDate") or None,
        "in_custody": in_custody,
        "results": len(exact),
        "source": BOP_SOURCE,
        "confidence": "name_only_low",
    }
    return _Lookup(match=match, answered=True, candidates=len(exact))


# ---- negative stamp + selection (mirrors enrichment_incarceration.py) --------

def _recheck_days() -> float:
    try:
        return float(os.environ.get("BOP_RECHECK_DAYS", "30"))
    except ValueError:
        return 30.0


def _stamp_of(li: Listing, name: str) -> Optional[datetime]:
    st = li.raw.get("bop_check") if isinstance(li.raw, dict) else None
    if not isinstance(st, dict) or st.get("name") != name:
        return None
    try:
        dt = datetime.fromisoformat(str(st.get("checked_at")))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _stamp_miss(li: Listing, name: str, now: datetime) -> None:
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["bop_check"] = {"checked_at": now.replace(microsecond=0).isoformat(),
                           "name": name, "source": BOP_SOURCE, "result": "no_match"}


def _select_targets(cands: list[tuple], max_queries: int) -> list[Listing]:
    """Never-checked leads first (board order), then oldest stamps. One
    national endpoint, so — unlike the per-state/county rotation in
    enrichment_incarceration.py — there is no county grouping to round-robin."""
    ordered = sorted(cands, key=lambda t: (t[2] is not None, t[2].timestamp() if t[2] else 0.0))
    return [li for li, _name, _checked in ordered[:max_queries]]


async def enrich_bop_federal(listings: list[Listing], max_queries: Optional[int] = None,
                             recheck_days: Optional[float] = None) -> dict:
    """Flag listings whose owner matches the federal BOP inmate locator.

    max_queries    total lookups this run (env BOP_MAX_QUERIES, default 150)
    recheck_days   how long an answered miss stays fresh (env BOP_RECHECK_DAYS,
                   default 30)
    """
    if max_queries is None:
        max_queries = int(os.environ.get("BOP_MAX_QUERIES", "150"))
    window = _recheck_days() if recheck_days is None else float(recheck_days)
    now = datetime.now(timezone.utc)

    cands, fresh = [], 0
    for li in listings:
        if li.state not in ("NC", "SC"):
            continue
        if (li.raw or {}).get("bop_federal"):
            continue
        owner = _owner_of(li)
        parts = _name_parts(owner) if owner else None
        if not parts:
            continue
        name = f"{parts[1]} {parts[0]}"
        checked = _stamp_of(li, name)
        if checked is not None and (now - checked).total_seconds() < window * 86400:
            fresh += 1
            continue
        cands.append((li, name, checked))
    targets = _select_targets(cands, max_queries)
    if not targets:
        log.info("bop.no_targets", skipped_fresh=fresh)
        return {"queried": 0, "matched": 0}

    sem = asyncio.Semaphore(int(os.environ.get("BOP_CONCURRENCY", "1")))
    delay = float(os.environ.get("BOP_DELAY", "1.0"))
    counts = {"queried": 0, "matched": 0, "stamped_miss": 0, "failed": 0,
             "skipped_fresh": fresh, "candidates": len(cands), "selected": len(targets),
             "blocked": 0}
    state_box = {"tripped": False, "strikes": 0}
    max_strikes = int(os.environ.get("BOP_MAX_FAILURES", "8"))
    cache: dict[tuple, asyncio.Future] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True) as http:
        async def lookup(last: str, first: str) -> Optional[_Lookup]:
            async with sem:
                if state_box["tripped"]:
                    return None
                counts["queried"] += 1
                res = await _bop_lookup(http, last, first)
                if res.blocked:
                    state_box["tripped"] = True
                    counts["blocked"] += 1
                    log.warning("bop.host_blocked")
                elif res.answered:
                    state_box["strikes"] = 0
                else:
                    state_box["strikes"] += 1
                    if state_box["strikes"] >= max_strikes:
                        state_box["tripped"] = True
                        log.warning("bop.host_failing")
                if delay:
                    await asyncio.sleep(delay)
                return res

        async def one(li: Listing):
            last, first = _name_parts(_owner_of(li))
            key = (last, first)
            # The same owner often holds several parcels: ask BOP once.
            if key not in cache:
                cache[key] = asyncio.ensure_future(lookup(last, first))
            res = await cache[key]
            if res is None or res.blocked:
                return                          # not asked: leave the lead unstamped
            if res.match:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["bop_federal"] = res.match
                li.raw.pop("bop_check", None)
                if res.match.get("in_custody"):
                    li.raw.setdefault("incarceration", {
                        "state": "FEDERAL", "source": BOP_SOURCE,
                        "matched_name": res.match["matched_name"],
                        "facility_type": res.match["facility_type"],
                        "confidence": "name_only_low"})
                counts["matched"] += 1
            elif res.answered:
                _stamp_miss(li, f"{first} {last}", now)
                counts["stamped_miss"] += 1
            else:
                counts["failed"] += 1           # no answer: never stamped
        await asyncio.gather(*(one(li) for li in targets))
    log.info("bop.done", **counts)
    return counts
