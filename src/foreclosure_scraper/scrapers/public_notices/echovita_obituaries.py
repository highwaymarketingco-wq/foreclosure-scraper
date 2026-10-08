"""Echovita obituaries, NC and SC statewide, with survivor lists (core counties first).

Echovita (echovita.com) republishes funeral-home obituaries nationwide on open, server-rendered
pages. Verified live 2026-10-07 with an ordinary request, >= 1.6 s apart:

  /us/obituaries/nc?page=N   statewide listing, newest first, 24 cards a page: decedent name,
                             city ('Obituaries - Roxboro, North Carolina'), dates and age;
  /us/obituaries/nc/<city>/<slug>-<id>
                             the obituary: a schema.org Person block (name, birthDate, deathDate,
                             address) and the full text in <div id="obituary">.

The pages carry Cloudflare's passive detection script but present no challenge; a real challenge
or a 403 / 429 stops the reader for the run (see _obit_common.wall_reason). An older note
(docs/blocked_sources_forensic.md) lumped Echovita with legacy.com as Cloudflare-403; re-checked
today it is open. robots.txt disallows only PDF, checkout and add-obituary paths.

WHAT A RUN DOES. Walk the NC and SC listing pages newest first (ECHOVITA_MAX_PAGES a state, default
40, about a week of postings), stopping early once a whole page is already in the private store.
Every card becomes a row (name, residence city -> county, age, dates). Obituary pages are then
read for the survivor list, Western NC + Upstate SC footprint counties first, then the rest, up to
ECHOVITA_MAX_DETAIL a run (default 120); one already stored with its survivors is not re-read.

Same row shape and privacy split as the other obituary readers (_obit_common.py): survivor names
ride in raw['obituary_private'] and never reach the public board.

Gate off with FORECLOSURE_ECHOVITA=0.

SOURCE-COMPLETENESS AUDIT (2026-10-08). The VM's first run returned 576 rows = 2 states x 12 pages
x 24 cards: the page cap bound exactly, while the listing runs far deeper (page 40 of the NC listing
was live that day, its cards dated about 8 days back). A binding cap is worse than a short run: after
a gap between runs longer than 12 pages of postings, the pages past the cap are never read, and the
next run stops at the first page already in the store, so that band of deaths is skipped for good.
The caught-up stop already ends a normal run early, so the default cap is now 40 pages a state
(about a week of postings); a run that is caught up costs what it did, a run after a gap reads at most
56 more pages (about 2 s each).
"""
from __future__ import annotations

import html as _html
import json
import os
import re
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...config import NC_COUNTIES, SC_COUNTIES
from ...quiet_title.fetch import Walled
from ._obit_common import PoliteFetcher, obituary_listing

log = structlog.get_logger()

BASE = "https://www.echovita.com"
STATES = {"nc": "NC", "sc": "SC"}
MAX_PAGES = int(os.environ.get("ECHOVITA_MAX_PAGES", "40"))
MAX_DETAIL = int(os.environ.get("ECHOVITA_MAX_DETAIL", "120"))
CORE = {("NC", c.name) for c in NC_COUNTIES} | {("SC", c.name) for c in SC_COUNTIES}

_CARD = re.compile(
    r'<a class="text-name-obit-in-list[^"]*" href="(?P<href>/us/obituaries/(?P<st>[a-z]{2})/(?P<city>[a-z0-9-]+)/'
    r'(?P<slug>[a-z0-9-]+))" title="Read the obituary of (?P<name>[^"]+)">(?P<rest>.*?)</div>', re.S)
_CITY_TITLE = re.compile(r'title="Obituaries - ([^",]+), (?:North|South) Carolina"')
_AGE = re.compile(r"\((\d{1,3}) years? old\)")
_DATES = re.compile(r'<span class="my-auto">([^<]{4,60})</span>')
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_TEXT = re.compile(r'<div[^>]*id="obituary"[^>]*>(.*?)</div>', re.S | re.I)
#: the obituary text is on the served page (outside any form): what makes a share-form CAPTCHA a
#: form widget rather than a gate (see _obit_common.wall_reason)
CONTENT_RX = re.compile(r'<div[^>]*id="obituary"[^>]*>\s*(?:<h1[^>]*>.*?</h1>)?\s*<p[^>]*>[^<]{40,}', re.S | re.I)


def parse_listing(html: str) -> list[dict]:
    """Cards of one listing page: [{url, state, city, name, age, dates_text}]."""
    out: list[dict] = []
    seen: set[str] = set()
    for m in _CARD.finditer(html or ""):
        url = BASE + m.group("href")
        if url in seen:
            continue
        seen.add(url)
        rest = m.group("rest")
        ct = _CITY_TITLE.search(rest)
        city = _html.unescape(ct.group(1)).strip() if ct else m.group("city").replace("-", " ").title()
        age = _AGE.search(rest)
        dt = _DATES.search(rest)
        out.append({"url": url, "state": m.group("st").upper(), "city": city,
                    "name": _html.unescape(m.group("name")).strip(),
                    "age": int(age.group(1)) if age else None,
                    "dates_text": _html.unescape(dt.group(1)).strip() if dt else None})
    return out


def _person_ld(html: str) -> dict:
    for block in _LD.findall(html or ""):
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            o = stack.pop(0)
            if isinstance(o, dict):
                if o.get("@type") == "Person" and (o.get("deathDate") or o.get("birthDate")):
                    return o
                stack.extend(v for v in o.values() if isinstance(v, (dict, list)))
            elif isinstance(o, list):
                stack.extend(o)
    return {}


def parse_obituary_page(html: str) -> dict:
    """{name, birth_date, death_date, city, region, text} from one obituary page."""
    p = _person_ld(html)
    addr = p.get("address") if isinstance(p.get("address"), dict) else {}
    m = _TEXT.search(html or "")
    return {"name": p.get("name"), "birth_date": p.get("birthDate"), "death_date": p.get("deathDate"),
            "city": addr.get("addressLocality"), "region": addr.get("addressRegion"),
            "text": m.group(1) if m else ""}


def _county(city: Optional[str], state: str) -> Optional[str]:
    from ...enrichment_obituary_match import counties_for_city
    cs = counties_for_city(city, state)
    return next(iter(cs)) if len(cs) == 1 else None


def _known() -> tuple[set[str], set[str]]:
    """(urls already in the private store, urls whose obituary page was already read)."""
    try:
        from ...heirs_store import ObituaryStore
        recs = ObituaryStore().load().records
        return set(recs), {u for u, r in recs.items() if r.get("detail_read") or r.get("survivors")}
    except Exception:  # noqa: BLE001
        return set(), set()


class EchovitaObituaries(BaseScraper):
    slug = "public_notices.echovita_obituaries"
    name = "Echovita obituaries (NC + SC statewide, survivors for W-NC + Upstate SC first)"
    category = "motivated_seller"
    timeout_s = 900.0
    expected_min_count = 0

    async def fetch(self) -> Iterable:
        if os.environ.get("FORECLOSURE_ECHOVITA", "1") == "0":
            return []
        stored, read = _known()
        cards: list[dict] = []
        stats = {"pages": 0, "cards": 0, "detail": 0, "with_survivors": 0}
        async with PoliteFetcher() as pf:
            for st in STATES:
                for page in range(1, MAX_PAGES + 1):
                    url = f"{BASE}/us/obituaries/{st}" + (f"?page={page}" if page > 1 else "")
                    try:
                        html = await pf.get(url)
                    except Walled as w:
                        stats["walled"] = w.reason
                        break
                    except Exception as exc:  # noqa: BLE001
                        stats.setdefault("errors", []).append(str(exc)[:80])
                        break
                    stats["pages"] += 1
                    got = [c for c in parse_listing(html) if c["state"] == STATES[st]]
                    if not got:
                        break
                    cards += got
                    if stored and all(c["url"] in stored for c in got):
                        break                      # caught up with what a previous run listed
                if "walled" in stats:
                    break
            stats["cards"] = len(cards)
            for c in cards:
                c["county"] = _county(c["city"], c["state"])
            order = sorted(range(len(cards)), key=lambda i: (0 if (cards[i]["state"], cards[i]["county"]) in CORE else 1, i))
            details: dict[str, dict] = {}
            for i in order:
                if len(details) >= MAX_DETAIL or "walled" in stats:
                    break
                c = cards[i]
                if c["url"] in read:
                    continue
                try:
                    details[c["url"]] = parse_obituary_page(await pf.get(c["url"], content_rx=CONTENT_RX))
                    stats["detail"] += 1
                except Walled as w:
                    stats["walled"] = w.reason
                except Exception:  # noqa: BLE001
                    continue
        out = self.partial
        for c in cards:
            d = details.get(c["url"], {})
            li = obituary_listing(
                source=self.slug, url=c["url"], decedent=c["name"], state=c["state"], county=c["county"],
                publisher="Echovita", text=d.get("text") or "", residence_city=c["city"], age=c["age"],
                birth_date=d.get("birth_date"), death_date=d.get("death_date"),
                extra_public={"dates_text": c["dates_text"], "detail_read": bool(d)})
            if li.raw["obituary"].get("survivor_names_parsed"):
                stats["with_survivors"] += 1
            out.append(li)
        log.info("echovita.done", rows=len(out), **{k: v for k, v in stats.items() if k != "errors"})
        self.last_stats = stats
        return out
