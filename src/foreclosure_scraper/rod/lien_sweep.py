"""County-wide lien sweep of a Harris AcclaimWeb register (Horry and Pickens SC), matched to the board
offline. Audit 2026-10-09, top-80 build list ranks 10 (Horry liens) and 67 (Pickens): the per-owner
name search (rod/acclaim_names.py) costs about 9 s a lookup and is capped at 30 lookups a county a
run, so 11,841 Horry rows could never all be checked. The register's own document-type search can
instead be asked for every adverse-lien instrument recorded in a date window (the same two POSTs a
person's browser makes, as rod/acclaim.py does for Pickens' recent-NOD sweep), 500 rows a page:
a year of Horry holds about 6,100 such instruments (13 pages). One sweep serves every board row.

THE FLOW (live-checked 2026-10-09 on Horry, 10 s of requests per year of data)
  1. GET  {base}/search/SearchTypeDocType     disclaimer form (accuracy text) -> POST disclaimer=true
  2. POST {base}/search/SearchTypeDocType?Length=6   DocTypes = comma list of the form's own
          DocTypeInfoCheckBox values for the ADVERSE types, RecordDateFrom/To (M/D/YYYY)
  3. POST {base}/Search/GridResults   page=N&size=500 -> JSON {Data|data, Total|total}
Adverse types are picked by the register's own titles (lien, lis pendens, foreclosure notice, tax
lien); satisfactions, releases, withdrawals, amendments, affidavits and lien-book plumbing are not.

HONESTY OF A NEGATIVE. A board owner with no match gets the stamp 'screened, none found' ONLY for the
window the sweep actually covered (window_from..window_to on the stamp); a lien recorded before the
window is not claimed absent. The cache (data/lien_sweep/<county>.json, git-ignored) keeps the
swept months so the next run reads only the new ones; the sweep goes newest month first, so a
budget that ends it early still covers the recent years.

Nothing here solves or works around a wall: sc_polite.PoliteSession paces (1.6 s a host, one request
at a time), checks every reply for a CAPTCHA / challenge / login / block and raises RodWalled.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin

from . import acclaim_names as AN
from .models import RodDoc
from .sc_chain import NameQuery, entity_tokens, index_parts, looks_entity, name_fit, owner_query
from .sc_polite import PoliteSession, RodWalled

PLATFORM = "harris_acclaimweb_lien_sweep"
ENV_FLAG = "FORECLOSURE_SC_LIEN_SWEEP"
PAGE_SIZE = 500
MAX_PAGES_PER_MONTH = 12                  # 6,000 instruments in one month would be a different system
CACHE_DIR = Path(os.environ.get("FORECLOSURE_LIEN_SWEEP_DIR", "data/lien_sweep"))

#: counties swept (state, lower-case county) -> the AcclaimWeb base config
SWEEP_COUNTIES = {("SC", "horry"): "horry", ("SC", "pickens"): "pickens"}

_ADVERSE = re.compile(r"LIEN|LIS PENDENS|FORECLOS|JUDG|EXECUTION|\bTAX\b", re.I)
_NOT_ADVERSE = re.compile(r"SATISF|RELEASE|WITHDRAW|AMEND|RESCISSION|TERMINAT|SURETY|AFFIDAVIT|LIEN BOOK|"
                          r"SUBORDINATION|ASSIGNMENT|CONTINUATION|UCC|REVOCATION|CANCEL", re.I)


def is_sweep_county(state: str, county: str) -> bool:
    return ((state or "").upper(), (county or "").replace(" County", "").strip().lower()) in SWEEP_COUNTIES


def _county_key(county: str) -> str:
    return (county or "").replace(" County", "").strip().lower()


# -- pure parsers -------------------------------------------------------------------------------------
def parse_doc_type_options(html: str) -> list[tuple[str, str]]:
    """[(title, value)] from the document-type check boxes of SearchTypeDocType."""
    out: list[tuple[str, str]] = []
    for tag in re.findall(r"<input\b[^>]*name=\"DocTypeInfoCheckBox\"[^>]*>", html or ""):
        t = re.search(r'title="([^"]*)"', tag)
        v = re.search(r'value="([^"]*)"', tag)
        if t and v:
            out.append((t.group(1).replace("&amp;", "&").strip(), v.group(1).strip()))
    return out


def adverse_options(options: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """The adverse-lien instrument types among a form's options (satisfactions etc. are not)."""
    return [(t, v) for t, v in options if _ADVERSE.search(t) and not _NOT_ADVERSE.search(t)]


def _month_end(d: date) -> date:
    ny, nm = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date.fromordinal(date(ny, nm, 1).toordinal() - 1)


def month_windows(newest: date, oldest: date) -> list[tuple[date, date]]:
    """Calendar months from the one holding `newest` back to the one holding `oldest`, newest first,
    as (first day, last day), the first window clipped to `newest`."""
    out: list[tuple[date, date]] = []
    y, m = newest.year, newest.month
    while (y, m) >= (oldest.year, oldest.month):
        first = date(y, m, 1)
        out.append((first, min(_month_end(first), newest)))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


def doc_summary(d: RodDoc) -> dict:
    """The compact, public-record fields kept per instrument (no images, no notes)."""
    return {"t": (d.doc_type or "")[:60], "d": d.recorded_date.date().isoformat() if d.recorded_date else None,
            "b": d.book, "p": d.page, "i": d.instrument_no, "f": (d.grantor or "")[:80],
            "g": (d.grantee or "")[:80],
            "n": re.sub(r"\W", "", d.parcel_id or "")[:20] or None}


# -- the matching index -------------------------------------------------------------------------------
class LienIndex:
    """Swept instruments indexed by surname (persons) and first entity word (entities)."""

    def __init__(self) -> None:
        self._persons: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        self._entities: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        self.size = 0

    def add(self, s: dict) -> None:
        self.size += 1
        for party in (s.get("f"), s.get("g")):
            if not party:
                continue
            if looks_entity(party):
                toks = entity_tokens(party)
                if toks:
                    self._entities[toks[0]].append((party, s))
                continue
            p = index_parts(party)
            if p:
                self._persons[p[0]].append((party, s))

    def match(self, owner: str, parcel: Optional[str] = None, limit: int = 12) -> Optional[list[dict]]:
        """Instruments whose party fits the owner, each copied with a `fit`: 'parcel' (the register's
        parcel number equals the board row's), 'exact' (surname, first name and middle initial all
        agree, or neither side has a middle initial; an entity's words equal) or 'name' (the surname
        and first name agree but the middle initial is absent on one side or only an initial of the
        first name fits). None when the owner name cannot be turned into a query (unmatchable, which
        is not 'none found')."""
        q: Optional[NameQuery] = owner_query(owner)
        if q is None:
            return None
        pn = re.sub(r"\W", "", parcel or "")
        pool = self._entities.get(q.tokens[0], []) if q.entity else self._persons.get(q.last, [])
        seen: set[tuple] = set()
        hits: list[dict] = []
        for party, s in pool:
            fit = name_fit(q, party)
            if not fit:
                continue
            k = (s.get("i"), s.get("b"), s.get("p"), s.get("t"), s.get("d"))
            if k in seen:
                continue
            seen.add(k)
            if pn and s.get("n") and s["n"] == pn:
                level = "parcel"
            elif fit == "full" and (q.entity or _middle_agrees(q, party)):
                level = "exact"
            else:
                level = "name"
            hits.append({**s, "fit": level})
        rank = {"parcel": 0, "exact": 1, "name": 2}
        hits.sort(key=lambda h: (rank[h["fit"]], _neg(h.get("d"))))
        return hits[:limit]


def _neg(d: Optional[str]) -> str:
    """Sort key putting the newest ISO date first inside one fit rank."""
    return "".join(chr(255 - ord(c)) for c in (d or ""))


def _middle_agrees(q: NameQuery, party: str) -> bool:
    p = index_parts(party)
    return bool(p) and p[1] == q.first and p[2] == q.middle


# -- cache ----------------------------------------------------------------------------------------------
def cache_path(county: str) -> Path:
    return CACHE_DIR / f"{_county_key(county)}.json"


def load_cache(county: str) -> dict:
    try:
        d = json.loads(cache_path(county).read_text())
        if isinstance(d, dict) and isinstance(d.get("months"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"months": {}, "docs": {}}


def save_cache(county: str, cache: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = cache_path(county).with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, separators=(",", ":")))
        tmp.replace(cache_path(county))
    except OSError:
        pass


# -- the sweep ------------------------------------------------------------------------------------------
@dataclass
class SweepResult:
    county: str
    months_read: int = 0
    months_cached: int = 0
    instruments_new: int = 0
    window_from: Optional[str] = None
    window_to: Optional[str] = None
    walled: Optional[str] = None
    budget_exhausted: bool = False
    error: Optional[str] = None
    types: int = 0


def _open(http: PoliteSession, base: str) -> list[tuple[str, str]]:
    r = http.get(f"{base}/search/SearchTypeDocType")
    if 'name="disclaimer"' in r.text or "disclaimer" in (r.url or "").lower():
        m = re.search(r'<form action="([^"]+)"', r.text)
        if not m:
            raise RuntimeError("disclaimer form not found")
        r = http.post(urljoin(r.url, m.group(1).replace("&amp;", "&")), data={"disclaimer": "true"})
    opts = parse_doc_type_options(r.text)
    if r.status_code != 200 or not opts:
        raise RuntimeError(f"document-type search not reached ({r.status_code})")
    return opts


def _read_month(http: PoliteSession, base: str, floor: str, ids: str, frm: date, to: date,
                county_title: str, doc_words: Optional[dict]) -> tuple[list[RodDoc], bool]:
    """(docs, complete). complete is False when the register said the window is too big or a page
    cap was reached, so the month is not recorded as swept."""
    xhr = {"X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/search/SearchTypeDocType"}
    s = http.post(f"{base}/search/SearchTypeDocType?Length=6", headers=xhr, data={
        "DocTypes": ids, "DocTypesDisplay-input": "x", "DocTypesDisplay": "", "DateRangeList": " ",
        "RecordDateFrom": AN._mdy(frm), "DefaultFromDate": floor, "RecordDateTo": AN._mdy(to),
        "btnSearch": "Search"})
    if "ShowError" in s.text:
        m = re.search(r"ShowError\(\s*'([^']*)'", s.text)
        if m and re.search(r"no records|not found", m.group(1), re.I):
            return [], True
        return [], False
    docs: list[RodDoc] = []
    complete = True
    for page in range(1, MAX_PAGES_PER_MONTH + 1):
        g = http.post(f"{base}/Search/GridResults", headers={"X-Requested-With": "XMLHttpRequest"},
                      data={"page": str(page), "size": str(PAGE_SIZE), "pageSize": str(PAGE_SIZE)})
        try:
            payload = json.loads(g.text)
        except ValueError:
            return docs, False
        rows = payload.get("Data") if "Data" in payload else payload.get("data")
        total = payload.get("Total") if "Total" in payload else payload.get("total")
        rows = rows or []
        docs += AN.parse_rows(rows, county_title, doc_words)
        if not rows or len(docs) >= (total if isinstance(total, int) else 0):
            break
        if page == MAX_PAGES_PER_MONTH:
            complete = False
    return docs, complete


def sweep_county(county: str, *, since: date, today: Optional[date] = None, budget_s: float = 600.0,
                 session: Optional[PoliteSession] = None, clock: Callable[[], float] = time.monotonic,
                 ) -> tuple[LienIndex, SweepResult]:
    """Read (or reuse from the cache) every month from today back to `since`, newest first, until the
    budget ends; return the index over everything held and what the sweep covered."""
    key = SWEEP_COUNTIES.get(("SC", _county_key(county)))
    res = SweepResult(county=county.replace(" County", "").strip().title())
    index = LienIndex()
    cache = load_cache(county)
    if key is None:
        res.error = "not a lien-sweep county"
        return index, res
    cfg = AN.ACCLAIM_NAME_COUNTIES[key]
    today = today or date.today()
    windows = month_windows(today, since)
    t0 = clock()
    http = session or PoliteSession(timeout=90.0)
    opened: Optional[list[tuple[str, str]]] = None
    ids = ""
    covered: list[str] = []                       # month keys, newest first, contiguous from today
    contiguous = True
    new = 0
    try:
        for frm, to in windows:
            mk = frm.strftime("%Y-%m")
            partial_month = to < _month_end(frm)          # the running month is re-read every run
            if mk in cache["months"] and not partial_month:
                res.months_cached += 1
                if contiguous:
                    covered.append(mk)
                continue
            if clock() - t0 > budget_s:
                res.budget_exhausted = True
                contiguous = False
                continue
            if opened is None:
                opened = _open(http, cfg.base)
                adv = adverse_options(opened)
                res.types = len(adv)
                if not adv:
                    raise RuntimeError("no adverse document types on the form")
                ids = ",".join(v for _, v in adv)
            docs, complete = _read_month(http, cfg.base, cfg.floor, ids, frm, to, res.county, None)
            if not complete:
                contiguous = False
                continue
            for d in docs:
                s = doc_summary(d)
                cache["docs"][f"{s['i'] or ''}|{s['b']}|{s['p']}|{s['t']}|{s['d']}|{s['f']}"] = s
            new += len(docs)
            if not partial_month:
                cache["months"][mk] = len(docs)
            res.months_read += 1
            if contiguous:
                covered.append(mk)
    except RodWalled as exc:
        res.walled = exc.reason
    except Exception as exc:  # noqa: BLE001 - a failed sweep reports and stamps nothing
        res.error = f"{type(exc).__name__}: {str(exc)[:120]}"
    res.instruments_new = new
    save_cache(county, cache)
    for s in cache["docs"].values():
        index.add(s)
    if covered and not res.walled and not res.error:
        res.window_from = min(covered) + "-01"
        res.window_to = min(_month_end(date.fromisoformat(max(covered) + "-01")), today).isoformat()
    return index, res


# -- the stamp ------------------------------------------------------------------------------------------
def stamp_for(hits: Optional[list[dict]], res: SweepResult, checked_at: Optional[str] = None) -> Optional[dict]:
    """raw['rod_lien_sweep'] for one board row, or None (unmatchable owner name / nothing covered).
    status: 'found' (a parcel or exact-name match), 'possible' (name-only matches), 'none_found'
    ('screened, none found' for window_from..window_to only)."""
    if hits is None or not res.window_from or res.walled or res.error:
        return None
    strong = [h for h in hits if h.get("fit") in ("parcel", "exact")]
    return {
        "status": "found" if strong else ("possible" if hits else "none_found"),
        "checked_at": checked_at or datetime.now(timezone.utc).date().isoformat(),
        "platform": PLATFORM, "county": res.county,
        "window_from": res.window_from, "window_to": res.window_to,
        "adverse_types": res.types, "adverse_count": len(strong), "possible_count": len(hits) - len(strong),
        "instruments": hits[:10],
    }
