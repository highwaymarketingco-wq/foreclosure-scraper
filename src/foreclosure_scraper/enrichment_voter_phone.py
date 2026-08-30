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
_FUZZY_INDEX: dict | None = None          # (soundex(last), first3(first)) -> phone
_FUZZY_NAME_INDEX: dict | None = None     # (soundex(last), first3(first)) -> phone (name-unique)
_NAME_COUNTY_FUZZY: dict | None = None    # (county, soundex(last), first3(first)) -> phone (unique in county)
_DIRECTIONAL = {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "NORTH", "SOUTH", "EAST", "WEST"}

# Common nicknames -> canonical first name. Used so "Bob Smith" in the deed
# matches "Robert Smith" in the voter file.
_NICKNAMES = {
    "BOB": "ROBERT", "BOBBY": "ROBERT", "ROB": "ROBERT",
    "BILL": "WILLIAM", "BILLY": "WILLIAM", "WILL": "WILLIAM",
    "JIM": "JAMES", "JIMMY": "JAMES", "JAMIE": "JAMES",
    "TOM": "THOMAS", "TOMMY": "THOMAS",
    "DICK": "RICHARD", "RICK": "RICHARD", "RICKY": "RICHARD",
    "MIKE": "MICHAEL", "MICK": "MICHAEL",
    "DAVE": "DAVID", "DAVEY": "DAVID",
    "CHRIS": "CHRISTOPHER",
    "MATT": "MATTHEW",
    "JOE": "JOSEPH", "JOEY": "JOSEPH",
    "JON": "JONATHAN", "JOHN": "JOHN",
    "PETE": "PETER",
    "STEVE": "STEVEN", "STEPHEN": "STEPHEN",
    "ANDY": "ANDREW", "DREW": "ANDREW",
    "ANTHONY": "ANTHONY", "TONY": "ANTHONY",
    "ED": "EDWARD", "EDDIE": "EDWARD", "TED": "EDWARD",
    "PAT": "PATRICK", "PATSY": "PATRICK",
    "RAY": "RAYMOND",
    "SAM": "SAMUEL", "SAMMY": "SAMUEL",
    "ALEX": "ALEXANDER",
    "BEN": "BENJAMIN",
    "BRAD": "BRADLEY",
    "CHARLIE": "CHARLES", "CHUCK": "CHARLES",
    "FRED": "FREDERICK", "FREDDIE": "FREDERICK",
    "GREG": "GREGORY",
    "HANK": "HENRY",
    "KEN": "KENNETH", "KENNY": "KENNETH",
    "LARRY": "LAWRENCE",
    "LOU": "LOUIS",
    "PHIL": "PHILIP", "PHILLIP": "PHILLIP",
    "RON": "RONALD", "RONNIE": "RONALD",
    "SHELLY": "MICHELLE",
    "SUE": "SUSAN", "SUSIE": "SUSAN",
    "KATE": "KATHERINE", "KATIE": "KATHERINE", "KATHY": "KATHERINE",
    "LIZ": "ELIZABETH", "BETTY": "ELIZABETH", "BETH": "ELIZABETH",
    "MAGGIE": "MARGARET", "PEGGY": "MARGARET",
    "CATHERINE": "CATHERINE", "CATHY": "CATHERINE",
}


def _soundex(s: str) -> str:
    """Standard 4-char Soundex code. Groups similar-sounding consonants so
    'Smith' and 'Smyth' both code to S530."""
    s = re.sub(r"[^A-Z]", "", (s or "").upper())
    if not s:
        return "0000"
    codes = {ord(c): n for c, n in zip("BFPVCGJKQSXZDTLNMR", "1111222222334456")}
    # Keep first letter
    result = s[0]
    prev = codes.get(ord(s[0]), "0")
    for ch in s[1:]:
        code = codes.get(ord(ch), "0")
        if code != "0" and code != prev:
            result += code
        prev = code
    # Pad/truncate to 4 chars
    result = (result + "000")[:4]
    return result


def _canon_first(name: str) -> str:
    """Map nicknames to canonical first name, return uppercased first 3 chars."""
    n = re.sub(r"[^A-Z]", "", (name or "").upper())
    n = _NICKNAMES.get(n, n)
    return n[:3] if n else ""


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
    """Returns (addr_index, name_county_unique, fuzzy_addr, fuzzy_namecty).

    addr_index keys (last,first,house,street6)->phone.
    name_county_unique keys (COUNTY,last,first)->phone ONLY when exactly one active voter with
    that name+county has a phone (unambiguous = safe to assign to an absentee owner).
    fuzzy_addr keys (soundex(last),canon_first,house,street6)->phone (soundex+nickname fuzzy).
    fuzzy_namecty keys (COUNTY,soundex(last),canon_first)->phone (unambiguous within county)."""
    idx: dict = {}
    nc_phones: dict = {}   # (county,last,first) -> set(phones)
    fz_addr: dict = {}     # (soundex(last),canon_first,house,street6) -> set(phones)
    fz_nc: dict = {}      # (county,soundex(last),canon_first) -> set(phones)
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
                # Fuzzy indices: Soundex(last) + canonical first 3 chars
                sx = _soundex(last)
                cf = _canon_first(first)
                if cf and sk:
                    fz_addr.setdefault((sx, cf, sk[0], sk[1]), set()).add(phone)
                fz_nc.setdefault((county, sx, cf), set()).add(phone)
        except Exception:  # noqa: BLE001
            continue
    name_county = {k: next(iter(v)) for k, v in nc_phones.items() if len(v) == 1}
    fz_addr_unique = {k: next(iter(v)) for k, v in fz_addr.items() if len(v) == 1}
    fz_nc_unique = {k: next(iter(v)) for k, v in fz_nc.items() if len(v) == 1}
    return idx, name_county, fz_addr_unique, fz_nc_unique


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
    global _INDEX, _NAME_COUNTY, _FUZZY_INDEX, _NAME_COUNTY_FUZZY
    if _INDEX is None:
        _INDEX, _NAME_COUNTY, _FUZZY_INDEX, _NAME_COUNTY_FUZZY = _build_index()
    stats = {"index_size": len(_INDEX), "nc_targets": 0,
             "matched_addr": 0, "matched_namecty": 0,
             "matched_fuzzy_addr": 0, "matched_fuzzy_namecty": 0}
    for li in listings:
        if li.state != "NC" or not li.owner_name:
            continue
        # Skip if already has a phone from any source
        raw = li.raw if isinstance(li.raw, dict) else {}
        if raw.get("owner_phone"):
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
                    hit = True
                    break
        # 3) FUZZY: Soundex(last) + canonical first name + address
        if not hit and sk:
            for last, first in cands:
                sx = _soundex(last)
                cf = _canon_first(first)
                if not cf:
                    continue
                ph = _FUZZY_INDEX.get((sx, cf, sk[0], sk[1]))
                if ph:
                    _set_phone(li, ph, f"fuzzy:soundex+addr")
                    stats["matched_fuzzy_addr"] += 1
                    hit = True
                    break
        # 4) FUZZY: Soundex(last) + canonical first name unique within county
        if not hit and li.county:
            cty = li.county.upper().replace(" COUNTY", "").strip()
            for last, first in cands:
                sx = _soundex(last)
                cf = _canon_first(first)
                if not cf:
                    continue
                ph = _NAME_COUNTY_FUZZY.get((cty, sx, cf))
                if ph:
                    _set_phone(li, ph, f"fuzzy:soundex+county-unique")
                    stats["matched_fuzzy_namecty"] += 1
                    break
    stats["matched"] = (stats["matched_addr"] + stats["matched_namecty"]
                        + stats["matched_fuzzy_addr"] + stats["matched_fuzzy_namecty"])
    return stats
