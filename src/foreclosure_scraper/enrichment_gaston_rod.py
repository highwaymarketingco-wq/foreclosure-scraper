"""Gaston County NC Register of Deeds — free lien-existence-by-owner-name enrichment.

The Gaston ROD (gastonnc.courthousecomputersystems.com, a CourthouseComputerSystems MVC /
DevExpress app) exposes a FREE, no-login, no-CAPTCHA grantor/grantee name-index search. The grid
lists every recorded instrument for a name — deeds, deeds of trust (mortgages), judgments, liens,
tax liens, releases, satisfactions — with Date/Kind/Grantor/Grantee/Description/DocNo/Book/Page.
That is lien EXISTENCE (the dollar amount lives on the paid document image, which we never order).

WHY A COLD POST FAILS, AND THE COMPLIANT FIX (originally live-verified 2026-06-29 via a one-time
headless capture — no security defeated, the disclaimer is client-side jQuery UI, there is no
login/CAPTCHA on the search): POST /LRSearch/ExecuteSearch returns "Object reference not set" to a
cold request because the search context is server-side session state seeded by the DevExpress grid
before the search fires. Reconstruct it with a 3-step sequence in one cookie session:
  1. GET /                               -> ASP.NET_SessionId cookie
  2. GET /LRSearch/LRIndex?searchTabID=0 -> seeds the server-side search context for that session
  3. POST /LRSearch/ExecuteSearch        -> the name-index grid (HTML DevExpress table)
The DXScript/DXCss DevExpress tokens in the captured body are NOT required (verified) — omitting
them makes the request robust against app-version churn. One seed serves many POSTs in a session.

FOUND 2026-11-24: the host is now Cloudflare-walled (a Turnstile "Just a moment" challenge at the
ROOT page, confirmed live — a plain curl_cffi Chrome-impersonation GET gets HTTP 403). This module
is Default-ON in production, so it has very likely been silently returning zero lien-existence
data for every Gaston board owner since Cloudflare's posture changed sometime after the original
June verification — nothing surfaced the gap because a walled seed just reports `error: "walled"`
in the stats dict, which nothing alerts on. FIX: `scrapling.fetchers.StealthyFetcher` with
`solve_cloudflare=True` (already proven elsewhere in this codebase, e.g.
`scrapers/counties_nc/nc_ecourts_estates.py`, for a different wall) solves this Turnstile
challenge. The 3-step request sequence above still works UNCHANGED once past it — confirmed live,
200 real instrument rows for a test name — but it now has to run as in-page `fetch()` calls from
inside that solved browser page (a fresh curl_cffi session would hit the exact same wall this file
was built to get past in the first place). `_seed()`/`search_instruments()` below are unchanged:
they only need something that quacks like a `.get()`/`.post()` session, which `_PageSession` gives
them. See docs/notes/gaston_rod_cloudflare_bypass_proven_2026-11-24.md for the full investigation.

COMPLIANCE: public records, free, read-only index lookups; we never order or pay for images.
Name-only matching means namesakes are possible, so flags are advisory (entity owners — the bulk
of the Gaston board — match cleanly). Gated behind FORECLOSURE_GASTON_ROD=1.
"""
from __future__ import annotations

import asyncio
import os
import re
import urllib.parse

_WALL_TITLE = re.compile(
    r"<title>[^<]*(?:Just a moment|Attention Required|Access Denied|log ?in|sign ?in)", re.I)
_WALL_MARKER = re.compile(r"g-recaptcha|h-captcha|cf-browser-verification", re.I)


class GastonWall(Exception):
    """The host answered with a 403, a Cloudflare challenge or a login page. That
    host is done for this run: never retry it and never burn the rest of the budget."""


def _wall_reason(status: int, text: str) -> str | None:
    if status in (401, 403, 407, 429, 503):
        return f"HTTP {status}"
    head = (text or "")[:6000]
    if _WALL_TITLE.search(head) or _WALL_MARKER.search(head):
        return "challenge, CAPTCHA or login page"
    return None


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


class _PageResp:
    """Duck-types curl_cffi's response just enough for _wall_reason()/_seed()/
    search_instruments() (.status_code, .text)."""
    __slots__ = ("status_code", "text")

    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class _PageSession:
    """Adapts an already-Cloudflare-solved Playwright page to the same
    .get()/.post() interface curl_cffi's AsyncSession gave _seed()/
    search_instruments() -- so neither function (nor their existing tests,
    which mock exactly this interface) needs to change. Every request runs as
    an in-page fetch() so it carries the page's own solved session/cookies; a
    fresh curl_cffi session here would hit the same Cloudflare wall
    StealthyFetcher was needed for in the first place."""

    def __init__(self, page):
        self._page = page

    async def get(self, url, **_kw):
        r = await self._page.evaluate(
            """async (url) => {
                const resp = await fetch(url, {credentials: 'include'});
                return {status: resp.status, text: await resp.text()};
            }""",
            url,
        )
        return _PageResp(r["status"], r["text"])

    async def post(self, url, **kw):
        data = kw.get("data", "")
        headers = kw.get("headers") or {}
        r = await self._page.evaluate(
            """async ([url, body, headers]) => {
                const resp = await fetch(url, {
                    method: 'POST', credentials: 'include', headers, body,
                });
                return {status: resp.status, text: await resp.text()};
            }""",
            [url, data, headers],
        )
        return _PageResp(r["status"], r["text"])


async def _run_stealthy(page_action) -> None:
    """Launch one Cloudflare-solved browser session and run `page_action(page)`
    inside it. A thin, monkeypatchable seam -- tests replace this instead of
    launching a real browser."""
    from scrapling.fetchers import StealthyFetcher
    await StealthyFetcher.async_fetch(
        BASE + "/",
        headless=True,
        network_idle=True,
        timeout=60000,
        page_action=page_action,
        solve_cloudflare=True,
        wait=5000,
    )


async def _seed(session) -> bool:
    """Seed the search context. Raises GastonWall on a Cloudflare challenge/block so the
    caller can stop immediately instead of treating a 403 page as 'seeded successfully'."""
    try:
        r1 = await session.get(BASE + "/", impersonate="chrome", timeout=20)
        reason = _wall_reason(r1.status_code, r1.text)
        if reason:
            raise GastonWall(f"seed GET /: {reason}")
        r2 = await session.get(LRINDEX, impersonate="chrome", timeout=20)
        reason = _wall_reason(r2.status_code, r2.text)
        if reason:
            raise GastonWall(f"seed GET LRIndex: {reason}")
        return True
    except GastonWall:
        raise
    except Exception:
        return False


async def search_instruments(session, last: str, first: str = "") -> list[dict]:
    """Run ExecuteSearch for a name on an already-seeded session; returns parsed rows.
    Raises GastonWall if the session hits a Cloudflare challenge/block mid-run (distinct
    from a genuine zero-match or a transient parse miss, neither of which should stop the
    run)."""
    if not last:
        return []
    try:
        r = await session.post(EXEC, data=_body(last, first), headers=_HDRS,
                               impersonate="chrome", timeout=45)
    except Exception:
        return []
    reason = _wall_reason(r.status_code, r.text)
    if reason:
        raise GastonWall(f"ExecuteSearch: {reason}")
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
    Gated by FORECLOSURE_GASTON_ROD=1 (network). One Cloudflare-solved browser session
    serves all lookups (see _run_stealthy/_PageSession and the 2026-11-24 note above)."""
    # Default-ON so every future run captures ROD lien-existence; set FORECLOSURE_GASTON_ROD=0 to skip.
    if os.environ.get("FORECLOSURE_GASTON_ROD", "1") == "0":
        return {"skipped": "disabled (FORECLOSURE_GASTON_ROD=0)"}
    targets = [li for li in listings
               if li.state == "NC" and (li.county or "").strip().upper().replace(" COUNTY", "") == "GASTON"
               and li.owner_name and not (isinstance(li.raw, dict) and "rod" in li.raw)]
    if max_lookups:
        targets = targets[:max_lookups]
    stats = {"targets": len(targets), "searched": 0, "with_instruments": 0,
             "with_mortgage": 0, "with_adverse": 0}
    if not targets:
        return stats

    async def page_action(page):
        session = _PageSession(page)
        try:
            if not await _seed(session):
                stats["error"] = "seed_failed"
                return
        except GastonWall as exc:
            stats["error"] = "walled"
            stats["wall_reason"] = str(exc)
            return
        for li in targets:
            last, first = _name_parts(li.owner_name)
            try:
                rows = await search_instruments(session, last, first)
            except GastonWall as exc:
                # Stop burning the rest of the run's budget on guaranteed-failing lookups;
                # the rows already attempted stand as real results.
                stats["error"] = "walled"
                stats["wall_reason"] = str(exc)
                return
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

    try:
        await _run_stealthy(page_action)
    except Exception as exc:  # noqa: BLE001 -- browser launch/navigation failure
        if "error" not in stats:
            stats["error"] = "fetch_failed"
            stats["wall_reason"] = str(exc)[:200]
    return stats
