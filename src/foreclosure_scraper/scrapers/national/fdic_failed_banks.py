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

FIXED 2026-10-01 (batch-5 extraction-completeness audit): this docstring
already named the real 7th column (Fund #) but the code never captured it
(it only ever read clean[0:5]) -- wired it into raw. Also: the Bank Name
cell carries an <a href="/bank-failures/failed-bank-list/<slug>"> to that
bank's own FDIC detail page, but every row shipped the same generic
source_url (the list page) regardless of which bank it was -- same bug
class fixed in counties_generic.epa_frs_sites earlier today. Spot-checked
the detail page itself (Nano Banc): it is consumer FAQ / press-release
boilerplate about deposit-insurance continuity, no address or REO-portfolio
data, so it is captured as the real per-row source_url for provenance but
not worth an extra per-row fetch.

Free, public, no login.
Slug: national.fdic_failed_banks
Category: reo
ListingType: REO
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.fdic.gov/bank-failures/failed-bank-list"

# The FDIC table's State column is a full name ("Pennsylvania"), but every
# downstream scope check compares state.upper() against "NC"/"SC" -- a full
# name would never match, silently dropping any in-footprint bank failure.
# Full US state-name map is overkill here (everything outside NC/SC gets
# filtered out anyway); only the two states this project tracks matter.
_STATE_NAME_TO_ABBR = {
    "NORTH CAROLINA": "NC",
    "SOUTH CAROLINA": "SC",
}


def _normalize_state(raw: str) -> str:
    s = (raw or "").strip()
    return _STATE_NAME_TO_ABBR.get(s.upper(), s)


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
            state = _normalize_state(clean[2])
            cert_num = clean[3]
            acquiring = clean[4]
            fail_date_str = clean[5]
            # 7th column, present on the live table even though older captures
            # of this page may not have had it -- tolerate its absence.
            fund_number = clean[6] if len(clean) > 6 and clean[6] else None

            if not bank_name or not state:
                continue

            # Bank Name is itself "<a href='/bank-failures/failed-bank-list/
            # <slug>'>Name</a>" -- a real per-bank detail page. Captured as the
            # row's actual source_url (every row previously shared the same
            # generic list-page URL) for provenance; not worth a per-row
            # fetch (spot-checked: consumer FAQ/press-release boilerplate,
            # no address or REO-portfolio data).
            detail_url = PAGE_URL
            dm = re.search(r'href="(/bank-failures/failed-bank-list/[^"]+)"', cells[0], re.I)
            if dm:
                detail_url = urljoin(PAGE_URL, dm.group(1))

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
                "fund_number": fund_number,
            }

            out.append(
                Listing(
                    source=self.slug,
                    source_url=detail_url,
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
