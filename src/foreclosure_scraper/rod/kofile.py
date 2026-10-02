"""Kofile PublicSearch — Oconee SC (only).

Greenville + Greenwood dropped per scope narrowing 2026-05.

2026-10-02 RE-VERIFIED LIVE, API CONTRACT MIGRATED (not a wall): the old flat
``GET https://{host}/api/search`` REST endpoint this module used to call is
gone sitewide — it now 404s with a React SPA error-page body for every shape
this module built. The site itself is alive and fully functional (confirmed
via live browser devtools network capture against
https://oconee.sc.publicsearch.us/search/advanced): the frontend rebranded to
"neumo" in its UI chrome but its wire protocol still lives under the
``@kofile/`` action namespace, and it now runs entirely over a persistent
WebSocket at ``wss://{host}/ws`` instead of per-request REST calls. There is
no CAPTCHA, no login and no WAF challenge anywhere in this flow — the
``authToken`` below is an ANONYMOUS visitor UUID the server hands out on any
plain GET (even a 404), not a credential, so this is ordinary "vendor changed
their API contract" maintenance, not a bypass.

THE WORKING CONTRACT (live-verified 2026-10-02):
  1. GET https://{host}/ (plain httpx) -> Set-Cookie: authToken=<uuid>;
     authToken.sig=<sig>. Both cookies are REQUIRED on the WS upgrade
     request's Cookie header (dropping them gets the handshake closed with
     code 1005 immediately) and the bare authToken UUID is ALSO repeated
     inside every WS message's JSON body.
  2. Open ``wss://{host}/ws`` with headers Origin: https://{host} and
     Cookie: <the two cookies from step 1>.
  3. Send one JSON text frame per page of results:
       {"type": "@kofile/FETCH_DOCUMENTS/v4",
        "payload": {"query": {<see below>}, "workspaceID": "<any string>"},
        "authToken": "<uuid from step 1>",
        "correlationId": "<fresh uuid>", "sync": true}
     query fields used here: limit (str), offset (str), department ("RP" —
     the only department this Kofile tenant exposes, live-checked: the UI's
     department picker lists "Property Records" only), recordedDateRange
     ("YYYYMMDD,YYYYMMDD"), searchType ("advancedSearch"), and optionally
     _docTypes (a list of vendor doc-type CODES, e.g. ["FORECLOS DEED"]) or
     parties (a JSON-STRING, not a nested object — "{"grantor":[{"term":
     "SMITH","types":["grantor"]}]}" for a single role, or "{"parties":
     [{"term":"SMITH","types":["grantor","grantee"]}]}" to match either
     role, which is what the UI's "Party Names (search both Grantor and
     Grantee)" field sends and what search_by_name below replicates).
  4. The matching reply is
       {"type": "@kofile/FETCH_DOCUMENTS_FULFILLED/v6",
        "payload": {"workspaceID": ..., "meta": {"numRecords": N,
        "statistics": {"docTypes": [{"label": ..., "hits": ...}, ...]}},
        "data": {"byOrder": [docId, ...], "byHash": {"<docId>": {...}}}}}
     Each byHash value carries recordedDate ("M/D/YYYY"), docType (human
     label), docTypeCode (vendor code), grantor/grantee (lists ending in a
     trailing "" sentinel), instrumentNumber/docNumber, volume (the real
     book/volume number — "book" holds a record-TYPE label like "DEED", not
     a number), page, bookVolumePage.

NOD-STAGE DOCUMENTS: the live doc-type facet list for Oconee's RP department
(148 distinct codes, pulled from meta.statistics.docTypes across the full
1955-2026 history) has NO "LIS PENDENS"/"NOTICE OF SALE"/"NOTICE OF DEFAULT"
code at all. The nearest-sounding code, "FORECLOS" ("CORRECT FORECLOSURES"),
is a rare post-sale correction document (7 total in county history, grantor
= Clerk of Court on an already-completed foreclosure), not a pre-foreclosure
notice — it correctly does NOT match NOD_KEYWORDS below. This matches the
rest of the project's documented SC landscape: pre-foreclosure notices/lis
pendens are Clerk of Court filings (covered elsewhere by the eCourts/Public
Index scrapers), not Register of Deeds recordings. So discover_recent_nods
against Oconee legitimately returns few-to-no rows today — that is this
county's real data landscape, not a code bug, and the function is written to
keep working if a future county or a vendor change adds a real NOD code.

search_by_name is real production coverage: enrichment_generic_rod.py calls
it for Oconee SC lien-existence enrichment (was stuck at 0% while the REST
endpoint was dead).
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta

import structlog
import websockets
from dateutil import parser as dateparser

from ..http_client import client
from .models import RodDoc, normalize_doc_type

log = structlog.get_logger()

KOFILE_COUNTIES = {
    ("SC", "Oconee"): "oconee.sc.publicsearch.us",
}

# The only department this Kofile tenant exposes (live-checked via the UI's
# department picker). Kept as a constant rather than per-county config since
# every county on this vendor so far only has one.
_DEPARTMENT = "RP"

# Earliest-possible floor for a "search all history" query. Oconee's own UI
# default floor is 10/16/1955 (presumably this county's actual earliest
# indexed record); an earlier floor is harmless — the server just returns
# whatever it actually has.
_FULL_HISTORY_FROM = "19000101"

_WS_TIMEOUT = 20.0
_PAGE_SIZE = 100          # live-verified up to 200 in one page; 100 is plenty
_MAX_PAGES = 20           # hard stop so a runaway loop can't hammer the host

KOFILE_NOD_DOC_TYPES = (
    "NOTICE OF FORECLOSURE SALE",
    "NOTICE OF SALE",
    "NOTICE OF DEFAULT",
    "LIS PENDENS",
    "FORECLOSURE",
    "NOS",
    "NOD",
)

NOD_KEYWORDS = (
    "NOTICE OF FORECLOSURE",
    "NOTICE OF DEFAULT",
    "NOTICE OF SALE",
    "LIS PENDENS",
    "NOS",
    "NOD",
    "FORECLOSURE SALE",
)


def _is_nod(doc_type: str | None) -> bool:
    if not doc_type:
        return False
    s = doc_type.upper()
    return any(kw in s for kw in NOD_KEYWORDS)


async def _auth_token(host: str) -> tuple[str, str] | None:
    """GET the site root to obtain the anonymous authToken + signature cookies
    the WS protocol needs (live-verified 2026-10-02 — see module docstring).
    No login, no credential: the server hands this UUID to any plain GET,
    even a 404. Returns (authToken, Cookie header value) or None on failure."""
    try:
        async with client(timeout=20.0) as c:
            r = await c.get(f"https://{host}/")
            token = r.cookies.get("authToken")
            if not token:
                return None
            cookie_header = "; ".join(f"{k}={v}" for k, v in r.cookies.items())
            return token, cookie_header
    except Exception as exc:  # noqa: BLE001
        log.warning("kofile.auth_token_failed", host=host,
                    error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return None


def _strip_highlight(name: str) -> str:
    """A party-name search hit comes back with the match wrapped in
    <em>...</em> (live-verified 2026-10-02: searching 'SMITH' returns grantor/
    grantee entries like '<em>SMITH</em> JACK'). Strip any such markup —
    downstream name-matching/normalization expects plain text."""
    return re.sub(r"<[^>]+>", "", name).strip()


def _doc_to_rod(doc: dict, county: str, state: str) -> RodDoc | None:
    if not isinstance(doc, dict):
        return None
    rec = doc.get("recordedDate")
    try:
        recorded = dateparser.parse(rec) if rec else None
    except (ValueError, TypeError, OverflowError):
        recorded = None
    grantors = [_strip_highlight(n) for n in (doc.get("grantor") or []) if n]
    grantees = [_strip_highlight(n) for n in (doc.get("grantee") or []) if n]
    instrument = doc.get("instrumentNumber") or doc.get("docNumber")
    return RodDoc(
        county=county,
        state=state,
        doc_type=normalize_doc_type(doc.get("docType") or doc.get("docTypeCode")),
        recorded_date=recorded,
        # "book" on the wire is a record-TYPE label ("DEED"/"MORTGAGE"), not a
        # number — the real book/volume lives in "volume".
        book=str(doc.get("volume") or "") or None,
        page=str(doc.get("page") or "") or None,
        grantor="; ".join(grantors)[:200] or None,
        grantee="; ".join(grantees)[:200] or None,
        instrument_no=str(instrument) if instrument else None,
        raw=doc,
    )


async def _fetch_documents(host: str, query: dict, max_docs: int) -> list[dict]:
    """One or more @kofile/FETCH_DOCUMENTS/v4 round trips over a single WS
    connection, paginating `offset` until max_docs is covered or the
    vendor's own numRecords is exhausted. Returns raw vendor doc dicts (the
    byHash values, in byOrder order). Swallows all failures to an empty/
    partial list — never raises — matching every other rod/ adapter's
    compliant-no-op contract on an unreachable host."""
    auth = await _auth_token(host)
    if not auth:
        return []
    token, cookie_header = auth
    out: list[dict] = []
    offset = 0
    total: int | None = None
    try:
        async with websockets.connect(
            f"wss://{host}/ws",
            additional_headers={"Origin": f"https://{host}", "Cookie": cookie_header},
            open_timeout=_WS_TIMEOUT,
            close_timeout=5.0,
        ) as ws:
            for _page in range(_MAX_PAGES):
                if len(out) >= max_docs:
                    break
                limit = min(_PAGE_SIZE, max_docs - len(out))
                q = dict(query, limit=str(limit), offset=str(offset))
                corr = str(uuid.uuid4())
                await ws.send(json.dumps({
                    "type": "@kofile/FETCH_DOCUMENTS/v4",
                    "payload": {"query": q, "workspaceID": uuid.uuid4().hex[:22]},
                    "authToken": token,
                    "correlationId": corr,
                    "sync": True,
                }))
                payload = None
                # The socket only ever carries replies to what we sent (we
                # never send ADD_TO_SEARCH_HISTORY etc.), but guard with a
                # correlationId check + bounded read count anyway.
                for _read in range(5):
                    raw = await asyncio.wait_for(ws.recv(), timeout=_WS_TIMEOUT)
                    msg = json.loads(raw)
                    if msg.get("correlationId") != corr:
                        continue
                    if msg.get("type") == "@kofile/FETCH_DOCUMENTS_FULFILLED/v6":
                        payload = msg.get("payload") or {}
                    break
                if payload is None:
                    break
                data = payload.get("data") or {}
                by_order = data.get("byOrder") or []
                by_hash = data.get("byHash") or {}
                if total is None:
                    total = (payload.get("meta") or {}).get("numRecords")
                if not by_order:
                    break
                for doc_id in by_order:
                    d = by_hash.get(str(doc_id))
                    if d:
                        out.append(d)
                offset += len(by_order)
                if total is not None and offset >= total:
                    break
                if len(by_order) < limit:
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("kofile.ws_fetch_failed", host=host,
                    error=f"{type(exc).__name__}: {str(exc)[:160]}")
    return out[:max_docs]


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """All recorded docs naming `name` as either grantor or grantee
    (lien-stack / payoff tracing) — same query the UI's "Party Names (search
    both Grantor and Grantee)" field sends."""
    if (state, county) not in KOFILE_COUNTIES or not name or not name.strip():
        return []
    host = KOFILE_COUNTIES[(state, county)]
    term = name.strip().upper()
    query = {
        "department": _DEPARTMENT,
        "parties": json.dumps({"parties": [{"term": term, "types": ["grantor", "grantee"]}]}),
        "recordedDateRange": f"{_FULL_HISTORY_FROM},{datetime.utcnow():%Y%m%d}",
        "searchType": "advancedSearch",
    }
    raw_docs = await _fetch_documents(host, query, max_docs)
    out = [d for d in (_doc_to_rod(r, county, state) for r in raw_docs) if d is not None]
    return out[:max_docs]


async def discover_recent_nods(
    state: str,
    county: str,
    days_back: int = 60,
    max_docs: int = 100,
) -> list[RodDoc]:
    """Sweep recent Kofile recordings for NOD-style document types.

    Fetches the plain date-range window (no server-side _docTypes filter, so
    a vendor code this module doesn't know about still surfaces) and
    post-filters with the same NOD_KEYWORDS heuristic the other rod/
    adapters use. See the module docstring for why this legitimately returns
    few-to-no rows for Oconee today — a real data-landscape fact, not a bug.
    """
    if (state, county) not in KOFILE_COUNTIES:
        return []
    host = KOFILE_COUNTIES[(state, county)]
    today = datetime.utcnow()
    from_date = today - timedelta(days=max(1, days_back))
    query = {
        "department": _DEPARTMENT,
        "recordedDateRange": f"{from_date:%Y%m%d},{today:%Y%m%d}",
        "searchType": "advancedSearch",
    }
    raw_docs = await _fetch_documents(host, query, max_docs * 6)

    out: list[RodDoc] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for raw in raw_docs:
        d = _doc_to_rod(raw, county, state)
        if d is None or not _is_nod(d.doc_type):
            continue
        if d.recorded_date and d.recorded_date < from_date:
            continue
        key = (d.book, d.page, (d.instrument_no or "").upper())
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
        if len(out) >= max_docs:
            break
    return out
