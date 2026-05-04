"""Cross-reference existing listings against recent CourtListener bankruptcy
filings. For each listing whose defendant name matches a recent NC/SC
bankruptcy debtor, tag raw.bankruptcy = { chapter, date_filed, court, ... }.

Bankruptcy filing on the same person who's the foreclosure defendant is a
strong pre-foreclosure signal:
  - Chapter 13 = trying to stop the sale with the automatic stay
  - Chapter 7 = liquidation, property will be sold
  - Both: the borrower is in real distress, not just a paperwork glitch

Free with CourtListener API token (sign up at courtlistener.com/sign-up/).
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

API_BASE = "https://www.courtlistener.com/api/rest/v4"
COURTS = ("ncwb", "nceb", "scb")
LOOKBACK_DAYS = 180
PAGE_SIZE = 200


def _load_token() -> Optional[str]:
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


def _normalize_name(name: str) -> str:
    """Strip honorifics + sufixes, lowercase, collapse whitespace, drop punctuation."""
    if not name:
        return ""
    s = name.lower()
    # Drop "estate of", "et al", honorifics, suffixes
    s = re.sub(r"\bestate of\b", "", s)
    s = re.sub(r"\bet\.?\s*al\.?\b", "", s)
    s = re.sub(r"\b(jr|sr|i{1,3}|iv|v|esq|md|dr|mr|mrs|ms)\.?\b", "", s)
    # Drop punctuation, collapse spaces
    s = re.sub(r"[^a-z\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _name_tokens(name: str) -> set[str]:
    n = _normalize_name(name)
    return {t for t in n.split() if len(t) >= 3}


async def _fetch_chapter(c, docket: dict, token: str) -> str:
    """Best-effort chapter lookup via bankruptcy_information sub-resource.
    Falls back to text-mining cause/nature_of_suit. Never raises.
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
                ch = (r.json() or {}).get("chapter")
                if ch:
                    return str(ch).strip()
        except Exception:
            pass
    blob = (
        (docket.get("cause") or "").lower()
        + " "
        + (docket.get("nature_of_suit") or "").lower()
    )
    for kw, ch in (("chapter 7", "7"), ("chapter 11", "11"), ("chapter 13", "13"),
                   ("ch.7", "7"), ("ch.11", "11"), ("ch.13", "13")):
        if kw in blob:
            return ch
    return "?"


async def _fetch_recent_bankruptcies(c, court: str, token: str) -> list[dict]:
    """Pull recent bankruptcy dockets from one court, paginated."""
    cutoff = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    out: list[dict] = []
    next_url: Optional[str] = (
        f"{API_BASE}/dockets/?court={court}&date_filed__gte={cutoff}&page_size={PAGE_SIZE}"
    )
    page = 0
    while next_url and page < 20:  # cap at 20 pages = 4000 cases per court
        try:
            r = await c.get(
                next_url,
                headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            )
            if r.status_code != 200:
                break
            data = r.json()
            results = data.get("results") or []
            out.extend(results)
            next_url = data.get("next")
            page += 1
        except Exception as exc:
            log.warning("bankruptcy.page_fetch_error", court=court, error=str(exc)[:100])
            break
    return out


async def enrich_with_bankruptcy(listings: list[Listing]) -> None:
    """Cross-reference defendants against recent bankruptcy filings."""
    if not listings:
        return
    token = _load_token()
    if not token:
        log.info("bankruptcy.no_token", hint="echo TOKEN > .secrets/courtlistener_token.txt to enable")
        return

    # Build a defendant-name -> listing index for fast lookup. Skip listings
    # that are themselves bankruptcy filings — they'd match themselves and
    # create noise; the source field already says "bankruptcy".
    by_token: dict[frozenset, list[Listing]] = {}
    for li in listings:
        if not li.defendant:
            continue
        if li.source and "bankruptcy" in li.source.lower():
            continue
        toks = _name_tokens(li.defendant)
        if len(toks) < 2:
            continue
        # Index by every 2-token subset to catch first+last matches
        from itertools import combinations
        for combo in combinations(sorted(toks), 2):
            by_token.setdefault(frozenset(combo), []).append(li)

    if not by_token:
        log.info("bankruptcy.no_named_defendants")
        return

    log.info("bankruptcy.start", indexed_listings=len(listings),
             token_keys=len(by_token), courts=len(COURTS))

    matched = 0
    total_filings = 0

    async with client(timeout=20.0) as c:
        for court in COURTS:
            filings = await _fetch_recent_bankruptcies(c, court, token)
            total_filings += len(filings)

            for f in filings:
                case_name = f.get("case_name") or ""
                if not case_name:
                    continue
                f_toks = _name_tokens(case_name)
                if len(f_toks) < 2:
                    continue

                # Find any listing whose defendant tokens overlap with this filing's.
                # Lazily fetch chapter only when we hit a real match — most filings
                # don't match anything, so we save 99% of API calls this way.
                from itertools import combinations
                hit_listings: set[int] = set()
                hit_lis_for_chapter: list[Listing] = []
                for combo in combinations(sorted(f_toks), 2):
                    key = frozenset(combo)
                    if key in by_token:
                        for li in by_token[key]:
                            if id(li) in hit_listings:
                                continue
                            hit_listings.add(id(li))
                            if not isinstance(li.raw, dict):
                                li.raw = {}
                            # Only keep most-recent match
                            existing = li.raw.get("bankruptcy")
                            if existing and existing.get("date_filed", "") > (f.get("date_filed") or ""):
                                continue
                            hit_lis_for_chapter.append(li)

                if not hit_lis_for_chapter:
                    continue

                # Match found — fetch chapter once, apply to all hit listings
                chapter = await _fetch_chapter(c, f, token)
                for li in hit_lis_for_chapter:
                    li.raw["bankruptcy"] = {
                        "court": court,
                        "case_name": case_name,
                        "docket_number": f.get("docket_number"),
                        "date_filed": f.get("date_filed"),
                        "chapter": chapter,
                        "absolute_url": f.get("absolute_url"),
                        "match_strategy": "name_tokens",
                    }
                matched += len(hit_lis_for_chapter)

    log.info("bankruptcy.done",
             listings=len(listings), matches=matched, total_filings=total_filings,
             courts=len(COURTS))
