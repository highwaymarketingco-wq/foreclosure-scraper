"""NC voter-file phone enrichment — the one FREE, ToS-clean personal-phone source.

NCSBE publishes the full voter file as a free bulk download; the `full_phone_number` column
is ~69% populated (live-verified Buncombe 2026-06-29). For NC owner-OCCUPANTS we match the
foreclosure owner (name AND property address) to an ACTIVE voter record -> phone.

CONSERVATIVE BY DESIGN: both the name and the street (house number + street token) must match,
so a hit means the same person at the same address — near-zero false positives. Absentee owners
(owner mailing address != property) won't match here; their phone isn't in this file, and that's
fine (they're the direct-mail / business-phone lane).

COMPLIANCE: every number is tagged source=ncsbe_voter + needs_dnc_scrub=True and is NEVER
call-ready until scrubbed against the National DNC Registry (re-scrub >=31 days), dialed
8am-9pm local, and screened for TCPA wireless rules. This is enrichment only; the outreach
stack gates any dialing. Footprint county files cached under data/ncvoter/.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent.parent / "data" / "ncvoter"
_INDEX: dict | None = None
_DIRECTIONAL = {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "NORTH", "SOUTH", "EAST", "WEST"}


def _street_key(addr: str | None):
    """('16 CRIS LN') -> ('16', 'CRIS') — house number + first real street token (6 chars)."""
    if not addr:
        return None
    s = re.sub(r"\s+", " ", addr.upper().strip())
    m = re.match(r"(\d+)\s+(.+)", s)
    if not m:
        return None
    toks = [t for t in re.split(r"[\s.,]+", m.group(2)) if t and t not in _DIRECTIONAL]
    if not toks:
        return None
    return (m.group(1), toks[0][:6])


def _build_index() -> dict:
    idx: dict = {}
    for f in sorted(_DATA.glob("ncvoter*.txt")):
        try:
            fh = open(f, encoding="latin-1")
            r = csv.reader(fh, delimiter="\t")
            next(r)  # header
            for row in r:
                if len(row) < 24 or row[8].strip() != "A":   # active voters only
                    continue
                phone = re.sub(r"\D", "", row[23] or "")
                if len(phone) != 10:
                    continue
                last, first = row[4].strip().upper(), row[5].strip().upper()
                sk = _street_key(row[12])
                if last and first and sk:
                    idx.setdefault((last, first, sk[0], sk[1]), phone)
        except Exception:  # noqa: BLE001
            continue
    return idx


def _name_candidates(owner: str):
    """Yield (last, first) candidates from a free-form owner_name (handles deed 'LAST FIRST'
    and 'First Last' and 'LAST, FIRST')."""
    o = re.sub(r"[^A-Za-z, ]", " ", owner or "").upper()
    o = re.sub(r"\s+", " ", o).strip()
    if not o:
        return
    if "," in o:
        a, b = o.split(",", 1)
        b = b.strip().split(" ")
        if a.strip() and b and b[0]:
            yield (a.strip(), b[0])
        return
    toks = o.split(" ")
    if len(toks) >= 2:
        yield (toks[0], toks[1])     # LAST FIRST (deed/grantor style)
        yield (toks[-1], toks[0])    # FIRST [MIDDLE] LAST


def enrich_voter_phone(listings) -> dict:
    global _INDEX
    if _INDEX is None:
        _INDEX = _build_index()
    stats = {"index_size": len(_INDEX), "nc_targets": 0, "matched": 0}
    for li in listings:
        if li.state != "NC" or not li.owner_name or not li.street_address:
            continue
        sk = _street_key(li.street_address)
        if not sk:
            continue
        stats["nc_targets"] += 1
        for last, first in _name_candidates(li.owner_name):
            ph = _INDEX.get((last, first, sk[0], sk[1]))
            if ph:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["owner_phone"] = {
                    "phone": f"({ph[0:3]}) {ph[3:6]}-{ph[6:]}",
                    "source": "ncsbe_voter", "line_type": "unknown",
                    "needs_dnc_scrub": True, "match": "name+address",
                }
                stats["matched"] += 1
                break
    return stats
