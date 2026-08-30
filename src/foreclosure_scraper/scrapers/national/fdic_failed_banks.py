"""FDIC Failed Bank List — bank failure data for REO/distress signal enrichment.

The FDIC publishes a list of failed banks at:
  https://www.fdic.gov/bank-failures/failed-bank-list

The old JSON API (banklist.json) was deprecated and now 301-redirects to the
HTML page. The page contains an HTML table with columns:
  Bank Name, City, State, Cert #, Acquiring Institution, Failure Date, Fund #.

While not a direct property listing source, bank failures are a leading
indicator for REO inventory — the acquiring institution typically offloads
the failed bank's REO portfolio within 6-12 months. This scraper captures
the bank failure data as a distress signal.

Free, public, no login.
Slug: national.fdic_failed_banks
Category: reo
ListingType: REO
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.fdic.gov/bank-failures/failed-bank-list"


class FDICFailedBanks(BaseScraper):
    slug = "national.fdic_failed_banks"
    name = "FDIC Failed Bank List"
    category = "reo"
    timeout_s = 60.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("fdic.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 500:
            return out

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
            if len(cells) < 6:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]

            bank_name = clean[0]
            city = clean[1]
            state = clean[2]
            cert_num = clean[3]
            acquiring = clean[4]
            fail_date_str = clean[5]

            if not bank_name or not state:
                continue

            try:
                fail_date = datetime.strptime(fail_date_str, "%B %d, %Y")
            except ValueError:
                try:
                    fail_date = datetime.strptime(fail_date_str, "%b %d, %Y")
                except ValueError:
                    fail_date = None

            # Only keep recent failures (last 2 years)
            if fail_date:
                days_ago = (datetime.now() - fail_date).days
                if days_ago > 730:
                    continue

            raw = {
                "bank_name": bank_name,
                "city": city,
                "state": state,
                "cert_number": cert_num,
                "acquiring_institution": acquiring,
                "failure_date": fail_date_str,
            }

            out.append(
                Listing(
                    source=self.slug,
                    source_url=PAGE_URL,
                    listing_type=ListingType.REO,
                    street_address=f"{bank_name}",
                    city=city,
                    state=state,
                    property_kind=PropertyKind.UNKNOWN,
                    raw=raw,
                    sale_date=fail_date,
                )
            )

        log.info("fdic.fetch_done", count=len(out))
        return out
