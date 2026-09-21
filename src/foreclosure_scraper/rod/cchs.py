"""Courthouse Computer Systems (CCHS) — Burke + Cleveland NC Register of Deeds.

The legacy flat `searchonline.asp` endpoint is dead (404 sitewide). The live
app is a classic-ASP search service:
  1. session bootstrap: GET /{root}/  -> /{App}/application.asp -> /{App}/realestatesearch.asp
  2. GET /{App}/SearchService.asp?cmd=search&...instrumenttypes=FCL,LIS/P...  -> <recordcount>
  3. GET /{App}/SearchService.asp?cmd=getall&start=0&offset=N  -> <r>..</r> XML rows

Each <r> carries: da (recorded date), ki (instrument type), bk/pg (book/page),
dn (doc#), or+or1 (grantor=owner), ee+ee1 (grantee=lender), mo (money/excise),
pk (parcel). Free, plain httpx, no render. (Lincoln is a different ASP.NET-MVC
CCHS install — not handled here; returns [] gracefully.)

DEED-INDEX SWEEP (sweep_loss_instruments). A date-window search restricted to the
loss-class kinds (trustee's, commissioner's, sheriff's deeds) returns one <r> per
PARTY, so a single deed arrives as several rows. collapse_documents() folds them
into one DeedInstrument per document. The search reply carries <recordcount>
(party rows) and <doccount> (documents); the sweep asserts both against what
getall returns instead of trusting either, and bisects any window that reaches
the row cap. It STOPS the host at the first 403, challenge, CAPTCHA or login
page and never retries it (CchsWall). 2026-09-20: us4 and us5 both answered the
search with a Cloudflare "Just a moment..." 403 after three normal 200
bootstrap pages, so the sweep has not been run live yet.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from dateutil import parser as dateparser

from ..deed_index import DeedInstrument, Party, derive_loss
from ..http_client import client
from ..name_normalize import normalize_name
from . import deed_stamp
from .inst_class import LOSS_CLASSES, classify_instrument
from .models import RodDoc, normalize_doc_type

# (state, county) -> (host, app_slug, root_slug). Burke + Cleveland share the
# us5 classic-ASP install. Lincoln runs the SAME classic-ASP SearchService.asp
# flow on us4/LincolnNCNW (verified live 2026-07-03: search returns recordcount,
# getall returns real <r> rows with grantor/grantee/book-page/doc#). The separate
# us4/LincolnNC2 ASP.NET-MVC install is NOT used — it's a different app surface.
CCHS_COUNTIES = {
    ("NC", "Burke"): ("us5", "BurkeNCNW", "burkenc"),
    ("NC", "Cleveland"): ("us5", "ClevelandNCNW", "clevelandnc"),
    ("NC", "Lincoln"): ("us4", "LincolnNCNW", "lincolnnc"),
    ("NC", "Madison"): ("us4", "MadisonNCNW", "madisonnc"),
    ("NC", "Henderson"): ("us4", "HendersonNCNW", "hendersonnc"),
}

_NOD_TYPES = "FCL,LIS/P,FORECLOSURE,LIS PENDEN"
# Loss-class instrument kinds, read from the county kind dictionaries on
# realestatesearch.asp: Burke (279 kinds) and Lincoln (214) on 2026-09-20, Cleveland
# (365) per docs/deed_index_scoping_2026-09-20.md. The list this replaced was
# "COM/D,FORECLOSURE DEED,SUBTRUSTEE DEED,TRUSTEE". Only COM/D is a real kind, so
# the post-sale sweep never saw a trustee's deed (finding F4).
LOSS_KINDS = ("TR/D", "COM/D", "SHF/D")
_EXTRA_LOSS_KINDS = {("NC", "Cleveland"): ("TR/DEED", "COMM/D", "COMM/DEED", "SHERIFFS DEED")}
_SOLD_TYPES = ",".join(LOSS_KINDS)
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126"}

NOD_KEYWORDS = ("FORECLOS", "LIS PENDEN", "LIS/P", "FCL", "NOTICE OF SALE", "NOS", "NOD")
POST_SALE_KEYWORDS = ("TRUSTEE", "COMMISSIONER", "COM/D", "FORECLOSURE DEED", "POWER OF SALE")
_MONEY_RE = re.compile(r"([\d,]+(?:\.\d{2})?)")


def _is_nod(doc_type: str | None, ki: str = "") -> bool:
    s = (str(ki or "") + " " + str(doc_type or "")).upper()
    return any(k in s for k in NOD_KEYWORDS)


def _is_post_sale(doc_type: str | None, ki: str = "") -> bool:
    s = (str(ki or "") + " " + str(doc_type or "")).upper()
    # The keyword list misses the vendor codes TR/D and SHF/D; the classifier has them.
    return (any(k in s for k in POST_SALE_KEYWORDS)
            or classify_instrument(ki, doc_type) in LOSS_CLASSES)


def loss_kinds(state: str, county: str) -> tuple[str, ...]:
    """Static loss-kind list for a county (the dictionary-derived list wins when
    the search page could be read; see sweep_loss_instruments)."""
    return LOSS_KINDS + _EXTRA_LOSS_KINDS.get((state, county), ())


def _money(s: str | None) -> float | None:
    if not s:
        return None
    m = _MONEY_RE.search(s.replace("$", ""))
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if 0 < v <= 50_000_000 else None


def _cdata(v: str) -> str:
    return re.sub(r"<!\[CDATA\[|\]\]>", "", v or "").strip()


def _field(rec: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", rec, re.S)
    return _cdata(m.group(1)) if m else ""


def _base(host: str, app: str) -> str:
    return f"https://{host}.courthousecomputersystems.com/{app}"


def search_url(state: str, county: str) -> str | None:
    cfg = CCHS_COUNTIES.get((state, county))
    return f"{_base(cfg[0], cfg[1])}/realestatesearch.asp" if cfg else None


def _parse_rows(xml: str, state: str, county: str, *, sold: bool) -> list[RodDoc]:
    docs: dict[tuple, RodDoc] = {}
    for rec in re.findall(r"<r>(.*?)</r>", xml or "", re.S):
        ki = _field(rec, "ki")
        bk, pg, dn = _field(rec, "bk"), _field(rec, "pg"), _field(rec, "dn")
        key = (bk, pg, dn)
        grantor = f"{_field(rec, 'or')} {_field(rec, 'or1')}".strip() or None
        grantee = f"{_field(rec, 'ee')} {_field(rec, 'ee1')}".strip() or None
        seen = docs.get(key)
        if seen is not None:
            # A later party row of a document already read. doc.grantor stays the
            # first row's (a trustee's deed often opens with the law firm), so the
            # full party lists ride in raw for anything that needs the losers.
            for names, name in ((seen.raw["grantors"], grantor), (seen.raw["grantees"], grantee)):
                if name and name not in names:
                    names.append(name)
            continue
        try:
            recorded = dateparser.parse(_field(rec, "da")) if _field(rec, "da") else None
        except (ValueError, TypeError, OverflowError):
            recorded = None
        doc = RodDoc(
            county=county, state=state, doc_type=normalize_doc_type(ki),
            recorded_date=recorded, book=bk or None, page=pg or None,
            instrument_no=dn or None, grantor=grantor, grantee=grantee,
            parcel_id=_field(rec, "pk") or None, notes=_field(rec, "de") or ki or None,
            raw={"ki": ki, "cchs": True,
                 "grantors": [grantor] if grantor else [],
                 "grantees": [grantee] if grantee else []},
        )
        if sold:
            # NC excise stamp = $1 per $500 of consideration; <mo> carries the stamp.
            stamp = _money(_field(rec, "mo"))
            if stamp:
                doc.excise_tax_stamp = stamp
                # Canonical guarded conversion — a misfired stamp yields None
                # (no garbage comp) rather than a bogus consideration.
                doc.consideration_amount = deed_stamp.consideration_from_fields(None, stamp)
        docs[key] = doc
    return list(docs.values())


async def _cchs_fetch(state: str, county: str, instrument_types: str, from_date: datetime,
                      today: datetime, max_docs: int, *, sold: bool) -> list[RodDoc]:
    cfg = CCHS_COUNTIES.get((state, county))
    if not cfg:
        return []
    host, app, root = cfg
    base = _base(host, app)
    xhr = {**_UA, "X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/realestatesearch.asp"}
    try:
        async with client(timeout=40.0, headers=_UA) as c:
            # 1) session bootstrap (cookies persist on the client)
            for u in (f"https://{host}.courthousecomputersystems.com/{root}/",
                      f"{base}/application.asp?resize=true", f"{base}/realestatesearch.asp"):
                await c.get(u, follow_redirects=True)
            # 2) search
            q = {"cmd": "search", "last": "", "given": "", "searchtype": 3, "indextype": 3,
                 "codetype": 3, "fromdate": from_date.strftime("%m/%d/%Y"),
                 "todate": today.strftime("%m/%d/%Y"), "instrumenttypes": instrument_types,
                 "description": "", "docnumber": "", "booknumber": "", "pagenumber": "",
                 "resultstype": 1, "maxrecordcount": max_docs, "sortorder": 1,
                 "sortfield": "docno", "rangetype": "doc"}
            r = await c.get(f"{base}/SearchService.asp?{urlencode(q)}", headers=xhr)
            m = re.search(r"<recordcount>(\d+)</recordcount>", r.text, re.I)
            count = int(m.group(1)) if m else 0
            if count <= 0:
                return []
            # 3) getall
            r2 = await c.get(f"{base}/SearchService.asp?cmd=getall&start=0&offset={min(count, max_docs)}",
                             headers=xhr)
            return _parse_rows(r2.text, state, county, sold=sold)
    except Exception:
        return []


async def discover_recent_nods(state: str, county: str, days_back: int = 60,
                               max_docs: int = 200) -> list[RodDoc]:
    """Recent NOD / lis-pendens / foreclosure recordings (pre-foreclosure leads)."""
    today = datetime.now()
    docs = await _cchs_fetch(state, county, _NOD_TYPES, today - timedelta(days=max(1, days_back)),
                             today, max_docs, sold=False)
    out = [d for d in docs if _is_nod(d.doc_type, d.raw.get("ki", ""))]
    return out[:max_docs]


async def discover_recent_sold_recordings(state: str, county: str, days_back: int = 90,
                                          max_docs: int = 200) -> list[RodDoc]:
    """Recent post-sale recordings (commissioner's / trustee's deed upon sale)."""
    today = datetime.now()
    docs = await _cchs_fetch(state, county, ",".join(loss_kinds(state, county)),
                             today - timedelta(days=max(1, days_back)), today, max_docs, sold=True)
    out = [d for d in docs if _is_post_sale(d.doc_type, d.raw.get("ki", ""))]
    return out[:max_docs]


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """All recorded docs for a grantor/grantee name (lien-stack / payoff tracing)."""
    cfg = CCHS_COUNTIES.get((state, county))
    if not cfg or not name:
        return []
    host, app, root = cfg
    base = _base(host, app)
    xhr = {**_UA, "X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/realestatesearch.asp"}
    last = name.strip().split()[0] if name.strip() else ""
    try:
        async with client(timeout=40.0, headers=_UA) as c:
            for u in (f"https://{host}.courthousecomputersystems.com/{root}/",
                      f"{base}/application.asp?resize=true", f"{base}/realestatesearch.asp"):
                await c.get(u, follow_redirects=True)
            q = {"cmd": "search", "last": last, "given": "", "searchtype": 1, "indextype": 1,
                 "codetype": 0, "fromdate": "", "todate": "", "instrumenttypes": "",
                 "resultstype": 1, "maxrecordcount": max_docs, "sortorder": 1,
                 "sortfield": "docno", "rangetype": "name"}
            r = await c.get(f"{base}/SearchService.asp?{urlencode(q)}", headers=xhr)
            m = re.search(r"<recordcount>(\d+)</recordcount>", r.text, re.I)
            count = int(m.group(1)) if m else 0
            if count <= 0:
                return []
            r2 = await c.get(f"{base}/SearchService.asp?cmd=getall&start=0&offset={min(count, max_docs)}",
                             headers=xhr)
            return _parse_rows(r2.text, state, county, sold=False)[:max_docs]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# Deed-index sweep                                                            #
# --------------------------------------------------------------------------- #

#: The search page's own hard-coded maxrecordcount (Manager constructor in
#: realestatesearch.asp). A reply at this count is treated as cut off.
CCHS_MAX_ROWS = 5000

_DOCTYPE_RE = re.compile(
    r"doctype\.name\s*=\s*'((?:[^'\\]|\\.)*)';\s*doctype\.kind\s*=\s*'((?:[^'\\]|\\.)*)';")
_BOOKTYPE_RE = re.compile(r"BookTypes\[BookTypes\.length-1\]\.name\s*=\s*'([^']*)'")
_WALL_TITLE = re.compile(
    r"<title>[^<]*(?:Just a moment|Attention Required|Access Denied|log ?in|sign ?in)", re.I)
_WALL_MARKER = re.compile(r"g-recaptcha|h-captcha|cf-browser-verification", re.I)


class CchsWall(Exception):
    """The host answered with a 403, a challenge, a CAPTCHA or a login page. That
    host is done: never retry it and never try to get past it."""


def _wall_reason(status: int, text: str) -> str | None:
    if status in (401, 403, 407, 429, 503):
        return f"HTTP {status}"
    head = (text or "")[:6000]
    if _WALL_TITLE.search(head) or _WALL_MARKER.search(head):
        return "challenge, CAPTCHA or login page"
    return None


def _check_wall(resp, host: str, what: str) -> None:
    reason = _wall_reason(resp.status_code, resp.text)
    if reason:
        raise CchsWall(f"{host} {what}: {reason}")


def parse_doctypes(page_html: str) -> list[tuple[str, str, str]]:
    """(book_type, kind, name) for every instrument kind on a realestatesearch.asp
    page. The dictionary is inline JavaScript: `doctype.name = '...'; doctype.kind =
    '...'` blocks, closed by a BookTypes name. Names are HTML-escaped ("&apos;")."""
    out: list[tuple[str, str, str]] = []
    pending: list[tuple[str, str]] = []
    for m in re.finditer(f"{_DOCTYPE_RE.pattern}|{_BOOKTYPE_RE.pattern}", page_html or ""):
        if m.group(3) is not None:
            out.extend((m.group(3), k, n) for k, n in pending)
            pending = []
        else:
            pending.append((html.unescape(m.group(2)), html.unescape(m.group(1))))
    out.extend(("", k, n) for k, n in pending)
    return out


def dictionary_loss_kinds(doctypes: list[tuple[str, str, str]]) -> tuple[str, ...]:
    """Kinds whose code or name reads as a loss deed. Working from the county's own
    dictionary keeps a kind the static list does not know (and drops one the
    county does not have) without a code change."""
    out: list[str] = []
    for _book, kind, name in doctypes:
        if classify_instrument(kind, name) in LOSS_CLASSES and kind not in out:
            out.append(kind)
    return tuple(out)


def _iso_date(v: str) -> str | None:
    try:
        return dateparser.parse(v).date().isoformat() if v else None
    except (ValueError, TypeError, OverflowError):
        return None


def _stamp(v: str | None) -> float | None:
    """The excise stamp as served. Unlike _money, a served "$0.00" stays 0.0, so
    "no stamp" and "zero stamp" stay different (a zero stamp is never a comp)."""
    m = _MONEY_RE.search((v or "").replace("$", ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _party(rec: str, tag: str) -> Party | None:
    """The party in the `or*` (grantor) or `ee*` (grantee) columns of one <r>.
    An individual is split last / first / middle, a firm is all in the first tag."""
    name = " ".join(p for p in (_field(rec, tag), _field(rec, tag + "1"), _field(rec, tag + "2")) if p)
    if not name:
        return None
    return Party(name, kind=_field(rec, tag + "c"), suffix=_field(rec, tag + "s"))


def collapse_documents(xml: str, state: str, county: str) -> list[DeedInstrument]:
    """One DeedInstrument per document from the party rows of a getall reply.

    Grantors and grantees are the distinct parties across all rows of the
    document, so the result is the same whether the vendor repeats the grantee on
    every row or gives it on the first only. Documents are keyed on book, page and
    instrument number; the loser derivation runs here, on the grantors."""
    docs: dict[tuple, dict] = {}
    for rec in re.findall(r"<r>(.*?)</r>", xml or "", re.S):
        key = (_field(rec, "bk"), _field(rec, "pg"), _field(rec, "dn"))
        d = docs.setdefault(key, {"ki": _field(rec, "ki"), "da": _field(rec, "da"),
                                  "grantors": {}, "grantees": {}, "pk": "", "de": "", "mo": None})
        for tag, bucket in (("or", "grantors"), ("ee", "grantees")):
            p = _party(rec, tag)
            if p:
                d[bucket].setdefault(normalize_name(p.name), p)
        d["pk"] = d["pk"] or _field(rec, "pk")
        d["de"] = d["de"] or _field(rec, "de")
        stamp = _stamp(_field(rec, "mo"))
        if stamp is not None and (d["mo"] is None or stamp > d["mo"]):
            d["mo"] = stamp
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out: list[DeedInstrument] = []
    for (bk, pg, dn), d in docs.items():
        inst_class = classify_instrument(d["ki"])
        grantors = list(d["grantors"].values())
        loss_kind, losers = derive_loss(inst_class, grantors, d["de"])
        out.append(DeedInstrument(
            county=county, state=state, source="cchs_classic", inst_code=d["ki"],
            inst_class=inst_class, recorded_date=_iso_date(d["da"]), book=bk or None,
            page=pg or None, instrument_no=dn or None, grantors=[p.name for p in grantors],
            grantor_parties=grantors, grantees=[p.name for p in d["grantees"].values()],
            excise_stamp=d["mo"], parcel_id=d["pk"] or None, description=d["de"] or None,
            loss_kind=loss_kind, loser_names=losers, fetched_at=now))
    return out


@dataclass
class SweepResult:
    state: str
    county: str
    instruments: list[DeedInstrument] = field(default_factory=list)
    kinds: tuple[str, ...] = ()
    kinds_source: str = ""            # "dictionary" (read from the search page) or "static"
    requests: int = 0
    windows: int = 0                  # searches that returned rows
    rows: int = 0                     # party rows read
    truncated: list[str] = field(default_factory=list)   # windows still at the row cap at one day
    problems: list[str] = field(default_factory=list)    # shape problems; never read as "no records"
    walled: str | None = None         # set when a wall stopped the host


def _year_windows(start: date, end: date):
    y = start.year
    while y <= end.year:
        yield max(start, date(y, 1, 1)), min(end, date(y, 12, 31))
        y += 1


def _search_params(kinds: tuple[str, ...], a: date, b: date, max_rows: int) -> dict:
    return {"cmd": "search", "last": "", "given": "", "searchtype": 3, "indextype": 3,
            "codetype": 3, "fromdate": a.strftime("%m/%d/%Y"), "todate": b.strftime("%m/%d/%Y"),
            "instrumenttypes": ",".join(kinds), "description": "", "docnumber": "",
            "booknumber": "", "pagenumber": "", "resultstype": 1, "maxrecordcount": max_rows,
            "sortorder": 1, "sortfield": "docno", "rangetype": "doc"}


async def _sweep_window(c, host: str, base: str, xhr: dict, res: SweepResult,
                        a: date, b: date, max_rows: int) -> None:
    label = f"{a.isoformat()}..{b.isoformat()}"
    span = (b - a).days

    async def halves() -> None:
        mid = a + timedelta(days=span // 2)
        await _sweep_window(c, host, base, xhr, res, a, mid, max_rows)
        await _sweep_window(c, host, base, xhr, res, mid + timedelta(days=1), b, max_rows)

    r = await c.get(f"{base}/SearchService.asp?{urlencode(_search_params(res.kinds, a, b, max_rows))}",
                    headers=xhr)
    res.requests += 1
    _check_wall(r, host, f"search {label}")
    m = re.search(r"<recordcount>(\d+)</recordcount>", r.text, re.I)
    if not m:
        res.problems.append(f"{label}: search reply has no <recordcount>, not read as 'no records'")
        return
    n = int(m.group(1))
    if n == 0:
        return
    if n >= max_rows and span >= 1:
        await halves()               # at the cap: the reply may be the head of a longer list
        return
    r2 = await c.get(f"{base}/SearchService.asp?cmd=getall&start=0&offset={n}", headers=xhr)
    res.requests += 1
    _check_wall(r2, host, f"getall {label}")
    got = len(re.findall(r"<r>", r2.text))
    if got < n and span >= 1:
        await halves()               # a short page: narrow the window until it fits
        return
    if got != n:
        res.problems.append(f"{label}: <recordcount> {n} but getall returned {got} rows")
    if n >= max_rows:
        res.truncated.append(label)
    docs = collapse_documents(r2.text, res.state, res.county)
    dm = re.search(r"<doccount>(\d+)</doccount>", r.text, re.I)
    if dm and int(dm.group(1)) != len(docs):
        res.problems.append(f"{label}: <doccount> {dm.group(1)} but {len(docs)} documents collapsed")
    loss = [d for d in docs if d.inst_class in LOSS_CLASSES]
    if len(loss) != len(docs):
        res.problems.append(f"{label}: {len(docs) - len(loss)} of {len(docs)} documents were not "
                            f"loss kinds (kind filter ignored?); dropped")
    res.rows += got
    res.windows += 1
    res.instruments.extend(loss)


async def sweep_loss_instruments(state: str, county: str, from_date: date, to_date: date,
                                 *, max_rows: int = CCHS_MAX_ROWS) -> SweepResult:
    """Every loss-class instrument (trustee's, commissioner's, sheriff's deed)
    recorded from from_date to to_date, one DeedInstrument per document.

    One session, one search and one getall per year window (more only when a
    window reaches the cap). Requests go through the throttled shared client, so
    the host sees roughly one request a second. A wall stops the sweep and comes
    back in SweepResult.walled with whatever was read before it."""
    res = SweepResult(state, county)
    cfg = CCHS_COUNTIES.get((state, county))
    if not cfg:
        res.problems.append(f"{county}, {state} is not a CCHS classic-ASP county")
        return res
    host, app, root = cfg
    hostname = f"{host}.courthousecomputersystems.com"
    base = _base(host, app)
    xhr = {**_UA, "X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/realestatesearch.asp"}
    try:
        async with client(timeout=40.0, headers=_UA) as c:
            page = ""
            for u in (f"https://{hostname}/{root}/", f"{base}/application.asp?resize=true",
                      f"{base}/realestatesearch.asp"):
                r = await c.get(u, follow_redirects=True)
                res.requests += 1
                _check_wall(r, hostname, "bootstrap")
                page = r.text
            found = dictionary_loss_kinds(parse_doctypes(page))
            if found:
                res.kinds, res.kinds_source = found, "dictionary"
            else:
                res.kinds, res.kinds_source = loss_kinds(state, county), "static"
                res.problems.append("no kind dictionary on realestatesearch.asp; used the static loss kinds")
            for a, b in _year_windows(from_date, to_date):
                await _sweep_window(c, hostname, base, xhr, res, a, b, max_rows)
    except CchsWall as w:
        res.walled = str(w)
    except Exception as exc:  # noqa: BLE001
        res.problems.append(f"sweep aborted: {type(exc).__name__}: {str(exc)[:160]}")
    res.instruments = list({d.doc_key: d for d in res.instruments}.values())
    return res
