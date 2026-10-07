"""Courthouse Computer Systems classic land-records search (application.asp / realestatesearch.asp /
SearchService.asp), name index, for the NC counties that host it OUTSIDE the vendor's Cloudflare-
fronted us3/us4/us5 servers: Orange (county domain), Stanly and Surry (self-hosted).

WHY ONLY THESE THREE
  On 2026-10-07 every hosted tenant tried (us3 Caldwell, us4 Franklin and Hertford, us5 Gates)
  answered an ordinary browser request for application.asp with a Cloudflare 403 challenge, the
  page a person's browser opens when the disclaimer is accepted. That is a wall: those counties
  (HOSTED_WALLED below) are listed for a person, not read. rod/cchs.py reads five hosted tenants
  with a TLS-fingerprint switch; this adapter does not do that.

PROTOCOL (the page's own JavaScript, Manager.search -> SearchService.asp; live-checked on Orange
and Surry)
  1. GET [root/], <app>application.asp?resize=true, <app>realestatesearch.asp      (session)
  2. GET <app>SearchService.asp?cmd=search&last=&given=&indextype=3&searchtype=1|2|3 (grantor,
         grantee, either)&codetype=3&fromdate=&todate=MM/DD/YYYY&...&resultstype=1
         &maxrecordcount=5000&rangetype=doc
     -> <SearchResponse><recordcount>N</recordcount><doccount>D</doccount></SearchResponse>
  3. GET <app>SearchService.asp?cmd=getall&start=0&offset=N   -> <r> rows, one per party pair:
     da date, ki kind, bk / pg book and page, dn document number, or/or1/or2 grantor,
     ee/ee1/ee2 grantee, de description, pk parcel.
  'Begins with' on the surname (the page's default); the owner filter is applied after.
WHAT IS NOT READ: document images.
"""
from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

from dateutil import parser as dateparser

from .nc_chain import IndexRecord, OwnerName, SearchResult, iso_to_mdy
from .nc_platform import NcRodPlatform
from .nc_polite import PoliteClient

PLATFORM = "cchs_classic"
ENV_FLAG = "FORECLOSURE_NC_CCHS_CLASSIC_ROD"
MAX_RECORDS = 5000              # the page's own maxrecordcount
READ_CAP = 1500                 # party rows read in one getall; more is reported as truncated
_SIDE = {"grantor": "1", "grantee": "2", "both": "3"}


@dataclass(frozen=True)
class CchsCounty:
    app: str                     # .../<App>/ (ends with a slash)
    root: Optional[str] = None   # the county landing page a browser opens first, when there is one


COUNTIES: dict[str, CchsCounty] = {
    "Orange": CchsCounty("https://rod.orangecountync.gov/OrangeNCNW/", "https://rod.orangecountync.gov/orangenc/"),
    "Stanly": CchsCounty("http://72.15.246.186/stanlyncnw/"),
    "Surry": CchsCounty("http://rod.surryinfo.net/surryncnwpub/"),
}

#: same app on the vendor's hosted servers, Cloudflare-challenged to an ordinary browser request
#: on 2026-10-07: a person reads them (rod/cchs.py reads Burke, Cleveland, Lincoln, Madison,
#: Henderson its own way)
HOSTED_WALLED = ("Caldwell", "Camden", "Caswell", "Chowan", "Currituck", "Dare", "Duplin", "Franklin", "Gates",
                 "Hertford", "Hyde", "Montgomery")


# ------------------------------------------------------------------------------------------------
# pure parsers (tested on hand-written fixtures)
# ------------------------------------------------------------------------------------------------

def search_query(who: OwnerName, side: str, date_thru: Optional[str]) -> dict:
    return {"cmd": "search", "last": who.last, "given": "" if who.entity else who.first, "indextype": "3",
            "searchtype": _SIDE.get(side, "3"), "codetype": "3", "fromdate": "", "todate": iso_to_mdy(date_thru),
            "instrumenttypes": "", "description": "", "docnumber": "", "booknumber": "", "pagenumber": "",
            "taxfrom": "", "taxto": "", "resultstype": "1", "maxrecordcount": str(MAX_RECORDS),
            "symbolsetout": "0", "sortorder": "1", "sortfield": "docno", "rangetype": "doc"}


def counts(xml: str) -> tuple[Optional[int], Optional[int]]:
    """(recordcount, doccount) of a cmd=search reply; (None, None) when it is not one."""
    m = re.search(r"<recordcount>\s*(\d+)\s*</recordcount>", xml or "", re.I)
    d = re.search(r"<doccount>\s*(\d+)\s*</doccount>", xml or "", re.I)
    return (int(m.group(1)) if m else None), (int(d.group(1)) if d else None)


def _field(rec: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", rec, re.S)
    v = re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1)) if m else ""
    return " ".join(htmllib.unescape(v).split())


def _party(rec: str, tag: str) -> str:
    return " ".join(p for p in (_field(rec, tag), _field(rec, tag + "1"), _field(rec, tag + "2")) if p)


def _iso(v: str) -> Optional[str]:
    try:
        return dateparser.parse(v).date().isoformat() if v else None
    except (ValueError, TypeError, OverflowError):
        return None


def parse_getall(xml: str) -> list[IndexRecord]:
    """One IndexRecord per document from the party rows of a getall reply."""
    out: dict[tuple, IndexRecord] = {}
    for rec in re.findall(r"<r>(.*?)</r>", xml or "", re.S):
        key = (_field(rec, "bk"), _field(rec, "pg"), _field(rec, "dn"))
        r = out.get(key)
        if r is None:
            r = out[key] = IndexRecord(recorded=_iso(_field(rec, "da")), book=key[0] or None, page=key[1] or None,
                                       instrument_no=key[2] or None, doc_type=_field(rec, "ki"),
                                       description=_field(rec, "de") or None)
        for name, bucket in ((_party(rec, "or"), r.grantors), (_party(rec, "ee"), r.grantees)):
            if name and name not in bucket:
                bucket.append(name)
        r.description = r.description or (_field(rec, "de") or None)
    return list(out.values())


# ------------------------------------------------------------------------------------------------
# the adapter
# ------------------------------------------------------------------------------------------------

class CchsClassic(NcRodPlatform):
    platform = PLATFORM
    counties = COUNTIES

    def source_url(self, cfg: CchsCounty) -> str:
        return cfg.app + "realestatesearch.asp"

    def _open(self, client: PoliteClient, cfg: CchsCounty) -> None:
        if cfg.root:
            client.get(cfg.root)
        client.get(cfg.app + "application.asp?resize=true")
        page = client.get(cfg.app + "realestatesearch.asp")
        if "SearchService.asp" not in page.text:
            raise RuntimeError("the land-records search page did not open")

    def _search(self, client: PoliteClient, cfg: CchsCounty, ctx, who: OwnerName, side: str,
                date_thru: Optional[str]) -> SearchResult:
        url = self.source_url(cfg)
        xhr = {"X-Requested-With": "XMLHttpRequest", "Referer": url}
        rep = client.get(cfg.app + "SearchService.asp?" + urlencode(search_query(who, side, date_thru)), headers=xhr)
        n, docs = counts(rep.text)
        if rep.status >= 400 or n is None:
            return SearchResult(status="error", url=url,
                                reason=f"HTTP {rep.status}" if rep.status >= 400 else "the search reply has no record count")
        if n == 0:
            return SearchResult(records=[], total=0, url=url)
        take = min(n, READ_CAP)
        rows = client.get(cfg.app + f"SearchService.asp?cmd=getall&start=0&offset={take}", headers=xhr)
        if rows.status >= 400:
            return SearchResult(status="error", reason=f"HTTP {rows.status}", url=url)
        recs = parse_getall(rows.text)
        if not recs:
            return SearchResult(status="error", reason="the record list was empty although the search counted rows",
                                url=url)
        return SearchResult(records=recs, total=docs if docs is not None else n, url=url,
                            truncated=n > take or n >= MAX_RECORDS)


ADAPTER = CchsClassic()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name(state, county, name, max_docs)


def chain(county: str, owner_name: Optional[str], *, state: str = "NC", depth: int = 3) -> dict:
    return ADAPTER.chain(county, owner_name, state=state, depth=depth)
