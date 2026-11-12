"""Step 2: validate the 322 board rows carrying raw['jail_booking'] against
LIVE county jail rosters fetched right now.

Reuses the real production fetch logic from
foreclosure_scraper.scrapers.national.jail_bookings (same URLs, same vendor
dispatch) for the "is this person still in custody today" check. For the
four vendors that actually publish a middle name/initial in the raw roster
record (Zuercher, Citizen Connect, Tyler New World, LANSA/Greenville), this
script keeps the middle token that the production parsers *discard* so it
can run the project's own disambiguation primitive
(name_normalize.party_middle_verdict) — the same check
enrichment_jail_bookings.match_cross_county added 2026-10-02 after discovering
the uncorroborated name-only tier was fanning out, and the same primitive
used for the SC-divorce 44%-false-match audit. P2C systems (Buncombe,
Cleveland, Burke, Lincoln) publish no middle name at all on the public feed,
so for those four counties no corroboration is possible by vendor design —
that is itself a finding, not a script limitation.
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")

from foreclosure_scraper.name_normalize import party_middle_verdict  # noqa: E402
from foreclosure_scraper.scrapers.national.jail_bookings import (  # noqa: E402
    _fetch_roster as scraper_fetch_roster,
    CITIZEN_CONNECT_BASE,
    _CC_CARD_SPLIT, _CC_NAME_RE, _CC_ROW_RE, _CC_CHARGE_RE,
    _CC_TOTAL_RE, _CC_SHOWING_RE, _CC_PAGE_SIZE,
    _TNW_ROW_RE, _TNW_CELL_RE, _TNW_SHOWING_RE, _TNW_MAX_PAGES,
    _strip_tags,
)
from foreclosure_scraper.enrichment_jail_bookings import _search_lansa  # noqa: E402

SCRATCH = Path("/private/tmp/claude-502/-Users-cashhigh-Desktop/"
               "b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad")
CANDIDATES_PATH = SCRATCH / "candidates_raw.json"
RESULTS_PATH = Path(
    "/private/tmp/claude-502/-Users-cashhigh-Desktop/"
    "b86058dc-f10e-4c7b-a7fd-37f22fac2920/scratchpad/jail_validation_results.json")

# vendor/target config for every county that actually showed up among the 322
# candidates. Buncombe/Cleveland/Cherokee/Anderson/Laurens/Oconee/Henderson/
# Gaston are verbatim from the scraper module's own ROSTERS list; Burke and
# Lincoln are the same vendors (p2c_centralsquare / p2c_jqgrid), just not in
# that module's own county list — their targets come straight from
# enrichment_jail_bookings.ROSTERS, the list actually used when these board
# rows were written.
BULK_TARGETS: dict[tuple[str, str], tuple[str, str]] = {
    ("NC", "Buncombe"): ("p2c_centralsquare",
                         "https://buncombecountyso.policetocitizen.com|23"),
    ("NC", "Cleveland"): ("p2c_jqgrid", "http://74.218.167.200/p2c"),
    ("SC", "Cherokee"): ("zuercher", "cherokee-so-sc"),
    ("SC", "Anderson"): ("zuercher", "anderson-so-sc"),
    ("SC", "Laurens"): ("zuercher", "laurens-911-sc"),
    ("SC", "Oconee"): ("zuercher", "oconee-so-sc"),
    ("NC", "Henderson"): ("citizen_connect", "HendersonCoNC|NC0450000"),
    ("NC", "Gaston"): ("tyler_inmate_inquiry",
                       "https://tepsweb.cityofgastonia.com/NewWorld.InmateInquiry/GastonCounty"),
    ("NC", "Burke"): ("p2c_centralsquare",
                      "https://morgantonpdnc.policetocitizen.com|342"),
    ("NC", "Lincoln"): ("p2c_jqgrid", "http://p2c.lincolnsheriff.org"),
}

NO_MIDDLE_VENDORS = {"p2c_centralsquare", "p2c_jqgrid"}


def _norm_key(last: str, first: str) -> tuple[str, str]:
    return (re.sub(r"[^A-Z]", "", (last or "").upper()),
            re.sub(r"[^A-Z]", "", (first or "").upper()))


# ---------------------------------------------------------------------------
# Middle-name-preserving fetchers for the three bulk vendors that actually
# publish one. Same hosts/endpoints/payloads as the production scraper; the
# only change is keeping the 2nd name token instead of discarding it.
# ---------------------------------------------------------------------------

async def _fetch_zuercher_full(subdomain: str) -> list[dict]:
    from curl_cffi.requests import AsyncSession
    from datetime import datetime, timezone
    url = f"https://{subdomain}.zuercherportal.com/api/portal/inmates/load"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {"name": "", "race": "all", "sex": "all", "cell_block": "all",
            "held_for_agency": "any", "in_custody": now,
            "paging": {"count": 2000, "start": 0},
            "sorting": {"sort_by_column_tag": "name", "sort_descending": False}}
    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.post(url, json=body, timeout=30)
            recs = (r.json() or {}).get("records") or []
    except Exception as exc:  # noqa: BLE001
        print(f"  [fetch_fail] zuercher {subdomain}: {exc}")
        return []
    for rec in recs:
        name = rec.get("name") or ""
        if "," not in name:
            continue
        last, _, rest = name.partition(",")
        toks = rest.strip().split()
        if not toks or not last.strip():
            continue
        first = toks[0].strip().upper()
        middle = toks[1].strip().upper() if len(toks) > 1 else ""
        out.append({
            "last": last.strip().upper(), "first": first, "middle": middle,
            "full_name_raw": name,
            "dob": rec.get("dob"), "arrest_date": rec.get("arrest_date"),
            "charge": rec.get("hold_reasons") or rec.get("charges"),
            "release_date": rec.get("release_date") or rec.get("actual_release_date"),
        })
    return out


async def _fetch_citizen_connect_full(target: str) -> list[dict]:
    from curl_cffi.requests import AsyncSession
    import math
    agency, _, jms = target.partition("|")
    page_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID={agency}"
    api = (f"{CITIZEN_CONNECT_BASE}/bookingsearch/fetchesforajax/"
           "fetch_current_confinements.php")
    hdr = {"X-Requested-With": "XMLHttpRequest", "Referer": page_url}
    out: list[dict] = []

    def parse(body: str) -> list[dict]:
        recs = []
        for card in (body or "").split(_CC_CARD_SPLIT)[1:]:
            nm = _CC_NAME_RE.search(card)
            if not nm:
                continue
            full_name = html.unescape(nm.group(1)).strip()
            toks = full_name.split()
            if len(toks) < 2:
                continue
            first, last = toks[0].upper(), toks[-1].upper()
            middle = toks[1].upper() if len(toks) > 2 else ""
            fields = {k.strip().rstrip(":"): html.unescape(v).strip()
                      for k, v in _CC_ROW_RE.findall(card)}
            charges = [_strip_tags(c) for c in _CC_CHARGE_RE.findall(card)]
            recs.append({
                "last": last, "first": first, "middle": middle,
                "full_name_raw": full_name,
                "dob": fields.get("Date of Birth"),
                "arrest_date": fields.get("Booked") or fields.get("Arrest Date/Time"),
                "charge": "; ".join(c for c in charges if c),
            })
        return recs

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            await s.get(page_url, timeout=30)
            r = await s.post(api, headers=hdr, timeout=60, data={
                "JMSAgencyID": jms, "search": "", "agency": "", "sort": "name"})
            body = r.text or ""
            if "booking-card" not in body:
                return []
            out.extend(parse(body))
            tm = _CC_TOTAL_RE.search(body)
            sm = _CC_SHOWING_RE.search(body)
            total = int(tm.group(1)) if tm else (int(sm.group(2)) if sm else len(out))
            pages = min(math.ceil(total / _CC_PAGE_SIZE) if total else 1, 60)
            for page in range(2, pages + 1):
                await asyncio.sleep(0.3)
                pr = await s.post(api, headers=hdr, timeout=60, data={
                    "IDX": page, "search": "", "agency": "", "sort": "name"})
                recs = parse(pr.text or "")
                if not recs:
                    break
                out.extend(recs)
    except Exception as exc:  # noqa: BLE001
        print(f"  [fetch_fail] citizen_connect {target}: {exc}")
        return out
    return out


async def _fetch_tyler_full(base: str) -> list[dict]:
    from curl_cffi.requests import AsyncSession
    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            page = 1
            while page <= _TNW_MAX_PAGES:
                r = await s.get(f"{base}?InCustody=True&Page={page}", timeout=60)
                body = r.text or ""
                page_recs = 0
                for rowm in _TNW_ROW_RE.finditer(body):
                    row = rowm.group(1)
                    cells = {k: _strip_tags(v) for k, v in _TNW_CELL_RE.findall(row)}
                    name = cells.get("Name")
                    if not name or "," not in name:
                        continue
                    if cells.get("InCustody", "").upper() != "YES":
                        continue
                    last, _, rest = name.partition(",")
                    toks = rest.strip().split()
                    if not toks or not last.strip():
                        continue
                    first = toks[0].strip().upper()
                    middle = toks[1].strip().upper() if len(toks) > 1 else ""
                    out.append({
                        "last": last.strip().upper(), "first": first, "middle": middle,
                        "full_name_raw": html.unescape(name),
                        "dob": cells.get("DateOfBirth"),
                        "arrest_date": None, "charge": "",
                    })
                    page_recs += 1
                if page_recs == 0:
                    break
                sm = _TNW_SHOWING_RE.search(body)
                if not sm or int(sm.group(2)) >= int(sm.group(3)):
                    break
                page += 1
                await asyncio.sleep(0.3)
    except Exception as exc:  # noqa: BLE001
        print(f"  [fetch_fail] tyler {base}: {exc}")
        return out
    return out


async def fetch_all_rosters(needed: set[tuple[str, str]]) -> dict:
    """Returns {(state, county): {"vendor": str, "records": [dict,...]}}"""
    out = {}
    tasks = []
    keys = []
    for key in sorted(needed):
        vendor, target = BULK_TARGETS[key]
        keys.append((key, vendor, target))
        if vendor == "zuercher":
            tasks.append(_fetch_zuercher_full(target))
        elif vendor == "citizen_connect":
            tasks.append(_fetch_citizen_connect_full(target))
        elif vendor == "tyler_inmate_inquiry":
            tasks.append(_fetch_tyler_full(target))
        else:  # p2c_centralsquare / p2c_jqgrid -- no middle available, use
               # the production dispatcher verbatim
            tasks.append(scraper_fetch_roster(key[0], key[1], vendor, target))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for (key, vendor, target), recs in zip(keys, results):
        if isinstance(recs, Exception):
            print(f"  [EXC] {key}: {recs}")
            recs = []
        out[key] = {"vendor": vendor, "records": recs, "count": len(recs)}
        print(f"  live roster {key}: vendor={vendor} count={len(recs)}")
    return out


def build_index(records: list[dict]) -> dict[tuple, list[dict]]:
    idx: dict[tuple, list[dict]] = {}
    for rec in records:
        last = rec.get("last") or (rec.get("lastname") if isinstance(rec, dict) else None)
        first = rec.get("first") or (rec.get("firstname") if isinstance(rec, dict) else None)
        if not last or not first:
            continue
        idx.setdefault(_norm_key(last, first), []).append(rec)
    return idx


def owner_string(cand: dict) -> str | None:
    om = cand.get("owner_mailing") or {}
    if isinstance(om, dict) and om.get("owner"):
        return om["owner"]
    return cand.get("defendant") or cand.get("owner_name")


async def main() -> None:
    candidates = json.loads(CANDIDATES_PATH.read_text())
    print(f"loaded {len(candidates)} candidates")

    needed = set()
    for c in candidates:
        jb = c.get("jail_booking") or {}
        key = (c.get("state"), jb.get("county"))
        if key in BULK_TARGETS:
            needed.add(key)
    print(f"bulk rosters needed: {sorted(needed)}")

    rosters = await fetch_all_rosters(needed)

    # Greenville SC (LANSA per-name search) -- the 1 candidate there
    greenville_cands = [c for c in candidates
                        if (c.get("jail_booking") or {}).get("county") == "Greenville"]
    greenville_hits: dict[tuple, list[dict]] = {}
    for c in greenville_cands:
        owner = owner_string(c)
        parts = None
        jb = c.get("jail_booking") or {}
        mn = jb.get("matched_name") or ""
        toks = mn.split()
        if len(toks) >= 2:
            last = toks[-1]
            recs = await _search_lansa(
                "https://app.greenvillecounty.org/cgi-bin/lansaweb?"
                "procfun+JAW_00+JAW00EX+GP1+eng", last)
            for r in recs:
                r["full_name_raw"] = f"{r.get('first','')} {r.get('middle','')} {r.get('last','')}".strip()
            greenville_hits.setdefault(_norm_key(*toks[-1:], *toks[:1]), []).extend(recs)
            await asyncio.sleep(0.4)

    results = []
    n_current = 0
    n_stale = 0
    n_conflict = 0
    n_agrees = 0
    n_unverified = 0
    n_no_roster = 0
    n_multi_person_same_name = 0

    for c in candidates:
        jb = c.get("jail_booking") or {}
        county = jb.get("county")
        state = c.get("state")
        key = (state, county)
        board_last_first = (jb.get("matched_name") or "").split()
        if len(board_last_first) >= 2:
            # matched_name is "FIRST LAST" (see _apply_hit: f"{first} {last}")
            m_first = board_last_first[0]
            m_last = " ".join(board_last_first[1:])
        else:
            m_first = m_last = None

        row_result = {
            "defendant": c.get("defendant"),
            "owner_name_used": owner_string(c),
            "state": state,
            "property_county": c.get("county"),
            "roster_county": county,
            "street_address": c.get("street_address"),
            "board_matched_name": jb.get("matched_name"),
            "board_charge": jb.get("charge"),
            "board_arrest_date": jb.get("arrest_date"),
            "board_release_status": jb.get("release_status"),
            "board_confidence": jb.get("confidence"),
        }

        vendor = BULK_TARGETS.get(key, (None, None))[0]
        if county == "Greenville":
            vendor = "lansa"
            hits = greenville_hits.get(_norm_key(m_last or "", m_first or ""), [])
        elif key in rosters:
            idx = build_index(rosters[key]["records"])
            hits = idx.get(_norm_key(m_last or "", m_first or ""), [])
        else:
            hits = None  # no roster fetched (shouldn't happen for our 10 counties)

        row_result["vendor"] = vendor

        if hits is None:
            row_result["live_status"] = "roster_fetch_unavailable"
            n_no_roster += 1
        elif not hits:
            row_result["live_status"] = "not_in_current_roster_(released_or_stale)"
            n_stale += 1
        else:
            row_result["live_status"] = "still_in_current_roster"
            n_current += 1
            row_result["live_hit_count"] = len(hits)
            row_result["live_hits"] = [
                {"full_name_raw": h.get("full_name_raw"), "dob": h.get("dob"),
                 "arrest_date": h.get("arrest_date"), "charge": h.get("charge")}
                for h in hits
            ]
            if len(hits) > 1:
                n_multi_person_same_name += 1
                row_result["note"] = "multiple distinct live records share this exact name"

            if vendor in NO_MIDDLE_VENDORS:
                row_result["middle_verdict"] = "unverified_no_middle_published_by_vendor"
                n_unverified += 1
            else:
                owner = owner_string(c)
                # party_middle_verdict expects "FIRST [MIDDLE] LAST" ordering
                # (see enrichment_jail_bookings._cross_county_corroborated,
                # which builds its party string the same way) -- Zuercher and
                # Tyler publish "Last, First Middle" on the wire, so build the
                # party string from the already-split last/first/middle
                # fields rather than passing the raw vendor string through.
                party_strings = [
                    f"{h.get('first','')} {h.get('middle','')} {h.get('last','')}".strip()
                    for h in hits if h.get("first") and h.get("last")
                ]
                verdict = party_middle_verdict(owner, party_strings)
                row_result["middle_verdict"] = verdict
                if verdict == "agrees":
                    n_agrees += 1
                elif verdict == "conflict":
                    n_conflict += 1
                else:
                    n_unverified += 1

        results.append(row_result)

    total = len(results)
    summary = {
        "total_candidates_jail_booking": total,
        "total_candidates_jail_booking_new": 0,
        "checked_live": total - n_no_roster,
        "still_in_custody_current": n_current,
        "stale_released_or_not_found": n_stale,
        "roster_fetch_unavailable": n_no_roster,
        "middle_name_corroboration": {
            "agrees_same_person": n_agrees,
            "conflict_different_person": n_conflict,
            "unverified_no_corroboration_possible": n_unverified,
        },
        "multiple_distinct_people_share_matched_name_live": n_multi_person_same_name,
        "pct_current": round(100 * n_current / total, 1) if total else None,
        "pct_stale": round(100 * n_stale / total, 1) if total else None,
        "pct_conflict_of_those_with_middle_data": (
            round(100 * n_conflict / (n_agrees + n_conflict), 1)
            if (n_agrees + n_conflict) else None
        ),
        "pct_unverified_of_checked": round(100 * n_unverified / total, 1) if total else None,
    }

    print(json.dumps(summary, indent=2))

    RESULTS_PATH.write_text(json.dumps({
        "summary": summary,
        "rows": results,
    }, indent=2, default=str))
    print(f"\nwrote {len(results)} row results to {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
