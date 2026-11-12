"""GovOS (Kofile) PublicSearch register reader: name search + deed chain + lien existence.

Platform: `<county>.<st>.publicsearch.us` (branded "neumo" in the UI since 2026). Used by Greenville
and Oconee SC here, and by many counties in other states. Per-county config is one line in
PUBLICSEARCH_COUNTIES.

THE WIRE (live-verified 2026-10-07 on Greenville and Oconee; same contract rod/kofile.py documents):
  1. GET https://{host}/ sets two cookies, authToken (an anonymous visitor id handed to any
     visitor, not a credential) and authToken.sig. No CAPTCHA, login or challenge page.
  2. Open wss://{host}/ws with Origin and those cookies.
  3. One JSON frame per page: {"type": "@kofile/FETCH_DOCUMENTS/v4", "payload": {"query": {...},
     "workspaceID": ...}, "authToken": ..., "correlationId": ..., "sync": true}. The query's
     "parties" value is a JSON STRING: {"parties": [{"term": T, "types": ["grantor", "grantee"]}]}
     for either side, {"grantee": [{"term": T, "types": ["grantee"]}]} for one side (the key must
     still be "parties"; putting the role at the top level is silently ignored and returns every
     document in the window). recordedDateRange is "YYYYMMDD,YYYYMMDD".
  4. The reply @kofile/FETCH_DOCUMENTS_FULFILLED/v6 carries meta.numRecords and
     data.byOrder/byHash; each document has recordedDate (M/D/YYYY), docType (label),
     docTypeCode, volume + page (book/page; "book" is a record-type label like DE/MO/SAT),
     instrumentNumber, grantor[] and grantee[] (search hits wrapped in <em>), and remarks[]
     ('Subdivision: ...', 'Free Form Legal: LT 53'): the index's short description.

Kept from a document: the fields above only. The OCR text, thumbnails and download links the
reply also carries are dropped at parse time.

Pacing and walls: sc_polite (>= 1.6 s per host for the GET, the socket open and every frame;
one request at a time per host; a challenge page, a refused socket (HTTP 401/403/429) or a reply
that names a CAPTCHA/challenge marks the county walled and stops).
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date, datetime
from typing import Any, Callable, Optional

import structlog

from .models import RodDoc
from .sc_chain import NameQuery, Searcher, run_chain, run_search
from .sc_polite import UA, PoliteSession, RodWalled, done_host, pace_host

log = structlog.get_logger()

PLATFORM = "govos_publicsearch"

#: (STATE, county lower) -> host, department, earliest index day (the UI's own floor).
PUBLICSEARCH_COUNTIES: dict[tuple[str, str], dict[str, str]] = {
    ("SC", "greenville"): {"host": "greenville.sc.publicsearch.us", "department": "RP", "floor": "17870101"},
    ("SC", "oconee"): {"host": "oconee.sc.publicsearch.us", "department": "RP", "floor": "19550101"},
}

PAGE_SIZE = 100
MAX_PAGES = 3          # at most 300 documents per name search
WS_TIMEOUT = 25.0
FULFILLED = "@kofile/FETCH_DOCUMENTS_FULFILLED/v6"
_WALL_WORDS = re.compile(r"captcha|challenge|forbidden|blocked|rate.?limit|too many requests", re.I)


def _cfg(state: str, county: str) -> Optional[dict[str, str]]:
    return PUBLICSEARCH_COUNTIES.get(((state or "").upper(), (county or "").strip().lower()))


def _strip(name: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(name or ""))).strip()


def parse_doc(doc: dict, county: str, state: str) -> Optional[RodDoc]:
    """One byHash document -> RodDoc (no OCR text, image or download link kept)."""
    if not isinstance(doc, dict):
        return None
    rec = doc.get("recordedDate")
    recorded = None
    if rec:
        try:
            recorded = datetime.strptime(str(rec).strip(), "%m/%d/%Y")
        except ValueError:
            recorded = None
    grantors = [_strip(n) for n in (doc.get("grantor") or []) if _strip(n)]
    grantees = [_strip(n) for n in (doc.get("grantee") or []) if _strip(n)]
    remarks = [_strip(r) for r in (doc.get("remarks") or []) if _strip(r)]
    label = _strip(doc.get("docType")).upper()
    code = _strip(doc.get("docTypeCode")).upper()
    inst = doc.get("instrumentNumber") or doc.get("docNumber")
    desc = "; ".join(remarks)[:200] or None
    return RodDoc(
        county=county, state=state,
        doc_type=label or code or "UNKNOWN",
        recorded_date=recorded,
        book=_strip(doc.get("volume")) or None,
        page=_strip(doc.get("page")) or None,
        grantor="; ".join(grantors) or None,
        grantee="; ".join(grantees) or None,
        instrument_no=str(inst) if inst else None,
        notes=desc,
        raw={"platform": PLATFORM, "doc_type_label": label or None, "doc_type_code": code or None,
             "book_type": _strip(doc.get("book")) or None, "description": desc},
    )


def parse_reply(msg: dict, county: str, state: str) -> tuple[list[RodDoc], Optional[int]]:
    """A FETCH_DOCUMENTS reply -> (documents in the register's order, numRecords).
    Raises RodWalled when the reply is a refusal that names a CAPTCHA, challenge or block."""
    typ = str(msg.get("type") or "")
    if typ != FULFILLED:
        blob = json.dumps(msg)[:2000]
        if _WALL_WORDS.search(blob):
            raise RodWalled(f"wss reply {typ}", "refusal naming a challenge or block")
        raise RuntimeError(f"unexpected reply type {typ[:60]}")
    payload = msg.get("payload") or {}
    data = payload.get("data") or {}
    by_hash = data.get("byHash") or {}
    out = []
    for doc_id in data.get("byOrder") or []:
        d = parse_doc(by_hash.get(str(doc_id)) or {}, county, state)
        if d is not None:
            out.append(d)
    return out, (payload.get("meta") or {}).get("numRecords")


def build_query(cfg: dict[str, str], term: str, side: str, date_to: Optional[date],
                limit: int, offset: int, date_from: Optional[date] = None) -> dict:
    role = {"both": "parties", "grantee": "grantee", "grantor": "grantor"}[side]
    types = ["grantor", "grantee"] if side == "both" else [side]
    upto = (date_to or date.today()).strftime("%Y%m%d")
    start = date_from.strftime("%Y%m%d") if date_from else cfg["floor"]
    return {
        "department": cfg["department"],
        "parties": json.dumps({role: [{"term": term, "types": types}]}),
        "recordedDateRange": f"{start},{upto}",
        "searchType": "advancedSearch",
        # newest first, so the last deed and the latest liens sit on the first page (without it
        # Oconee answers in no date order; live-checked 2026-10-07)
        "sort": "desc", "sortBy": "recordedDate",
        "limit": str(limit), "offset": str(offset),
    }


class _Socket:
    """A paced WebSocket conversation with one host (open lazily, one frame at a time)."""

    def __init__(self, host: str, session: Optional[PoliteSession] = None,
                 connect: Optional[Callable[..., Any]] = None) -> None:
        self.host = host
        self.http = session or PoliteSession()
        self._connect = connect
        self.ws = None
        self.token: Optional[str] = None

    def open(self) -> None:
        r = self.http.get(f"https://{self.host}/")          # wall-checked
        jar = getattr(self.http.s, "cookies", None)
        token = jar.get("authToken") if jar is not None else None
        if not token:
            raise RuntimeError("no authToken cookie on the root page")
        self.token = token
        cookie = "; ".join(f"{k}={v}" for k, v in jar.items() if k.startswith("authToken"))
        connect = self._connect
        if connect is None:
            from websockets.sync.client import connect as ws_connect
            connect = ws_connect
        lk = pace_host(self.host)
        try:
            self.ws = connect(f"wss://{self.host}/ws", additional_headers={
                "Origin": f"https://{self.host}", "Cookie": cookie, "User-Agent": UA},
                open_timeout=WS_TIMEOUT, close_timeout=5)
        except Exception as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (401, 403, 407, 429):
                raise RodWalled(f"wss://{self.host}/ws", f"HTTP {status} on the socket") from exc
            raise
        finally:
            done_host(self.host, lk)
        _ = r

    def ask(self, query: dict) -> dict:
        if self.ws is None:
            self.open()
        corr = str(uuid.uuid4())
        frame = json.dumps({"type": "@kofile/FETCH_DOCUMENTS/v4",
                            "payload": {"query": query, "workspaceID": uuid.uuid4().hex[:22]},
                            "authToken": self.token, "correlationId": corr, "sync": True})
        lk = pace_host(self.host)
        try:
            self.ws.send(frame)
            for _ in range(6):
                msg = json.loads(self.ws.recv(timeout=WS_TIMEOUT))
                if msg.get("correlationId") == corr:
                    return msg
        finally:
            done_host(self.host, lk)
        raise RuntimeError("no reply for the request")

    def close(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:  # noqa: BLE001
                pass
            self.ws = None


def make_searcher(state: str, county: str, *, socket: Optional[_Socket] = None,
                  max_pages: int = MAX_PAGES, date_from: Optional[date] = None) -> Searcher:
    """A sc_chain searcher for one county. date_from narrows every search (live checks only)."""
    cfg = _cfg(state, county)
    if cfg is None:
        raise KeyError(f"{county} {state} is not a PublicSearch county")
    sock = socket or _Socket(cfg["host"])

    def search(q: NameQuery, side: str, date_to: Optional[date]) -> list[RodDoc]:
        out: list[RodDoc] = []
        offset = 0
        for _ in range(max_pages):
            msg = sock.ask(build_query(cfg, q.term, side, date_to, PAGE_SIZE, offset, date_from))
            docs, total = parse_reply(msg, county.title(), state.upper())
            out += docs
            offset += len(docs)
            if not docs or len(docs) < PAGE_SIZE or (total is not None and offset >= total):
                break
        return out

    return search


def chain(county: str, owner_name: str, *, state: str = "SC", depth: int = 3,
          socket: Optional[_Socket] = None) -> dict:
    """Last deed into the owner + up to `depth` earlier deeds + lien existence: the shared
    raw['rod_chain'] dict (rod/sc_chain.ChainResult.to_dict; same keys as rod/nc_chain.py)."""
    if _cfg(state, county) is None:
        raise KeyError(f"{county} {state} is not a PublicSearch county")
    holder: dict = {}

    def factory() -> Searcher:
        holder["sock"] = socket or _Socket(_cfg(state, county)["host"])
        return make_searcher(state, county, socket=holder["sock"])

    try:
        return run_chain(platform=PLATFORM, state=state.upper(), county=county.title(),
                         owner_name=owner_name, make_searcher=factory, max_prior=depth,
                         source_url=f"https://{_cfg(state, county)['host']}/search/advanced").to_dict()
    finally:
        if "sock" in holder and socket is None:
            holder["sock"].close()


def _search_sync(state: str, county: str, name: str, max_docs: int) -> list[RodDoc]:
    if _cfg(state, county) is None:
        return []
    holder: dict = {}

    def factory() -> Searcher:
        holder["sock"] = _Socket(_cfg(state, county)["host"])
        return make_searcher(state, county, socket=holder["sock"])

    try:
        return run_search(platform=PLATFORM, state=state.upper(), county=county.title(), name=name,
                          make_searcher=factory, max_docs=max_docs)
    finally:
        if "sock" in holder:
            holder["sock"].close()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """Every instrument naming `name` as grantor or grantee (newest first): the shared
    enrichment_generic_rod interface."""
    return await asyncio.to_thread(_search_sync, state, county, name, max_docs)
