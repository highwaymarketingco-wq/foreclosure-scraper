"""People-search sites — TruePeopleSearch, FastPeopleSearch.

truepeoplesearch.com and fastpeoplesearch.com are behind Cloudflare.
They provide free people search (name, address, phone) which is useful
for enriching owner/defendant names with contact info.

Strategy: Use wall_bypass escalation (curl-cffi → pydoll → nodriver)
to get past Cloudflare, then search by name and parse results.

REAL NAMES, NOT A STUB (fixed 2026-10-12). This scraper used to search three
hardcoded placeholder names ("John Smith", "Robert Johnson", "Mary Davis")
forever — confirmed live: it has never searched a real board name. Candidates
now come from a cheap, bounded stream of the real board (`_candidate_names()`,
via `board_stream.iter_board_rows()`, which never materializes the whole
board), picking person-looking owner/defendant names on rows that don't
already carry an owner_phone, capped at `_MAX_CANDIDATES` per run so this
stays a quick per-run sample, not a full-board sweep.

NOT WIRED TO owner_phone / any dialing field (deliberate). enrichment_voter_
phone.py already established a TCPA/do-not-dial compliance line around
owner_phone on this board — a number from a people-search aggregator carries
the same dialing risk, so it does not get to skip that line by arriving
through a different scraper. This module writes to its own hand-off ledger
(docs/handoff/people_search_results.json, same cumulative-ledger shape as
sos_agent_handoff.py) instead of fabricating board rows or touching
raw['owner_phone'] directly. Whether/how a resolved contact should reach
outreach is the owner's call, not this scraper's.

`run_walled_sources.py`'s SKIP_SOURCES currently skips this whole source with
the blanket reason "All people-search sites 403 on Oracle Cloud IP" — live-
checked 2026-10-12 from a non-Oracle IP: truepeoplesearch.com still 403s,
but fastpeoplesearch.com returns a clean 200 with real content. The "all" in
that comment is wrong for fastpeoplesearch specifically; it may be an
Oracle-datacenter-IP-range block rather than a block on the site generally.
Left in SKIP_SOURCES for now (this fix only addresses the stub-names bug,
not the network path) — flagged separately for Hermes to test from a
non-Oracle egress before re-enabling.

MULTI-CANDIDATE CAPTURE (fixed 2026-10-14). Live-verified both sites return
many distinct people per name search, and the old `cards[0]`-only code
captured none of them correctly:
  - fastpeoplesearch needs the wall_bypass browser tier to clear Cloudflare
    (curl-cffi impersonation still 403s as of this check), and that tier
    (wall_bypass.fetch_with_pydoll / fetch_with_nodriver) returns flattened
    visible TEXT, not HTML (see wall_bypass._html_to_text) — so the old
    BeautifulSoup `.select(".card", ...)` call always found zero elements
    and every search silently recorded "no_match", even when the page body
    plainly listed 9-10 free candidates.
  - truepeoplesearch's curl-cffi tier still returns real HTML with `.card`
    elements, but `cards[0]` was the "Search Neighbors" form widget, not a
    person — the real results are the `.card-summary` cards further down
    (confirmed live: 10 real candidates on a "John Smith" search, excluding
    a hidden `.d-none` duplicate of the first one).
Fix: parse ALL matching cards (DOM path, per-site `card_selector`, skipping
hidden duplicates and non-person chrome by requiring an "Age NN" marker),
and fall back to a regex pass over the flattened text (DOM path finds
nothing — the realistic case) that anchors on the "<Name> Age <NN> •
<City>, <ST> ... View Free Details" shape of a real, free result card;
sponsored/paid cards lack that shape and are excluded by construction.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_SITES = {
    "truepeoplesearch": {
        "url": "https://www.truepeoplesearch.com",
        "search_path": "/results?name=",
        # Live-verified 2026-10-14: real person cards. cards[0] used to be
        # the "Search Neighbors" form widget — not a person.
        "card_selector": ".card-summary",
    },
    "fastpeoplesearch": {
        "url": "https://www.fastpeoplesearch.com",
        "search_path": "/name/",
        # Generic fallback — live-verified 2026-10-14 this site is reached
        # through the browser wall_bypass tier, which returns flattened
        # text (no tags at all), so this selector matches zero elements in
        # practice and `_matches_from_text` does the real work. Left here
        # in case a plain/impersonate fetch ever returns real tagged HTML.
        "card_selector": ".card, .result-card, .person-card, .search-result, .listing",
    },
}

# Bail out of candidate selection once we have this many names — this is a
# per-run sample pass, not a full-board sweep. Re-run picks up names that
# weren't already resolved in the ledger (see _load_ledger/_already_checked).
_MAX_CANDIDATES = 40

# Cap distinct candidate matches kept per name per site — defensive, not
# hit in live testing (max seen was 10).
_MAX_MATCHES_PER_SITE = 20

_AGE_RE = re.compile(r"Age\s*(\d{1,3})")
_STREET_ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
    r"(?:St|Street|Ave|Avenue|Blvd|Dr|Rd|Road|"
    r"Lane|Ln|Way|Pl|Ct))",
)
_PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_NAME_BEFORE_AGE_RE = re.compile(r"^(.*?)\s+Age\s*\d{1,3}")

# Flattened-text fallback card shape, live-confirmed against real
# fastpeoplesearch output 2026-10-14. Each free (non-sponsored) result
# reads "<Name> Age <NN> • <City>, <ST> Past Addresses: ... Relatives:
# ... AKA: ... View Free Details" in the flattened text; sponsored/paid
# cards ("<Name> <City>, <ST> Age <NN> View Details Sponsored By ...") lack
# the Past Addresses/Relatives/AKA/"View Free Details" markers and never
# match, so they're excluded by construction.
#
# `name` is pinned to exactly 2 capitalized tokens immediately before
# "Age" — live-verified this correctly bounds every real card, including
# the first one on a results page, which directly follows a run of
# capitalized city names (the popular-cities list) with no tag boundary
# to mark where the boilerplate ends and the real name starts; a looser
# token count re-introduces that over-match. Tradeoff: a 3+-token legal
# name would be truncated to its last two tokens. Acceptable — this ledger
# is a best-effort, human-reviewed enrichment side-channel, never written
# to board rows (see module docstring).
_TEXT_CARD_RE = re.compile(
    r"(?P<name>[A-Z][A-Za-z.'-]+\s+[A-Z][A-Za-z.'-]+)\s+Age\s+(?P<age>\d{1,3})"
    r"\s*[•·]\s*(?P<city>[A-Za-z.'\s-]+?,\s*[A-Z]{2})\s+"
    r"Past Addresses:\s*(?P<past>.*?)\s+Relatives:\s*(?P<relatives>.*?)\s+"
    r"AKA:\s*(?P<aka>.*?)\s+View Free Details"
)


def _matches_from_text(text: str, limit: int = _MAX_MATCHES_PER_SITE) -> list[dict]:
    """Every free (non-sponsored) candidate card found in flattened text —
    the realistic path once a search needs the wall_bypass browser tier
    (see module docstring)."""
    out: list[dict] = []
    for m in _TEXT_CARD_RE.finditer(text):
        out.append({
            "name": m.group("name").strip(),
            "age": m.group("age"),
            "city": m.group("city").strip(),
            "address": None,
            "phone": None,
            "full_text": m.group(0)[:500],
        })
        if len(out) >= limit:
            break
    return out


def _matches_from_cards(cards: list, limit: int = _MAX_MATCHES_PER_SITE) -> list[dict]:
    """Every real person-result card in a parsed DOM — skips hidden
    duplicates (`.d-none`) and non-person chrome (search form, filters,
    ads, alerts) by requiring an "Age NN" marker in the card's own text."""
    out: list[dict] = []
    for card in cards:
        classes = card.get("class") or []
        if "d-none" in classes:
            continue
        text = card.get_text(separator=" ", strip=True)
        age_match = _AGE_RE.search(text)
        if not age_match:
            continue
        name_match = _NAME_BEFORE_AGE_RE.match(text)
        addr_match = _STREET_ADDR_RE.search(text)
        phone_match = _PHONE_RE.search(text)
        out.append({
            "name": name_match.group(1).strip() if name_match else None,
            "age": age_match.group(1),
            "city": None,
            "address": addr_match.group(1) if addr_match else None,
            "phone": phone_match.group(0) if phone_match else None,
            "full_text": text[:500],
        })
        if len(out) >= limit:
            break
    return out

_ENTITY_RE = re.compile(
    r"\b(LLC|L\.L\.C\.|INC|INCORPORATED|CORP|CORPORATION|CO\b|COMPANY|"
    r"LP\b|LLP\b|TRUST|ESTATE OF|BANK|TAX COLLECTOR|COUNTY|CITY OF|"
    r"HOMEOWNERS|ASSOCIATION|HOA\b|CHURCH|MINISTR|TEMPLE|CHAPEL|"
    r"CONGREGATION|SCHOOL|ACADEMY|UNIVERSITY|FOUNDATION|MINISTRIES)",
    re.I,
)
_LEDGER_PATH = Path("docs/handoff/people_search_results.json")


def _looks_like_person(name: str | None) -> str | None:
    """A cleaned person-looking name, or None (entity, blank, or junk)."""
    if not name:
        return None
    name = name.strip()
    if not name or len(name) < 4:
        return None
    if _ENTITY_RE.search(name):
        return None
    # Needs at least a first + last token to be worth searching.
    if len(name.split()) < 2:
        return None
    return name


def _already_checked(ledger: dict, name: str) -> bool:
    key = name.strip().lower()
    return key in ledger.get("names", {})


def _load_ledger() -> dict:
    if _LEDGER_PATH.exists():
        try:
            return json.loads(_LEDGER_PATH.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"schema": 1, "kind": "people_search_results", "names": {}}


def _save_ledger(ledger: dict) -> None:
    ledger["generated_at"] = datetime.now(timezone.utc).isoformat()
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LEDGER_PATH.write_text(json.dumps(ledger, indent=2, sort_keys=True))


def _candidate_names(limit: int = _MAX_CANDIDATES) -> list[str]:
    """Up to `limit` real, not-yet-checked, person-looking owner/defendant
    names from the board, via a bounded stream (never loads the whole
    board). A row already carrying raw['owner_phone'] is skipped — it
    already has a contact path, it doesn't need this one too."""
    from ...board_stream import iter_board_rows

    ledger = _load_ledger()
    seen: set[str] = set()
    out: list[str] = []
    try:
        for row in iter_board_rows():
            if len(out) >= limit:
                break
            raw = row.get("raw") if isinstance(row, dict) else None
            if isinstance(raw, dict) and raw.get("owner_phone"):
                continue
            for field in ("owner_name", "defendant"):
                name = _looks_like_person(row.get(field) if isinstance(row, dict) else None)
                if not name:
                    continue
                key = name.lower()
                if key in seen or _already_checked(ledger, name):
                    continue
                seen.add(key)
                out.append(name)
                if len(out) >= limit:
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("people_search.candidate_scan_error", error=str(exc)[:200])
    return out


class PeopleSearchScraper(BaseScraper):
    """People-search sites via wall_bypass."""

    slug = "national.people_search"
    name = "People Search Sites"
    category = "people_search"
    timeout_s = 300.0

    async def fetch(self) -> list[Listing]:
        """Looks up real board names, writes resolved contacts to the
        hand-off ledger, and returns [] — this scraper enriches existing
        rows (via a human/owner decision on the ledger output), it does not
        create new lead rows, so there is nothing for safe_run to merge
        into the board directly."""
        names = _candidate_names()
        if not names:
            log.info("people_search.no_candidates")
            return []

        ledger = _load_ledger()
        resolved = 0
        checked = 0

        for name in names:
            entry = {"name": name, "checked_at": datetime.now(timezone.utc).date().isoformat(),
                      "sites": {}}
            found_any = False

            for site_name, cfg in _SITES.items():
                try:
                    search_url = f"{cfg['url']}{cfg['search_path']}" \
                                 f"{name.replace(' ', '+')}"
                    log.info("people_search.fetching", site=site_name, name=name)

                    html = await get_text(search_url, wall_bypass=True, timeout=30.0)

                    if not html or len(html) < 500:
                        from ...wall_bypass import fetch_with_nodriver
                        html = await fetch_with_nodriver(search_url, timeout_s=45)

                    if not html or len(html) < 500:
                        log.warning("people_search.empty", site=site_name, name=name)
                        entry["sites"][site_name] = {"status": "blocked_or_empty"}
                        continue

                    soup = BeautifulSoup(html, "html.parser")
                    cards = soup.select(cfg["card_selector"])

                    # DOM path first (real tagged HTML, e.g. truepeoplesearch
                    # via curl-cffi); fall back to the flattened-text regex
                    # path when no cards parse out (the realistic case for a
                    # site reached only through the wall_bypass browser
                    # tier, which returns visible text with no tags at all
                    # — see module docstring).
                    matches = _matches_from_cards(cards) if cards else []
                    if not matches:
                        matches = _matches_from_text(
                            soup.get_text(separator=" ", strip=True)
                        )

                    if not matches:
                        entry["sites"][site_name] = {"status": "no_match"}
                        continue

                    entry["sites"][site_name] = {
                        "status": "found",
                        "match_count": len(matches),
                        "matches": matches,
                    }
                    found_any = True

                except Exception as exc:
                    log.warning("people_search.search_error", site=site_name, name=name,
                                error=str(exc)[:200])
                    entry["sites"][site_name] = {"status": "error", "detail": str(exc)[:160]}

            ledger["names"][name.lower()] = entry
            checked += 1
            if found_any:
                resolved += 1

        _save_ledger(ledger)
        log.info("people_search.run_done", checked=checked, resolved=resolved)
        return []
