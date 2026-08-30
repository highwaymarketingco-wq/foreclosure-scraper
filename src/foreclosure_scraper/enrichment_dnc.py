"""DNC (Do Not Call) scrubber enrichment — FTC National Do Not Call Registry.

Every phone number surfaced by the voter_phone or skip_trace enrichers is tagged
needs_dnc_scrub=True. This module checks each phone against a local DNC registry
CSV (operator downloads from https://www.donotcall.gov/ — free, requires
registration as a telemarketer/seller). If no local DNC file exists, all numbers
are tagged dnc_status="unverified" so the outreach stack never dials blind.

The module is 100% free: no API calls, no paid services. It loads the DNC file
into a set of 10-digit numbers at startup and checks membership in O(1).

DNC file expected at: data/dnc_registry.csv
Format: one phone number per line (10-digit, no dashes), or CSV with a phone column.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

import structlog

from .models import Listing

log = structlog.get_logger()

_DNC_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "dnc_registry.csv"
_DNC_SET: set[str] | None = None


def _normalize_phone(phone: str | None) -> str | None:
    """Extract 10-digit phone (strip country code 1, non-digits)."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return digits
    return None


def _load_dnc() -> set[str] | None:
    """Load DNC registry CSV into a set of 10-digit strings."""
    global _DNC_SET
    if _DNC_SET is not None:
        return _DNC_SET
    if not _DNC_PATH.exists():
        log.info("dnc.no_local_file", path=str(_DNC_PATH))
        _DNC_SET = set()  # empty = no scrub possible, but don't re-attempt load
        return None  # signal: no file available
    numbers: set[str] = set()
    try:
        with _DNC_PATH.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                # Try first column that looks like a phone number
                for cell in row:
                    ph = _normalize_phone(cell)
                    if ph:
                        numbers.add(ph)
                        break
        _DNC_SET = numbers
        log.info("dnc.loaded", count=len(numbers), path=str(_DNC_PATH))
    except Exception as exc:
        log.error("dnc.load_failed", error=str(exc)[:200])
        _DNC_SET = set()
        return None
    return _DNC_SET


def _get_phones(li: Listing) -> list[str]:
    """Extract all phone numbers from a listing (voter_phone + skip_trace + free_phones + sc_voter_xref)."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    phones: list[str] = []
    # voter_phone enricher: raw['owner_phone']['phone']
    op = raw.get("owner_phone")
    if isinstance(op, dict) and op.get("phone"):
        ph = _normalize_phone(op["phone"])
        if ph:
            phones.append(ph)
    # skip_trace enricher: raw['skip_trace']['phone_numbers'] (list)
    st = raw.get("skip_trace")
    if isinstance(st, dict):
        for p in st.get("phone_numbers") or []:
            ph = _normalize_phone(p)
            if ph and ph not in phones:
                phones.append(ph)
    # free_phones enricher: raw['free_phones'] (list of dicts with 'phone')
    fp = raw.get("free_phones")
    if isinstance(fp, list):
        for entry in fp:
            if isinstance(entry, dict) and entry.get("phone"):
                ph = _normalize_phone(entry["phone"])
                if ph and ph not in phones:
                    phones.append(ph)
    # sc_voter_xref enricher: raw['sc_voter_xref']['phone']
    sx = raw.get("sc_voter_xref")
    if isinstance(sx, dict) and sx.get("phone"):
        ph = _normalize_phone(sx["phone"])
        if ph and ph not in phones:
            phones.append(ph)
    return phones


def enrich_dnc_scrub(listings) -> dict:
    """Scrub phone numbers against the FTC DNC registry.

    Sets li.raw['dnc_scrub'] = list of {phone, dnc_registered, dnc_status, scrubbed_at}.
    """
    dnc = _load_dnc()
    now = datetime.now(timezone.utc).isoformat()
    stats = {"total_listings": len(listings), "listings_with_phone": 0, "scrubbed": 0, "registered": 0, "clear": 0, "unverified": 0}

    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        if not raw:
            continue
        phones = _get_phones(li)
        if not phones:
            continue
        stats["listings_with_phone"] += 1

        # Skip already-scrubbed listings (idempotent)
        existing = raw.get("dnc_scrub")
        if isinstance(existing, list) and existing:
            stats["scrubbed"] += 1
            continue

        results = []
        for ph in phones:
            if dnc is None:
                # No local DNC file — tag unverified, don't dial blind
                results.append({
                    "phone": ph,
                    "dnc_registered": None,
                    "dnc_status": "unverified",
                    "scrubbed_at": now,
                })
                stats["unverified"] += 1
            else:
                is_registered = ph in dnc
                results.append({
                    "phone": ph,
                    "dnc_registered": is_registered,
                    "dnc_status": "registered" if is_registered else "clear",
                    "scrubbed_at": now,
                })
                if is_registered:
                    stats["registered"] += 1
                else:
                    stats["clear"] += 1

        raw["dnc_scrub"] = results
        stats["scrubbed"] += 1

    log.info("dnc.done", **{k: v for k, v in stats.items() if isinstance(v, int)})
    return stats
