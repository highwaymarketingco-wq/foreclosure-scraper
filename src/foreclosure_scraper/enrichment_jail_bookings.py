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
  * CentralSquare P2C (modern) — Buncombe NC (name+age+booking date+charge; the
    public roster redacts DOB). This build is the "session/token handshake"
    variant: the SPA at policetocitizen.com sets an XSRF-TOKEN cookie only after
    an app-route GET, which we then echo back as the X-XSRF-TOKEN header on the
    JSON /api/Inmates/<id> search POST. The endpoint caps Take at ~200 and never
    fills TotalCount, so we page in blocks of 200 until a short page. Free,
    compliant (open JSON-XHR + standard anti-forgery echo, no login/CAPTCHA/WAF
    defeat). Verified live 2026-07-01: 542 in custody.
Adding a county = one ROSTERS entry once its vendor endpoint is confirmed
(Henderson NC Southern Software still needs a session/token handshake — deferred;
see project_jail_booking_sources memory for endpoints).

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

# (state, county, vendor, target) — target is the Zuercher subdomain, the P2C
# jqGrid base URL, or (for the modern CentralSquare P2C) the "<host>|<listId>"
# pair whose XHR search is /api/Inmates/<listId>.
ROSTERS = [
    ("SC", "Cherokee", "zuercher", "cherokee-so-sc"),
    ("SC", "Anderson", "zuercher", "anderson-so-sc"),
    ("NC", "Cleveland", "p2c_jqgrid", "http://74.218.167.200/p2c"),
    ("NC", "Buncombe", "p2c_centralsquare",
     "https://buncombecountyso.policetocitizen.com|23"),
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


async def _fetch_p2c_centralsquare(target: str) -> list[dict]:
    """Modern CentralSquare P2C (policetocitizen.com) current-inmate roster.

    Handshake: GET an app route (/en/Inmates) so the SPA hands back an
    XSRF-TOKEN cookie, then echo it as the X-XSRF-TOKEN header on the JSON
    search POST to /api/Inmates/<listId>. The endpoint rejects Take>~200 with
    a 400 and never populates TotalCount, so page in blocks of 200 until a
    short page. DOB is redacted on the public feed; Age + ArrestDate survive.
    Compliant: open JSON-XHR + standard anti-forgery echo, no login/CAPTCHA.
    """
    from curl_cffi.requests import AsyncSession
    host, _, list_id = target.partition("|")
    list_id = list_id or "23"
    api = f"{host}/api/Inmates/{list_id}"
    page_size = 200
    out: list[dict] = []
    try:
        # verify=False mirrors the repo's other AsyncSession enrichers
        # (gaston_rod, sc_divorce): it tolerates a TLS-intercepting proxy in the
        # run environment, NOT a cert/WAF defeat on the source itself.
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            # 1) establish the XSRF-TOKEN cookie via an app-route GET
            await s.get(f"{host}/en/Inmates", timeout=25)
            token = s.cookies.get("XSRF-TOKEN")
            if not token:
                log.warning("jail.p2c_cs_no_token", host=host)
                return []
            hdr = {"X-XSRF-TOKEN": token,
                   "Content-Type": "application/json",
                   "Accept": "application/json, text/plain, */*",
                   "Referer": f"{host}/en/Inmates", "Origin": host}
            skip = 0
            while True:
                body = {
                    "FilterOptionsParameters": {
                        "IntersectionSearch": True, "SearchText": "",
                        "Parameters": []},
                    "IncludeCount": True,
                    "PagingOptions": {
                        "SortOptions": [{"Name": "ArrestDate",
                                         "SortDirection": "Descending",
                                         "Sequence": 1}],
                        "Take": page_size, "Skip": skip}}
                r = await s.post(api, headers=hdr, json=body, timeout=60)
                recs = (r.json() or {}).get("Inmates") or []
                if not recs:
                    break
                for rec in recs:
                    last = (rec.get("LastName") or "").strip().upper()
                    first = (rec.get("FirstName") or "").strip().upper()
                    if not last or not first:
                        continue
                    out.append({
                        "last": last, "first": first,
                        "dob": rec.get("DateOfBirth"),  # redacted on this feed
                        "age": rec.get("Age"),
                        "arrest_date": rec.get("ArrestDate"),
                        "charge": (rec.get("PrimaryChargeDescription") or "")[:300]})
                if len(recs) < page_size:
                    break
                skip += page_size
                if skip > 5000:  # safety cap; roster is ~540
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("jail.p2c_cs_fail", host=host, error=str(exc)[:120])
        return []
    return out


async def _load_roster(state: str, county: str, vendor: str, target: str):
    if vendor == "zuercher":
        recs = await _fetch_zuercher(target)
    elif vendor == "p2c_centralsquare":
        recs = await _fetch_p2c_centralsquare(target)
    else:
        recs = await _fetch_p2c_jqgrid(target)
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
            "roster_dob": hit.get("dob"), "roster_age": hit.get("age"),
            "arrest_date": hit.get("arrest_date"),
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
