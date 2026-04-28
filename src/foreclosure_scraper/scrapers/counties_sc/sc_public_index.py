"""SC Judicial Department Public Index — case-level foreclosure search.

We use the per-county case-search portal (sccourts.org/caseSearch) to find recently
filed foreclosure cases (case type 'CP' with sub-type starting 'Foreclosure').
The portal is JS-heavy; we delegate to apify/rag-web-browser.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from ...apify_helper import fetch_rendered
from ...base_scraper import BaseScraper
from ...config import SC_COUNTIES
from ...models import Listing, ListingType, PropertyKind

CASE_RE = re.compile(r"\b\d{4}-CP-\d{2}-\d{4,6}\b")


class SCPublicIndex(BaseScraper):
    slug = "counties_sc.sc_public_index"
    name = "SC Judicial Public Index"
    category = "state_court"
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for c in SC_COUNTIES:
            url = (
                "https://www.sccourts.org/caseSearch/index.cfm?"
                f"action=index&county={c.name.replace(' ', '+')}&caseType=CP&caseSubType=Foreclosure"
            )
            content = await fetch_rendered(url)
            if not content:
                continue
            for case in set(CASE_RE.findall(content)):
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=url,
                        listing_type=ListingType.LIS_PENDENS,
                        property_kind=PropertyKind.UNKNOWN,
                        state="SC",
                        county=c.name,
                        case_number=case,
                        description=f"SC Public Index foreclosure case {case} ({c.name} County)",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
        return out
