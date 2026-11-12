"""Anderson County SC register by name: ACPASS (7/1/1974 - 2/20/2026), with the post-2026-02-20
gap stated in every result.

THE GAP, CHECKED 2026-10-07
    Anderson moved its register to Ingenuity 'Online Services' (sc.ingcountyapps.com/anderson_rod)
    on 2026-02-21; ACPASS stops at 2026-02-20. The attorney cleared terms-only limits (Ingenuity's
    terms ban bots), so the new site was opened once to see whether a script may read it. It may
    not: every page loads Scripts/botdetect.js, which grades the browser (navigator.webdriver,
    headless user agent, empty languages, a tampered eval) and posts the verdict back in a hidden
    field (ctl00$hdnBotResult) before the land-record lookup is offered, and the site says it
    monitors for automated use. Filling that field from a script would be defeating a bot check,
    so nothing here touches Ingenuity: sc_polite.detect_wall() classes that page 'bot check'.
    Deeds recorded since 2026-02-21 are a person's job (open the site in a normal browser).
    What a script CAN add: the county parcel layer's current deed book/page and sale year
    (County_Parcels: DBOOK, DPAGE, SALE_YEAR) for a parcel, which shows when the vesting deed is
    newer than the ACPASS index (chain(..., parcel_id=...)).

ACPASS NAME SEARCH (live-checked 2026-10-07; robots.txt Disallow: / which the owner ruled is not a
wall; no CAPTCHA, login or challenge; the scraper counties_sc.anderson_acpass_deeds reads the
same host's type sweep)
    POST deedmain.cgi  QrySrchType=L, QryName=<LAST FIRST>, QryLimitBeg=<MM/DD/YYYY or ''>, and
                       every other field empty (a name with a date range is refused: 'Please Choose
                       Only One Field')
      -> 25 rows a page: NAME (the party that matched), GRANTOR|GRANTEE (its role), TYPE, date,
         instrument number, book and page, then a 'DESC:' line (the index's short description)
    POST dednamen.cgi  searchtype, queryn, instrnon, seqnon from the page's 'More' form -> next 25
    GET  deddetail1.cgi?instryearnbr=L<year><instr>  every party with its role
A row names one side only, so the other side of a deed is read from its detail page (at most
DETAIL_CAP deeds per search, newest first).
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from ..sensitive_fields import drop_sensitive
from .models import RodDoc
from .sc_chain import Docs, NameQuery, Searcher, kind_of, name_fit, run_chain, run_search
from .sc_polite import PoliteSession

PLATFORM = "anderson_acpass"
BASE = "https://acpass.andersoncountysc.org"
INDEX_THROUGH = date(2026, 2, 20)
INGENUITY_URL = "https://sc.ingcountyapps.com/anderson_rod/"
INGENUITY_WALL = "bot check (client-side bot detector posts its verdict before the land-record lookup)"
GIS_URL = ("https://gis.cityofandersonsc.com/arcgis/rest/services/WaterUtilities/County_Parcels/"
           "FeatureServer/0/query")
GIS_FIELDS = "TMS,DBOOK,DPAGE,SALE_YEAR"
MAX_PAGES = 8
DETAIL_CAP = 4
GAP_NOTE = (f"Anderson's online index read here (ACPASS) ends {INDEX_THROUGH:%Y-%m-%d}. Deeds and liens "
            f"recorded since 2026-02-21 are only in the county's new system ({INGENUITY_URL}), which runs a "
            f"bot check, so a person must look there.")


@dataclass
class AcpassRow:
    key: str                  # L<year><instr>
    name: str
    role: str                 # GRANTOR | GRANTEE
    doc_type: str
    recorded: Optional[datetime]
    instrument_no: Optional[str]
    book: Optional[str]
    page: Optional[str]
    description: Optional[str]


#: the role column's words, and which side of the instrument each is
ROLES = {"GRANTOR": "GRANTOR", "GRANTEE": "GRANTEE", "MORTGAGOR": "GRANTOR", "MORTGAGEE": "GRANTEE",
         "DEBTOR": "GRANTOR", "SECURED PARTY": "GRANTEE", "LIENOR": "GRANTOR", "LIENEE": "GRANTEE",
         "PLAINTIFF": "GRANTOR", "DEFENDANT": "GRANTEE"}


def _clean(s: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ").replace("&amp;", "&").split())


def parse_results(html: str) -> list[AcpassRow]:
    """One deedmain.cgi / dednamen.cgi page -> rows."""
    parts = re.split(r'<input type="checkbox" name="instryearnbr" value="(L\d+)">', html or "")
    out: list[AcpassRow] = []
    for i in range(1, len(parts), 2):
        key, chunk = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        a = re.search(r'deddetail1\.cgi\?instryearnbr=' + re.escape(key) + r'">(.*?)</a>', chunk, re.S)
        if not a:
            continue
        cells = [_clean(c) for c in re.findall(r'<div align="center">(.*?)</div>', chunk, re.S)]
        cells = [c for c in cells if c]
        role = next((c for c in cells if c in ROLES), "")
        after = cells[cells.index(role) + 1:] if role in cells else cells[1:]
        typ = after[0] if after else ""
        m_date = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", chunk)
        rec = datetime(int(m_date.group(3)), int(m_date.group(1)), int(m_date.group(2))) if m_date else None
        m_bp = re.search(r"<div align=\"center\">\s*([0-9A-Z-]+)(?:&nbsp;)+\s*([0-9A-Z-]+)\s*</div>", chunk)
        inst = next((c for c in after[1:] if re.fullmatch(r"\d{6,12}", c)), None)
        desc = None
        m_desc = re.search(r"DESC:\s*</strong>.*?<strong>(.*?)</strong>", chunk, re.S)
        if m_desc:
            desc = _clean(m_desc.group(1)) or None
        out.append(AcpassRow(key=key, name=_clean(a.group(1)), role=role, doc_type=typ.upper(), recorded=rec,
                             instrument_no=inst,
                             book=(m_bp.group(1).lstrip("0") or m_bp.group(1)) if m_bp else None,
                             page=(m_bp.group(2).lstrip("0") or m_bp.group(2)) if m_bp else None,
                             description=desc))
    return out


def parse_more(html: str) -> Optional[dict[str, str]]:
    """The 'More' form's hidden cursor, or None on the last page."""
    if 'name="queryn"' not in (html or ""):
        return None
    out = {}
    for f in ("searchtype", "queryn", "instrnon", "seqnon"):
        m = re.search(r'name="' + f + r'"\s+type="hidden"\s+value="?([^">]*)"?', html)
        if not m:
            return None
        out[f] = m.group(1)
    return out


def parse_detail(html: str) -> dict[str, list[str]]:
    """deddetail1.cgi -> {'GRANTOR': [...], 'GRANTEE': [...]}"""
    lines = [ln.strip(" :") for ln in re.sub(r"<[^>]+>", "\n", (html or "").replace("&nbsp;", " ")).split("\n")]
    lines = [ln for ln in lines if ln]
    out: dict[str, list[str]] = {"GRANTOR": [], "GRANTEE": []}
    for i, ln in enumerate(lines):
        if ln in out and i >= 1:
            name = " ".join(lines[i - 1].split())
            if name and name not in out[ln] and name not in ("GRANTOR", "GRANTEE"):
                out[ln].append(name)
    return out


#: ACPASS type spellings that are deeds although no shared rule reads them so
_DEED_TYPES = {"DEE", "DED", "DEED'", "DEED"}


def to_doc(r: AcpassRow) -> RodDoc:
    side = ROLES.get(r.role)
    grantor, grantee = (r.name, None) if side == "GRANTOR" else (None, r.name) if side == "GRANTEE" else (r.name, None)
    doc = RodDoc(county="Anderson", state="SC", doc_type=r.doc_type or "UNKNOWN", recorded_date=r.recorded,
                  book=r.book, page=r.page, grantor=grantor, grantee=grantee, instrument_no=r.instrument_no,
                  notes=r.description,
                  raw={"platform": PLATFORM, "doc_type_label": r.doc_type or None, "party_role": r.role or None,
                       "acpass_key": r.key, "description": r.description})
    if r.doc_type in _DEED_TYPES:
        doc.raw["kind_hint"] = "deed"
    return doc


def browse_term(q: NameQuery) -> str:
    """ACPASS lists the index FROM the typed name onward, and keeps people as 'LAST, FIRST': a
    person is typed that way (typed 'LAST FIRST' the list starts after every 'LAST, ...' entry).
    Entries filed under the initial only ('LAST, J') sort before the start and are not read."""
    return q.term if q.entity else f"{q.last}, {q.first}"


def past_name(q: NameQuery, rows: list[AcpassRow]) -> bool:
    """The browse has moved past every name the query can fit (the last row sorts after it)."""
    if not rows:
        return False
    last = " ".join(re.sub(r"[^A-Z0-9, ]", " ", rows[-1].name.upper()).split())
    return not last.startswith(browse_term(q).upper())


def make_searcher(*, session: Optional[PoliteSession] = None, date_from: Optional[date] = None,
                  detail_cap: int = DETAIL_CAP) -> Searcher:
    http = session or PoliteSession()
    opened = {"ok": False}

    def search(q: NameQuery, side: str, date_to: Optional[date]) -> list[RodDoc]:
        if not opened["ok"]:
            http.get(f"{BASE}/deeda.cgi?SearchType=L")
            opened["ok"] = True
        hdr = {"Referer": f"{BASE}/deeda.cgi?SearchType=L", "Origin": BASE}
        r = http.post(f"{BASE}/deedmain.cgi", data={
            "QrySrchType": "L", "QryName": browse_term(q), "QryLimitBeg": date_from.strftime("%m/%d/%Y") if date_from else "",
            "QryInstYear": "", "QryBegInstNbr": "", "QryEndInstNbr": "", "QryBook": "", "QryBegPage": "",
            "QryEndPage": "", "QryFromDate": "", "QryToDate": "", "QryType": "", "Submit": "Submit"}, headers=hdr)
        if r.status_code != 200:
            raise RuntimeError(f"ACPASS answered HTTP {r.status_code}")
        if re.search(r"Error\(s\) Have Been Found", r.text):
            raise RuntimeError("ACPASS refused the search")
        rows = parse_results(r.text)
        cursor, pages = parse_more(r.text), 1
        while cursor and pages < MAX_PAGES and not past_name(q, rows):
            nxt = http.post(f"{BASE}/dednamen.cgi", data=cursor, headers={"Referer": f"{BASE}/deedmain.cgi"})
            more = parse_results(nxt.text)
            if not more:
                cursor = None
                break
            rows += more
            cursor, pages = parse_more(nxt.text), pages + 1
        if past_name(q, rows):
            cursor = None
        out = Docs()
        out.truncated = cursor is not None
        for row in rows:
            row_side = ROLES.get(row.role)
            if side in ("grantor", "grantee") and row_side and row_side != side.upper():
                continue
            if not name_fit(q, row.name):
                continue
            day = row.recorded.date() if row.recorded else None
            if day and date_to and day > date_to:
                continue
            out.append(to_doc(row))
        # the other side of the newest deeds into the name (the chain needs their grantors)
        deeds = sorted((d for d in out if d.grantee and kind_of(d) == "deed"),
                       key=lambda d: d.recorded_date or datetime.min, reverse=True)
        for d in deeds[:detail_cap]:
            det = parse_detail(http.get(f"{BASE}/deddetail1.cgi?instryearnbr={d.raw['acpass_key']}").text)
            if det["GRANTOR"]:
                d.grantor = "; ".join(det["GRANTOR"])
            if det["GRANTEE"]:
                d.grantee = "; ".join(det["GRANTEE"])
        return out

    return search


def parcel_deed(parcel_id: str, *, session: Optional[PoliteSession] = None) -> Optional[dict]:
    """The county parcel layer's current deed reference for one TMS (explicit fields only)."""
    pid = re.sub(r"[^0-9A-Za-z-]", "", parcel_id or "")
    if not pid:
        return None
    http = session or PoliteSession()
    r = http.get(GIS_URL, params={"where": f"TMS='{pid}'", "outFields": GIS_FIELDS,
                                  "returnGeometry": "false", "f": "json"})
    try:
        feats = r.json().get("features") or []
    except ValueError:
        return None
    if not feats:
        return None
    a = drop_sensitive(feats[0].get("attributes") or {})
    return {"book": str(a.get("DBOOK") or "").strip() or None, "page": str(a.get("DPAGE") or "").strip() or None,
            "sale_year": a.get("SALE_YEAR")}


def chain(county: str, owner_name: str, *, state: str = "SC", depth: int = 3,
          session: Optional[PoliteSession] = None, parcel_id: Optional[str] = None) -> dict:
    """The shared raw['rod_chain'] dict for an Anderson owner, from ACPASS, with the index's end
    date stated; with parcel_id, a vesting deed newer than the index is flagged for a person."""
    if (state or "").upper() != "SC" or (county or "").strip().lower() != "anderson":
        raise KeyError(f"{county} {state} is not Anderson SC")
    res = run_chain(platform=PLATFORM, state="SC", county="Anderson", owner_name=owner_name,
                    make_searcher=lambda: make_searcher(session=session), max_prior=depth,
                    source_url=f"{BASE}/deeda.cgi?SearchType=L")
    res.notes.append(GAP_NOTE)
    out = res.to_dict()
    out["index_through"] = INDEX_THROUGH.isoformat()
    out["after_index"] = {"source": INGENUITY_URL, "readable_by_script": False, "why": INGENUITY_WALL}
    if parcel_id and out["status"] not in ("walled", "capped"):
        try:
            gis = parcel_deed(parcel_id, session=session)
        except Exception:  # noqa: BLE001 - the flag is extra; the chain stands without it
            gis = None
        if gis:
            ld = out.get("last_deed") or {}
            same = gis.get("book") and (gis["book"].lstrip("0"), (gis.get("page") or "").lstrip("0")) == \
                ((ld.get("book") or "").lstrip("0"), (ld.get("page") or "").lstrip("0"))
            out["after_index"]["parcel_layer_deed"] = gis
            if not same and isinstance(gis.get("sale_year"), int) and gis["sale_year"] >= INDEX_THROUGH.year:
                out["after_index"]["newer_deed_likely"] = True
                out["notes"].append(f"The county parcel layer cites deed {gis.get('book')}/{gis.get('page')} "
                                    f"({gis['sale_year']}), not in the ACPASS index: a newer deed a person must "
                                    f"read in the new system.")
    return out


def _search_sync(state: str, county: str, name: str, max_docs: int) -> list[RodDoc]:
    if (state or "").upper() != "SC" or (county or "").strip().lower() != "anderson":
        return []
    return run_search(platform=PLATFORM, state="SC", county="Anderson", name=name,
                      make_searcher=lambda: make_searcher(), max_docs=max_docs)


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """Every ACPASS instrument naming `name` (newest first; index ends 2026-02-20): the shared
    enrichment_generic_rod interface."""
    return await asyncio.to_thread(_search_sync, state, county, name, max_docs)
