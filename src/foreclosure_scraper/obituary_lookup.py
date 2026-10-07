"""Lead-driven obituary and memorial lookups for dead-owner leads (name search), capped and polite.

The feed readers catch deaths as they happen. Most dead-owner leads on the board died years ago
(the roll already says HEIRS or ESTATE), so their obituary is not in any feed today. This module
searches by the owner's name instead, for a capped number of leads a run:

  Echovita name search, city-scoped (verified open 2026-10-07):
      GET https://www.echovita.com/us/obituaries/<st>/<city>?q=<First Last>&s=1
      -> the same cards as the listing pages; a card whose name fits is read in full
         (schema.org Person dates + the obituary text with its survivor list).
  Find a Grave memorial search, county-scoped (read-only; verified open 2026-10-07):
      GET https://www.findagrave.com/memorial/search?firstname=&middlename=&lastname=&location=&locationId=county_N
      -> cards with name, birth-death dates and the cemetery's 'City, County, State'. A card whose
         name fits is read: its birth and death dates and the biography text (often a pasted
         obituary, read for survivors). Find a Grave's family links point to OTHER MEMORIALS, i.e.
         to people who have died, so they are counted, never offered as heir candidates.
      County ids come from the site's own state browse pages (two requests, cached privately).

Every found record goes into the private obituary store (heirs_store.ObituaryStore) and is then
matched by enrichment_obituary_match's rules (full-name fit, county, dates; ambiguity recorded,
not attached). A search is never repeated within LOOKUP_TTL_DAYS (heirs_store.LookupLog).

Politeness and walls: _obit_common.PoliteFetcher (>= 1.6 s a host, ordinary UA, a CAPTCHA /
challenge / login / 401-403 / 402 / 429 stops that host for the run; nothing is retried or worked
around). Off unless asked: OBITUARY_LOOKUPS=<n leads> (default 0 in the pipeline).
"""
from __future__ import annotations

import asyncio
import html as _html
import json
import os
import re
from typing import Any, Iterable, Optional
from urllib.parse import quote_plus

import structlog

from .enrichment_obituary_match import (
    _get,
    _norm_county,
    _raw,
    iso_date,
    name_level,
    obit_person,
    owner_readings,
)
from .obituary_text import clean_text, parse_survivors
from .quiet_title.fetch import Walled

log = structlog.get_logger()

LOOKUP_TTL_DAYS = float(os.environ.get("OBITUARY_LOOKUP_TTL_DAYS", "45"))
MAX_DETAIL_PER_LEAD = 2

#: county -> echovita city slugs searched when the lead names no city (seat first)
COUNTY_CITIES: dict[tuple[str, str], tuple[str, ...]] = {
    ("NC", "Buncombe"): ("asheville", "weaverville", "black-mountain", "candler", "arden"),
    ("NC", "Henderson"): ("hendersonville", "fletcher", "flat-rock"),
    ("NC", "Rutherford"): ("rutherfordton", "forest-city", "spindale"),
    ("NC", "Cleveland"): ("shelby", "kings-mountain", "boiling-springs"),
    ("NC", "Polk"): ("columbus", "tryon", "mill-spring"),
    ("NC", "Gaston"): ("gastonia", "belmont", "mount-holly", "cherryville"),
    ("NC", "Transylvania"): ("brevard", "pisgah-forest"),
    ("NC", "McDowell"): ("marion", "old-fort"),
    ("NC", "Lincoln"): ("lincolnton", "denver"),
    ("NC", "Mitchell"): ("spruce-pine", "bakersville"),
    ("NC", "Burke"): ("morganton", "valdese"),
    ("SC", "Spartanburg"): ("spartanburg", "boiling-springs", "inman", "duncan", "woodruff"),
    ("SC", "Anderson"): ("anderson", "belton", "williamston", "honea-path"),
    ("SC", "Pickens"): ("easley", "pickens", "clemson", "liberty"),
    ("SC", "Oconee"): ("seneca", "walhalla", "westminster"),
    ("SC", "Cherokee"): ("gaffney", "blacksburg"),
    ("SC", "Union"): ("union", "jonesville"),
    ("SC", "Laurens"): ("laurens", "clinton"),
    ("SC", "Greenville"): ("greenville", "greer", "simpsonville", "taylors", "travelers-rest"),
}
_STATE_NAME = {"NC": "North Carolina", "SC": "South Carolina"}


def _slug(city: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", city.strip().lower()).strip("-")


def _best_reading(row: Any):
    """The owner reading to search with: the one carrying the most name words (a middle name
    makes the strict fit possible), from the heirs/estate-marked owner part when there is one."""
    from .enrichment_obituary_match import _lead_owner_strings
    best = None
    for s in _lead_owner_strings(row):
        for p, how in owner_readings(s):
            if how == "FIRST MIDDLE LAST" and not re.search(r"[a-z]", s):
                continue                    # all-caps roll: search the roll's own LAST FIRST order
            if best is None or len(p.given) > len(best.given):
                best = p
    return best


# --------------------------------------------------------------------------- Find a Grave

FAG = "https://www.findagrave.com"
_FAG_CARD = re.compile(r'<div class="memorial-item [^"]*" id="sr-(\d+)">(.*?)(?=<div class="memorial-item |'
                       r'<!-- Memorial search result list ends|$)', re.S)


def parse_fag_search(html: str) -> list[dict]:
    out = []
    for mid, body in _FAG_CARD.findall(html or ""):
        href = re.search(r'href="(/memorial/\d+/[^"]+)"', body)
        name = re.search(r'<h2 class="name-grave[^"]*"><i[^>]*>(.*?)</i>', body, re.S)
        dates = re.search(r'<b class="birthDeathDates[^"]*">(.*?)</b>', body, re.S)
        addr = re.search(r'<p class="addr-cemet[^>]*>(.*?)</p>', body, re.S)
        if not href or not name:
            continue
        out.append({"url": FAG + href.group(1), "id": mid,
                    "name": clean_text(_html.unescape(name.group(1))),
                    "dates_text": clean_text(_html.unescape(dates.group(1))) if dates else None,
                    "cemetery_place": clean_text(_html.unescape(addr.group(1))) if addr else None})
    return out


def parse_fag_memorial(html: str) -> dict:
    """{birth_date, death_date, bio, family: [{relation, name, death_date}]} from a memorial."""
    h = html or ""
    bd = re.search(r'itemprop="birthDate"[^>]*>([^<]{4,40})<', h)
    dd = re.search(r'itemprop="deathDate"[^>]*>([^<]{4,40})<', h)
    bio = re.search(r'itemprop="description"[^>]*>(.*?)</(?:p|div)>', h, re.S)
    fam: list[dict] = []
    grid = h[h.find('id="family-grid"'):] if 'id="family-grid"' in h else ""
    for lab, ul in re.findall(r'<b[^>]*class="label-relation"[^>]*>\s*([^<]+?)\s*</b>\s*<ul[^>]*>(.*?)</ul>', grid, re.S):
        for li in re.findall(r"<li[^>]*>(.*?)</li>", ul, re.S):
            nm = re.search(r'itemprop="name"[^>]*>(.*?)</h3>', li, re.S)
            de = re.search(r'itemprop="deathDate"[^>]*>([^<]*)<', li)
            if nm:
                fam.append({"relation": lab.strip().lower(), "name": clean_text(nm.group(1)),
                            "death_date": (de.group(1).strip() if de else "") or None})
    return {"birth_date": clean_text(bd.group(1)) if bd else None, "death_date": clean_text(dd.group(1)) if dd else None,
            "bio": clean_text(bio.group(1)) if bio else "", "family": fam}


async def _fag_location_ids(pf, cache_dir=None) -> dict[str, str]:
    """{'NC|Buncombe': 'county_1661', ...} from the site's state browse pages (cached privately)."""
    from .heirs_store import private_dir
    path = (cache_dir or private_dir()) / "findagrave_locations.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    out: dict[str, str] = {}
    usa = await pf.get(f"{FAG}/cemetery-browse/USA?id=country_4")
    states = dict(re.findall(r'href="/cemetery-browse/USA/([A-Za-z-]+)\?id=(state_\d+)"', usa))
    for st, nm in (("NC", "North-Carolina"), ("SC", "South-Carolina")):
        sid = states.get(nm)
        if not sid:
            continue
        page = await pf.get(f"{FAG}/cemetery-browse/USA/{nm}?id={sid}")
        for cname, cid in re.findall(rf'href="/cemetery-browse/USA/{nm}/([A-Za-z-]+)-County\?id=(county_\d+)"', page):
            out[f"{st}|{cname.replace('-', ' ')}"] = cid
    if out:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, sort_keys=True), encoding="utf-8")
    return out


async def findagrave_records(pf, person, county: str, state: str, loc_ids: dict) -> list[dict]:
    cid = loc_ids.get(f"{state}|{county}")
    if not cid:
        return []
    params = {"firstname": person.first.title(), "lastname": person.last.title(),
              "location": f"{county} County, {_STATE_NAME[state]}, United States of America", "locationId": cid}
    if person.middles and len(person.middles[0]) > 1:
        params["middlename"] = person.middles[0].title()
    html = await pf.get(f"{FAG}/memorial/search", params=params)
    out = []
    for card in parse_fag_search(html):
        dp = obit_person(card["name"])
        if not dp or not name_level(person, dp)[0]:
            continue
        place = card.get("cemetery_place") or ""
        if county.lower() not in place.lower() or _STATE_NAME[state].lower() not in place.lower():
            continue
        rec = {"url": card["url"], "source": "findagrave_search", "decedent": card["name"], "state": state,
               "county": county, "residence_city": None, "dates_text": card.get("dates_text"),
               "county_basis": "the cemetery where the memorial places the burial",
               "note": "a memorial (burial record), not an obituary; the cemetery's county stands in for residence"}
        if len(out) < MAX_DETAIL_PER_LEAD:
            m = parse_fag_memorial(await pf.get(card["url"]))
            rec["birth_date"] = iso_date(m["birth_date"])
            rec["death_date"] = iso_date(m["death_date"])
            s = parse_survivors(m["bio"]) if m["bio"] else {"survivors": [], "unnamed": [], "predeceased": []}
            rec["survivors"], rec["unnamed"], rec["predeceased"] = s["survivors"], s["unnamed"], s["predeceased"]
            rec["family_memorials"] = len(m["family"])
            rec["detail_read"] = True
        out.append(rec)
    return out


# --------------------------------------------------------------------------- Echovita search

async def echovita_records(pf, person, county: str, state: str, cities: Iterable[str]) -> list[dict]:
    from .scrapers.public_notices.echovita_obituaries import CONTENT_RX, parse_listing, parse_obituary_page
    q = " ".join([person.first.title()] + [m.title() for m in person.middles if len(m) > 1][:1] + [person.last.title()])
    out, seen = [], set()
    for city in cities:
        html = await pf.get(f"https://www.echovita.com/us/obituaries/{state.lower()}/{_slug(city)}?q={quote_plus(q)}&s=1")
        for c in parse_listing(html):
            if c["url"] in seen or c["state"] != state:
                continue
            seen.add(c["url"])
            dp = obit_person(c["name"])
            if not dp or not name_level(person, dp)[0]:
                continue
            rec = {"url": c["url"], "source": "echovita_search", "decedent": c["name"], "state": state,
                   "county": county, "residence_city": c["city"], "age": c.get("age"), "dates_text": c.get("dates_text"),
                   "county_basis": "the city searched"}
            if sum(1 for r in out if r.get("detail_read")) < MAX_DETAIL_PER_LEAD:
                d = parse_obituary_page(await pf.get(c["url"], content_rx=CONTENT_RX))
                s = parse_survivors(d.get("text") or "")
                rec.update({"birth_date": iso_date(d.get("birth_date")), "death_date": iso_date(d.get("death_date")),
                            "survivors": s["survivors"], "unnamed": s["unnamed"], "predeceased": s["predeceased"],
                            "detail_read": True})
            out.append(rec)
    return out


def _lead_cities(row: Any) -> list[str]:
    raw = _raw(row)
    cities: list[str] = []
    for c in (_get(row, "city"), (raw.get("owner_mailing") or {}).get("city") if isinstance(raw.get("owner_mailing"), dict) else None):
        if c and str(c).strip() and str(c).strip().lower() not in [x.lower() for x in cities]:
            cities.append(str(c).strip())
    key = (str(_get(row, "state") or "").upper(), str(_get(row, "county") or "").strip())
    for c in COUNTY_CITIES.get(key, ())[:2]:
        if c.replace("-", " ") not in [x.lower() for x in cities]:
            cities.append(c.replace("-", " "))
    return cities[:3]


async def lookup_leads(rows: list, *, limit: int, store, sources=("echovita", "findagrave"),
                       log_store=None, fetcher_factory=None) -> dict:
    """Search by name for up to `limit` dead-owner leads that have no attached obituary match,
    add what fits to `store`. Returns counts (never names)."""
    from .enrichment_heir_candidates import deceased_signals
    from .heirs_store import LookupLog
    from .scrapers.public_notices._obit_common import PoliteFetcher
    lg = log_store or LookupLog().load()
    stats = {"leads_searched": 0, "records_found": 0, "with_survivors": 0, "walled": {}, "skipped_recent": 0}
    todo = []
    for row in rows:
        raw = _raw(row)
        if (raw.get("obituary_match") or {}).get("status") == "attached" or not deceased_signals(row):
            continue
        st = str(_get(row, "state") or "").upper()
        co = str(_get(row, "county") or "").strip()
        if st not in _STATE_NAME or not co:
            continue
        p = _best_reading(row)
        if not p:
            continue
        key = f"{st}|{_norm_county(co)}|{p.last}|{' '.join(p.given)}|{p.suffix or ''}"
        if lg.recent(key, LOOKUP_TTL_DAYS):
            stats["skipped_recent"] += 1
            continue
        todo.append((row, p, st, co, key))
        if len(todo) >= limit:
            break
    factory = fetcher_factory or PoliteFetcher
    async with factory() as pf:
        loc_ids = {}
        if "findagrave" in sources:
            try:
                loc_ids = await _fag_location_ids(pf)
            except Walled as w:
                stats["walled"]["findagrave"] = w.reason
        for row, p, st, co, key in todo:
            found = []
            if "echovita" in sources and "echovita" not in stats["walled"]:
                try:
                    found += await echovita_records(pf, p, co, st, _lead_cities(row))
                except Walled as w:
                    stats["walled"]["echovita"] = w.reason
                except Exception as exc:  # noqa: BLE001
                    log.info("obituary_lookup.echovita_error", error=str(exc)[:120])
            if "findagrave" in sources and loc_ids and "findagrave" not in stats["walled"]:
                try:
                    found += await findagrave_records(pf, p, co, st, loc_ids)
                except Walled as w:
                    stats["walled"]["findagrave"] = w.reason
                except Exception as exc:  # noqa: BLE001
                    log.info("obituary_lookup.findagrave_error", error=str(exc)[:120])
            stats["leads_searched"] += 1
            for rec in found:
                store.upsert(rec)
            stats["records_found"] += len(found)
            stats["with_survivors"] += sum(1 for r in found if r.get("survivors"))
            lg.mark(key, n=len(found))
            if len(stats["walled"]) == len(sources):
                break
    try:
        lg.save()
        store.save()
    except OSError as exc:
        log.warning("obituary_lookup.save_failed", error=str(exc)[:200])
    log.info("obituary_lookup.done", **{k: v for k, v in stats.items()})
    return stats


async def enrich_obituary_lookups(listings: list) -> dict:
    """Pipeline entry (network). OBITUARY_LOOKUPS=<n> leads a run; 0 / unset = off."""
    n = int(os.environ.get("OBITUARY_LOOKUPS", "0") or 0)
    if n <= 0:
        return {"skipped": "OBITUARY_LOOKUPS=0"}
    from .heirs_store import ObituaryStore
    return await lookup_leads(listings, limit=n, store=ObituaryStore().load())
