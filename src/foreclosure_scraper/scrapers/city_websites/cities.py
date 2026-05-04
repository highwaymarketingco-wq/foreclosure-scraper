"""Generic city-website foreclosure / tax sale / code enforcement scraper.

Cities in our 25-county footprint don't all have dedicated foreclosure pages,
but most publish:
  * Tax sale notices (delinquent property auctions) on the finance / treasurer page
  * Code enforcement / nuisance abatement / demolition lists
  * Public notice / legal advertising sections
  * Surplus property auctions

Rather than maintain 50+ custom city parsers, we use Apify rag-web-browser to
search each city's domain for foreclosure-related keywords and harvest links +
text. Each hit becomes a lightweight Listing pointing at the city URL — these
get enriched downstream by GIS + court records.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable

from ...apify_helper import fetch_rendered
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind


# (state, county, city, domain) — covers every city seat plus major suburbs
CITIES: tuple[tuple[str, str, str, str], ...] = (
    # Greenville/Greenwood/Newberry/Abbeville removed per scope narrowing 2026-05.
    # SC
    ("SC", "Spartanburg", "Spartanburg", "cityofspartanburg.org"),
    ("SC", "Spartanburg", "Boiling Springs", "boilingspringssc.org"),
    ("SC", "Spartanburg", "Inman", "cityofinmansc.org"),
    ("SC", "Anderson", "Anderson", "cityofandersonsc.com"),
    ("SC", "Anderson", "Belton", "cityofbeltonsc.com"),
    ("SC", "Anderson", "Williamston", "williamstonsc.us"),
    ("SC", "Pickens", "Easley", "cityofeasley.com"),
    ("SC", "Pickens", "Pickens", "cityofpickens.com"),
    ("SC", "Pickens", "Liberty", "cityoflibertysc.com"),
    ("SC", "Oconee", "Walhalla", "cityofwalhalla.com"),
    ("SC", "Oconee", "Seneca", "seneca.sc.us"),
    ("SC", "Oconee", "Westminster", "cityofwestminstersc.com"),
    ("SC", "Cherokee", "Gaffney", "cityofgaffneysc.gov"),
    ("SC", "Cherokee", "Blacksburg", "townofblacksburg.com"),
    ("SC", "Union", "Union", "cityofunionsc.org"),
    ("SC", "Laurens", "Laurens", "cityoflaurenssc.com"),
    ("SC", "Laurens", "Clinton", "cityofclintonsc.com"),
    # NC
    ("NC", "Mecklenburg", "Charlotte", "charlottenc.gov"),
    ("NC", "Mecklenburg", "Davidson", "townofdavidson.org"),
    ("NC", "Mecklenburg", "Cornelius", "cornelius.org"),
    ("NC", "Mecklenburg", "Huntersville", "huntersville.org"),
    ("NC", "Mecklenburg", "Matthews", "matthewsnc.gov"),
    ("NC", "Mecklenburg", "Mint Hill", "minthill.com"),
    ("NC", "Mecklenburg", "Pineville", "pinevillenc.gov"),
    ("NC", "Buncombe", "Asheville", "ashevillenc.gov"),
    ("NC", "Buncombe", "Black Mountain", "townofblackmountain.org"),
    ("NC", "Buncombe", "Weaverville", "weavervillenc.org"),
    ("NC", "Henderson", "Hendersonville", "hendersonvillenc.gov"),
    ("NC", "Henderson", "Flat Rock", "villageofflatrock.org"),
    ("NC", "Rutherford", "Rutherfordton", "rutherfordton.net"),
    ("NC", "Rutherford", "Forest City", "townoffc.org"),
    ("NC", "Rutherford", "Spindale", "townofspindale.com"),
    ("NC", "Cleveland", "Shelby", "cityofshelby.com"),
    ("NC", "Cleveland", "Kings Mountain", "cityofkm.com"),
    ("NC", "Cleveland", "Boiling Springs", "boilingspringsnc.com"),
    ("NC", "Polk", "Columbus", "columbusnc.com"),
    ("NC", "Polk", "Tryon", "tryon-nc.com"),
    ("NC", "Gaston", "Gastonia", "gastonianc.gov"),
    ("NC", "Gaston", "Mount Holly", "mtholly.us"),
    ("NC", "Gaston", "Belmont", "cityofbelmont.org"),
    ("NC", "Gaston", "Bessemer City", "bessemercity.com"),
    ("NC", "Gaston", "Cherryville", "cityofcherryville.com"),
    ("NC", "Transylvania", "Brevard", "cityofbrevard.com"),
    ("NC", "McDowell", "Marion", "marionnc.org"),
    ("NC", "McDowell", "Old Fort", "oldfortnc.gov"),
    ("NC", "Lincoln", "Lincolnton", "lincolntonnc.org"),
    ("NC", "Madison", "Marshall", "townofmarshall.org"),
    ("NC", "Madison", "Mars Hill", "townofmarshillnc.com"),
    ("NC", "Yancey", "Burnsville", "townofburnsville.org"),
    ("NC", "Mitchell", "Bakersville", "townofbakersville.com"),
    ("NC", "Mitchell", "Spruce Pine", "townofsprucepine.org"),
    ("NC", "Burke", "Morganton", "morgantonnc.gov"),
    ("NC", "Burke", "Valdese", "townofvaldese.com"),
)

QUERIES = (
    "foreclosure",
    "tax sale",
    "delinquent tax",
    "property auction",
    "code enforcement",
    "nuisance abatement",
    "demolition",
)

ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
DATE_RE = re.compile(
    r"\b(?:\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)


class CityWebsites(BaseScraper):
    slug = "city_websites.search"
    name = "City government websites (search)"
    category = "city_government"
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        sem = asyncio.Semaphore(4)

        async def search_one(state: str, county: str, city: str, domain: str, query: str) -> None:
            search_url = f"https://{domain}/?s={query.replace(' ', '+')}"
            async with sem:
                content = await fetch_rendered(search_url)
                if not content or len(content) < 200:
                    return
                # Find all distinct addresses + page mentions
                addrs = list({m.group(1) for m in ADDR_RE.finditer(content)})[:20]
                if not addrs:
                    return

                # Determine listing type from query
                q = query.lower()
                ltype = ListingType.UNKNOWN
                if "tax" in q:
                    ltype = ListingType.TAX_SALE
                elif "foreclos" in q:
                    ltype = ListingType.FORECLOSURE_SALE
                elif "auction" in q:
                    ltype = ListingType.AUCTION

                date_m = DATE_RE.search(content)
                date_hint = date_m.group(0) if date_m else None

                for addr in addrs:
                    out.append(
                        Listing(
                            source=f"city_websites.{domain.replace('.', '_')}",
                            source_url=search_url,
                            listing_type=ltype,
                            property_kind=PropertyKind.UNKNOWN,
                            street_address=addr,
                            city=city,
                            state=state,
                            county=county,
                            description=f"{city}, {state} city site '{query}' search hit. Date hint: {date_hint or 'unknown'}",
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                        )
                    )

        # Cap concurrency: searches × cities = ~400 fetches; bound at 4 concurrent
        tasks = []
        for state, county, city, domain in CITIES:
            for q in QUERIES[:3]:  # keep top 3 queries per city — most yield is in foreclosure / tax sale / delinquent
                tasks.append(search_one(state, county, city, domain, q))
        await asyncio.gather(*tasks)
        return out
