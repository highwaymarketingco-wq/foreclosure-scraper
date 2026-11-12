"""SC county probate courts on the Spartan "Public Probate Inquiry" app: Greenwood, Newberry, Calhoun.

WHY (top-80 build list 2026-10-09, item 51 'probate', 5 SC cells: Calhoun, Greenwood, Lexington,
Newberry, Richland). Three of the five courts publish their estate index on the same vendor app
(Spartan Technology hosted public inquiry), reached from the county's own probate page. It needs no
login, no CAPTCHA and no terms click-through, and it is not on southcarolinaprobate.net (the aggregator
sc_probate_net reads), so none of the three was ever searched. Lexington (a statutory solicitation
notice and a CAPTCHA, per the matrix) and Richland (its own estate inquiry) are separate.

THE SOURCE (read live 2026-10-09). Each tenant's party-search page posts nothing: a DataTables grid
calls a JSON handler with the form fields as query parameters (Spartan.js serializes every
`.formControl` input under the LAST segment of its name):

    GET {app}/Handlers/Data.asmx/CasePartySearch
        sEcho=1 iColumns=3 iDisplayStart=<n> iDisplayLength=100 mDataProp_0..2=WARANTNO,PTYNAME,CSPTYTYP
        iSortingCols=2 iSortCol_0=0 sSortDir_0=asc iSortCol_1=1 sSortDir_1=asc
        AgencyId=<the court> LastName= FirstName= PartyType=DEC DispositionStatus=
    Content-Type: application/json   (the ASMX answers JSON only to that header)
    -> {"d": "<json>"}  with recordsTotal and aaData rows
       {APPCODE, CMSCASE, CASPTYSQ, WARANTNO (case no, e.g. 1985ES2400360), CSPTYTYP, PTYNAME
        ("LAST, FIRST M"), PROSNAME}
An empty LastName with PartyType=DEC lists every decedent party of the court (Greenwood 20,480, Newberry
13,366, Calhoun 3,674 on the day). A two-column sort keeps the pages stable (Calhoun: 3,674 distinct of
3,674 over 37 pages).

WHAT IT DOES. Reads the court's whole decedent index once (100 per request, one request at a time per
host, PACE_S apart; a half-built index is saved and resumed by the next run) and matches every board
owner string of that county against it offline with the obituary matcher's full-name rules
(enrichment_obituary_match.owner_readings / name_level). It writes:

  raw['probate_index_match']  [{case_number, party_type, level, county, source, case_year}] (up to 3) for
                              an owner whose name fits a decedent of the county's court at level full or
                              middle_initial; a thin fit (given name + surname, no middle name on either
                              side) is kept only for a case dated RECENT_YEAR or later or a name that
                              appears once in the court's index (Calhoun's case numbers carry no year). A
                              name match is not an identity: the case is evidence for the lawyer, not a
                              fact about this owner.
  raw['probate']              ONLY when the fit is full / middle_initial (or a unique thin fit) AND the row
                              already shows a death on the roll (enrichment_obituary_match.death_signal_on_roll:
                              an estate or heirs owner string, a death life-event). Then {decedent,
                              case_number, es_case_number, county, source, match_confidence}. Nothing else
                              writes it, so a namesake never raises a lead's probate score on a name alone.

SCREEN. A county whose whole index was read (rows >= 99% of recordsTotal) within CACHE_TTL_DAYS has had every
one of its board rows' owners matched, hit or not: the run stats carry screened = {probate: ["SC|County"]},
which screen_ledger turns into the cube's 'screened, none found'. A half-built index claims nothing.

Kill switch FORECLOSURE_PROBATE_SPARTAN=0. Budget FORECLOSURE_PROBATE_SPARTAN_BUDGET_S (default 1500 s).
Counts, case numbers and county names only in logs and stats.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog

from .http_client import client

log = structlog.get_logger()

ENV = "FORECLOSURE_PROBATE_SPARTAN"
ENV_BUDGET = "FORECLOSURE_PROBATE_SPARTAN_BUDGET_S"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "probate_index"
CACHE_TTL_DAYS = int(os.environ.get("PROBATE_SPARTAN_TTL_DAYS", "30"))
PACE_S = float(os.environ.get("PROBATE_SPARTAN_PACE_S", "2.0"))
PAGE = 100
MAX_PAGES = 400
#: rows that make an index complete (a duplicate row from tied sort keys can push the count above total)
COMPLETE_RATIO = 0.99
RECENT_YEAR = 2005                    # a 'given_surname' fit counts only for a case at or after this year
STATE = "SC"
SOURCE = "spartan_public_probate"

#: county -> app root (no trailing slash). The AgencyId and the handler path are read from the
#: tenant's own party-search page, never assumed.
PORTALS: dict[str, str] = {
    "Greenwood": "https://scportal.hostedbyspartan.com/GreenwoodPublicPortal",
    "Newberry": "https://scportal.hostedbyspartan.com/NewberryPublicPortal",
    "Calhoun": "https://govcloud2.hostedbyspartan.com/CalhounPRO/PublicProbate",
}

_HANDLER = re.compile(r"SetDataTable\('#partyListGrid',\s*'([^']+)'")
_AGENCY = re.compile(r'AgencyId"[^>]*>\s*<option[^>]*value="(\d+)"', re.I)


class SpartanError(RuntimeError):
    pass


def _host(base: str) -> str:
    m = re.match(r"https?://[^/]+", base)
    return m.group(0) if m else base


# ---------------------------------------------------------------------------------------------
# the portal (network parts)
# ---------------------------------------------------------------------------------------------

def parse_search_page(html: str) -> tuple[str, str]:
    """(handler path, AgencyId) from a tenant's party-search page."""
    h, a = _HANDLER.search(html or ""), _AGENCY.search(html or "")
    if not h or not a:
        raise SpartanError("party-search page has no grid handler or agency id")
    return h.group(1), a.group(1)


def page_params(agency: str, start: int, length: int = PAGE) -> dict:
    return {"sEcho": "1", "iColumns": "3", "iDisplayStart": str(start), "iDisplayLength": str(length),
            "mDataProp_0": "WARANTNO", "mDataProp_1": "PTYNAME", "mDataProp_2": "CSPTYTYP",
            "iSortingCols": "2", "iSortCol_0": "0", "sSortDir_0": "asc", "iSortCol_1": "1", "sSortDir_1": "asc",
            "AgencyId": agency, "LastName": "", "FirstName": "", "PartyType": "DEC", "DispositionStatus": ""}


def parse_answer(text: str) -> tuple[int, list[list[str]]]:
    """(recordsTotal, [[case no, party name], ...]) from the handler's {"d": "<json>"} answer."""
    try:
        j = json.loads(json.loads(text)["d"])
    except (ValueError, KeyError, TypeError) as exc:
        raise SpartanError("not a Spartan grid answer") from exc
    if j.get("Error"):
        raise SpartanError(f"portal error {str(j['Error'])[:80]}")
    rows = [[str(a.get("WARANTNO") or "").strip(), str(a.get("PTYNAME") or "").strip()]
            for a in j.get("aaData") or [] if a.get("WARANTNO") and a.get("PTYNAME")]
    return int(j.get("recordsTotal") or 0), rows


async def _get(http: Any, url: str, **kw: Any) -> Any:
    last = "no attempt"
    for attempt in range(3):
        if attempt:
            await asyncio.sleep(PACE_S * (attempt + 1))
        try:
            r = await http.get(url, timeout=60.0, **kw)
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {str(exc)[:80]}"
            continue
        if r.status_code == 200:
            return r
        last = f"HTTP {r.status_code}"
    raise SpartanError(last)


async def read_index(http: Any, base: str, cache: Optional[dict], deadline: float) -> dict:
    """The county's decedent index, resumed from `cache` when it is a half-built one of this TTL.
    Returns {fetched_on, complete, total, next_start, rows, requests}."""
    r = await _get(http, base + "/pages/PartySearchPage.aspx")
    handler, agency = parse_search_page(r.text)
    url = _host(base) + handler
    keep = cache if cache and not cache.get("complete") else None
    rows: list[list[str]] = list(keep["rows"]) if keep else []
    start = int(keep["next_start"]) if keep else 0
    total = int(keep["total"]) if keep else 0
    requests = 1
    for _ in range(MAX_PAGES):
        if time.monotonic() > deadline:
            break
        await asyncio.sleep(PACE_S)
        resp = await _get(http, url, params=page_params(agency, start), headers={"Content-Type": "application/json"})
        requests += 1
        total, got = parse_answer(resp.text)
        rows.extend(got)
        start += PAGE
        if start >= total or not got:
            break
    seen: set = set()
    uniq = []
    for c, n in rows:
        if (c, n) not in seen:
            seen.add((c, n))
            uniq.append([c, n])
    complete = bool(total) and start >= total and len(uniq) >= COMPLETE_RATIO * total
    return {"fetched_on": date.today().isoformat(), "complete": complete, "total": total,
            "next_start": start, "rows": uniq, "requests": requests}


# ---------------------------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------------------------

def _path(county: str) -> Path:
    return CACHE_DIR / f"{county.lower()}.json"


def load_cache(county: str, today: Optional[date] = None) -> Optional[dict]:
    today = today or date.today()
    try:
        d = json.loads(_path(county).read_text())
        age = (today - date.fromisoformat(str(d.get("fetched_on")))).days
    except Exception:  # noqa: BLE001
        return None
    return d if age <= CACHE_TTL_DAYS else None


def save_cache(county: str, doc: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _path(county).with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, separators=(",", ":")))
        tmp.replace(_path(county))
    except Exception as exc:  # noqa: BLE001
        log.warning("probate_spartan.cache_write_failed", county=county, error=str(exc)[:100])


# ---------------------------------------------------------------------------------------------
# matching (pure)
# ---------------------------------------------------------------------------------------------

def case_year(case_no: str) -> Optional[int]:
    m = re.match(r"^(19|20)\d{2}", case_no or "")
    return int(m.group(0)) if m else None


class DecedentIndex:
    """surname -> [(case no, PersonName, display)] over a county's decedent parties."""

    def __init__(self, rows: Iterable[list[str]]) -> None:
        from .enrichment_obituary_match import owner_readings
        self.by_last: dict[str, list[tuple[str, Any]]] = {}
        #: how many decedent parties share a (surname, given names) reading: a thin fit (no middle name
        #: on either side) is only as good as that name is rare in the court's index
        self.name_counts: dict[tuple, int] = {}
        self.n = 0
        for case_no, name in rows:
            readings = owner_readings(name)
            if not readings:
                continue
            person = readings[0][0]
            self.by_last.setdefault(person.last, []).append((case_no, person))
            k = (person.last, tuple(person.given))
            self.name_counts[k] = self.name_counts.get(k, 0) + 1
            self.n += 1

    def fits(self, owner_strings: Iterable[str]) -> list[dict]:
        from .enrichment_obituary_match import name_level, owner_readings
        best: dict[str, dict] = {}
        for s in owner_strings:
            for reading, _how in owner_readings(s):
                for case_no, dec in self.by_last.get(reading.last, []):
                    level, _why = name_level(reading, dec)
                    if not level:
                        continue
                    yr = case_year(case_no)
                    unique = self.name_counts.get((dec.last, tuple(dec.given)), 0) == 1
                    # a thin fit (no middle name either side) needs a recent dated case or a name that
                    # appears once in the court's index (Calhoun prints no year in its case numbers)
                    if level == "given_surname" and not ((yr and yr >= RECENT_YEAR) or unique):
                        continue
                    cur = best.get(case_no)
                    rank = {"full": 3, "middle_initial": 2, "given_surname": 1}[level]
                    if cur is None or rank > cur["rank"]:
                        best[case_no] = {"case_number": case_no, "party_type": "DEC", "level": level,
                                         "rank": rank, "case_year": yr, "unique_name": unique,
                                         "decedent": " ".join(dec.given + [dec.last])}
        out = sorted(best.values(), key=lambda f: (-f["rank"], -(f["case_year"] or 0)))
        return out


def stamp(li: Any, fits: list[dict], county: str, death_on_roll: bool) -> tuple[bool, bool]:
    """(match stamped, probate promoted). Never overwrites a probate block that already names a case."""
    if not fits:
        return False, False
    raw = li.raw if isinstance(li.raw, dict) else {}
    raw["probate_index_match"] = [
        {"case_number": f["case_number"], "party_type": f["party_type"], "level": f["level"],
         "case_year": f["case_year"], "county": county, "source": SOURCE} for f in fits[:3]]
    promoted = False
    top = fits[0]
    firm = top["level"] in ("full", "middle_initial") or (top["level"] == "given_surname" and top.get("unique_name"))
    if firm and death_on_roll:
        existing = raw.get("probate")
        if not (isinstance(existing, dict) and (existing.get("case_number") or existing.get("es_case_number"))):
            raw["probate"] = {**(existing if isinstance(existing, dict) else {}),
                              "decedent": top["decedent"], "case_number": top["case_number"],
                              "es_case_number": top["case_number"], "county": county, "source": SOURCE,
                              "match_confidence": top["level"]}
            promoted = True
    li.raw = raw
    return True, promoted


def _county_of(li: Any) -> str:
    return str(getattr(li, "county", "") or "").replace(" County", "").strip().title()


def match_rows(listings: Iterable[Any], indexes: dict[str, DecedentIndex]) -> dict:
    from .enrichment_obituary_match import _lead_owner_strings, death_signal_on_roll
    stats = {"rows_matched_against": 0, "match_stamped": 0, "probate_promoted": 0}
    for li in listings:
        if str(getattr(li, "state", "") or "").upper() != STATE:
            continue
        county = _county_of(li)
        idx = indexes.get(county)
        if idx is None:
            continue
        owners = _lead_owner_strings(li)
        if not owners:
            continue
        stats["rows_matched_against"] += 1
        fits = idx.fits(owners)
        s, p = stamp(li, fits, county, death_signal_on_roll(li) if fits else False)
        stats["match_stamped"] += int(s)
        stats["probate_promoted"] += int(p)
    return stats


# ---------------------------------------------------------------------------------------------
# the enrichment
# ---------------------------------------------------------------------------------------------

async def enrich_probate_spartan(listings: list[Any]) -> dict:
    """Build / refresh the three decedent indexes (budgeted) and match the board's rows. Never raises."""
    if os.environ.get(ENV) == "0":
        return {"skipped": f"{ENV}=0"}
    budget = float(os.environ.get(ENV_BUDGET, "1500"))
    deadline = time.monotonic() + budget
    t0 = time.monotonic()
    want = {c for c in PORTALS if any(_county_of(li) == c and str(getattr(li, "state", "")).upper() == STATE
                                      for li in listings)}
    info: dict[str, dict] = {}
    indexes: dict[str, DecedentIndex] = {}
    hosts: dict[str, asyncio.Lock] = {}

    async def one(county: str, http: Any) -> None:
        base = PORTALS[county]
        lock = hosts.setdefault(_host(base), asyncio.Lock())
        cached = load_cache(county)
        if cached and cached.get("complete"):
            doc, fresh_requests = cached, 0
        else:
            async with lock:                         # one request at a time per host
                try:
                    doc = await read_index(http, base, cached, deadline)
                except SpartanError as exc:
                    info[county] = {"error": str(exc)[:100]}
                    log.warning("probate_spartan.failed", county=county, error=str(exc)[:100])
                    return
                except Exception as exc:  # noqa: BLE001
                    info[county] = {"error": f"{type(exc).__name__}: {str(exc)[:80]}"}
                    return
            fresh_requests = doc["requests"]
            save_cache(county, doc)
        info[county] = {"complete": bool(doc.get("complete")), "total": doc.get("total"),
                        "rows": len(doc.get("rows") or []), "requests": fresh_requests,
                        "fetched_on": doc.get("fetched_on")}
        if doc.get("complete"):
            indexes[county] = DecedentIndex(doc["rows"])

    if want:
        async with client(timeout=60.0) as http:
            await asyncio.gather(*(one(c, http) for c in sorted(want)))
    stats = match_rows(listings, indexes)
    stats.update(counties=info, seconds=round(time.monotonic() - t0, 1),
                 screened={"probate": [f"{STATE}|{c}" for c in sorted(indexes)]} if indexes else {})
    log.info("probate_spartan.done", **{k: v for k, v in stats.items() if not isinstance(v, (dict, list))})
    return stats
