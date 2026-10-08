"""Gannett obituaries (W-NC + Upstate-SC) — pre-probate heir leads.

A property owner's DEATH is the earliest motivated-seller signal in the estate
funnel: it surfaces weeks before a probate creditor-notice publishes, and it also
catches estates that never formally probate. The Gannett (USA Today network) local
papers across the core footprint publish their daily obituaries as plain server-
rendered HTML (the Tukios platform), one ``/obituaries/<decedent-name-slug>`` link
per death — free, no login, no WAF:

  Western NC : citizen-times.com=Buncombe (Asheville), blueridgenow.com=Henderson,
               gastongazette.com=Gaston, shelbystar.com=Cleveland,
               thedigitalcourier.com=Rutherford
  Upstate SC : goupstate.com=Spartanburg, greenvilleonline.com=Greenville,
               independentmail.com=Anderson

One name-only lead per decedent (slug -> name). The name->property resolver then
pins the decedent's parcel via the county GIS owner-name index (same path as the
Spartan Weekly probate notices); decedents who owned property in-county become real
heir/estate leads, the rest stay unresolved name-only and carry no value.

Per-decedent DETAIL fetch (added 2026-10-01; extraction_gaps.md: "gannett_obituaries
never fetches the per-decedent detail (age/funeral-home/survivors)"): the detail page
at /obituaries/<slug> is a heavy client-side (Tukios) app whose RENDERED DOM never
actually surfaces the obituary narrative even after a full stealth-browser render
(live-checked) -- but the server-rendered <meta name="description"> tag on the SAME
plain-HTTP response already carries the lede sentence verbatim, e.g. "Darlene Rice
Honeycutt, 80, of Asheville, North Carolina, passed away on September 26, 2026. Born
on January 22, 1946, she was the daughter of..." -- AGE, city, and a death/service
date, sometimes a literal street address ("Jerry Deal, 92, of 11 Elk Mountain Road,
died on..."), no stealth browser needed, no extra tooling. One additional plain GET
per decedent (~0.8s observed), gated by _DETAIL_MAX so a paper with an unusually
long list can't blow the timeout. Failures are per-decedent and non-fatal: the
list-only Listing (name + slug) this scraper always produced is still emitted.

Free, public, plain-HTTP. Gate off with FORECLOSURE_OBITUARIES=0, or the detail
fetch alone with FORECLOSURE_OBIT_DETAIL=0 (keeps the name-only list behavior).

EXTRACTION-COMPLETENESS AUDIT FINDING (2026-10-04, final batch): despite its
own docstring above claiming all 8 papers are "Gannett... the Tukios
platform," ``thedigitalcourier.com`` is NOT -- it is a TownNews/BLOX (TNCMS)
site, confirmed live by its real URL shapes (``/archives/<slug>/
article_<uuid>.html``, not Tukios' ``/obituaries/<slug>``) and its RSS
search endpoint. The static ``/obituaries/`` list page this scraper fetches
for every host renders only the SINGLE most-recent obituary server-side for
this one host (TownNews lazy-loads the rest client-side); the other 7 real
Tukios hosts correctly render ~20 each. Live-confirmed 2026-10-04: this
host's own TownNews RSS feed (``/search/?f=rss&t=article&c=obituaries&
l=50``) carries 50 real current obituaries -- a 98% miss (1 of 50) on every
run since this scraper existed, on a REAL 18-county-footprint source
(Rutherford NC). The RSS item is also strictly richer than the Tukios path
for this host: the full obituary lede + age/city is already in the feed's
own ``<description>`` (no extra per-decedent GET needed, unlike the Tukios
``_fetch_detail`` path) and each item carries a real `<enclosure>` photo URL
TownNews serves directly. Routed this one host through its RSS feed instead
of the Tukios HTML-list path; ``_AGE_FROM_DESC_RE`` extended (one optional
"age " token) to also match TownNews' "Name, age 89, of City..." phrasing
alongside the existing Tukios "Name, 80, of City..." shape -- both now share
``_parse_detail_description()`` unchanged otherwise.

SOURCE-COMPLETENESS AUDIT (2026-10-08): 39 rows on the VM's gated run, down from
~140 a run before the detail fetch (2026-10-01) and 89-90 since. On that run the
last two papers in PAPERS (greenvilleonline.com, independentmail.com) answered 429
to their LIST page, after ~100 detail GETs to the other papers, and three more
list fetches failed; all five papers' rows were lost, not just their detail. One
ordinary request from the Mac the same day got 200 from all three list pages
probed, so this is the papers throttling our run's volume, not a wall. Now every
list page is read first and each decedent becomes a row at once (also into
self.partial); the detail pass runs afterwards, round-robin across papers and
time-boxed (_DETAIL_BUDGET_S). Every request to the papers, list or detail, is
spaced by _GAP_S whatever the host (they share one rate-limited edge: live from
the Mac the old loop drew 429 on 5 of 7 list pages within about 3 s), and the
first 429 stops the Gannett pass for the run (a 402/403/429 on a detail page
stops the detail pass); nothing is retried. A throttled run costs detail fields
and the papers not yet read, never rows already read.
"""
from __future__ import annotations

import asyncio
import html
import os
import re
import time
from datetime import datetime
from typing import Iterable

import feedparser
import structlog

from ...base_scraper import BaseScraper
from ...http_client import client, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# Gannett local paper host -> (county, state) it covers, across the core footprint.
PAPERS = {
    "citizen-times.com": ("Buncombe", "NC"),
    "blueridgenow.com": ("Henderson", "NC"),
    "gastongazette.com": ("Gaston", "NC"),
    "shelbystar.com": ("Cleveland", "NC"),
    "thedigitalcourier.com": ("Rutherford", "NC"),
    "goupstate.com": ("Spartanburg", "SC"),
    "greenvilleonline.com": ("Greenville", "SC"),
    "independentmail.com": ("Anderson", "SC"),
}

# Hosts in PAPERS that are actually TownNews (NOT Tukios) -- see the module
# docstring's 2026-10-04 finding. Routed through _fetch_townnews_rss()
# instead of the Tukios /obituaries/ list-page path.
_TOWNNEWS_RSS_HOSTS = {"thedigitalcourier.com"}


def _townnews_rss_url(host: str) -> str:
    return f"https://www.{host}/search/?f=rss&t=article&c=obituaries&l=50&s=start_time&sd=desc"

_SLUG_RE = re.compile(r'/obituaries/([a-z][a-z0-9]+-[a-z0-9-]{2,40})(?=["/?])')
_NOISE = ("daily-digest", "privacy", "terms", "how-to", "self-service", "faq",
          "place-an", "frequently", "submit")
_SUFFIX = {"jr": "Jr.", "sr": "Sr.", "ii": "II", "iii": "III", "iv": "IV"}

# Per-paper cap on detail fetches, so one unusually long list can't blow the
# scraper's timeout_s. ~20/paper observed live -- 2x headroom.
_DETAIL_MAX = int(os.environ.get("FORECLOSURE_OBIT_DETAIL_MAX", "40"))
#: Wall-clock budget for the whole detail pass (all papers), well inside timeout_s.
_DETAIL_BUDGET_S = float(os.environ.get("FORECLOSURE_OBIT_DETAIL_BUDGET_S", "170"))
#: Minimum gap between ANY two requests to the Gannett papers (list or detail, any host).
#: The 7 Tukios papers sit behind one shared edge that rate-limits per client IP across
#: all of them: live 2026-10-08 from the Mac, the old loop (list page, detail page, next
#: paper, no wait between different hosts) drew HTTP 429 on 5 of 7 list pages within
#: about 3 seconds. The per-host throttle in http_client never spaces different hosts.
_GAP_S = float(os.environ.get("FORECLOSURE_OBIT_GAP_S", "3.0"))
#: A detail page answering one of these means the papers are throttling or refusing us:
#: the detail pass stops for the run (never retried, never hammered); list rows stay.
_STOP_DETAIL_STATUSES = frozenset({402, 403, 429})


class _Pacer:
    """Spaces requests to the shared Gannett edge by _GAP_S, whatever the host."""

    def __init__(self) -> None:
        self._last: float | None = None

    async def wait(self) -> None:
        gap = _GAP_S
        if self._last is not None and gap > 0:
            d = gap - (time.monotonic() - self._last)
            if d > 0:
                await asyncio.sleep(d)
        self._last = time.monotonic()

_META_DESC_RE = re.compile(
    r'<meta\s+name="description"\s+content="([^"]*)"', re.I
)
# "Darlene Rice Honeycutt, 80, of Asheville, ..." (Tukios) / "Jerry Deal, 92,
# of 11 Elk Mountain Road, ..." (Tukios) / "Charles E. Smith, age 89, of
# Ellenboro, ..." (TownNews, live-confirmed 2026-10-04 on thedigitalcourier.com's
# own RSS <description> -- same shape, one extra "age " token) -- the
# decedent's own name repeats the slug-derived name, age is the first bare
# integer after the first comma, optionally preceded by the literal word "age".
_AGE_FROM_DESC_RE = re.compile(r"^[^,]+,\s*(?:age\s+)?(\d{1,3}),", re.I)
# "passed away on September 26, 2026" / "died on Wednesday, September 30, 2026"
_DEATH_DATE_RE = re.compile(
    r"(?:passed away|died)(?:\s+on)?\s+(?:[A-Z][a-z]+,\s+)?"
    r"([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})"
)
# A literal street address sometimes IS the decedent's own home, e.g.
# "Jerry Deal, 92, of 11 Elk Mountain Road, died on ..." -- distinct from a
# city-only "of Asheville, North Carolina,". Conservative: requires a leading
# house number and a common street-suffix word so a bare city name never
# matches.
_HOME_ADDRESS_RE = re.compile(
    r"\bof\s+(\d[\w .'-]*?\b(?:road|rd|street|st|drive|dr|lane|ln|avenue|ave|"
    r"boulevard|blvd|highway|hwy|circle|cir|court|ct|way|place|pl|trail|trl|"
    r"parkway|pkwy|terrace|ter|loop)\b)\s*,",
    re.I,
)
# Service/venue line, when the (short, truncated) description reaches it:
# "will be held at 11 AM on Wednesday, October 3, at Ashelawn Garden..."
_SERVICE_VENUE_RE = re.compile(
    r"\b(?:service|services|visitation|funeral)\b.{0,80}?\bat\s+([A-Z][\w .'&-]{3,60})",
    re.I,
)


def _parse_detail_description(desc: str) -> dict:
    """Pull age / death_date / home_address / service_venue out of the
    decedent's own meta description text (server-rendered, no JS needed).
    Best-effort -- any field it can't recover is simply absent."""
    text = html.unescape(desc or "").strip()
    out: dict = {}
    if not text:
        return out
    am = _AGE_FROM_DESC_RE.match(text)
    if am:
        try:
            age = int(am.group(1))
            if 1 <= age <= 120:
                out["age"] = age
        except (TypeError, ValueError):
            pass
    dm = _DEATH_DATE_RE.search(text)
    if dm:
        out["death_date_text"] = dm.group(1).strip()
    hm = _HOME_ADDRESS_RE.search(text)
    if hm:
        out["home_address"] = re.sub(r"\s+", " ", hm.group(1)).strip(" ,.")
    sm = _SERVICE_VENUE_RE.search(text)
    if sm:
        out["service_venue"] = re.sub(r"\s+", " ", sm.group(1)).strip(" ,.")
    out["summary"] = text[:500]
    return out


async def _fetch_detail_status(c, url: str) -> tuple[int | None, dict]:
    """(HTTP status or None on a network error, parsed meta-description fields). Never
    raises -- a bad detail fetch must not cost the list-only lead this scraper already had."""
    try:
        r = await c.get(url)
        if r.status_code != 200:
            return r.status_code, {}
        m = _META_DESC_RE.search(r.text)
        if not m:
            return 200, {}
        return 200, _parse_detail_description(m.group(1))
    except Exception as exc:  # noqa: BLE001
        log.info("obituaries.detail_failed", url=url, error=str(exc)[:140])
        return None, {}


async def _fetch_detail(c, url: str) -> dict:
    """One plain GET for a decedent's detail page; returns the parsed meta
    description fields, or {} on any failure (never raises)."""
    return (await _fetch_detail_status(c, url))[1]


_TOWNNEWS_ARTICLE_ID_RE = re.compile(r"article_([0-9a-f-]+)\.html", re.I)


def _obit_description(name: str, county: str, state: str, age) -> str:
    desc_bits = [f"Obituary (death) — {name}"]
    if age:
        desc_bits.append(f"age {age}")
    desc_bits.append(f"{county} County {state} — pre-probate heir/estate signal")
    return ", ".join(desc_bits)[:300]


def _apply_detail(li: Listing, detail: dict) -> None:
    """Merge a decedent's detail fields into its row (in place)."""
    if not detail:
        return
    obituary = li.raw["obituary"]
    obituary.update(detail)
    li.description = _obit_description(obituary["decedent"], obituary["county"],
                                       obituary["state"], detail.get("age"))
    # A literal home address found in the obituary text IS the decedent's own
    # situs — skip the name->parcel resolver entirely and anchor the lead
    # directly, same value a resolved parcel gives, for free.
    home_addr = detail.get("home_address")
    if home_addr:
        li.street_address = home_addr
        obituary["home_address_used_as_situs"] = True


def _build_obit_listing(
    source_slug: str,
    slug_or_id: str,
    name: str,
    detail_url: str,
    host: str,
    county: str,
    state: str,
    detail: dict,
    now: datetime,
) -> Listing:
    """Shared Listing-builder for both the Tukios (/obituaries/<slug> + a
    per-decedent detail GET) and TownNews (RSS item, detail already in hand)
    paths -- same raw shape either way."""
    obituary = {"decedent": name, "slug": slug_or_id,
                "paper": host, "county": county, "state": state}
    li = Listing(
        source=source_slug,
        source_url=detail_url,
        listing_type=ListingType.PROBATE_NOTICE,
        property_kind=PropertyKind.UNKNOWN,
        state=state, county=county,
        defendant=name,  # decedent -> resolver pins parcel by owner-name
        description=_obit_description(name, county, state, None),
        first_seen=now, last_seen=now,
        raw={
            "obituary": obituary,
            "life_event": "death",
            "relationship_signal": {"kind": "probate",
                                    "keyword": "obituary"},
        },
    )
    _apply_detail(li, detail)
    return li


async def _fetch_townnews_host(
    host: str, county: str, state: str, now: datetime, source_slug: str,
) -> list[Listing]:
    """TownNews path (currently just thedigitalcourier.com -- see module
    docstring's 2026-10-04 finding). The RSS item already carries the full
    lede (age/city/death-date in <description>) and a real photo
    (<enclosure>), so unlike the Tukios path this needs NO extra per-decedent
    GET -- strictly cheaper AND far more complete (50 real rows vs. the 1 the
    static /obituaries/ list page server-renders for this host).

    Fetched independently of the Tukios loop's shared plain-httpx client via
    ``get_text(..., impersonate=True)``: live-confirmed 2026-10-04 this
    host's TownNews search endpoint 429s plain httpx fairly readily (shared
    with the newspapers.* TownNews sources' own documented rate-limiting)
    but a real Chrome TLS fingerprint gets a clean 200 reliably."""
    out: list[Listing] = []
    url = _townnews_rss_url(host)
    try:
        text = await get_text(url, timeout=20.0, impersonate=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("obituaries.townnews_fetch_failed", host=host, error=str(exc)[:140])
        return out

    parsed = feedparser.parse(text)
    for e in parsed.entries:
        name = (getattr(e, "title", "") or "").strip()
        if len(name) < 5 or name.replace(" ", "").isdigit() or " " not in name:
            continue
        link = (getattr(e, "link", "") or "").strip()
        if not link:
            continue
        summary = getattr(e, "summary", "") or ""
        detail = _parse_detail_description(summary)

        idm = _TOWNNEWS_ARTICLE_ID_RE.search(link)
        slug_or_id = idm.group(1) if idm else name

        li = _build_obit_listing(
            source_slug, slug_or_id, name, link, host, county, state, detail, now,
        )
        # The RSS <enclosure> is a real, directly-fetchable photo URL --
        # confirmed live (bloximages.newyork1.vip.townnews.com, image/jpeg).
        encs = getattr(e, "enclosures", None) or []
        if encs:
            href = (encs[0].get("href") or "").strip()
            if href.startswith("http"):
                li.raw["images"] = {"real": [href]}
        out.append(li)
    log.info("obituaries.townnews_county", host=host, county=county, kept=len(out))
    return out


def _name_from_slug(slug: str) -> str:
    parts = slug.split("-")
    # drop trailing numeric disambiguators the platform appends: sara-moore-2026-1
    while parts and parts[-1].isdigit():
        parts.pop()
    out = []
    for p in parts:
        if p in _SUFFIX:
            out.append(_SUFFIX[p])
        elif len(p) == 1:
            out.append(p.upper())          # middle initial
        else:
            out.append(p.capitalize())
    return " ".join(out)


class GannettObituaries(BaseScraper):
    slug = "public_notices.gannett_obituaries"
    name = "Gannett Obituaries (W-NC + Upstate-SC — pre-probate heir leads)"
    category = "motivated_seller"
    # Bumped from 120s: the per-decedent detail fetch below adds ~1 plain GET
    # per obituary (~0.8s observed), ~140 across all 8 papers -- comfortably
    # inside 300s with the 8 list-page fetches, nowhere close to it at 120s.
    timeout_s = 300.0
    expected_min_count = 0  # captcha/markup drift -> empty, not REGRESSED

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_OBITUARIES", "1") == "0":
            return []
        detail_on = os.environ.get("FORECLOSURE_OBIT_DETAIL", "1") != "0"
        out: list[Listing] = []
        now = datetime.utcnow()
        detail_fetched = detail_hits = 0
        stopped = None
        pace = _Pacer()
        async with client(timeout=30.0) as c:
            # Pass 1: every paper's list page FIRST, each decedent a row at once (into
            # self.partial too). The detail GETs used to run paper by paper in between,
            # ~20 per paper, so the last papers' LIST pages were asked for after ~100
            # detail requests; on the VM's 2026-10-08 run those two answered 429 and
            # their whole lists were lost (39 rows, down from ~140).
            to_detail: list[list[tuple[Listing, str]]] = []
            for host, (county, state) in PAPERS.items():
                if host in _TOWNNEWS_RSS_HOSTS:
                    got = await _fetch_townnews_host(host, county, state, now, self.slug)
                    out.extend(got)
                    self.partial.extend(got)
                    continue

                if stopped:
                    continue
                try:
                    await pace.wait()
                    r = await c.get(f"https://www.{host}/obituaries/")
                    if r.status_code == 429:
                        # The papers share one edge: asking the next paper now only
                        # collects more 429s. Stop the Gannett pass; rows so far ship.
                        stopped = "HTTP 429 on a list page"
                        log.warning("obituaries.bad_status", host=host, status=429,
                                    action="stop_gannett_for_run")
                        continue
                    if r.status_code != 200:
                        log.warning("obituaries.bad_status", host=host, status=r.status_code)
                        continue
                except Exception as exc:  # noqa: BLE001
                    log.warning("obituaries.fetch_failed", host=host, error=str(exc)[:140])
                    continue

                slugs = [
                    s for s in dict.fromkeys(_SLUG_RE.findall(r.text))
                    if s.count("-") >= 1 and not any(n in s for n in _NOISE)
                ]
                paper: list[tuple[Listing, str]] = []
                for slug in slugs:
                    name = _name_from_slug(slug)
                    if len(name) < 5 or name.replace(" ", "").isdigit():
                        continue
                    detail_url = f"https://www.{host}/obituaries/{slug}"
                    li = _build_obit_listing(
                        self.slug, slug, name, detail_url, host, county, state, {}, now,
                    )
                    out.append(li)
                    self.partial.append(li)
                    paper.append((li, detail_url))
                to_detail.append(paper[:_DETAIL_MAX])
                log.info("obituaries.county", host=host, county=county, kept=len(paper))

            # Pass 2: per-decedent detail (age / death date / a literal home address /
            # service venue from the server-rendered meta description; see the module
            # docstring), round-robin across the papers so a cut-off pass still covers
            # every paper, time-boxed, and stopped for the run on the first refusal.
            if detail_on and not stopped:
                order = [paper[i] for i in range(max((len(p) for p in to_detail), default=0))
                         for paper in to_detail if i < len(paper)]
                t0 = time.monotonic()
                for li, detail_url in order:
                    if time.monotonic() - t0 > _DETAIL_BUDGET_S:
                        stopped = "budget"
                        break
                    await pace.wait()
                    status, detail = await _fetch_detail_status(c, detail_url)
                    detail_fetched += 1
                    if status in _STOP_DETAIL_STATUSES:
                        stopped = f"HTTP {status}"
                        log.warning("obituaries.detail_refused", status=status,
                                    url=detail_url, fetched=detail_fetched)
                        break
                    if detail:
                        detail_hits += 1
                        _apply_detail(li, detail)
        log.info("obituaries.done", leads=len(out),
                 detail_fetched=detail_fetched, detail_hits=detail_hits,
                 detail_stopped=stopped)
        return out
