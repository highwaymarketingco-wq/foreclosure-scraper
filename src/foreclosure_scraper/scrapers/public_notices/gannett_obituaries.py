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
"""
from __future__ import annotations

import html
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
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

_SLUG_RE = re.compile(r'/obituaries/([a-z][a-z0-9]+-[a-z0-9-]{2,40})(?=["/?])')
_NOISE = ("daily-digest", "privacy", "terms", "how-to", "self-service", "faq",
          "place-an", "frequently", "submit")
_SUFFIX = {"jr": "Jr.", "sr": "Sr.", "ii": "II", "iii": "III", "iv": "IV"}

# Per-paper cap on detail fetches, so one unusually long list can't blow the
# scraper's timeout_s. ~20/paper observed live -- 2x headroom.
_DETAIL_MAX = int(os.environ.get("FORECLOSURE_OBIT_DETAIL_MAX", "40"))

_META_DESC_RE = re.compile(
    r'<meta\s+name="description"\s+content="([^"]*)"', re.I
)
# "Darlene Rice Honeycutt, 80, of Asheville, ..." / "Jerry Deal, 92, of 11 Elk
# Mountain Road, ..." -- the decedent's own name repeats the slug-derived name,
# age is the first bare integer after the first comma.
_AGE_FROM_DESC_RE = re.compile(r"^[^,]+,\s*(\d{1,3}),")
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


async def _fetch_detail(c, url: str) -> dict:
    """One plain GET for a decedent's detail page; returns the parsed meta
    description fields, or {} on any failure (never raises -- a bad detail
    fetch must not cost the list-only lead this scraper already had)."""
    try:
        r = await c.get(url)
        if r.status_code != 200:
            return {}
        m = _META_DESC_RE.search(r.text)
        if not m:
            return {}
        return _parse_detail_description(m.group(1))
    except Exception as exc:  # noqa: BLE001
        log.info("obituaries.detail_failed", url=url, error=str(exc)[:140])
        return {}


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
        async with client(timeout=30.0) as c:
            for host, (county, state) in PAPERS.items():
                try:
                    r = await c.get(f"https://www.{host}/obituaries/")
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
                kept = 0
                for i, slug in enumerate(slugs):
                    name = _name_from_slug(slug)
                    if len(name) < 5 or name.replace(" ", "").isdigit():
                        continue
                    detail_url = f"https://www.{host}/obituaries/{slug}"

                    # Per-decedent detail: age / death date / a literal home
                    # address / service venue, parsed from the server-rendered
                    # meta description (see module docstring — no JS/stealth
                    # browser needed). Capped per paper, never fatal.
                    detail: dict = {}
                    if detail_on and i < _DETAIL_MAX:
                        detail = await _fetch_detail(c, detail_url)
                        detail_fetched += 1
                        if detail:
                            detail_hits += 1

                    obituary = {"decedent": name, "slug": slug,
                                "paper": host, "county": county, "state": state}
                    obituary.update(detail)

                    desc_bits = [f"Obituary (death) — {name}"]
                    if detail.get("age"):
                        desc_bits.append(f"age {detail['age']}")
                    desc_bits.append(f"{county} County {state} — pre-probate heir/estate signal")

                    li = Listing(
                        source=self.slug,
                        source_url=detail_url,
                        listing_type=ListingType.PROBATE_NOTICE,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state, county=county,
                        defendant=name,  # decedent -> resolver pins parcel by owner-name
                        description=", ".join(desc_bits)[:300],
                        first_seen=now, last_seen=now,
                        raw={
                            "obituary": obituary,
                            "life_event": "death",
                            "relationship_signal": {"kind": "probate",
                                                    "keyword": "obituary"},
                        },
                    )
                    # A literal home address found in the obituary text IS the
                    # decedent's own situs — skip the name->parcel resolver
                    # entirely and anchor the lead directly, same value a
                    # resolved parcel gives, for free.
                    home_addr = detail.get("home_address")
                    if home_addr:
                        li.street_address = home_addr
                        obituary["home_address_used_as_situs"] = True
                    out.append(li)
                    kept += 1
                log.info("obituaries.county", host=host, county=county, kept=kept)
        log.info("obituaries.done", leads=len(out),
                 detail_fetched=detail_fetched, detail_hits=detail_hits)
        return out
