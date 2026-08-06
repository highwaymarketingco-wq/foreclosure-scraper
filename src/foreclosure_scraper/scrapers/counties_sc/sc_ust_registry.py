"""SC DES Underground Storage Tank registry — the SC contamination spine.

WHY THIS MATTERS MORE THAN ITS SUBJECT SUGGESTS
    A registered underground storage tank is a recorded environmental liability
    that runs with the land. Abandoned tanks at dead service stations and rural
    groceries are exactly the properties that sit unsold for decades.

    But the real value is coverage. This is ONE statewide search that returns
    every SC county in the footprint, including the two with almost no local
    data at all:

        Spartanburg 1,148 · Anderson 788 · Pickens 410 · Laurens 320
        Oconee 315 · Cherokee 230 · Union 121          = 3,332 in-footprint

    Union SC is blocked or empty on five of six signals in the coverage matrix.
    This is the first real source it has.

A PROBATE SIGNAL HIDING IN A TANK REGISTRY
    39 of the 3,332 name an owner of record as "ESTATE OF ..." or "... HEIRS" —
    e.g. 'ESTATE OF ALLIE M GRAHAM' at 6511 HWY 72, Whitmire (Union), a
    service station whose tanks were abandoned in 1996. An estate still holding
    a contaminated commercial parcel thirty years on is about as motivated as a
    seller gets, and no probate source in the engine surfaces it.

WHAT IS DELIBERATELY NOT FETCHED
    Each row has a "Details" page carrying Tank Owner Phone. A sample of 30
    Spartanburg detail pages found a phone on 30 of 30 — at full pull that is
    3,000+ personal and small-business phone numbers.

    We fetch the LIST ONLY. It already carries facility name, owner of record,
    situs address, city and county, which is everything needed to make a lead.
    Contact data belongs to the skip-trace path under its own DNC rules, not to
    a source reader that would hoover up three thousand numbers as a side
    effect. The detail page is one request away and is not made.

ACCESS
    Plain form POST to /Home/searchRegistryRequest, one per county. No auth, no
    CAPTCHA, no token. apps.des.sc.gov serves no robots.txt (404).
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...layer_guard import LayerHarvest
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://apps.des.sc.gov/USTRegistry/"
SEARCH = BASE + "Home/searchRegistryRequest"

#: The seven SC counties in the footprint.
COUNTIES = ("Spartanburg", "Anderson", "Pickens", "Laurens", "Oconee",
            "Cherokee", "Union")

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
#: Owner-of-record strings that mean the owner is an estate rather than a person.
# "REAL ESTATE OF SC LLC" is a company, not a decedent's estate — a bare
# "ESTATE OF" match flags it wrongly. Require the phrase not be preceded by
# "REAL".
_ESTATE = re.compile(r"(?<!REAL )\bESTATE OF\b|\bHEIRS?\b|\bDECEASED\b", re.I)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", html)).strip()


def _to_listing(cells: list[str], county: str) -> Optional[Listing]:
    # Facility | Tank Owner | Address | City | County | Permit | #Tanks | Details
    if len(cells) < 6:
        return None
    facility, owner, addr, city, cnty, permit = (cells[0], cells[1], cells[2],
                                                 cells[3], cells[4], cells[5])
    addr = addr.strip()
    if not addr:
        return None                      # no address, no lead
    owner = owner.strip() or None
    is_estate = bool(owner and _ESTATE.search(owner))
    now = datetime.utcnow()
    bits = [b for b in (owner, addr, facility) if b]
    return Listing(
        source="counties_sc.sc_ust_registry",
        source_url=BASE,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        state="SC", county=(cnty.strip() or county),
        street_address=addr,
        city=city.strip() or None,
        owner_name=owner, defendant=owner,
        case_number=permit.strip() or None,
        foreclosure_process="contamination",
        description=f"{county} SC UST — {' | '.join(bits)}"[:300],
        first_seen=now, last_seen=now,
        raw={"sc_ust_registry": {
            "facility": facility.strip() or None,
            "owner_of_record": owner,
            "permit": permit.strip() or None,
            "tanks": cells[6].strip() if len(cells) > 6 else None,
            # Surfaced because an estate still holding a contaminated parcel is
            # a probate signal no probate source in the engine reaches.
            "estate_owned": is_estate,
        }},
    )


async def _one_county(c, county: str) -> list[Listing]:
    r = await c.post(SEARCH, data={
        "siteNumber": "", "ownersName": "", "address": "", "city": "",
        "selectedCounty": county, "zipCode": "", "selectedProduct": "",
        "Search": "Search",
    }, timeout=90.0)
    if r.status_code != 200:
        raise RuntimeError(f"{county}: HTTP {r.status_code}")
    out: list[Listing] = []
    for tr in _ROW.findall(r.text):
        cells = [_text(x) for x in _CELL.findall(tr)]
        if not cells or cells[0].lower() == "facility":
            continue                     # header
        li = _to_listing(cells, county)
        if li:
            out.append(li)
    est = sum(1 for li in out
              if (li.raw or {}).get("sc_ust_registry", {}).get("estate_owned"))
    log.info("sc_ust.county_done", county=county, leads=len(out), estate_owned=est)
    return out


class SCUstRegistry(BaseScraper):
    slug = "counties_sc.sc_ust_registry"
    name = "SC DES Underground Storage Tank registry (7 upstate counties)"
    category = "state_distress"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get("FORECLOSURE_SC_UST") == "0":
            return []
        out: list[Listing] = []
        guard = LayerHarvest(self.slug, list(COUNTIES), attempts=3)
        async with client(timeout=90.0) as c:
            await c.get(BASE)            # seed the session
            with guard:
                for county in COUNTIES:
                    out.extend(await guard.harvest(county, self._one(c, county)))
        return out

    @staticmethod
    def _one(c, county: str):
        async def _run() -> list[Listing]:
            return await _one_county(c, county)
        return _run
