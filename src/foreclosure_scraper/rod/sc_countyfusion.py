"""GovOS CountyFusion register search (Sumter SC), the guest name index and the document-type window
search the county-wide lien sweep (rod/county_sweeps.py) uses.

Audit 2026-10-09, top-80 build list ranks 34 and 53 (Sumter liens and atty_rod_lien_checked, 3,612
board rows). Before this the platform was recorded as "walled: Login as Guest is a button on a login
form". It is the same shape the Cott eSearch tenants have: a no-credential 'Login as Guest' button
(username and password boxes stay empty, exactly as a browser posts them), then a plain Accept
click-through on the county's disclaimer. No CAPTCHA, challenge or account anywhere (live 2026-10-09).
The disclaimer's only restriction is the SC commercial-solicitation statute the other SC registers
carry too; nothing forbids automated reading.

THE FLOW (live-checked 2026-10-09 on countyfusion2.govos.com, county SumterSC)
  1. GET  /countyweb/login.do?countyname=SumterSC            (a JavaScript forward)
  2. GET  /countyweb/loginDisplay.action?countyname=SumterSC login page: hidden token, 'Login as Guest'
  3. POST /countyweb/login.action  cmd=login, public=true (the guest button), empty username/password
  4. GET  /countyweb/disclaimer.do ; POST /countyweb/disclaimer.do cmd=Accept
  5. GET  /countyweb/search/searchMain.do?defaultType=Public, /search/searchCriteria.do?..., then
          /search/dyncriteria/dynCriteria.do?searchType=allNames  (the session needs all three)
  6. POST /countyweb/search/searchExecute.do?assessor=false  the 'All Names' form: ALLNAMES='LAST FIRST'
          (surname first; 'FIRST LAST' finds nothing), PARTY both|7 (grantor)|6 (grantee),
          FROMDATE/TODATE, INSTTYPE='A,B,C' (document type ids) with INSTTYPEALL empty, RECSPERPAGE=100.
          The reply is the results frame: searchResultObj.noResults / resultsCount / numRecordPages.
  7. GET  /countyweb/search/SumterSC/docs_SearchResultList.jsp?scrollPos=0&searchSessionId=searchJobMain
          the first page of party rows (13 cells a row; Name Type R = grantor/mortgagor, E = grantee).
A blank ALLNAMES with a document-type list and a date window is accepted: that is the sweep.
Document images are never opened.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import dataclass
from typing import Optional

from .nc_chain import IndexRecord, OwnerName, SearchResult, iso_to_mdy, mdy_to_iso
from .nc_platform import NcRodPlatform
from .nc_polite import Page, PoliteClient

PLATFORM = "countyfusion"
ENV_FLAG = "FORECLOSURE_SC_COUNTYFUSION_ROD"
RECS_PER_PAGE = 100          # the form's own largest page size
_SIDE = {"grantor": "7", "grantee": "6", "both": "both"}


@dataclass(frozen=True)
class FusionCounty:
    host: str
    name: str                # the vendor's county key, e.g. SumterSC

    @property
    def base(self) -> str:
        return f"https://{self.host}/countyweb/"


COUNTIES: dict[str, FusionCounty] = {
    "Sumter": FusionCounty("countyfusion2.govos.com", "SumterSC"),
}


# ------------------------------------------------------------------------------------------------
# pure parsers (tested on hand-written fixtures)
# ------------------------------------------------------------------------------------------------

def is_guest_login(text: str) -> bool:
    """The vendor's login page offering a 'Login as Guest' button that asks for no credential."""
    return bool(text) and "doGuestLogin(true)" in text and "Login as Guest" in text


def login_token(text: str) -> Optional[str]:
    m = re.search(r'name="token"\s+value="([^"]+)"', text or "")
    return m.group(1) if m else None


def guest_login_form(county: str, token: str) -> dict:
    """Exactly what the browser posts when 'Login as Guest' is pressed: public=true, no credential."""
    return {"cmd": "login", "countyname": county, "scriptsupport": "yes", "apptype": "", "datasource": "",
            "userdatasource": "", "fraudsleuth": "false", "guest": "false", "public": "true", "startPage": "",
            "CountyFusionForceNewSession": "true", "struts.token.name": "token", "token": token,
            "username": "", "password": ""}


def inst_type_instance(text: str) -> Optional[str]:
    """The id the document-type panel is loaded with (initInstTypePanel(50, ...))."""
    m = re.search(r"initInstTypePanel\(\s*(\d+)\s*,", text or "")
    return m.group(1) if m else None


def search_form(name: str, side: str, date_from: Optional[str], date_to: Optional[str],
                inst_types: Optional[list[str]] = None) -> dict:
    """The All Names form as the page posts it. `name` is 'LAST FIRST' (or '' for a sweep)."""
    types = ",".join(inst_types or [])
    return {"searchCategory": "ADVANCED", "searchSessionId": "searchJobMain", "PLATS": "", "QUARTER": "",
            "SEARCHTYPE": "allNames", "RECSPERPAGE": str(RECS_PER_PAGE), "userRefCode": "",
            "INSTTYPEALL": "" if types else "selected", "INSTTYPE": types, "CASETYPE": "", "ORDERBY_LIST": "",
            "DATERANGE": "", "PARTY": _SIDE.get(side, "both"), "ALLNAMES": name, "SELECTEDNAMES": "",
            "FROMDATE": iso_to_mdy(date_from), "TODATE": iso_to_mdy(date_to)}


def result_counts(text: str) -> Optional[dict]:
    """{no_results, count, pages} of a searchExecute reply, None when it is not a results frame."""
    if "searchResultObj" not in (text or ""):
        return None
    nr = re.search(r"searchResultObj\.noResults\s*=\s*(true|false)", text)
    cnt = re.search(r"searchResultObj\.resultsCount\s*=\s*(\d+)", text)
    pg = re.search(r"searchResultObj\.numRecordPages\s*=\s*(\d+)", text)
    return {"no_results": bool(nr and nr.group(1) == "true"), "count": int(cnt.group(1)) if cnt else 0,
            "pages": int(pg.group(1)) if pg else 0}


def list_url(text: str) -> Optional[str]:
    """The results-list frame address inside a searchExecute reply (relative to /countyweb/search/)."""
    m = re.search(r'src="([^"]*docs_SearchResultList\.jsp[^"]*)"', text or "")
    return htmllib.unescape(m.group(1)) if m else None


def _td_text(td: str) -> str:
    t = re.sub(r"<script.*?</script>", " ", td, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(htmllib.unescape(t).replace("\xa0", " ").split()).rstrip("+").strip()


def _names(td: str) -> list[str]:
    """Every name in a Names / Other Names cell: the first span's title carries the full list
    ('A:: B') when the cell shows 'A +'."""
    m = re.search(r'<span\s+title="([^"]*)"', td)
    full = htmllib.unescape(m.group(1)).strip() if m else ""
    if full:
        return [" ".join(p.split()) for p in full.split("::") if p.strip()]
    one = _td_text(td)
    return [one] if one else []


def parse_result_list(text: str) -> list[IndexRecord]:
    """One IndexRecord per party row of docs_SearchResultList.jsp. Name Type R = grantor/mortgagor,
    E = grantee/lender; the row's other party column carries the opposite side."""
    out: list[IndexRecord] = []
    inst_nums = {int(i): n for i, n in re.findall(r'documentRowInfo\[(\d+)\]\.instNum\s*=\s*"([^"]*)"', text or "")}
    for rid, body in re.findall(r'<tr id="(\d+)">(.*?)</tr>', text or "", re.S):
        tds = re.findall(r"<td>(.*?)</td>", body, re.S)
        if len(tds) < 11:
            continue
        bp = _td_text(tds[2])
        m = re.match(r"\s*(\S+)\s*/\s*(\S+)", bp)
        recorded = mdy_to_iso(_td_text(tds[4]))
        kind = _td_text(tds[5])
        t1, t2 = _td_text(tds[6]).upper(), _td_text(tds[8]).upper()
        n1, n2 = _names(tds[7]), _names(tds[9])
        rec = IndexRecord(recorded=recorded, book=m.group(1) if m else None, page=m.group(2) if m else None,
                          instrument_no=inst_nums.get(int(rid)) or (_td_text(tds[3]) or None), doc_type=kind,
                          description=_td_text(tds[10]) or None)
        for side, names in ((t1, n1), (t2, n2)):
            bucket = rec.grantors if side == "R" else rec.grantees if side == "E" else None
            if bucket is None:
                continue
            for n in names:
                if n not in bucket:
                    bucket.append(n)
        out.append(rec)
    return out


def parse_instrument_tree(payload: str) -> list[tuple[str, str]]:
    """[(id, text)] for every leaf (document type) of getInstrumentCategories.do's JSON tree."""
    try:
        tree = json.loads(payload)
    except (ValueError, TypeError):
        return []
    out: list[tuple[str, str]] = []

    def walk(node) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            kids = (node.get("children") or []) + (node.get("children1") or [])
            nid = str(node.get("id") or "")
            if not kids and nid and not nid.startswith(("Root", "Branch")):
                out.append((nid, str(node.get("text") or "")))
            walk(kids)

    walk(tree)
    return out


_ADVERSE = re.compile(r"LIEN|JUDG|GARNISH|ATTACH|WARRANT OF ATT|WORKMAN|DELINQUENT TAX|FORECLOS|"
                      r"CHILD SUPPORT|LIS PENDENS|\bDEW\b|NOTICE OF LINE", re.I)
_NOT_ADVERSE = re.compile(r"SATISF|RELEASE|SAT\.|WITHDRAW|EXPUNG|AMEND|SUBORDIN|ASSIGN|RESCIS|TERMIN|"
                          r"BOND ADD|PART REL|SUB\.", re.I)


def adverse_type_ids(types: list[tuple[str, str]]) -> list[str]:
    """The document types that are adverse to an owner: liens, judgments, garnishments, attachments,
    foreclosure deeds, delinquent tax notices; not their satisfactions, releases or amendments."""
    return [i for i, t in types if _ADVERSE.search(t) and not _NOT_ADVERSE.search(t)]


# ------------------------------------------------------------------------------------------------
# the adapter
# ------------------------------------------------------------------------------------------------

class CountyFusion(NcRodPlatform):
    platform = PLATFORM
    state = "SC"
    counties = COUNTIES
    cap_env = "FORECLOSURE_SC_COUNTYFUSION_ROD_MAX"

    def source_url(self, cfg: FusionCounty) -> str:
        return f"{cfg.base}login.do?countyname={cfg.name}"

    def _open(self, client: PoliteClient, cfg: FusionCounty):
        return open_session(client, cfg)

    def _search(self, client: PoliteClient, cfg: FusionCounty, ctx, who: OwnerName, side: str,
                date_thru: Optional[str]) -> SearchResult:
        term = who.last if who.entity else f"{who.last} {who.first}".strip()
        recs, counts = run_search(client, cfg, ctx, search_form(term, side, None, date_thru))
        url = self.source_url(cfg)
        if counts is None:
            return SearchResult(status="error", url=url, reason="the search reply was not a results frame")
        if counts["no_results"] or counts["count"] == 0:
            return SearchResult(records=[], total=0, url=url)
        if not recs:
            return SearchResult(status="error", url=url, reason="the result list was empty although it counted rows")
        return SearchResult(records=recs, total=counts["count"], url=url,
                            truncated=counts["pages"] > 1 or counts["count"] > len(recs))


def open_session(client: PoliteClient, cfg: FusionCounty) -> dict:
    """Guest login, disclaimer accept and the three search pages; returns the context the search
    calls need. Raises RuntimeError when a step does not look like the vendor's page."""
    b = cfg.base
    client.get(f"{b}login.do?countyname={cfg.name}")
    login = client.get(f"{b}loginDisplay.action?countyname={cfg.name}",
                       accept_signin=lambda p: is_guest_login(p.text))
    token = login_token(login.text)
    if not is_guest_login(login.text) or not token:
        raise RuntimeError("the sign-in page does not offer a no-credential guest button")
    main = client.post(f"{b}login.action", guest_login_form(cfg.name, token),
                       headers={"Referer": f"{b}loginDisplay.action?countyname={cfg.name}"})
    if "main.jsp" not in main.final_url and "bodyframe" not in main.text:
        raise RuntimeError("the guest login did not open the county's main page")
    ref = {"Referer": f"{b}main.jsp?countyname={cfg.name}"}
    client.get(f"{b}disclaimer.do", headers=ref)
    client.post(f"{b}disclaimer.do", {"cmd": "Accept"}, headers=ref)
    client.get(f"{b}search/searchMain.do?defaultType=Public", headers=ref)
    client.get(f"{b}search/searchCriteria.do?searchCategory=ADVANCED&dynamic=true&enhanced=true", headers=ref)
    crit = client.get(f"{b}search/dyncriteria/dynCriteria.do?searchType=allNames&searchCategory=ADVANCED",
                      headers=ref)
    if "searchExecute.do" not in crit.text:
        raise RuntimeError("the All Names search form did not open")
    return {"ref": f"{b}search/dyncriteria/dynCriteria.do?searchType=allNames&searchCategory=ADVANCED",
            "instance": inst_type_instance(crit.text)}


def run_search(client: PoliteClient, cfg: FusionCounty, ctx: dict, form: dict) -> tuple[list[IndexRecord], Optional[dict]]:
    """POST the form, return (the first page of party rows, the reply's counts)."""
    b = cfg.base
    rep = client.post(f"{b}search/searchExecute.do?assessor=false", form, headers={"Referer": ctx["ref"]})
    counts = result_counts(rep.text)
    if counts is None or counts["no_results"] or counts["count"] == 0:
        return [], counts
    rel = list_url(rep.text) or "SumterSC/docs_SearchResultList.jsp?scrollPos=0&searchSessionId=searchJobMain"
    page = client.get(f"{b}search/{rel}", headers={"Referer": f"{b}search/searchExecute.do?assessor=false"})
    return parse_result_list(page.text), counts


def instrument_types(client: PoliteClient, cfg: FusionCounty, ctx: dict) -> list[tuple[str, str]]:
    """Every document type of the county's All Names panel: [(id, text)]."""
    b = cfg.base
    inst = ctx.get("instance") or "50"
    client.get(f"{b}search/dyncriteria/insttype.jsp?instance={inst}&datatype=INSTTYPE", headers={"Referer": ctx["ref"]})
    rep = client.get(f"{b}search/getInstrumentCategories.do?ordertypes=", headers={"Referer": ctx["ref"]})
    return parse_instrument_tree(rep.text)


ADAPTER = CountyFusion()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name(state, county, name, max_docs)


async def search_by_name_status(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name_status(state, county, name, max_docs)


def chain(county: str, owner_name: Optional[str], *, state: str = "SC", depth: int = 3) -> dict:
    return ADAPTER.chain(county, owner_name, state=state, depth=depth)
