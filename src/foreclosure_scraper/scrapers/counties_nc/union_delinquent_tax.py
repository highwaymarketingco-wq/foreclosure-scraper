"""Union County NC delinquent real-estate tax roll -- a confirmed-live Akamai wall on the
county's main CMS, bypassed with this project's OWN existing curl-cffi impersonation tier
(``http_client.get_text(..., impersonate=True)``), not a new bypass technique.

WHY THIS EXISTS (gap_matrix run 2026-11-11, bucket "bot_wall_inhouh" for Union, NC:
    multi_year_delinquent_tax / repeat_tax_loss / rollback_exposure / tax_aging_surfaced /
    two_year_delinquent, source "unioncountync.gov", next_action "Playwright + stealth").
    Before writing a line of bypass code, the wall was checked LIVE (2026-11-11, plain curl,
    a realistic desktop Chrome UA, no auth, no cookies):

        curl -A "<desktop Chrome UA>" https://www.unioncountync.gov
        -> HTTP/2 403, server: AkamaiGHost, ~400-byte block body

    Both the bare homepage AND the specific tax-foreclosure page 403 the same way -- this is a
    REAL, currently-live bot wall (Akamai Bot Manager, not Cloudflare -- the two WAF vendors
    get conflated in casual notes, but the block signature here is AkamaiGHost, confirmed by
    the `server` response header, not a cf-ray/cf-mitigated pair). Matches the project's own
    prior finding (docs/new_sources_2026-10-07_distress.md, docs/walled_sources_solutions.md
    "Union County NC -- Akamai"): this one has been a real wall for at least a month.

THE BYPASS, AND WHY IT IS NOT A NEW TECHNIQUE. `http_client.py` already documents a tiered
    fetch ladder (its own module docstring): plain httpx, then curl-cffi
    ``AsyncSession(impersonate="chrome")`` -- a real Chrome JA3/TLS + HTTP/2 fingerprint, NO
    browser process -- as the automatic escalation tier when a host is known to fingerprint-
    block (`get_text(..., impersonate=True)`). Tried live 2026-11-11 against the exact URL that
    403'd on a bare curl: the impersonation tier alone (no page JS, no sensor data, no browser)
    returns a clean HTTP 200 with the real page. Akamai's edge block here keys off the TLS/
    HTTP2 client fingerprint, not a JS challenge -- so the project's existing, lightest-weight
    stealth tier is already sufficient. This module therefore calls
    `http_client.get_text(url, impersonate=True)` exactly like every other scraper in this
    package; it does NOT reach for Scrapling/StealthyFetcher or any other real-browser tier
    (`wall_bypass=True` is never passed), both because the lighter tier already works and
    because launching a real headless-browser process from an unattended agent run on this
    machine is the thing this project's own operating notes say to avoid.

REAL DATA FOUND BEHIND THE WALL (live 2026-11-11, read-only, nothing written to the board by
    this discovery pass). The county's own nav chain (homepage -> "/business/tax-administration"
    -> "Property Tax Foreclosures" -> "...collection-payment/property-tax-foreclosure-auction")
    ends on a page whose body literally says "Delinquent Tax List - Updated 11/4/2026" (one week
    old at verification time -- a live, actively-maintained document, not a stale artifact) with
    a Granicus ``/home/showdocument?id=<N>&t=<token>`` link. Fetched: HTTP 200, Content-Type
    text/csv, 5,942 rows, columns "Property Display Name, Property Key, Year, Primary Source,
    Balance Due". ``Primary Source`` is "PP" (Personal Property -- vehicles/business personal,
    5,013 of 5,942 rows, the SAME non-lead noise Buncombe's layers carry in
    ``scrapers/counties_generic/multi_year_delinquent_tax.py``), "RE" (Real Estate, 926 rows /
    327 distinct parcels -- the actual lead population) or "RR" (3 rows, meaning unconfirmed --
    excluded rather than guessed at). Of the 327 RE parcels, 152 (46%) already carry >=2
    distinct delinquent years on this ONE export -- no separate per-year service to enumerate,
    unlike the Buncombe/Oconee/Pickens ArcGIS shape; Union publishes the whole multi-year roll
    as a single CSV.

THE DOC ID IS NOT STABLE. ``id=4792`` was today's value; like Charleston's tax-sale-listing
    PDFs (`charleston_delinquent_tax.py`) and Rutherford's cache-busted .xlsx
    (`rutherford_tax.py`), Granicus re-issues a new numeric id on every re-upload. This module
    re-discovers the link by anchor text ("Delinquent Tax List") on every run rather than
    hard-coding today's id, the same discipline those two modules already use for their own
    moving targets.

SHAPE, AND WHAT IS DELIBERATELY NOT CLAIMED. This CSV has no rollback code, no attorney-
    verification flag and no tax-sale/overage field anywhere in its five columns -- so only
    ONE of the five signals gap_matrix named for Union (multi_year_delinquent_tax) is actually
    buildable from this source; this module does not fabricate rollback_exposure,
    atty_tax_verified_confirmed, lt_tax_sale or lt_tax_sale_overage blocks it has no real field
    for. `raw['union_delinquent_tax']` carries the full per-parcel bill history (shape matching
    `enrichment_ptscloud_multiyear_tax.build_block`'s `by_year` contract: one
    {tax_year, total_due} dict per distinct unpaid year) so a later, better-informed enrichment
    can still restate it into other keys if a real field for them ever turns up. The shared
    `raw['multi_year_delinquent_tax']` block is built directly in this scraper (not a separate
    enrichment pass) by reusing `enrichment_ptscloud_multiyear_tax.build_block` unchanged --
    same MIN_YEARS=2 + matured-year gate every other producer of this key already uses, so a
    downstream consumer sees one consistent contract regardless of which producer filled it.

DATELESS. A standing "who currently owes" roll, no per-parcel event date -- same reasoning as
    every other county delinquent-tax source already in `main.DATELESS_OK_SOURCES`
    (`counties_sc.berkeley_paystar_tax` et al.); this slug must be added to that set too or
    every row here is filtered out as dateless.

Free, no API key, no login. Gate off with FORECLOSURE_UNION_NC_TAX=0.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Iterable, Optional
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...enrichment_ptscloud_multiyear_tax import build_block as _mydt_build_block
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_nc.union_delinquent_tax"

HOME = "https://www.unioncountync.gov"
# Stable page path (live-verified 2026-11-11); the showdocument id on it is NOT stable.
AUCTION_PAGE = f"{HOME}/government/departments-r-z/taxes-property/collection-payment/property-tax-foreclosure-auction"

ENABLED = os.environ.get("FORECLOSURE_UNION_NC_TAX") != "0"

# "PP" = personal property (vehicles/business personal) -- confirmed noise, same reasoning as
# Buncombe's current-levy/personal-property filter in the generic multi-year module. "RE" is
# the only confirmed real-estate code; an unrecognized code (seen once as "RR", 3 rows total in
# the 2026-11-11 export) is excluded rather than guessed at.
_REAL_ESTATE_CODES = {"RE"}

_DOC_LINK_RE = re.compile(
    r"<a\s+href=['\"]([^'\"]*?/home/showdocument\?id=\d+[^'\"]*)['\"][^>]*>\s*"
    r"<img[^>]*>\s*<span[^>]*>\s*Delinquent Tax List",
    re.I,
)
# Fallback: some renders put the anchor text before the href attribute order above changes.
_DOC_LINK_RE_FALLBACK = re.compile(
    r"Delinquent Tax List[^<]*</span>\s*</a>", re.I,
)
_HREF_RE = re.compile(r"href=['\"]([^'\"]*?/home/showdocument\?id=\d+[^'\"]*)['\"]", re.I)


def _money(s: str | None) -> Optional[float]:
    if not s:
        return None
    digits = re.sub(r"[^\d.]", "", s)
    if not digits or digits == ".":
        return None
    try:
        v = float(digits)
    except ValueError:
        return None
    return v if v > 0 else None


async def _discover_csv_url() -> Optional[str]:
    """Find today's "Delinquent Tax List" showdocument link on the auction page.

    The id= query param changes on every re-upload, so this re-reads the page every run
    instead of trusting a cached URL. Returns None (not a guessed URL) if the page's shape
    has changed enough that the anchor can't be found -- silent-wrong-URL is worse than zero.
    """
    html = await get_text(AUCTION_PAGE, impersonate=True, timeout=30.0)
    # Primary pattern: the exact button-link markup seen live 2026-11-11.
    m = _DOC_LINK_RE.search(html)
    if m:
        return urljoin(HOME, m.group(1))
    # Fallback: locate the "Delinquent Tax List" text block, then the nearest preceding
    # showdocument href within a short window (handles minor markup drift).
    m2 = _DOC_LINK_RE_FALLBACK.search(html)
    if m2:
        window = html[max(0, m2.start() - 600):m2.start()]
        hrefs = _HREF_RE.findall(window)
        if hrefs:
            return urljoin(HOME, hrefs[-1])
    return None


def _parse_csv(text: str) -> list[dict]:
    """Rows as dicts keyed by the CSV's own header; tolerant of the trailing blank column."""
    import csv
    import io

    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        rows.append(row)
    return rows


def build_listings(rows: list[dict], *, today: Optional[date] = None,
                    source_url: str = AUCTION_PAGE) -> list[Listing]:
    """Pure: CSV rows -> one Listing per distinct real-estate parcel.

    Groups by Property Key, keeps only rows whose Primary Source is a confirmed real-estate
    code, and reuses `enrichment_ptscloud_multiyear_tax.build_block` (unchanged) to compute the
    shared `multi_year_delinquent_tax` block when a parcel clears the >=2-matured-year gate.
    """
    today = today or date.today()
    by_parcel: dict[str, list[dict]] = {}
    owner_by_parcel: dict[str, str] = {}
    for r in rows:
        src = (r.get("Primary Source") or "").strip().upper()
        if src not in _REAL_ESTATE_CODES:
            continue
        parcel = (r.get("Property Key") or "").strip()
        year = (r.get("Year") or "").strip()
        amount = _money(r.get("Balance Due"))
        if not parcel or not year or amount is None:
            continue
        by_parcel.setdefault(parcel, []).append({"tax_year": year, "total_due": amount})
        owner_by_parcel.setdefault(parcel, (r.get("Property Display Name") or "").strip())

    out: list[Listing] = []
    for parcel, by_year in by_parcel.items():
        total_owed = round(sum(e["total_due"] for e in by_year), 2)
        years = sorted({e["tax_year"] for e in by_year})
        mydt = _mydt_build_block(parcel, "NC", "Union", by_year, tenant=None, today=today)
        if mydt:
            # build_block's own fallback source_url/layers are the ptscloud/BillPWA module's
            # defaults (it has no Union-specific values to fall back to) -- overwrite both so
            # a downstream reader of the SHARED multi_year_delinquent_tax key sees where this
            # one actually came from, not another county's vendor.
            mydt["source_url"] = source_url
            mydt["layers"] = ["union_nc_granicus_delinquent_tax_list"]
        desc_bits = [
            f"Union County NC delinquent real-estate tax (parcel {parcel})",
            f"{len(years)} unpaid tax year(s) ({years[0]}-{years[-1]})" if len(years) > 1
            else f"tax year {years[0]}",
            f"total owed ${total_owed:,.2f}",
        ]
        out.append(Listing(
            source=SLUG,
            source_url=source_url,
            listing_type=ListingType.TAX_LIEN,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county="Union",
            parcel_id=parcel,
            owner_name=owner_by_parcel.get(parcel) or None,
            judgment_amount=total_owed,
            foreclosure_process="tax",
            description=" | ".join(desc_bits)[:300],
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={
                "union_delinquent_tax": {
                    "parcel_key": parcel,
                    "by_year": by_year,
                    "years": years,
                    "total_owed": total_owed,
                    "source_url": source_url,
                },
                **({"multi_year_delinquent_tax": mydt} if mydt else {}),
            },
        ))
    return out


class UnionDelinquentTax(BaseScraper):
    slug = SLUG
    name = "Union County (NC) Delinquent Real-Estate Tax Roll"
    category = "county_tax"
    expected_min_count = 0  # the county can take the list down between re-uploads
    requires_apify = False
    timeout_s = 90.0

    async def fetch(self) -> Iterable[Listing]:
        if not ENABLED:
            return []
        try:
            csv_url = await _discover_csv_url()
        except Exception as exc:  # noqa: BLE001
            log.warning("union_delinquent_tax.discover_fail", error=str(exc)[:200])
            return self.partial
        if not csv_url:
            log.warning("union_delinquent_tax.no_doc_link_found")
            return self.partial

        try:
            text = await get_text(csv_url, impersonate=True, timeout=60.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("union_delinquent_tax.csv_fetch_fail", url=csv_url, error=str(exc)[:200])
            return self.partial

        rows = _parse_csv(text)
        out = build_listings(rows, source_url=csv_url)
        log.info("union_delinquent_tax.done", csv_rows=len(rows), parcels=len(out),
                 multi_year=sum(1 for li in out if li.raw.get("multi_year_delinquent_tax")))
        return out
