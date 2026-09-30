"""Cross-reference existing listings against recent CourtListener bankruptcy
filings. For each listing whose defendant name matches a recent NC/SC
bankruptcy debtor, tag raw.bankruptcy = { chapter, date_filed, court, ... }.

Bankruptcy filing on the same person who's the foreclosure defendant is a
strong pre-foreclosure signal:
  - Chapter 13 = trying to stop the sale with the automatic stay
  - Chapter 7 = liquidation, property will be sold
  - Both: the borrower is in real distress, not just a paperwork glitch

Free with CourtListener API token (sign up at courtlistener.com/sign-up/).

LONG-OPEN DISCOVERY (2026-09-29, docs/dirty_deeds_synthesis_2026-09-10.md Tier B
#28: "bankruptcies open 10-15 years are the strongest variant"):

The recent-filings query above (`_fetch_recent_bankruptcies`, LOOKBACK_DAYS=180)
structurally CANNOT surface a case that has been open 10-15 years — such a case
was FILED 10-15 years ago, outside any "recent filings" window by definition.
Live-verified 2026-09-29 against the real CourtListener API that a genuinely
different query finds this population: the RECAP full-text search endpoint
supports a Lucene-style negative existence filter, `q=-dateTerminated:[* TO *]`,
which returns dockets with NO recorded termination date. Combined with
`filed_after`/`filed_before` set to a 10-15-year-old window, one court (ncwb)
returned 89 real candidates in a single 5-year slice — genuine, still-active-
looking Chapter 7/13 petitions (e.g. "Robert Lee Newman and Sharon Elaine
Newman", filed 2013-03-13, chapter 7, no date_terminated ~13 years later),
mixed with noise this module filters out: adversary proceedings (chapter is
blank on those; the chapter filter below drops them) and PACER training/test
entries ("Ted Mark Test and Tess Test", docket "00-18888" filed 2013 — the
docket-year-prefix sanity check below drops those; PACER always keeps the
docket's leading 2-digit year in sync with the real filing year, so a mismatch
means synthetic data, not a person).

`_fetch_long_open_bankruptcies` runs this query per court (a handful of results
each, not thousands) and feeds its output into the SAME name-matching loop
`enrich_with_bankruptcy` already runs for recent filings — a long-open debtor
whose name matches a CURRENT tax-delinquent or foreclosure defendant is exactly
the discovery mechanism the synthesis describes. Every match (recent or
long-open) gets `case_age_days` / `case_age_years` / `is_long_open` computed
from the docket's own date_filed (+ date_terminated when present) via
`signal_freshness.bankruptcy_case_age` — cheap, since the date was already
being captured and simply not surfaced as an age signal.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import structlog

from .http_client import client
from .models import Listing
from .scrapers.national.courtlistener_bankruptcy import _normalize_search_hit
from .signal_freshness import bankruptcy_case_age

log = structlog.get_logger()

API_BASE = "https://www.courtlistener.com/api/rest/v4"
COURTS = ("ncwb", "nceb", "scb")
LOOKBACK_DAYS = 180
PAGE_SIZE = 200

# --- long-open window: cases FILED 10-15 years ago, per the synthesis's own framing ---
LONG_OPEN_MIN_YEARS = 10
LONG_OPEN_MAX_YEARS = 15
# Full courts list for the long-open pass (the recent-filings pass above omits ncmb for
# historical reasons unrelated to this addition; the long-open query is cheap enough —
# a handful of results per court, not thousands — to just cover all 4).
LONG_OPEN_COURTS = ("ncwb", "ncmb", "nceb", "scb")
_VALID_CHAPTERS = {"7", "11", "12", "13"}
# PACER training/test entries live permanently in the corpus ("Test v. Test", "Ted Mark
# Test and Tess Test") and, unlike a real debtor, are never terminated — exactly the shape
# this query selects for. A real person's name is very unlikely to contain "test" as a
# whole word; belt-and-suspenders alongside the docket-year check below.
_TEST_CASE_RE = re.compile(r"\btest\b", re.I)
_DOCKET_YEAR_RE = re.compile(r"^(\d{2})-")


def _docket_year_matches_filed(docket_number: str, date_filed: str) -> bool:
    """PACER's docket-number convention prefixes every case with its 2-digit filing
    year (``13-50207`` was filed in 2013). A mismatch (``00-18888`` filed 2013) is a
    synthetic/placeholder entry, not a real case — confirmed live 2026-09-29 against
    two PACER test dockets that showed up in the long-open query's raw results."""
    if not docket_number or not date_filed:
        return False
    m = _DOCKET_YEAR_RE.match(docket_number.strip())
    if not m:
        return False
    try:
        filed_year = int(str(date_filed)[:4])
    except (TypeError, ValueError):
        return False
    return int(m.group(1)) == filed_year % 100


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


_BUSINESS_STOPWORDS = {
    "llc", "inc", "corp", "corporation", "co", "company", "ltd", "limited",
    "lp", "llp", "lc", "pa", "pllc", "pllp", "associates", "associate",
    "group", "groups", "holdings", "holding", "properties", "property",
    "investments", "investment", "partners", "partnership", "ventures",
    "venture", "enterprises", "enterprise", "trust", "trustee", "trustees",
    "bank", "banks", "fund", "funds", "capital", "the", "and",
}


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
    """Tokens of length >= 3 that are NOT generic business stopwords.
    Without the stopword filter, every "Smith Holdings LLC" matches every
    "Anderson Holdings LLC" via the (holdings, llc) pair — pure noise.
    """
    n = _normalize_name(name)
    return {t for t in n.split() if len(t) >= 3 and t not in _BUSINESS_STOPWORDS}


def _is_business_name(name: str) -> bool:
    """Heuristic: does the original (un-stopworded) name look like a business?"""
    n = _normalize_name(name)
    return any(tok in _BUSINESS_STOPWORDS for tok in n.split())


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


async def _fetch_long_open_bankruptcies(c, court: str, token: str, today: date | None = None) -> list[dict]:
    """Pull candidate LONG-OPEN bankruptcy petitions from one court: filed
    LONG_OPEN_MIN_YEARS-LONG_OPEN_MAX_YEARS years ago, with no recorded
    date_terminated. Returns dicts in the same shape as
    `_fetch_recent_bankruptcies` (case_name, docket_number, date_filed,
    absolute_url, chapter, date_terminated, ...) via the shared
    `_normalize_search_hit` mapper, pre-filtered to real individual/business
    petitions (valid chapter, docket-year sane, not a PACER test entry) so the
    caller's matching loop never has to special-case this source.

    Uses the RECAP full-text search endpoint (not /dockets/, which has no
    `isnull`-style filter for date_terminated — confirmed live 2026-09-29,
    CourtListener rejects `date_terminated__isnull` as an unknown param). The
    chapter comes back INLINE on this endpoint (same reason
    courtlistener_bankruptcy.py's scraper uses it), so — unlike the recent-
    filings path above — no per-docket bankruptcy_information lookup is ever
    needed here.
    """
    t = today or date.today()
    filed_after = (t - timedelta(days=365 * LONG_OPEN_MAX_YEARS)).strftime("%Y-%m-%d")
    filed_before = (t - timedelta(days=365 * LONG_OPEN_MIN_YEARS)).strftime("%Y-%m-%d")
    out: list[dict] = []
    next_url: Optional[str] = (
        f"{API_BASE}/search/?type=r&court={court}&filed_after={filed_after}"
        f"&filed_before={filed_before}&q=-dateTerminated%3A%5B*+TO+*%5D"
        f"&order_by=dateFiled%20asc&page_size=20"
    )
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    page = 0
    dropped_chapter = dropped_year_mismatch = dropped_test_name = 0
    while next_url and page < 10:  # a handful of real hits per court; 10 pages = 200 is ample headroom
        try:
            r = await c.get(next_url, headers=headers)
            if r.status_code != 200:
                break
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("bankruptcy.long_open_fetch_error", court=court, error=str(exc)[:100])
            break
        for hit in data.get("results") or []:
            d = _normalize_search_hit(hit, court)
            chapter = (d.get("chapter") or "").strip()
            if chapter not in _VALID_CHAPTERS:
                dropped_chapter += 1
                continue
            if not _docket_year_matches_filed(d.get("docket_number") or "", d.get("date_filed") or ""):
                dropped_year_mismatch += 1
                continue
            if _TEST_CASE_RE.search(d.get("case_name") or ""):
                dropped_test_name += 1
                continue
            out.append(d)
        next_url = data.get("next")
        page += 1
    log.info("bankruptcy.long_open_fetched", court=court, kept=len(out),
              dropped_chapter=dropped_chapter, dropped_year_mismatch=dropped_year_mismatch,
              dropped_test_name=dropped_test_name)
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
    #
    # We also store the FULL distinctive-token set per listing so we can
    # require strict subset overlap downstream (avoids "Smith Holdings LLC"
    # matching "Anderson Holdings LLC" via shared business stopwords).
    by_token: dict[frozenset, list[tuple[Listing, frozenset]]] = {}
    for li in listings:
        if not li.defendant:
            continue
        if li.source and "bankruptcy" in li.source.lower():
            continue
        toks = _name_tokens(li.defendant)
        if len(toks) < 2:
            continue
        toks_frozen = frozenset(toks)
        # Index by every 2-token subset to catch first+last matches
        from itertools import combinations
        for combo in combinations(sorted(toks), 2):
            by_token.setdefault(frozenset(combo), []).append((li, toks_frozen))

    if not by_token:
        log.info("bankruptcy.no_named_defendants")
        return

    log.info("bankruptcy.start", indexed_listings=len(listings),
             token_keys=len(by_token), courts=len(COURTS))

    matched = 0
    total_filings = 0
    long_open_matched = 0

    async def _match_filings(c, court: str, filings: list[dict], *, signal: str,
                              chapter_known: bool) -> int:
        """Shared matching loop for both the recent-filings and long-open
        passes below. `chapter_known` skips the lazy per-match chapter
        lookup for long-open hits, which already carry chapter inline from
        the /search/ endpoint (see _fetch_long_open_bankruptcies)."""
        n_matched = 0
        for f in filings:
            case_name = f.get("case_name") or ""
            if not case_name:
                continue
            f_toks = _name_tokens(case_name)
            if len(f_toks) < 2:
                continue

            # Find any listing whose defendant tokens overlap with this
            # filing's STRICTLY: every distinctive token of the listing's
            # defendant must appear in the filing's case_name. This kills
            # the false positives where "Smith Holdings LLC" was matching
            # "Anderson Holdings LLC" via just two stopword tokens.
            #
            # Lazily fetch chapter only when we hit a real match — most
            # filings don't match anything, so we save ~99% of API calls.
            from itertools import combinations
            f_toks_frozen = frozenset(f_toks)
            hit_listings: set[int] = set()
            hit_lis_for_chapter: list[Listing] = []
            for combo in combinations(sorted(f_toks), 2):
                key = frozenset(combo)
                if key in by_token:
                    for li, li_toks in by_token[key]:
                        if id(li) in hit_listings:
                            continue
                        # STRICT subset check: every distinctive token of
                        # the foreclosure defendant must appear in the
                        # bankruptcy case_name. This eliminates the LLC-
                        # token noise without missing real matches.
                        if not li_toks.issubset(f_toks_frozen):
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

            # Match found — chapter is either already known (long-open path,
            # from the search endpoint) or fetched once here and applied to
            # every hit listing (recent-filings path).
            chapter = (f.get("chapter") or "").strip() if chapter_known else await _fetch_chapter(c, f, token)
            age_flags = bankruptcy_case_age(
                {"date_filed": f.get("date_filed"), "date_terminated": f.get("date_terminated")}
            )
            for li in hit_lis_for_chapter:
                li.raw["bankruptcy"] = {
                    "court": court,
                    "case_name": case_name,
                    "docket_number": f.get("docket_number"),
                    "date_filed": f.get("date_filed"),
                    "date_terminated": f.get("date_terminated"),
                    "chapter": chapter,
                    "absolute_url": f.get("absolute_url"),
                    "match_strategy": "strict_subset",
                    "signal": signal,
                    **age_flags,
                }
            n_matched += len(hit_lis_for_chapter)
        return n_matched

    async with client(timeout=20.0) as c:
        for court in COURTS:
            filings = await _fetch_recent_bankruptcies(c, court, token)
            total_filings += len(filings)
            matched += await _match_filings(c, court, filings, signal="recent_filing",
                                             chapter_known=False)

        # Long-open pass (Tier B #28): a SEPARATE, much older filing window that the
        # recent-filings pass above cannot reach. Runs over LONG_OPEN_COURTS (all 4)
        # rather than COURTS (3) — see that constant's comment.
        for court in LONG_OPEN_COURTS:
            long_open_filings = await _fetch_long_open_bankruptcies(c, court, token)
            long_open_matched += await _match_filings(
                c, court, long_open_filings, signal="long_open", chapter_known=True)
        matched += long_open_matched

    log.info("bankruptcy.done",
             listings=len(listings), matches=matched, total_filings=total_filings,
             long_open_matches=long_open_matched, courts=len(COURTS))
