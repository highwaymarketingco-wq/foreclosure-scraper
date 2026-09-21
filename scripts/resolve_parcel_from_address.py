#!/usr/bin/env python3
"""Resolve a parcel_id for leads that have a street address and no parcel, from the local parcel caches.

WHY. 47,720 board leads carry a street address and no parcel_id (about 31,000 are `liensnc` NC rows, plus
Charleston SC, Onslow, Brunswick and others). Without a parcel the parcel-cache join
(scripts/join_parcel_cache_to_board.py) cannot fill value, sqft, acreage, mailing or owner. The county
caches under data/parcel_cache/ hold each parcel's situs address, so a house number plus the street name
can name the parcel, offline.

THE RULE (precision over recall: a wrong parcel is a wrong owner, a wrong mailing address and a wrong value):
  * the lead's own county and state pick the cache (dual-state names use the state-qualified file);
    a lead with no county, an overage claim, or a parcel_id already set is never touched;
  * the lead's street must be ONE numbered address (no range "831-833", no road-only, no sentinel "0 X");
  * the cache side is every parcel whose situs has the same house number (leading zeros ignored, a letter
    suffix must match) AND the same street NAME in full (every word, after USPS suffix/ordinal spelling
    normalisation), plus the same suffix when BOTH sides state one and the same direction ("N MAIN ST" is not
    "MAIN ST"; only a county-wide quadrant such as "SW" may go unstated) and the same town when both state one.
    One shared word is not enough (the older Burke rule): "OAK HILL RD" is not "OAK RD";
  * a unit or apartment address resolves only when exactly one parcel carries that unit, or when every
    candidate is unit-less and there is exactly one; a lead WITHOUT a unit never resolves to a unit parcel;
  * the parcel must be UNIQUE. Each parcel sits in the cache under 2 to 3 id spellings (same owner, situs,
    mailing, values), so candidates are grouped by their attributes; two different groups at one address
    is ambiguous and nothing is written. Two groups that share a specific id are one parcel;
  * an id is written only if it is SPECIFIC: every cache row carrying that id belongs to the matched group.
    Placeholder ids (Cumberland "37051" sits on 6,886 rows, Spartanburg "41") are refused. This is the
    poisoned-id guard the first version of this script had;
  * when the parcel's owner mailing starts with its own street, its ZIP is the property's ZIP; a lead ZIP
    that disagrees rejects the match (same street number in a neighbouring town);
  * never lat/lng, never a fuzzy street, never the owner name as a matching key.

The written id is the spelling this county's other board leads already use for that parcel when one is
on the board (so a lien and a tax-roll lead on the same parcel group together), else the cache spelling
whose length is the most common in the county's board ids. Provenance goes in raw['parcel_from_address']
(source, matched situs, cache owner, owner_agrees True/False/None). For liensnc the lead's owner is the owner
of the property being built on and the cache owner may be a new owner or the builder, so owner agreement is
recorded, not required.

    python scripts/resolve_parcel_from_address.py                     # dry run over the live board (ONE streaming pass)
    python scripts/resolve_parcel_from_address.py --rows-file X.jsonl # dry run over a saved board-format extract
    python scripts/resolve_parcel_from_address.py --apply             # ONLY board process (about 3 GB)

Or as a step of the single-load driver: python scripts/apply_board_fixes.py --steps parcel,address,join --apply
See docs/parcel_from_address_2026-09-21.md.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dq_common import county_in_state, iter_rows, lt_str, norm_county  # noqa: E402

REQUIRED_RAW_KEYS = ["parcel_from_address"]
BACKUP_NAME = "resolve_parcel_from_address"     # fill-only: nothing is replaced, so no '_backup' is ever returned
RAW_KEY = "parcel_from_address"
SOURCE_TAG = "parcel_cache_situs_address"

#: Sources whose street_address is measured NOT to be the parcel's situs, so an address match would hand the lead
#: the wrong parcel. Measured 2026-09-21 as the share of a source's parcel-bearing rows whose own parcel sits at the
#: row's street (same house number and street name), pop >= 50, docs/parcel_from_address_2026-09-21.md section 5.4.
#: Not on the list on purpose: liensnc (29%, because ITS existing parcels are often a neighbour's, picked without the
#: address; section 5.5 of the doc) and Transylvania (the cache holds lot text, not a numbered street).
DENY_SOURCES = frozenset({
    "nc_county_pdf_delinquent_tax",   # 7%: the street is the taxpayer's mailing address
    "nc_ptscloud_delinquent_tax",     # 44%: taxpayer mailing address
    "buncombe_unpaid_bills",          # 23%: bill mailing address
    "hud_reac_inspection",            # 31%: apartment-complex addresses, a building of many parcels
    "landwatch",                      # 50%: land-listing address is approximate
    "landandfarm",                    # 59%: land-listing address is approximate
    "asheville_str_permits",          # 59%: permit address, parcel from a neighbouring lot
    "asheville_helene",               # 49%
    "lincoln_vacant", "gaston_vacant",  # 30% / 62%: vacant-lot list carries the owner's other address
    "sc_rod_acclaim",                 # 62%: register-of-deeds party addresses
    "nc_ecourts_lis_pendens", "sc_flc", "shapiro_ingle_powerbi",   # 39% / 39% / 64%
})

#: the parcel cache's columns, in table order (an id shared by more rows than its own group holds is a placeholder:
#: see CountyIndex.specific)
_COLS = ("id", "owner", "address", "owner_mailing", "market_value", "tax_value", "acreage", "living_sqft",
         "land_use", "sale_price", "sale_date")


# ================================================================================== street parsing
_SUFFIX_TABLE = """
ALY ALLEY ALLEE ALLY | AVE AVENUE AV AVEN AVENU AVN AVNUE | BND BEND | BLF BLUFF | BLVD BOULEVARD BOULV BOUL BV |
BR BRANCH | BRG BRIDGE | BRK BROOK | BYP BYPASS BYPA | CSWY CAUSEWAY | CTR CENTER CENTRE CNTR | CIR CIRCLE CIRCL CIRC CR |
CLB CLUB | CMN COMMON | COR CORNER | CRSE COURSE | CT COURT CRT | CV COVE | CRK CREEK | CRES CRESCENT |
XING CROSSING | XRD CROSSROAD | CURV CURVE | DR DRIVE DRIV DRV | EXT EXTENSION EXTN | FLS FALLS | FRY FERRY |
FLD FIELD | FLT FLATS | FRD FORD | FRST FOREST | FRK FORK | FT FORT | FWY FREEWAY | GDN GARDEN | GTWY GATEWAY |
GLN GLEN | GRN GREEN | GRV GROVE | HBR HARBOR | HVN HAVEN | HTS HEIGHTS | HWY HIGHWAY HIGHWY HIWAY | HL HILL |
HOLW HOLLOW | IS ISLAND | JCT JUNCTION | KY KEY | KNL KNOLL | LK LAKE | LNDG LANDING | LN LANE | LOOP LP |
MNR MANOR | MDW MEADOW MEADOWS MDWS | ML MILL | MT MOUNT | MTN MOUNTAIN | ORCH ORCHARD | PARK | PKWY PARKWAY PKY PY |
PASS | PATH | PIKE | PNE PINE | PL PLACE | PLN PLAIN | PLZ PLAZA | PT POINT | PRT PORT | PR PRAIRIE |
RNCH RANCH | RPDS RAPIDS | RST REST | RDG RIDGE | RIV RIVER | RD ROAD | RTE ROUTE | ROW | RUN | SHL SHOAL |
SHR SHORE | SKWY SKYWAY | SPG SPRING | SQ SQUARE | STA STATION | STRM STREAM | ST STREET STR STRT | SMT SUMMIT |
TER TERRACE TERR | TRCE TRACE | TRAK TRACK | TRL TRAIL TRAILS TL | TRLR TRAILER | TPKE TURNPIKE | UN UNION |
VLY VALLEY | VIA | VW VIEW | VLG VILLAGE | VIS VISTA | WALK | WAY WY | WL WELL | ACRES
"""
SUFFIX: dict[str, str] = {}
for _grp in _SUFFIX_TABLE.replace("\n", " ").split("|"):
    _w = _grp.split()
    for _v in _w:
        SUFFIX[_v] = _w[0]

DIRS = {"N": "N", "NORTH": "N", "S": "S", "SOUTH": "S", "E": "E", "EAST": "E", "W": "W", "WEST": "W",
        "NE": "NE", "NORTHEAST": "NE", "NW": "NW", "NORTHWEST": "NW", "SE": "SE", "SOUTHEAST": "SE",
        "SW": "SW", "SOUTHWEST": "SW"}
_ORD = {"FIRST": "1ST", "SECOND": "2ND", "THIRD": "3RD", "FOURTH": "4TH", "FIFTH": "5TH", "SIXTH": "6TH",
        "SEVENTH": "7TH", "EIGHTH": "8TH", "NINTH": "9TH", "TENTH": "10TH", "ELEVENTH": "11TH", "TWELFTH": "12TH"}
_UNIT_KW = (r"(?:APT|APARTMENT|UNIT|STE|SUITE|BLDG|BUILDING|LOT|SPC|SPACE|TRLR|TRAILER|RM|ROOM|FL|FLOOR|"
            r"TWNH|TWNHM|TH|TOWNHOME|TOWNHOUSE|DEPT|OFC|OFFICE|BSMT|REAR)")
_UNIT_RE = re.compile(rf"\s(?:{_UNIT_KW}\b#?\s*([A-Z0-9]+)?|#\s*([A-Z0-9]+))")
_TAIL_UNIT_RE = re.compile(rf"^\s*(?:{_UNIT_KW}\b\.?\s*#?\s*([A-Z0-9]+)|#\s*([A-Z0-9]+)|([A-Z]?\d{{1,5}}[A-Z]?)(?=\s+[A-Z]|\s*$))")
_STATE_ZIP_TAIL = re.compile(r"\s+(?:NC|SC)(?:\s+\d{5}(?:\s*\d{4})?)?\s*$")
_RANGE_RE = re.compile(r"^\s*\d+\s*(?:-|&|/|\bAND\b)\s*\d+\s+[A-Z]")


class Street(NamedTuple):
    num: int
    numsuf: str           # "" or one letter ("12C")
    dirs: frozenset       # {"N"}, {"NW"}, ... empty when none stated
    name: tuple           # canonical street-name words
    suffix: str           # canonical USPS suffix or ""
    unit: str             # normalised unit value or ""
    trail: tuple = ()     # city words that follow the suffix ("1101 PARTRIDGE RD SPARTANBURG"); never part of the name
    body: tuple = ()      # the raw words after the number and any leading direction, for a city-aware re-split
    pre: frozenset = frozenset()


def _canon_word(w: str, first: bool, multi: bool) -> str:
    if first and multi and w == "ST":
        return "SAINT"
    return _ORD.get(w) or SUFFIX.get(w) or w


def parse_street(text) -> tuple:
    """(Street, '') for one numbered street line, else (None, reason). reason is one of
    empty / no_number / sentinel / range / no_street_name."""
    s = str(text or "").upper().replace(" ", " ")
    if not s.strip():
        return None, "empty"
    if _RANGE_RE.match(s):
        return None, "range"
    s = re.sub(r"\s+\d*\.\d+\s*$", "", s)                    # "12C TOXAWAY FALLS DR .86": the county appends the acreage
    s = re.sub(r"(?<=\d)-(?=[A-Z](?:\s|$))", "", s)          # "12-B MAIN ST" -> "12B MAIN ST"
    s = re.sub(r"[.'`]", "", s)
    s = s.replace("-", " ").replace("/", " / ")
    main, _, tail = s.partition(",")
    main = " " + re.sub(r"\s+", " ", main).strip()
    main = _STATE_ZIP_TAIL.sub("", main)
    unit = ""
    m = _UNIT_RE.search(main)
    if m:
        unit = (m.group(1) or m.group(2) or main[m.start():].split()[0]).strip("#")
        main = main[:m.start()]
    elif tail:
        t = _TAIL_UNIT_RE.match(re.sub(r"\s+", " ", tail).upper())
        if t:
            unit = (t.group(1) or t.group(2) or t.group(3) or "").strip("#")
    toks = main.split()
    if not toks:
        return None, "empty"
    m = re.match(r"^(\d+)([A-Z]?)$", toks[0])
    if not m:
        return None, "no_number"
    digits, numsuf = m.group(1), m.group(2)
    n = int(digits)
    if n == 0 or (set(digits) == {"9"} and len(digits) >= 4) or len(digits) > 7:
        return None, "sentinel"
    rest = toks[1:]
    if rest and rest[0] == "/" or (len(rest) > 1 and rest[1] == "/"):        # "123 1/2 MAIN ST"
        return None, "range"
    if not any(re.search(r"[A-Z]", t) for t in rest):
        return None, "no_street_name"
    pre: set = set()
    if len(rest) >= 2 and rest[0] in DIRS and not (len(rest) == 2 and rest[1] in SUFFIX):
        pre.add(DIRS[rest[0]])
        rest = rest[1:]
    rest = [w for w in rest if w != "/"]
    name, suffix, trail, post = _split_body(tuple(rest))
    if not name:
        return None, "no_street_name"
    return Street(n, numsuf, frozenset(pre | post), name, suffix, unit, trail, tuple(rest), frozenset(pre)), ""


def _split_body(body: tuple, city: tuple = ()) -> tuple:
    """(name, suffix, trail, post-direction set) for the words after the house number and any leading direction.
    The suffix is the LAST suffix word that still leaves a street name before it. Only alphabetic words may follow
    it (a city: "PARTRIDGE RD SPARTANBURG"); with a known `city` the body must end with it and only a direction may
    sit between suffix and city. "NC HWY 74" keeps HWY and 74 in the name: a route number after a road word is
    part of the road, never a city."""
    rest = list(body)
    trail: tuple = ()
    if city and len(rest) > len(city) and tuple(rest[-len(city):]) == city:
        rest, trail = rest[:-len(city)], city
    suffix, post = "", set()
    for i in range(len(rest) - 1, 0, -1):
        if rest[i] in SUFFIX:
            after = rest[i + 1:]
            if trail:
                ok = not after or (len(after) == 1 and after[0] in DIRS)
            else:
                ok = len(after) <= 4 and all(w.isalpha() for w in after)
            if ok:
                suffix, tail, rest = SUFFIX[rest[i]], tuple(after), rest[:i]
                if tail and tail[0] in DIRS:
                    post.add(DIRS[tail[0]])
                    tail = tail[1:]
                if not trail:
                    trail = tail
            break
    trail = tuple(w for w in trail if w not in ("NC", "SC"))
    name = tuple(_canon_word(w, i == 0, len(rest) > 1) for i, w in enumerate(rest))
    return name, suffix, trail, post


#: a compound direction some counties append to EVERY address (Brunswick's 911 quadrants); the lead may omit it
_QUADRANTS = frozenset({"NE", "NW", "SE", "SW"})
#: cache "cities" that carry no town information
_NO_TOWN = {"UNINC", "UNINCORPORATED", "UNKNOWN", "COUNTY"}


def street_agrees(lead: Street, cache: Street, lead_city: tuple = (), city_rule: str = "conflict") -> bool:
    """The full-name rule. Same number and letter; the street name and suffix words equal in order, except that
    ONE side may omit its suffix ("3270 BEAVER CREEK" is "3270 BEAVER CREEK DR"; two DIFFERENT suffixes never agree);
    the same direction on both sides, except a quadrant (NE NW SE SW) the cache states and the lead does not.
    When the cache situs carries a town and the lead names its own
    city, the two must agree (city_rule 'conflict'; 'off' ignores towns). A cache situs that ends in the town
    INSTEAD of a suffix ("70 FOX WOOD SANFORD") agrees only when the extra trailing words are the lead's city."""
    if lead.num != cache.num or lead.numsuf != cache.numsuf:
        return False
    name, suffix, trail, post = cache.name, cache.suffix, cache.trail, cache.dirs - cache.pre
    body = cache.body
    if lead_city and len(body) > len(lead_city) and _norm_city(body[-len(lead_city):]) == lead_city:
        name, suffix, trail, post = _split_body(body, tuple(body[-len(lead_city):]))   # the city is known: split on it
    dirs = cache.pre | post
    L = lead.name + ((lead.suffix,) if lead.suffix else ())
    C = name + ((suffix,) if suffix else ())
    if L != C:
        n = len(lead.name)
        if suffix and C[:-1] == L:                    # the lead omitted its suffix (or its "suffix" ends the name)
            pass
        elif lead.suffix and L[:-1] == C:             # the cache omitted its suffix
            pass
        elif lead_city and not suffix and name[:n] == lead.name and _norm_city(name[n:]) == lead_city:
            pass
        else:
            return False
    if lead.dirs != dirs and not (not lead.dirs and dirs <= _QUADRANTS):
        return False                    # N MAIN ST is not MAIN ST; only a county-wide quadrant ("... WAY SW") may go unstated
    if city_rule == "conflict" and trail and lead_city and not (set(trail) & _NO_TOWN) and _norm_city(trail) != lead_city:
        return False
    return True


_CITY_OK = re.compile(r"[A-Za-z][A-Za-z .'\-]{1,38}")
_CITY_ALIAS = {"FT": "FORT", "MT": "MOUNT", "MTN": "MOUNTAIN", "ST": "SAINT"}


def _norm_city(words) -> tuple:
    """City words with the common abbreviations spelled out ("FT MILL" is "FORT MILL"), state codes dropped."""
    return tuple(_CITY_ALIAS.get(w, w) for w in words if w not in ("NC", "SC"))


def _city_words(city) -> tuple:
    """The lead's city as comparable words, or () when the column is not a city name (an address, a plat note, a
    number). () means the town is not judged."""
    c = str(city or "").strip()
    if not _CITY_OK.fullmatch(c):
        return ()
    return _norm_city(re.sub(r"[.'`]", "", c.upper()).replace("-", " ").split())


_ORD_VALUES = frozenset(_ORD.values())


def anchor_word(st: Street) -> str:
    """The longest plain alphabetic name word of the street, used only to narrow the SQL scan: any cache
    situs that agrees on the full name contains it verbatim. Words that the canonicaliser can respell
    (HIGHWAY/HWY, MOUNTAIN/MTN, FIRST/1ST, SAINT/ST) are never anchors."""
    best = ""
    for w in st.name:
        if w.isalpha() and len(w) >= 3 and w not in SUFFIX and w not in _ORD_VALUES and w != "SAINT" and len(w) > len(best):
            best = w
    return best


# ================================================================================== cache index
class Group:
    """One parcel of one county cache: every cache row sharing owner, situs, mailing and values."""
    __slots__ = ("owner", "address", "mailing", "cols", "ids", "streets")

    def __init__(self, row):
        self.owner, self.address, self.mailing = row[1], row[2], row[3]
        self.cols = row[1:]
        self.ids: Counter = Counter()
        self.streets: list = []


class Res(NamedTuple):
    status: str            # unique | ambiguous | no_match | unit_rejected | zip_conflict | no_specific_id
    group: object = None   # Group (unique only)
    ids: tuple = ()        # specific ids of the parcel (unique only)
    detail: str = ""


def _count_sql_ids(con) -> Callable:
    memo: dict = {}

    def n(i):
        if i not in memo:
            memo[i] = con.execute("SELECT COUNT(*) FROM parcels WHERE id=?", (i,)).fetchone()[0]
        return memo[i]
    return n


_NUM_SQL = "CAST(substr(ltrim(address),1,instr(ltrim(address)||' ',' ')-1) AS INTEGER)"
_NORM_SQL = "replace(replace(upper(address),'''',''),'-',' ')"


class CountyIndex:
    """The cache rows of one county whose situs could match a set of leads, grouped into parcels.
    Built with ONE scan of the cache (SQLite prefilters on house number and one street word)."""

    def __init__(self, county, state, con, groups_by_num, city_rule="conflict"):
        self.county, self.state, self._con = county, state, con
        self.city_rule = city_rule
        self.by_num: dict = groups_by_num
        self._id_count = _count_sql_ids(con)
        self._memo: dict = {}

    @classmethod
    def build(cls, county: str, state: str, keys: Iterable[tuple]) -> "CountyIndex | None":
        """keys: (house number, anchor word or ''). None when the county has no readable cache."""
        from foreclosure_scraper import parcel_cache as pc
        try:
            p = pc._db_path(county, state)
        except ValueError:
            return None
        if not p.exists():
            return None
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            con.execute("CREATE TEMP TABLE need(n INTEGER, w TEXT)")
            con.executemany("INSERT INTO need VALUES(?,?)", sorted(set(keys)))
            con.execute("CREATE INDEX need_n ON need(n)")
            cur = con.execute(
                f"SELECT {','.join(_COLS)} FROM parcels WHERE address IS NOT NULL AND EXISTS "
                f"(SELECT 1 FROM need WHERE need.n = {_NUM_SQL} AND (need.w = '' OR instr({_NORM_SQL}, need.w) > 0))")
            groups: dict = {}
            for row in cur:
                g = groups.get(row[1:])
                if g is None:
                    g = groups[row[1:]] = Group(row)
                    for part in str(row[2]).split(";"):
                        st, _why = parse_street(part)
                        if st:
                            g.streets.append(st)
                g.ids[row[0]] += 1
        except sqlite3.Error:
            con.close()
            return None                       # stale-schema or unreadable cache: the weekly refresh rebuilds it
        by_num: dict = defaultdict(list)
        for g in groups.values():
            for k in {(s.num, s.numsuf) for s in g.streets}:
                by_num[k].append(g)
        return cls(county, state, con, by_num)

    def close(self):
        try:
            self._con.close()
        except Exception:  # noqa: BLE001
            pass

    def specific(self, groups) -> list:
        """Ids of the union of `groups` that no other row of the cache carries."""
        held: Counter = Counter()
        for g in groups:
            held.update(g.ids)
        return sorted(i for i, k in held.items() if self._id_count(i) == k)

    def resolve(self, lead: Street, *, city="", zip_code="") -> Res:
        # a lead street that ends in its own town ("141 E MAIN ST PACOLET") stands in for a blank city column
        key = (lead, _city_words(city) or _norm_city(lead.trail), str(zip_code or "")[:5])
        r = self._memo.get(key)
        if r is None:
            r = self._memo[key] = self._resolve(lead, key[1], key[2])
        return r

    def _resolve(self, lead: Street, city_w: tuple, zip5: str) -> Res:
        pool = self.by_num.get((lead.num, lead.numsuf), ())
        if not pool:
            return Res("no_match", detail="no_house_number")
        cands = []
        for g in pool:
            for s in g.streets:
                if street_agrees(lead, s, city_w, self.city_rule):
                    cands.append((g, s))
                    break
        if not cands:
            return Res("no_match", detail="street_differs")
        if lead.unit:
            same = [c for c in cands if c[1].unit == lead.unit]
            if same:
                cands = same
            elif any(c[1].unit for c in cands):
                return Res("unit_rejected", detail="unit_not_in_cache")
        else:
            plain = [c for c in cands if not c[1].unit]
            if not plain:
                return Res("unit_rejected", detail="cache_has_units_only")
            cands = plain
        groups = list({id(g): g for g, _s in cands}.values())
        ids = self.specific(groups)
        if len(groups) > 1:
            shared = set.intersection(*[set(g.ids) for g in groups]) & set(ids)
            if not shared:
                return Res("ambiguous", detail=f"{len(groups)}_parcels")
            ids = sorted(shared)
        if not ids:
            return Res("no_specific_id", detail="placeholder_or_shared_id")
        g = groups[0]
        if zip5 and _mailing_zip_conflicts(g, zip5, self.state):
            return Res("zip_conflict", g, tuple(ids))
        return Res("unique", g, tuple(ids))


def _mailing_zip_conflicts(g: Group, lead_zip5: str, state: str) -> bool:
    """When the owner mails to the property (the mailing begins with the situs) its ZIP is the property's ZIP."""
    from fill_address_from_parcel import city_zip_from_mailing
    z = city_zip_from_mailing(re.sub(r"\s+", " ", str(g.address or "").split(";")[0]).strip(), g.mailing, state)[1]
    return bool(z and z[:5] != lead_zip5)


# ================================================================================== leads
class Lead(NamedTuple):
    ref: int
    source: str
    listing_type: str
    state: str
    county: str
    parcel_id: str
    street: str
    city: str
    zip_code: str
    owner: str
    market_value: object
    tax_value: object
    living_sqft: object
    acreage: object
    has_mailing: bool
    addr_from_cache: bool     # the street itself came from a parcel cache or GIS layer (not independent evidence)
    pid_derived: bool         # the parcel id came from coordinates, a name search, a promotion or this resolver (not source-native)


def _has_mailing(raw: dict) -> bool:
    om = raw.get("owner_mailing")
    if isinstance(om, dict) and om.get("mailing"):
        return True
    if isinstance(om, str) and om.strip():
        return True
    g = raw.get("gis")
    return bool(isinstance(g, dict) and g.get("mailing"))


def _lead(ref, source, lt, state, county, pid, street, city, zip_code, owner, mv, tv, sqft, ac, raw) -> Lead:
    raw = raw if isinstance(raw, dict) else {}
    sas = raw.get("situs_address_source")
    return Lead(ref, str(source or ""), lt, str(state or "").upper(), norm_county(county),
                str(pid or "").strip(), str(street or "").strip(), str(city or "").strip(),
                str(zip_code or "").strip(), str(owner or "").strip(), mv, tv, sqft, ac, _has_mailing(raw),
                bool(sas), bool(raw.get("parcel_from_geo") or raw.get("resolved_from_name") or raw.get(RAW_KEY)))


def lead_from_dict(ref: int, d: dict) -> Lead:
    return _lead(ref, d.get("source"), lt_str(d.get("listing_type")), d.get("state"), d.get("county"),
                 d.get("parcel_id"), d.get("street_address"), d.get("city"), d.get("zip_code"), d.get("owner_name"),
                 d.get("market_value"), d.get("tax_value"), d.get("living_sqft"), d.get("acreage"), d.get("raw"))


def lead_from_listing(ref: int, li) -> Lead:
    return _lead(ref, li.source, lt_str(li.listing_type), li.state, li.county, li.parcel_id, li.street_address,
                 li.city, li.zip_code, li.owner_name, li.market_value, li.tax_value, li.living_sqft, li.acreage,
                 li.raw)


def eligibility(ld: Lead) -> str:
    """'' when the lead is in the population, else the skip reason."""
    if ld.parcel_id:
        return "skip_has_parcel"
    if not ld.street:
        return "skip_no_address"
    if ld.listing_type == "tax_sale_overage":
        return "skip_tax_sale_overage"       # the cache owner is not the claimant
    if ld.source.split(".")[-1] in DENY_SOURCES:
        return "skip_source_street_is_not_situs"
    if not ld.county:
        return "skip_no_county"
    if not county_in_state(ld.county, ld.state):
        return "skip_county_not_in_state"
    return ""


class Corpus:
    """What one pass over the board must keep: the targets, a hold-out sample, the county id-spellings on the
    board, and the state totals the coverage-lift estimate needs. Constant memory apart from those."""

    def __init__(self, keep_holdout: bool = True):
        self.keep_holdout = keep_holdout
        self.targets: list[Lead] = []
        self.holdout: list[Lead] = []
        self.skips: Counter = Counter()
        self.id_hist: dict = defaultdict(Counter)          # (state, county) -> {normalised id length: rows}
        self.board_pids: dict = defaultdict(set)           # (state, county) -> raw parcel_id strings
        self.state_rows: Counter = Counter()
        self.state_have: dict = defaultdict(Counter)       # state -> {field: rows that have it}
        self.n = 0

    def add(self, ld: Lead) -> None:
        from foreclosure_scraper import parcel_cache as pc
        self.n += 1
        self.state_rows[ld.state] += 1
        h = self.state_have[ld.state]
        h["mailing"] += ld.has_mailing
        h["owner"] += bool(ld.owner)
        h["market_value"] += bool(ld.market_value)
        h["tax_value"] += bool(ld.tax_value)
        h["living_sqft"] += bool(ld.living_sqft)
        h["acreage"] += bool(ld.acreage)
        h["parcel"] += bool(ld.parcel_id)
        if ld.parcel_id and ld.county:
            k = (ld.state, ld.county)
            self.id_hist[k][len(pc._norm_id(ld.parcel_id))] += 1
            self.board_pids[k].add(ld.parcel_id)
        why = eligibility(ld)
        if not why:
            self.targets.append(ld)
        else:
            self.skips[why] += 1
        # hold-out: parcel AND an independent street, county in state, cache-backed later
        if (self.keep_holdout and ld.parcel_id and ld.street and ld.county and ld.listing_type != "tax_sale_overage"
                and not ld.addr_from_cache and not ld.pid_derived and county_in_state(ld.county, ld.state)):
            self.holdout.append(ld)


def collect_dicts(rows: Iterable[dict], keep_holdout: bool = True) -> Corpus:
    c = Corpus(keep_holdout)
    for i, d in enumerate(rows):
        c.add(lead_from_dict(i, d))
    return c


def collect_listings(rows) -> Corpus:
    c = Corpus(keep_holdout=False)
    for i, li in enumerate(rows):
        c.add(lead_from_listing(i, li))
    return c


# ================================================================================== id choice
def board_id_map(county_pids: Iterable[str]) -> dict:
    """normalised lookup spelling -> the raw board parcel_id string, exact spellings winning over tolerant ones."""
    from foreclosure_scraper import parcel_cache as pc
    out: dict = {}
    for tier_pass in ("exact", "tolerant"):
        for raw in county_pids:
            for k, tier in pc._lookup_candidates(raw):
                if (tier == "exact") == (tier_pass == "exact"):
                    out.setdefault(k, raw)
    return out


def choose_id(ids: Iterable[str], board_map: dict, hist: Counter) -> tuple:
    """(parcel_id, basis). The board's own spelling for this parcel if any lead already carries it, else the
    cache spelling whose length is the most common among this county's board ids (digits first, then shorter)."""
    ids = list(ids)
    for i in ids:
        if i in board_map:
            return board_map[i], "board_existing"
    best = max(ids, key=lambda i: (hist.get(len(i), 0), i.isdigit(), -len(i), i))
    return (best.upper() if any(c.isalpha() for c in best) else best), "cache_form"


def owner_verdict(lead_owner: str, cache_owner) -> "bool | None":
    from promote_ptscloud_block import is_placeholder_owner, owners_agree
    if not lead_owner or not cache_owner or is_placeholder_owner(lead_owner) or is_placeholder_owner(cache_owner):
        return None
    return owners_agree(lead_owner, cache_owner)


# ================================================================================== resolution driver
def resolve_targets(corpus: Corpus, *, index_factory=None, log=None) -> list:
    """Returns (results, per_county). results = [(lead, Res, parcel_id or None, basis, owner_agrees)] for every
    target; per_county[(state, county)] is a Counter of statuses."""
    build = index_factory or CountyIndex.build
    by_county: dict = defaultdict(list)
    for ld in corpus.targets:
        by_county[(ld.state, ld.county)].append(ld)
    results: list = []
    per: dict = defaultdict(Counter)
    for (state, county), leads in sorted(by_county.items(), key=lambda kv: -len(kv[1])):
        c = per[(state, county)]
        c["leads"] = len(leads)
        parsed = [(ld, *parse_street(ld.street)) for ld in leads]
        exists = True if index_factory else _cache_exists(county, state)
        if not exists:
            for ld, _st, _why in parsed:
                c["no_cache"] += 1
                results.append((ld, Res("no_cache"), None, "", None))
            continue
        keys = {(st.num, anchor_word(st)) for _ld, st, _w in parsed if st}
        idx = build(county, state, keys) if keys else None
        if keys and idx is None:                        # the file exists but cannot be read (stale schema)
            for ld, st, why in parsed:
                res = Res("cache_unreadable") if st else Res("rejected_street", detail=why)
                c[res.status] += 1
                results.append((ld, res, None, "", None))
            continue
        c["cache"] = len(leads)
        bmap = board_id_map(corpus.board_pids.get((state, county), ()))
        hist = corpus.id_hist.get((state, county), Counter())
        try:
            for ld, st, why in parsed:
                if st is None:
                    res = Res("rejected_street", detail=why)
                    c["rejected_street"] += 1
                    results.append((ld, res, None, "", None))
                    continue
                res = idx.resolve(st, city=ld.city, zip_code=ld.zip_code)
                c[res.status] += 1
                pid = basis = None
                agrees = None
                if res.status == "unique":
                    pid, basis = choose_id(res.ids, bmap, hist)
                    agrees = owner_verdict(ld.owner, res.group.owner)
                results.append((ld, res, pid, basis or "", agrees))
        finally:
            if idx:
                idx.close()
        if log:
            log(f"  {state} {county}: {dict(c)}")
    return results, per


def situs_share(county, state) -> "float | None":
    """Fraction of the county cache's parcels whose situs starts with a house number (None: no cache). A cache with
    no situs (Guilford, Cabarrus, Orange, Franklin, Hoke, Oconee) cannot resolve anything however good the rule."""
    from foreclosure_scraper import parcel_cache as pc
    try:
        p = pc._db_path(county, state)
    except ValueError:
        return None
    if not p.exists():
        return None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        n, k = con.execute("SELECT COUNT(*), SUM(address GLOB '[0-9]*') FROM parcels").fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return (k or 0) / n if n else None


def _cache_exists(county, state) -> bool:
    from foreclosure_scraper import parcel_cache as pc
    try:
        return pc._db_path(county, state).exists()
    except ValueError:
        return False


# ================================================================================== apply_rows
def _stamp(li, res: Res, pid: str, basis: str, agrees) -> None:
    if not isinstance(li.raw, dict):
        li.raw = {}
    g = res.group
    prev = li.raw.get(RAW_KEY)
    li.parcel_id = pid
    li.raw[RAW_KEY] = {"source": SOURCE_TAG, "verified": "address_exact_unique", "county": norm_county(li.county),
                       "state": li.state, "matched_situs": str(g.address or "")[:120], "cache_owner": g.owner,
                       "owner_agrees": agrees, "id_basis": basis, "cache_ids": list(res.ids)[:4]}
    if isinstance(prev, dict) and prev.get("withdrawn_parcel"):
        # scripts/repair_parcel_from_address.py withdrew a neighbour's parcel from this lead; keep that on the record
        li.raw[RAW_KEY].update({"withdrawn_parcel": prev["withdrawn_parcel"], "withdrawn_reason": prev.get("reason"),
                                "withdrawn_situs": prev.get("withdrawn_situs")})


def apply_rows(rows: list, *, dry_run: bool = False, index_factory=None) -> dict:
    """Fill parcel_id (and raw['parcel_from_address']) on Listing objects that have a street address and no parcel,
    in place. Never changes len(rows), never writes a file, never replaces an existing parcel_id. With
    dry_run=True nothing is mutated and the same counts come back. `index_factory(county, state, keys)` swaps
    in another cache reader (tests)."""
    from _dq_common import assert_raw_keep
    if not dry_run:
        assert_raw_keep(REQUIRED_RAW_KEYS)
    n = len(rows)
    corpus = collect_listings(rows)
    results, _per = resolve_targets(corpus, index_factory=index_factory)
    c: Counter = Counter(corpus.skips)
    for ld, res, pid, basis, agrees in results:
        if res.status != "unique":
            c[res.status] += 1
            continue
        c["resolved"] += 1
        c[f"owner_agrees_{agrees}"] += 1
        if not dry_run:
            _stamp(rows[ld.ref], res, pid, basis, agrees)
    assert len(rows) == n, "a resolver must never change the row count"
    return {k: v for k, v in c.items() if v}


# ================================================================================== hold-out
def name_level_agree(lead_street, truth_address) -> bool:
    """The lead's own parcel sits at the lead's address, judged with the resolver's parser but ignoring the suffix, the
    direction and the town: same house number and same street NAME. It is the truth filter of the hold-out."""
    a, _ = parse_street(lead_street)
    if a is None:
        return False
    for part in str(truth_address or "").split(";"):
        b, _ = parse_street(part)
        if b and b.num == a.num and b.numsuf == a.numsuf and (b.name == a.name or b.name[:len(a.name)] == a.name):
            return True
    return False


def evaluate_holdout(corpus: Corpus, *, index_factory=None, max_per_county: int = 4000, city_rule: str = "conflict",
                     skip_sources: Iterable[str] = DENY_SOURCES) -> dict:
    """Hide the parcel of leads that have both a parcel and a source-independent street, resolve by street, and
    compare with the lead's own parcel.

    THE TRUTH IS ONLY TRUSTED WHEN THE LEAD'S OWN PARCEL SITS AT THE LEAD'S ADDRESS. Measured 2026-09-21: many
    sources' parcel_id does not describe their street_address (a delinquent-tax list prints the owner's mailing
    address, a permit list carries a neighbour's parcel, 60% of the parcel-bearing liensnc rows carry a parcel picked
    from approximate coordinates that sits a few doors away). Scoring the resolver against those would punish it for
    being right. So a hold-out lead counts only when its own parcel's cache situs agrees with its street at the
    LOOSE level of the older Burke rule (same house number and one shared street word), deliberately looser than
    the resolver's own rule so the filter does not favour it. The rest are reported as 'own_parcel_elsewhere'.
    The HEADLINE uses name_level_agree (same number and street name, suffix/direction/town ignored); the Burke
    level is kept as a reference tally in result['loose'].
    per[(state, county)] = Counter(pop, resolved, correct, wrong, ...)."""
    from foreclosure_scraper import parcel_cache as pc
    from repair_burke_storm_damage_parcels import addresses_agree as loose_agree
    build = index_factory or CountyIndex.build
    skip = set(skip_sources)
    seen: set = set()
    by_county: dict = defaultdict(list)
    for ld in corpus.holdout:
        if ld.source.split(".")[-1] in skip:
            continue
        k = (ld.state, ld.county, pc._norm_id(ld.parcel_id), ld.street.upper())
        if k in seen:
            continue
        seen.add(k)
        if len(by_county[(ld.state, ld.county)]) < max_per_county:
            by_county[(ld.state, ld.county)].append(ld)
    per: dict = defaultdict(Counter)
    detail: dict = defaultdict(Counter)       # source class -> counters
    loose: Counter = Counter()                # same tallies under the looser Burke-level truth filter
    wrong_samples: list = []
    for (state, county), leads in sorted(by_county.items(), key=lambda kv: -len(kv[1])):
        if not (True if index_factory else _cache_exists(county, state)):
            continue
        parsed = [(ld, *parse_street(ld.street)) for ld in leads]
        keys = {(st.num, anchor_word(st)) for _l, st, _w in parsed if st}
        idx = build(county, state, keys) if keys else None
        if idx is not None:
            idx.city_rule = city_rule
        c = per[(state, county)]
        try:
            for ld, st, why in parsed:
                truth, tier = pc.lookup_with_tier(county, ld.parcel_id, state)
                if not tier or not truth or not truth.get("address"):
                    c["truth_has_no_situs"] += 1
                    continue
                v_loose = loose_agree(ld.street, truth["address"])
                v_name = name_level_agree(ld.street, truth["address"])
                if v_loose:
                    loose["pop"] += 1
                if not v_name:
                    c["own_parcel_elsewhere"] += 1          # the lead's parcel is not at the lead's address: no truth
                    if v_loose and st is not None and idx is not None:      # loose-only: still tally for the reference line
                        r0 = idx.resolve(st, city=ld.city, zip_code=ld.zip_code)
                        if r0.status == "unique":
                            loose["resolved"] += 1
                            hit0 = {k for k, _t in pc._lookup_candidates(ld.parcel_id)} & set(r0.group.ids)
                            loose["correct" if hit0 else "wrong"] += 1
                    continue
                c["pop"] += 1
                cls = _source_class(ld.source)
                detail[cls]["pop"] += 1
                if st is None or idx is None:
                    c["rejected_street"] += 1
                    continue
                res = idx.resolve(st, city=ld.city, zip_code=ld.zip_code)
                if res.status != "unique":
                    c[res.status] += 1
                    continue
                c["resolved"] += 1
                detail[cls]["resolved"] += 1
                tv = {k for k, _t in pc._lookup_candidates(ld.parcel_id)}
                if v_loose:
                    loose["resolved"] += 1
                if tv & set(res.group.ids):
                    c["correct"] += 1
                    detail[cls]["correct"] += 1
                    if v_loose:
                        loose["correct"] += 1
                else:
                    if v_loose:
                        loose["wrong"] += 1
                    c["wrong"] += 1
                    same_owner = owner_verdict(truth.get("owner"), res.group.owner)
                    same_mail = bool(truth.get("owner_mailing") and truth.get("owner_mailing") == res.group.mailing)
                    c["wrong_same_owner_or_mailing" if (same_owner or same_mail) else "wrong_harmful"] += 1
                    detail[cls]["wrong"] += 1
                    if len(wrong_samples) < 40:
                        wrong_samples.append((state, county, ld.parcel_id, ld.street, res.group.address,
                                              truth.get("address"), ld.source.split(".")[-1]))
        finally:
            if idx:
                idx.close()
    return {"per": per, "by_class": detail, "wrong_samples": wrong_samples, "loose": loose}


def _source_class(src: str) -> str:
    s = str(src or "").split(".")[-1]
    if s == "liensnc":
        return "liensnc"
    if any(t in s for t in ("delinquent", "tax", "qpaybill", "vacant", "elderly", "roll")):
        return "tax_roll_or_county_list"
    return "other"


# ================================================================================== reporting
_LIFT_FIELDS = (("mailing", "has_mailing"), ("owner", "owner"), ("market_value", "market_value"),
                ("living_sqft", "living_sqft"), ("acreage", "acreage"))


def lift(corpus: Corpus, results: list) -> dict:
    """What the existing join would fill on the resolved leads (it is fill-only): per state and per field, the number of
    resolved leads that lack the field and whose parcel row has it. Also split by owner agreement for mailing."""
    add: dict = defaultdict(Counter)
    for ld, res, pid, _basis, agrees in results:
        if res.status != "unique":
            continue
        g = res.group
        a = add[ld.state]
        a["resolved"] += 1
        row = dict(zip(_COLS[1:], g.cols))
        if not ld.has_mailing and row.get("owner_mailing"):
            a["mailing"] += 1
            a[f"mailing_owner_agrees_{agrees}"] += 1
        if not ld.owner and row.get("owner"):
            a["owner"] += 1
        if not ld.market_value and row.get("market_value"):
            a["market_value"] += 1
        if not ld.living_sqft and row.get("living_sqft"):
            a["living_sqft"] += 1
        if not ld.acreage and row.get("acreage"):
            a["acreage"] += 1
        if not ld.tax_value and row.get("tax_value"):
            a["tax_value"] += 1
    return add


def print_report(corpus: Corpus, results: list, per: dict, hold: dict | None, out=print) -> None:
    out(f"board rows scanned: {corpus.n:,}")
    out(f"population: {len(corpus.targets):,} leads with a street address and no parcel "
        f"(skipped: {dict(corpus.skips)})")
    out("\nPER COUNTY (leads = address, no parcel; cache = a cache file exists; unique / ambiguous / nomatch / street = "
        "road-only, legal, range or unit rejected)")
    out(f"{'state':5}{'county':15}{'leads':>7}{'cache':>7}{'unique':>8}{'ambig':>7}{'nomatch':>8}{'street':>7}{'other':>7}{'situs%':>8}")
    tot: Counter = Counter()
    for (st, co), c in sorted(per.items(), key=lambda kv: -kv[1]["leads"]):
        other = c["zip_conflict"] + c["no_specific_id"]
        street = c["rejected_street"] + c["unit_rejected"]
        sh = situs_share(co, st) if c["cache"] else None
        out(f"{st:5}{co[:14]:15}{c['leads']:>7,}{c['cache']:>7,}{c['unique']:>8,}{c['ambiguous']:>7,}"
            f"{c['no_match']:>8,}{street:>7,}{other:>7,}{('%.0f' % (100 * sh)) if sh is not None else '-':>8}"
            + (f"   (no cache: {c['no_cache']:,})" if c["no_cache"] else ""))
        tot.update(c)
    other = tot["zip_conflict"] + tot["no_specific_id"]
    out(f"{'':5}{'TOTAL':15}{tot['leads']:>7,}{tot['cache']:>7,}{tot['unique']:>8,}{tot['ambiguous']:>7,}"
        f"{tot['no_match']:>8,}{tot['rejected_street'] + tot['unit_rejected']:>7,}{other:>7,}   (no cache: {tot['no_cache']:,})")
    out("\nBY SOURCE (largest 14: leads / unique / ambiguous / no match / street or unit rejected / no cache)")
    srcs: dict = defaultdict(Counter)
    for ld, r, _p, _b, _a in results:
        c = srcs[ld.source.split(".")[-1]]
        c["leads"] += 1
        c[r.status] += 1
    for name, c in sorted(srcs.items(), key=lambda kv: -kv[1]["leads"])[:14]:
        out(f"  {name[:32]:33}{c['leads']:>7,}{c['unique']:>8,}{c['ambiguous']:>7,}{c['no_match']:>8,}"
            f"{c['rejected_street'] + c['unit_rejected']:>7,}{c['no_cache']:>8,}")
    basis = Counter(b for _l, r, _p, b, _a in results if r.status == "unique")
    agree = Counter(a for _l, r, _p, _b, a in results if r.status == "unique")
    out(f"\nresolved {tot['unique']:,}; id spelling {dict(basis)}; owner agrees {dict(agree)}")
    if hold is not None:
        _print_holdout(hold, out)
    add = lift(corpus, results)
    out("\nEXPECTED FILLS if join_parcel_cache_to_board runs on the resolved leads (fill-only), by state")
    for st in sorted(add):
        a, rows = add[st], corpus.state_rows[st] or 1
        have = corpus.state_have[st]
        parts = []
        for f in ("mailing", "owner", "market_value", "tax_value", "living_sqft", "acreage"):
            base = have.get({"tax_value": "market_value"}.get(f, f), 0) if f != "tax_value" else None
            if f == "tax_value":
                parts.append(f"tax_value +{a[f]:,}")
                continue
            parts.append(f"{f} +{a[f]:,} ({100 * base / rows:.1f}% -> {100 * (base + a[f]) / rows:.1f}%, "
                         f"+{100 * a[f] / rows:.2f} pp)")
        out(f"  {st} ({rows:,} rows, {a['resolved']:,} resolved): " + "; ".join(parts))
        out(f"      parcel coverage {100 * have['parcel'] / rows:.1f}% -> {100 * (have['parcel'] + a['resolved']) / rows:.1f}%;"
            f" new mailing fills by owner agreement: agrees {a['mailing_owner_agrees_True']:,}, differs "
            f"{a['mailing_owner_agrees_False']:,}, unknown {a['mailing_owner_agrees_None']:,}")


def _print_holdout(hold: dict, out) -> None:
    per = hold["per"]
    out("\nHOLD-OUT (parcel hidden, resolved by street alone; truth = the lead's own parcel; street not from a cache)")
    out(f"{'state':5}{'county':15}{'pop':>7}{'resolved':>9}{'correct':>8}{'wrong':>6}{'harmful':>8}{'prec%':>7}{'recall%':>8}")
    tot: Counter = Counter()
    for (st, co), c in sorted(per.items(), key=lambda kv: -kv[1]["pop"]):
        if c["pop"] < 25:
            tot.update(c)
            continue
        p = 100 * c["correct"] / c["resolved"] if c["resolved"] else 0.0
        r = 100 * c["correct"] / c["pop"] if c["pop"] else 0.0
        out(f"{st:5}{co[:14]:15}{c['pop']:>7,}{c['resolved']:>9,}{c['correct']:>8,}{c['wrong']:>6,}{c['wrong_harmful']:>8,}{p:>7.1f}{r:>8.1f}")
        tot.update(c)
    p = 100 * tot["correct"] / tot["resolved"] if tot["resolved"] else 0.0
    r = 100 * tot["correct"] / tot["pop"] if tot["pop"] else 0.0
    out(f"{'':5}{'ALL (incl. counties under 25)':15}{tot['pop']:>7,}{tot['resolved']:>9,}{tot['correct']:>8,}{tot['wrong']:>6,}"
        f"{tot['wrong_harmful']:>8,}{p:>7.1f}{r:>8.1f}")
    for cls, c in sorted(hold["by_class"].items()):
        pp = 100 * c["correct"] / c["resolved"] if c["resolved"] else 0.0
        rr = 100 * c["correct"] / c["pop"] if c["pop"] else 0.0
        out(f"  {cls:26} pop {c['pop']:>6,} resolved {c['resolved']:>6,} correct {c['correct']:>6,} precision {pp:5.1f}% recall {rr:5.1f}%")
    lo = hold.get("loose") or Counter()
    if lo["resolved"]:
        out(f"  reference, Burke-level truth filter (number + one shared word): pop {lo['pop']:,} resolved {lo['resolved']:,} "
            f"correct {lo['correct']:,} precision {100 * lo['correct'] / lo['resolved']:.2f}% (the extra misses are permit and "
            f"vacant-lot sources whose parcel is a different street)")
    out("  outcomes: " + ", ".join(f"{k} {v:,}" for k, v in tot.most_common() if k not in ('pop',)))
    for s in hold["wrong_samples"][:12]:
        out("  WRONG " + " | ".join(str(x) for x in s))


def _dry_run(rows_file, do_holdout: bool) -> int:
    corpus = collect_dicts(iter_rows(rows_file))
    results, per = resolve_targets(corpus)
    hold = evaluate_holdout(corpus) if do_holdout else None
    print_report(corpus, results, per, hold)
    print("\nDRY RUN, nothing written, no network. Re-run with --apply (as the only board process).")
    return 0


def _apply() -> int:
    from _dq_common import run_apply
    return run_apply("resolve_parcel_from_address", apply_rows, REQUIRED_RAW_KEYS, BACKUP_NAME)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the board (board_lock + load_board + write_artifact)")
    ap.add_argument("--dry-run", action="store_true", help="accepted for the old CLI; a dry run is now the default")
    ap.add_argument("--rows-file", help="dry run over a saved board-format JSONL extract instead of the live board")
    ap.add_argument("--no-holdout", action="store_true", help="skip the hold-out precision measurement")
    args = ap.parse_args()
    if args.apply and not args.dry_run:
        if args.rows_file:
            raise SystemExit("--rows-file is dry-run only")
        return _apply()
    return _dry_run(args.rows_file, not args.no_holdout)


if __name__ == "__main__":
    raise SystemExit(main())
