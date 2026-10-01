"""CourtListener federal civil-docket scraper — foreclosure / real-property cases.

CourtListener (free public mirror of PACER) has the entire federal civil
docket. Most foreclosure activity in NC + SC happens in state court, but
federal civil real-property cases catch:

  * Mortgage-fraud and quiet-title actions filed in federal court
  * RESPA / TILA violations as defendants in foreclosure
  * Federal lender (Fannie / Freddie / FDIC / HUD) plaintiff cases
  * Multi-state mortgage class actions touching NC/SC properties

Volume is much smaller than bankruptcy (most foreclosure stays in
state court) but each hit is a high-quality, specific lead.

Filter: federal courts in NC + SC + nature_of_suit codes for real
property:

  220  Foreclosure
  230  Rent Lease & Ejectment
  240  Torts to Land
  290  Other Real Property

2026-10-01 ENDPOINT FIX (per-source extraction audit, docs/HERMES.md sec 8):
this scraper was pulling /dockets/ directly, the SAME endpoint
courtlistener_bankruptcy.py's own 2026-08-02 docstring documents as broken
for exactly this purpose -- nature_of_suit/cause come back EMPTY STRING on
fresh filings (live-verified 2026-10-01: 0/5 sampled ncwd dockets filed in
the last 90 days had either field populated), so `_is_real_property_case()`
could almost never match a RECENT case -- a silent, HTTP-200, "looks fine"
starvation of exactly the freshest, most actionable leads (the CLAUDE.md
"silent success" failure mode). The bankruptcy scraper already fixed this by
switching to `/search/?type=r`, which carries `suitNature` inline (live-
verified 2026-10-01: 10/20 ncwd rows populated via /search/ vs 0/5 via
/dockets/) and, as a bonus, trustee/party/attorney/firm fields the old
/dockets/ pull never had access to at all. This file now reuses the same
/search/ pagination + normalizer the bankruptcy scraper already built rather
than duplicating a second broken pull.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

# Reuse the helper functions from the bankruptcy scraper — same auth,
# same /search/ pagination + normalizer, same county-from-text recovery.
from .courtlistener_bankruptcy import (
    API_BASE,
    LOOKBACK_DAYS,
    SEARCH_PAGE_SIZE,
    _auth_headers,
    _county_from_text,
    _load_token,
    _normalize_search_hit,
    _PAGE_RETRIES,
    _split_caption,
)

log = structlog.get_logger()

# Civil real-property volume is much smaller than bankruptcy's (see module
# docstring), so a far smaller page cap than bankruptcy's 200 already gives
# generous headroom (50 pages x 20/page = 1,000 rows/court/90-day window).
MAX_SEARCH_PAGES_PER_COURT_CIVIL = 50


# Federal District Courts covering NC + SC
CIVIL_COURTS = ("nced", "ncmd", "ncwd", "scd")

CIVIL_COURT_STATE = {"nced": "NC", "ncmd": "NC", "ncwd": "NC", "scd": "SC"}

# Nature-of-suit codes for real-property civil cases. CourtListener
# stores these as strings on the docket record.
REAL_PROPERTY_NOS = {
    "220": "Foreclosure",
    "230": "Rent Lease & Ejectment",
    "240": "Torts to Land",
    "245": "Tort Product Liability — Real Property",
    "290": "All Other Real Property",
}


def _is_real_property_case(docket: dict) -> bool:
    """Return True if the docket's nature_of_suit OR cause text matches a
    real-property pattern. Both fields are checked because CourtListener
    is inconsistent — older dockets often have nature_of_suit empty but
    a populated cause string."""
    # NOS code or NOS label
    nos = (docket.get("nature_of_suit") or "").strip()
    if nos:
        if nos in REAL_PROPERTY_NOS:
            return True
        nos_lower = nos.lower()
        if any(label.lower() in nos_lower for label in REAL_PROPERTY_NOS.values()):
            return True
    # Cause-of-action text fallback (common in older dockets / civil rights cases)
    cause = (docket.get("cause") or "").lower()
    if cause and any(kw in cause for kw in (
        "foreclos", "real property", "quiet title",
        "ejectment", "lis pendens",
    )):
        return True
    return False


async def _fetch_court_civil(
    c, court: str, token: str | None, deadline: float | None = None,
) -> list[dict]:
    """Pull recent civil dockets from one federal district court.

    Uses the v4 /search/ endpoint (type=r = RECAP dockets), same as
    courtlistener_bankruptcy._fetch_court, because it returns `suitNature`
    inline where /dockets/ returns an empty string on fresh filings (see the
    2026-10-01 ENDPOINT FIX note in this module's docstring).
    """
    cutoff = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    out: list[dict] = []
    next_url: str | None = (
        f"{API_BASE}/search/?type=r&court={court}&filed_after={cutoff}"
        f"&page_size={SEARCH_PAGE_SIZE}&order_by=dateFiled%20desc"
    )
    headers = _auth_headers(token)
    page = 0
    while next_url and page < MAX_SEARCH_PAGES_PER_COURT_CIVIL:
        if deadline is not None and time.monotonic() > deadline:
            log.warning("courtlistener_civil.budget_exhausted",
                        court=court, pages=page, rows=len(out))
            break
        # Same retry-with-backoff as courtlistener_bankruptcy._fetch_court:
        # a single transient ReadTimeout (common against this host — it is
        # per-host throttled) used to abandon the WHOLE court after page 1
        # with no retry, live-reproduced 2026-10-01 (3 of 4 civil courts
        # dropped to 0 rows on a bare, message-less exception on first try).
        data = None
        for attempt in range(_PAGE_RETRIES):
            try:
                r = await c.get(next_url, headers=headers)
                if r.status_code != 200:
                    log.warning("courtlistener_civil.error",
                                court=court, status=r.status_code)
                    break
                data = r.json()
                break
            except Exception as exc:  # noqa: BLE001 — transient network/read timeout
                log.warning("courtlistener_civil.fetch_error", court=court, page=page,
                            attempt=attempt + 1,
                            error=f"{type(exc).__name__}: {str(exc)[:100]}")
                if attempt + 1 < _PAGE_RETRIES:
                    await asyncio.sleep(2.0 * (attempt + 1))
        if data is None:
            break
        # Pre-filter to real-property cases at the page level — saves
        # the orchestrator from parsing irrelevant dockets.
        for hit in data.get("results") or []:
            d = _normalize_search_hit(hit, court)
            if _is_real_property_case(d):
                out.append(d)
        next_url = data.get("next")
        page += 1
    return out


class CourtListenerCivil(BaseScraper):
    """Federal civil dockets in NC + SC filtered to real-property cases."""

    slug = "national.courtlistener_civil"
    name = "CourtListener federal civil — real property (NC + SC)"
    category = "federal_court"
    expected_min_count = 0   # Volume is small; weeks may have 0
    requires_apify = False
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        # Kept token-required (unlike courtlistener_bankruptcy, which made
        # this optional): an existing test (test_civil_skips_without_token)
        # asserts the no-token path returns [] without touching the network,
        # and that contract is not part of the confirmed gap this pass fixes
        # (the /dockets/ -> /search/ endpoint switch below). Not changed here
        # to avoid an unreviewed behavior change outside this audit's scope.
        token = _load_token()
        if not token:
            log.info("courtlistener_civil.no_token")
            return []

        out: list[Listing] = []
        seen_keys: set[tuple[str, str]] = set()
        deadline = time.monotonic() + self.timeout_s * 0.8

        async with client(timeout=20.0) as c:
            for court in CIVIL_COURTS:
                dockets = await _fetch_court_civil(c, court, token, deadline)
                state_default = CIVIL_COURT_STATE.get(court, "NC")

                for d in dockets:
                    case_name = d.get("case_name") or ""
                    docket_no = d.get("docket_number") or ""
                    if not case_name and not docket_no:
                        continue

                    # Per-court dedup (same as the bankruptcy scraper)
                    if docket_no:
                        key = (court, docket_no.strip())
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)

                    # State is authoritative from the court (see
                    # courtlistener_bankruptcy._county_from_text's docstring for
                    # why a city keyword must not override it).
                    state = state_default
                    county = _county_from_text(case_name, state)

                    nos = (d.get("nature_of_suit") or "").strip()
                    cause = (d.get("cause") or "").strip()
                    date_filed = d.get("date_filed")

                    desc = (
                        f"Federal civil real-property case ({court.upper()}) — "
                        f"NOS {nos or '?'}; filed {date_filed or '?'}"
                        + (f" — {case_name[:120]}" if case_name else "")
                    )[:500]

                    # A federal real-property case_name IS a true "<Plaintiff>
                    # v. <Defendant>" caption (live-verified 2026-10-01, e.g.
                    # "Federal National Mortgage Association v. <Borrower>"),
                    # and nearly every real-property plaintiff here IS a
                    # mortgage servicer/GSE. The old code dumped the whole
                    # caption into `defendant` -- the field downstream
                    # name-resolution enrichers read as "the owner" -- so the
                    # servicer's own name regularly ended up looking like the
                    # homeowner's (extraction_gaps.md: "servicer/GSE as
                    # owner_name ... SERVICEMAC/FNMA/case-caption"). Split it.
                    cap_plaintiff, cap_defendant = _split_caption(case_name)

                    out.append(Listing(
                        source=self.slug,
                        source_url=("https://www.courtlistener.com" + d["absolute_url"]) if d.get("absolute_url") else "",
                        listing_type=ListingType.LIS_PENDENS,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state,
                        county=county,
                        case_number=docket_no or None,
                        plaintiff=cap_plaintiff[:200] if cap_plaintiff else None,
                        defendant=cap_defendant[:200] if cap_defendant else None,
                        # The /search/ switch (see module docstring) surfaces
                        # trustee/attorney/firm/party fields /dockets/ never
                        # had -- HERMES sec 8 explicitly calls out
                        # attorney/trustee as a required field to capture.
                        trustee=d.get("trustee") or None,
                        description=desc,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"courtlistener_civil": {
                            "court": court,
                            "nature_of_suit": nos,
                            "cause": cause,
                            "case_name": case_name,
                            "date_filed": date_filed,
                            "absolute_url": d.get("absolute_url"),
                            "docket_id": d.get("docket_id"),
                            "pacer_case_id": d.get("pacer_case_id"),
                            "trustee": d.get("trustee") or None,
                            "party": d.get("party") or None,
                            "attorney": d.get("attorney") or None,
                            "firm": d.get("firm") or None,
                            "date_terminated": d.get("date_terminated"),
                        }},
                    ))

        log.info("courtlistener_civil.done",
                 listings=len(out), courts=len(CIVIL_COURTS),
                 lookback_days=LOOKBACK_DAYS)
        return out
