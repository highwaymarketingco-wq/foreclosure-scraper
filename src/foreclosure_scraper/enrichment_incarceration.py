"""Incarceration distress signal — match property owners against inmate rosters.

An owner who is in prison/jail is a motivated seller (can't manage the property,
family needs liquidity). This is an ENRICHMENT, not a listing source: it takes
the owner names we resolved via #0 (owner_mailing) / the defendant field and
checks them against the state corrections roster, flagging raw['incarceration'].

NC: NC DAC Offender Public Information — queryable by last+first name
(webapps.doc.state.nc.us/opi/offendersearch.do), parseable HTML results.
SC: SCDC inmate search is a React SPA (no static form) — TODO once its JSON
API is identified; SC owners are skipped for now (logged), not silently dropped.

HONEST CAVEAT: this is a NAME-ONLY match (we have no owner DOB), so common
names produce false positives. It is therefore emitted as a LOW-confidence
STACK signal (confidence='name_only') — meaningful only when combined with
other distress on the same property, never as a standalone "this owner is in
prison" claim. Capped + paced to be polite to the state server.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

DAC_URL = "https://webapps.doc.state.nc.us/opi/offendersearch.do"

# Owner strings that aren't a person → no one to incarcerate, skip.
_ENTITY = re.compile(r"\b(LLC|L\.L\.C|INC|CORP|COMPANY|CO\b|TRUST|ESTATE|HEIRS|BANK|"
                     r"ASSOC|PARTNERS|LP\b|LLP|CHURCH|MINISTR|HOLDINGS|PROPERTIES|"
                     r"FUND|GROUP|AUTHORITY|COUNTY|CITY OF|STATE OF)\b", re.I)


def _name_parts(owner: str) -> Optional[tuple[str, str]]:
    """Return (last, first) from an owner string, or None if not a usable person.
    Handles 'LAST, FIRST M' and 'LAST FIRST M' (county GIS often stores either)."""
    if not owner or _ENTITY.search(owner):
        return None
    o = re.split(r"[;&]| and ", owner)[0].strip()  # first owner of a joint pair
    raw_o = o
    o = re.sub(r"[^A-Za-z, ]", " ", o).strip()
    if "," in o:
        # "LAST, FIRST M" — reliable
        last, _, rest = o.partition(",")
        toks = rest.strip().split()
        first = toks[0] if toks else ""
    else:
        toks = o.split()
        if len(toks) < 2:
            return None
        # Casing heuristic: ALL-CAPS no-comma is the GIS "LAST FIRST [MIDDLE]"
        # convention; mixed/Title-case is human "FIRST [MIDDLE] LAST".
        if raw_o.isupper():
            last, first = toks[0], toks[1]
        else:
            first, last = toks[0], toks[-1]
    last, first = last.strip().upper(), first.strip().upper()
    if len(last) < 2 or len(first) < 2:
        return None
    return last, first


_OFFENDER_LINK = re.compile(r"offenderID=\d+", re.I)
_NAME_CELL = re.compile(r"<td[^>]*>\s*([A-Z][A-Z .'-]{1,40}?)\s*</td>")


async def _dac_match(http: httpx.AsyncClient, last: str, first: str) -> Optional[dict]:
    """Search NC DAC by name; return match info if an offender with the same
    last+first is found, else None."""
    params = {"method": "list", "searchLastName": last, "searchFirstName": first}
    try:
        r = await http.get(DAC_URL, params=params, timeout=25.0,
                            headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        html = r.text
    except Exception:
        return None
    if not _OFFENDER_LINK.search(html):
        return None
    # Confirm a result row actually carries this last AND first name (the search
    # can be loose); the result table lists last/first in adjacent cells.
    n_results = len(_OFFENDER_LINK.findall(html))
    cells = [c.strip().upper() for c in _NAME_CELL.findall(html)]
    has_last = any(c == last for c in cells)
    has_first = any(c == first for c in cells)
    # Only flag a NEAR-UNIQUE name. A name returning many offenders (e.g. 24
    # "Robert Morgan"s) is noise; 1-2 exact matches is a usable lead. Even then
    # it's name-only (no DOB) → low confidence, stack-signal only.
    # 2026-06-19: require EXACTLY ONE result. With 2+ result rows, has_last and
    # has_first can match DIFFERENT offenders (cross-row), producing hard name
    # mismatches (e.g. last from row A + first from row B). A single result row
    # makes cross-row contamination impossible, so the name match is reliable.
    max_results = int(os.environ.get("INCARCERATION_MAX_RESULTS", "1"))
    if has_last and has_first and 1 <= n_results <= max_results:
        return {"state": "NC", "source": "NC DAC offender search",
                "matched_name": f"{first} {last}", "results": n_results,
                "confidence": "name_only_low"}
    return None


def _owner_of(li: Listing) -> Optional[str]:
    om = (li.raw or {}).get("owner_mailing") or {}
    return om.get("owner") or li.defendant or None


async def enrich_incarceration(listings: list[Listing], max_queries: int = 150) -> dict:
    """Flag listings whose owner matches a state corrections roster (NC now)."""
    targets = []
    for li in listings:
        if li.state != "NC":
            continue
        if (li.raw or {}).get("incarceration"):
            continue
        owner = _owner_of(li)
        if owner and _name_parts(owner):
            targets.append(li)
    sc_skipped = sum(1 for li in listings if li.state == "SC" and _owner_of(li) and _name_parts(_owner_of(li)))
    targets = targets[:max_queries]
    if not targets:
        log.info("incarceration.no_targets", sc_skipped=sc_skipped)
        return {"queried": 0, "matched": 0, "sc_skipped": sc_skipped}

    sem = asyncio.Semaphore(int(os.environ.get("INCARCERATION_CONCURRENCY", "2")))
    delay = float(os.environ.get("INCARCERATION_DELAY", "0.5"))
    counts = {"queried": 0, "matched": 0, "sc_skipped": sc_skipped}

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True) as http:
        async def one(li: Listing):
            last, first = _name_parts(_owner_of(li))
            async with sem:
                counts["queried"] += 1
                res = await _dac_match(http, last, first)
                if delay:
                    await asyncio.sleep(delay)
            if res:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["incarceration"] = res
                counts["matched"] += 1
        await asyncio.gather(*(one(li) for li in targets))
    log.info("incarceration.done", **counts)
    return counts
