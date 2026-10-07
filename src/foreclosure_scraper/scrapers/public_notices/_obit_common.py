"""Shared pieces for the obituary readers (obituary_feeds.py, echovita_obituaries.py).

POLITE BY CONSTRUCTION. PoliteFetcher keeps at least MIN_GAP_S (1.6 s) between two requests to the
same host, sends an ordinary desktop-browser User-Agent and nothing else (no TLS impersonation, no
proxy, no cookie or token other than what an ordinary page load sets), and checks every answer
for a wall: a CAPTCHA, a login form, a challenge page, HTTP 401/402/403/407/429. A wall raises
Walled; the reader records the host as walled and stops asking it for the rest of the run.

One note on the wall check. Some sites (Echovita, Find a Grave) include Cloudflare's passive
bot-detection script (/cdn-cgi/challenge-platform/scripts/jsd/...) on ordinary, fully served
pages. That script presents nothing and blocks nothing: the page's content is there. It is not a
challenge, so it is not counted as one. A real challenge page ('Just a moment...', a cf-chl form,
a CAPTCHA widget, a 403) still is.

ROW SHAPE. One Listing per obituary, the same shape the existing obituary scrapers use
(PROBATE_NOTICE, decedent as owner_name/defendant, raw['obituary'], life_event 'death',
dateless). PRIVACY: raw['obituary'] (published) carries the decedent, dates, residence, publisher
and COUNTS of survivors only; the parsed survivor names ride in raw['obituary_private'], which is
not in RAW_KEEP and never reaches the public board (enrichment_obituary_match copies it into the
gitignored private store).
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

import httpx
import structlog

from ...models import Listing, ListingType, PropertyKind
from ...obituary_text import clean_text, parse_obituary_lede, parse_survivors
from ...quiet_title.fetch import HEADERS, Walled, detect_wall

log = structlog.get_logger()

MIN_GAP_S = 1.6
_PASSIVE_JSD = re.compile(r"/cdn-cgi/challenge-platform/scripts/jsd/[^\"'\s<>]*|challenge-platform/scripts/jsd/[^\"'\s<>]*")


_FORM = re.compile(r"(?is)<form\b[^>]*>.*?</form>")


def wall_reason(status: int, final_url: str, text: str, content_rx: Optional[re.Pattern] = None) -> Optional[str]:
    """detect_wall, with two narrow exceptions on a page that was SERVED (HTTP 200, no challenge
    interstitial):
      * Cloudflare's passive detection script is not a wall;
      * a CAPTCHA widget inside a <form> (Echovita's 'share this obituary by e-mail' form, a
        WordPress comment form) is not a wall WHEN the page also carries the content we came for
        outside any form (`content_rx`). Those forms are never submitted. A CAPTCHA that stands in
        front of the content (no content outside the form) is still a wall."""
    t = text or ""
    if status == 200 and "Just a moment" not in t[:5000]:
        t = _PASSIVE_JSD.sub(" ", t)
        if content_rx is not None:
            outside = _FORM.sub(" ", t)
            if content_rx.search(outside):
                t = outside
    return detect_wall(status, final_url, t)


class PoliteFetcher:
    """Async GET with a per-host gap, an ordinary UA, and the wall check. One per scraper run."""

    def __init__(self, *, min_gap_s: float = MIN_GAP_S, timeout: float = 30.0) -> None:
        self.min_gap_s = min_gap_s
        self.timeout = timeout
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.walled: dict[str, str] = {}
        self.requests: dict[str, int] = {}
        self.last_url = ""
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "PoliteFetcher":
        self._client = httpx.AsyncClient(headers=dict(HEADERS), follow_redirects=True,
                                         timeout=httpx.Timeout(self.timeout, connect=10.0))
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _pace(self, host: str) -> None:
        lk = self._locks.setdefault(host, asyncio.Lock())
        async with lk:
            last = self._last.get(host)
            if last is not None:
                wait = self.min_gap_s - (time.monotonic() - last)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def get(self, url: str, params: Optional[dict] = None,
                  content_rx: Optional[re.Pattern] = None) -> str:
        host = (urlsplit(url).hostname or "").lower()
        if host in self.walled:
            raise Walled(url, self.walled[host])
        await self._pace(host)
        self.requests[host] = self.requests.get(host, 0) + 1
        assert self._client is not None, "use 'async with PoliteFetcher()'"
        r = await self._client.get(url, params=params)
        why = wall_reason(r.status_code, str(r.url), r.text, content_rx)
        if why:
            self.walled[host] = why
            log.warning("obituary_reader.walled", host=host, reason=why)
            raise Walled(url, why)
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
        self.last_url = str(r.url)
        return r.text


    async def post(self, url: str, data: dict) -> str:
        """A form postback (an ASP.NET grid's own next-page / preset button), same pacing and wall
        check as get(). Only the site's own public search form is ever posted."""
        host = (urlsplit(url).hostname or "").lower()
        if host in self.walled:
            raise Walled(url, self.walled[host])
        await self._pace(host)
        self.requests[host] = self.requests.get(host, 0) + 1
        assert self._client is not None, "use 'async with PoliteFetcher()'"
        r = await self._client.post(url, data=data)
        why = wall_reason(r.status_code, str(r.url), r.text)
        if why:
            self.walled[host] = why
            log.warning("obituary_reader.walled", host=host, reason=why)
            raise Walled(url, why)
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
        self.last_url = str(r.url)
        return r.text

    async def get_with_url(self, url: str) -> tuple[str, str]:
        """get(), also returning the final URL (a session-in-path site redirects)."""
        text = await self.get(url)
        return text, self.last_url


_TITLE_NOISE = re.compile(r"^\s*(?:obituary|obituaries|in\s+memory\s+of|in\s+loving\s+memory\s+of)\s*[:\-|]\s*|"
                          r"\s*[\-|:]\s*(?:obituary|obituaries)\s*$|\s*\|\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$", re.I)


def decedent_from_title(title: str) -> Optional[str]:
    """'Obituary: Velma Juno Crisp, 87' / 'Velma Juno Crisp | 09/30/2026' -> 'Velma Juno Crisp'."""
    t = clean_text(title)
    t = _TITLE_NOISE.sub("", t).strip()
    t = re.split(r",\s*(?:age\s+)?\d{1,3}\b|\s+\(\d{4}\s*-\s*\d{4}\)|\s+\d{4}\s*-\s*\d{4}\s*$", t)[0]
    t = re.sub(r"\s+", " ", t).strip(" ,-|")
    words = t.split()
    if len(words) < 2 or len(words) > 7 or any(ch.isdigit() for ch in t):
        return None
    if not re.match(r"^[A-Z]", t):
        return None
    for w in words:
        core = w.strip(".,'\"()")
        if core.lower() in _PARTICLES:
            continue
        if not core or not core[0].isupper() or core.upper() in _NOT_NAME:
            return None
    return t


_PARTICLES = {"de", "da", "del", "della", "der", "di", "du", "la", "le", "van", "von", "st"}
_NOT_NAME = {
    "BOARD", "COUNCIL", "COUNTY", "CITY", "TOWN", "MEETING", "MEETS", "NEWS", "UPDATE", "NOTICE", "NOTICES",
    "CHURCH", "SCHOOL", "SCHOOLS", "OBITUARIES", "OBITUARY", "FUNERAL", "SERVICES", "SERVICE", "MEMORIAL",
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY", "WEEK", "TODAY", "THE",
    "AND", "FOR", "WITH", "FROM", "COMMISSIONERS", "POLICE", "SHERIFF", "STATE", "HIGH", "PARK", "CLUB",
    "DEPARTMENT", "FIRE", "ANNUAL", "CELEBRATION", "REMEMBERING", "TRIBUTE", "LETTER", "EDITOR",
}
_DEATH_WORDS = re.compile(r"\b(?:died|passed\s+away|passed|death|survived|surviving|funeral|memorial|obituary|"
                          r"went\s+(?:home|to\s+be)|entered|departed|age\s+\d|,\s*\d{1,3},|years?\s+old|born)\b", re.I)


def looks_like_obituary(text: str) -> bool:
    return bool(_DEATH_WORDS.search(clean_text(text or "")))


def obituary_listing(*, source: str, url: str, decedent: str, state: str, county: Optional[str],
                     publisher: str, text: str = "", residence_city: Optional[str] = None,
                     age: Optional[int] = None, birth_date: Optional[str] = None,
                     death_date: Optional[str] = None, published: Optional[str] = None,
                     extra_public: Optional[dict] = None) -> Listing:
    """One obituary -> one Listing (see module docstring for what is public and what is not)."""
    now = datetime.utcnow()
    body = clean_text(text) if text else ""
    lede = parse_obituary_lede(body) if body else {}
    surv = parse_survivors(body) if body else {"survivors": [], "unnamed": [], "predeceased": [], "clauses": 0}
    age = age or lede.get("age")
    residence_city = residence_city or lede.get("residence")
    public = {
        "decedent": decedent, "state": state, "county": county, "url": url, "source": source,
        "publisher": publisher, "age": age, "birth_date": birth_date, "death_date": death_date or
        lede.get("death_date_text"), "residence_city": residence_city, "pub_date": published,
        "survivor_names_parsed": len(surv["survivors"]),
        "has_survivor_list": bool(surv["clauses"]),
    }
    if extra_public:
        public.update(extra_public)
    public = {k: v for k, v in public.items() if v not in (None, "")}
    private = {"survivors": surv["survivors"], "unnamed": surv["unnamed"],
               "predeceased": surv["predeceased"], "residence": residence_city,
               "death_date_text": lede.get("death_date_text"), "birth_date_text": lede.get("birth_date_text")}
    private = {k: v for k, v in private.items() if v not in (None, "", [])}
    where = f"{county} County {state}" if county else state
    return Listing(
        source=source,
        source_url=url,
        listing_type=ListingType.PROBATE_NOTICE,
        property_kind=PropertyKind.UNKNOWN,
        state=state, county=county,
        city=residence_city or None,
        defendant=decedent,
        owner_name=decedent,
        description=(f"Obituary (death) - {decedent}" + (f", age {age}" if age else "") +
                     f", {where} - pre-probate heir/estate signal ({publisher})")[:300],
        first_seen=now, last_seen=now,
        raw={
            "obituary": public,
            "obituary_private": private,
            "life_event": "death",
            "dateless": True,
            "relationship_signal": {"kind": "probate", "keyword": "obituary"},
        },
    )
