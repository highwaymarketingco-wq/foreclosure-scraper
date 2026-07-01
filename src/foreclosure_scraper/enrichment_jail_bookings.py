"""County-jail booking enrichment — pre-trial / local-hold incarceration signal.

The state-prison match (enrichment_incarceration: NC DAC + SC SCDC) only catches
people already sentenced to state custody. County jail rosters catch the much
larger pool of PRE-TRIAL detainees and local holds — an owner sitting in the
county jail (can't manage the property, family needs liquidity, bond to make) is
a motivated seller the state rosters miss entirely.

We fetch each county's CURRENT in-custody roster once per run (free public
"jail viewer" APIs), index it by (last, first), and match resolved owner names.
Several rosters expose full DOB, which we keep for future disambiguation (we
still match name-only today since we have no owner DOB — so this stays a
LOW-confidence STACK signal, meaningful only combined with other distress).

Covered now (verified live 2026-07-01, free, no login/CAPTCHA):
  * Zuercher portal  — Cherokee SC (dob+charges), Anderson SC (name+charges, no dob)
  * CentralSquare P2C jqGrid — Cleveland NC (dob+charges)
Adding a county = one ROSTERS entry once its vendor endpoint is confirmed
(Henderson NC Southern Software + Buncombe NC modern-P2C need a session/token
handshake — deferred; see project_jail_booking_sources memory for endpoints).

Sets raw['jail_booking'] (detail) + raw['incarceration'] (so distress_score's
existing LEGAL incarceration signal, weight 8, picks it up). Free + compliant.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

import structlog

from .models import Listing
from .enrichment_incarceration import _name_parts, _owner_of

log = structlog.get_logger()

# (state, county, vendor, target) — target is the Zuercher subdomain or P2C base.
ROSTERS = [
    ("SC", "Cherokee", "zuercher", "cherokee-so-sc"),
    ("SC", "Anderson", "zuercher", "anderson-so-sc"),
    ("NC", "Cleveland", "p2c_jqgrid", "http://74.218.167.200/p2c"),
]


def _norm_key(last: str, first: str) -> tuple[str, str]:
    return (re.sub(r"[^A-Z]", "", (last or "").upper()),
            re.sub(r"[^A-Z]", "", (first or "").upper()))


def _split_zuercher_name(name: str) -> Optional[tuple[str, str]]:
    """'Adams, Bruce Edward' -> ('ADAMS', 'BRUCE')."""
    if not name or "," not in name:
        return None
    last, _, rest = name.partition(",")
    toks = rest.strip().split()
    if not toks or not last.strip():
        return None
    return last.strip().upper(), toks[0].strip().upper()


async def _fetch_zuercher(subdomain: str) -> list[dict]:
    from curl_cffi.requests import AsyncSession
    url = f"https://{subdomain}.zuercherportal.com/api/portal/inmates/load"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {"name": "", "race": "all", "sex": "all", "cell_block": "all",
            "held_for_agency": "any", "in_custody": now,
            "paging": {"count": 2000, "start": 0},
            "sorting": {"sort_by_column_tag": "name", "sort_descending": False}}
    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome") as s:
            r = await s.post(url, json=body, timeout=30)
            recs = (r.json() or {}).get("records") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("jail.zuercher_fail", subdomain=subdomain, error=str(exc)[:120])
        return []
    for rec in recs:
        parts = _split_zuercher_name(rec.get("name") or "")
        if not parts:
            continue
        last, first = parts
        charges = rec.get("hold_reasons") or rec.get("charges") or ""
        if isinstance(charges, list):
            charges = "; ".join(str(x) for x in charges)[:300]
        out.append({"last": last, "first": first, "dob": rec.get("dob"),
                    "arrest_date": rec.get("arrest_date"), "charge": str(charges)[:300]})
    return out


async def _fetch_p2c_jqgrid(base: str) -> list[dict]:
    from curl_cffi.requests import AsyncSession
    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome") as s:
            await s.get(f"{base}/jailinmates.aspx", timeout=20)  # session cookie
            r = await s.post(f"{base}/jqHandler.ashx?op=s",
                             data={"t": "ii", "_search": "false", "rows": "2000",
                                   "page": "1", "sidx": "disp_name", "sord": "asc"},
                             timeout=30)
            rows = (r.json() or {}).get("rows") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("jail.p2c_fail", base=base, error=str(exc)[:120])
        return []
    for rw in rows:
        last = (rw.get("lastname") or "").strip().upper()
        first = (rw.get("firstname") or "").strip().upper()
        if not last or not first:
            continue
        out.append({"last": last, "first": first, "dob": rw.get("dob"),
                    "arrest_date": rw.get("disp_arrest_date"),
                    "charge": (rw.get("chrgdesc") or rw.get("disp_charge") or "")[:300]})
    return out


async def _load_roster(state: str, county: str, vendor: str, target: str):
    recs = await (_fetch_zuercher(target) if vendor == "zuercher"
                  else _fetch_p2c_jqgrid(target))
    index: dict[tuple, dict] = {}
    for rec in recs:
        index.setdefault(_norm_key(rec["last"], rec["first"]), rec)
    log.info("jail.roster", county=county, vendor=vendor, inmates=len(recs))
    return (state, county), index


async def enrich_jail_bookings(listings: list[Listing]) -> dict:
    """Match resolved owner names against covered county jail rosters."""
    covered = {(s, c) for s, c, _, _ in ROSTERS}
    # Only bother if some in-scope lead sits in a covered county.
    if not any((li.state, (li.county or "").replace(" County", "").strip().title()) in covered
               for li in listings):
        log.info("jail.no_targets")
        return {"matched": 0}

    rosters = dict(await asyncio.gather(
        *[_load_roster(s, c, v, t) for s, c, v, t in ROSTERS]))

    counts = {"matched": 0}
    for li in listings:
        county = (li.county or "").replace(" County", "").strip().title()
        idx = rosters.get((li.state, county))
        if not idx or (li.raw or {}).get("jail_booking"):
            continue
        parts = _name_parts(_owner_of(li) or "")
        if not parts:
            continue
        hit = idx.get(_norm_key(*parts))
        if not hit:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        raw["jail_booking"] = {
            "county": county, "state": li.state,
            "matched_name": f"{parts[1]} {parts[0]}",
            "roster_dob": hit.get("dob"), "arrest_date": hit.get("arrest_date"),
            "charge": hit.get("charge"), "confidence": "name_only_low",
        }
        # Reuse the existing LEGAL incarceration distress signal.
        raw.setdefault("incarceration", {
            "state": li.state, "source": f"{county} County jail roster",
            "matched_name": f"{parts[1]} {parts[0]}", "confidence": "name_only_low"})
        li.raw = raw
        counts["matched"] += 1
    log.info("jail.done", matched=counts["matched"])
    return counts
