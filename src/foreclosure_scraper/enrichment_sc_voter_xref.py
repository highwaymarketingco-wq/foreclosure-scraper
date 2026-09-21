"""SC phone enrichment via NC voter file cross-reference.

SC has no free bulk voter file with phones. But many SC property owners live in NC
(or have NC records). This enricher cross-references SC foreclosure owner names
against the NC voter file (NCSBE) to find phone numbers.

CONSERVATIVE: Only matches on (last, first) when that name is UNIQUE in the NC voter
file (exactly one active NC voter with that name has a phone). Ambiguous names
(multiple voters with different phones) are skipped to avoid false positives.

A UNIQUE NAME IS NOT AN IDENTITY. It means one NC voter has that name, not that the SC owner
is that voter, and the owner's mailing address is an SC address in 93% of the stored matches.
So every match now goes through the identity gate in enrichment_sc_phone at write time:

  * an entity or estate owner (LLC, INC, VFW POST, TRUST, ESTATE ...) is never matched;
  * every other match is stored with identity_check = corroborated | unverified |
    contradicted, and do_not_dial = True unless it is corroborated (the owner mails to an NC
    address that is the voter's residential street, or name + middle initial + county agree);
  * the phone value is always kept, so nothing is lost, only flagged;
  * phones already stored by an earlier run are re-checked on every run, because owner_name is
    promoted from the assessor AFTER this step runs and a phone stamped for one owner can end up
    on another.

The gate is fail-closed: the phone is written with do_not_dial True and the gate then clears it
only on evidence, so an error in the gate leaves a flagged phone, never a dialable one.

Every number is tagged source=ncsbe_voter_xref + needs_dnc_scrub=True.
"""
from __future__ import annotations

import re
from pathlib import Path

# Reuse the NC voter index builder
from foreclosure_scraper.enrichment_voter_phone import _build_index, _name_candidates
from foreclosure_scraper.enrichment_sc_phone import (
    GATE_REASON_PREFIX,
    UNVERIFIED,
    XREF_SOURCES,
    flag_unverified_xref_phones,
    owner_is_non_person,
)


_NAME_INDEX: dict | None = None


def _build_name_only_index() -> dict:
    """Build a (last, first) -> phone index from NC voter file.

    Only includes names where exactly one active NC voter has that name+phone
    (unambiguous = safe). Names with multiple phone numbers are excluded.
    """
    _, name_county, _, _ = _build_index()

    name_only: dict = {}
    name_counts: dict = {}

    for (cty, last, first), ph in name_county.items():
        key = (last, first)
        if key not in name_counts:
            name_counts[key] = set()
        name_counts[key].add(ph)

    # Only keep names with exactly one unique phone
    for key, phones in name_counts.items():
        if len(phones) == 1:
            name_only[key] = next(iter(phones))

    return name_only


def _set_phone(li, ph: str, match: str):
    """Store the match FAIL-CLOSED: flagged unverified until the gate finds evidence."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["owner_phone"] = {
        "phone": f"({ph[0:3]}) {ph[3:6]}-{ph[6:]}",
        "source": "ncsbe_voter_xref",
        "line_type": "unknown",
        "needs_dnc_scrub": True,
        "match": match,
        "identity_check": UNVERIFIED,
        "do_not_dial": True,
        "do_not_dial_reason": GATE_REASON_PREFIX + UNVERIFIED,
    }


def enrich_sc_phone_xref(listings) -> dict:
    """Cross-reference SC owner names against NC voter file for phones, behind the identity gate.

    Returns the original counters (sc_targets, matched, skipped_no_owner, skipped_ambiguous)
    plus skipped_entity, regated (phones from earlier runs re-checked) and the gate's verdict
    counts over everything it looked at (corroborated, unverified, contradicted, do_not_dial).
    `matched` counts phones written this run, including the ones stored flagged do_not_dial.
    """
    global _NAME_INDEX
    if _NAME_INDEX is None:
        _NAME_INDEX = _build_name_only_index()

    stats = {
        "sc_targets": 0,
        "matched": 0,
        "skipped_no_owner": 0,
        "skipped_ambiguous": 0,
        "skipped_entity": 0,
        "regated": 0,
    }
    written = []      # matched this run
    earlier = []      # xref phones an earlier run stored: re-checked, never re-matched

    for li in listings:
        if li.state != "SC":
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        existing = raw.get("owner_phone")
        if existing:
            if isinstance(existing, dict) and str(existing.get("source") or "") in XREF_SOURCES:
                earlier.append(li)
            continue                                   # never clobber a phone from any source
        if not li.owner_name:
            stats["skipped_no_owner"] += 1
            continue
        if owner_is_non_person(li.owner_name):
            stats["skipped_entity"] += 1               # a person's phone on an LLC or a post
            continue

        stats["sc_targets"] += 1

        cands = list(_name_candidates(li.owner_name))
        for last, first in cands:
            ph = _NAME_INDEX.get((last, first))
            if ph:
                _set_phone(li, ph, f"nc_xref:{last},{first}")
                stats["matched"] += 1
                written.append(li)
                break

    to_gate = written + earlier
    stats["regated"] = len(earlier)
    if to_gate:
        gate = flag_unverified_xref_phones(to_gate, apply=True)
        for k in ("corroborated", "unverified", "contradicted", "do_not_dial"):
            stats[k] = gate[k]

    return stats
