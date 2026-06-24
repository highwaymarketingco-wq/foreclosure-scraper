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

Auth: free, requires a CourtListener account + API token.
  1. Sign up: https://www.courtlistener.com/sign-up/
  2. Get token: https://www.courtlistener.com/profile/api/
  3. Save: echo "TOKEN" > .secrets/courtlistener_token.txt
  4. Or set env: COURTLISTENER_TOKEN=...

Without a token, the scraper logs once and returns []. No errors, no spam.
"""
from __future__ import annotations

import asyncio
import os
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
PAGE_SIZE = 200
MAX_PAGES_PER_COURT = 10  # cap at 10 pages = 2000 cases per court


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


async def _fetch_court(c, court: str, token: str) -> list[dict]:
    """Pull recent bankruptcy dockets from one court, paginated."""
    cutoff = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    out: list[dict] = []
    next_url: str | None = (
        f"{API_BASE}/dockets/?court={court}&date_filed__gte={cutoff}&page_size={PAGE_SIZE}"
    )
    page = 0
    while next_url and page < MAX_PAGES_PER_COURT:
        try:
            r = await c.get(
                next_url,
                headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            )
            if r.status_code != 200:
                log.warning("courtlistener.error", court=court, status=r.status_code)
                break
            data = r.json()
            results = data.get("results") or []
            out.extend(results)
            next_url = data.get("next")
            page += 1
        except Exception as exc:
            log.warning("courtlistener.fetch_error", court=court, error=str(exc)[:120])
            break
    return out


class CourtListenerBankruptcy(BaseScraper):
    slug = "national.courtlistener_bankruptcy"
    name = "CourtListener Bankruptcy (NC W/E + SC, Ch 7/11/13)"
    category = "national_aggregator"
    expected_min_count = 0  # graceful when no token
    requires_apify = False
    # The per-docket chapter lookups (one extra API call each) are the cost; at
    # 480s the run timed out mid-pass and got flagged BLOCKED. Give it real
    # headroom — scrapers run concurrently so a long one doesn't block others.
    timeout_s = 900.0

    async def fetch(self) -> Iterable[Listing]:
        token = _load_token()
        if not token:
            log.info("courtlistener.no_token", hint="sign up free at courtlistener.com to enable")
            return []

        out: list[Listing] = []
        chapter_lookups = 0
        # CourtListener free tier = 5000 reqs/hr. The per-docket chapter lookup
        # is sequential and is the runtime bottleneck, so bound it: debtor NAMES
        # (the foreclosure-defendant join key) are captured for ALL dockets
        # regardless; only the precise chapter is skipped past this cap (those
        # fall back to the text-mined chapter / "?"). Keeps the run inside budget.
        MAX_CHAPTER_LOOKUPS = int(os.environ.get("BANKRUPTCY_CHAPTER_LOOKUPS", "700"))

        # Dedup tracker — CourtListener pagination occasionally returns the
        # same docket twice (cursor-based with overlap on edits, plus we
        # query bankruptcy_information sub-resources separately). Without
        # this guard the audit measured 181 duplicate case_numbers per run.
        # Key is (court, docket_no) — same docket# across different courts
        # is legitimate and must NOT be deduped (NCWB 26-02017 is a
        # different case from NCEB 26-02017).
        seen_keys: set[tuple[str, str]] = set()
        dedup_dropped = 0

        async with client(timeout=20.0) as c:
            for court in COURTS:
                dockets = await _fetch_court(c, court, token)
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

                    # Chapter detection: text-mine first (cheap), then hit
                    # bankruptcy_information sub-resource (one extra API call) when
                    # text-mine fails. Chapter is the most valuable single signal —
                    # Ch.13 = trying to stop a foreclosure, Ch.7 = liquidation.
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
