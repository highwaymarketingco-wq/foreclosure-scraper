"""CourtListener bankruptcy filings scraper (NC W/E + SC bankruptcy courts).

Pulls Chapter 7, 11, 13 bankruptcy filings from the past 90 days for the
3 federal bankruptcy courts covering our footprint:
  - ncwb : NC Western District (Charlotte, Asheville, Statesville)
  - nceb : NC Eastern District (Raleigh, Wilson, Greenville)
  - scb  : SC District (Columbia, Charleston, Spartanburg)

Why this matters for flippers: a Chapter 13 filer is usually trying to STOP a
state-court foreclosure with the automatic stay. ~30% of Ch.13 cases convert
to Ch.7 within 18 months, at which point the property is liquidated. These
are pre-foreclosure leads with even more lead time than NOD recordings.

Emission strategy: bankruptcy dockets do NOT carry debtor addresses (verified
via direct API probe — bankruptcy_information has chapter but no address).
So we emit every filing from these 3 courts as a state-level lead with the
debtor name as `defendant`. Best-effort county tag from city keywords in
case name when present. The cross-reference enrichment in
`enrichment_bankruptcy.py` then matches these debtor names to existing
foreclosure-listing defendants for the BIG-signal join.

Auth: FREE and ANONYMOUS-capable. The v4 /search/ endpoint answers without a
token; a token (free account) is sent when present purely to raise the rate
limit. See https://www.courtlistener.com/sign-up/ ->
https://www.courtlistener.com/profile/api/ -> echo "TOKEN" >
.secrets/courtlistener_token.txt (or env COURTLISTENER_TOKEN=...).

2026-08-02 TIMEOUT FIX (source had been failing with "exceeded soft timeout
900s" and returning nothing at all):

  ROOT CAUSE — an N+1 API call per docket. The /dockets/ endpoint does NOT
  carry the bankruptcy chapter, and for these three courts `cause` and
  `nature_of_suit` are empty strings, so the cheap text-mine ALWAYS failed and
  every docket fell through to a separate /bankruptcy-information/ fetch. With
  ~3,900 dockets in a 90-day window, and http_client's per-host throttle
  spacing every courtlistener.com request ~1.15s apart (concurrency cannot beat
  a per-host rate limiter), that is ~75 minutes of sequential calls. The
  700-lookup cap did not save it: 700 x 1.15s = ~805s, which already blows the
  900s soft timeout before the third court is even reached.

  FIX — pull from /search/?type=r instead. That endpoint returns `chapter`
  INLINE on every result (live probe 2026-08-02: 795/800 scb rows populated,
  99.4%), so the per-docket lookup disappears entirely. Cost is 20 results per
  page instead of 200, but 194 pages x ~1.7s = ~330s for all three courts with
  ZERO follow-up calls — comfortably inside the timeout, and it returns ~3,900
  dockets instead of 0. A wall-clock deadline bounds it regardless of how the
  courts grow.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

API_BASE = "https://www.courtlistener.com/api/rest/v4"
COURTS = ("ncwb", "nceb", "scb")
LOOKBACK_DAYS = 90
# /search/ hard-caps page_size at 20 regardless of what we ask for (verified:
# page_size=100 and page_size=200 both return 20). Pages are cheap because each
# one already carries the chapter, so no follow-up call is needed.
SEARCH_PAGE_SIZE = 20
# ~1,600 dockets/court/90d today -> ~80 pages. 200 leaves 2.5x headroom.
MAX_SEARCH_PAGES_PER_COURT = int(os.environ.get("BANKRUPTCY_MAX_PAGES", "200"))
# /dockets/ page size + page cap. No longer used by THIS scraper, but
# courtlistener_civil imports both — leave them at their original values.
PAGE_SIZE = 200
MAX_PAGES_PER_COURT = 10
# Hard wall-clock budget for the whole pass, well under timeout_s. Results are
# ordered newest-first, so running out of budget drops the OLDEST filings.
FETCH_BUDGET_S = float(os.environ.get("BANKRUPTCY_BUDGET_S", "600"))
# Attempts per search page before abandoning the court.
_PAGE_RETRIES = 3


def _load_token() -> str | None:
    tok = os.environ.get("COURTLISTENER_TOKEN") or os.environ.get("COURTLISTENER_API_TOKEN")
    if tok:
        return tok.strip()
    f = Path(".secrets/courtlistener_token.txt")
    if f.exists():
        try:
            return f.read_text().strip()
        except Exception:
            return None
    return None


# Best-effort city → county map for our 21-county footprint. When a city
# keyword appears in the case_name (rare but happens — joint filings sometimes
# include city) we tag the listing with the county. Otherwise we leave county
# as the court's default region.
CITY_TO_COUNTY = {
    "CHARLOTTE": ("NC", "Mecklenburg"),
    "ASHEVILLE": ("NC", "Buncombe"),
    "HENDERSONVILLE": ("NC", "Henderson"),
    "GASTONIA": ("NC", "Gaston"),
    "SHELBY": ("NC", "Cleveland"),
    "RUTHERFORDTON": ("NC", "Rutherford"),
    "FOREST CITY": ("NC", "Rutherford"),
    "MORGANTON": ("NC", "Burke"),
    "MARION": ("NC", "McDowell"),
    "LINCOLNTON": ("NC", "Lincoln"),
    "BREVARD": ("NC", "Transylvania"),
    "BURNSVILLE": ("NC", "Yancey"),
    "BAKERSVILLE": ("NC", "Mitchell"),
    "MARSHALL": ("NC", "Madison"),
    "COLUMBUS": ("NC", "Polk"),
    "TRYON": ("NC", "Polk"),
    "SPARTANBURG": ("SC", "Spartanburg"),
    "ANDERSON": ("SC", "Anderson"),
    "PICKENS": ("SC", "Pickens"),
    "EASLEY": ("SC", "Pickens"),
    "WALHALLA": ("SC", "Oconee"),
    "SENECA": ("SC", "Oconee"),
    "GAFFNEY": ("SC", "Cherokee"),
    "UNION": ("SC", "Union"),
    "LAURENS": ("SC", "Laurens"),
    "CLINTON": ("SC", "Laurens"),
}

# Court → default state (so listings always carry at least state). County is
# only set when we can recover it from the case name.
COURT_STATE = {"ncwb": "NC", "nceb": "NC", "scb": "SC"}


def _county_from_text(text: str) -> tuple[str | None, str | None]:
    if not text:
        return (None, None)
    upper = text.upper()
    for kw, (state, county) in CITY_TO_COUNTY.items():
        if kw in upper:
            return (state, county)
    return (None, None)


def _chapter_from_text(*texts: str) -> str:
    blob = " ".join(t.lower() for t in texts if t)
    for kw, ch in (
        ("chapter 7", "7"),
        ("chapter 11", "11"),
        ("chapter 13", "13"),
        ("ch.7", "7"),
        ("ch.11", "11"),
        ("ch.13", "13"),
        ("ch 7", "7"),
        ("ch 11", "11"),
        ("ch 13", "13"),
    ):
        if kw in blob:
            return ch
    return "?"


async def _fetch_chapter(c, docket: dict, token: str) -> str:
    """Fetch chapter from the bankruptcy_information endpoint when available.
    Falls back to text-mining cause/nature_of_suit. Best-effort, never raises.
    """
    bi_url = docket.get("bankruptcy_information")
    if bi_url and isinstance(bi_url, str):
        try:
            r = await c.get(
                bi_url,
                headers={"Authorization": f"Token {token}", "Accept": "application/json"},
                timeout=10.0,
            )
            if r.status_code == 200:
                bi = r.json()
                ch = bi.get("chapter")
                if ch:
                    return str(ch).strip()
        except Exception:
            pass
    return _chapter_from_text(docket.get("cause"), docket.get("nature_of_suit"))


def _auth_headers(token: str | None) -> dict:
    """Token is OPTIONAL — /search/ answers anonymously; the header only raises
    the rate limit when a free account token is configured."""
    h = {"Accept": "application/json"}
    if token:
        h["Authorization"] = f"Token {token}"
    return h


def _normalize_search_hit(hit: dict, court: str) -> dict:
    """Map a /search/?type=r result onto the docket shape the rest of this
    module (and its tests) already speak, carrying `chapter` through inline."""
    absolute_url = hit.get("docket_absolute_url") or ""
    return {
        "case_name": hit.get("caseName") or hit.get("case_name_full") or "",
        "docket_number": hit.get("docketNumber") or "",
        "date_filed": hit.get("dateFiled"),
        "absolute_url": absolute_url,
        "cause": hit.get("cause") or "",
        "nature_of_suit": hit.get("suitNature") or "",
        "chapter": (hit.get("chapter") or "").strip(),
        "court_id": hit.get("court_id") or court,
        "docket_id": hit.get("docket_id"),
        "trustee": hit.get("trustee_str") or "",
    }


async def _fetch_court(c, court: str, token: str | None, deadline: float | None = None) -> list[dict]:
    """Pull recent bankruptcy dockets from one court, paginated.

    Uses the v4 /search/ endpoint (type=r = RECAP dockets) because it returns
    the bankruptcy `chapter` inline — the /dockets/ endpoint does not, and the
    per-docket chapter lookup it forced is what blew the soft timeout. Ordered
    newest-first so a budget cut-off sheds the oldest filings, not the freshest.
    """
    cutoff = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    out: list[dict] = []
    next_url: str | None = (
        f"{API_BASE}/search/?type=r&court={court}&filed_after={cutoff}"
        f"&page_size={SEARCH_PAGE_SIZE}&order_by=dateFiled%20desc"
    )
    headers = _auth_headers(token)
    page = 0
    while next_url and page < MAX_SEARCH_PAGES_PER_COURT:
        if deadline is not None and time.monotonic() > deadline:
            log.warning("courtlistener.budget_exhausted", court=court,
                        pages=page, rows=len(out))
            break
        # A single dropped page used to abandon the whole court (live smoke:
        # ncwb bailed after page 1 on a bare ReadTimeout and yielded 20 of 767
        # rows). Retry the page before giving up.
        data = None
        for attempt in range(_PAGE_RETRIES):
            try:
                r = await c.get(next_url, headers=headers)
                if r.status_code != 200:
                    log.warning("courtlistener.error", court=court, status=r.status_code)
                    break
                data = r.json()
                break
            except Exception as exc:  # noqa: BLE001 — transient network/read timeout
                log.warning("courtlistener.fetch_error", court=court, page=page,
                            attempt=attempt + 1,
                            error=f"{type(exc).__name__}: {str(exc)[:100]}")
                if attempt + 1 < _PAGE_RETRIES:
                    await asyncio.sleep(2.0 * (attempt + 1))
        if data is None:
            break
        for hit in data.get("results") or []:
            out.append(_normalize_search_hit(hit, court))
        next_url = data.get("next")
        page += 1
    return out


class CourtListenerBankruptcy(BaseScraper):
    slug = "national.courtlistener_bankruptcy"
    name = "CourtListener Bankruptcy (NC W/E + SC, Ch 7/11/13)"
    category = "national_aggregator"
    expected_min_count = 0  # graceful when the API is unreachable
    requires_apify = False
    # /search/ carries the chapter inline, so the pass is pure pagination
    # (~330s for all three courts). FETCH_BUDGET_S cuts it off well before this
    # ceiling; the ceiling only exists so a slow network can't trip the alarm.
    timeout_s = 900.0

    async def fetch(self) -> Iterable[Listing]:
        # Token is optional: /search/ answers anonymously. When present it only
        # buys a higher rate limit, so a missing token is no longer fatal.
        token = _load_token()
        if not token:
            log.info("courtlistener.no_token",
                     hint="running anonymously; a free token raises the rate limit")

        out: list[Listing] = []
        chapter_lookups = 0
        # Chapter now arrives inline on ~99% of rows. This bounded fallback only
        # covers the handful that come back blank (adversary proceedings etc).
        MAX_CHAPTER_LOOKUPS = int(os.environ.get("BANKRUPTCY_CHAPTER_LOOKUPS", "50"))
        deadline = time.monotonic() + FETCH_BUDGET_S

        # Dedup tracker — CourtListener pagination occasionally returns the
        # same docket twice (cursor-based with overlap on edits, and /search/
        # can surface one docket under several matching documents). Without
        # this guard the audit measured 181 duplicate case_numbers per run.
        # Key is (court, docket_no) — same docket# across different courts
        # is legitimate and must NOT be deduped (NCWB 26-02017 is a
        # different case from NCEB 26-02017).
        seen_keys: set[tuple[str, str]] = set()
        dedup_dropped = 0

        async with client(timeout=45.0) as c:
            for court in COURTS:
                dockets = await _fetch_court(c, court, token, deadline)
                state_default = COURT_STATE.get(court, "NC")

                for d in dockets:
                    case_name = d.get("case_name") or ""
                    docket_no = d.get("docket_number") or ""
                    if not case_name and not docket_no:
                        continue

                    # Skip duplicates within the same scrape pass.
                    if docket_no:
                        key = (court, docket_no.strip())
                        if key in seen_keys:
                            dedup_dropped += 1
                            continue
                        seen_keys.add(key)

                    # Try to recover state+county from case name (rare hit; mostly None)
                    state_match, county_match = _county_from_text(case_name)
                    state = state_match or state_default
                    county = county_match  # may be None — that's fine, downstream tolerates

                    # Chapter detection. /search/ hands it to us inline, which is
                    # the whole point of the endpoint switch — Ch.13 = trying to
                    # stop a foreclosure, Ch.7 = liquidation. Fall back to the
                    # cheap text-mine, then (rarely, and bounded) to the
                    # bankruptcy_information sub-resource.
                    chapter = (d.get("chapter") or "").strip()
                    if not chapter or chapter == "?":
                        chapter = _chapter_from_text(d.get("cause"), d.get("nature_of_suit"))
                    if chapter == "?" and chapter_lookups < MAX_CHAPTER_LOOKUPS:
                        chapter = await _fetch_chapter(c, d, token)
                        chapter_lookups += 1

                    date_filed = d.get("date_filed")
                    desc = (
                        f"Ch.{chapter} bankruptcy filed {date_filed or '?'} ({court.upper()}) "
                        f"— Debtor: {case_name[:160]}"
                    )

                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=("https://www.courtlistener.com" + d["absolute_url"]) if d.get("absolute_url") else "",
                            listing_type=ListingType.BANKRUPTCY,  # 2026-06-19: was mislabeled LIS_PENDENS
                            property_kind=PropertyKind.UNKNOWN,
                            state=state,
                            county=county,
                            case_number=docket_no,
                            defendant=case_name[:200] or None,
                            description=desc,
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                            raw={
                                "courtlistener": {
                                    "court": court,
                                    "docket_number": docket_no,
                                    "chapter": chapter,
                                    "case_name": case_name,
                                    "date_filed": date_filed,
                                    "nature_of_suit": d.get("nature_of_suit"),
                                    "cause": d.get("cause"),
                                    "absolute_url": d.get("absolute_url"),
                                    "bankruptcy_information": d.get("bankruptcy_information"),
                                    "docket_id": d.get("docket_id"),
                                    "trustee": d.get("trustee") or None,
                                },
                            },
                        )
                    )

        log.info(
            "courtlistener.done",
            listings=len(out),
            courts=len(COURTS),
            lookback_days=LOOKBACK_DAYS,
            chapter_api_lookups=chapter_lookups,
            dedup_dropped=dedup_dropped,
        )
        return out
