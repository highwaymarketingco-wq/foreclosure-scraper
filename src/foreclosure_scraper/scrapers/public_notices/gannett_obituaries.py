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

Free, public, plain-HTTP. Gate off with FORECLOSURE_OBITUARIES=0.
"""
from __future__ import annotations

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
    timeout_s = 120.0
    expected_min_count = 0  # captcha/markup drift -> empty, not REGRESSED

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_OBITUARIES", "1") == "0":
            return []
        out: list[Listing] = []
        now = datetime.utcnow()
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
                for slug in slugs:
                    name = _name_from_slug(slug)
                    if len(name) < 5 or name.replace(" ", "").isdigit():
                        continue
                    out.append(Listing(
                        source=self.slug,
                        source_url=f"https://www.{host}/obituaries/{slug}",
                        listing_type=ListingType.PROBATE_NOTICE,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state, county=county,
                        defendant=name,  # decedent -> resolver pins parcel by owner-name
                        description=f"Obituary (death) — {name}, {county} County {state} "
                                    f"— pre-probate heir/estate signal",
                        first_seen=now, last_seen=now,
                        raw={
                            "obituary": {"decedent": name, "slug": slug,
                                         "paper": host, "county": county, "state": state},
                            "life_event": "death",
                            "relationship_signal": {"kind": "probate",
                                                    "keyword": "obituary"},
                        },
                    ))
                    kept += 1
                log.info("obituaries.county", host=host, county=county, kept=kept)
        log.info("obituaries.done", leads=len(out))
        return out
