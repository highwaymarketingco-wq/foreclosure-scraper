"""Row identity on the finished board: duplicate properties, fused rows, owners the roll contradicts.
Pure, no I/O. docs/audit_2026-10-09/identity.md has the measurements.

Three defects of one family (a row is not exactly one property with its own owner), measured on the
reconciled pre_publish checkpoint of 2026-10-09 (383,378 rows):

DUPLICATES. board_selfcheck's "no duplicate identifiable properties" read 896 (live board 809). It
grouped rows by parcel id (any string) or a street address whose first token holds a digit, and
counted every group of 2-3 distinct addresses as duplicates. Partitioned by property (partition()):
  * 666 keys hold 2+ different properties: one parcel id with 2-3 different REAL house numbers or
    units, each named by its own record (an apartment complex's code cases at two buildings, a
    parcel's two damaged structures, the lots a LiensNC master PIN covers, a mobile-home bill
    beside the land bill). dedupe's identity rule (dedupe.identity_conflict) refuses to merge
    different house numbers on purpose; these are not duplicates (a 4th address already made the
    selfcheck call such a key "fused", an inconsistency);
  * an "address" with digits and no house number ('6th Avenue', an interstate exit) names no
    property; the house number is placeholder_twins.real_house_no's, the street compared with its
    suffix and direction (verification.core.address_key) and its unit;
  * 375 real duplicates are left (Catawba 103, nc_ust_incidents 140, nc_county_pdf 105):
      - SAME NUMBERED ADDRESS, NO PARCEL (185): rows dedupe never compared or scored under 92
        ('<n> E HIGHWAY 56' and '<n> NC HWY 56 EAST': two UST incidents of one store; a SEMS or
        ACRES site beside its UST incident);
      - AGED COPY, SAME PARCEL AND ADDRESS (118): Catawba delinquent-tax rows whose short account
        id validation nulls and whose PIN the name resolver adds only in the tail (after dedupe2),
        so the aged prior copy and the re-scrape carry the same PIN and never met;
      - AGED COPY AT ANOTHER ADDRESS (47): the copy's address is the owner's MAILING address
        (Buncombe elderly and unpaid-bill rows of before the 9/29 source fix) or the county
        re-addressed the parcel (an aged copy of the same source record, same PIN and county id);
        the house-number guard reads two houses;
      - LIVE ROWS, SAME PARCEL AND ADDRESS (25): not traced to one writer (cross-source rows that
        took a parcel after dedupe2, two docket cases at one address).
  collapse_twins() merges exactly these (one property, never two): the live row is the base and
  an aged copy gives it only what placeholder_twins.COPY_ALLOWLIST names; two live rows merge as
  dedupe would have merged them, the base keeping its own source blocks.

FUSED ROWS. A row whose own source record (the block its scraper wrote) names a parcel of the
row's numbering system that is not the row's: the record of one property under another's parcel,
address and owner (pre-10/6 address-key merges; a Buncombe unpaid bill for 0609-68-4200 published
as 0609-68-0073 at its owner's mailing address). fused_record() detects it, unfuse() re-keys the row
to its own record (parcel, situs, owner) and records what it displaced in raw['unfused']; the late
block scrub then drops the blocks that belonged to the displaced parcel. Nothing is deleted.
unfuse() also clears raw['gis_fill']/['county_deed_ref']/['county_legal'] (gis_fill.py's own fill +
screen, SUPERSEDED_PARCEL_FILL_BLOCKS below): gis_fill runs early in main.py's pipeline and keys
its "screened"/deed/legal verdict to li.parcel_id at the time it ran, with no re-check before the
late unfuse() pass re-keys parcel_id out from under it -- left alone, the row would carry the
SUPERSEDED (from_parcel)'s verdict under the new (to_parcel) identity, and gis_fill.needs() would
skip re-screening it as already done (2026-10-18 top80-fill-screen-honest unfuse/repoint gap).

OWNER CONTRADICTED BY THE ROLL. block_binding.row_owner_strength() == 'contradicted': every county
roll block on the row names someone else. 40 sampled rows were checked against a third source (NC
OneMap's parcel layer queried by the row's own parcel id; Spartanburg's CAMA layer):
  * the contradicting block carries no parcel id (raw['gis'] from a point or the parcel cache) or
    is a tax bill's historical taxpayer (qpaybill 'owner' of 2017-2020 bills): the row's owner was
    right every time it could be checked;
  * the contradicting block is the county record looked up BY the row's parcel id (gis_attrs_full
    parno, lrcpwa reid) and the row's owner was never refreshed from a current record: the roll was
    right every time;
  * both are current-state claims (the row's owner carries a refresh stamp): undecided (the stamp
    travels with Listing.merge's raw deep-merge and is not proof the owner value is the refreshed
    one: a HUD facility name carried a parcel-cache stamp).
resolve_owner() applies that rule and stamps raw['owner_conflict'] on every contradicted row.

PARTY-ROLE CONFUSION. A fourth, different defect: the string offered as the owner is not a
person's (or a legitimate owning entity's) name at all -- a lienholder, a government body, a
builder-of-record, or (confirmed on the live board) a literal job title ("Procurement Manager")
read off a lien filing's free-text owner field. 2026-11-19 verification: of 18 live-checked rows
where li.owner_name and raw['skip_trace']['owner_name'] disagreed, 3 had NEITHER right -- not a
staleness problem (the roll-vs-row check above already covers that), a party-role problem no
cheap rule can fully solve. suspicious_owner_name() below is a narrow, high-confidence net for
the shapes that sample actually showed, meant to fail SAFE (flag and fall back) rather than
guess; outreach.py's _owner() is the consumer.
"""
from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict
from typing import Any, Iterable, Optional

from .block_binding import (
    ROLL_MAILING_SOURCES,
    ROLL_OWNER_BLOCKS,
    block_kind,
    keep_fresh_blocks,
    name_tokens,
    names_disagree,
    own_source_block,
    probe,
)
from .rod.sc_chain import name_fit, owner_query
from .tax_binding import canon_id, comparable, county_key, row_ids, same_id
from .verification.core import address_key

# ------------------------------------------------------------------------------------- helpers


def _get(row: Any, name: str):
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _raw(row: Any) -> dict:
    r = _get(row, "raw")
    return r if isinstance(r, dict) else {}


def _pt():
    from . import placeholder_twins
    return placeholder_twins


def _dd():
    from . import dedupe
    return dedupe


def is_aged(row: Any) -> bool:
    return bool(_raw(row).get("pulled_sale"))


#: identifier blocks whose ids are a list of CANDIDATES (an address lookup's matches), not a claim
#: about which parcel the row is
CANDIDATE_ID_BLOCKS = frozenset({"parcel_from_address", "parcel_from_geo", "parcel_resolution"})
#: sources whose own record names a parent/master tract (a lien-agent filing's PIN covers a
#: subdivision's lots): a different id there is not a fused row
PARENT_PIN_SOURCES = ("liensnc",)
#: raw blocks gis_fill.apply_one() writes keyed to li.parcel_id AT THE TIME IT RAN (gis_fill runs
#: early in main.py's pipeline, identity's unfuse() late) -- none of the three carries its own
#: "this is parcel X's screen" guard gis_fill.needs()/deed_ref_on_row()/legal_on_row() checks
#: before skipping a re-screen, so once unfuse() re-keys row.parcel_id to the record's OWN parcel
#: (to_parcel), a block still on the row is the SUPERSEDED (from_parcel)'s verdict/deed/legal
#: wearing the new parcel's name. Cleared below so the next gis_fill run screens the row's real
#: (to_parcel) identity instead of trusting a stale "found"/deed/legal that belongs to the
#: parcel this row no longer is. Same family as enrichment_prior_correction.py's
#: _PARCEL_BLOCKS/_PARCEL_ONLY_BLOCKS (clearing a block tied to an abandoned parcel id), applied
#: here to unfuse()'s own re-key instead of a withdrawn fallback point.
SUPERSEDED_PARCEL_FILL_BLOCKS = ("gis_fill", "county_deed_ref", "county_legal")


def own_blocks(row: Any) -> dict:
    """The blocks the row's OWN scraper wrote (block_binding.own_source_block), minus person blocks
    and, for the shared 'arcgis_distress' container, a layer other than the row's source (a
    Pickens county-owned record merged into a flood-damage row is not that row's record)."""
    src = str(_get(row, "source") or "")
    tail = src.rsplit(".", 1)[-1]
    out = {}
    for name, blk in _raw(row).items():
        if not isinstance(blk, dict) or block_kind(name) == "person":
            continue
        if not own_source_block(row, name, blk):
            continue
        if name == "arcgis_distress" and str(blk.get("layer") or "") not in ("", tail):
            continue
        out[name] = blk
    return out


def _street_of(addr: Any) -> str:
    return _dd().numbered_street(addr) if isinstance(addr, str) else ""


#: the field families a source record states its situs in (house number, street, type)
_SITUS_PARTS = (("house_num", "street_name", "street_type"), ("house_number", "road_name", None),
                ("NUMBER", "STREET", "TYPE"), ("HouseNumber", "streetname", "StreetType"),
                ("saddno", "saddstname", None))
_SITUS_FIELDS = ("WHOLE_ADDR", "PHYSICALADDR", "property_address", "siteadd", "situs",
                 "full_civic_address", "Address", "situs_address", "property_location")


def record_situs(blk: Any) -> Optional[str]:
    """The situs a source record states (never its owner's mailing lines), or None."""
    if not isinstance(blk, dict):
        return None
    for num, street, typ in _SITUS_PARTS:
        n, s = blk.get(num), blk.get(street)
        if n not in (None, "") and isinstance(s, str) and s.strip():
            t = blk.get(typ) if typ else None
            return " ".join(str(x).strip() for x in (n, s, t) if x not in (None, "") and str(x).strip())
    for f in _SITUS_FIELDS:
        v = blk.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def own_situs_streets(row: Any) -> frozenset:
    """Numbered streets the row's own source record, or the county roll on the row, states as the
    property's situs (an owner-occupied house: its mailing address IS its situs)."""
    out = set()
    raw = _raw(row)
    blocks = list(own_blocks(row).items())
    blocks += [(b, raw[b]) for b in ROLL_OWNER_BLOCKS if isinstance(raw.get(b), dict)]
    om = raw.get("owner_mailing")
    if isinstance(om, dict) and str(om.get("source") or "") in ROLL_MAILING_SOURCES:
        blocks.append(("owner_mailing", {"situs": om.get("situs")}))
    for name, blk in blocks:
        for a in [record_situs(blk)] + probe(name, blk)["addrs"]:
            s = _street_of(a)
            if s:
                out.add(s)
    return frozenset(out)


def mailing_streets(row: Any) -> frozenset:
    """Numbered streets of the owner's mailing address as the row's blocks state it."""
    out = set()
    raw = _raw(row)
    for k in ("owner_mailing", "gis", "skip_trace", "heir_estate"):
        b = raw.get(k)
        if isinstance(b, dict):
            for f in ("mailing", "mail_address", "mailing_address", "owner_mailing_address"):
                s = _street_of(b.get(f))
                if s:
                    out.add(s)
        elif isinstance(b, str) and k == "owner_mailing":
            s = _street_of(b)
            if s:
                out.add(s)
    return frozenset(out)


_UNIT = re.compile(r"(?:\b(?:apt|apartment|unit|suite|ste|lot|room|rm|floor|fl|bldg|building)\b\.?|#)"
                   r"\s*([\w-]+)", re.I)
#: a bare short token after a comma ('1429 W FLOYD BAKER BLVD, 225') is a suite, not a city or zip
_COMMA_UNIT = re.compile(r",\s*([A-Za-z]?\d{1,4}[A-Za-z]?)\s*(?:,|$)")
_HALF = re.compile(r"^\s*\d+\s*(?:1/2|½)\b")


def situs_tag(row: Any) -> str:
    """The property address a row names, '' when none: a REAL house number
    (placeholder_twins.real_house_no: '6th Avenue', 'I-85 & PELHAM RD' and a '0' / '99999' sentinel
    are none), the street's name tokens and its suffix and direction tokens exactly
    (verification.core.address_key: '100 E MAIN ST' and '100 S MAIN ST' are two addresses, 'ROAD'
    and 'RD' one), and the unit when it carries one."""
    addr = _get(row, "street_address")
    if not isinstance(addr, str) or not _pt().real_house_no(addr):
        return ""
    from .web_artifact import _is_valid_street_address
    if not _is_valid_street_address(addr):     # what the publish nulls names no property either
        return ""
    num, name, tail = address_key(addr)
    words = name | tail          # '<n> RIDGE AVE': RIDGE reads as a suffix (RDG), so no name
    if not num or not words:
        return ""
    units = sorted({u.lower() for u in _UNIT.findall(addr)} | {u.lower() for u in _COMMA_UNIT.findall(addr)})
    unit = "#" + "/".join(units) if units else ""
    half = "1/2" if _HALF.match(addr) else ""
    return f"{num}{half} {' '.join(sorted(words))}".lower() + unit


def situs_base(row: Any) -> str:
    """The row's numbered street as mailing addresses are compared (dedupe.numbered_street)."""
    return _street_of(_get(row, "street_address")) if situs_tag(row) else ""


def ident_key(row: Any) -> Optional[str]:
    """Which property the row claims to be, for grouping: a VALID parcel (placeholder_twins.
    parcel_key: 7+ characters, not one repeated digit, not a recorded-document pattern) in its
    county, else its county and numbered street. None when it names neither."""
    st, cty = _get(row, "state"), _get(row, "county")
    k = _pt().parcel_key(st, cty, _get(row, "parcel_id"))
    if k:
        return "p|" + k
    tag = situs_tag(row)
    if tag and county_key(cty):
        return f"a|{str(st or '').upper()}|{county_key(cty)}|{tag}"
    return None


def record_key(row: Any) -> Optional[tuple]:
    """The SOURCE RECORD a row is: (source, the ids and situs its own blocks state, case number).
    Two rows with one record key are one record of one source (an aged copy and its re-scrape);
    None when the own blocks state no id."""
    ids, streets = set(), set()
    for name, blk in own_blocks(row).items():
        p = probe(name, blk)
        ids |= {canon_id(x) for x in p["ids"]}
        for a in [record_situs(blk)] + p["addrs"]:
            s = _street_of(a)
            if s:
                streets.add(s)
    if not ids:
        return None
    case = re.sub(r"[^a-z0-9]", "", str(_get(row, "case_number") or "").lower())
    return (str(_get(row, "source") or ""), tuple(sorted(ids)), tuple(sorted(streets)), case)


# ------------------------------------------------------------------------------------ fused rows


def fused_record(row: Any) -> Optional[str]:
    """The parcel id the row's own source record names when it is NOT the row's (a comparable id of
    the same numbering system that is none of tax_binding.row_ids, and a VALID parcel id:
    placeholder_twins.parcel_key), else None. Candidate lists, a lien filing's parent PIN, a short
    county account and a row that has no id of its own are not fused rows."""
    if any(m in str(_get(row, "source") or "") for m in PARENT_PIN_SOURCES):
        return None
    rids = [canon_id(x) for x in row_ids(row)]
    if not rids:
        return None
    st, cty = _get(row, "state"), _get(row, "county")
    for name, blk in own_blocks(row).items():
        if name in CANDIDATE_ID_BLOCKS:
            continue
        ids = [canon_id(x) for x in probe(name, blk)["ids"]]
        if not ids or any(same_id(i, r) for i in ids for r in rids):
            continue
        for i in ids:
            # a short county account (validation nulls it as not unique) is too weak to say the
            # record is another property
            if any(comparable(i, r) for r in rids) and _pt().parcel_key(st, cty, i) is not None:
                return i
    return None


def _record_owner(blk: dict) -> Optional[str]:
    p = probe("", blk)
    for o in p["owners"]:
        if name_tokens(o):
            return o
    for f in ("NAME1", "Owner", "NAME1_1"):
        if name_tokens(blk.get(f)):
            return str(blk[f]).strip()
    last, first = blk.get("owner1_last_name"), blk.get("owner1_first_name")
    if name_tokens(last):
        return " ".join(str(x).strip() for x in (last, first) if x)
    return None


def unfuse(row: Any) -> Optional[dict]:
    """Re-key a fused row (fused_record()) to its OWN source record, in place: the record's parcel
    id (only a valid one, placeholder_twins.parcel_key), the situs it states (else none: the old
    address belonged to the displaced identity or was the owner's mailing), and the owner it
    names when that disagrees with the row's. A changed address clears the point (it was the other
    property's). raw['unfused'] records what was displaced. Returns that record, or None when the
    row is not fused or the record names no valid parcel. Never removes the row."""
    other = fused_record(row)
    if not other:
        return None
    st, cty = _get(row, "state"), _get(row, "county")
    if _pt().parcel_key(st, cty, other) is None:
        return None
    blk = next((b for n, b in own_blocks(row).items() if n not in CANDIDATE_ID_BLOCKS and any(
        same_id(canon_id(x), other) for x in probe(n, b)["ids"])), None)
    if blk is None:
        return None
    raw_pid = next(x for x in probe("", blk)["ids"] if same_id(canon_id(x), other))
    situs = record_situs(blk)
    owner = _record_owner(blk)
    rec = {"from_parcel": _get(row, "parcel_id"), "to_parcel": raw_pid,
           "from_address": _get(row, "street_address"), "reason": "own_source_record"}
    _set(row, "parcel_id", raw_pid)
    if _street_of(situs) != _street_of(_get(row, "street_address")):
        rec["to_address"] = situs
        _set(row, "street_address", situs)
        if _get(row, "latitude") is not None or _get(row, "longitude") is not None:
            rec["point_cleared"] = True
            _set(row, "latitude", None)
            _set(row, "longitude", None)
    if owner and names_disagree(owner, _get(row, "owner_name")):
        rec["from_owner"] = _get(row, "owner_name")
        rec["to_owner"] = owner
        _set(row, "owner_name", owner)
    raw = _raw(row)
    raw.pop("parcel_id_alias", None)
    cleared_fill = [k for k in SUPERSEDED_PARCEL_FILL_BLOCKS if raw.pop(k, None) is not None]
    if cleared_fill:
        rec["superseded_fill_cleared"] = cleared_fill
    raw["unfused"] = rec
    if not isinstance(_get(row, "raw"), dict):
        _set(row, "raw", raw)
    return rec


def _set(row: Any, name: str, value: Any) -> None:
    if isinstance(row, dict):
        row[name] = value
    else:
        setattr(row, name, value)


def unfuse_rows(listings: Iterable[Any]) -> dict:
    """unfuse() over a board, in place. Counts only; never raises on an odd row."""
    stats: Counter = Counter()
    for li in listings:
        try:
            rec = unfuse(li)
        except Exception:  # noqa: BLE001 - an unreadable row stays as it is
            stats["error"] += 1
            continue
        if rec:
            stats["unfused"] += 1
            stats["address_changed"] += "to_address" in rec
            stats["owner_changed"] += "to_owner" in rec
        elif fused_record(li):
            stats["fused_not_rekeyed"] += 1
    return dict(stats)


# ------------------------------------------------------------------------------- duplicate twins


def _source_ids(row: Any) -> frozenset:
    """{(state|county, parcel, source)} of every parcel id a SOURCE published for the row, however
    short (dedupe.identity: two different ids of one source in one county are two properties)."""
    ident = _dd().identity(row)
    out = set()
    for ref, src in ident.sp:
        stc, _, parcel = ref.rpartition("|")
        out.add((stc, parcel, src))
    return frozenset(out)


def view(i: int, row: Any, h=lambda x: x) -> dict:
    """What partition() reads of one row. `h` maps each string to a smaller token (the streaming
    invariant passes hash); partition only compares tokens for equality."""
    tag = situs_tag(row)
    rec = record_key(row)
    return {"i": i, "tag": h(tag) if tag else "", "base": h(situs_base(row)) if tag else "",
            "mail": frozenset(h(x) for x in mailing_streets(row)),
            "own": frozenset(h(x) for x in own_situs_streets(row)),
            "aged": is_aged(row), "rec": h(repr(rec)) if rec else None,
            "res": _pt().resolver_parcel(_raw(row)),
            "src": h(str(_get(row, "source") or "")),
            "case": h(re.sub(r"[^a-z0-9]", "", str(_get(row, "case_number") or "").lower())),
            "has_case": bool(re.sub(r"[^a-z0-9]", "", str(_get(row, "case_number") or ""))),
            "sp": frozenset((h(a), h(b), h(c)) for a, b, c in _source_ids(row)),
            "who": frozenset(h(t) for t in name_tokens(_get(row, "owner_name")))}


def _conflict(ga: list[dict], gb: list[dict]) -> bool:
    """Two groups of rows that must stay two properties although they name one address:
      * a source published two different parcel ids for them in one county (two entries of its
        roll; dedupe.different_source_parcels), or
      * two rows of one source that are not provably one record (same record_key and case) and
        whose owners share no name: one address of several units or tenants (one Asheville
        address with two STR permits of two owners; two businesses' state tax liens in one strip mall),
        not one property landed twice."""
    for x in ga:
        for y in gb:
            for stc, px, sx in x["sp"]:
                if any(sty == stc and sy == sx and py != px for sty, py, sy in y["sp"]):
                    return True
            same_record = x["rec"] is not None and x["rec"] == y["rec"] and x["case"] == y["case"]
            if (x["src"] == y["src"] and not same_record
                    and x["who"] and y["who"] and not (x["who"] & y["who"])):
                return True
    return False


def partition(views: list[dict]) -> list[list[int]]:
    """One identity group (rows of one ident_key()) split into PROPERTIES; returns lists of view
    positions. Two rows are two properties when they name two different property addresses
    (situs_tag: real house number, street, suffix and direction, unit) or when _conflict() says so,
    except that
      * an AGED copy's address that is the owner's MAILING address (on any row of the group) and
        that neither its own source record nor the county roll on it states as the situs is no
        property address, when another row of the group names a real one (a live row's address
        is what its source says today and always counts; an aged record with a case number of
        its own is its own record, not a copy);
      * an aged copy of the SAME source record (record_key) as another row is that row's property
        whatever address it carries (the county re-addressed the parcel).
    A row naming no property address joins the group's one property, or stays alone when the
    group names several (it cannot be told which) or when its parcel was attached by a resolver."""
    n = len(views)
    mail = set().union(*(v["mail"] for v in views)) if views else set()
    cases = Counter((v["src"], v["case"]) for v in views if v["has_case"])
    real = [bool(v["tag"]) and (not v["aged"] or v["base"] not in mail or v["base"] in v["own"]
                                or (v["has_case"] and cases[(v["src"], v["case"])] < 2))
            for v in views]
    has_real = any(real)
    tags = [v["tag"] if (real[k] or not has_real) else "" for k, v in enumerate(views)]
    parent = list(range(n))
    members = {k: [views[k]] for k in range(n)}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return True
        if _conflict(members[ra], members[rb]):
            return False
        parent[rb] = ra
        members[ra] += members.pop(rb)
        return True

    # same source record, one of them aged: one property (first, so the copy joins its record)
    by_rec: dict = {}
    for k, v in enumerate(views):
        if v["rec"] is None:
            continue
        j = by_rec.get(v["rec"])
        if j is None:
            by_rec[v["rec"]] = k
        elif v["aged"] or views[j]["aged"]:
            union(j, k)
    by_tag: dict = {}
    for k, t in enumerate(tags):
        if t:
            for j in by_tag.setdefault(t, []):
                if union(j, k):
                    break
            else:
                by_tag[t].append(k)
    roots = {find(k) for k, t in enumerate(tags) if t}
    for k, t in enumerate(tags):
        if t or find(k) != k or views[k]["res"]:
            continue
        if len(roots) == 1:
            union(next(iter(roots)), k)
        elif not roots:
            # no row names an address: rows of one valid parcel are one property
            for j in range(k):
                if not tags[j] and not views[j]["res"] and find(j) == j and union(j, k):
                    break
    out: dict[int, list[int]] = defaultdict(list)
    for k in range(n):
        out[find(k)].append(k)
    return list(out.values())


#: a key this many distinct property addresses share is a placeholder or master id, not a property
#: (board_selfcheck.FUSION_THRESHOLD, placeholder_twins.MAX_GROUP_ROWS)
FUSED_KEY_ADDRESSES = 4


def duplicate_groups(rows: Iterable[Any]) -> tuple[list[list[int]], dict]:
    """(clusters of 2+ row indexes that are one property, stats) over a board (rows held in memory
    by the caller: a list of Listings or dicts). Fused rows (fused_record) are left out: their
    parcel is not their own."""
    groups: dict[str, list[dict]] = defaultdict(list)
    stats: Counter = Counter()
    for i, row in enumerate(rows):
        try:
            k = ident_key(row)
            if not k or fused_record(row):
                continue
            groups[k].append(view(i, row))
        except Exception:  # noqa: BLE001
            stats["error"] += 1
    clusters = []
    for k, views in groups.items():
        if len(views) < 2:
            continue
        if len({v["tag"] for v in views if v["tag"]}) >= FUSED_KEY_ADDRESSES:
            stats["fused_keys"] += 1
            continue
        parts = partition(views)
        stats["multi_address_groups"] += len(parts) > 1
        for p in parts:
            if len(p) > 1:
                clusters.append([views[x]["i"] for x in p])
    stats["duplicates"] = sum(len(c) - 1 for c in clusters)
    return clusters, dict(stats)


#: how many absorbed records one row keeps in raw['merged_records']
MAX_MERGED_RECORDS = 10


def _keep_record(merged: Any, other: Any) -> None:
    """A second LIVE record of the property (another case, permit or incident) merged into the
    base: its own source blocks stay readable in raw['merged_records'] (the base kept its own
    blocks of the same name), with its source, case number and listing type."""
    raw = _raw(merged)
    recs = raw.get("merged_records")
    recs = list(recs) if isinstance(recs, list) else []
    if len(recs) >= MAX_MERGED_RECORDS:
        return
    lt = _get(other, "listing_type")
    recs.append({"source": _get(other, "source"), "case_number": _get(other, "case_number"),
                 "listing_type": getattr(lt, "value", lt), "street_address": _get(other, "street_address"),
                 "blocks": copy.deepcopy(own_blocks(other))})
    raw["merged_records"] = recs
    if not isinstance(_get(merged, "raw"), dict):
        _set(merged, "raw", raw)


def _base_index(rows: list, idxs: list[int]) -> int:
    """The row the others merge into: a live row (not aged) first, then the latest last_seen, then
    the row with the most raw blocks."""
    return max(idxs, key=lambda i: (not is_aged(rows[i]), str(_get(rows[i], "last_seen") or ""),
                                    len(_raw(rows[i]))))


def _revalidate_lien_sweep(li: Any) -> bool:
    """A merged row's raw['rod_lien_sweep'] stamp (enrichment_register_lien_sweep.py /
    enrichment_county_lien_sweep.py) was computed against the owner_name ONE SIDE of a merge had
    BEFORE the merge; Listing.merge() keeps a scalar field (owner_name) from whichever side was
    self, but deep-merges raw, so a stamp a merge's LOSING identity had already correctly earned
    can end up attached to raw on a row whose final owner_name is the WINNING side's -- a stamp
    that was right for the identity it was computed against, now sitting under a different name
    (2026-10-17 gap-sweep wave 7, top80-lien-sweep-name-fit). Each stamped instrument already
    carries its own grantor/grantee text ('f'/'g', lien_sweep.doc_summary), so this re-checks
    fit purely from data already on the stamp -- no register re-read, no network. Drops the
    stamp when none of its instruments still name-fit; returns True when it did. Pure."""
    raw = _raw(li)
    stamp = raw.get("rod_lien_sweep") if isinstance(raw, dict) else None
    if not isinstance(stamp, dict) or stamp.get("status") not in ("found", "possible"):
        return False
    q = owner_query(getattr(li, "owner_name", None) or "")
    if q is None:
        raw.pop("rod_lien_sweep", None)
        return True
    for inst in stamp.get("instruments") or ():
        if not isinstance(inst, dict):
            continue
        if name_fit(q, inst.get("f") or "") or name_fit(q, inst.get("g") or ""):
            return False
    raw.pop("rod_lien_sweep", None)
    return True


def collapse_twins(listings: list) -> dict:
    """Merge every cluster duplicate_groups() finds, IN PLACE (Listings). The live base absorbs its
    aged copies with placeholder_twins.absorb_copies (only COPY_ALLOWLIST: a county situs over a
    sentinel, the earlier first_seen of the same owner); a second live row merges as dedupe would
    have merged it (dedupe.merge_rows), the base keeping its own source blocks
    (block_binding.keep_fresh_blocks) so two records never blend leaf by leaf. Rows are removed
    only into the row they merged into; nothing is merged across two properties."""
    clusters, stats = duplicate_groups(listings)
    pt, dd = _pt(), _dd()
    drop: set[int] = set()
    out: Counter = Counter(stats)
    for c in clusters:
        b = _base_index(listings, c)
        base = listings[b]
        aged = [listings[i] for i in c if i != b and is_aged(listings[i])]
        live = [listings[i] for i in c if i != b and not is_aged(listings[i])]
        merged = base
        for other in live:
            m = dd.merge_rows(merged, other)
            keep_fresh_blocks(merged, m)
            _keep_record(m, other)
            merged = m
            out["merged_live"] += 1
        if live and _revalidate_lien_sweep(merged):
            out["lien_sweep_dropped_on_merge"] += 1
        if aged:
            aged.sort(key=lambda r: str(_get(r, "last_seen") or ""), reverse=True)
            merged, taken = pt.absorb_copies(merged, aged)
            out["absorbed_aged"] += len(aged)
            out["address_taken"] += "street_address" in taken
        raw = _raw(merged)
        raw["twins_collapsed"] = raw.get("twins_collapsed", 0) + len(c) - 1
        if not isinstance(merged.raw, dict):
            merged.raw = raw
        listings[b] = merged
        drop |= {i for i in c if i != b}
    if drop:
        listings[:] = [li for i, li in enumerate(listings) if i not in drop]
    out["rows_removed"] = len(drop)
    out["clusters"] = len(clusters)
    return dict(out)


# ------------------------------------------------------------------------------- owner conflicts

#: blocks that look a parcel up BY ITS ID in the county's current parcel record: a contradicting
#: owner there is the county's current owner of the row's parcel
CURRENT_ROLL_BLOCKS = ("gis_attrs_full", "lrcpwa", "lincoln_vacant", "gaston_gis", "transylvania_vacant",
                       "greenville_distress")
#: blocks whose owner is a tax bill's taxpayer (of the years the bill is for), not today's owner
HISTORICAL_ROLL_BLOCKS = ("qpaybill_roll",)
#: id fields (lower case) the current-roll blocks key their record by, beside block_binding's
_ROLL_ID_EXTRA = ("reid", "parno", "altparno", "parid", "pin")


def _roll_ids(blk: dict) -> list[str]:
    ids = list(probe("", blk)["ids"])
    for k, v in blk.items():
        if str(k).lower() in _ROLL_ID_EXTRA and v not in (None, ""):
            ids.append(str(v))
    return ids


def owner_claims(row: Any) -> list[dict]:
    """Every county-roll owner on the row, classified:
    'bound'      the county's record of the row's own parcel (its id is one of the row's ids);
    'historical' a tax bill's taxpayer;
    'foreign'    a record of another parcel of the row's numbering system;
    'unbound'    no parcel id to tell (a point or parcel-cache 'gis' bag, a mailing record)."""
    raw = _raw(row)
    rids = [canon_id(x) for x in row_ids(row)]
    out = []
    for b in ROLL_OWNER_BLOCKS + HISTORICAL_ROLL_BLOCKS:
        blk = raw.get(b)
        if not isinstance(blk, dict):
            continue
        owners = [o for o in probe(b, blk)["owners"] if name_tokens(o)]
        if b == "lincoln_vacant" and name_tokens(blk.get("NAME1")):
            owners = owners or [str(blk["NAME1"])]
        if not owners:
            continue
        ids = [canon_id(x) for x in _roll_ids(blk)]
        if b in HISTORICAL_ROLL_BLOCKS:
            kind = "historical"
        elif ids and rids and any(same_id(i, r) for i in ids for r in rids):
            kind = "bound" if b in CURRENT_ROLL_BLOCKS else "unbound"
        elif ids and rids and any(comparable(i, r) for i in ids for r in rids):
            kind = "foreign"
        else:
            kind = "unbound"
        for o in owners:
            out.append({"block": b, "owner": o, "kind": kind})
    om = raw.get("owner_mailing")
    if isinstance(om, dict) and str(om.get("source") or "") in ROLL_MAILING_SOURCES:
        for o in probe("owner_mailing", om)["owners"]:
            if name_tokens(o):
                pid = om.get("parcel_id")
                bound = bool(pid and rids and any(same_id(canon_id(pid), r) for r in rids))
                foreign = bool(pid and rids and not bound and any(comparable(canon_id(pid), r) for r in rids))
                out.append({"block": "owner_mailing", "owner": o,
                            "kind": "foreign" if foreign else ("bound" if bound else "unbound")})
    return out


def owner_verdict(row: Any) -> Optional[dict]:
    """None when the row's owner is not contradicted (no owner, no roll owner, or some roll owner
    shares a name with it). Else {'decision', 'reason', 'other', 'block'}:
      'roll'       a 'bound' current record names another owner and the row's owner was never
                   refreshed (raw['owner_name_as_of'] absent): the county's record of THIS parcel
                   wins (3 of 3 checked against NC OneMap);
      'row'        every contradicting owner is 'unbound', 'historical' or 'foreign' (11 of 11
                   checked: the row was right);
      'undecided'  a bound record contradicts an owner that carries a refresh stamp (two current
                   claims; the stamp is not proof, see the module docstring)."""
    own = _get(row, "owner_name")
    if not name_tokens(own):
        return None
    claims = owner_claims(row)
    usable = [c for c in claims if c["kind"] != "foreign"]
    if not usable or any(not names_disagree(own, c["owner"]) for c in usable):
        return None
    bound = [c for c in usable if c["kind"] == "bound"]
    if bound:
        c = bound[0]
        if _raw(row).get("owner_name_as_of"):
            return {"decision": "undecided", "reason": "bound_record_vs_refreshed_owner",
                    "other": c["owner"], "block": c["block"]}
        return {"decision": "roll", "reason": "bound_record", "other": c["owner"], "block": c["block"]}
    c = usable[0]
    return {"decision": "row", "reason": f"{c['kind']}_record", "other": c["owner"], "block": c["block"]}


def resolve_owner(row: Any) -> Optional[str]:
    """owner_verdict() applied in place: 'roll' replaces owner_name with the bound record's owner;
    every contradicted row gets raw['owner_conflict'] = {decision, reason, block, loser} (the
    name that lost, or for 'undecided' the roll's). Returns the decision or None. Idempotent: a
    replaced owner agrees with the roll afterwards."""
    v = owner_verdict(row)
    raw = _raw(row)
    if v is None:
        return None
    rec = {"decision": v["decision"], "reason": v["reason"], "block": v["block"]}
    if v["decision"] == "roll":
        rec["loser"] = _get(row, "owner_name")
        _set(row, "owner_name", v["other"])
    else:
        rec["loser"] = v["other"]
    raw["owner_conflict"] = rec
    if not isinstance(_get(row, "raw"), dict):
        _set(row, "raw", raw)
    return v["decision"]


#: shapes that identify a PARTY ROLE, not a person -- a conservative, whole-string match (1-3
#: words ending in one of these nouns) so an ordinary long name that happens to contain one of
#: these words elsewhere is never caught, and a genuine rare surname ("Clerk", "Collector") is
#: caught only when it is the ENTIRE offered name, which the verification sample's real examples
#: ("Procurement Manager") always were. False positives here just lose the personalized name
#: (outreach.py falls back to the next candidate, or the generic default) -- the safe direction.
_JOB_TITLE_RE = re.compile(
    r"^(?:[A-Z]+\s+){0,2}(?:MANAGER|DIRECTOR|SUPERVISOR|OFFICER|ADMINISTRATOR|COORDINATOR|"
    r"CLERK|COLLECTOR|TREASURER|ASSESSOR|RECORDER|REGISTER|ATTORNEY|PARALEGAL|AGENT|"
    r"REPRESENTATIVE|SECRETARY|EXAMINER|INSPECTOR|AUDITOR|COMPTROLLER|SPECIALIST|ANALYST)$"
)

#: raw['owner_mailing']['source'] values that name a LIEN FILING's own unvalidated free-text
#: parse, not a county tax roll -- liensnc_handoff.py's parse_owner() reads a filing's
#: "owner_text" line with no identity check at all (see enrichment_skip_trace.py's
#: TaxRecordsOnlyProvider, which copies this straight into raw['skip_trace']['owner_name'] too),
#: so an entity-suffixed hit sourced from here is as likely to be the filing agent's or a
#: contractor's registered name as the actual property owner. An LLC/trust owner sourced from
#: an actual county roll block is NOT flagged by this -- only this specific unvalidated source.
_LIEN_FILING_SOURCES = frozenset({"liensnc_filing", "liensnc"})


def suspicious_owner_name(name: Any, *, source: Optional[str] = None) -> Optional[dict]:
    """Safety net for the PARTY-ROLE CONFUSION defect in the module docstring above -- a
    different bug class from owner_verdict()/resolve_owner(): those settle "the county roll
    disagrees with a name that IS a person's"; this catches "the string offered as an owner is
    not a person's name at all". Deliberately cheap and non-exhaustive (real identity
    resolution is out of scope); callers must fail SAFE on a hit, never guess.

    `source` is the candidate's own provenance tag when it has one (raw['owner_mailing']
    ['source']) -- needed only for the entity_from_lien_filing rule below.

    None when `name` reads as an ordinary person (or an entity sourced from an actual county
    roll block). Else {"reason", "name"}:
      'government'               classify_entity_type() reads a county/city/state/authority/
                                  district name.
      'entity_from_lien_filing'  an LLC/Inc/Trust/Corp-suffixed name whose own source is a lien
                                  filing's free-text parse, not a county tax roll.
      'job_title'                the whole string is job-title-shaped, not a name.
    """
    if not name_tokens(name):
        return None
    from .name_normalize import classify_entity_type, normalize_name
    kind = classify_entity_type(name)
    if kind == "government":
        return {"reason": "government", "name": str(name)}
    if kind in ("entity", "trust") and source in _LIEN_FILING_SOURCES:
        return {"reason": "entity_from_lien_filing", "name": str(name)}
    if _JOB_TITLE_RE.match(normalize_name(name)):
        return {"reason": "job_title", "name": str(name)}
    return None


def owner_identity_uncertain(row: Any) -> Optional[dict]:
    """suspicious_owner_name() applied to THIS row's own li.owner_name, using
    raw['owner_mailing']['source'] as the provenance tag. A convenience for callers that only
    care about the row's primary owner field; outreach.py's _owner() instead runs the same
    check per-candidate across every owner source it considers (li.owner_name,
    skip_trace.owner_name, li.defendant), since which field is actually about to be used
    determines what should be checked."""
    om = _raw(row).get("owner_mailing")
    source = om.get("source") if isinstance(om, dict) else None
    return suspicious_owner_name(_get(row, "owner_name"), source=source)


# ---------------------------------------------------------------------------
# STALE OWNER AFTER A REAL TRANSFER. The residual gap f5eeab0d/f8aa709c (2026-11-19) scoped out
# by name: a verification sample found 22% of li.owner_name/skip_trace.owner_name mismatches had
# skip_trace more correct -- concentrated in builder-new-construction and heir/estate parcels
# where li.owner_name (read off a county tax-roll snapshot) was never refreshed after a real,
# recorded conveyance. "too small a slice, and with no reliable flag to key off at this call
# site" (f5eeab0d's own commit message) -- which is still true for the GENERAL case: this board
# does not carry a deed chain with usable grantor/grantee data for that population
# (enrichment_deed_chain's own measured coverage -- assessor_card 6.9%, rod_docs 0.4% -- live-
# checked 2026-11-20 against the 24,154 rows whose owner_name reads as a builder/developer
# entity: 4,268 have ANY deed_chain, and across every one of them exactly 0 have the entity as a
# transfer's grantor paired with a DIFFERENT grantee. There is no signal there to key off.)
#
# raw['rod_chain']['conveyed_out_since'] (enrichment_rod_chain.py, a register name-index search,
# off by default and only wired for a subset of NC counties) is the one place a genuine signal
# DOES exist -- but it is found by the owner's NAME, not by parcel (that module's own docstring:
# "a chain is found by the OWNER'S NAME, so its newest deed can be that owner's deed for another
# parcel"; a 2026-10-09 sample of 30 found 14 right, 10 another parcel's deed, 6 missing a later
# deed). Live-checked 2026-11-20 against the 109 real rows currently carrying
# binding.reason=="owner_conveyed_since_last_deed": the risk is not hypothetical. A builder who
# buys a dozen lots in one bulk deed and sells them off one at a time is the worst case --
# RiverWILD Homes LLC's one retrieved conveyance ("MEADOW CREST Lot 4") cannot be the current
# owner of all three separate board rows on East Clydes Point Way that cite the same bulk chain,
# and Byers Construction & Development LLC's retrieved conveyance (3.21 AC) turned out to be a
# DIFFERENT, larger tract than the 0.314 AC parcel this row's own county_deed_ref binds it to.
# Only 5 of the 109 (Clark Joshua Keith -> Blueridge Processing Corp; a life-estate/remainderman
# pair; two heir deeds; JAG Development Company -> Colony Custom Builders LLC, the one live
# builder/developer example) could be independently tied to THIS row's own parcel rather than a
# namesake's or a different lot in the same bulk purchase. rod_chain_conveyance_owner() below is
# that narrow confirmation, used as outreach.py's new FIRST candidate; everything that fails it
# (the overwhelming majority -- rod_chain itself covers well under 1% of the board, since
# FORECLOSURE_ROD_CHAIN defaults off) falls straight through to the existing li.owner_name ->
# skip_trace.owner_name -> li.defendant chain, unchanged.
# ---------------------------------------------------------------------------

#: a parcel_id this short could coincidentally appear inside an unrelated description's digits
_CONVEYANCE_MIN_PARCEL_DIGITS = 8


def _conveyance_confirmed(row: Any, entry: dict) -> Optional[str]:
    """Independent, row-specific proof that `entry` (one of raw['rod_chain']['conveyed_out_since'])
    is THIS row's own parcel's deed, not a namesake's or a different lot in the same bulk
    purchase -- the one thing a name-matched chain cannot promise on its own (see the module note
    above). Either tie is read off data this row already carries; nothing is fetched.
      'book_page'   entry's own book/page is the SAME instrument the county's current parcel
                    record cites (lawyer_lane.county_deed_ref/same_book_page) -- the strongest
                    tie there is, independent of either side having a date.
      'parcel_id'   this row's own parcel_id (digits only, >= _CONVEYANCE_MIN_PARCEL_DIGITS of
                    them, to rule out a short coincidental match) appears in entry's own recorded
                    description -- a register index often embeds the parcel/lot number in the
                    text (e.g. "Parcel: 5468-30-1427-00 LOT 17 POLLOCKSVILLE TOWNSHIP").
    None when neither ties out."""
    from .lawyer_lane import county_deed_ref, same_book_page
    cdr = county_deed_ref(row)
    if same_book_page(entry.get("book"), entry.get("page"), cdr.get("book"), cdr.get("page")):
        return "book_page"
    pid = re.sub(r"[^0-9]", "", str(_get(row, "parcel_id") or ""))
    if len(pid) >= _CONVEYANCE_MIN_PARCEL_DIGITS:
        desc_digits = re.sub(r"[^0-9]", "", str(entry.get("description") or ""))
        if pid in desc_digits:
            return "parcel_id"
    return None


def rod_chain_conveyance_owner(row: Any) -> Optional[dict]:
    """The grantee of a register deed PROVEN -- not merely name-matched -- to be THIS row's own
    parcel, conveyed away from the name raw['rod_chain'] searched for: the stale-owner-after-a-
    real-transfer gap described in the module note above. None whenever there is nothing to
    confirm against (no rod_chain, no status "ok", no conveyed_out_since) or no candidate
    conveyance ties to this parcel specifically (_conveyance_confirmed()) -- fails safe rather
    than trusting a name-only chain. Checks conveyances in the order enrichment_rod_chain.py
    already gives them (newest first) and returns the first confirmed one, i.e. the most recent
    proven conveyance. Else {'name': the grantee(s), 'tie', 'recorded', 'book', 'page'}."""
    rc = _raw(row).get("rod_chain")
    if not isinstance(rc, dict) or rc.get("status") != "ok":
        return None
    for entry in rc.get("conveyed_out_since") or []:
        if not isinstance(entry, dict):
            continue
        tie = _conveyance_confirmed(row, entry)
        if not tie:
            continue
        grantees = [str(g).strip() for g in (entry.get("grantees") or []) if str(g or "").strip()]
        if not grantees:
            continue
        return {"name": "; ".join(grantees), "tie": tie, "recorded": entry.get("recorded"),
                "book": entry.get("book"), "page": entry.get("page")}
    return None


def resolve_owners(listings: Iterable[Any]) -> dict:
    """resolve_owner() over a board, in place. Counts only; never raises on an odd row."""
    stats: Counter = Counter()
    for li in listings:
        try:
            d = resolve_owner(li)
        except Exception:  # noqa: BLE001
            stats["error"] += 1
            continue
        if d:
            stats[d] += 1
    return dict(stats)


def run_identity_pass(listings: list) -> dict:
    """The pipeline step: unfuse, then collapse duplicate twins, then resolve owner conflicts (on
    the collapsed rows). Order matters: an unfused row may be the twin of its own record's row."""
    out = {}
    out["unfuse"] = unfuse_rows(listings)
    out["twins"] = collapse_twins(listings)
    out["owners"] = resolve_owners(listings)
    return out


__all__ = [
    "collapse_twins", "duplicate_groups", "fused_record", "ident_key", "owner_identity_uncertain",
    "owner_verdict", "partition", "record_key", "resolve_owner", "resolve_owners",
    "rod_chain_conveyance_owner", "run_identity_pass", "situs_tag", "suspicious_owner_name",
    "unfuse", "unfuse_rows",
]
