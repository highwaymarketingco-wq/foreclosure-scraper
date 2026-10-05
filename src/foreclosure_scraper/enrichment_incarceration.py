"""Incarceration distress signal — match property owners against inmate rosters.

An owner who is in prison/jail is a motivated seller (can't manage the property,
family needs liquidity). This is an ENRICHMENT, not a listing source: it takes
the owner names we resolved via #0 (owner_mailing) / the defendant field and
checks them against the state corrections roster, flagging raw['incarceration'].

NC: NC DAC Offender Public Information — queryable by last+first name
(webapps.doc.state.nc.us/opi/offendersearch.do), parseable HTML results.
SC: SCDC inmate search — the React SPA's backing servlet
(public.doc.state.sc.us/scdc-public/inmateSearch.do, params in the query string,
method=POST) returns a JSON offender array. Wired via _scdc_match (verified live
2026-07-01: 250 records for lastName=SMITH). Same single-exact-match noise gate
as NC. Both are STATE-PRISON rosters; county-jail bookings (pre-trial + local
holds, several exposing full DOB) are a separate net-new lane — see
docs/ or project_gap_analysis for the P2C/Zuercher/Southern-Software endpoints.

HONEST CAVEAT: this is a NAME-ONLY match (we have no owner DOB), so common
names produce false positives. It is therefore emitted as a LOW-confidence
STACK signal (confidence='name_only') — meaningful only when combined with
other distress on the same property, never as a standalone "this owner is in
prison" claim. Capped + paced to be polite to the state server.

NEGATIVE STAMPS (J-01, 2026-09-20): a miss used to leave nothing on the lead, so
every run re-queried the same first 150 non-matching owners and never got past
them (Mitchell, Oconee and Union, which have no county roster, stayed at zero).
A lookup the state actually answered with no match now writes
raw['incarceration_check'] = {checked_at, name, source, result}. Leads
with a fresh stamp are skipped, never-checked leads go first, then the oldest
stamps, and the per-run budget is shared round-robin across counties (footprint
counties before the rest) with a per-county cap. A lookup that FAILED (timeout,
5xx, an unrecognised page) is never stamped: that would repeat the divorce
enricher's 2026-09-18 bug, where an unsearched lead read as "checked, no
match". A host that answers 403/429 or a challenge page is left alone for the
rest of the run. The stamp is deliberately a separate key: raw['incarceration']
is the signal itself (distress_score weight 8) and must stay truthy only for a
real name match.

STALE-MATCH INVALIDATION (2026-10-03, same bug shape as owner_name/bop_federal/
owner_name_signal, found during the sweep that fixed those three): a match,
once stamped, was never revisited even after the owner on record changed —
`if (li.raw or {}).get("incarceration"): continue` treated any existing match
as permanent. Live-checked against the real board: 11 rows carry
raw['incarceration'] naming someone with zero relation to the CURRENT owner,
now a bank/city/HOA/LLC entity, plus several more where the current owner
parses to a different real person. `_clear_stale_matches` (run first, every
call) drops a match the current owner no longer supports so the row becomes
an ordinary candidate again — see `_owner_still_supports_match` for the real
examples. It only ever touches a match this module itself stamped (gated on
`source` in (DAC_SOURCE, SCDC_SOURCE)); a BOP or county-jail-roster match
sharing the same raw['incarceration'] key is left for enrichment_bop_federal.py
/ enrichment_jail_bookings.py to own.
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

from .config import in_scope
from .models import Listing
from .mailing_shape import mailing_dict
from .signal_freshness import incarceration_active

log = structlog.get_logger()

DAC_URL = "https://webapps.doc.state.nc.us/opi/offendersearch.do"
# SC Dept of Corrections public inmate search. The React SPA calls this with
# the query params in the URL (NOT the POST body) + method=POST; it returns a
# JSON array of inmate records. Verified live 2026-06-21.
SCDC_URL = "https://public.doc.state.sc.us/scdc-public/inmateSearch.do"
DAC_SOURCE = "NC DAC offender search"
SCDC_SOURCE = "SC DOC inmate search"

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
# Heading of the OPI results page. It is on a page with rows AND on the "No
# offenders found." page (checked live 2026-09-20 with a nonsense name), so it
# separates "the state answered: nobody" from a WAF / error page that says nothing.
_DAC_RESULTS_PAGE = re.compile(r"Offender\s+Search\s+Results", re.I)
# A host that shows one of these is telling us to stop, not answering the query.
_CHALLENGE = re.compile(r"captcha|access denied|just a moment|attention required|"
                        r"request unsuccessful|verify you are human|unusual traffic", re.I)
_BLOCK_STATUS = (401, 403, 407, 429)


@dataclass
class _Lookup:
    """One state-roster query, with the three facts the stamp logic needs.

    match      a name-only match that passed the single-exact-result gate, or None
    answered   the state gave a usable answer (a hit OR a real "nobody"); False for
               a timeout, a non-200, or a page we do not recognise. Only an answered
               miss may be stamped.
    blocked    403 / 429 / login / challenge: stop querying this host for the run
    candidates result rows the state returned (a miss on 24 "Robert Morgan"s is an
               answered miss, not an error)
    """
    match: Optional[dict] = None
    answered: bool = False
    blocked: bool = False
    candidates: int = 0


def _blocked_response(r) -> bool:
    return getattr(r, "status_code", 200) in _BLOCK_STATUS


async def _dac_lookup(http: httpx.AsyncClient, last: str, first: str) -> _Lookup:
    """Search NC DAC by name; a match needs the same last+first on EXACTLY ONE row."""
    params = {"method": "list", "searchLastName": last, "searchFirstName": first}
    try:
        r = await http.get(DAC_URL, params=params, timeout=25.0,
                            headers={"User-Agent": "Mozilla/5.0"})
        if _blocked_response(r):
            return _Lookup(blocked=True)
        if r.status_code != 200:
            return _Lookup()
        html = r.text
    except Exception:
        return _Lookup()
    if not _OFFENDER_LINK.search(html):
        if _DAC_RESULTS_PAGE.search(html):
            return _Lookup(answered=True)          # "No offenders found."
        return _Lookup(blocked=bool(_CHALLENGE.search(html)))  # unknown page: no answer
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
        return _Lookup(match={"state": "NC", "source": DAC_SOURCE,
                              "matched_name": f"{first} {last}", "results": n_results,
                              # NC DAC is the state prison system — never a
                              # county jail (see enrichment_jail_bookings.py)
                              # or federal BOP (see enrichment_bop_federal.py).
                              "facility_type": "prison",
                              "confidence": "name_only_low"},
                       answered=True, candidates=n_results)
    return _Lookup(answered=True, candidates=n_results)


async def _scdc_lookup(http: httpx.AsyncClient, last: str, first: str) -> _Lookup:
    """Search SC DOC by name; a match needs EXACTLY ONE exact last+first record."""
    params = {"lastName": last, "firstName": first, "scdcId": "", "sid": "",
              "phoneticMatch": ""}
    try:
        # SCDC wants the params in the QUERY STRING with method=POST (mirrors
        # the SPA's own fetch); a body POST returns an empty 200.
        r = await http.post(SCDC_URL, params=params, timeout=25.0,
                            headers={"User-Agent": "Mozilla/5.0",
                                     "Accept": "application/json, text/plain, */*"})
        if _blocked_response(r):
            return _Lookup(blocked=True)
        if r.status_code != 200:
            return _Lookup()
        recs = r.json()
    except Exception:
        return _Lookup()
    if not isinstance(recs, list):
        return _Lookup()                           # HTML / error body, not an answer
    if not recs:
        return _Lookup(answered=True)              # "[]": the state says nobody
    # Exact last+first (fields are space-padded in the feed). Require EXACTLY one
    # so a common name returning several offenders is treated as noise, not a hit.
    exact = [x for x in recs
             if str(x.get("lname") or "").strip().upper() == last
             and str(x.get("fname") or "").strip().upper() == first]
    max_results = int(os.environ.get("INCARCERATION_MAX_RESULTS", "1"))
    if 1 <= len(exact) <= max_results:
        rec = exact[0]
        return _Lookup(match={"state": "SC", "source": SCDC_SOURCE,
                              "matched_name": f"{first} {last}", "results": len(exact),
                              "scdc_id": str(rec.get("scdcId") or "").strip() or None,
                              # SC DOC (SCDC) is the state prison system.
                              "facility_type": "prison",
                              "confidence": "name_only_low"},
                       answered=True, candidates=len(recs))
    return _Lookup(answered=True, candidates=len(recs))


async def _dac_match(http: httpx.AsyncClient, last: str, first: str) -> Optional[dict]:
    """Match info if NC DAC lists exactly one offender with this last+first, else None."""
    return (await _dac_lookup(http, last, first)).match


async def _scdc_match(http: httpx.AsyncClient, last: str, first: str) -> Optional[dict]:
    """Match info if SC DOC lists exactly one offender with this last+first, else None."""
    return (await _scdc_lookup(http, last, first)).match


def _owner_of(li: Listing) -> Optional[str]:
    om = mailing_dict(li)
    return om.get("owner") or li.defendant or None


def _owner_still_supports_match(li: Listing) -> bool:
    """A stale state-prison match is worse than no tag -- same "missing-only,
    never revisited" shape commit 9e3fd2c9 fixed for enrichment_bop_federal.py
    the same day, one lane over: this module's own
    `if (li.raw or {}).get("incarceration"): continue` guard treats ANY
    existing NC DAC / SC DOC match as permanent, so a later owner-name refresh
    (a sale, an estate closing, a parcel_cache correction) never gets
    reconciled against a name-keyed match stamped against whoever used to own
    the parcel. Live-checked 2026-10-03 against the real board: 11 rows carry
    raw['incarceration'] naming someone with zero relation to the CURRENT
    owner, which is now an unrelated entity (a bank, a city, an HOA, an LLC --
    e.g. a Henderson parcel matched "MICHAEL PEAK" but now reads
    "FIRST CITIZENS BANK & TRUST CO"; a Gaston parcel matched "DEANA WILSON"
    but now reads "GASTONIA CITY OF"), plus several more rows where the
    current owner parses to a different real person entirely.

    Returns True ("leave it alone") when raw['incarceration'] is absent, was
    stamped by a DIFFERENT enricher (BOP federal or a county jail roster --
    each owns clearing its own, see enrichment_bop_federal.py /
    enrichment_jail_bookings.py), or still names a person the CURRENT owner
    supports. Returns False only when THIS module's own NC DAC/SC DOC match no
    longer matches the current owner name -- the caller clears the stale tag
    so the row becomes an ordinary candidate again instead of quietly keeping
    someone else's state-custody record forever."""
    match = li.raw.get("incarceration") if isinstance(li.raw, dict) else None
    if not isinstance(match, dict) or match.get("source") not in (DAC_SOURCE, SCDC_SOURCE):
        return True                     # not this module's match -- don't touch it
    queried = str(match.get("matched_name") or "").strip().upper()
    if not queried:
        return True                     # nothing to check against -- don't touch it
    owner = _owner_of(li)
    parts = _name_parts(owner) if owner else None
    if not parts:
        return False                    # current owner isn't even a person anymore
    last, first = parts
    return queried == f"{first} {last}"


def _clear_stale_matches(listings: list[Listing]) -> int:
    """Pre-pass: drop any NC-DAC/SC-DOC raw['incarceration'] match the CURRENT
    owner no longer supports (see _owner_still_supports_match), so the normal
    candidate-selection loop below picks the row up again as if never checked.
    Only ever removes a match THIS module itself set (checked by `source`) --
    never touches a BOP or county-jail-roster entry sharing the same key."""
    cleared = 0
    for li in listings:
        if li.state not in ("NC", "SC") or not isinstance(li.raw, dict):
            continue
        if _owner_still_supports_match(li):
            continue
        li.raw.pop("incarceration", None)
        cleared += 1
    return cleared


# ---- negative stamps, selection and rotation ---------------------------------

def _recheck_days() -> float:
    """How long an answered miss stays fresh. A person can be sentenced at any
    time, so a "no" is not permanent; 30 days matches the divorce enricher."""
    try:
        return float(os.environ.get("INCARCERATION_RECHECK_DAYS", "30"))
    except ValueError:
        return 30.0


def _county_key(li: Listing) -> tuple[str, str]:
    return (li.state or "", (li.county or "").replace(" County", "").strip().title())


def _stamp_of(li: Listing, name: str) -> Optional[datetime]:
    """When this lead's CURRENT owner name was last checked, or None if never.
    A stamp for a different name (the owner was re-resolved since) does not count."""
    st = li.raw.get("incarceration_check") if isinstance(li.raw, dict) else None
    if not isinstance(st, dict) or st.get("name") != name:
        return None
    try:
        dt = datetime.fromisoformat(str(st.get("checked_at")))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _round_robin(groups: dict, keys: list, budget: int, cap: int) -> list:
    """Take one lead per county per pass, so one big county cannot eat the budget."""
    out: list = []
    depth = 0
    while len(out) < budget:
        moved = False
        for k in keys:
            g = groups[k]
            if depth < len(g) and (cap <= 0 or depth < cap):
                out.append(g[depth])
                moved = True
                if len(out) >= budget:
                    break
        if not moved:
            break
        depth += 1
    return out


def _select_targets(cands: list, max_queries: int, per_county_cap: int,
                    now: datetime) -> list:
    """Pick this run's leads from (lead, name, last_checked) candidates.

    Within a county: never-checked leads first (board order), then the oldest
    stamps. Across counties: round-robin, footprint counties (config.in_scope)
    before the rest, each county capped at per_county_cap. The county order
    rotates daily so the partial last pass does not always favour the same ones.
    """
    groups: dict[tuple[str, str], list] = {}
    for li, _name, checked in cands:
        groups.setdefault(_county_key(li), []).append((checked, li))
    for k, g in groups.items():
        # stable sort: unstamped (None) keep board order and sit ahead of stamped
        g.sort(key=lambda t: (t[0] is not None, t[0].timestamp() if t[0] else 0.0))
        groups[k] = [li for _c, li in g]
    keys = sorted(groups)
    spin = now.toordinal() % len(keys) if keys else 0
    keys = keys[spin:] + keys[:spin]
    core = [k for k in keys if in_scope(k[1], k[0])]
    rest = [k for k in keys if k not in core]
    picked = _round_robin(groups, core, max_queries, per_county_cap)
    if len(picked) < max_queries:
        picked += _round_robin(groups, rest, max_queries - len(picked), per_county_cap)
    return picked


def _stamp_miss(li: Listing, name: str, source: str, now: datetime) -> None:
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["incarceration_check"] = {
        "checked_at": now.replace(microsecond=0).isoformat(), "name": name,
        "source": source, "result": "no_match"}


async def enrich_incarceration(listings: list[Listing], max_queries: Optional[int] = None,
                               per_county_cap: Optional[int] = None,
                               recheck_days: Optional[float] = None) -> dict:
    """Flag listings whose owner matches a state corrections roster (NC + SC).

    max_queries     total lookups this run (env INCARCERATION_MAX_QUERIES, default 150)
    per_county_cap  most leads any one county may take (env INCARCERATION_PER_COUNTY_CAP,
                    default 50; 0 = no cap)
    recheck_days    how long an answered miss stays fresh (env INCARCERATION_RECHECK_DAYS,
                    default 30)

    Starts with a read-only-looking but mutating pre-pass (_clear_stale_matches)
    that drops any NC-DAC/SC-DOC match the CURRENT owner no longer supports, so
    a sale/estate-closing/parcel_cache correction since the match was stamped
    doesn't leave someone else's state-custody record sitting on the lead
    forever -- see _owner_still_supports_match for the real example that
    found this.
    """
    if max_queries is None:
        max_queries = int(os.environ.get("INCARCERATION_MAX_QUERIES", "150"))
    if per_county_cap is None:
        per_county_cap = int(os.environ.get("INCARCERATION_PER_COUNTY_CAP", "50"))
    window = _recheck_days() if recheck_days is None else float(recheck_days)
    now = datetime.now(timezone.utc)

    stale_cleared = _clear_stale_matches(listings)

    cands, fresh = [], 0
    for li in listings:
        if li.state not in ("NC", "SC"):
            continue
        raw = li.raw or {}
        # An ended county-jail flag no longer blocks the lookup: that is exactly the person
        # who may have moved on to state prison.
        if incarceration_active(raw.get("incarceration"), raw.get("jail_booking")):
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
    targets = _select_targets(cands, max_queries, per_county_cap, now)
    if not targets:
        log.info("incarceration.no_targets", skipped_fresh=fresh, stale_cleared=stale_cleared)
        return {"queried": 0, "matched": 0, "stale_cleared": stale_cleared}

    sem = asyncio.Semaphore(int(os.environ.get("INCARCERATION_CONCURRENCY", "1")))
    delay = float(os.environ.get("INCARCERATION_DELAY", "1.0"))
    counts = {"queried": 0, "matched": 0, "matched_nc": 0, "matched_sc": 0,
              "stamped_miss": 0, "failed": 0, "skipped_fresh": fresh,
              "candidates": len(cands), "selected": len(targets), "blocked_hosts": 0,
              "stale_cleared": stale_cleared}
    tripped: set[str] = set()      # states whose host we stopped asking this run
    strikes = {"NC": 0, "SC": 0}   # consecutive unusable answers per state
    cache: dict[tuple, asyncio.Future] = {}
    max_strikes = int(os.environ.get("INCARCERATION_MAX_FAILURES", "8"))

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True) as http:
        async def lookup(state: str, last: str, first: str) -> Optional[_Lookup]:
            async with sem:
                if state in tripped:
                    return None
                counts["queried"] += 1
                # Route to the right state's corrections roster.
                res = await (_scdc_lookup if state == "SC" else _dac_lookup)(http, last, first)
                if res.blocked:
                    tripped.add(state)
                    counts["blocked_hosts"] += 1
                    log.warning("incarceration.host_blocked", state=state)
                elif res.answered:
                    strikes[state] = 0
                else:
                    strikes[state] += 1
                    if strikes[state] >= max_strikes:
                        tripped.add(state)
                        log.warning("incarceration.host_failing", state=state)
                if delay:
                    await asyncio.sleep(delay)
                return res

        async def one(li: Listing):
            last, first = _name_parts(_owner_of(li))
            key = (li.state, last, first)
            # The same owner often holds several parcels: ask the state once.
            if key not in cache:
                cache[key] = asyncio.ensure_future(lookup(li.state, last, first))
            res = await cache[key]
            if res is None or res.blocked:
                return                         # not asked: leave the lead unstamped
            if res.match:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["incarceration"] = res.match
                li.raw.pop("incarceration_check", None)
                counts["matched"] += 1
                counts["matched_sc" if li.state == "SC" else "matched_nc"] += 1
            elif res.answered:
                # A miss the state actually answered: remember it so the next run
                # moves on to leads it has not checked.
                _stamp_miss(li, f"{first} {last}",
                            SCDC_SOURCE if li.state == "SC" else DAC_SOURCE, now)
                counts["stamped_miss"] += 1
            else:
                counts["failed"] += 1          # no answer: never stamped
        await asyncio.gather(*(one(li) for li in targets))
    log.info("incarceration.done", **counts)
    return counts
