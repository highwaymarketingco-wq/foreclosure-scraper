"""SC public notices (scpublicnotices.com, SC Press Association) — the FREE,
legal, public-by-design route to statewide SC foreclosure + probate leads.

SC foreclosure is judicial and the court Public Index is scraping-prohibited, but
legal NOTICES (foreclosure summons/sale, estate/creditor, tax sale) must be
published and are public — this site aggregates them for all 46 counties. This
fills the SC gap where ROD-probate isn't wired (Spartanburg/Anderson/Cherokee/
Oconee) and cross-checks foreclosures.

Mechanism (browserless, verified): the site uses ASP.NET WebForms with a
COOKIELESS session (the /(S(id))/ path segment). GET Search.aspx -> the response
URL carries the session id; POST to THAT session URL with
__EVENTTARGET=ddlPopularSearches + ddlPopularSearches=<category> returns the
results GridView. Each row exposes publication / date / City: / County: + the
full notice text + a Details.aspx?ID= link. (POSTing the base URL or btnSearch
just re-renders the form — the session URL + event target are the unlock.)

YIELD/LIMITATION (v1): the popular-search returns the recent statewide notices per
category (~10-11 parsed per category; the grid lazy-loads the rest to 100 via
AJAX), filtered here to our 7 in-scope counties — so a given run yields the
in-scope notices that surfaced recently. The county-FILTERED search (lstCounty
checkboxes + date range via btnGo) would give complete per-county coverage but
currently returns HTTP 500 on the bare POST (needs the AJAX async-postback
protocol / a field combo not yet cracked, or the stealth renderer). Refinement:
drive the county+date+category search via render.py/StealthyFetcher (handles the
AJAX), or page the lazy-loaded grid, for full coverage. The parser + mapping below
are complete and correct regardless of how the rows are fetched.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://www.scpublicnotices.com/Search.aspx"
_PFX = "ctl00$ContentPlaceHolder1$as1$"

# Popular-search category -> (our listing type, kind tag)
_CATEGORIES = {
    "4":  (ListingType.LIS_PENDENS, "foreclosure"),    # Foreclosures (summons/sale)
    "23": (ListingType.PROBATE_NOTICE, "probate"),     # Probate Notices
    "30": (ListingType.PROBATE_NOTICE, "probate"),     # Notice to Creditors (estate)
    "26": (ListingType.TAX_SALE, "tax"),               # Tax Sales
}
_IN_SCOPE = {"spartanburg", "anderson", "pickens", "oconee", "cherokee", "union", "laurens"}

_HID_RE = re.compile(r'id="(__[A-Z]+)"\s+value="([^"]*)"')
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_ID_RE = re.compile(r"Details\.aspx\?SID=[^&]+&(?:amp;)?ID=(\d+)")
_COUNTY_RE = re.compile(r"County:\s*([A-Za-z .'-]+?)(?:\s*City:|\s*$|\s*<)", re.I)
_CITY_RE = re.compile(r"City:\s*([A-Za-z .'-]+?)\s*County:", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b|"
                      r"\b([A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\b")
# defendant / decedent extraction from legal-notice text
_VS_RE = re.compile(r"(?:plaintiff[s]?,?\s+)?v[s.]{1,3}\.?\s+([A-Z][A-Za-z .,'&-]{3,60}?)(?:,?\s+defendant|,?\s+et al|\s+TO THE|\s*\.|\s*$)", re.I)
_ESTATE_RE = re.compile(r"(?:estate of|in re:?|decedent:?)\s+([A-Z][A-Za-z .,'-]{3,60}?)(?:,|\s+deceased|\s+date of death|\s*\()", re.I)
_ADDR_RE = re.compile(r"(?:property\s+(?:located\s+at|address)|premises\s+(?:known|located)\s+as)[:\s]+([0-9][^,.;]{6,60})", re.I)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ")
                  .replace("&amp;", "&").replace("&#39;", "'")).strip()


def _hidden(html: str) -> dict:
    return {k: v for k, v in _HID_RE.findall(html)}


def _parse_results(html: str) -> list[dict]:
    """Parse the results GridView into notice dicts (publication/date/city/county/text/id)."""
    out: list[dict] = []
    for row in _ROW_RE.findall(html):
        m = _ID_RE.search(row)
        if not m:
            continue
        cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        cells = [c for c in cells if c and "javascript" not in c.lower()]
        meta = next((c for c in cells if "county:" in c.lower()), "")
        body = max((c for c in cells if "county:" not in c.lower()), key=len, default="")
        county_m = _COUNTY_RE.search(meta)
        city_m = _CITY_RE.search(meta)
        date_m = _DATE_RE.search(meta)
        out.append({
            "notice_id": m.group(1),
            "county": (county_m.group(1).strip() if county_m else ""),
            "city": (city_m.group(1).strip() if city_m else ""),
            "date_text": (date_m.group(1) or date_m.group(2)) if date_m else "",
            "publication": meta.split(" ")[0:3] and " ".join(meta.split()[:3]) or "",
            "text": body,
        })
    return out


def _parse_date(s: str) -> datetime | None:
    for fmt in ("%m/%d/%Y", "%A, %B %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _defendant(text: str, kind: str) -> str | None:
    if kind == "probate":
        m = _ESTATE_RE.search(text)
    else:
        m = _VS_RE.search(text)
    return _clean(m.group(1)) if m else None


def _to_listing(n: dict, cat: str, slug: str) -> Listing | None:
    if (n["county"] or "").strip().lower() not in _IN_SCOPE:
        return None
    lt, kind = _CATEGORIES[cat]
    text = n["text"]
    # Foreclosure: distinguish a SALE notice from a pre-foreclosure summons.
    if kind == "foreclosure" and re.search(r"\b(master'?s sale|notice of sale|will be sold|public auction)\b", text, re.I):
        lt = ListingType.FORECLOSURE_SALE
    rec = _parse_date(n["date_text"])
    addr_m = _ADDR_RE.search(text)
    raw: dict = {"public_notice": {"notice_id": n["notice_id"], "publication": n["publication"],
                                   "category": cat, "city": n["city"], "text": text[:4000]}}
    if kind == "probate":
        raw["relationship_signal"] = {"kind": "probate", "keyword": "public_notice",
                                      "tagged_at": datetime.utcnow().isoformat() + "Z"}
    return Listing(
        source=slug,
        source_url=f"https://www.scpublicnotices.com/Details.aspx?ID={n['notice_id']}",
        listing_type=lt, property_kind=PropertyKind.UNKNOWN,
        state="SC", county=n["county"].strip().title(),
        city=n["city"].strip().title() or None,
        defendant=_defendant(text, kind),
        street_address=(_clean(addr_m.group(1)) if addr_m else None),
        description=(text[:200] or f"{kind} notice"),
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw=raw,
    )


class SCPublicNotices(BaseScraper):
    slug = "counties_sc.sc_public_notices"
    name = "SC Public Notices (scpublicnotices.com — foreclosure/probate/tax)"
    category = "public_notices"
    expected_min_count = 0
    requires_render = False
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            async with client(timeout=60.0) as c:
                r = await c.get(_BASE)
                session_url = str(r.url)   # cookieless session lives in the URL
                hidden = _hidden(r.text)
                for cat in _CATEGORIES:
                    data = {
                        "__EVENTTARGET": _PFX + "ddlPopularSearches", "__EVENTARGUMENT": "",
                        "__VIEWSTATE": hidden.get("__VIEWSTATE", ""),
                        "__VIEWSTATEGENERATOR": hidden.get("__VIEWSTATEGENERATOR", ""),
                        "__EVENTVALIDATION": hidden.get("__EVENTVALIDATION", ""),
                        _PFX + "ddlPopularSearches": cat,
                        _PFX + "txtSearch": "", _PFX + "rdoType": "AND", _PFX + "txtExclude": "",
                    }
                    try:
                        rp = await c.post(session_url, data=data,
                                          headers={"Content-Type": "application/x-www-form-urlencoded",
                                                   "Referer": session_url})
                        if rp.status_code != 200:
                            continue
                        for n in _parse_results(rp.text):
                            li = _to_listing(n, cat, self.slug)
                            if li:
                                out.append(li)
                        # refresh hidden fields for the next category postback
                        hidden = _hidden(rp.text) or hidden
                    except Exception:
                        log.warning("scpublicnotices.category_failed", category=cat)
        except Exception:
            log.warning("scpublicnotices.failed")
            return []
        log.info("scpublicnotices.done", leads=len(out))
        return out
