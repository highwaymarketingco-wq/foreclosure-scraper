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

COUNTIES (added 2026-09-21 from docs/county_breadth_research_2026-09-21.md, each verified
live with ONE request through the same POST /Records call)
    Pickens    c9ab58ea-c187-4c02-ad9d-b18dd6167431  pickenscountysctax.us     (original)
    Chester    61020303-8d26-4a16-b995-6deb1def7d97  chestercountysctax.com    zero board rows before
    Hampton    38077f99-bf3d-48df-8d9a-467eb4de0d64  hamptoncountytax.org      zero board rows before
    Fairfield  89835e71-6978-4dc5-a0a8-17306a76b81f  fairfieldsctax.com        zero board rows before
    Aiken      27a11acb-7de9-43e7-a078-f98cfb4fc397  aikencountysctax.com      12 board rows before

    The four new counties do NOT share Pickens' record shape, and the research note said
    they did ("same schema, no parser change"). Measured 2026-09-21 on one prefix each:

      * Chester, Hampton   RecordType "Delinquent" + RealPropertyType True, exactly like
                           Pickens. Chester also carries an AssessorData block: the CURRENT
                           owner and the deed sale, while OwnerName1 is the name the bill was
                           issued to. On Chester 48 of 71 delinquent rows differ between the
                           two, so the current owner is used and the billed name is kept.
      * Fairfield          RecordType "Real" (not "Delinquent"), RealPropertyType is null, and
                           the delinquency marker is DelqSw True. The situs is in Description.
      * Aiken              RealPropertyType is null on every row. Real-property delinquents
                           are RecordType "Delinquent" WITH a ParcelNumber and DelqSw True;
                           the "Delinquent" rows with no parcel and a BillingID starting "M"
                           or "P" are business personal property (19 of 47 in one prefix).
                           125 of 740 rows were "Mobile Home" bills with DelqSw True; those
                           are excluded unless CATALIS_ROLL_MOBILE_HOMES=1, because a
                           mobile-home bill is a personal-property tax on a unit that may sit
                           on someone else's land. Aiken responses run about 3 MB a prefix.

    Each county therefore has a CountyRule. The default rule is Pickens' behaviour unchanged.

WHAT ELSE CHANGED IN THE SAME EDIT
    * The balance was never captured. Values.AmountDue (base tax + penalty + costs) is now
      written to raw["catalis_roll"]["total_due"] and to raw["tax_owed"], which is what the
      scorer's recorded_debt signal and the debt-aware ranking read.
    * A 403 stops the sweep. weekend_runner.sh records that this host escalated 429 -> 403
      against the Pickens sweep on 2026-09-11 and that working around a 403 is off the table.
      The old loop retried a 403 five times with backoff; it now raises CatalisBlocked once,
      the county is reported blocked, and the remaining counties (same host) are skipped.
    * Rows are appended to self.partial as they arrive, so a soft timeout ships what was read
      instead of nothing (this scraper's 600 s timeout covers only about 75 requests at an
      8 s pace, so it used to return [] in a pipeline run).
    * street_address is set only when the text looks like a street address. Mobile-home
      descriptions ("1987 HORTON 14 X 56 10458657") and legal fragments go to
      legal_description instead of poisoning the address dedupe key.
    * Listing type: a row with a TaxSaleRedemptionDate is TAX_SALE (a real sale happened and
      the redemption clock is running). A standing roll is TAX_LIEN for the four new counties.
      Pickens stays TAX_SALE, unchanged, because its rows are already on the board that way
      and the scorer weights a dateless TAX_SALE the same as TAX_LIEN (20).

Free, public, no login.
Slug: counties_sc.sc_catalis_delinquent_roll
Category: county_tax
ListingType: TAX_LIEN (standing roll, new counties) / TAX_SALE (Pickens, or a recorded sale)
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_CDN = "https://d1ebsyxxbc7tep.cloudfront.net/data"

SLUG = "counties_sc.sc_catalis_delinquent_roll"

#: county -> (data GUID, the county site that fronts it). The GUID in the site's HTML is a
#: CMS id and is NOT the data id; the data id comes from the app bundle's API calls.
CATALIS_COUNTIES: dict[str, tuple[str, str]] = {
    "Pickens": ("c9ab58ea-c187-4c02-ad9d-b18dd6167431", "https://pickenscountysctax.us"),
    # Added 2026-09-21, each verified live with one POST /Records (docstring above).
    "Chester": ("61020303-8d26-4a16-b995-6deb1def7d97", "https://chestercountysctax.com"),
    "Hampton": ("38077f99-bf3d-48df-8d9a-467eb4de0d64", "https://hamptoncountytax.org"),
    "Fairfield": ("89835e71-6978-4dc5-a0a8-17306a76b81f", "https://fairfieldsctax.com"),
    "Aiken": ("27a11acb-7de9-43e7-a078-f98cfb4fc397", "https://aikencountysctax.com"),
}

#: Cheapest county first. Aiken answers about 3 MB a prefix, so it goes last: if the soft
#: timeout fires, the small counties are already in self.partial.
SWEEP_ORDER = ("Pickens", "Chester", "Hampton", "Fairfield", "Aiken")

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


class CatalisBlocked(RuntimeError):
    """The host answered 403. That is the host declining, not a rate limit: stop, do not
    retry, do not work around it (scripts/weekend_runner.sh, 2026-09-11)."""


@dataclass(frozen=True)
class CountyRule:
    """How one county's Catalis records say "delinquent real property".

    The default is Pickens' behaviour exactly (RecordType "Delinquent" and
    RealPropertyType True), so the original county is unchanged.
    """
    record_types: tuple[str, ...] = ("delinquent",)   # lower-cased RecordType values
    require_real_flag: bool = True      # RealPropertyType must be True
    require_delq_sw: bool = False       # DelqSw must be True
    require_parcel: bool = False        # ParcelNumber present and digit-led (not business personal property)
    allow_mobile_homes: bool = False    # RecordType "Mobile Home" admitted when CATALIS_ROLL_MOBILE_HOMES=1
    standing_type: ListingType = ListingType.TAX_LIEN
    aggregate_by_parcel: bool = True    # one lead per parcel with the years summed
    max_depth: int | None = None
    budget: int | None = None


#: Pickens, unchanged: one row per bill (BillingID is unique per bill there), TAX_SALE.
RULE_DEFAULT = CountyRule(standing_type=ListingType.TAX_SALE, aggregate_by_parcel=False)

COUNTY_RULES: dict[str, CountyRule] = {
    "Pickens": RULE_DEFAULT,
    "Chester": CountyRule(),
    "Hampton": CountyRule(),
    "Fairfield": CountyRule(record_types=("real", "delinquent"), require_real_flag=False,
                            require_delq_sw=True, require_parcel=True, allow_mobile_homes=True),
    "Aiken": CountyRule(record_types=("delinquent", "real"), require_real_flag=False,
                        require_delq_sw=True, require_parcel=True, allow_mobile_homes=True,
                        max_depth=2, budget=400),
}


def rule_for(county: str) -> CountyRule:
    return COUNTY_RULES.get(county, RULE_DEFAULT)


def _mobile_homes_on() -> bool:
    return os.getenv("CATALIS_ROLL_MOBILE_HOMES", "").strip().lower() in ("1", "true", "yes")


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


#: A parcel id that belongs to real property: digit-led ("061-02-00-021-000",
#: "4192-00-96-2106"). Aiken's business personal property carries no parcel at all and a
#: BillingID starting "M" or "P".
_PARCEL_SHAPE = re.compile(r"^\d[\d\-.A-Za-z]{3,}$")


def is_delinquent_real_property(rec: dict, rule: CountyRule | None = None) -> bool:
    """The filters that matter, and why none is the obvious one.

    `type: "Property"` in the request does NOT exclude vehicles -- 390 records came back
    for prefix "AB" and only 80 were real property. And `isDelinquent` was False on every
    single delinquent real-property row in Pickens; the real marker is RecordType ==
    "Delinquent". Other counties differ (see CountyRule): Fairfield says "Real" and marks
    delinquency with DelqSw, Aiken leaves RealPropertyType null.
    """
    rule = rule or RULE_DEFAULT
    rtype = str(rec.get("RecordType") or "").strip().lower()
    allowed = set(rule.record_types)
    if rule.allow_mobile_homes and _mobile_homes_on():
        allowed.add("mobile home")
    if rtype not in allowed:
        return False
    if rule.require_real_flag and rec.get("RealPropertyType") is not True:
        return False
    if rule.require_delq_sw and rec.get("DelqSw") is not True:
        return False
    if rule.require_parcel:
        parcel = str(rec.get("ParcelNumber") or "").strip()
        if not parcel or not _PARCEL_SHAPE.match(parcel):
            return False
    return True


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


_STREET_SUFFIX = (
    r"ST|STREET|RD|ROAD|DR|DRIVE|LN|LANE|CT|COURT|CIR|CIRCLE|AVE|AVENUE|BLVD|HWY|HIGHWAY|"
    r"WAY|TRL|TRAIL|PL|PLACE|PKWY|PARKWAY|LOOP|TER|TERRACE|CV|COVE|RUN|PT|POINT|PIKE|ALY|"
    r"XING|SQ|BND|BEND|RDG|RIDGE|PATH|ROW"
)
#: A house number, up to five words, then a street suffix ("1306 SEIVERN RD",
#: "198 OLD CHEROKEE INDIAN RD", "1521 SUMNER AVE Lot 5"). "1994 FLEETWOOD" is a
#: mobile-home description, not an address, and has no suffix.
_STREET_RE = re.compile(
    rf"^\d{{1,6}}[A-Z]?\s+(?:[A-Za-z0-9.'#&-]+\s+){{0,5}}?(?:{_STREET_SUFFIX})\b", re.I)


def looks_like_street_address(text: str | None) -> bool:
    return bool(text and _STREET_RE.match(text.strip()))


def _parse_dt(v) -> datetime | None:
    if not v:
        return None
    s = str(v).strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26] if "." in s else s[:19], fmt)
        except ValueError:
            continue
    return None


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _clean(v) -> str | None:
    if v is None:
        return None
    out = " ".join(str(v).split())
    return out or None


def to_listing(county: str, rec: dict) -> Listing | None:
    parcel = (rec.get("ParcelNumber") or "").strip() or None
    if not parcel:
        return None
    rule = rule_for(county)
    vals = rec.get("Values") if isinstance(rec.get("Values"), dict) else {}
    cv = rec.get("CountyValues") if isinstance(rec.get("CountyValues"), dict) else {}
    assessor = rec.get("AssessorData") if isinstance(rec.get("AssessorData"), dict) else {}
    billed = " ".join(x for x in (rec.get("OwnerName1"), rec.get("OwnerName2"))
                      if x and str(x).strip()) or None
    # Chester carries the county assessor's CURRENT owner beside the name the bill was
    # issued to. The current owner is the person who holds the property and the one the
    # mailing address in OwnerAddress is written to ("c/o ..."), so it leads.
    current = _clean(assessor.get("OwnerName"))
    owner = current or billed
    mailing = _addr(rec.get("OwnerAddress"))

    # Situs: SitusAddress.Line1 on most counties, Description on Fairfield (whose
    # SitusAddress is empty). Only a real street address goes in street_address.
    situs_raw = _addr(rec.get("SitusAddress")) or _clean(rec.get("Description"))
    street = situs_raw if looks_like_street_address(situs_raw) else None
    if street is None:
        s911 = " ".join(x for x in (_clean(assessor.get("StreetNumber911")),
                                    _clean(assessor.get("StreetName911"))) if x)
        if looks_like_street_address(s911):
            street = s911
    legal = None if street else situs_raw

    occ = owner_occupancy(vals)
    appraised = vals.get("Appraised")
    amount_due = _num(vals.get("AmountDue"))
    original_due = _num(vals.get("OriginalAmountDue"))
    total_due = amount_due if (amount_due and amount_due > 0) else (
        original_due if (original_due and original_due > 0) else None)
    year = rec.get("Year")
    redemption = _parse_dt(rec.get("TaxSaleRedemptionDate"))

    rtype = str(rec.get("RecordType") or "").strip().lower()
    kind = PropertyKind.MOBILE if rtype == "mobile home" else PropertyKind.UNKNOWN
    # A recorded tax sale (the redemption clock is running) is a real sale; a standing
    # delinquent roll is not.
    ltype = ListingType.TAX_SALE if redemption else rule.standing_type
    now = datetime.utcnow()
    catalis = {
        "county": county,
        "parcel_number": parcel,
        "billing_id": rec.get("BillingID"),
        "year": year,
        "record_type": rec.get("RecordType"),
        "owner": owner,
        "billed_owner": billed,
        "assessor_owner": current,
        # THE FIELD THIS SOURCE EXISTS FOR.
        "owner_mailing": mailing,
        "situs_address": situs_raw,
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
        # The balance. Values.AmountDue = base tax + penalty + costs at read time.
        "total_due": total_due,
        "base_tax": _num(vals.get("BaseTax")),
        "penalty": _num(vals.get("Penalty")),
        "interest": _num(vals.get("Interest")),
        "costs": _num(vals.get("Costs")),
        "due_date": rec.get("DueDate"),
        "last_updated": rec.get("LastUpdated"),
    }
    raw: dict = {"catalis_roll": catalis}
    if total_due:
        raw["tax_owed"] = {"balance": total_due, "kind": "delinquent_tax", "source": SLUG,
                           "year": year, "basis": "own_record"}
    return Listing(
        source=SLUG,
        source_url=CATALIS_COUNTIES[county][1],
        listing_type=ltype,
        property_kind=kind,
        state="SC",
        county=county,
        parcel_id=parcel,
        defendant=owner,
        owner_name=owner,
        street_address=street,
        legal_description=legal,
        acreage=_num(rec.get("Acres")) or None,
        tax_value=float(appraised) if appraised not in (None, "", 0) else None,
        description=(f"Delinquent property tax {year}: "
                     f"appraised ${float(appraised or 0):,.0f}"
                     + (f", ${total_due:,.2f} due" if total_due else "")
                     + ("" if occ is None else
                        f", {'owner-occupied (4%)' if occ else 'NOT owner-occupied (6%)'}")),
        first_seen=now, last_seen=now,
        raw=raw,
    )


def aggregate_bills(county: str, recs: list[dict]) -> list[Listing]:
    """One lead per PARCEL for the counties that publish one bill per tax year.

    A parcel delinquent for ten years arrives as ten bills sharing one parcel number. On
    the board they merge into one row on the parcel key, and the merge keeps only the last
    bill's balance. So the years are summed here, once, and the bills are kept in raw.
    """
    by_parcel: dict[str, list[dict]] = {}
    for rec in recs:
        p = (rec.get("ParcelNumber") or "").strip()
        if p:
            by_parcel.setdefault(p, []).append(rec)
    out: list[Listing] = []
    for parcel, bills in by_parcel.items():
        bills = sorted(bills, key=lambda r: (r.get("Year") or 0), reverse=True)
        li = to_listing(county, bills[0])
        if li is None:
            continue
        c = li.raw["catalis_roll"]
        per_bill = []
        for b in bills:
            v = b.get("Values") if isinstance(b.get("Values"), dict) else {}
            amt = _num(v.get("AmountDue"))
            if not (amt and amt > 0):
                amt = _num(v.get("OriginalAmountDue")) if (_num(v.get("OriginalAmountDue")) or 0) > 0 else None
            per_bill.append({"year": b.get("Year"), "billing_id": b.get("BillingID"),
                             "total_due": amt})
        years = sorted({x["year"] for x in per_bill if x["year"]})
        total = round(sum(x["total_due"] or 0 for x in per_bill), 2) or None
        c["bills"] = per_bill
        c["years"] = years
        c["years_delinquent"] = len(years)
        c["oldest_year"] = years[0] if years else None
        c["is_two_year_plus"] = len(years) >= 2
        # The shared, published key fullmer_rank reads for delinquency ripeness.
        li.raw["two_year_delinquent"] = {"is_two_year_plus": len(years) >= 2, "years": len(years),
                                         "oldest_year": years[0] if years else None, "source": SLUG}
        c["total_due"] = total
        if total:
            li.raw["tax_owed"] = {"balance": total, "kind": "delinquent_tax", "source": SLUG,
                                  "year": c.get("year"), "basis": "own_record"}
        else:
            li.raw.pop("tax_owed", None)
        appraised = c.get("appraised")
        span = f"{years[0]}-{years[-1]}" if len(years) > 1 else (str(years[0]) if years else "")
        li.description = (
            f"Delinquent property tax {span} ({len(years) or len(bills)} bill"
            f"{'s' if (len(years) or len(bills)) != 1 else ''}): "
            f"appraised ${float(appraised or 0):,.0f}"
            + (f", ${total:,.2f} due" if total else "")
            + ("" if c.get("owner_occupied") is None else
               f", {'owner-occupied (4%)' if c['owner_occupied'] else 'NOT owner-occupied (6%)'}"))
        out.append(li)
    return out


def to_listings(county: str, recs: list[dict]) -> list[Listing]:
    """Per-parcel leads for the new counties, per-bill leads for Pickens (unchanged)."""
    if rule_for(county).aggregate_by_parcel:
        return aggregate_bills(county, recs)
    return [li for li in (to_listing(county, r) for r in recs) if li]


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
                       budget: _Budget, *,
                       prefixes: Iterable[str] | None = None,
                       on_new: Callable[[dict], None] | None = None,
                       ) -> tuple[list[dict], dict]:
    """Adaptive name-prefix sweep. Returns (delinquent real-property records, stats).

    `prefixes` overrides the first level (a sample run passes one common surname);
    `on_new` is called once per newly seen record so the caller can keep partial results.
    Raises CatalisBlocked on a 403.
    """
    rule = rule_for(county)
    max_depth = rule.max_depth or MAX_PREFIX_DEPTH
    seen: dict[str, dict] = {}
    stats = {"queries": 0, "errors": 0, "records_seen": 0, "capped": 0,
             "truncated_prefixes": 0}
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(client: httpx.AsyncClient, prefix: str) -> bool:
        if stats.get("blocked"):
            return False          # a sibling task already hit a 403: send nothing more
        if not budget.take():
            return False
        payload = {"year": -1, "payStatus": "Unpaid", "type": "Property",
                   "parameter": "Name", "value": prefix}
        async with sem:
            rows = None
            for attempt in range(5):
                try:
                    r = await client.post(f"{_CDN}/{guid}/Records", json=payload)
                    # A 403 is the host declining. Stop; never retry or route around it.
                    if r.status_code == 403:
                        stats["blocked"] = True
                        log.warning("catalis_roll.blocked_403", county=county, prefix=prefix,
                                    note="the host answered 403; stopping this sweep and "
                                         "not retrying (weekend_runner.sh 2026-09-11)")
                        raise CatalisBlocked(f"HTTP 403 for {county} prefix {prefix!r}")
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
                except CatalisBlocked:
                    raise
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
            if is_delinquent_real_property(rec, rule):
                # The YEAR is part of the key. On Chester and Hampton the BillingID is just
                # the parcel number, identical for every tax year: keyed on BillingID alone,
                # a parcel delinquent since 2016 collapsed to one bill (measured: 71 delinquent
                # rows for prefix BROWN read back as 18).
                key = (f"{rec.get('BillingID') or rec.get('ParcelNumber')}:"
                       f"{rec.get('Year')}:{rec.get('RecordType')}")
                if key not in seen and on_new is not None:
                    on_new(rec)
                seen[key] = rec
        if len(rows) >= PAGE_CAP:
            stats["capped"] += 1
            return True
        return False

    async with httpx.AsyncClient(timeout=90.0, headers=_headers(site)) as client:
        frontier = list(prefixes) if prefixes else list(_ALPHABET)
        depth = 1
        while frontier and depth <= max_depth:
            tasks = [asyncio.ensure_future(one(client, p)) for p in frontier]
            try:
                res = await asyncio.gather(*tasks)
            except CatalisBlocked:
                # gather() does not cancel its siblings on an exception; cancel them so
                # nothing keeps talking to a host that has just said no.
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            nxt = [p + ch for p, capped in zip(frontier, res) if capped for ch in _ALPHABET]
            if nxt and depth >= max_depth:
                stats["truncated_prefixes"] = len({p[:-1] for p in nxt})
                log.warning("catalis_roll.depth_truncated", county=county,
                            prefixes=sorted({p[:-1] for p in nxt})[:10],
                            note="still filling the cap at max depth; raise CATALIS_ROLL_DEPTH")
            frontier = nxt
            depth += 1
    return list(seen.values()), stats


class SCCatalisDelinquentRoll(BaseScraper):
    slug = SLUG
    name = "SC Catalis/Sturgis Delinquent Roll (owner mailing address)"
    category = "county_tax"
    timeout_s = 600.0
    expected_min_count = 0
    optional = True

    #: A sample run (the ingest script's dry run) sets this to one surname per county.
    sample_prefixes: dict[str, str] | None = None

    async def fetch(self) -> Iterable[Listing]:
        only = {c.strip().title() for c in
                (os.getenv("CATALIS_ROLL_COUNTIES") or "").split(",") if c.strip()}
        order = [c for c in SWEEP_ORDER if c in CATALIS_COUNTIES] + \
                sorted(c for c in CATALIS_COUNTIES if c not in SWEEP_ORDER)
        targets = [(c, CATALIS_COUNTIES[c]) for c in order if not only or c in only]
        t0 = time.monotonic()
        out: list[Listing] = []
        for county, (guid, site) in targets:
            rule = rule_for(county)
            budget = _Budget(rule.budget or REQUEST_BUDGET)

            def _keep(rec: dict, _county: str = county) -> None:
                li = to_listing(_county, rec)
                if li is not None:
                    self.partial.append(li)

            first = None
            if self.sample_prefixes and county in self.sample_prefixes:
                first = [self.sample_prefixes[county]]
                budget = _Budget(1)
            try:
                recs, stats = await sweep_county(county, guid, site, budget,
                                                 prefixes=first, on_new=_keep)
            except CatalisBlocked as exc:
                log.warning("catalis_roll.county_blocked", county=county, error=str(exc)[:140],
                            note="403 is a stop: this and every later county (same host) "
                                 "are skipped")
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("catalis_roll.county_failed", county=county,
                            error=str(exc)[:140])
                continue
            got = to_listings(county, recs)
            out.extend(got)
            mailing = sum(1 for li in got
                          if li.raw["catalis_roll"].get("owner_mailing"))
            absentee = sum(1 for li in got
                           if li.raw["catalis_roll"].get("owner_occupied") is False)
            log.info("catalis_roll.county_done", county=county, leads=len(got),
                     with_owner_mailing=mailing, not_owner_occupied=absentee,
                     requests=budget.spent, **stats)
            if budget.left <= 0 and not first:
                log.warning("catalis_roll.budget_exhausted", county=county,
                            note="roll INCOMPLETE; raise CATALIS_ROLL_BUDGET")
        log.info("catalis_roll.done", leads=len(out),
                 seconds=round(time.monotonic() - t0, 1))
        return out
