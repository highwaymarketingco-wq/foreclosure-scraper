"""Listing deduplication. Same property from multiple sources merges into one row."""
from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from typing import NamedTuple, Optional

import structlog
from rapidfuzz import fuzz

from .models import Listing
from .validation import _PARCEL_BAD_PATTERNS

log = structlog.get_logger()


_SUFFIX = {
    "avenue": "ave", "ave": "ave", "street": "st", "st": "st", "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr", "lane": "ln", "ln": "ln", "boulevard": "blvd", "blvd": "blvd",
    "court": "ct", "ct": "ct", "circle": "cir", "cir": "cir", "place": "pl", "pl": "pl",
    "trail": "trl", "trl": "trl", "way": "way", "parkway": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy": "hwy", "terrace": "ter", "ter": "ter", "loop": "loop", "run": "run",
    "cove": "cv", "cv": "cv", "path": "path", "pike": "pike", "point": "pt", "pt": "pt",
    "crossing": "xing", "square": "sq", "ridge": "rdg",
}


def _canon_street(a: str) -> str:
    """House# + street name through the standardized suffix, dropping any trailing city/unit
    ('19 gosnell avenue inman' -> '19 gosnell ave'). '' if no leading house# or no known suffix."""
    if not a:
        return ""
    toks = a.split()
    if not toks or not re.match(r"^\d", toks[0]):
        return ""
    for i in range(1, len(toks)):
        base = re.sub(r"[^a-z]", "", toks[i])
        if base in _SUFFIX:
            return " ".join(toks[:i] + [_SUFFIX[base]])
    return ""


def _strong_sigs(li: Listing) -> set:
    """Strong same-property signatures for union-merge. Excludes placeholder /
    bankruptcy 'addresses' so name-only rows never collapse together."""
    out: set = set()
    st = (li.state or "")
    z = (li.zip_code or "").strip()
    a = _norm_addr(li.street_address)
    lt = li.listing_type.value if hasattr(li.listing_type, "value") else str(li.listing_type or "")
    if a.startswith(("lis pendens", "property in", "vacant")) or lt == "bankruptcy":
        a = ""
    pn = re.sub(r"[^a-z0-9]", "", (li.parcel_id or "").lower())
    # Same digitless-parcel rejection as models._normalize_parcel. This signature is
    # scoped to the STATE, not the county, so a bogus alpha "parcel" fuses strangers
    # across the whole state -- 'ehurst' linked 122 Pinehurst properties.
    if pn and not any(c.isdigit() for c in pn):
        pn = ""
    if pn and len(pn) >= 4 and st:          # guard: whitespace/degenerate parcel -> no sig
        out.add(("p", pn, st))
        # Buncombe (and similar) write the same PIN two ways: a 15-digit zero-padded form
        # (9678774126 -> 967877412600000) and the bare 10-digit. Emit the 10-digit form too so
        # the padded + bare copies of one parcel union-merge (they otherwise split, esp. on
        # bankruptcy rows that have no address signature to fall back on).
        if len(pn) == 15 and pn.endswith("00000"):
            out.add(("p", pn[:10], st))
    cn = (li.case_number or "").strip()
    if cn and a:                            # require a real case# AND a real address
        out.add(("c", cn, (li.county or ""), a))
    if a and z:
        out.add(("a", a, z))
    # Canonical street + county + state — merges the SAME street address across sources even when
    # one copy lacks a zip or jams the city into the street field (the '19 Gosnell Ave' dup class).
    cs = _canon_street(a)
    cty = re.sub(r"[^a-z0-9]", "", (li.county or "").lower())
    if cs and cty and st:
        out.add(("s", cs, cty, st))
    return out


def _norm_addr(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.lower().replace(",", " ").split())


def _house_no_of(addr: str | None) -> str:
    """Leading house number of a street address, '' when there isn't one."""
    m = re.match(r"\s*(\d+)\b", (addr or "").strip())
    return m.group(1) if m else ""


def _provably_different_property(a: Listing, b: Listing) -> bool:
    """True when two rows are provably NOT the same property.

    A DIFFERENT HOUSE NUMBER is a different house, essentially always. Measured on the
    live board 2026-09-11: rows were merging like

        '306 fountain way'           + '346 fountain way'            parcel 9698372180
        '545 dillingham panoview rd' + '562 dillingham panoview rd'

    -- two separate houses fused because one carries the other's parcel id. A wrong
    parcel does not fail loudly, it silently deletes a property. This guard cannot repair
    the bad parcel; it stops the MERGE, which is the half that loses data.

    Deliberately narrow: it fires only when BOTH rows carry a house number and the two
    differ. Suffix and punctuation variants ('318 fairfax ave' vs '318 fairfax ave.',
    '11 carefree lane' vs '11 carefree ln') share a house number and still merge -- that
    is 93% of real merge groups and must not be lost.
    """
    ha, hb = _house_no_of(a.street_address), _house_no_of(b.street_address)
    return bool(ha and hb and ha != hb)


# ---------------------------------------------------------------- identity evidence (2026-10-06)
# THE DEFECT. dedupe() merged DIFFERENT properties whenever their addresses looked alike and the
# house-number guard above had nothing to compare. Measured on a fresh four-source scrape
# (spartanburg_vacant, spartanburg_condemned, buncombe_delinquent_tax, rutherford_tax; 16,932
# records): 755 output rows had absorbed 2,596 records of other properties (2,339 distinct valid
# parcels gone). On 56 sources scraped fresh together (185,178 rows after main.run()'s filters,
# about 70% of a full run's rows): 6,992 rows had absorbed 32,720 records (26,410 valid parcels),
# and pass 1 deleted 72 rows outright (see the overwrite note in dedupe()). The rules that did it:
#   * pass 2 (fuzzy): token_set_ratio >= 92 in the same zip or county. A county roll's "no house
#     number" sentinel ("0 SOUTHPORT RD", "99999 US 70 HWY") reads as house number "0"/"99999" on
#     both sides, so the guard saw EQUAL numbers: 33 different "0 SOUTHPORT RD" lots, 33 parcels,
#     became one row; "0 HIGH ST" took "0 HUGH ST" and "0 S HIGH POINT RD". A numberless street
#     ("LOOKOUT RD", "BANKS TOWN RD") has no number at all, so it matched every numbered house on
#     its road ("328 LOOKOUT RD"), and the merged row kept the numberless address, so it went on
#     absorbing. Same-number different-street pairs scored >= 92 too ('128 GEORGE ST' + '128
#     GEORGIA ST', '209 BUTLER ST' + '209 BUNKER ST'), each with its own parcel.
#   * pass 3 (signatures): the canonical-street signature ("0 southport rd", county, state) joined
#     the ROEBUCK lots to the SPARTANBURG ones; union-find then chains through any member.
# THE RULE (identity_conflict below; every merge in all three passes goes through it, against the
# whole group already merged, not just the row that matched):
#   * two different REAL house numbers: different properties (the old guard, except that a
#     sentinel is not a real number: placeholder_twins.real_house_no);
#   * two different VALID parcels: different properties, whatever the addresses say. Valid =
#     placeholder_twins.parcel_key() (state + county + normalized parcel of 7+ chars, not one
#     repeated digit, not a book/page pattern; digitless garbage like the PIN_RE 'ehurst' is already
#     rejected) and not attached by a resolver (placeholder_twins.resolver_parcel: a geocoded or
#     road-centroid guess proves nothing either way). The same parcel number in two counties is
#     two parcels; one county spelled two ways ('Rutherford' / 'Rutherfordton') is one;
#   * a row with no real house number (none, or a sentinel) matches a numbered row only when their
#     valid parcels agree, and matches another unnumbered row on ADDRESS evidence only when their
#     valid parcels agree. A shared case number or source URL is not address evidence and still
#     merges as before.
# When a merge does join an unnumbered row to a numbered one (same valid parcel), the merged row
# takes the numbered address (placeholder_twins.fold() does the same): a sentinel is nulled on
# publish, and a numberless base must not go on matching other houses on its road.
#
# ---------------------------------------------------------------- shared parcels (2026-10-06, 2)
# THE DEFECT LEFT AFTER THE RULE ABOVE (replay of main.run()'s second dedupe on the 10/5
# checkpoint's 13 heaviest-loss counties, 75,124 rows): one row still absorbed 608 different
# properties. Rutherford parcel 1654116 (a church at the Rutherfordton county-seat point) sat on
# 619 rows of 10 sources (589 rutherford_tax lots, lis pendens, divorces, land listings), every
# one attached by enrichment_parcel_from_geo at that point: the geocoder's Tier-4 fallback puts an
# address-less row on its county seat, and the resolver then took whatever parcel lies under it.
# A resolver parcel is no identity (pk None above), but pass 1 still BUCKETED the rows under it,
# and a 'parcel:' key counts as PARCEL evidence, which lets two unnumbered rows merge. Then
# scripts/fill_address_from_parcel.py wrote that parcel's situs onto the address-less rows
# (raw['situs_address_source'] = 'parcel_cache:exact'): 104 New Hanover lis pendens and divorces
# all read '100 RALEIGH ST', 30 Rutherford rows '139 RUNNING DEER LN', the same real house number
# on every row, so they merged on ADDRESS evidence too. A source can also give one id to many
# houses (liensnc master-tract PINs, a condo complex, spartanburg_property_cleanup's
# 5-20-01-037.00 on '113 OAKDALE CT', '113 HOLMES DR' and '113 VICTORIA RD').
# THE RULE (on top of the one above):
#   * a parcel id the input attaches to OVERSHARED_MIN_STREETS or more different numbered streets
#     (overshared_parcels(), any provenance) is not valid identity (placeholder_twins.parcel_key
#     with `overshared`);
#   * such a parcel, or one enrichment_parcel_from_geo attached at a fallback point
#     (placeholder_twins.fallback_point_parcel), is no MATCH KEY either: pass 1 buckets the row
#     under its next dedupe_key() branch (address or case; never the URL, which one county roll's
#     PDF gives thousands of rows) and pass 3 drops its 'p' signature;
#   * an address written from such a parcel's record (placeholder_twins.situs_from_parcel) is not
#     a real house number for identity: the row matches on case number or URL, never on it.
# A resolver parcel found at the row's own precise point still buckets as before (no evidence
# either way, as above).

# ---------------------------------------------------------------- short source parcels (2026-10-06, 3)
# THE DEFECT LEFT AFTER THE TWO RULES ABOVE (the same four-source fresh scrape, 16,932 records): no
# output row held two valid parcels or two real house numbers (the old rule left 755), but 21
# rutherford_tax pairs were still merged: one real house number ('146 WALDO LN' twice, '173 E MAIN
# ST' / '173 N MAIN ST'), an address score >= 92, and two different parcel ids on two different tax
# bills, with different amounts and (19 of 21) different taxpayers. Rutherford's roll mixes 6-digit
# and 7-digit ids, and an id under placeholder_twins.MIN_PARCEL_LEN is no valid parcel (validation.py
# nulls it as not unique), so identity_conflict() saw no parcel on that side.
# THE RULE (on top of the ones above): a short id cannot prove two rows are the SAME property, but
# two different ids published by ONE source, in one county, are two entries of that source's roll
# (source_parcel(), different_source_parcels()). Ids from two different sources are two id systems
# and do not conflict; neither does an id a resolver attached, an over-shared one, one repeated
# character, a recorded-document pattern, or one under MIN_SOURCE_PARCEL_LEN characters. A group
# remembers every (parcel, source) it has taken in, like its valid parcel.
#
# ---------------------------------------------------------------- roll URL keys (2026-10-09, 4)
# THE DEFECT (audit 2026-10-09, regressions; the gated d42058b3 run against the 10/7 board): a row
# with no parcel id, no address and no case number is keyed by its source URL (Listing.dedupe_key's
# last branch), and a county roll's URL is the source_url of every row of the roll. The rule above
# never fired on such rows: their short id had been nulled by validation (a published row, replayed
# by carryover.py or aged by merge_prior_board, carries parcel_id None and the id only in
# raw['parcel_id_nulled'] or the source's own raw block), and URL evidence merges two unnumbered rows
# with no parcel. Rutherford's TR-452 roll was blocked (403) from the VM, carryover replayed its
# 5,109 published rows, and dedupe() fused the 580 that had no situs into ONE row (580 taxpayers,
# 580 parcels); the 10/7 board's aged PTS Cloud rows of Madison, Beaufort, Guilford, Pitt and Hyde
# share 'https://bcpwa.ncptscloud.com/' and fused across counties in the second dedupe (109 gone).
# THE RULE: identity_of() reads the id the row's source published even when validation nulled it
# (nulled_source_parcel(); the same lookup board_persist._prior_identity applies to prior rows), so
# two different ids of one source stay two rows; and on URL evidence alone two rows merge only when
# they name the same county and the same owner (url_key_conflict()): a shared URL is the same RECORD
# only when nothing on the two rows says otherwise.

#: A parcel id on this many different numbered streets is not one property's id. Of the published
#: board's parcels (2026-10-06) 111,543 carry one numbered street, 819 two (a duplex, a corner
#: lot, an owner-mailing address copied as the situs), and the 60 with exactly three are almost all
#: several properties (master-tract PINs of a subdivision, condo complexes, a mobile-home park
#: roll, three different streets under one cleanup-layer id); one was three spellings of one
#: address. Twins and fusion checks elsewhere use 4 (placeholder_twins.MAX_GROUP_ROWS); this
#: counts STREETS, not rows, so three is already three properties or a broken id.
OVERSHARED_MIN_STREETS = 3

#: Shortest normalized parcel id source_parcel() counts. board_persist._restored_parcel_key() uses
#: the same floor for the short ids validation.py nulls ('0', '00', '123' key many rows of a county).
MIN_SOURCE_PARCEL_LEN = 4

_DIRECTIONS = frozenset({"n", "s", "e", "w", "ne", "nw", "se", "sw",
                         "north", "south", "east", "west"})


def _pt():
    """placeholder_twins, imported on first use (it imports this module at load time)."""
    from . import placeholder_twins
    return placeholder_twins


def numbered_street(addr) -> str:
    """'<real house number> <street>' for counting how many different numbered addresses one parcel
    id sits on; '' without a real house number (placeholder_twins.real_house_no). Case, commas,
    directionals, a trailing unit and anything after the street suffix (city, zip) are dropped and
    the suffix standardized, so spellings of one address count once: '113 OAKDALE COURT,
    SPARTANBURG, 29306' and '113 Oakdale Ct' are both '113 oakdale ct'."""
    from .models import _UNIT_RE
    hn = _pt().real_house_no(addr)
    if not hn:
        return ""
    s = _norm_addr(addr)
    m = _UNIT_RE.search(s)
    if m:
        s = s[:m.start()]
    toks = s.split()
    cs = _canon_street(s)
    body = cs.split()[1:] if cs else toks[1:4]
    return " ".join([hn] + [t for t in body if t not in _DIRECTIONS])


def overshared_parcels(listings, min_streets: int = OVERSHARED_MIN_STREETS) -> frozenset[str]:
    """placeholder_twins.parcel_ref() of every parcel id the rows attach to `min_streets` or more
    different numbered streets (numbered_street()). Rows are Listings or board row dicts."""
    pt = _pt()
    streets: dict[str, set] = {}
    for li in listings:
        if isinstance(li, dict):
            st, cty, pid, addr = (li.get("state"), li.get("county"), li.get("parcel_id"),
                                  li.get("street_address"))
        else:
            st, cty, pid, addr = li.state, li.county, li.parcel_id, li.street_address
        if not pid:
            continue
        ref = pt.parcel_ref(st, cty, pid)
        s = numbered_street(addr) if ref else ""
        if s:
            streets.setdefault(ref, set()).add(s)
    return frozenset(k for k, v in streets.items() if len(v) >= min_streets)


def no_key_parcel(state, county, parcel_id, raw, overshared: frozenset = frozenset()) -> bool:
    """The row's parcel id must not even bring rows together (pass 1 bucket, pass 3 signature): it
    is over-shared, or enrichment_parcel_from_geo attached it at a fallback point."""
    if not parcel_id or not str(parcel_id).strip():
        return False
    pt = _pt()
    if pt.fallback_point_parcel(raw):
        return True
    return bool(overshared) and pt.parcel_ref(state, county, parcel_id) in overshared


class Identity(NamedTuple):
    """What a row (or an already-merged group) can PROVE about which property it is."""
    hn: str                    # real house number; '' = no address, no leading number, or a sentinel
    pk: Optional[str] = None   # 'ST|parcel' of a validated parcel; None when absent / invalid /
                               # resolver-derived
    cty: str = ""              # the county that parcel was given under (lowercased)
    sp: frozenset = frozenset()  # {(parcel_ref, source)}: parcel ids a SOURCE published for the
                               # row or group, however short (source_parcel()); a group keeps all


#: Evidence that made two rows candidates. Only ADDRESS evidence needs a real house number.
ADDRESS, PARCEL, CASE, URL = "address", "parcel", "case", "url"
_KEY_EVIDENCE = {"addr": ADDRESS, "parcel": PARCEL, "case": CASE, "url": URL}
_SIG_EVIDENCE = {"a": ADDRESS, "s": ADDRESS, "p": PARCEL, "c": CASE}


def key_evidence(key: str) -> str:
    """Evidence behind a dedupe_key() ('parcel:..', 'addr:..', 'case:..', 'url:..')."""
    return _KEY_EVIDENCE.get(str(key).split(":", 1)[0], ADDRESS)


def sig_evidence(sig: tuple) -> str:
    """Evidence behind a _strong_sigs() signature, or a ('k', dedupe_key) one."""
    if sig and sig[0] == "k":
        return key_evidence(sig[1])
    return _SIG_EVIDENCE.get(sig[0] if sig else "", ADDRESS)


def source_parcel(state, county, parcel_id, raw, source,
                  overshared: frozenset = frozenset()) -> frozenset:
    """{(parcel_ref, source)} for the parcel id the row's own SOURCE published, or an empty set.

    A short id (placeholder_twins.MIN_PARCEL_LEN) is too weak to say two rows are the SAME property
    (validation.py nulls it as not unique), but two different ids from ONE source's roll are two
    entries of that roll. The id must not be a resolver's (raw['parcel_from_geo'] /
    ['parcel_from_address']), over-shared, one repeated character or a recorded-document
    pattern, and needs MIN_SOURCE_PARCEL_LEN normalized characters."""
    if not source or parcel_id is None:
        return frozenset()
    pt = _pt()
    if pt.resolver_parcel(raw):
        return frozenset()
    ref = pt.parcel_ref(state, county, parcel_id)
    if ref is None:
        return frozenset()
    p = ref.rsplit("|", 1)[1]
    if (len(p) < MIN_SOURCE_PARCEL_LEN or len(set(p)) == 1
            or any(pat.match(str(parcel_id).strip()) for pat in _PARCEL_BAD_PATTERNS)
            or (overshared and ref in overshared)):
        return frozenset()
    return frozenset({(ref, str(source))})


def nulled_source_parcel(parcel_id, raw, source) -> Optional[str]:
    """The id a row's SOURCE published as parcel_id when validation nulled it as too short: raw
    ['parcel_id_nulled'] (validation.py, 2026-10-06), else the source's own raw block for a row
    published before that field (board_persist._SOURCE_PARCEL_FIELDS, the one table of where each
    such source keeps it). None when the row carries a parcel id or no id was nulled."""
    if parcel_id not in (None, ""):
        return None
    raw = raw if isinstance(raw, dict) else {}
    pid = None
    nulled = raw.get("parcel_id_nulled")
    if isinstance(nulled, dict) and nulled.get("reason") == "too_short":
        pid = nulled.get("value")
    if not pid:
        spec = _source_parcel_fields().get(str(source or ""))
        blk = raw.get(spec[0]) if spec else None
        if isinstance(blk, dict):
            pid = blk.get(spec[1])
    return str(pid or "").strip() or None


_SPF: Optional[dict] = None


def _source_parcel_fields() -> dict:
    """board_persist._SOURCE_PARCEL_FIELDS, read on first use (board_persist imports this module)."""
    global _SPF
    if _SPF is None:
        try:
            from .board_persist import _SOURCE_PARCEL_FIELDS
            _SPF = dict(_SOURCE_PARCEL_FIELDS)
        except Exception:  # noqa: BLE001 - without the table only raw['parcel_id_nulled'] is read
            _SPF = {}
    return _SPF


def _get(row, name):
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _owner_key(v) -> str:
    return "".join(ch for ch in str(v or "").casefold() if ch.isalnum())


def url_key_conflict(a, b) -> Optional[str]:
    """Why two rows that share only their source URL (Listing.dedupe_key's url branch) are two
    records, or None. A Listing or a board row dict on either side. 'url_county': two different
    counties; 'url_owner': two different owner names. A county roll's URL is the source_url of every
    row of the roll, so URL evidence is the same record only when nothing on the rows says otherwise
    (see 'roll URL keys' above). Different ids of one source are identity_conflict()'s, not this."""
    ca = str(_get(a, "county") or "").strip().lower()
    cb = str(_get(b, "county") or "").strip().lower()
    if ca and cb and not _same_county(ca, cb):
        return "url_county"
    oa, ob = _owner_key(_get(a, "owner_name")), _owner_key(_get(b, "owner_name"))
    if oa and ob and oa != ob:
        return "url_owner"
    return None


#: The as-scraped fields that tell two records of one URL apart (with the owner, the source id and
#: the point): the same record scraped twice agrees on all of them. verification.core._fingerprint
#: reads the same fields (less the URL, which is the key here).
_URL_RECORD_FIELDS = ("source", "listing_type", "city", "state", "zip_code", "county", "plaintiff",
                      "defendant", "trustee", "sale_date", "sale_time", "sale_location",
                      "opening_bid", "judgment_amount", "legal_description")


def url_bucket_key(key: str, li) -> str:
    """dedupe()'s pass-1 bucket for a row keyed by its URL alone: the URL key plus everything else
    the row says about which record it is (_URL_RECORD_FIELDS, the owner, the source id: its parcel
    id, else the id validation nulled; and its point to 4 decimals). Only the same record scraped
    twice shares a bucket: on the 10/7 board 25,578 rows had nothing but a URL, 10,010 of them one
    PTS Cloud URL, and city / ZIP / owner / point are all that tell those apart (2,127 UST incidents
    share one DEQ URL, many under one chain's owner name; 76 Spartanburg cleanup cases share the
    county home page with no owner). key_evidence() of the result is still URL."""
    pid = _get(li, "parcel_id") or nulled_source_parcel(None, _get(li, "raw"), _get(li, "source")) or ""
    owner = _owner_key(_get(li, "owner_name"))
    if not owner and not pid:
        # nothing names the record (76 such cleanup cases, 12 at one fallback point): alone,
        # like the 'nokey' rows above, never merged on a URL
        return f"{key}\x01nokey\x01{id(li)}"
    parts = [key, owner, _owner_key(pid)]
    for f in _URL_RECORD_FIELDS:
        v = _get(li, f)
        v = getattr(v, "value", v)
        parts.append(str(v if v is not None else "").strip().lower())
    for f in ("latitude", "longitude"):
        v = _get(li, f)
        parts.append(f"{v:.4f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else "")
    return "\x01".join(parts)


def identity_of(state, county, parcel_id, street_address, raw,
                overshared: frozenset = frozenset(), source=None) -> Identity:
    """Validity is placeholder_twins.parcel_key()'s (which also needs a known county). An address
    written from a parcel that is no match key (no_key_parcel()) gives no house number. A row whose
    short id validation nulled still names it for the source-parcel rule (nulled_source_parcel())."""
    pt = _pt()
    hn = pt.real_house_no(street_address)
    if hn and pt.situs_from_parcel(raw) and no_key_parcel(state, county, parcel_id, raw, overshared):
        hn = ""
    sp = source_parcel(state, county, parcel_id, raw, source, overshared)
    if not sp:
        npid = nulled_source_parcel(parcel_id, raw, source)
        if npid:
            sp = source_parcel(state, county, npid, raw, source, overshared)
    if pt.resolver_parcel(raw):
        return Identity(hn)
    k = pt.parcel_key(state, county, parcel_id, overshared)
    if k is None:
        return Identity(hn, sp=sp)
    st, rest = k.split("|", 1)
    cty, parcel = rest.rsplit("|", 1)
    return Identity(hn, f"{st}|{parcel}", cty, sp)


def _same_county(a: str, b: str) -> bool:
    """One county written two ways: the board carries 'Rutherford' / 'Rutherfordton' for one
    parcel (test_digitless_parcel_guard). Two counties are not: an Oconee heir parcel and a Berkeley
    tax bill both carry 097-00-02-002."""
    return a == b or a.startswith(b) or b.startswith(a)


def identity(li, overshared: frozenset = frozenset()) -> Identity:
    """Identity of a Listing or of a board row dict. `overshared`: overshared_parcels() of the rows
    being compared (dedupe() passes its own). Without it no parcel counts as over-shared;
    board_persist uses this only to REFUSE a fold across two valid parcels, which an over-shared
    parcel can then only do more often."""
    if isinstance(li, dict):
        return identity_of(li.get("state"), li.get("county"), li.get("parcel_id"),
                           li.get("street_address"), li.get("raw"), overshared, li.get("source"))
    return identity_of(li.state, li.county, li.parcel_id, li.street_address, li.raw, overshared,
                       li.source)


def _union(x: Identity, y: Identity) -> Identity:
    p = x if x.pk else y
    return Identity(x.hn or y.hn, p.pk, p.cty, x.sp | y.sp)


def different_valid_parcels(x: Identity, y: Identity) -> bool:
    """Both carry a valid parcel and they are not the same parcel."""
    return bool(x.pk and y.pk and (x.pk != y.pk or not _same_county(x.cty, y.cty)))


def different_source_parcels(x: Identity, y: Identity) -> bool:
    """Some source published a parcel id for one side and a DIFFERENT id, in the same county, for
    the other: two entries of one source's roll are two properties, however short the ids."""
    for rx, sx in x.sp:
        stx, ctx, px = rx.split("|", 2)
        for ry, sy in y.sp:
            if sx != sy:
                continue
            sty, cty, py = ry.split("|", 2)
            if stx == sty and px != py and _same_county(ctx, cty):
                return True
    return False


def identity_conflict(x: Identity, y: Identity, evidence: str = ADDRESS) -> Optional[str]:
    """Why two rows (or merged groups) must NOT be merged, or None when they may be.

    'house_number': two different real house numbers. 'parcel': two different valid parcels, or two
    different parcel ids of one source in one county (different_source_parcels()).
    'unnumbered': one side has no real house number and the valid parcels do not agree (or, on
    address evidence, neither side has one and the valid parcels do not agree)."""
    if x.hn and y.hn and x.hn != y.hn:
        return "house_number"
    if x.sp and y.sp and different_source_parcels(x, y):
        return "parcel"
    if x.pk and y.pk:
        return "parcel" if different_valid_parcels(x, y) else None
    if x.hn != y.hn:                       # exactly one side carries a real house number
        return "unnumbered"
    if evidence == ADDRESS and not x.hn:   # neither does, and only the address says "same"
        return "unnumbered"
    return None


def _merge(a: Listing, b: Listing) -> Listing:
    """merge_rows(), and an unnumbered merged row takes the numbered member's address (the
    merge was allowed only because their valid parcels agree). An AGED member's number counts
    only when the county wrote it (placeholder_twins.county_situs): on the 10/5 board most numbers
    on aged copies of unnumbered parcels were the owner's mailing address (placeholder_twins'
    ADDRESS RULE), and a live member that has no number must not take one of those, neither over
    its sentinel nor into its empty address (Listing.merge() backfills that)."""
    out = merge_rows(a, b)
    pt = _pt()
    if is_aged(a) != is_aged(b):
        live, aged = (b, a) if is_aged(a) else (a, b)
        if (pt.real_house_no(aged.street_address) and not pt.real_house_no(live.street_address)
                and not pt.county_situs(aged)):
            out.street_address = live.street_address
            return out
    if not pt.real_house_no(out.street_address):
        for li in (a, b):
            if pt.real_house_no(li.street_address):
                out.street_address = li.street_address
                break
    return out


def is_aged(li) -> bool:
    """A carried-forward row the run AGED: merge_prior_board() (or enrich_with_pulled_sales())
    kept it because the scrape did NOT see it, and tagged raw['pulled_sale']. Every other row in
    the run's list (fresh, matched, or created by an enricher) was seen this run."""
    raw = getattr(li, "raw", None)
    return isinstance(raw, dict) and bool(raw.get("pulled_sale"))


def drop_withdrawn_tags(merged: Listing, *, keep_stale_case: bool = False) -> None:
    """A row this run saw cannot be presumed withdrawn. After a live row absorbed aged copies,
    drop what Listing.merge() carried over from them: the pulled_sale miss counter, the
    'presumed_withdrawn' status _age() wrote, and board_quality's derived raw['stale_case'] flag
    (kept only when the live row carried it itself). merge_prior_board() clears the first two
    on a matched row the same way."""
    raw = merged.raw if isinstance(merged.raw, dict) else {}
    if raw.pop("pulled_sale", None) is not None and merged.auction_status == "presumed_withdrawn":
        merged.auction_status = None
    if not keep_stale_case:
        raw.pop("stale_case", None)
    merged.raw = raw


def merge_rows(a: Listing, b: Listing) -> Listing:
    """``a.merge(b)``, except across a live row and an aged one (is_aged()): the LIVE row is the
    base and the result is not presumed withdrawn (drop_withdrawn_tags()). That is exactly
    merge_prior_board()'s fresh.merge(prior): the live row's top-level fields win and the aged
    copy backfills the empty ones; inside raw, Listing.merge() lets the aged copy win leaf
    collisions (how prior enrichment is carried), and the tags are then dropped.

    Why (2026-10-05). main.run()'s second dedupe() runs over merge_prior_board()'s output, which
    holds this run's rows AND the prior rows it aged, and since the 2026-10-04 streaming rewrite
    the aged rows come FIRST. Every pass of dedupe() keeps the earlier row as the merge base, so a
    live row that met an aged row there took the aged row's parcel, address, owner, source and
    status, and Listing.merge()'s raw deep-merge carried raw['pulled_sale'] onto it in either
    order. board_quality then demoted a lead the run had just scraped. merge_prior_board() itself
    merges fresh-first and clears the tag; this keeps dedupe() to the same rule. Two live rows,
    or two aged rows, merge exactly as before."""
    a_aged, b_aged = is_aged(a), is_aged(b)
    if a_aged == b_aged:
        return a.merge(b)
    live, aged = (b, a) if a_aged else (a, b)
    out = live.merge(aged)
    live_raw = live.raw if isinstance(live.raw, dict) else {}
    drop_withdrawn_tags(out, keep_stale_case=bool(live_raw.get("stale_case")))
    return out


def addresses_per_dedupe_key(listings) -> dict[str, set]:
    """dedupe_key() -> the set of distinct normalized street addresses that key covers.

    Pulled out of dedupe() (2026-09-22) so the same "how many real properties does this
    key actually cover" computation used to detect a fused parcel id is available to
    callers that never run dedupe() itself -- the scorer's parcel grouping and the
    parcel-cache join both trust dedupe_key()'s parcel branch the same way dedupe() does,
    and both need to know when it is lying before they act on it."""
    out: dict[str, set] = {}
    for li in listings:
        a = _norm_addr(li.street_address)
        if a:
            out.setdefault(li.dedupe_key(), set()).add(a)
    return out


def suspicious_parcel_keys(listings, min_addresses: int = 4) -> frozenset[str]:
    """dedupe_key()s whose PARCEL branch is shared by min_addresses or more distinct real
    addresses -- the same threshold and computation dedupe.suspicious_primary_key logs.

    A key this broad is not describing one property. The liensnc lien-agent-appointment
    source is the repeat offender: a subdivision's lots share one master-tract PIN until
    the county assigns individual PINs, so a filing batch can cite the SAME PIN for
    dozens to hundreds of different houses (audit 2026-09-22: Pender County parcel
    3208-90-5620-0000 covered 216 distinct addresses in one run). dedupe()'s
    house_number_guard already stops that from deleting rows during a MERGE; this lets
    the scorer's per-parcel grouping and the parcel-cache join refuse to trust the key
    too, instead of silently stacking 216 unrelated properties' signals together or
    copying one property's owner and value onto the other 215."""
    per_key = addresses_per_dedupe_key(listings)
    return frozenset(k for k, addrs in per_key.items()
                      if k.startswith("parcel:") and len(addrs) >= min_addresses)


def dedupe(listings: list[Listing]) -> list[Listing]:
    """Merge listings that point to the same property.

    Strategy:
    1. Bucket by primary dedupe_key (parcel/address/case)
    2. Within each bucket, merge using Listing.merge
    3. Cross-bucket fuzzy address match for stragglers

    Every merge goes through merge_rows(): when a live row meets a row the run aged (raw
    ['pulled_sale']), the live row is the base and the result is not presumed withdrawn,
    whatever order the two arrived in.

    Every candidate merge is checked with identity_conflict() against the WHOLE group merged so
    far (see the block comment above it): two different real house numbers or two different
    valid parcels never merge, and a row with no real house number needs agreeing valid parcels.
    A refused row stays its own row; nothing is dropped.

    A parcel id the input puts on several different numbered streets, or one a resolver attached
    at a geocoder fallback point, neither proves identity nor brings rows together, and an address
    written from such a parcel is not a house number (see the 'shared parcels' block comment).
    """
    if not listings:
        return []
    # Parcel-id aliases (parcel_alias.py, 2026-10-07): a row whose parcel_id is a county's SHORT
    # id takes the PIN an alias source (Lincoln PARCELID, Rutherford Parcel_Number) published for
    # the same property in this batch, so rows of other sources still meet it on the parcel.
    from . import parcel_alias as _pa
    _pa.apply(listings, _pa.build(listings))
    if not listings:
        return []

    overshared = overshared_parcels(listings)
    if overshared:
        log.info("dedupe.overshared_parcels", parcels=len(overshared),
                 sample=sorted(overshared)[:10],
                 note=f"parcel ids on {OVERSHARED_MIN_STREETS}+ different numbered streets: no "
                      "identity evidence and no match key")

    def ident(li) -> Identity:
        return identity(li, overshared)

    blocked: Counter = Counter()          # (pass, reason) -> merges refused

    buckets: dict[str, Listing] = {}
    # Identity of each bucket that has absorbed a row (a single row's is read off the row).
    # Holds one small tuple per MERGE, never one per row.
    bucket_ids: dict[str, Identity] = {}
    # Track the DISTINCT street addresses absorbed by each primary key. This is
    # pass 1, where the bulk of merging happens -- and where a bad parcel_id does
    # its damage, because dedupe_key's parcel branch trusts the value with no
    # sanity check. Measured: `scrape_liensnc.py`'s PIN_RE
    # (`(?:pin|tms|parcel|tax\s*map)` IGNORECASE, no word boundary) captured
    # 'ehurst' from "Pinehurst" and 'number' from "PIN number:", so 122 distinct
    # Pinehurst properties shared one key and collapsed into a single row. The run
    # logged nothing. Now it does.
    _addrs_per_key = addresses_per_dedupe_key(listings)
    rekeyed = 0
    for li in listings:
        k = li.dedupe_key()
        if k.startswith("parcel:") and no_key_parcel(li.state, li.county, li.parcel_id, li.raw,
                                                     overshared):
            # keyed as if it had no parcel id: address or case number. Not by URL: one county
            # roll's PDF is the source_url of thousands of rows, and a row that has neither an
            # address nor a case is better alone than in that bucket.
            k = li.model_copy(update={"parcel_id": None}).dedupe_key()
            if k.startswith("url:"):
                k = f"nokey:{len(buckets)}:{id(li)}"
            rekeyed += 1
        if k.startswith("url:"):
            # One bucket per (county, owner, source id) under a shared URL: rows that
            # url_key_conflict() or the source-parcel rule would refuse never meet, so a roll of
            # 10,010 address-less rows (PTS Cloud on the 10/7 board) does not walk a bucket chain.
            k = url_bucket_key(k, li)
        if k not in buckets:
            buckets[k] = li
            continue
        # Same primary key. A refused row is NOT dropped: it goes on to the next bucket under
        # this key ('<key>\x002', '\x003', ...; no real key contains NUL) it does not conflict
        # with, or opens a new one. (The old guard parked it under '<key>#hn<number>', and a
        # second row with that number OVERWROTE the first one there, deleting it.)
        ev = key_evidence(k)
        li_id = ident(li)
        kk, n = k, 1
        while kk in buckets:
            b_id = bucket_ids.get(kk) or ident(buckets[kk])
            why = identity_conflict(b_id, li_id, ev)
            if why is None and ev == URL:
                # a roll URL is shared by every row of the roll: same county and owner, or two
                # records (see 'roll URL keys' above)
                why = url_key_conflict(buckets[kk], li)
            if why is None:
                buckets[kk] = _merge(buckets[kk], li)
                bucket_ids[kk] = _union(b_id, li_id)
                break
            if kk == k:
                blocked[(1, why)] += 1
            n += 1
            kk = f"{k}\x00{n}"
        else:
            buckets[kk] = li

    if rekeyed:
        log.info("dedupe.parcel_not_a_key", rows=rekeyed,
                 note="parcel over-shared or attached at a geocoder fallback point: row keyed by "
                      "its address or case number instead")
    _p1 = {r: c for (p, r), c in blocked.items() if p == 1}
    if _p1:
        log.info("dedupe.house_number_guard_pass1", blocked_merges=sum(_p1.values()),
                 reasons=_p1,
                 note="rows sharing a primary key that are provably different properties "
                      "(different house numbers or parcels, or an unnumbered row without "
                      "an agreeing valid parcel); merging would have deleted one of them")

    _fused = [(len(v), k) for k, v in _addrs_per_key.items() if len(v) >= 4]
    if _fused:
        _fused.sort(reverse=True)
        log.warning("dedupe.suspicious_primary_key",
                    keys=len(_fused),
                    addresses_fused=sum(n - 1 for n, _ in _fused),
                    worst=[{"key": k, "distinct_addresses": n} for n, k in _fused[:10]])

    merged = list(buckets.values())
    merged_ids: list[Optional[Identity]] = [bucket_ids.get(k) for k in buckets]
    del buckets, bucket_ids

    # Pass 2: fuzzy address merge — across listings that have addresses.
    # Original required zip on both sides; now also matches when both have
    # same county+state (catches the 73 cross-source dups where one source
    # had zip and the other didn't).
    #
    # BLOCKING OPTIMIZATION (2026-08-27): Pre-index by zip and (county, state)
    # so we only compare listings within the same geographic block. This cuts
    # O(n²) on 116K listings (6.7B comparisons) down to ~67M — 100x faster.
    # Without this, merge_prior_board on 94K+22K hangs for hours and the
    # try/except in main.py silently swallows the failure, dropping 72K leads.
    #
    # Each index list is in ascending order, so "every j > i" is a bisect + slice rather than a
    # Python-level filter over the whole block; and each row's normalized address is computed
    # once (merged[j] is never modified before its own turn), not once per candidate pair.
    # Same candidates, same order, same scores: only faster, which matters because the
    # identity rule leaves more rows unconsumed to run their own candidate loops.
    norm_addrs = [_norm_addr(li.street_address) for li in merged]
    # Each row's validated parcel ('ST|parcel', or None). Two rows whose parcels differ can never
    # merge (identity_conflict), so such a pair is skipped before the fuzzy score: without this,
    # every lot of a county's vacant roll (21,767 Gaston rows, each its own parcel) scores against
    # every other one, now that they are no longer folded away. Same merges as scoring them; only
    # the refusal counts logged below no longer include these pairs.
    row_pks = [(merged_ids[j] or ident(merged[j])).pk for j in range(len(merged))]
    by_zip: dict[str, list[int]] = {}
    by_locale: dict[tuple, list[int]] = {}
    for idx, li in enumerate(merged):
        z = (li.zip_code or "").strip()[:5]
        if z:
            by_zip.setdefault(z, []).append(idx)
        cty = (li.county or "").strip().lower()
        st = (li.state or "").strip().lower()
        if cty and st:
            by_locale.setdefault((cty, st), []).append(idx)

    final: list[Listing] = []
    final_ids: list[Optional[Identity]] = []
    consumed: set[int] = set()
    for i, a in enumerate(merged):
        if i in consumed:
            continue
        addr_a = norm_addrs[i]
        if not addr_a:
            final.append(a)
            final_ids.append(merged_ids[i])
            continue
        a_id = merged_ids[i]
        a_merged = a_id is not None
        a_pk = row_pks[i]
        county_a = (a.county or "").strip().lower()
        state_a = (a.state or "").strip().lower()
        zip_a = (a.zip_code or "").strip()[:5]

        # Build candidate set from blocking indexes — NOT all j > i
        candidates: set[int] = set()
        if zip_a and zip_a in by_zip:
            blk = by_zip[zip_a]
            candidates.update(blk[bisect_right(blk, i):])
        locale_key = (county_a, state_a)
        if county_a and state_a and locale_key in by_locale:
            blk = by_locale[locale_key]
            candidates.update(blk[bisect_right(blk, i):])

        for j in candidates:
            if j in consumed:
                continue
            pj = row_pks[j]
            if pj is not None and a_pk is not None and pj != a_pk:
                continue
            b = merged[j]
            if not b.street_address:
                continue
            # Must be same county+state OR same zip (guaranteed by blocking,
            # but keep the check for safety on edge cases)
            zip_b = (b.zip_code or "").strip()[:5]
            county_b = (b.county or "").strip().lower()
            state_b = (b.state or "").strip().lower()
            same_zip = zip_a and zip_b and zip_a == zip_b
            same_locale = (county_a == county_b and state_a == state_b
                           and county_a and state_a)
            if not (same_zip or same_locale):
                continue
            score = fuzz.token_set_ratio(addr_a, norm_addrs[j])
            if score >= 92:
                # A fuzzy score is ADDRESS evidence only, and it is where the damage was done:
                # '306 Fountain Way' vs '346 Fountain Way' score ~97, '0 SOUTHPORT RD' vs
                # '0 SOUTHPORT RD' (two lots) and 'LOOKOUT RD' vs '328 LOOKOUT RD' score 100.
                # Checked against everything `a` has absorbed so far, so a merged group can
                # never collect two houses one member at a time.
                #
                # The check sits AFTER the score test on purpose. Placed before it, it
                # counted every candidate pair it skipped -- 99,875,342 of them on one
                # board -- which is a true number of comparisons and a useless number to
                # log. Here it counts merges actually prevented.
                if a_id is None:
                    a_id = ident(a)
                b_id = merged_ids[j] or ident(b)
                why = identity_conflict(a_id, b_id, ADDRESS)
                if why is not None:
                    blocked[(2, why)] += 1
                    continue
                a = _merge(a, b)
                a_id = _union(a_id, b_id)
                a_pk = a_id.pk
                a_merged = True
                consumed.add(j)
        final.append(a)
        final_ids.append(a_id if a_merged else None)
    del merged, merged_ids, norm_addrs, row_pks, by_zip, by_locale, consumed

    _p2 = {r: c for (p, r), c in blocked.items() if p == 2}
    if _p2:
        log.info("dedupe.house_number_guard_pass2", blocked_merges=sum(_p2.values()),
                 reasons=_p2,
                 note="fuzzy address match refused: different house numbers or parcels, "
                      "or an unnumbered address without an agreeing valid parcel")

    # Pass 3 (2026-06-19): signature union-merge. dedupe_key is parcel>addr>case>
    # url, so the SAME property with a parcel_id on one copy and only a case# on
    # another splits into two keys and never merges (verified leak: ~19 rows).
    # Union any rows sharing a strong signature, then merge each group.
    parent = list(range(len(final)))
    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    # root -> identity of the group, for groups of 2+ rows only (union-find chains through any
    # member, so a union is checked group against group, not just row against row).
    group_ids: dict[int, Identity] = {}

    def _row_id(x: int) -> Identity:
        return final_ids[x] or ident(final[x])

    def _group_id(r: int) -> Identity:
        return group_ids.get(r) or _row_id(r)

    sigmap: dict = {}
    for i, li in enumerate(final):
        sigs = _strong_sigs(li)
        if no_key_parcel(li.state, li.county, li.parcel_id, li.raw, overshared):
            sigs = {s for s in sigs if s[0] != "p"}
        for s in sigs:
            if s in sigmap:
                j = sigmap[s]
                ri, rj = _find(i), _find(j)
                if ri == rj:
                    continue
                ev = sig_evidence(s)
                why = (identity_conflict(_row_id(i), _row_id(j), ev)
                       or identity_conflict(_group_id(ri), _group_id(rj), ev))
                if why is not None:
                    blocked[(3, why)] += 1
                    continue
                gid = _union(_group_id(ri), _group_id(rj))
                parent[rj] = ri
                group_ids.pop(rj, None)
                group_ids[ri] = gid
            else:
                sigmap[s] = i
    del group_ids
    _p3 = {r: c for (p, r), c in blocked.items() if p == 3}
    if _p3:
        log.info("dedupe.house_number_guard", blocked_merges=sum(_p3.values()), reasons=_p3,
                 note="rows sharing a signature that are provably different properties "
                      "(different house numbers or parcels, or an unnumbered row without "
                      "an agreeing valid parcel); a merge here would delete one of them")
    groups: dict = {}
    for i in range(len(final)):
        groups.setdefault(_find(i), []).append(i)
    out: list[Listing] = []
    # SUSPICIOUS-FUSION REPORT. A wrong signature does not fail, it silently
    # deletes properties -- which is how `scrape_liensnc.py`'s PIN_RE
    # (`(?:pin|tms|parcel|tax\s*map)` with IGNORECASE and no word boundary)
    # turned "Pinehurst" into parcel_id 'ehurst' and fused 122 distinct
    # Pinehurst properties into one row, plus 'eville' (130), 'number' (247).
    # Nothing in any log said so. Union groups that swallow many DISTINCT
    # street addresses are the signature of that class of bug, so they are now
    # reported at WARNING with the shared key named.
    _suspicious: list[tuple[int, int, str]] = []
    for idxs in groups.values():
        m = final[idxs[0]]
        for j in idxs[1:]:
            m = _merge(m, final[j])
        out.append(m)
        if len(idxs) >= 5:
            addrs = {_norm_addr(final[j].street_address) for j in idxs}
            addrs.discard("")
            # Same property from many sources is normal and fine. Many DIFFERENT
            # street addresses under one signature is not.
            if len(addrs) >= 4:
                shared = [s for s, first in sigmap.items()
                          if _find(first) == _find(idxs[0])]
                key = str(sorted(shared, key=lambda x: (x[0], str(x)))[:2])
                _suspicious.append((len(idxs), len(addrs), key))
    if _suspicious:
        _suspicious.sort(reverse=True)
        log.warning("dedupe.suspicious_fusion",
                    groups=len(_suspicious),
                    rows_fused=sum(n - 1 for n, _, _ in _suspicious),
                    worst=[{"rows": n, "distinct_addresses": a, "shared_signature": k}
                           for n, a, k in _suspicious[:10]])
    return out
