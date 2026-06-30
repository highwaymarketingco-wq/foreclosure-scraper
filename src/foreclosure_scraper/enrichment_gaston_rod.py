"""Gaston County NC Register of Deeds — free lien-existence-by-owner-name enrichment.

The Gaston ROD (gastonnc.courthousecomputersystems.com, a CourthouseComputerSystems MVC /
DevExpress app) exposes a FREE, no-login, no-CAPTCHA grantor/grantee name-index search. The grid
lists every recorded instrument for a name — deeds, deeds of trust (mortgages), judgments, liens,
tax liens, releases, satisfactions — with Date/Kind/Grantor/Grantee/Description/DocNo/Book/Page.
That is lien EXISTENCE (the dollar amount lives on the paid document image, which we never order).

WHY A COLD POST FAILS, AND THE COMPLIANT FIX (live-verified 2026-06-29 via a one-time headless
capture — no security defeated, the disclaimer is client-side jQuery UI, there is no login/CAPTCHA
on the search): POST /LRSearch/ExecuteSearch returns "Object reference not set" to a cold request
because the search context is server-side session state seeded by the DevExpress grid before the
search fires. Reconstruct it with a 3-step sequence in one cookie session:
  1. GET /                               -> ASP.NET_SessionId cookie
  2. GET /LRSearch/LRIndex?searchTabID=0 -> seeds the server-side search context for that session
  3. POST /LRSearch/ExecuteSearch        -> the name-index grid (HTML DevExpress table)
The DXScript/DXCss DevExpress tokens in the captured body are NOT required (verified) — omitting
them makes the request robust against app-version churn. One seed serves many POSTs in a session.

COMPLIANCE: public records, free, read-only index lookups; we never order or pay for images.
Name-only matching means namesakes are possible, so flags are advisory (entity owners — the bulk
of the Gaston board — match cleanly). Gated behind FORECLOSURE_GASTON_ROD=1.
"""
from __future__ import annotations

import asyncio
import os
import re
import urllib.parse

try:
    from curl_cffi.requests import AsyncSession
except Exception:  # pragma: no cover
    AsyncSession = None

BASE = "https://gastonnc.courthousecomputersystems.com"
LRINDEX = BASE + "/LRSearch/LRIndex?searchTabID=0"
EXEC = BASE + "/LRSearch/ExecuteSearch"
_HDRS = {
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": LRINDEX,
}

# Lien classification on Kind code + Description text. Gaston's Kind codes are terse:
# D/T = Deed of Trust (mortgage), SAT/CAN = satisfaction/cancellation of one, JUDG/LIEN/TAX adverse.
_MORTGAGE = re.compile(r"DEED OF TRUST|MORTGAGE|SECURITY (DEED|AGREEMENT)|\bD\s*/\s*T\b|\bDOT\b", re.I)
_ADVERSE = re.compile(r"JUDG|\bLIEN\b|\bTAX\b|EXECUTION|FORECLOS|LIS PEND|CLAIM OF|MECHANIC", re.I)

_ROW = re.compile(r'<tr id="gridTrad_DXDataRow\d+"[^>]*>(.*?)</tr>', re.S)
_CELL = re.compile(r'class="[^"]*Cell_(\w+) dxgv"[^>]*>(.*?)</td>', re.S)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def _body(last: str, first: str = "") -> str:
    p = [
        "MaxRecordCount=2000", "PageSize=200", "SortOrder=1", "IsAdvancedSearch=true",
        "ResultsAreFiltered=false", "SearchWasDirectory=false", "SearchTabID=0",
        "LRMatchContainsDefaultOn=False", "allRowsAreExpanded=false", "SearchType=3",
        "MultiNameLast%5B%5D=" + urllib.parse.quote(last),
        "MultiNameGiven%5B%5D=" + urllib.parse.quote(first),
        "MultiNameSearchType%5B%5D=3", "SearchRefDocs=false", "SimilarNameSearch=none",
        "MatchType=beginswith", "CodeType=3", "IndexType=3", "SymbolSetOut=false",
        "AdvancedDescriptionQualifier%5B%5D=%2B%2B", "AdvancedDescriptionAndOr%5B%5D=AND",
        "ResultsType=1", "ExpandAllRows=false", "HighlightSearchTermsInResults=false",
        "AutocompleteEnabled=false", "SortDirectionPrimary=1", "SortDirectionSecondary=1",
    ]
    return "&".join(p)


def parse_rows(html: str) -> list[dict]:
    """Parse the DevExpress results grid into instrument dicts."""
    rows: list[dict] = []
    for rm in _ROW.finditer(html or ""):
        cells = {}
        for cm in _CELL.finditer(rm.group(1)):
            cells[cm.group(1).lower()] = _text(cm.group(2))
        if any(cells.get(k) for k in ("grantor", "grantee", "kind")):
            rows.append(cells)
    return rows


def classify(rows: list[dict]) -> dict:
    """Summarise an owner's recorded instruments into a lien-existence signal."""
    kinds: dict[str, int] = {}
    has_mortgage = has_adverse = False
    adverse_types: set[str] = set()
    for r in rows:
        k = (r.get("kind") or "").strip().upper()
        if k:
            kinds[k] = kinds.get(k, 0) + 1
        blob = f"{k} {r.get('description', '')}"
        if _MORTGAGE.search(blob):
            has_mortgage = True
        if _ADVERSE.search(blob):
            has_adverse = True
            m = _ADVERSE.search(blob)
            if m:
                adverse_types.add(m.group(0).upper())
    return {
        "instrument_count": len(rows),
        "kinds": kinds,
        "has_mortgage": has_mortgage,
        "has_adverse_lien": has_adverse,
        "adverse_types": sorted(adverse_types),
        "source": "gaston_rod",
    }


async def _seed(session) -> bool:
    try:
        await session.get(BASE + "/", impersonate="chrome", timeout=20)
        await session.get(LRINDEX, impersonate="chrome", timeout=20)
        return True
    except Exception:
        return False


async def search_instruments(session, last: str, first: str = "") -> list[dict]:
    """Run ExecuteSearch for a name on an already-seeded session; returns parsed rows."""
    if not last:
        return []
    try:
        r = await session.post(EXEC, data=_body(last, first), headers=_HDRS,
                               impersonate="chrome", timeout=45)
    except Exception:
        return []
    if r.status_code != 200 or "Object reference" in (r.text or ""):
        return []
    return parse_rows(r.text)


def _name_parts(owner: str):
    """('SMITH, JOHN') -> ('SMITH','JOHN'); entity names pass through as last-only."""
    o = re.sub(r"\s+", " ", (owner or "").strip())
    if "," in o:
        a, b = o.split(",", 1)
        return a.strip(), b.strip().split(" ")[0]
    return o, ""


async def enrich_gaston_rod(listings, max_lookups: int | None = None) -> dict:
    """For NC/Gaston leads with an owner_name, attach raw['rod'] lien-existence summary.
    Gated by FORECLOSURE_GASTON_ROD=1 (network). One seeded session serves all lookups."""
    if AsyncSession is None or os.environ.get("FORECLOSURE_GASTON_ROD") != "1":
        return {"skipped": "gated (set FORECLOSURE_GASTON_ROD=1)"}
    targets = [li for li in listings
               if li.state == "NC" and (li.county or "").strip().upper().replace(" COUNTY", "") == "GASTON"
               and li.owner_name and not (isinstance(li.raw, dict) and "rod" in li.raw)]
    if max_lookups:
        targets = targets[:max_lookups]
    stats = {"targets": len(targets), "searched": 0, "with_instruments": 0,
             "with_mortgage": 0, "with_adverse": 0}
    if not targets:
        return stats
    async with AsyncSession(verify=False) as s:
        if not await _seed(s):
            return {**stats, "error": "seed_failed"}
        for li in targets:
            last, first = _name_parts(li.owner_name)
            rows = await search_instruments(s, last, first)
            stats["searched"] += 1
            if not rows:
                continue
            summary = classify(rows)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["rod"] = summary
            stats["with_instruments"] += 1
            if summary["has_mortgage"]:
                stats["with_mortgage"] += 1
            if summary["has_adverse_lien"]:
                stats["with_adverse"] += 1
            await asyncio.sleep(0.4)
    return stats
