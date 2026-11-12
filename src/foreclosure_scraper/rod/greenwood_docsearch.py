"""Greenwood County SC register reader ('Greenwood County Document Search', the Clerk of Court's
own React app): name search, deed chain and lien existence.

The best free index in SC: deeds from 1897, mortgages from 1980, plats from 1854, tax liens from
2000, each row with the index's legal description and the instruments linked to it. Judgments,
lis pendens and mechanics liens are not in it (they are SC Public Index court filings, left to a
person).

THE WIRE (the page's own request; live-checked 2026-10-07; the Agree/Disagree disclaimer is a
client-side dialog with accuracy-only text, no CAPTCHA, login or challenge)
    POST https://www.greenwoodsc.gov/docsearchrod/asp/webAPI   (Accept: application/json)
      {id: -1, offsetRows, fetchRows (the app uses 300), action: "getResults", txt: "LAST FIRST",
       isValidIP: false, searchType: "Name", exactSearch: false, startsWith1: true,
       partyDirection1: "Either", deeds/mortgages/plats/taxLiens: true|false,
       fromDate / toDate: "MM/DD/YYYY" or "", ...}
      -> {totRec, errMsg, names: [...], details: [{id, instrumentNumber, bookPage ('2210-118'),
          volume, documentType ('Deed', 'Mortgage', 'Satisfaction', 'SC Tax Lien', ...),
          fromNames: [{name: 'Smith John H', match: true}], toNames: [...], legalDescription,
          recorded ('MM/DD/YYYY'), related: [{bookPage, volume, documentType, recorded}], ...}]}
    The app first asks api.ipify.org for the visitor's address to recognise the clerk's own
    terminals (isValidIP); a script is not one of them and sends false, as a home visitor does.
fromNames are the grantors, toNames the grantees; 'match' marks the searched party, which is how
the grantee-side and grantor-side searches are cut here. Names are 'Last First Middle'.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime
from typing import Optional

from .models import RodDoc
from .sc_chain import Docs, NameQuery, Searcher, run_chain, run_search
from .sc_polite import PoliteSession

PLATFORM = "greenwood_docsearch"
BASE = "https://www.greenwoodsc.gov/docsearchrod"
API = f"{BASE}/asp/webAPI"
PAGE_ROWS = 300
MAX_PAGES = 3
TIMEOUT_S = 60.0


def _is_greenwood(state: str, county: str) -> bool:
    return (state or "").upper() == "SC" and (county or "").strip().lower() == "greenwood"


def payload(term: str, *, offset: int = 0, date_from: Optional[date] = None,
            date_to: Optional[date] = None) -> dict:
    mdy = (lambda d: d.strftime("%m/%d/%Y") if d else "")
    return {"id": -1, "offsetRows": offset, "fetchRows": PAGE_ROWS, "action": "getResults", "txt": term,
            "isValidIP": False, "searchType": "Name", "exactSearch": False, "name2": "",
            "startsWith1": True, "startsWith2": True, "partyDirection1": "Either", "partyDirection2": "Either",
            "deeds": True, "mortgages": True, "plats": False, "taxLiens": True,
            "fromDate": mdy(date_from), "toDate": mdy(date_to), "includePartyName": False, "historyText": ""}


def _kind_hint(label: str) -> Optional[str]:
    s = label.upper()
    if ("TAX" in s or s.startswith("FED")) and re.search(r"SATISF|RELEASE|WITHDRAW", s):
        return "lien_release"
    if "TAX LIEN" in s:
        return "lien"
    return None


def parse_details(data: dict, county: str = "Greenwood") -> list[RodDoc]:
    """A webAPI reply -> RodDocs (the matched-party flags kept in raw for side filtering)."""
    out: list[RodDoc] = []
    for d in (data or {}).get("details") or []:
        if not isinstance(d, dict):
            continue
        frm = [n for n in d.get("fromNames") or [] if isinstance(n, dict) and (n.get("name") or "").strip()]
        to = [n for n in d.get("toNames") or [] if isinstance(n, dict) and (n.get("name") or "").strip()]
        label = " ".join(str(d.get("documentType") or "").split()).upper()
        rec = None
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(d.get("recorded") or ""))
        if m:
            rec = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        book, _, page = str(d.get("bookPage") or "").partition("-")
        legal = " ".join(str(d.get("legalDescription") or "").split())[:200] or None
        related = [{"type": r.get("documentType"), "book_page": r.get("bookPage"), "recorded": r.get("recorded")}
                   for r in d.get("related") or [] if isinstance(r, dict)]
        raw = {"platform": PLATFORM, "doc_type_label": label or None, "volume": d.get("volume"),
               "description": legal, "grantor_matched": any(n.get("match") for n in frm),
               "grantee_matched": any(n.get("match") for n in to), "related": related[:10]}
        hint = _kind_hint(label)
        if hint:
            raw["kind_hint"] = hint
        out.append(RodDoc(county=county, state="SC", doc_type=label or "UNKNOWN", recorded_date=rec,
                          book=book.strip() or None, page=page.strip() or None,
                          grantor="; ".join(" ".join(n["name"].split()).upper() for n in frm) or None,
                          grantee="; ".join(" ".join(n["name"].split()).upper() for n in to) or None,
                          instrument_no=str(d.get("instrumentNumber") or "") or None, notes=legal, raw=raw))
    return out


def make_searcher(*, session: Optional[PoliteSession] = None, date_from: Optional[date] = None) -> Searcher:
    http = session or PoliteSession(timeout=TIMEOUT_S)
    opened = {"ok": False}
    hdr = {"Referer": f"{BASE}/", "Accept": "application/json, text/plain, */*"}

    def search(q: NameQuery, side: str, date_to: Optional[date]) -> list[RodDoc]:
        if not opened["ok"]:
            http.get(f"{BASE}/")                              # the app shell (wall-checked)
            opened["ok"] = True
        out = Docs()
        total = None
        for page in range(MAX_PAGES):
            r = http.post(API, json=payload(q.term, offset=page * PAGE_ROWS, date_from=date_from, date_to=date_to),
                          headers=hdr)
            if r.status_code != 200:
                raise RuntimeError(f"webAPI answered HTTP {r.status_code}")
            try:
                data = json.loads(r.text)
            except ValueError as exc:
                raise RuntimeError("webAPI answer was not JSON") from exc
            if (data.get("errMsg") or "").strip():
                raise RuntimeError(f"register error: {data['errMsg'][:80]}")
            docs = parse_details(data)
            total = data.get("totRec") if isinstance(data.get("totRec"), int) else total
            for d in docs:
                if side == "grantee" and not d.raw.get("grantee_matched"):
                    continue
                if side == "grantor" and not d.raw.get("grantor_matched"):
                    continue
                out.append(d)
            if len(docs) < PAGE_ROWS or (total is not None and (page + 1) * PAGE_ROWS >= total):
                break
        else:
            out.truncated = True
        return out

    return search


def chain(county: str, owner_name: str, *, state: str = "SC", depth: int = 3,
          session: Optional[PoliteSession] = None) -> dict:
    """Last deed into the owner + up to `depth` earlier deeds + lien existence: the shared
    raw['rod_chain'] dict (rod/sc_chain.ChainResult.to_dict)."""
    if not _is_greenwood(state, county):
        raise KeyError(f"{county} {state} is not Greenwood SC")
    return run_chain(platform=PLATFORM, state="SC", county="Greenwood", owner_name=owner_name,
                     make_searcher=lambda: make_searcher(session=session), max_prior=depth,
                     source_url=f"{BASE}/").to_dict()


def _search_sync(state: str, county: str, name: str, max_docs: int) -> list[RodDoc]:
    if not _is_greenwood(state, county):
        return []
    return run_search(platform=PLATFORM, state="SC", county="Greenwood", name=name,
                      make_searcher=lambda: make_searcher(), max_docs=max_docs)


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """Every instrument naming `name` as grantor or grantee (newest first)."""
    return await asyncio.to_thread(_search_sync, state, county, name, max_docs)
