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

PHONES THAT ARE NEVER SCRUBBED AS DIALABLE (see enrichment_sc_phone)
    A phone that must not be dialed gets a dnc_scrub entry with dnc_status "do_not_dial" (and a
    block_reason), never "clear": do_not_dial True on the phone, an NC-voter-xref phone whose
    identity is not corroborated, a people-search phone, everything in raw.free_phones. An agent,
    attorney or trustee phone gets "not_owner_contact". A scrub result from before a phone was
    gated is downgraded on the next run, and a phone whose block is later lifted is re-scrubbed.
    The lane rules themselves (role "agent", do_not_dial on the walled people-search lane) are
    stamped here too, so a phone written by an enricher that predates the gate is still tagged.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

import structlog

from .enrichment_sc_phone import (
    WALLED_REASON,
    flag_lane_phones,
    owner_phone_block_reason,
)
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


def _get_phone_records(li: Listing) -> list[tuple[str, str | None]]:
    """Every phone on a listing as (10 digits, block reason or None).

    A reason means the phone must not be dialed as the owner's number (do_not_dial, an
    uncorroborated NC-voter-xref match, a people-search phone, an agent). Sources: owner_phone
    (voter_phone, surfaced contacts, county phones, liensnc), skip_trace, free_phones and
    sc_voter_xref. A number listed twice keeps the unblocked status if any source clears it.
    """
    if not isinstance(li.raw, dict):
        li.raw = {}
    raw = li.raw
    found: dict[str, str | None] = {}

    def _add(phone, reason: str | None) -> None:
        ph = _normalize_phone(phone)
        if not ph:
            return
        if ph not in found or (found[ph] is not None and reason is None):
            found[ph] = reason

    # voter_phone enricher: raw['owner_phone']['phone']
    op = raw.get("owner_phone")
    if isinstance(op, dict) and op.get("phone"):
        _add(op["phone"], owner_phone_block_reason(op))
    # skip_trace enricher: raw['skip_trace']['phone_numbers'] (list)
    st = raw.get("skip_trace")
    if isinstance(st, dict):
        for p in st.get("phone_numbers") or []:
            _add(p, None)
    # free_phones enricher: raw['free_phones'] (list of dicts with 'phone'). People-search lane: walled.
    fp = raw.get("free_phones")
    if isinstance(fp, list):
        for entry in fp:
            if isinstance(entry, dict) and entry.get("phone"):
                _add(entry["phone"], WALLED_REASON)
    # sc_voter_xref enricher: raw['sc_voter_xref']['phone'], always an NC-voter xref phone
    sx = raw.get("sc_voter_xref")
    if isinstance(sx, dict) and sx.get("phone"):
        _add(sx["phone"], owner_phone_block_reason({**sx, "source": "sc_voter_xref"}))
    return list(found.items())


def _get_phones(li: Listing) -> list[str]:
    """The phones on a listing that may be scrubbed as dialable (blocked ones excluded)."""
    return [ph for ph, why in _get_phone_records(li) if why is None]


def _blocked_status(reason: str) -> str:
    return "not_owner_contact" if reason == "agent_contact" else "do_not_dial"


def enrich_dnc_scrub(listings) -> dict:
    """Scrub phone numbers against the FTC DNC registry.

    Sets li.raw['dnc_scrub'] = list of {phone, dnc_registered, dnc_status, scrubbed_at}.
    A phone that must not be dialed is recorded with dnc_status "do_not_dial" (or
    "not_owner_contact" for an agent) and a block_reason, and is never scrubbed as clear.
    """
    dnc = _load_dnc()
    now = datetime.now(timezone.utc).isoformat()
    stats = {"total_listings": len(listings), "listings_with_phone": 0, "scrubbed": 0, "registered": 0,
             "clear": 0, "unverified": 0, "blocked": 0}

    # Stamp the lane rules first (role agent, people-search do_not_dial) so the block reasons
    # below see them and the flags persist on the row.
    lane = flag_lane_phones(listings, apply=True)
    stats["agent_tagged"] = lane["agent_tagged"]
    stats["walled_flagged"] = lane["walled_flagged"] + lane["free_phones_flagged"]

    for li in listings:
        if not isinstance(li.raw, dict):
            li.raw = {}
        raw = li.raw
        if not raw:
            continue
        records = _get_phone_records(li)
        if not records:
            continue
        stats["listings_with_phone"] += 1

        # Idempotent: an entry already scrubbed stays. A phone with no entry yet is scrubbed, a
        # phone gated after its scrub is downgraded, and a phone whose block was lifted is redone.
        existing = raw.get("dnc_scrub")
        results = list(existing) if isinstance(existing, list) else []
        have: dict[str, dict] = {}
        for e in results:
            if isinstance(e, dict):
                d = _normalize_phone(e.get("phone"))
                if d:
                    have[d] = e

        for ph, why in records:
            entry = have.get(ph)
            if why:
                status = _blocked_status(why)
                stats["blocked"] += 1
                if entry is None:
                    entry = {"phone": ph, "dnc_registered": None}
                    results.append(entry)
                    have[ph] = entry
                if entry.get("dnc_status") != status or entry.get("block_reason") != why:
                    entry.update({"dnc_status": status, "block_reason": why, "scrubbed_at": now})
                continue
            if entry is not None and entry.get("dnc_status") not in ("do_not_dial", "not_owner_contact"):
                continue                                   # already scrubbed as dialable-or-not by the registry
            if dnc is None:
                # No local DNC file, tag unverified, don't dial blind
                fresh = {"phone": ph, "dnc_registered": None, "dnc_status": "unverified", "scrubbed_at": now}
                stats["unverified"] += 1
            else:
                is_registered = ph in dnc
                fresh = {"phone": ph, "dnc_registered": is_registered,
                         "dnc_status": "registered" if is_registered else "clear", "scrubbed_at": now}
                stats["registered" if is_registered else "clear"] += 1
            if entry is None:
                results.append(fresh)
                have[ph] = fresh
            else:
                entry.clear()
                entry.update(fresh)

        raw["dnc_scrub"] = results
        stats["scrubbed"] += 1

    log.info("dnc.done", **{k: v for k, v in stats.items() if isinstance(v, int)})
    return stats
