"""Foreclosure STARTS from the Western NC register of deeds — Clay, Haywood, Yancey.

WHY THIS IS THE EARLIEST SIGNAL THIS PROJECT HAS
    In North Carolina a power-of-sale foreclosure begins when the lender records
    a **substitution of trustee** (`S/T`) — it swaps the original deed-of-trust
    trustee for a foreclosure trustee. It is recorded BEFORE the notice of
    hearing is filed with the clerk and long before any sale is advertised.

    Everything else this engine reads for NC foreclosure (public notices, law
    firm sale lists, court filings) happens downstream of that document. Reading
    `S/T` gets to the owner while the file is still with the servicer.

    `TR/D` (trustee's deed) is the other end: the sale completed and the property
    is now REO. Both are emitted; the type says which.

WHY THESE THREE COUNTIES
    Clay, Haywood and Yancey are core-footprint Western NC counties that hold
    **zero** leads on the board today. They run "The Lookup", the only county
    recorder platform in this footprint that opens without a CAPTCHA, a login or
    restriction language in its terms (checked — see docs/ROD_PORTAL_ACCESS.md).

    They were nearly missed twice: the registry held their landing page
    (`haywooddeeds.com`) rather than the platform (`search.haywooddeeds.com`),
    and nine counties on a DIFFERENT platform were briefly recorded as sharing
    this one because all of them answer HTTP 200.

ONE DOCUMENT IS MANY ROWS
    The index emits a row per party, so a single substitution of trustee with a
    borrower, a servicer, a lender and two trustees is five rows — and because
    parties are fetched in batches, the same document repeats once per batch it
    appears in. A raw 3-day Haywood window is 8,528 rows and **133 documents**.
    Deduping on (date, book, type) before counting anything is not optional.

    The borrower is the natural-person GRANTOR. Servicers, lenders and trustees
    are all parties to the same instrument and must be filtered out, or the lead
    is "U.S. BANK TRUST, NATIONAL ASSOCIATION".
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

from ...base_scraper import BaseScraper
from ...enrichment_rod_lookup import LOOKUP_HOSTS, bulk_by_date
from ...models import Listing, ListingType, PropertyKind

#: Only the counties whose platform is verified to return rows. Deliberately
#: reuses LOOKUP_HOSTS rather than restating a list that could drift from it.
COUNTIES = [(c, s) for (c, s) in LOOKUP_HOSTS if s == "NC"]

#: How far back to read each run. The window is small because the pick list is
#: capped and a 3-day Haywood window already returns 385 parties.
LOOKBACK_DAYS = 21

#: Institutional parties to a foreclosure instrument. The lead is the person who
#: owes the money, never the bank that is taking the house.
_INSTITUTION_RE = re.compile(
    r"\b(?:LLC|L\.L\.C|INC\b|CORP|COMPANY|BANK|N\.A\.|NA\b|TRUST(?:EE|S)?\b|"
    r"MORTGAGE|SERVICING|SERVICES|ASSOCIATION|ASSOC\b|FEDERAL|CREDIT UNION|"
    r"ATTORNEY IN FACT|LAW\b|PARTNERS|LP\b|LLP|FUND|CAPITAL|HOLDINGS|"
    r"SUBSTITUTE TRUSTEE|ESQ\b|PLLC|AGENCY|DEPARTMENT|SECRETARY|"
    r"UNITED STATES|STATE OF|COUNTY OF)\b",
    re.I,
)

#: What we publish, and the listing type each maps to.
_EMIT = {
    "substitution_of_trustee": ListingType.LIS_PENDENS,   # foreclosure STARTED
    "trustees_deed": ListingType.REO,                     # foreclosure COMPLETED
}


def _is_person(name: str) -> bool:
    n = (name or "").strip()
    return bool(n) and not _INSTITUTION_RE.search(n)


def _dedupe(rows: list[dict]) -> dict[tuple, list[dict]]:
    """(date, book, type) -> its distinct party rows."""
    out: dict[tuple, dict[tuple, dict]] = {}
    for r in rows:
        key = (r.get("recorded"), r.get("book_info"), r.get("doc_type"))
        out.setdefault(key, {})[(r.get("party"), r.get("party_role"))] = r
    return {k: list(v.values()) for k, v in out.items()}


def _to_listing(slug: str, county: str, state: str, key: tuple,
                parties: list[dict]) -> Listing | None:
    kind = next((p["kind"] for p in parties if p.get("kind")), None)
    listing_type = _EMIT.get(kind or "")
    if listing_type is None:
        return None

    borrowers = [p["party"] for p in parties
                 if p.get("party_role") == "GRANTOR" and _is_person(p["party"])]
    if kind == "trustees_deed":
        # On a trustee's deed the FORMER owner is the grantor side too; the
        # grantee is whoever took title at the sale.
        borrowers = borrowers or [p["party"] for p in parties
                                  if _is_person(p["party"])]
    if not borrowers:
        return None  # institution-only instrument, no person to contact

    recorded, book, doc_type = key
    try:
        rec_dt = datetime.strptime(recorded, "%m/%d/%Y")
    except (TypeError, ValueError):
        return None

    lenders = [p["party"] for p in parties if not _is_person(p["party"])]
    host = LOOKUP_HOSTS[(county, state)]
    now = datetime.utcnow()
    if kind == "substitution_of_trustee":
        label, stage = "Substitution of trustee", "begins"
    else:
        label, stage = "Trustee's deed", "completed"
    return Listing(
        source=slug,
        source_url=f"{host}/index.php?Accept=Accept",
        listing_type=listing_type,
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        county=county.title(),
        defendant="; ".join(sorted(set(borrowers))[:4]),
        owner_name="; ".join(sorted(set(borrowers))[:4]),
        filing_date=rec_dt,
        description=(f"{label} recorded {recorded} ({book}). "
                     f"NC power-of-sale foreclosure {stage}."),
        first_seen=now, last_seen=now,
        raw={"wnc_rod": {
            "county": county, "state": state, "recorded": recorded,
            "book_page": book, "doc_type": doc_type, "kind": kind,
            "borrowers": sorted(set(borrowers)),
            "institutions": sorted(set(lenders))[:8],
            "party_count": len(parties),
        }},
    )


class WNCRodForeclosureStarts(BaseScraper):
    slug = "counties_nc.wnc_rod_foreclosure_starts"
    name = "Western NC ROD — substitutions of trustee (foreclosure starts)"
    category = "register_of_deeds"
    # Small counties: a quiet three weeks genuinely can yield very few. Zero is
    # a legitimate outcome here, not evidence of a break.
    expected_min_count = 0
    timeout_s = 900.0

    async def fetch(self) -> Iterable[Listing]:
        end = datetime.utcnow()
        start = end - timedelta(days=LOOKBACK_DAYS)
        a, b = start.strftime("%m/%d/%Y"), end.strftime("%m/%d/%Y")

        out: list[Listing] = []
        for county, state in COUNTIES:
            rows = bulk_by_date(county, state, a, b)
            if not rows:
                continue
            for key, parties in _dedupe(rows).items():
                li = _to_listing(self.slug, county, state, key, parties)
                if li is not None:
                    out.append(li)
        return out
