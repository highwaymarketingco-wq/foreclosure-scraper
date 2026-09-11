"""Catalis/Sturgis county tax API -> the SC delinquent roll WITH the owner's mailing address.

WHY THIS EXISTS ALONGSIDE qpaybill_delinquent_roll
    The qPayBill roll covers 19 SC counties and gives parcel, owner, situs and balance --
    but no owner MAILING address, and it does not cover Pickens at all (its treasurer is
    on a different vendor). SC owner contact runs 8-18% against NC's 50-89%, and the
    per-county coverage matrix names it the binding constraint in every SC county. This
    API returns the mailing address on every record.

    Pickens is a FOOTPRINT county, so this is not a statewide-distressed addition: it is
    the seventh SC foreclosure county finally getting a delinquent-tax lane.

WHAT A RECORD CARRIES (verified live 2026-09-10, prefix "AB": 390 records, 80 of them
real-property Delinquent, and 80 of 80 carried a mailing address)
    ParcelNumber      4192-00-96-2106            the county TMS
    BillingID         ...0001763                 per-bill id, so multi-year rows are distinct
    RecordType        "Delinquent"               THE delinquency marker. `isDelinquent` is a
                                                 different, vehicle-oriented flag and was
                                                 False on every delinquent real-property row.
    OwnerName1/2      ABEL SEBASTIN
    OwnerAddress      {Line1, Line2, Line3, City, State, Zip}   <- the MAILING address
    SitusAddress      {Line1, ...}               situs, or the mobile-home description
    Values            Appraised, Assessed, and the appraisal split BY ASSESSMENT RATIO:
                      Building/Land Appraisal_4Pct vs _6Pct vs _10pt5Pct. SC law sets 4%
                      for an owner-occupied legal residence and 6% for everything else, so
                      a record whose value sits entirely in the 6% columns is
                      authoritatively NOT the owner's residence -- the same free absentee
                      signal the qPayBill detail page gives, but without a second request.
    CountyValues      GrossTax, Mills, HomesteadExemption, LegalResidenceExemption
    Classes, District, Description, TaxSaleRedemptionDate

ENUMERATION
    POST /Records {"year":-1, "payStatus":"Unpaid", "type":"Property", "parameter":"Name",
    "value":<prefix>} over A-Z0-9, deepening any prefix that fills the 1,000-record cap.
    The `type` filter does NOT actually exclude vehicles -- measured: 390 records for "AB"
    of which only 80 were real property -- so RealPropertyType is filtered client-side.
    Same self-verifying shape as the qPayBill roll: a result under the cap proves the
    prefix is exhausted.

ACCESS POSTURE -- READ THIS BEFORE CHANGING IT
    The API host d1ebsyxxbc7tep.cloudfront.net serves `User-agent: * / Disallow: /`. That
    is a blanket crawler exclusion on the CDN host, not a terms-of-service prohibition:
    there is no login, no CAPTCHA, no click-through terms, and the application it backs is
    the county's own public tax search, which pickenscountysctax.us invites the public to
    use. It was raised with the operator on 2026-09-10 and he authorised this class of
    source explicitly.

    That authorisation does NOT extend to a written ToS prohibition. SC PublicIndex stays
    closed -- its disclaimer expressly forbids automated querying and the operator accepts
    that disclaimer to reach the search. Logins, paywalls and CAPTCHA walls stay closed too.

    Because robots asks us not to crawl, this is deliberately gentle: a low concurrency
    cap, a real browser UA with the county site as Referer/Origin (the same headers the
    county's own page sends), a bounded request budget, and no detail fetch unless asked.

Free, public, no login.
Slug: counties_sc.sc_catalis_delinquent_roll
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_CDN = "https://d1ebsyxxbc7tep.cloudfront.net/data"

#: county -> (data GUID, the county site that fronts it). The GUID in the site's HTML is a
#: CMS id and is NOT the data id; the data id comes from the app bundle's API calls.
CATALIS_COUNTIES: dict[str, tuple[str, str]] = {
    "Pickens": ("c9ab58ea-c187-4c02-ad9d-b18dd6167431", "https://pickenscountysctax.us"),
}

#: Server-side result cap per query, observed. A full page means "deepen the prefix".
PAGE_CAP = 1000
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MAX_PREFIX_DEPTH = int(os.getenv("CATALIS_ROLL_DEPTH", "3"))
REQUEST_BUDGET = int(os.getenv("CATALIS_ROLL_BUDGET", "600"))
#: Deliberately gentle. The host's robots asks not to be crawled, and it enforces with
#: HTTP 429 -- a 600-request burst at concurrency 3 got the sweep rate-limited for minutes
#: afterwards. Low concurrency plus a pace delay reads the same roll without tripping it.
#: MEASURED 2026-09-11, the hard way. A 600-request burst at concurrency 3 exhausted
#: whatever per-IP quota this host enforces. A later run at concurrency 1 with a 1.0s
#: pace still took 57 HTTP 429s in 32 minutes, abandoned 11 name prefixes after five
#: attempts each, and never captured a single lead -- the quota had not reset. The host
#: also serves `Disallow: /`. Both facts point the same way: this source is a SLOW
#: background job, not something to run on demand.
#:
#: 8s between requests is roughly 450/hour, which reads Pickens' ~2,600 delinquent
#: parcels in a couple of unattended hours without tripping the limiter. Raise the pace
#: before raising concurrency; concurrency is what got us banned the first time.
_CONCURRENCY = int(os.getenv("CATALIS_ROLL_CONCURRENCY", "1"))
_PACE_S = float(os.getenv("CATALIS_ROLL_PACE_S", "8.0"))
_BACKOFF_S = float(os.getenv("CATALIS_ROLL_BACKOFF_S", "30.0"))


def _headers(site: str) -> dict:
    return {"User-Agent": _UA, "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": f"{site}/taxes.html", "Origin": site}


def _addr(block) -> str | None:
    """Flatten Catalis's {Line1,Line2,Line3,City,State,Zip} into one line.

    City arrives as 'PICKENS                 SC' -- name and state in one padded field,
    with State itself null -- so whitespace is collapsed rather than assuming the parts.
    """
    if not isinstance(block, dict):
        return None
    parts = [block.get("Line1"), block.get("Line2"), block.get("Line3"),
             block.get("City"), block.get("State"), block.get("Zip")]
    out = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    out = " ".join(out.split())
    return out or None


def is_delinquent_real_property(rec: dict) -> bool:
    """The two filters that matter, and why neither is the obvious one.

    `type: "Property"` in the request does NOT exclude vehicles -- 390 records came back
    for prefix "AB" and only 80 were real property. And `isDelinquent` was False on every
    single delinquent real-property row; the real marker is RecordType == "Delinquent".
    """
    if rec.get("RealPropertyType") is not True:
        return False
    return str(rec.get("RecordType") or "").strip().lower() == "delinquent"


def owner_occupancy(values: dict | None) -> bool | None:
    """SC assessment ratio as an owner-occupancy verdict.

    4% is the owner-occupied legal-residence ratio and 6% is everything else, so value
    sitting in the 6% columns says the county does not treat this as the owner's home.
    Returns None when neither side carries value -- never False, because False asserts
    "the county says this is not their residence" and inventing that would put a
    homeowner on an absentee list.
    """
    if not isinstance(values, dict):
        return None
    def s(*keys) -> float:
        return sum(float(values.get(k) or 0) for k in keys)
    four = s("BuildingAppraisal_4Pct", "LandAppraisal_4Pct")
    six = s("BuildingAppraisal_6Pct", "LandAppraisal_6Pct",
            "BuildingAppraisal_10pt5Pct", "LandAppraisal_10pt5Pct")
    if four <= 0 and six <= 0:
        return None
    return four > six


def to_listing(county: str, rec: dict) -> Listing | None:
    parcel = (rec.get("ParcelNumber") or "").strip() or None
    if not parcel:
        return None
    vals = rec.get("Values") if isinstance(rec.get("Values"), dict) else {}
    cv = rec.get("CountyValues") if isinstance(rec.get("CountyValues"), dict) else {}
    owner = " ".join(x for x in (rec.get("OwnerName1"), rec.get("OwnerName2"))
                     if x and str(x).strip()) or None
    mailing = _addr(rec.get("OwnerAddress"))
    situs = _addr(rec.get("SitusAddress"))
    occ = owner_occupancy(vals)
    appraised = vals.get("Appraised")
    now = datetime.utcnow()
    return Listing(
        source="counties_sc.sc_catalis_delinquent_roll",
        source_url=CATALIS_COUNTIES[county][1],
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county=county,
        parcel_id=parcel,
        defendant=owner,
        owner_name=owner,
        street_address=situs,
        tax_value=float(appraised) if appraised not in (None, "", 0) else None,
        description=(f"Delinquent property tax {rec.get('Year')}: "
                     f"appraised ${float(appraised or 0):,.0f}"
                     + ("" if occ is None else
                        f", {'owner-occupied (4%)' if occ else 'NOT owner-occupied (6%)'}")),
        first_seen=now, last_seen=now,
        raw={"catalis_roll": {
            "county": county,
            "parcel_number": parcel,
            "billing_id": rec.get("BillingID"),
            "year": rec.get("Year"),
            "record_type": rec.get("RecordType"),
            "owner": owner,
            # THE FIELD THIS SOURCE EXISTS FOR.
            "owner_mailing": mailing,
            "situs_address": situs,
            "appraised": appraised,
            "assessed": vals.get("Assessed"),
            "owner_occupied": occ,
            "appraisal_4pct": (vals.get("BuildingAppraisal_4Pct") or 0) + (vals.get("LandAppraisal_4Pct") or 0),
            "appraisal_6pct": (vals.get("BuildingAppraisal_6Pct") or 0) + (vals.get("LandAppraisal_6Pct") or 0),
            "gross_tax": cv.get("GrossTax"),
            "mills": cv.get("Mills"),
            "homestead_exemption": cv.get("HomesteadExemption"),
            "legal_residence_exemption": cv.get("LegalResidenceExemption"),
            "district": rec.get("District"),
            "description": rec.get("Description"),
            "tax_sale_redemption_date": rec.get("TaxSaleRedemptionDate"),
            "id_hash": rec.get("IDHash"),
        }},
    )


class _Budget:
    def __init__(self, n: int) -> None:
        self.left, self.spent = n, 0

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        self.spent += 1
        return True


async def sweep_county(county: str, guid: str, site: str,
                       budget: _Budget) -> tuple[list[dict], dict]:
    """Adaptive name-prefix sweep. Returns (delinquent real-property records, stats)."""
    seen: dict[str, dict] = {}
    stats = {"queries": 0, "errors": 0, "records_seen": 0, "capped": 0,
             "truncated_prefixes": 0}
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(client: httpx.AsyncClient, prefix: str) -> bool:
        if not budget.take():
            return False
        payload = {"year": -1, "payStatus": "Unpaid", "type": "Property",
                   "parameter": "Name", "value": prefix}
        async with sem:
            rows = None
            for attempt in range(5):
                try:
                    r = await client.post(f"{_CDN}/{guid}/Records", json=payload)
                    # A 429 MUST NOT look like an empty prefix. The first version of this
                    # returned `rows = r.json()` without checking the status, so when the
                    # host started rate-limiting after a 600-request burst the sweep
                    # reported queries=36, records_seen=0, errors=0 and leads=0 -- a clean
                    # log for a county whose roll it had entirely failed to read.
                    if r.status_code == 429:
                        stats["rate_limited"] = stats.get("rate_limited", 0) + 1
                        wait = float(r.headers.get("Retry-After") or 0) or _BACKOFF_S * (2 ** attempt)
                        log.info("catalis_roll.rate_limited", county=county, prefix=prefix,
                                 attempt=attempt + 1, sleeping=round(wait, 1))
                        await asyncio.sleep(min(wait, 120.0))
                        continue
                    r.raise_for_status()
                    parsed = r.json()
                    if not isinstance(parsed, list):
                        raise ValueError(f"expected a list, got {type(parsed).__name__}")
                    rows = parsed
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 4:
                        stats["errors"] += 1
                        stats.setdefault("lost_prefixes", []).append(prefix)
                        log.warning("catalis_roll.query_lost", county=county,
                                    prefix=prefix, error=str(exc)[:120],
                                    note="this prefix contributed nothing; the roll is "
                                         "INCOMPLETE for owners whose name starts with it")
                        return False
                    await asyncio.sleep(_BACKOFF_S * (2 ** attempt))
            if rows is None:
                stats["errors"] += 1
                stats.setdefault("lost_prefixes", []).append(prefix)
                log.warning("catalis_roll.rate_limit_gave_up", county=county, prefix=prefix,
                            note="still 429 after 5 attempts; roll INCOMPLETE for this prefix")
                return False
            await asyncio.sleep(_PACE_S)
        stats["queries"] += 1
        stats["records_seen"] += len(rows)
        for rec in rows:
            if is_delinquent_real_property(rec):
                key = str(rec.get("BillingID") or f"{rec.get('ParcelNumber')}:{rec.get('Year')}")
                seen[key] = rec
        if len(rows) >= PAGE_CAP:
            stats["capped"] += 1
            return True
        return False

    async with httpx.AsyncClient(timeout=90.0, headers=_headers(site)) as client:
        frontier = list(_ALPHABET)
        depth = 1
        while frontier and depth <= MAX_PREFIX_DEPTH:
            res = await asyncio.gather(*(one(client, p) for p in frontier))
            nxt = [p + ch for p, capped in zip(frontier, res) if capped for ch in _ALPHABET]
            if nxt and depth >= MAX_PREFIX_DEPTH:
                stats["truncated_prefixes"] = len({p[:-1] for p in nxt})
                log.warning("catalis_roll.depth_truncated", county=county,
                            prefixes=sorted({p[:-1] for p in nxt})[:10],
                            note="still filling the cap at max depth; raise CATALIS_ROLL_DEPTH")
            frontier = nxt
            depth += 1
    return list(seen.values()), stats


class SCCatalisDelinquentRoll(BaseScraper):
    slug = "counties_sc.sc_catalis_delinquent_roll"
    name = "SC Catalis/Sturgis Delinquent Roll (owner mailing address)"
    category = "county_tax"
    timeout_s = 600.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        only = {c.strip().title() for c in
                (os.getenv("CATALIS_ROLL_COUNTIES") or "").split(",") if c.strip()}
        targets = {k: v for k, v in CATALIS_COUNTIES.items() if not only or k in only}
        t0 = time.monotonic()
        out: list[Listing] = []
        for county, (guid, site) in sorted(targets.items()):
            budget = _Budget(REQUEST_BUDGET)
            try:
                recs, stats = await sweep_county(county, guid, site, budget)
            except Exception as exc:  # noqa: BLE001
                log.warning("catalis_roll.county_failed", county=county,
                            error=str(exc)[:140])
                continue
            got = [li for li in (to_listing(county, r) for r in recs) if li]
            out.extend(got)
            mailing = sum(1 for li in got
                          if li.raw["catalis_roll"].get("owner_mailing"))
            absentee = sum(1 for li in got
                           if li.raw["catalis_roll"].get("owner_occupied") is False)
            log.info("catalis_roll.county_done", county=county, leads=len(got),
                     with_owner_mailing=mailing, not_owner_occupied=absentee,
                     requests=budget.spent, **stats)
            if budget.left <= 0:
                log.warning("catalis_roll.budget_exhausted", county=county,
                            note="roll INCOMPLETE; raise CATALIS_ROLL_BUDGET")
        log.info("catalis_roll.done", leads=len(out),
                 seconds=round(time.monotonic() - t0, 1))
        return out
