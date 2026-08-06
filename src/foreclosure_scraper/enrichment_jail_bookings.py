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

Two access shapes:

BULK ROSTERS (fetch the whole current in-custody list once/run, index by name):
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
  * Southern Software Citizen Connect — Henderson NC. PHP roster whose "Get
    Current Confinements" button XHRs fetch_current_confinements.php; the
    endpoint needs a PHP session seeded by one GET of the booking-search page
    (?AgencyID=HendersonCoNC) or it answers 500 "Session AgencyID not set".
    20 cards/page, pager posts IDX=<page>. Publishes FULL DOB. Verified live
    2026-07-31: 182 in custody, DOB on 182/182.
  * Tyler New World InmateInquiry — Gaston NC. Plain GET form, so
    ?InCustody=True&Page=<n> yields the whole roster 100 rows at a time with
    FULL DOB, the in-custody flag and the scheduled release date. This replaces
    Gaston's retired newworld.aegis.webportal InmateInquiry.aspx per-name
    search, which now 302s to Shared/Default.aspx and returns nothing. Verified
    live 2026-07-31: 695 in custody, DOB on 695/695.

PER-NAME SEARCH ROSTERS (no "show all"; we search each in-scope owner's last name):
  * Greenville SC — LANSA-for-the-Web WEBEVENT postback
    (app.greenvillecounty.org/cgi-bin/lansaweb, proc JAW_00 / func JAW00EX).
    GET the framed entry to get the session-scoped WEBEVENT action token + ~36
    hidden fields; POST them back with ASC_NML (last), ASC_NMF (first) and
    ASTDRENTST=SEARCH (what the page's Search link sets before HandleEvent). The
    grid is current detainees only: Name (LAST, FIRST MIDDLE) | Book Date | Race
    | Sex | Age | Height | Weight, headed by "Records Found: N". An Incapsula
    script is present but passive — the page and POST both complete with plain
    curl_cffi chrome impersonation (no WAF token solved/defeated). Greenville is
    the largest SC jail population. Verified live 2026-07-01: SMITH -> 28 records.

Adding a BULK county = one ROSTERS entry; a SEARCH county = one SEARCH_ROSTERS
entry, once its vendor endpoint is confirmed. Spartanburg SC has no entry
because its portal is offline, not because it is walled: the Sheriff's Bookings
Search 302s to http://mugshots.spartanburgsheriff.org/, whose host stopped
answering on :80 and :443 (last Internet Archive capture 2026-03-08), and the
county is not a Zuercher / P2C / JailTracker tenant.

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
# The Citizen Connect / Tyler fetchers are shared verbatim with the standalone
# jail-bookings scraper rather than duplicated here.
from .scrapers.national.jail_bookings import (
    _fetch_citizen_connect,
    _fetch_tyler_detail,
    _fetch_tyler_inmate_inquiry,
)

log = structlog.get_logger()

# (state, county, vendor, target) — target is the Zuercher subdomain, the P2C
# jqGrid base URL, the "<host>|<listId>" pair whose XHR search is
# /api/Inmates/<listId> (modern CentralSquare P2C), the
# "<AgencyID>|<JMSAgencyID>" pair (Citizen Connect), or the app base URL
# (Tyler New World InmateInquiry).
ROSTERS = [
    ("SC", "Cherokee", "zuercher", "cherokee-so-sc"),
    ("SC", "Anderson", "zuercher", "anderson-so-sc"),
    ("NC", "Cleveland", "p2c_jqgrid", "http://74.218.167.200/p2c"),
    ("NC", "Buncombe", "p2c_centralsquare",
     "https://buncombecountyso.policetocitizen.com|23"),
    ("NC", "Henderson", "citizen_connect", "HendersonCoNC|NC0450000"),
    ("NC", "Gaston", "tyler_inmate_inquiry",
     "https://tepsweb.cityofgastonia.com/NewWorld.InmateInquiry/GastonCounty"),
    # Added 2026-08-06. All three ride adapters that already existed — Polk and
    # Transylvania are the same Southern Software tenant as Henderson (only the
    # JMSAgencyID differs), Burke is the same CentralSquare P2C as Buncombe.
    # Verified live through the real adapters that day: Burke 175 in custody,
    # Transylvania 83, Polk 44. The incarceration signal covered 15 leads across
    # all 18 counties before this.
    ("NC", "Polk", "citizen_connect", "PolkCoNC|NC0750000"),
    ("NC", "Transylvania", "citizen_connect", "TransylvaniaCoNC|NC0880000"),
    ("NC", "Burke", "p2c_centralsquare",
     "https://morgantonpdnc.policetocitizen.com|342"),
    # Lincoln runs the SAME CentralSquare jqGrid build as Cleveland — only the
    # host differs. Verified live through the existing adapter: 173 in custody.
    # NB the vendor typos its own agency as 'Lncoln County'; there is also a
    # Lincoln County NEBRASKA P2C, so match on the host, never the agency string.
    ("NC", "Lincoln", "p2c_jqgrid", "http://p2c.lincolnsheriff.org"),
]

# (state, county, vendor, target) for the PER-NAME search vendors — no bulk
# "show all", so we search each in-scope owner's last name at match time.
SEARCH_ROSTERS = [
    ("SC", "Greenville", "lansa",
     "https://app.greenvillecounty.org/cgi-bin/lansaweb?procfun+JAW_00+JAW00EX+GP1+eng"),
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


# ---- per-name search vendors -------------------------------------------------

_NAME_RE = re.compile(r'name=["\']([^"\']+)["\']')
_VALUE_RE = re.compile(r'value=["\']([^"\']*)["\']')


def _cell_text(cell_html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell_html or "")).replace(
        "&nbsp;", " ").replace("&quot;", '"').strip()


def _split_comma_name(name: str) -> Optional[tuple[str, str]]:
    """'Smith, Christopher Michael' -> ('SMITH', 'CHRISTOPHER')."""
    if not name or "," not in name:
        return None
    last, _, rest = name.partition(",")
    toks = rest.strip().split()
    if not toks or not last.strip():
        return None
    return last.strip().upper(), toks[0].strip().upper()


_GVL_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_GVL_ACTION_RE = re.compile(r'action=["\']([^"\']*WEBEVENT[^"\']*)["\']', re.I)


async def _search_lansa(entry: str, last: str, first: str = "") -> list[dict]:
    """Greenville SC LANSA-for-the-Web WEBEVENT inmate search.

    GET the framed entry -> session-scoped WEBEVENT action token + ~36 hidden
    fields. POST them back with ASC_NML (last name) + ASTDRENTST=SEARCH (what the
    page's Search link sets before HandleEvent). Grid is current detainees only:
    Name | Book Date | Race | Sex | Age | Height | Weight. Compliant: replays the
    page's own postback; the Incapsula script present on the page is passive (no
    token solved/defeated).

    We deliberately search by LAST NAME ONLY and filter first name client-side:
    the page's first-name box (ASC_NMF) is an unreliable exact/normalized match
    that returns 0 rows for names that plainly exist (verified: "SMITH, ALEX
    MATTHEW" is in the roster, yet ASC_NMF="ALEX" yields nothing), so echoing it
    would cause false negatives. The grid returns the alphabetical-by-first-name
    page 1 (~15 rows); LANSA's JS-driven WEBEVENT paging does not replay cleanly
    from a stateless POST, so for a very common surname a match beyond page 1 can
    be missed. That only costs RECALL — every row returned is a real current
    detainee (no false positives) — consistent with this module's LOW-confidence
    stack-signal philosophy. `first` is accepted for signature symmetry, unused.
    """
    from curl_cffi.requests import AsyncSession
    from urllib.parse import urlsplit, urlunsplit
    out: list[dict] = []
    if not last:
        return out
    sp = urlsplit(entry)
    origin = urlunsplit((sp.scheme, sp.netloc, "", "", ""))
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(entry, timeout=30,
                            headers={"Referer": origin + "/inmate_search.htm"})
            body = r.text or ""
            am = _GVL_ACTION_RE.search(body)
            if not am:
                log.warning("jail.lansa_no_action", entry=entry)
                return []
            # LANSA renders many inputs (not just type=hidden); pull them all.
            fields: dict = {}
            for im in re.finditer(r"<input[^>]*>", body, re.I):
                tag = im.group(0)
                n = _NAME_RE.search(tag)
                if not n:
                    continue
                v = _VALUE_RE.search(tag)
                fields[n.group(1)] = v.group(1) if v else ""
            fields["ASC_NML"] = last
            fields["ASC_NMF"] = ""              # see docstring: unreliable, skip
            fields["ASTDRENTST"] = "SEARCH"     # what the Search link sets
            action_url = origin + am.group(1)
            pr = await s.post(action_url, data=fields, timeout=45,
                              headers={"Referer": entry,
                                       "Content-Type": "application/x-www-form-urlencoded"})
            rbody = pr.text or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("jail.lansa_fail", entry=entry, error=str(exc)[:120])
        return []
    # Results table only: rows are Name | Book Date | Race | Sex | Age | Ht | Wt.
    # A data row's first cell is "LAST, FIRST ..." and its second a mm/dd/yyyy.
    for rowm in _GVL_ROW_RE.finditer(rbody):
        cells = [_cell_text(c) for c in
                 re.findall(r"<td[^>]*>(.*?)</td>", rowm.group(1), re.S)]
        cells = [c for c in cells if c]
        if len(cells) < 5:
            continue
        parts = _split_comma_name(cells[0])
        if not parts or not re.match(r"\d{1,2}/\d{1,2}/\d{4}$", cells[1]):
            continue
        last_n, first_n = parts
        age = cells[4] if len(cells) > 4 and cells[4].isdigit() else None
        out.append({"last": last_n, "first": first_n, "dob": None,
                    "age": age, "arrest_date": cells[1],  # Book Date
                    "race": cells[2] if len(cells) > 2 else "",
                    "sex": cells[3] if len(cells) > 3 else "", "charge": ""})
    return out


async def _search_vendor(vendor: str, target: str, last: str, first: str) -> list[dict]:
    if vendor == "lansa":
        return await _search_lansa(target, last, first)
    return []


async def _load_roster(state: str, county: str, vendor: str, target: str):
    if vendor == "zuercher":
        recs = await _fetch_zuercher(target)
    elif vendor == "p2c_centralsquare":
        recs = await _fetch_p2c_centralsquare(target)
    elif vendor == "citizen_connect":
        recs = await _fetch_citizen_connect(target)
    elif vendor == "tyler_inmate_inquiry":
        recs = await _fetch_tyler_inmate_inquiry(target)
    else:
        recs = await _fetch_p2c_jqgrid(target)
    index: dict[tuple, dict] = {}
    for rec in recs:
        index.setdefault(_norm_key(rec["last"], rec["first"]), rec)
    log.info("jail.roster", county=county, vendor=vendor, inmates=len(recs))
    return (state, county), index


def _plain_county(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().title()


async def _hydrate_tyler_hits(listings: list[Listing],
                              max_hydrations: int = 100) -> int:
    """Fill in booking date + charges for matched Tyler (Gaston) rows.

    The InmateInquiry grid carries DOB and the in-custody flag but keeps the
    booking date and charge list on each inmate's detail page. Fetching 700 of
    those every run would be rude and slow, so we fetch only the rows that
    actually matched an owner — normally a handful.
    """
    bases = {(s, c): t for s, c, v, t in ROSTERS if v == "tyler_inmate_inquiry"}
    done = 0
    for li in listings:
        if done >= max_hydrations:
            break
        jbk = (li.raw or {}).get("jail_booking") or {}
        detail_id = jbk.get("detail_id")
        base = bases.get((li.state, _plain_county(li)))
        if not detail_id or not base or jbk.get("arrest_date"):
            continue
        detail = await _fetch_tyler_detail(base, detail_id)
        if detail.get("arrest_date"):
            jbk["arrest_date"] = detail["arrest_date"]
        if detail.get("charge"):
            jbk["charge"] = detail["charge"]
        done += 1
        await asyncio.sleep(0.3)  # polite pacing
    if done:
        log.info("jail.tyler_hydrated", count=done)
    return done


def _apply_hit(li: Listing, county: str, first: str, last: str, hit: dict) -> None:
    """Attach the jail_booking detail + reuse the LEGAL incarceration signal."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    raw["jail_booking"] = {
        "county": county, "state": li.state,
        "matched_name": f"{first} {last}",
        "roster_dob": hit.get("dob"), "roster_age": hit.get("age"),
        "arrest_date": hit.get("arrest_date"),
        "charge": hit.get("charge"),
        "release_status": hit.get("release_status") or "in_custody",
        "scheduled_release": hit.get("scheduled_release"),
        # Vendor row id, kept only so _hydrate_tyler_hits can pull the booking
        # date + charges for this one person.
        "detail_id": hit.get("detail_id"),
        "confidence": "name_only_low",
    }
    raw.setdefault("incarceration", {
        "state": li.state, "source": f"{county} County jail roster",
        "matched_name": f"{first} {last}", "confidence": "name_only_low"})
    li.raw = raw


async def enrich_jail_bookings(listings: list[Listing],
                               max_searches_per_county: int = 200) -> dict:
    """Match resolved owner names against covered county jail rosters.

    Two lanes: BULK rosters (fetched once/run + indexed) and PER-NAME SEARCH
    rosters (Greenville), where we run one last-name lookup per in-scope
    owner (paced, capped per county).
    """
    bulk_covered = {(s, c) for s, c, _, _ in ROSTERS}
    search_covered = {(s, c): (v, t) for s, c, v, t in SEARCH_ROSTERS}
    covered = bulk_covered | set(search_covered)

    _county = _plain_county

    if not any((li.state, _county(li)) in covered for li in listings):
        log.info("jail.no_targets")
        return {"matched": 0}

    counts = {"matched": 0}

    # ---- lane 1: bulk rosters (fetch each once, index by name) ----
    bulk_needed = [(s, c, v, t) for s, c, v, t in ROSTERS
                   if any((li.state, _county(li)) == (s, c) for li in listings)]
    rosters = dict(await asyncio.gather(
        *[_load_roster(s, c, v, t) for s, c, v, t in bulk_needed])) if bulk_needed else {}
    for li in listings:
        idx = rosters.get((li.state, _county(li)))
        if not idx or (li.raw or {}).get("jail_booking"):
            continue
        parts = _name_parts(_owner_of(li) or "")
        if not parts:
            continue
        hit = idx.get(_norm_key(*parts))
        if not hit:
            continue
        _apply_hit(li, _county(li), parts[1], parts[0], hit)
        counts["matched"] += 1

    # Tyler grids omit booking date + charges; pull them for matched rows only.
    counts["hydrated"] = await _hydrate_tyler_hits(listings)

    # ---- lane 2: per-name search rosters (one lookup per in-scope owner) ----
    for (state, county), (vendor, target) in search_covered.items():
        # De-dupe owner names so we hit the vendor once per distinct surname pair.
        by_name: dict[tuple, list[Listing]] = {}
        for li in listings:
            if (li.state, _county(li)) != (state, county):
                continue
            if (li.raw or {}).get("jail_booking"):
                continue
            parts = _name_parts(_owner_of(li) or "")
            if parts:
                by_name.setdefault(_norm_key(*parts), []).append(li)
        if not by_name:
            continue
        searched = 0
        for _key, lis in by_name.items():
            if searched >= max_searches_per_county:
                break
            parts = _name_parts(_owner_of(lis[0]) or "")
            if not parts:
                continue
            last, first = parts
            recs = await _search_vendor(vendor, target, last, first)
            searched += 1
            index: dict[tuple, dict] = {}
            for rec in recs:
                index.setdefault(_norm_key(rec["last"], rec["first"]), rec)
            hit = index.get(_norm_key(last, first))
            if hit:
                for li in lis:
                    _apply_hit(li, county, first, last, hit)
                    counts["matched"] += 1
            await asyncio.sleep(0.4)  # polite pacing
        log.info("jail.search_roster", county=county, vendor=vendor, searched=searched)

    log.info("jail.done", matched=counts["matched"])
    return counts
