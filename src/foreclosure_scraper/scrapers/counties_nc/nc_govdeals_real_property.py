"""NC + SC GovDeals government real-property auctions (master feed, one file).

Built 2026-06-26 for the GOVDEALS REAL-PROPERTY track. NC and SC governments —
counties, cities/towns, school systems — liquidate surplus and tax-foreclosed
real property through GovDeals. The user originally named three target NC
sellers — Pender (legacy agency 22325), Burke (legacy seller 29265),
Transylvania (storefront "tcncre") — but the scope is now the GovDeals MASTER
real-estate feed for ALL NC + SC government sellers (e.g. City of Asheville,
Gaston County, Mount Airy, Yadkin County), so municipal/county surplus +
tax-foreclosed real property from any NC/SC seller is ingested. The parser keeps
EVERY real-property lot GovDeals surfaces and records county/state per row;
in-footprint scoping is applied downstream by the orchestrator.

WHY the master STATE feed rather than per-seller calls
------------------------------------------------------
GovDeals migrated off the old ColdFusion ``index.cfm`` storefront onto a
Liquidity Services Angular SPA backed by a JSON search service
(``maestro.lqdt1.com/search/list``). In that migration the legacy seller /
agency numbers (22325, 29265, the "tcncre" storefront slug) were re-namespaced:
they no longer resolve as the ``accountId`` the new search service filters on
(verified live 2026-06-26 — ``accountIds:[22325]`` and ``[29265]`` both return
0, while a current seller's real ``accountId`` filters correctly). Rather than
hard-code three brittle, already-stale numeric ids, this scraper queries the
Real Estate category (external id ``t11``) constrained to the ``state`` facet
for NC and SC — the SPA's own filters, the same ones the public site exposes.
That captures the WHOLE NC/SC government real-estate inventory (Pender / Burke /
Transylvania when active, plus City of Asheville, Gaston County, Mount Airy,
Yadkin County, the SC sellers, etc.) — a strict superset of the three named
sellers — without depending on those lots bubbling into the nationwide top
pages, and it survives the next id re-shuffle. The named legacy ids are recorded
below for provenance, and a per-seller ``accountIds`` pull is preserved as a
fallback (see ``_seller_account_body`` / ``fetch``) for any future seller whose
real accountId becomes known.

STATE FACET (verified live 2026-06-26)
--------------------------------------
The search response's ``assetSearchFacets`` exposes a ``state`` facet whose
filter token is ``{!tag=state}state:"NC"`` (resp. ``"SC"``). Passing that
alongside the category token constrains results server-side to one state. The
service does NOT honour a combined ``state:("NC" OR "SC")`` token (returns 0),
so we query each state separately and merge — two small paged pulls instead of
one ~900-row nationwide sweep.

ENDPOINT (free + compliant — the same SPA JSON the public site uses)
--------------------------------------------------------------------
GovDeals.com itself is an Angular SPA (a direct WebFetch / httpx GET of the
HTML returns the empty app shell, and the marketing host 403s a bare client),
exactly the GovDeals problem the porsche ``government_auctions`` subproject
flagged ("Angular SPA — needs XHR endpoint or headless"). The COMPLIANT answer
is the SPA's own public JSON search endpoint, reused here:

  POST https://maestro.lqdt1.com/search/list
  headers: x-api-key (the SPA's public key), x-user-id: -1 (anonymous),
           x-api-correlation-id / x-page-unique-id (per-request GUIDs)
  body:    businessId "GD", searchText "*", category via the facetsFilter
           product_category_external_id:"t11", paged by displayRows/page.

Plain httpx through the shared ``client()`` reaches it directly — no Akamai wall,
no headless browser, no CAPTCHA / login / WAF defeat. The key + endpoint are the
public values the unauthenticated site ships in its JS bundle.

Each result row carries city/state/zip (county attribution), the auction end
date, the current bid, and usually the street address + PIN inside
``assetShortDescription`` (e.g. "0.231 Acres on Carolina Avenue, Mount Airy, NC
27030 (PIN 501116835592)"). Some lots have a real ``locationAddress1``; many
(land parcels) carry the address only in the description, so we parse both.

TRANSYLVANIA legal-notice pairing
---------------------------------
Per the task, Transylvania is ALSO paired with the county's plain-HTTP
legal-notice feed (https://www.transylvaniacounty.org/news), which carries the
parcel PINs for tax-foreclosure notices of sale. We GET that page, scan for
notice-of-sale / foreclosure items, and pull any PIN tokens so a Transylvania
GovDeals lot can be cross-referenced to its recorded notice (and so a notice
with no GovDeals lot yet is still surfaced as a parcel-only lead). The feed is
meeting-notice heavy and frequently carries NO foreclosure notice at all
(verified 2026-06-26 — only meeting + surplus-personal-property notices live),
so this half legitimately yields 0 rows off-cycle; that is expected, not a bug.

DATELESS vs DATED
-----------------
GovDeals lots are timed auctions and almost always carry ``assetAuctionEndDate``
-> ``sale_date`` (DATED). A Transylvania legal-notice parcel pulled with no
parseable sale date is emitted DATELESS (sale_date=None); each row records
``raw[...]["dated"]`` so downstream can tell them apart.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Iterable, Optional

import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ..._coastal_city_to_county import coastal_county_for
from ..._upstate_city_to_county import upstate_county_for
from ...base_scraper import BaseScraper
from ...http_client import client, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SLUG = "counties_nc.nc_govdeals_real_property"

# GovDeals SPA public JSON search service (Liquidity Services "maestro").
GOVDEALS_SEARCH_API = "https://maestro.lqdt1.com/search/list"
# Public values shipped in the unauthenticated govdeals.com Angular bundle.
GOVDEALS_API_KEY = "af93060f-337e-428c-87b8-c74b5837d6cd"
# Asset detail page (built from accountId + assetId; matches the SPA's ct= link).
GOVDEALS_ASSET_URL = "https://www.govdeals.com/asset/{asset_id}/{account_id}"
# Real Estate category external id (t11) — the SPA's own category filter token.
REAL_ESTATE_FACET = '{!tag=product_category_external_id}product_category_external_id:"t11"'
# Per-state filter token from the response's ``state`` facet. {st} = NC | SC.
STATE_FACET = '{{!tag=state}}state:"{st}"'
# States we pull the master real-estate feed for. The service won't OR them in a
# single token, so we query each separately and merge.
FEED_STATES = ("NC", "SC")

# Named target sellers from the task. These are LEGACY GovDeals ids that no
# longer resolve as the post-migration accountId (see module docstring); kept
# for provenance and so the per-seller fallback can map them once a real
# accountId is known. Coverage is by the NC/SC master feed, which is a superset.
# Map name -> real numeric accountId (int) to activate the fallback for a seller;
# the legacy ids below are NON-resolving and stay None until a real id is found.
TARGET_SELLERS: dict[str, int | None] = {
    "Pender": None,         # legacy agency 22325 — non-resolving post-migration
    "Burke": None,          # legacy seller 29265 — non-resolving post-migration
    "Transylvania": None,   # legacy storefront "tcncre" — non-resolving
}

TRANSYLVANIA_NEWS = "https://www.transylvaniacounty.org/news"

# Pull cap. Each NC/SC state slice is small (verified live 2026-06-26: 9 NC + 1
# SC real-estate lots), but cap generously so a busier cycle (City of Asheville /
# Gaston County batch surplus sales) is captured in full. 100/page x 5 pages =
# 500 per state ceiling; pulls stop early when a short page is returned.
_PAGE_SIZE = 100
_MAX_PAGES = 5

# Street-suffix alternation reused by both address shapes below.
_SUFFIX = (
    r"(?:Road|Rd|Street|St|Drive|Dr|Avenue|Ave|Lane|Ln|Way|Court|Ct|Place|Pl|"
    r"Boulevard|Blvd|Highway|Hwy|Circle|Cir|Trail|Trl|Parkway|Pkwy|Terrace|Ter|"
    r"Loop|Run|Pike)"
)
# (a) A real house-numbered street, e.g. "320 E. Lee Avenue". The house number
#     must NOT be the tail of a decimal acreage ("0.231"), so it can't be
#     preceded by a digit or a dot.
_STREET_NUMBERED_RE = re.compile(
    r"(?<![\d.])\d{1,6}\s+[A-Za-z0-9.'\- ]+?" + _SUFFIX + r"\b", re.I
)
# (b) An acreage-described land parcel names its street after "on", e.g.
#     "0.231 Acres on Carolina Avenue" -> "Carolina Avenue". Capture just the
#     street name (not the acreage), which is the useful locator.
_STREET_ON_RE = re.compile(
    r"\bon\s+([A-Za-z0-9.'\- ]+?" + _SUFFIX + r")\b", re.I
)
# PIN / parcel token, e.g. "(PIN 501116835592)" / "PIN: 1234-56-7890".
_PIN_RE = re.compile(r"PIN[#:\s]*([0-9][0-9A-Za-z\-.]{4,})", re.I)


def _parse_dt(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    try:
        return dateparser.parse(s)
    except (ValueError, TypeError, OverflowError):
        return None


def _county_for(city: str | None, state: str | None) -> str | None:
    """Resolve a city to a footprint county via the upstate/WNC gazetteer first,
    then the coastal gazetteer (Pender, Brunswick, etc. live there)."""
    return upstate_county_for(city, state) or coastal_county_for(city, state)


def _county_from_company(name: str | None, state: str | None) -> str | None:
    """Pull a county out of a GovDeals seller name like
    "Burke County School System, NC" / "Yadkin County - Real Estate, NC"."""
    if not name:
        return None
    m = re.search(r"\b([A-Z][A-Za-z.]+(?:\s[A-Z][A-Za-z.]+)*?)\s+County\b", name)
    if not m:
        return None
    return m.group(1).strip()


# GovDeals files some PERSONAL property under the Real Estate (t11) category —
# "Portable Buildings and structures" is portable restrooms, mobile/modular
# classroom trailers, storage sheds, etc. (verified live 2026-06-26: a $110
# "14 X 38 Portable Restroom Unit" and $400/$500 mobile classrooms). These are
# not real property and must not become leads. Genuine lots use "Real Estate /
# Land Parcels", "Vacant Land - ...", "Commercial Property", "Single Family ...".
_NON_REALTY_CATEGORIES = {
    "portable buildings and structures",
}


def _is_real_property(category: str | None, desc: str | None) -> bool:
    cat = (category or "").strip().lower()
    if cat in _NON_REALTY_CATEGORIES:
        return False
    blob = f"{desc or ''}".lower()
    # Catch portable/mobile/modular UNITS that slip in under a benign category.
    if re.search(r"\b(portable|modular)\b.*\b(restroom|classroom|building|unit|trailer)\b",
                 blob):
        return False
    return True


def _property_kind(desc: str | None, category: str | None) -> PropertyKind:
    blob = f"{desc or ''} {category or ''}".lower()
    if any(k in blob for k in ("acre", "land parcel", "lot ", "vacant", "parcel")):
        return PropertyKind.LAND
    if "commercial" in blob:
        return PropertyKind.COMMERCIAL
    if any(k in blob for k in ("single family", "residential home", "house", "dwelling")):
        return PropertyKind.SINGLE_FAMILY
    if "mobile" in blob or "manufactured" in blob:
        return PropertyKind.MOBILE
    return PropertyKind.UNKNOWN


def _search_headers() -> dict[str, str]:
    return {
        "x-api-key": GOVDEALS_API_KEY,
        "x-user-id": "-1",  # anonymous buyer
        "x-api-correlation-id": str(uuid.uuid4()),
        "x-page-unique-id": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.govdeals.com",
        "Referer": "https://www.govdeals.com/",
    }


def _base_body(page: int) -> dict[str, Any]:
    """Common /search/list payload skeleton for the Real Estate category."""
    return {
        "categoryIds": "",
        "businessId": "GD",
        "searchText": "*",
        "isQAL": False,
        "locationId": None,
        "model": "",
        "makebrand": "",
        "auctionTypeId": None,
        "page": page,
        "displayRows": _PAGE_SIZE,
        "sortField": "bestfit",
        "sortOrder": "desc",
        "sessionId": str(uuid.uuid4()),
        "requestType": "search",
        "responseStyle": "fullResponse",
        "facets": ["sellerDisplayName", "state"],
        "facetsFilter": [REAL_ESTATE_FACET],
        "timeType": "",
        "sellerTypeId": None,
        "accountIds": [],
    }


def _state_body(page: int, state: str) -> dict[str, Any]:
    """Master real-estate feed constrained to one state (NC | SC) server-side."""
    body = _base_body(page)
    body["facetsFilter"] = [REAL_ESTATE_FACET, STATE_FACET.format(st=state)]
    return body


def _seller_account_body(page: int, account_id: int) -> dict[str, Any]:
    """Per-seller fallback: the SPA's accountIds filter for one known seller.

    Preserves the original per-seller behavior for any seller whose real
    post-migration accountId becomes known (the legacy ids in TARGET_SELLERS are
    non-resolving — see module docstring). Unused while every TARGET_SELLERS id
    is None; kept so coverage degrades gracefully to a direct seller pull.
    """
    body = _base_body(page)
    body["facetsFilter"] = [REAL_ESTATE_FACET]
    body["accountIds"] = [account_id]
    return body


def parse_asset(d: dict[str, Any]) -> Optional[Listing]:
    """Turn one GovDeals search-result asset into a Listing carrying county/state,
    or None when it isn't NC/SC real property we can attribute to a county.

    This is the MASTER NC/SC feed: we keep EVERY attributable NC/SC government
    real-property lot and record county/state on the row. In-footprint scoping is
    applied DOWNSTREAM by the orchestrator (main._in_scope + the coastal bypass),
    not here — so a Mount Airy / Yadkin / City-of-Asheville lot is emitted with
    its real county and the orchestrator decides whether it makes the board."""
    state = (d.get("locationState") or "").strip().upper() or None
    city = (d.get("locationCity") or "").strip() or None
    short_desc = (d.get("assetShortDescription") or "").strip() or None
    long_desc = (d.get("assetLongDescription") or "").strip() or None
    company = (d.get("companyName") or "").strip() or None

    # Master feed is NC/SC only. The state slice already constrains this, but the
    # per-seller fallback / any stray cross-listing could carry another state —
    # never emit non-NC/SC rows from this source.
    if state not in ("NC", "SC"):
        return None
    # County attribution: city gazetteer first, then the seller name. A row we
    # can't pin to a county is useless downstream, so drop it.
    county = _county_from_company(company, state) or _county_for(city, state)
    if not county:
        return None
    # Drop personal property mis-filed under the Real Estate category.
    if not _is_real_property(d.get("categoryDescription"), short_desc or long_desc):
        return None
    # NO in-footprint gate here — see the docstring. The orchestrator applies
    # footprint scope (and the coastal-county bypass) downstream; we keep every
    # attributable NC/SC government real-property lot with its county/state.

    asset_id = d.get("assetId")
    account_id = d.get("accountId")
    if asset_id is None or account_id is None:
        return None
    url = GOVDEALS_ASSET_URL.format(asset_id=asset_id, account_id=account_id)

    # Street address: prefer locationAddress1, else parse it out of the desc.
    # Try a real house-numbered street first; fall back to the "...on <Street>"
    # land-parcel form (don't mistake the leading acreage for a house number).
    street = (d.get("locationAddress1") or "").strip() or None
    if not street:
        for blob in (short_desc, long_desc):
            if not blob:
                continue
            m = _STREET_NUMBERED_RE.search(blob)
            if m:
                street = m.group(0).strip()
                break
            m = _STREET_ON_RE.search(blob)
            if m:
                street = m.group(1).strip()
                break

    # PIN / parcel from the description.
    parcel = None
    for blob in (short_desc, long_desc):
        if not blob:
            continue
        m = _PIN_RE.search(blob)
        if m:
            parcel = m.group(1).strip()
            break

    bid = d.get("currentBid")
    if bid in (None, 0, 0.0):
        bid = d.get("assetBidPrice")
    try:
        opening_bid = float(bid) if bid not in (None, "") else None
    except (TypeError, ValueError):
        opening_bid = None

    end_raw = d.get("assetAuctionEndDate") or d.get("assetAuctionEndDateUtc")
    sale_date = _parse_dt(end_raw)

    lat = d.get("latitude")
    lng = d.get("longitude")
    try:
        lat = float(lat) if lat not in (None, "") else None
        lng = float(lng) if lng not in (None, "") else None
    except (TypeError, ValueError):
        lat = lng = None

    return Listing(
        source=SLUG,
        source_url=url,
        listing_type=ListingType.AUCTION,
        property_kind=_property_kind(short_desc or long_desc, d.get("categoryDescription")),
        street_address=street,
        city=city,
        state=state,
        zip_code=(d.get("locationZip") or "").strip()[:5] or None,
        county=county,
        parcel_id=parcel,
        latitude=lat,
        longitude=lng,
        sale_date=sale_date,
        opening_bid=opening_bid,
        auction_status="active",
        description=(
            f"GovDeals real-property auction — {short_desc or long_desc or company or 'lot'}"
        )[:400],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "nc_govdeals_real_property": {
                "account_id": account_id,
                "asset_id": asset_id,
                "auction_id": d.get("auctionId"),
                "seller": company,
                "category": d.get("categoryDescription"),
                "dated": sale_date is not None,
                "current_bid": opening_bid,
            }
        },
    )


# ---------------------------------------------------------------------------
# Transylvania legal-notice feed — parcel PINs for tax-foreclosure notices.
# ---------------------------------------------------------------------------
_NOTICE_KEYWORDS = re.compile(
    r"foreclosure|notice of sale|tax sale|substitute trustee|upset bid|"
    r"surplus real|notice of foreclosure",
    re.I,
)


def parse_transylvania_notices(html: str, page_url: str = TRANSYLVANIA_NEWS) -> list[Listing]:
    """Scan the Transylvania County news feed for tax-foreclosure / notice-of-
    sale items and emit a parcel-only (usually DATELESS) lead per PIN found.

    The feed is dominated by meeting notices and frequently carries NO
    foreclosure notice (off-cycle), so an empty return here is expected. We only
    emit when an item's text both trips a foreclosure keyword AND yields a PIN,
    so a routine "Notice to Public: ... Meeting" never produces a phantom lead.
    """
    out: list[Listing] = []
    seen: set[str] = set()
    tree = HTMLParser(html)
    text = re.sub(r"\s+", " ", tree.text(separator=" ") or "")

    # Only bother if the page actually mentions a foreclosure-type notice.
    if not _NOTICE_KEYWORDS.search(text):
        return out

    # Pull PINs that sit near a foreclosure keyword (within ~200 chars).
    for km in _NOTICE_KEYWORDS.finditer(text):
        window = text[max(0, km.start() - 60): km.end() + 200]
        for pm in _PIN_RE.finditer(window):
            pin = pm.group(1).strip()
            if pin in seen:
                continue
            seen.add(pin)
            out.append(
                Listing(
                    source=SLUG,
                    source_url=page_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Transylvania",
                    parcel_id=pin,
                    foreclosure_process="tax",
                    auction_status="active",
                    description=(
                        "Transylvania County legal-notice tax-foreclosure "
                        f"(parcel {pin})"
                    ),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"nc_govdeals_real_property": {"county": "Transylvania",
                                                       "source_kind": "legal_notice",
                                                       "dated": False}},
                )
            )
    return out


class NCGovDealsRealProperty(BaseScraper):
    slug = SLUG
    name = "NC GovDeals County Real Property (Pender/Burke/Transylvania + footprint)"
    category = "county_auction"
    # GovDeals real-property turnover in any single footprint county is episodic;
    # a given run can legitimately surface 0 in-footprint lots.
    expected_min_count = 0
    timeout_s = 240.0

    async def _pull(
        self,
        c: Any,
        label: str,
        body_for_page,
        seen_keys: set[tuple[Any, Any]],
        out: list[Listing],
    ) -> int:
        """Page one /search/list slice (a state feed or a seller pull), dedup on
        (accountId, assetId), parse footprint rows into ``out``. Returns the
        number of NEW raw rows seen across all pages of this slice."""
        new_total = 0
        for page in range(1, _MAX_PAGES + 1):
            resp = await c.post(
                GOVDEALS_SEARCH_API,
                json=body_for_page(page),
                headers=_search_headers(),
            )
            resp.raise_for_status()
            rows = resp.json().get("assetSearchResults") or []
            if not rows:
                break
            new_on_page = 0
            for d in rows:
                key = (d.get("accountId"), d.get("assetId"))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                new_on_page += 1
                new_total += 1
                li = parse_asset(d)
                if li:
                    out.append(li)
            log.info("nc_govdeals.page", slice=label, page=page, rows=len(rows),
                     new=new_on_page, kept=len(out))
            if len(rows) < _PAGE_SIZE:
                break
        return new_total

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_keys: set[tuple[Any, Any]] = set()

        # GovDeals Real Estate MASTER feed, sliced per state (NC, SC) so the
        # whole NC/SC government inventory is captured regardless of nationwide
        # ranking. County/state is kept per row; footprint scoping is downstream.
        try:
            async with client(timeout=40.0) as c:
                for state in FEED_STATES:
                    await self._pull(
                        c, state,
                        lambda page, st=state: _state_body(page, st),
                        seen_keys, out,
                    )
                counties_seen = {f"{li.county},{li.state}" for li in out}

                # Per-seller FALLBACK — preserved original behavior. Only fires
                # for a named seller with a known real accountId whose county the
                # state feed did NOT already surface (graceful degradation if a
                # state slice ever 0s out while a seller pull still resolves).
                for name, account_id in TARGET_SELLERS.items():
                    if account_id is None:
                        continue
                    if any(name in cs for cs in counties_seen):
                        continue
                    n = await self._pull(
                        c, f"seller:{name}",
                        lambda page, aid=account_id: _seller_account_body(page, aid),
                        seen_keys, out,
                    )
                    log.info("nc_govdeals.seller_fallback", seller=name,
                             account_id=account_id, new=n)
            log.info("nc_govdeals.govdeals_done", footprint=len(out))
        except Exception as exc:  # noqa: BLE001
            log.warning("nc_govdeals.govdeals_failed", error=str(exc)[:200])

        # Transylvania legal-notice feed — parcel PINs (plain HTTP GET).
        try:
            html = await get_text(TRANSYLVANIA_NEWS, headers={"User-Agent": "Mozilla/5.0"})
            notices = parse_transylvania_notices(html)
            out.extend(notices)
            log.info("nc_govdeals.transylvania_notices", rows=len(notices))
        except Exception as exc:  # noqa: BLE001
            log.warning("nc_govdeals.transylvania_failed", error=str(exc)[:200])

        return out


# Run directly for quick iteration:
#   uv run python -m foreclosure_scraper.scrapers.counties_nc.nc_govdeals_real_property
if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        scraper = NCGovDealsRealProperty()
        results = await scraper.safe_run()
        print(f"parsed: {len(results)}  outcome={scraper.last_outcome}  "
              f"reason={scraper.last_reason!r}")
        by_county: dict[str, int] = {}
        dated = dateless = 0
        for x in results:
            by_county[f"{x.county}, {x.state}"] = by_county.get(f"{x.county}, {x.state}", 0) + 1
            if x.sale_date:
                dated += 1
            else:
                dateless += 1
        print(f"dated={dated} dateless={dateless}")
        for cs, n in sorted(by_county.items()):
            print(f"  {cs}: {n}")
        for x in results[:15]:
            print(f"  {x.county},{x.state} addr={x.street_address!r} pin={x.parcel_id} "
                  f"bid={x.opening_bid} date={x.sale_date} kind={x.property_kind.value} "
                  f"url={x.source_url}")

    asyncio.run(_main())
