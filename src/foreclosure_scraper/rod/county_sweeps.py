"""County-wide register sweeps by document type and date window, matched to the board offline, for the
registers whose per-owner name search cannot reach every board row inside a run's lookup cap.

Audit 2026-10-09, top-80 build list (register platforms CCHS classic, CCHS LRSearch, GovOS CountyFusion,
GovOS/Kofile PublicSearch). The per-owner readers cost 5 to 15 s a lookup and are capped at 30 lookups
a county a run, so a county with 3,000 to 3,900 board rows (Orange, Sumter, Oconee, Beaufort) can never
be fully checked that way. These registers can instead be asked, by the same form a person uses, for
every ADVERSE instrument (lien, judgment, lis pendens, foreclosure, tax lien) recorded in a date
window; ten years of one county is 10 to 60 requests, cached in data/county_sweeps/ (git-ignored) so the
next run reads only what is new. One sweep then serves every board row of the county.

HONESTY OF A NEGATIVE. A board owner with no match gets 'screened, none found' ONLY for the window the
sweep actually covered (window_from..window_to on the stamp), by owner name, for adverse instrument
types only: it says "no lien, judgment or lis pendens indexed under this name in that window", not "no
mortgage". A window that overflowed the register's row cap is bisected; a day that still overflows,
a wall, an error or an exhausted budget shortens the claimed window or stamps nothing.

Same stamp shape as rod/lien_sweep.py (raw['rod_lien_sweep']) so one reader of the key serves both.

Nothing here solves or works around a wall: every request goes through nc_polite.PoliteClient or
sc_polite.PoliteSession (>= 1.6 s a host, one request at a time, wall check on every reply).
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

import structlog

from .nc_chain import IndexRecord, merge_records
from .nc_polite import PoliteClient, RodWalled as NcWalled
from .sc_chain import NameQuery, entity_tokens, index_parts, looks_entity, name_fit, owner_query
from .sc_polite import RodWalled as ScWalled

log = structlog.get_logger()

CACHE_DIR = Path(os.environ.get("FORECLOSURE_COUNTY_SWEEP_DIR", "data/county_sweeps"))
DEFAULT_SINCE = "2016-01-01"
RECENT_REREAD_DAYS = 14          # the newest two weeks are re-read each run (late-indexed documents)
MAX_PARTIES = 8                  # parties kept per side of a swept document


# ------------------------------------------------------------------------------------------------
# summaries and the matching index
# ------------------------------------------------------------------------------------------------

def summarize(rec: IndexRecord) -> dict:
    """The compact, public-record fields kept per swept instrument (no images, no free text beyond
    the index's short description)."""
    return {"t": (rec.doc_type or "")[:60], "d": rec.recorded, "b": rec.book, "p": rec.page,
            "i": rec.instrument_no, "fs": [x[:80] for x in rec.grantors[:MAX_PARTIES]],
            "gs": [x[:80] for x in rec.grantees[:MAX_PARTIES]]}


def doc_key(s: dict) -> str:
    return f"{s.get('i') or ''}|{s.get('b')}|{s.get('p')}|{s.get('t')}|{s.get('d')}"


def clean_owner(owner: str) -> str:
    """A board owner string without the trailing comma / semicolon some county rolls leave on a name
    ('DOE JOHN A,'), which makes the name parser give up."""
    return re.sub(r"[\s,;]+$", "", owner or "").strip()


def _neg(d: Optional[str]) -> str:
    """Sort key putting the newest ISO date first inside one fit rank."""
    return "".join(chr(255 - ord(c)) for c in (d or ""))


class PartyIndex:
    """Swept instruments indexed by surname (persons) and first entity word (entities), one entry per
    party so a deed naming five grantors is found under each."""

    def __init__(self) -> None:
        self._persons: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        self._entities: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        self.size = 0

    def add(self, s: dict) -> None:
        self.size += 1
        for party in list(s.get("fs") or []) + list(s.get("gs") or []):
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

    def match(self, owner: str, limit: int = 12, keep_parties: bool = False) -> Optional[list[dict]]:
        """Instruments whose party fits the owner, each copied with a `fit`: 'exact' (surname, first
        name and middle initial agree, or neither side has a middle initial; an entity's words equal)
        or 'name' (surname and first name agree, a middle initial absent on one side, or only an
        initial of the first name fits). None when the owner name cannot be turned into a query."""
        q: Optional[NameQuery] = owner_query(clean_owner(owner))
        if q is None:
            return None
        pool = self._entities.get(q.tokens[0], []) if q.entity else self._persons.get(q.last, [])
        seen: set[str] = set()
        hits: list[dict] = []
        for party, s in pool:
            fit = name_fit(q, party)
            if not fit:
                continue
            k = doc_key(s)
            if k in seen:
                continue
            seen.add(k)
            p = None if q.entity else index_parts(party)
            level = "exact" if fit == "full" and (q.entity or (p is not None and p[1] == q.first and p[2] == q.middle)) \
                else "name"
            base = dict(s) if keep_parties else {k2: v for k2, v in s.items() if k2 not in ("fs", "gs")}
            hits.append({**base, "f": (s.get("fs") or [""])[0][:80], "g": (s.get("gs") or [""])[0][:80], "fit": level})
        rank = {"exact": 0, "name": 1}
        hits.sort(key=lambda h: (rank[h["fit"]], _neg(h.get("d"))))
        return hits[:limit]


# ------------------------------------------------------------------------------------------------
# a client that does not mistake Cloudflare's passive beacon for a challenge
# ------------------------------------------------------------------------------------------------

#: Every page of a Cloudflare-fronted site carries a "JS detections" loader for
#: /cdn-cgi/challenge-platform/scripts/jsd/main.js. It is a passive beacon, not an interstitial, but
#: the shared wall detector reads the string "challenge-platform" as a challenge page: that is why the
#: 2026-10-07 survey recorded Beaufort and the vendor-hosted CCS tenants as walled although their search
#: pages answer 200 with the real content. An actual challenge has none of the beacon's neighbours
#: (the "Just a moment..." title, cf-chl tokens, _cf_chl_opt, a CAPTCHA widget) and answers 403/503.
_BEACON = re.compile(r"/cdn-cgi/challenge-platform/scripts/jsd/main\.js")
_REAL_CHALLENGE = re.compile(r"Just a moment|cf-chl|_cf_chl_opt|Attention Required|cf-browser-verification|"
                             r"g-recaptcha|h-captcha|cf-turnstile|/challenge-platform/h/", re.I)


class _Reply:
    def __init__(self, r, text: str) -> None:
        self.status_code, self.url, self.text = r.status_code, getattr(r, "url", ""), text
        self.headers = getattr(r, "headers", {})
        self.content = text.encode("utf-8", "ignore")


class BeaconBlindSession:
    """Wraps a requests-style session: a 200 reply whose only brush with Cloudflare is the passive
    jsd beacon has that one script path neutralised before the wall check reads it. Any reply with a
    real challenge marker, any non-200 status and every other wall marker are passed through
    untouched, so a genuine challenge, CAPTCHA, login or block still walls the county."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.headers = getattr(inner, "headers", {})

    def request(self, *args, **kwargs):
        r = self.inner.request(*args, **kwargs)
        text = getattr(r, "text", "") or ""
        if int(getattr(r, "status_code", 0) or 0) == 200 and _BEACON.search(text) and not _REAL_CHALLENGE.search(text):
            return _Reply(r, _BEACON.sub("/cdn-cgi/jsd-beacon", text))
        return r


def beacon_blind_client(platform: str, state: str, county: str) -> PoliteClient:
    c = PoliteClient(platform, state, county)
    c.session = BeaconBlindSession(c.session)
    return c


# ------------------------------------------------------------------------------------------------
# readers: one per register platform. read(a, b) -> (summaries, overflow)
# ------------------------------------------------------------------------------------------------

class Reader:
    """A register platform's document-type window reader. `overflow` means the register showed fewer
    rows than it counted (or hit its row cap), so the window must be split."""
    label = ""                # the stamp's platform name
    state = ""
    county = ""
    types = 0                 # adverse document types asked for

    def open(self) -> None:
        raise NotImplementedError

    def read(self, a: date, b: date) -> tuple[list[dict], bool]:
        raise NotImplementedError

    @property
    def key(self) -> str:
        return f"{self.state}_{self.county}".lower().replace(" ", "_")

    def close(self) -> None:
        pass


def _adverse(name: str) -> bool:
    return bool(_ADV.search(name or "")) and not _NOT_ADV.search(name or "")


_ADV = re.compile(r"LIEN|JUDG|LIS PENDENS|LIS/P|FORECLOS|ATTACH|\bTAX\b|GARNISH|EXECUTION", re.I)
_NOT_ADV = re.compile(r"SATISF|RELEASE|WITHDRAW|CANCEL|AMEND|SUBORDIN|ASSIGN|RESCIS|DISCHARGE|EXPUNG|POSTPONE|"
                      r"CORRECT|NOTICE OF INTENT|NOTICE REQUEST", re.I)


#: Courthouse Computer Systems classic-ASP tenants on the vendor's own us3/us4/us5 servers: county ->
#: (server, application folder). Read 2026-10-09: application.asp (the frame page) answers a script with a
#: Cloudflare 403, but realestatesearch.asp and SearchService.asp (the two pages the search itself uses)
#: answer an ordinary browser request with a plain 200 on 15 of 15 tenants tried, no challenge, no cookie
#: from application.asp needed. This reader asks for those two and nothing else; the first challenge,
#: CAPTCHA or 403 walls the county for the run (nc_polite) and nothing retries it.
HOSTED_CCHS: dict[str, tuple[str, str]] = {
    "Burke": ("us5", "BurkeNCNW"), "Cleveland": ("us5", "ClevelandNCNW"), "Caswell": ("us5", "CaswellNCNW"),
    "Gates": ("us5", "GatesNCNW"), "Dare": ("us5", "DareNCNW"),
    "Lincoln": ("us4", "LincolnNCNW"), "Madison": ("us4", "MadisonNCNW"), "Henderson": ("us4", "HendersonNCNW"),
    "Hertford": ("us4", "HertfordNCNW"), "Hyde": ("us4", "HydeNCNW"), "Montgomery": ("us4", "MontgomeryNCNW"),
    "Chowan": ("us4", "ChowanNCNW"), "Franklin": ("us4", "FranklinNCNW"), "Camden": ("us4", "CamdenNCNW"),
    "Duplin": ("us4", "DuplinNCNW"),
    "Caldwell": ("us3", "CaldwellNCNW"), "Currituck": ("us3", "CurrituckNCNW"),
}


class CchsClassicReader(Reader):
    """Courthouse Computer Systems classic ASP: county-run servers (Orange, Stanly, Surry NC) and the
    vendor-hosted tenants (HOSTED_CCHS)."""
    label = "ccs_classic_asp_sweep"
    state = "NC"

    def __init__(self, county: str, client: Optional[PoliteClient] = None) -> None:
        from . import nc_cchs_classic as C
        self.C = C
        self.county = county
        self.hosted = county in HOSTED_CCHS
        if self.hosted:
            host, slug = HOSTED_CCHS[county]
            self.app = f"https://{host}.courthousecomputersystems.com/{slug}/"
            self.root = None
        else:
            cfg = C.COUNTIES[county]
            self.app, self.root = cfg.app, cfg.root
        self.client = client or beacon_blind_client(C.PLATFORM + ("_hosted_sweep" if self.hosted else "_sweep"), "NC", county)
        self.kinds: list[str] = []

    def open(self) -> None:
        from .cchs import parse_doctypes
        c = self.client
        if not self.hosted:                              # the county-run sequence the adapter documents
            if self.root:
                c.get(self.root)
            c.get(self.app + "application.asp?resize=true")
        page = c.get(self.app + "realestatesearch.asp")
        if "SearchService.asp" not in page.text:
            raise RuntimeError("the land-records search page did not open")
        self.kinds = [k for _book, k, name in parse_doctypes(page.text) if _adverse(name)]
        self.types = len(self.kinds)
        if not self.kinds:
            raise RuntimeError("no adverse instrument kinds in the county's dictionary")

    def read(self, a: date, b: date) -> tuple[list[dict], bool]:
        from urllib.parse import urlencode
        C = self.C
        xhr = {"X-Requested-With": "XMLHttpRequest", "Referer": self.app + "realestatesearch.asp"}
        q = {"cmd": "search", "last": "", "given": "", "indextype": "3", "searchtype": "3", "codetype": "3",
             "fromdate": a.strftime("%m/%d/%Y"), "todate": b.strftime("%m/%d/%Y"),
             "instrumenttypes": ",".join(self.kinds), "description": "", "docnumber": "", "booknumber": "",
             "pagenumber": "", "taxfrom": "", "taxto": "", "resultstype": "1", "maxrecordcount": str(C.MAX_RECORDS),
             "symbolsetout": "0", "sortorder": "1", "sortfield": "docno", "rangetype": "doc"}
        rep = self.client.get(self.app + "SearchService.asp?" + urlencode(q), headers=xhr)
        n, _docs = C.counts(rep.text)
        if rep.status >= 400 or n is None:
            raise RuntimeError(f"search reply HTTP {rep.status} without a record count")
        if n == 0:
            return [], False
        if n >= C.MAX_RECORDS:
            return [], True
        rows = self.client.get(self.app + f"SearchService.asp?cmd=getall&start=0&offset={n}", headers=xhr)
        if rows.status >= 400:
            raise RuntimeError(f"getall HTTP {rows.status}")
        recs = C.parse_getall(rows.text)
        if not recs:
            raise RuntimeError("the record list was empty although the search counted rows")
        return [summarize(r) for r in recs], False


class LrSearchReader(Reader):
    """Courthouse Computer Systems LRSearch (Beaufort NC)."""
    label = "ccs_lrsearch_sweep"
    state = "NC"

    def __init__(self, county: str, client: Optional[PoliteClient] = None) -> None:
        from . import nc_lrsearch as L
        self.L = L
        self.county = county
        self.cfg = L.COUNTIES[county]
        self.client = client or beacon_blind_client(L.PLATFORM + "_sweep", "NC", county)
        self.ctx: dict = {}
        self.codes: list[str] = []

    def open(self) -> None:
        L = self.L
        self.ctx = L.open_search(self.client, self.cfg)
        self.codes = L.adverse_codes(L.doc_types(self.client, self.cfg, self.ctx))
        self.types = len(self.codes)
        if not self.codes:
            raise RuntimeError("no adverse document types on the county's list")

    def read(self, a: date, b: date) -> tuple[list[dict], bool]:
        L = self.L
        rep = self.client.post(self.cfg.base + "LRSearch/ExecuteSearch",
                               L.window_form(self.ctx["defaults"], self.codes, a.isoformat(), b.isoformat()),
                               headers=self.ctx["xhr"])
        n, _docs = L.totals(rep.text)
        if n is None:
            raise RuntimeError("the search reply is not a results grid")
        if n == 0:
            return [], False
        recs = L.parse_grid(rep.text)
        if n > len(recs) or n >= L.MAX_RECORDS:
            return [], True
        return [summarize(r) for r in merge_records(recs)], False


class CountyFusionReader(Reader):
    """GovOS CountyFusion (Sumter SC)."""
    label = "govos_countyfusion_sweep"
    state = "SC"

    def __init__(self, county: str, client: Optional[PoliteClient] = None) -> None:
        from . import sc_countyfusion as F
        self.F = F
        self.county = county
        self.cfg = F.COUNTIES[county]
        self.client = client or PoliteClient(F.PLATFORM + "_sweep", "SC", county)
        self.ctx: dict = {}
        self.ids: list[str] = []

    def open(self) -> None:
        F = self.F
        self.ctx = F.open_session(self.client, self.cfg)
        self.ids = F.adverse_type_ids(F.instrument_types(self.client, self.cfg, self.ctx))
        self.types = len(self.ids)
        if not self.ids:
            raise RuntimeError("no adverse document types in the county's tree")

    def read(self, a: date, b: date) -> tuple[list[dict], bool]:
        F = self.F
        recs, counts = F.run_search(self.client, self.cfg, self.ctx,
                                    F.search_form("", "both", a.isoformat(), b.isoformat(), self.ids))
        if counts is None:
            raise RuntimeError("the search reply was not a results frame")
        if counts["no_results"] or counts["count"] == 0:
            return [], False
        if counts["pages"] > 1 or counts["count"] > len(recs):
            return [], True
        return [summarize(r) for r in merge_records(recs)], False


class PublicSearchReader(Reader):
    """GovOS (Kofile) PublicSearch (Oconee SC; the same reader serves Greenville)."""
    label = "govos_publicsearch_sweep"
    state = "SC"
    MAX_PAGES = 20            # 2,000 documents a window; more is bisected

    def __init__(self, county: str, socket=None, http=None) -> None:
        from . import publicsearch as P
        self.P = P
        self.county = county
        self.cfg = P._cfg("SC", county)
        if self.cfg is None:
            raise KeyError(county)
        self.sock = socket or P._Socket(self.cfg["host"])
        self.http = http
        self.codes: list[str] = []

    def open(self) -> None:
        from .sc_polite import PoliteSession
        http = self.http or PoliteSession()
        root = http.get(f"https://{self.cfg['host']}/")
        self.codes = [c for c, name in parse_publicsearch_doc_types(root.text) if _adverse(name)]
        self.types = len(self.codes)
        if not self.codes:
            raise RuntimeError("no adverse document types in the county's list")

    def read(self, a: date, b: date) -> tuple[list[dict], bool]:
        P = self.P
        out: list[dict] = []
        offset = 0
        for _ in range(self.MAX_PAGES):
            q = {"department": self.cfg["department"], "recordedDateRange": f"{a:%Y%m%d},{b:%Y%m%d}",
                 "searchType": "advancedSearch", "docTypes": ",".join(self.codes), "sort": "desc",
                 "sortBy": "recordedDate", "limit": str(P.PAGE_SIZE), "offset": str(offset)}
            docs, total = P.parse_reply(self.sock.ask(q), self.county.title(), "SC")
            for d in docs:
                out.append({"t": (d.doc_type or "")[:60], "d": d.recorded_date.date().isoformat() if d.recorded_date else None,
                            "b": d.book, "p": d.page, "i": d.instrument_no,
                            "fs": [x for x in (d.grantor or "").split("; ")][:MAX_PARTIES],
                            "gs": [x for x in (d.grantee or "").split("; ")][:MAX_PARTIES]})
            offset += len(docs)
            if not docs or len(docs) < P.PAGE_SIZE or (total is not None and offset >= total):
                return out, False
        return [], True

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass


def parse_publicsearch_doc_types(page_html: str) -> list[tuple[str, str]]:
    """[(code, description)] of the document-type options the PublicSearch root page embeds as JSON."""
    import html as _h
    return [(c, _h.unescape(d)) for c, d in re.findall(r'\{"code":"([^"]+)","description":"([^"]*)"\}', page_html or "")]


class MarriageReader(Reader):
    """The Marriages index of the same CCS LRSearch site (Beaufort NC): every licence in a date window."""
    label = "ccs_lrsearch_marriage_sweep"
    state = "NC"

    def __init__(self, county: str, client: Optional[PoliteClient] = None) -> None:
        from . import nc_lrsearch as L
        self.L = L
        self.county = county
        self.cfg = L.COUNTIES[county]
        self.client = client or beacon_blind_client(L.PLATFORM + "_marriage_sweep", "NC", county)
        self.ctx: dict = {}

    @property
    def key(self) -> str:
        return f"{self.state}_{self.county}_marriage".lower()

    def open(self) -> None:
        self.ctx = self.L.open_marriage(self.client, self.cfg)
        self.types = 1

    def read(self, a: date, b: date) -> tuple[list[dict], bool]:
        rows, overflow = self.L.marriage_window(self.client, self.cfg, self.ctx, a.isoformat(), b.isoformat())
        if overflow:
            return [], True
        return [{"t": "MARRIAGE", "d": r["date"], "x": r["issued"], "i": r["license_no"], "b": r["book"],
                 "p": r["page"], "fs": [r["a1"]] if r["a1"] else [], "gs": [r["a2"]] if r["a2"] else []}
                for r in rows], False


# ------------------------------------------------------------------------------------------------
# the sweep
# ------------------------------------------------------------------------------------------------

@dataclass
class SweepResult:
    county: str
    state: str = ""
    platform: str = ""
    windows_read: int = 0
    instruments_new: int = 0
    window_from: Optional[str] = None
    window_to: Optional[str] = None
    walled: Optional[str] = None
    budget_exhausted: bool = False
    error: Optional[str] = None
    types: int = 0
    index_size: int = 0


def _year_chunks(newest: date, oldest: date) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    y = newest.year
    while y >= oldest.year:
        out.append((max(date(y, 1, 1), oldest), min(date(y, 12, 31), newest)))
        y -= 1
    return out


def cache_path(reader: Reader, cache_dir: Optional[Path] = None) -> Path:
    return (cache_dir or CACHE_DIR) / f"{reader.key}.json"


def load_cache(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
        if isinstance(d, dict) and isinstance(d.get("docs"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"from": None, "to": None, "docs": {}}


def save_cache(path: Path, cache: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, separators=(",", ":")))
        tmp.replace(path)
    except OSError:
        pass


def read_back(read: Callable[[date, date], tuple[list[dict], bool]], newest: date, oldest: date,
              out_of_time: Callable[[], bool], counter: list) -> tuple[list[dict], date]:
    """Read [oldest, newest] newest first, a year at a time, bisecting any window the register says is
    too big. Returns (documents, covered_from): [covered_from, newest] is fully read (covered_from is
    newest + 1 day when nothing was)."""
    cov = newest + timedelta(days=1)
    docs: list[dict] = []

    def go(a: date, b: date) -> tuple[list[dict], date]:
        if out_of_time():
            return [], b + timedelta(days=1)
        counter[0] += 1
        got, overflow = read(a, b)
        if not overflow:
            return got, a
        if a >= b:
            return got, b + timedelta(days=1)       # one day still too big: kept, not claimed
        mid = a + (b - a) // 2
        d2, c2 = go(mid + timedelta(days=1), b)
        if c2 > mid + timedelta(days=1):
            return d2, c2
        d1, c1 = go(a, mid)
        return d2 + d1, c1

    for a, b in _year_chunks(newest, oldest):
        got, c = go(a, b)
        docs += got
        if c > a:
            cov = c
            break
        cov = a
    return docs, cov


def sweep(reader: Reader, *, since: date, today: Optional[date] = None, budget_s: float = 900.0,
          clock: Callable[[], float] = time.monotonic, cache_dir: Optional[Path] = None
          ) -> tuple[PartyIndex, SweepResult]:
    """Read (or reuse from the cache) every adverse instrument from today back to `since`, newest first,
    until the budget ends; return the index over everything held and what the sweep covered."""
    today = today or date.today()
    res = SweepResult(county=reader.county, state=reader.state, platform=reader.label)
    path = cache_path(reader, cache_dir)
    cache = load_cache(path)
    t0 = clock()
    counter = [0]

    def out_of_time() -> bool:
        if clock() - t0 > budget_s:
            res.budget_exhausted = True
            return True
        return False

    c_from = date.fromisoformat(cache["from"]) if cache.get("from") else None
    c_to = date.fromisoformat(cache["to"]) if cache.get("to") else None
    new: dict[str, dict] = {}
    try:
        reader.open()
        res.types = reader.types
        lo = max(since, (c_to - timedelta(days=RECENT_REREAD_DAYS)) if c_to else since)
        docs1, cov1 = read_back(reader.read, today, lo, out_of_time, counter)
        for s in docs1:
            new[doc_key(s)] = s
        if cov1 > lo:                                    # the newest part is incomplete: claim only what was read
            window_from = cov1
        else:
            window_from = min(c_from, lo) if c_from else lo
            if window_from > since:                      # then extend backwards toward `since`
                docs2, cov2 = read_back(reader.read, window_from - timedelta(days=1), since, out_of_time, counter)
                for s in docs2:
                    new[doc_key(s)] = s
                window_from = min(window_from, cov2)
        if window_from <= today:                         # nothing newer read: the old claim stands as it was
            cache["from"], cache["to"] = window_from.isoformat(), today.isoformat()
    except (NcWalled, ScWalled) as exc:
        res.walled = exc.reason
    except Exception as exc:  # noqa: BLE001 - a failed sweep reports and stamps nothing
        res.error = f"{type(exc).__name__}: {str(exc)[:120]}"
    finally:
        reader.close()
    before = len(cache["docs"])
    cache["docs"].update(new)
    res.instruments_new = len(cache["docs"]) - before
    res.windows_read = counter[0]
    if not res.walled and not res.error:
        save_cache(path, cache)
    index = PartyIndex()
    for s in cache["docs"].values():
        index.add(s)
    res.index_size = index.size
    if cache.get("from") and not res.walled and not res.error:
        res.window_from, res.window_to = cache["from"], cache["to"]
    return index, res


# ------------------------------------------------------------------------------------------------
# the stamp
# ------------------------------------------------------------------------------------------------

def stamp_for(hits: Optional[list[dict]], res: SweepResult, checked_at: Optional[str] = None) -> Optional[dict]:
    """raw['rod_lien_sweep'] for one board row, or None (unmatchable owner name / nothing covered).
    status: 'found' (an exact-name match), 'possible' (name-only matches), 'none_found' ('screened, none
    found' for window_from..window_to only)."""
    if hits is None or not res.window_from or res.walled or res.error:
        return None
    strong = [h for h in hits if h.get("fit") == "exact"]
    return {
        "status": "found" if strong else ("possible" if hits else "none_found"),
        "checked_at": checked_at or datetime.now(timezone.utc).date().isoformat(),
        "platform": res.platform, "county": res.county,
        "window_from": res.window_from, "window_to": res.window_to,
        "adverse_types": res.types, "adverse_count": len(strong), "possible_count": len(hits) - len(strong),
        "instruments": hits[:10],
    }


def marriage_stamp(hits: Optional[list[dict]], owner: str, res: SweepResult, county: str,
                   checked_at: Optional[str] = None) -> Optional[dict]:
    """raw['marriage_license'] for one board row from a marriage-index sweep: the newest licence in
    which the owner is one of the two applicants (the spouse is the other name), or a dated
    {'status': 'no_match'} for the window swept. None for an entity or an unmatchable name."""
    q = owner_query(clean_owner(owner))
    if hits is None or q is None or q.entity or not res.window_from or res.walled or res.error:
        return None
    now = checked_at or datetime.now(timezone.utc).isoformat()
    base = {"checked_at": now, "county_issued": county, "source": res.platform,
            "window_from": res.window_from, "window_to": res.window_to}
    if not hits:
        return {**base, "status": "no_match"}
    best = hits[0]
    spouse = next((p for p in list(best.get("fs") or []) + list(best.get("gs") or []) if not name_fit(q, p)), "")
    return {**base, "status": "found" if best.get("fit") == "exact" else "possible",
            "spouse_name": _title(spouse), "license_date": best.get("x") or best.get("d"),
            "marriage_date": best.get("d"), "license_no": best.get("i"),
            "match_confidence": "high" if best.get("fit") == "exact" and q.first else "medium"}


def _title(index_name: str) -> str:
    """'SURNAME, GIVEN M' -> 'Given M Surname' (the board's display order)."""
    if "," in index_name:
        last, _, rest = index_name.partition(",")
        index_name = f"{rest.strip()} {last.strip()}"
    return " ".join(w.capitalize() for w in index_name.split())
