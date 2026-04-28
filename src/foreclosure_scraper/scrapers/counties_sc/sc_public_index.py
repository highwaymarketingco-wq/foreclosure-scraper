"""SC Judicial Public Index — per-county case search via Apify rag-web-browser."""
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
    timeout_s = 480.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        # Per-county Public Index pages — these are the live case search portals
        for c in SC_COUNTIES[:5]:  # cap to 5 highest-pop counties to keep Apify cost bounded
            url = f"https://publicindex.sccourts.org/{c.name}/PublicIndex/"
            content = await fetch_rendered(url)
            if not content:
                continue
            seen: set[str] = set()
            for case in set(CASE_RE.findall(content)):
                if case in seen:
                    continue
                seen.add(case)
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
