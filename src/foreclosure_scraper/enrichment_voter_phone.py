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
_NAME_COUNTY: dict | None = None
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


def _build_index():
    """Returns (addr_index, name_county_unique). addr_index keys (last,first,house,street6)->phone.
    name_county_unique keys (COUNTY,last,first)->phone ONLY when exactly one active voter with
    that name+county has a phone (unambiguous = safe to assign to an absentee owner)."""
    idx: dict = {}
    nc_phones: dict = {}   # (county,last,first) -> set(phones)
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
                county = row[1].strip().upper()
                last, first = row[4].strip().upper(), row[5].strip().upper()
                if not (last and first):
                    continue
                sk = _street_key(row[12])
                if sk:
                    idx.setdefault((last, first, sk[0], sk[1]), phone)
                nc_phones.setdefault((county, last, first), set()).add(phone)
        except Exception:  # noqa: BLE001
            continue
    name_county = {k: next(iter(v)) for k, v in nc_phones.items() if len(v) == 1}
    return idx, name_county


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


def _set_phone(li, ph, match):
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["owner_phone"] = {
        "phone": f"({ph[0:3]}) {ph[3:6]}-{ph[6:]}",
        "source": "ncsbe_voter", "line_type": "unknown",
        "needs_dnc_scrub": True, "match": match,
    }


def enrich_voter_phone(listings) -> dict:
    global _INDEX, _NAME_COUNTY
    if _INDEX is None:
        _INDEX, _NAME_COUNTY = _build_index()
    stats = {"index_size": len(_INDEX), "nc_targets": 0, "matched_addr": 0, "matched_namecty": 0}
    for li in listings:
        if li.state != "NC" or not li.owner_name:
            continue
        stats["nc_targets"] += 1
        cands = list(_name_candidates(li.owner_name))
        # 1) high-confidence name + property address (owner-occupants)
        sk = _street_key(li.street_address) if li.street_address else None
        hit = False
        if sk:
            for last, first in cands:
                ph = _INDEX.get((last, first, sk[0], sk[1]))
                if ph:
                    _set_phone(li, ph, "name+address")
                    stats["matched_addr"] += 1
                    hit = True
                    break
        # 2) fallback: name unique within the county (catches absentee owners)
        if not hit and li.county:
            cty = li.county.upper().replace(" COUNTY", "").strip()
            for last, first in cands:
                ph = _NAME_COUNTY.get((cty, last, first))
                if ph:
                    _set_phone(li, ph, "name+county-unique")
                    stats["matched_namecty"] += 1
                    break
    stats["matched"] = stats["matched_addr"] + stats["matched_namecty"]
    return stats
