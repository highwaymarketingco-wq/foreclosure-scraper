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
    },
    "fastpeoplesearch": {
        "url": "https://www.fastpeoplesearch.com",
        "search_path": "/name/",
    },
}

# Bail out of candidate selection once we have this many names — this is a
# per-run sample pass, not a full-board sweep. Re-run picks up names that
# weren't already resolved in the ledger (see _load_ledger/_already_checked).
_MAX_CANDIDATES = 40

_ENTITY_RE = re.compile(
    r"\b(LLC|L\.L\.C\.|INC|INCORPORATED|CORP|CORPORATION|CO\b|COMPANY|"
    r"LP\b|LLP\b|TRUST|ESTATE OF|BANK|TAX COLLECTOR|COUNTY|CITY OF|"
    r"HOMEOWNERS|ASSOCIATION|HOA\b)",
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
                    cards = soup.select(
                        ".card, .result-card, .person-card, "
                        ".search-result, .listing"
                    )

                    if not cards:
                        entry["sites"][site_name] = {"status": "no_match"}
                        continue

                    card = cards[0]
                    text = card.get_text(separator=" | ", strip=True)
                    addr_match = re.search(
                        r"(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
                        r"(?:St|Street|Ave|Avenue|Blvd|Dr|Rd|Road|"
                        r"Lane|Ln|Way|Pl|Ct))",
                        text,
                    )
                    age_match = re.search(r"Age\s*(\d+)", text, re.I)
                    phone_match = re.search(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)

                    entry["sites"][site_name] = {
                        "status": "found",
                        "address": addr_match.group(1) if addr_match else None,
                        "age": age_match.group(1) if age_match else None,
                        "phone": phone_match.group(0) if phone_match else None,
                        "full_text": text[:500],
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
