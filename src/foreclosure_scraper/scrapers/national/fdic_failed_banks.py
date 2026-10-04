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

FIXED 2026-10-04 (national.* extraction-completeness audit, batch 15) — two
compounding, severe bugs that together meant this source has NEVER shipped a
single row to the board, by construction, since it was first written:

  1. COMPLETENESS: the HTML table at PAGE_URL is paginated ("items_per_page=
     25" baked into its own sort-link querystrings, live-verified
     2026-10-04) and the old code only ever fetched page 1 -- 25 of the
     table's 578 total historical rows. The live page ALSO links a complete,
     free, no-login CSV export (`/bank-failures/download-data.csv`,
     confirmed live: 578 rows back to 2000, State already abbreviated
     "NC"/"SC" rather than the HTML table's full names). Switched the
     primary data source to that CSV -- one fetch, the entire history, no
     pagination-drift risk if failures ever spike again (2010 alone had 157
     nationally, which would have blown straight through a 25-row first
     page). The per-bank HTML detail-page link has no address/portfolio data
     of its own (see the FIXED-2026-10-01 note above) but is still cheap to
     recover: a second, best-effort fetch of PAGE_URL's first page builds a
     Cert#->detail-url map (Cert# is a stable, exact-match key present in
     both the CSV and the HTML table, so this needs no bank-name/HTML-entity
     normalization); a cert absent from that map (any row older than the
     current ~25-row first page) falls back to the generic list-page URL,
     same as before. A failure of this second fetch never blocks the CSV
     data itself.

  2. CORRECTNESS (the fatal one): the scraper has ALWAYS emitted
     `listing_type=ListingType.REO` and NEVER set `county` (the FDIC table
     has no county column -- only City). `ListingType.REO` is in
     `main._FLIP_LISTING_TYPES` ("something you could go bid on or buy
     TODAY"), which routes scope-checking through the NARROW 18-county
     footprint gate (`config.in_scope(county, state)`) -- and that function
     returns False immediately whenever `county` is falsy
     (`if not county_name or not state: return False`, config.py). With
     county always None, EVERY row from this source has always failed
     `main._in_scope()` and been silently deleted before ever reaching the
     board, for the entire life of this scraper (confirmed via
     `git log` -- no commit ever touched this). This was invisible in
     practice because the live NC/SC failures are old enough (most recent:
     2014, Allendale County Bank) to also fail the scraper's own 730-day
     recency filter -- but the bug is 100% reproducible and would have
     silently zeroed the NEXT NC/SC bank failure too, the exact moment this
     signal would matter.

     Root-caused as a correctness/mapping bug, not just a missing field: a
     bank failure itself is NOT "something you could go bid on or buy
     today" -- it is a leading indicator, exactly the distinction
     `main._FLIP_LISTING_TYPES`'s own docstring draws (and the module
     docstring above already says so: "not a direct property listing
     source... a leading indicator"). `distress_score.py` independently
     encodes the same REO==FLIP_TYPES assumption
     (`FLIP_TYPES = frozenset({..., "reo"})`), so typing this REO was ALSO
     silently mislabeling every row's `foreclosure_process` as NC
     power-of-sale / SC judicial (`enrichment_process_timing.py`'s
     `_FORECLOSURE_TYPES` includes REO) -- a bank failure has no such
     process at all.

     Fixed in two parts:
       a. `listing_type` -> `ListingType.DISTRESSED` (the project's generic
          non-flip signal type; matches how CourtListener bankruptcy/civil
          signals are typed, and fixes the `foreclosure_process` mislabel
          for free since DISTRESSED isn't in `_FORECLOSURE_TYPES` either).
          Also added "fdic_failed_banks" to distress_score.py's
          `_CONTEXT_ONLY_DISTRESSED_SOURCES` -- a bank failure is a federal
          regulatory record with zero evidence about THIS structure's
          condition, the same reasoning already applied to
          hud_section8_contracts/crexi_multifamily/fema_disasters in that
          set; without it, DISTRESSED's default PROPERTY-category score
          would wrongly imply condition evidence that doesn't exist here.
       b. County is now derived from City via the existing
          `_bankruptcy_city_to_county.bankruptcy_county_for()` 146-county
          NC+SC gazetteer (live-checked against all 17 real historical
          NC/SC rows in the CSV: 14/17 resolve correctly, e.g. Asheville ->
          Buncombe, Spartanburg -> Spartanburg; Pawleys Island/Myrtle
          Beach/Fairfax SC are genuine gazetteer gaps). Because that
          gazetteer is not 100% complete, `national.fdic_failed_banks` was
          ALSO added to `main.SCOPE_BYPASS_SOURCES` (same mechanism already
          used for craigslist_fsbo/sc_public_index/CourtListener: "state is
          reliable, county may not resolve") so a City the gazetteer
          doesn't cover still ships as a tagged state-only lead instead of
          being silently dropped a second, independent way.

Free, public, no login.
Slug: national.fdic_failed_banks
Category: reo
ListingType: DISTRESSED (see 2026-10-04 fix above -- was REO)
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ..._bankruptcy_city_to_county import bankruptcy_county_for
from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.fdic.gov/bank-failures/failed-bank-list"
# Complete historical export (578 rows back to 2000, live-verified 2026-10-04)
# linked from PAGE_URL's own "Download Data (CSV)" button. One fetch, no
# pagination -- see module docstring part 1.
CSV_URL = "https://www.fdic.gov/bank-failures/download-data.csv"

# The FDIC HTML table's State column is a full name ("Pennsylvania"), but
# every downstream scope check compares state.upper() against "NC"/"SC" -- a
# full name would never match, silently dropping any in-footprint bank
# failure. The CSV already gives 2-letter codes, but this is kept (and still
# applied) as a defensive no-op in case the export format ever reverts.
# Full US state-name map is overkill here (everything outside NC/SC gets
# filtered out anyway); only the two states this project tracks matter.
_STATE_NAME_TO_ABBR = {
    "NORTH CAROLINA": "NC",
    "SOUTH CAROLINA": "SC",
}


def _normalize_state(raw: str) -> str:
    s = (raw or "").strip()
    return _STATE_NAME_TO_ABBR.get(s.upper(), s)


def _detail_url_map(html: str) -> dict[str, str]:
    """Cert# -> per-bank FDIC detail-page URL, from the paginated HTML
    table's first page (the CSV has no link column at all). Cert# is a
    stable, exact-match key present in both sources, so this needs no
    bank-name / HTML-entity normalization to join against the CSV rows.
    Best-effort: a cert# not on this ~25-row first page (anything older)
    is simply absent from the returned map; the caller falls back to
    PAGE_URL for those.
    """
    out: dict[str, str] = {}
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
        if len(cells) < 4:
            continue
        cert = re.sub(r"<[^>]+>", "", cells[3]).strip()
        if not cert:
            continue
        dm = re.search(r'href="(/bank-failures/failed-bank-list/[^"]+)"', cells[0], re.I)
        if dm:
            out[cert] = urljoin(PAGE_URL, dm.group(1))
    return out


class FDICFailedBanks(BaseScraper):
    slug = "national.fdic_failed_banks"
    name = "FDIC Failed Bank List"
    category = "reo"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            csv_text = await get_text(CSV_URL, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("fdic.csv_fetch_fail", error=str(exc)[:160])
            return out

        if not csv_text or len(csv_text) < 100:
            return out

        # Best-effort only -- a failure here must never block the CSV data.
        # See _detail_url_map's docstring: this recovers the per-bank detail
        # link for current rows; it carries no address/portfolio data of its
        # own, so losing it entirely would be a cosmetic regression at most.
        cert_to_url: dict[str, str] = {}
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=30.0)
            if html:
                cert_to_url = _detail_url_map(html)
        except Exception as exc:
            log.info("fdic.detail_url_map_skip", error=str(exc)[:160])

        reader = csv.reader(io.StringIO(csv_text))
        for i, cells in enumerate(reader):
            if i == 0 or not cells:
                # Header row. Its own cells carry a stray encoding artifact
                # (U+FFFD after every column name, live-verified 2026-10-04,
                # harmless since we read by position) -- skipped by index,
                # not by sniffing content.
                continue
            if len(cells) < 6:
                continue
            clean = [c.strip() for c in cells]

            bank_name = clean[0]
            city = clean[1]
            state = _normalize_state(clean[2])
            cert_num = clean[3]
            acquiring = clean[4]
            fail_date_str = clean[5]
            fund_number = clean[6] if len(clean) > 6 and clean[6] else None

            if not bank_name or not state:
                continue

            try:
                fail_date = datetime.strptime(fail_date_str, "%d-%b-%y")
            except ValueError:
                fail_date = None

            # Only keep recent failures (last 2 years)
            if fail_date:
                days_ago = (datetime.now() - fail_date).days
                if days_ago > 730:
                    continue

            # County is never on the source table -- derive it from City via
            # the existing 146-county NC+SC gazetteer (see module docstring
            # part 2b). Harmless no-op for every non-NC/SC row (returns None).
            county = bankruptcy_county_for(city, state)

            detail_url = cert_to_url.get(cert_num, PAGE_URL)

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
                    # 2026-10-04 fix: was ListingType.REO -- see module
                    # docstring part 2a for why that silently zeroed every
                    # row via main._FLIP_LISTING_TYPES's narrow-footprint
                    # scope gate.
                    listing_type=ListingType.DISTRESSED,
                    street_address=f"{bank_name}",
                    city=city,
                    county=county,
                    state=state,
                    property_kind=PropertyKind.UNKNOWN,
                    raw=raw,
                    sale_date=fail_date,
                )
            )

        log.info("fdic.fetch_done", count=len(out))
        return out
