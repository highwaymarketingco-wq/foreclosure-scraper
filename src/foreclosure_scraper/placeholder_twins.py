"""Placeholder twins: one source's row for a parcel, written twice because its house number was
a "no number" sentinel.

THE DEFECT (measured 2026-10-05 on the 10/5 VM run, ~380 new duplicate groups)
    Several county rolls publish a vacant or unnumbered lot with a sentinel house number:
    Spartanburg's vacant registry and condemned layer and Rutherford's delinquent-tax roll write
    "0 PATCH DR SPARTANBURG", Buncombe's lien advertisement writes "99999 GREEN TREE LN". The
    published board never shows that string (web_artifact._to_dict nulls a sentinel situs), and
    the operator backfill scripts/fill_address_from_parcel.py later wrote the parcel cache's real
    numbered situs onto those published rows ("499 PATCH DR SPARTANBURG",
    raw['situs_address_source'] = 'parcel_cache:exact').

    The next full run scrapes the same row again, still "0 PATCH DR". Same source, same parcel
    id, same dedupe_key(). But the house-number guard (dedupe._provably_different_property and
    board_persist._provably_different_dict) reads "0" as a real house number, sees 0 != 499, and
    refuses the merge, so the prior copy is kept as a separate prior-only row and the board
    carries the parcel twice. Real pairs from that run (fresh scrape vs published board):

        714252203123  spartanburg_vacant      '0 PATCH DR SPARTANBURG'  vs '499 PATCH DR SPARTANBURG'
        7037-51-0954.56 spartanburg_condemned '0 BLACKSTOCK RD PAULINE' vs '1312 BLACKSTOCK RD PAULINE'
        967806998600000 buncombe_delinquent_tax '99999 GREEN TREE LN'   vs '8 GREEN TREE LN'
        1647690       rutherford_tax          '0 COBB RD'               vs '212 COBB RD'

    This is NOT the 2026-10-04 streaming rewrite of merge_prior_board(): replaying the real
    fixture through the pre-rewrite load_board() + dedupe(fresh + prior) path leaves the same
    pairs split (dedupe()'s pass-1 and pass-3 guards fire on 0 vs 499 exactly the same way).
    What changed between the 9/22 and 10/5 runs is the backfill that gave the prior rows a
    numbered address.

THE RULE (one rule, used by both callers below)
    Two rows are placeholder twins when ALL of these hold:
      * the same VALID parcel key: same state, same county, the same normalized parcel id
        (models._normalize_parcel) of at least MIN_PARCEL_LEN characters that is not one
        repeated character ("0000000", "9999999999999") and not one of validation.py's
        recorded-document patterns. A digitless "parcel" is already rejected by
        _normalize_parcel (the PIN_RE 'ehurst' class);
      * a shared source (primary source or raw['also_seen_in']): one county roll's own record of
        its own parcel, not two sources that disagree about which parcel a property is;
      * the house numbers do not PROVABLY differ: at most one REAL house number between them,
        where a sentinel ("0", "00", "9999", "99999") or no number is not a real one;
      * neither carries a unit/apt/lot designator (models._UNIT_RE), so units of a multi-unit
        building that share a parcel are never collapsed by this rule;
      * neither row's parcel was derived by a resolver (raw['parcel_from_geo'] /
        raw['parcel_from_address']) instead of coming from a source.
    Plus a uniqueness bound per caller (one fresh row for the key; at most one distinct real
    house number in the whole group; MAX_GROUP_ROWS), so a fused or placeholder parcel id that a
    subdivision's lots all share can never pull several properties into one.

WHO USES IT
    * board_persist.merge_prior_board(): the streaming merge falls back to this rule when the
      strict match was refused by the house-number guard (future runs).
    * scripts/resume_from_checkpoint.py --collapse-dry-run / RESUME_COLLAPSE_PLACEHOLDER_TWINS:
      a one-off, opt-in collapse of the twins already in the 10/5 run's pre_publish checkpoint,
      planned here by plan_collapse() and applied by apply_collapse(). With --seen-since /
      RESUME_SEEN_SINCE the same plan, digest and apply also remove the presumed-withdrawn tag
      that dedupe2 put on rows this run saw (repair_reseen(); see the block comment there).

The two callers merge differently:
  * merge_prior_board() (future runs) uses fold(): Listing.merge() with the re-scraped (fresh)
    row as the base, so fresh wins on conflicting fields and the old row backfills missing ones
    (merge_prior_board's rule for every matched prior row); fold() then keeps the old row's
    numbered situs over the fresh row's sentinel string, BUT ONLY WHEN THAT NUMBER CAME FROM THE
    COUNTY (county_situs()).
  * the one-off collapse (apply_collapse()) uses absorb_copies(): the live row is the published
    row, and an aged copy gives it ONLY what COPY_ALLOWLIST names (the county situs number and
    its provenance, and the earlier first_seen when the owners match). See the block comment
    above COPY_ALLOWLIST for why nothing else on these copies can be trusted.

ADDRESS RULE (2026-10-06, measured on all 325 groups of the 10/5 pre_publish plan against the
parcel cache, the county's own situs and owner-mailing record):
    The twins are real duplicates (same valid parcel, shared source), but the old copy's NUMBERED
    address was the county situs in only 69 groups, every one stamped
    raw['situs_address_source'] = 'parcel_cache:exact'. In 208 it is the owner's MAILING address
    (713272200834 '0 EMERALD CT' vs '100 MISTYBROOK DR'; 710297267572: county situs 'CONVAIR DR',
    old copy '717 TABERNACLE LN' = owner mailing '717 TABERNACLE LN LYMAN SC'), in 25 another
    street with no county support, in 18 the county says the parcel has no number at all, and 5
    are a reverse geocode ('10, Reynolds Lane, Weaverville, ...'), a map reference
    ('24 M 144   0 Barkley Dr') or a legal description ('1244 HIGHLANDS 2802252'). None of those
    256 carries the parcel_cache provenance (182 carry raw['situs_road_only']: the county itself
    said the parcel has no house number). So the old copy's number replaces a sentinel only when
    county_situs() vouches for it; otherwise the merged row keeps the live row's own address.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Optional

from .dedupe import _house_no_of, drop_withdrawn_tags
from .models import Listing, _UNIT_RE, _normalize_parcel
from .validation import _PARCEL_BAD_PATTERNS
from .web_artifact import _PLACEHOLDER_HOUSE_NUM_RE, _identity_keys, _to_dict

#: validation.py nulls a parcel id under 7 characters as too short to be unique; same floor.
MIN_PARCEL_LEN = 7

#: Largest group (live row + its old copies) the cleanup will collapse. Same number as
#: board_selfcheck.FUSION_THRESHOLD / dedupe.suspicious_parcel_keys: 4+ rows under one parcel is
#: the shape of a fused or placeholder id, not of one property landed twice.
MAX_GROUP_ROWS = 4

#: raw keys that mark a parcel id a resolver attached, rather than one the source published.
RESOLVER_PARCEL_KEYS = ("parcel_from_geo", "parcel_from_address")

#: raw['situs_address_source'] values that mean the street address was written from the county's
#: own parcel record (scripts/fill_address_from_parcel.py via the parcel cache). See the module
#: docstring's ADDRESS RULE for why nothing else qualifies ('gis_parcel_situs' wrote 47 owner
#: mailing addresses among the 10/5 twins).
COUNTY_SITUS_PREFIXES = ("parcel_cache:",)


# ------------------------------------------------------------------------------ field rules
def is_sentinel_address(addr: Any) -> bool:
    """True for a "no house number assigned" sentinel situs ("0 PATCH DR", "99999 GREEN TREE
    LN"): web_artifact._PLACEHOLDER_HOUSE_NUM_RE, the same pattern _to_dict uses to null them."""
    return isinstance(addr, str) and bool(_PLACEHOLDER_HOUSE_NUM_RE.match(addr.strip()))


def real_house_no(addr: Any) -> str:
    """The leading house number of ``addr`` when it is a REAL one, without leading zeros
    ("000141 LEVI DR" -> "141"); "" for no address, no leading number, or a sentinel."""
    if not isinstance(addr, str) or is_sentinel_address(addr):
        return ""
    return _house_no_of(addr).lstrip("0")


def has_unit(addr: Any) -> bool:
    return isinstance(addr, str) and bool(_UNIT_RE.search(addr.strip()))


def parcel_key(state: Any, county: Any, parcel_id: Any) -> Optional[str]:
    """"ST|county|normalized-parcel" for a parcel id this rule may trust, else None."""
    if parcel_id is None:
        return None
    raw_pid = str(parcel_id).strip()
    p = _normalize_parcel(raw_pid)
    if len(p) < MIN_PARCEL_LEN or len(set(p)) == 1:
        return None
    if any(pat.match(raw_pid) for pat in _PARCEL_BAD_PATTERNS):
        return None
    st = str(state or "").strip().upper()
    cty = str(county or "").strip().lower()
    if not st or not cty:
        return None
    return f"{st}|{cty}|{p}"


def sources_of(source: Any, raw: Any) -> frozenset:
    out = {str(source)} if source else set()
    if isinstance(raw, dict):
        for d in raw.get("also_seen_in") or []:
            if isinstance(d, dict) and d.get("source"):
                out.add(str(d["source"]))
    return frozenset(out)


def resolver_parcel(raw: Any) -> bool:
    return isinstance(raw, dict) and any(raw.get(k) for k in RESOLVER_PARCEL_KEYS)


def county_situs(row: Any) -> bool:
    """``row``'s street address was written from the county's own parcel record (see the module
    docstring's ADDRESS RULE). The only old-copy house number another row may take."""
    src = _raw(row).get("situs_address_source")
    return isinstance(src, str) and src.startswith(COUNTY_SITUS_PREFIXES)


def _get(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _raw(row: Any) -> dict:
    r = _get(row, "raw")
    return r if isinstance(r, dict) else {}


def twin_house_numbers_ok(addr_a: Any, addr_b: Any) -> bool:
    """The house numbers do not provably differ: at most one real number between the two."""
    a, b = real_house_no(addr_a), real_house_no(addr_b)
    return not (a and b and a != b)


def twin_pair_ok(a: Any, b: Any) -> bool:
    """The pairwise half of the rule (see the module docstring), for two rows (dicts or
    Listings). The group-level bounds are the caller's."""
    ka = parcel_key(_get(a, "state"), _get(a, "county"), _get(a, "parcel_id"))
    if ka is None or ka != parcel_key(_get(b, "state"), _get(b, "county"), _get(b, "parcel_id")):
        return False
    ra, rb = _raw(a), _raw(b)
    if not (sources_of(_get(a, "source"), ra) & sources_of(_get(b, "source"), rb)):
        return False
    sa, sb = _get(a, "street_address"), _get(b, "street_address")
    if has_unit(sa) or has_unit(sb):
        return False
    if resolver_parcel(ra) or resolver_parcel(rb):
        return False
    return twin_house_numbers_ok(sa, sb)


def fold(base: Listing, other: Listing) -> Listing:
    """``base.merge(other)`` (fresh/live row first: its non-null fields win, ``other`` backfills),
    except that a base whose situs is a no-number sentinel takes ``other``'s numbered situs when
    county_situs(other) says the county wrote it. Listing.merge() would keep the sentinel (it is
    non-null), and the sentinel is exactly what _to_dict nulls on publish. Any other number on the
    old copy (an owner's mailing address, a reverse geocode, a map reference) is not taken: the
    merged row keeps the base's own address (see the module docstring's ADDRESS RULE). That
    includes a base with no address at all, which Listing.merge() would otherwise backfill with
    the old copy's number (SC|oconee|1450003017: '1244 HIGHLANDS 2802252', a legal description)."""
    merged = base.merge(other)
    base_addr = base.street_address
    if real_house_no(other.street_address) and (
            is_sentinel_address(base_addr) or not (base_addr or "").strip()):
        merged.street_address = other.street_address if county_situs(other) else base_addr
    return merged


# ------------------------------------------------------- what an aged copy may give the live row
# THE DEFECT (dress rehearsal of the 10/5 publish on the VM, 2026-10-06, real checkpoint).
# apply_collapse() used to fold each aged copy into the live row with Listing.merge() and then
# lay the live row's raw back on top: the live row won every field BOTH rows carried, and
# everything it LACKED (top-level fields, raw keys, nested leaves) came from the copy. In 208 of
# the 325 groups the copy names a DIFFERENT owner (one name, HALLIDAY Q STANFORD IV, sits on
# about 180 of those copies), so the published rows carried another person's outreach letter and
# skip-trace (245 rows; NC|rutherford|1616705: live FOSTER, TAMMIE, letter "Dear Francis," to
# WALSH, FRANCIS ROBERT), phones (10), email (1), divorce (184), deed chain (155), owner cluster
# (146), CRM (206), owner mailing (4) and the detail file's sale fields (deed ref, previous owner,
# sale amount; 9). And 9 rows published max_bid_70 / wholesale_mao / equity that the live row had
# withheld on a contradicted ARV (SC|spartanburg|713272200834: live ARV $300 flagged
# arv_land_sqft_mismatch; published max bid $121,200 from the copy's $271,600 ARV), breaking
# three board_selfcheck money rules that are 0 on the uncollapsed board.
#
# THE COPIES ARE NOT A SOURCE OF PROPERTY FACTS EITHER (measured on all 325 groups). Every
# enricher ran on the live row THIS run; a block the live row lacks is one this run did not
# produce for it, mostly because its address is a sentinel or its point a road or county
# centroid (325 of 325 live rows have no photos). The copies have those blocks because their
# address and point were another place: the owner's mailing address in 208 groups, and even
# where the owner matches, 47 of 116 copies' photos are centred more than 60 m from the live
# row's point (Buncombe: 2.8 to 20 km, e.g. live '99999 HUMMINGBIRD HL', copy '3 CARRERE CT').
# The property facts follow the wrong place: 713272200834 is a vacant HOA subdivision lot, and
# its copy says 4 beds, 3 baths, built 1956, a roof graded 'major', another building footprint
# and an aerial photo about 170 m away. The parcel-keyed blocks do not qualify either: gis,
# gis_attrs_full, lrcpwa, septic, assessor_card and cama carry an owner, a mailing address or a
# sale; vacant_lot, storm_damage, property_category, land_ratio and the top-level sqft/beds/
# baths/year/acreage/assessed values feed the score or the valuation, which the live row was
# scored without (nothing re-scores at publish), and carry no per-field provenance.
#
# THE RULE. The live row is the published row. absorb_copies() starts from a deep copy of it and
# takes from a copy ONLY what COPY_ALLOWLIST names. The publish holds the same line for the
# detail sidecar: write_artifact() must not backfill a kept row's vision/comps/cama/rent_comps
# from the prior board, whose row for that parcel IS the aged copy (it would have, through the
# parcel id the collapse makes unique, for 284 of the 325 kept rows: 243 vision reports, 282
# comps, 22 cama), and must not join another row to the prior board through a key only a
# dropped copy shared with it (apply_collapse(kept_out=...) / resume_from_checkpoint._collapse).

#: Everything absorb_copies() may take from an aged copy. An ALLOWLIST: whatever the live row
#: lacks, a field that is not named here is never taken.
COPY_ALLOWLIST = {
    "street_address": "the copy's numbered address over the live row's sentinel or empty one, "
                      "only when county_situs(copy): written from the county's own parcel record, "
                      "looked up by the parcel id the twin rule already requires to be the same "
                      "(re-checked 2026-10-06: all 69 such copies equal today's parcel cache, the "
                      "43 whose owner differs included, so the copy's owner data cannot reach it)",
    "raw.situs_address_source": "only together with that address: its provenance",
    "first_seen": "the earlier one, only when same_owner(): when this source first listed this "
                  "parcel; written by the scraper, never by an enricher",
}


def owner_tokens(name: Any) -> frozenset:
    """An owner name's identity tokens: enrichment_board_qa._name_tokens (upper case, 3+
    characters, no punctuation, suffixes, role words or digits)."""
    from .enrichment_board_qa import _name_tokens
    return frozenset(_name_tokens(name if isinstance(name, str) else ""))


def same_owner(a: Any, b: Any) -> bool:
    """Both rows name an owner and one name's identity tokens contain the other's ('ALLISON,
    WAYNE' and 'ALLISON, WAYNE L ALLISON, L MARLENE'). A missing owner, or two names that merely
    overlap ('SMITH JOHN' and 'SMITH MARY'), is not the same owner."""
    ta, tb = owner_tokens(_get(a, "owner_name")), owner_tokens(_get(b, "owner_name"))
    return bool(ta and tb and (ta <= tb or tb <= ta))


def absorb_copies(live: Listing, copies: list[Listing]) -> tuple[Listing, list[str]]:
    """The live row with its aged ``copies`` (newest first) absorbed under COPY_ALLOWLIST:
    returns (merged row, the allowlisted fields actually taken). The merged row is a deep copy of
    ``live``; neither input is changed."""
    merged = live.model_copy(deep=True)
    taken: list[str] = []
    base_addr = live.street_address
    if is_sentinel_address(base_addr) or not (base_addr or "").strip():
        for c in copies:
            if real_house_no(c.street_address) and county_situs(c):
                merged.street_address = c.street_address
                raw = merged.raw if isinstance(merged.raw, dict) else {}
                raw["situs_address_source"] = _raw(c)["situs_address_source"]
                merged.raw = raw
                taken += ["street_address", "raw.situs_address_source"]
                break
    for c in copies:
        cf, mf = parse_stamp(c.first_seen), parse_stamp(merged.first_seen)
        if same_owner(live, c) and cf is not None and mf is not None and cf < mf:
            merged.first_seen = c.first_seen
            if "first_seen" not in taken:
                taken.append("first_seen")
    unknown = set(taken) - set(COPY_ALLOWLIST)
    if unknown:     # a code change that takes more must extend the allowlist (and its reasons)
        raise AssertionError(f"absorb_copies took {sorted(unknown)} outside COPY_ALLOWLIST")
    return merged, taken


# ------------------------------------------------------------------- full-board cleanup plan
_VIEW_FIELDS = ("source", "street_address", "first_seen", "last_seen")


@dataclass
class _View:
    idx: int
    key: str
    source: str
    street_address: Optional[str]
    first_seen: str
    last_seen: str
    live: bool
    real_hn: str
    unit: bool
    resolver: bool
    sources: frozenset

    def ident(self) -> list:
        return [self.source, self.street_address, self.first_seen, self.last_seen]


def _stamp(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return v.isoformat()
    except AttributeError:
        return str(v)


def _view_fields(row: Any) -> dict:
    if isinstance(row, dict):
        return {k: row.get(k) for k in _VIEW_FIELDS}
    # The SAME serialization checkpoint.save() wrote, so a plan made by streaming the
    # checkpoint file and a plan made from the loaded Listings compare equal.
    return row.model_dump(mode="json", include=set(_VIEW_FIELDS))


def _view(idx: int, row: Any, key: str, revived: frozenset = frozenset()) -> _View:
    d = _view_fields(row)
    raw = _raw(row)
    addr = d.get("street_address")
    return _View(idx=idx, key=key, source=str(d.get("source") or ""), street_address=addr,
                 first_seen=_stamp(d.get("first_seen")), last_seen=_stamp(d.get("last_seen")),
                 live=not raw.get("pulled_sale") or idx in revived, real_hn=real_house_no(addr),
                 unit=has_unit(addr), resolver=resolver_parcel(raw),
                 sources=sources_of(d.get("source"), raw))


# --------------------------------------------- rows the run saw that dedupe2 left "withdrawn"
# THE DEFECT (2026-10-05). main.run()'s second dedupe() ran over merge_prior_board()'s output,
# aged prior-only rows first, so a live row that met an aged one there was folded INTO it:
# Listing.merge() kept the aged row's top-level fields and backfilled raw['pulled_sale'] and
# the 'presumed_withdrawn' status, and board_quality then flagged raw['stale_case'] and moved a
# HOT stack to WARM. dedupe.merge_rows() fixes future runs. These rows are still in the 10/5
# pre_publish checkpoint, and the only trace of the live row is last_seen: Listing.merge()
# keeps the LATEST last_seen, and a row created this run has last_seen >= the run's start,
# while every row the run aged kept the last_seen the prior board gave it (all older).
#
# WHAT THE ROWS ARE (real four-source replay, 23 such rows). Every one joined two DIFFERENT
# parcels, and every one shows the aged row's parcel, address and owner. Every one of those
# shown parcels WAS in this run's scrape: the first dedupe() had fused its fresh record into a
# neighbour's (its fuzzy pass matches a numberless street, "LOOKOUT RD", to a numbered one,
# "328 LOOKOUT RD"; the house-number guard needs two numbers), so merge_prior_board() found no
# fresh row to match the prior copy and aged it, and dedupe2 matched the two again. So the tag
# is wrong on all 23. A row whose shown property really left the source and that dedupe2 fused
# into a live neighbour would lose a correct tag; none of the 23 was one.
#
# WHAT THE REPAIR DOES AND CANNOT DO. It removes the tag and its effects (pulled_sale, the
# status, stale_case, a HOT->WARM down-rank whose reason is the tag, the intent cap), the same
# result the tail would have produced without the tag. It cannot restore the live row's own
# top-level values: the merge kept only the aged row's, the checkpoint holds no other copy, and
# every enricher after dedupe2 ran on the merged row.
#
# THE WHOLE 10/5 CHECKPOINT (2026-10-06, streamed on the VM; the four-source replay above was a
# sample). 6,414 tagged rows have last_seen at or after the run start; 5,493 of them are their
# OWN prior copy (same source, first_seen and address/parcel) and only 1,545 show a second
# source. The big class is an identity mismatch, not a fusion: validation nulls a parcel id
# under 7 characters before publish, so Catawba's tax-account rows (3,737; parcel '65771' in the
# scrape, None on the board) and other short-id rolls never matched their published copy in
# merge_prior_board(), were aged, and dedupe2 met them again through the synthesized
# 'Parcel - <owner> ...' address. Checked live on 10/6: all 3,519 Catawba rows that carry their
# account number are on today's delinquent list, all 457 hud_reac_inspection rows are in
# today's REAC pull. 143 fannie_homepath rows were revived by enrichment_reo_freshness (it set
# last_seen when HomePath still listed them, 2026-10-06T03:2x, and left the tag).
#
# THE CUTOFF IS NOT ALWAYS THE RUN START. Rows from the Mac's stealth hand-off keep the Mac's
# scrape time as last_seen (10/4 19:34:31 - 21:13:51 for the hand-off the 10/5 run ingested),
# which is BEFORE the VM run's start: 266 tagged rows carry exactly such a stamp. What separates
# "seen this run" from "aged" is the prior board: every aged row kept a last_seen from it, and
# its newest is 2026-10-02T21:47:35.693631. So the cutoff is any instant after the prior board's
# newest last_seen and no later than the oldest last_seen this run brought in (the hand-off's
# oldest row when there is one); for the 10/5 run that is 2026-10-04T19:34:31Z, and it moves no
# untagged-but-old row and no aged row (the newest tagged row before it is 10/2 21:31:37).
#
# STALE_CASE WITHOUT A TAG. board_quality sets raw['stale_case'] only for the two withdrawn
# reasons, and merge_prior_board() cleared pulled_sale and the status on a matched row but kept
# the prior copy's stale_case. So a row seen this run that carries stale_case and no tag
# inherited it: 7,741 in the 10/5 checkpoint. The dashboard reads stale_case as "presumed
# withdrawn" and lead_signals caps intent at 69 on it, so these are repaired the same way.


def parse_stamp(v: Any) -> Optional[datetime]:
    """A naive-UTC datetime from a datetime or an ISO string; None for anything else."""
    if isinstance(v, str) and v:
        s = v[:-1] + "+00:00" if v.endswith("Z") else v
        try:
            v = datetime.fromisoformat(s)
        except ValueError:
            return None
    if not isinstance(v, datetime):
        return None
    return v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo else v


def _hot_demoted_by_tag(raw: dict) -> bool:
    from .enrichment_board_quality import WITHDRAWN_TAG_REASONS
    ds = raw.get("distress_stack")
    return (isinstance(ds, dict) and bool(ds.get("downranked_stale"))
            and ds.get("downranked_reason") in WITHDRAWN_TAG_REASONS)


@dataclass
class _Reseen:
    idx: int
    source: str
    street_address: Optional[str]
    first_seen: str
    last_seen: str
    parcel_id: Optional[str] = None
    aged_source: Optional[str] = None
    status: Optional[str] = None
    hot_demoted: bool = False
    also_seen_in: tuple = ()
    #: "tagged" (carries raw['pulled_sale']) or "stale_case" (an inherited stale_case, no tag)
    kind: str = "tagged"

    def ident(self) -> list:
        return [self.source, self.street_address, self.first_seen, self.last_seen]

    def sample(self) -> dict:
        return {"row": self.ident(), "kind": self.kind, "parcel_id": self.parcel_id,
                "aged_copy_source": self.aged_source, "also_seen_in": list(self.also_seen_in),
                "status": self.status, "hot_demoted": self.hot_demoted}


def _reseen_view(idx: int, row: Any) -> _Reseen:
    d = _view_fields(row)
    raw = _raw(row)
    ps = raw.get("pulled_sale")
    return _Reseen(idx=idx, source=str(d.get("source") or ""), street_address=d.get("street_address"),
                   first_seen=_stamp(d.get("first_seen")), last_seen=_stamp(d.get("last_seen")),
                   parcel_id=_get(row, "parcel_id"), status=_get(row, "auction_status"),
                   aged_source=ps.get("last_seen_source") if isinstance(ps, dict) else None,
                   hot_demoted=_hot_demoted_by_tag(raw),
                   also_seen_in=tuple(sorted(sources_of(None, raw))),
                   kind="tagged" if ps else "stale_case")


def _repairable(row: Any) -> bool:
    """A row the reseen repair may touch: it carries the withdrawn tag, or the stale_case flag
    that only the tag ever sets (see STALE_CASE WITHOUT A TAG above)."""
    raw = _raw(row)
    return bool(raw.get("pulled_sale") or raw.get("stale_case"))


def repair_reseen(listings: list[Listing], today: Optional[date] = None) -> dict:
    """Remove the withdrawn tag from rows this run saw (see the block comment above), and redo,
    for these rows only and in the tail's order, the steps that read it: the intent score
    (enrichment_lead_signals, which runs before board quality) and board quality's stale check
    (a sale date that is past can still down-rank the row; the tag no longer can)."""
    from .enrichment_board_quality import downrank_if_stale
    from .enrichment_lead_signals import enrich_lead_signals

    today = today or date.today()
    stats: Counter = Counter()
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        stats["status_cleared"] += li.auction_status == "presumed_withdrawn"
        stats["stale_case_cleared"] += bool(raw.get("stale_case"))
        stats["stale_case_only"] += not raw.get("pulled_sale")
        drop_withdrawn_tags(li)
        # No scraper writes this status; on a row this run saw it can only be inherited, with or
        # without the miss counter that normally comes with it.
        if li.auction_status == "presumed_withdrawn":
            li.auction_status = None
        if _hot_demoted_by_tag(li.raw):
            ds = copy.deepcopy(li.raw["distress_stack"])
            ds["tier"] = "HOT"
            ds.pop("downranked_stale", None)
            ds.pop("downranked_reason", None)
            li.raw["distress_stack"] = ds
            stats["hot_restored"] += 1
    if listings:
        enrich_lead_signals(listings)
    for li in listings:
        downrank_if_stale(li, li.raw, today, stats)
    stats["rows"] = len(listings)
    return dict(stats)


@dataclass
class CollapsePlan:
    rows_scanned: int = 0
    groups: list = field(default_factory=list)   # [{"key", "keep": _View, "drop": [_View]}]
    skipped: Counter = field(default_factory=Counter)
    #: ISO run start when the reseen repair is part of the plan (plan_collapse(seen_since=...))
    seen_since: Optional[str] = None
    reseen: list = field(default_factory=list)          # [_Reseen] to repair
    evidence: dict = field(default_factory=dict)

    @property
    def rows_dropped(self) -> int:
        return sum(len(g["drop"]) for g in self.groups)

    def by_source(self) -> Counter:
        return Counter(g["keep"].source for g in self.groups)

    def digest(self) -> str:
        """sha256 prefix over every group's identity (parcel key + each member's source,
        street_address, first_seen, last_seen) and, when the reseen repair is on, its run start
        and each repaired row's identity -- independent of row positions, so the dry run over the
        checkpoint FILE and the apply over the loaded Listings agree. Without the reseen part
        it is the same digest the twins-only plan always had."""
        # Members are ordered by their JSON text: an ident can hold None (a row with no street
        # address), and None does not compare with a string.
        def members(views):
            return sorted((v.ident() for v in views), key=lambda i: json.dumps(i, default=str))
        items = sorted(
            json.dumps([g["key"], g["keep"].ident(), members(g["drop"])], default=str)
            for g in self.groups)
        if self.seen_since is not None:
            items.append(json.dumps(["reseen", self.seen_since, members(self.reseen)], default=str))
        return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()[:16]

    def summary(self, sample: int = 10) -> dict:
        out = {
            "rows_scanned": self.rows_scanned,
            "groups": len(self.groups),
            "rows_dropped": self.rows_dropped,
            "digest": self.digest(),
            "by_source": dict(self.by_source().most_common()),
            "skipped": dict(self.skipped.most_common()),
            "sample": [],
        }
        for g in sorted(self.groups, key=lambda g: (g["keep"].source, g["key"]))[:sample]:
            out["sample"].append({
                "parcel": g["key"],
                "keep": g["keep"].ident(),
                "drop": [v.ident() for v in g["drop"]],
            })
        if self.seen_since is not None:
            order = lambda v: (v.kind != "tagged", v.source, v.last_seen, v.idx)  # noqa: E731
            tagged = [v for v in self.reseen if v.kind == "tagged"]
            stale = [v for v in self.reseen if v.kind != "tagged"]
            out["reseen"] = {
                "seen_since": self.seen_since,
                "rows_repaired": len(self.reseen),
                "tagged_rows": len(tagged),
                "stale_case_only_rows": len(stale),
                "by_source": dict(Counter(v.source for v in tagged).most_common()),
                "stale_case_only_by_source": dict(Counter(v.source for v in stale).most_common()),
                "status_presumed_withdrawn": sum(v.status == "presumed_withdrawn"
                                                 for v in self.reseen),
                "hot_demoted_by_tag": sum(v.hot_demoted for v in self.reseen),
                "evidence": self.evidence,
                "sample": [v.sample() for v in sorted(self.reseen, key=order)[:sample]],
            }
        return out


def plan_collapse(rows: Callable[[], Iterable[Any]], seen_since: Any = None) -> CollapsePlan:
    """Plan the pre-publish clean-up of a WHOLE board (a checkpoint or the published board).
    Read-only.

    PLACEHOLDER TWINS: one LIVE row (re-scraped this run: no raw['pulled_sale']) with no real
    house number, plus the aging prior-only copies of the same parcel from the same source that
    the merge left beside it.

    RESEEN ROWS (only when ``seen_since`` is given): a row carrying raw['pulled_sale'] whose
    last_seen is at or after ``seen_since`` absorbed a row this run brought in (see the block
    comment above parse_stamp()) and is planned for repair_reseen(); so is an untagged row with
    an inherited raw['stale_case'] at or after it. A repaired row counts as live for the twin
    rule too. ``seen_since`` is NOT simply the run's start when the run ingested rows stamped
    earlier (the Mac hand-off): it must sit after the prior board's newest last_seen and at or
    before the oldest last_seen the run brought in. The evidence block shows where it falls.

    ``rows`` is called twice and must yield the same rows in the same order each time (dicts
    or Listings): pass 1 keeps only the parcel keys of live placeholder rows and a small view of
    each reseen row, pass 2 keeps a small view of only the rows under those keys. Memory is
    bounded by those candidates, never by the board.

    A twin group is collapsed only when, under its parcel key: exactly one live placeholder row;
    no other live row from a source it shares; at least one aging copy from a shared source
    with a real house number; at most ONE distinct real house number among ALL the key's rows
    (any source); no unit designator and no resolver-derived parcel on any member; and at most
    MAX_GROUP_ROWS members. Anything else is counted in ``skipped`` by reason and left alone.
    """
    cut = parse_stamp(seen_since) if seen_since is not None else None
    if seen_since is not None and cut is None:
        raise ValueError(f"seen_since {seen_since!r} is not an ISO timestamp")
    plan = CollapsePlan(seen_since=cut.isoformat() if cut is not None else None)
    seeds: dict[str, int] = {}
    revived: set[int] = set()
    below = above = None
    below_days: Counter = Counter()
    n = 0
    for n, row in enumerate(rows(), start=1):
        raw = _raw(row)
        if raw.get("pulled_sale"):
            if cut is None:
                continue
            ls = parse_stamp(_get(row, "last_seen"))
            if ls is None or ls < cut:
                if ls is not None:
                    below_days[ls.date().isoformat()] += 1
                    if below is None or ls > below:
                        below = ls
                continue
            if above is None or ls < above:
                above = ls
            plan.reseen.append(_reseen_view(n - 1, row))
            revived.add(n - 1)
        elif cut is not None and raw.get("stale_case"):
            ls = parse_stamp(_get(row, "last_seen"))
            if ls is not None and ls >= cut:
                plan.reseen.append(_reseen_view(n - 1, row))
        addr = _get(row, "street_address")
        if real_house_no(addr) or has_unit(addr):
            continue
        k = parcel_key(_get(row, "state"), _get(row, "county"), _get(row, "parcel_id"))
        if k is None or resolver_parcel(raw):
            continue
        seeds[k] = seeds.get(k, 0) + 1
    plan.rows_scanned = n
    if cut is not None:
        # The newest days of tagged rows left alone: the cutoff should sit in a gap after them.
        # (The old 'tagged_carryover_rows_before_cutoff_not_judged' count is gone: raw['carryover']
        # is sticky from the 8/14 and 9/22 runs, so it counted 2,922 rows that had nothing to do
        # with this run.)
        plan.evidence = {
            "newest_tagged_last_seen_before_cutoff": below.isoformat() if below else None,
            "oldest_tagged_last_seen_at_or_after_cutoff": above.isoformat() if above else None,
            "tagged_rows_before_cutoff_newest_days": dict(sorted(below_days.items())[-4:]),
            "stale_case_only_rows_at_or_after_cutoff": sum(v.kind != "tagged" for v in plan.reseen),
        }

    if not seeds:
        return plan
    frozen = frozenset(revived)
    groups: dict[str, list[_View]] = {}
    for idx, row in enumerate(rows()):
        k = parcel_key(_get(row, "state"), _get(row, "county"), _get(row, "parcel_id"))
        if k is not None and k in seeds:
            groups.setdefault(k, []).append(_view(idx, row, k, frozen))
    del seeds

    for k, views in groups.items():
        live_ph = [v for v in views if v.live and not v.real_hn and not v.unit and not v.resolver]
        if len(views) < 2:
            plan.skipped["no_twin"] += 1
            continue
        if len(live_ph) != 1:
            plan.skipped["not_exactly_one_live_placeholder"] += 1
            continue
        keep = live_ph[0]
        same_src = [v for v in views if v is not keep and v.sources & keep.sources]
        if not same_src:
            plan.skipped["no_same_source_twin"] += 1
            continue
        if any(v.live for v in same_src):
            plan.skipped["live_twin_same_source"] += 1
            continue
        if not any(v.real_hn for v in same_src):
            plan.skipped["no_numbered_twin"] += 1
            continue
        if len({v.real_hn for v in views if v.real_hn}) > 1:
            plan.skipped["ambiguous_house_numbers"] += 1
            continue
        if any(v.unit or v.resolver for v in same_src):
            plan.skipped["unit_or_resolver_parcel"] += 1
            continue
        if 1 + len(same_src) > MAX_GROUP_ROWS:
            plan.skipped["too_many_rows"] += 1
            continue
        drop = sorted(same_src, key=lambda v: (v.last_seen, v.first_seen), reverse=True)
        plan.groups.append({"key": k, "keep": keep, "drop": drop})
    return plan


class CollapsePlanMismatch(RuntimeError):
    """The rows a plan names are not the rows at those positions any more."""


def apply_collapse(listings: list[Listing], plan: CollapsePlan,
                   today: Optional[date] = None, *, kept_out: Optional[dict] = None) -> dict:
    """Apply ``plan`` to ``listings`` IN PLACE. Every planned row is re-checked against the
    plan's view of it first (CollapsePlanMismatch, nothing changed, if any differs). Then the
    reseen rows are repaired (repair_reseen()), and each twin group's live row absorbs its aging
    copies via absorb_copies() (newest copy first): the published row is the live row, plus only
    what COPY_ALLOWLIST names. Its own raw, scores, tags and valuation are untouched, so a
    copy's withdrawn tag, stale_case, owner data or money never reaches it. The copies are
    removed.

    ``kept_out``, when given, is filled for the publish (write_artifact's prior-detail
    exclusions, see the block comment above COPY_ALLOWLIST): ``rows`` the kept Listing objects,
    ``keys`` the published identity keys (web_artifact._identity_keys) of the dropped copies."""
    for g in plan.groups:
        for v in [g["keep"], *g["drop"]]:
            if v.idx >= len(listings):
                raise CollapsePlanMismatch(f"row {v.idx} is past the end ({len(listings)} rows)")
            now = _view(v.idx, listings[v.idx], v.key)
            if now.ident() != v.ident() or now.key != v.key:
                raise CollapsePlanMismatch(f"row {v.idx}: planned {v.ident()} found {now.ident()}")
    cut = parse_stamp(plan.seen_since) if plan.seen_since is not None else None
    for v in plan.reseen:
        if v.idx >= len(listings):
            raise CollapsePlanMismatch(f"row {v.idx} is past the end ({len(listings)} rows)")
        li = listings[v.idx]
        now = _reseen_view(v.idx, li)
        ls = parse_stamp(li.last_seen)
        if (now.ident() != v.ident() or now.kind != v.kind or not _repairable(li)
                or ls is None or cut is None or ls < cut):
            raise CollapsePlanMismatch(f"row {v.idx}: planned reseen {v.ident()} found {now.ident()}")

    # The dropped copies' published identity keys, read before anything changes (pure: each
    # _to_dict runs on a deep copy).
    copy_keys: set[str] = set()
    if kept_out is not None:
        for g in plan.groups:
            for v in g["drop"]:
                copy_keys.update(_identity_keys(_to_dict(listings[v.idx].model_copy(deep=True))))

    reseen_stats = repair_reseen([listings[v.idx] for v in plan.reseen], today=today)

    # Every merged row is built (absorb_copies() changes neither input) before any is swapped in.
    merged_rows: list[tuple[int, Listing]] = []
    taken_n: Counter = Counter()
    owner_differs = 0
    for g in plan.groups:
        live = listings[g["keep"].idx]
        copies = [listings[v.idx] for v in g["drop"]]          # newest first (plan order)
        merged, taken = absorb_copies(live, copies)
        taken_n.update(taken)
        owner_differs += any(not same_owner(live, c) for c in copies)
        merged_rows.append((g["keep"].idx, merged))
    dropped = {v.idx for g in plan.groups for v in g["drop"]}
    for keep_idx, merged in merged_rows:
        listings[keep_idx] = merged
    before_n = len(listings)
    listings[:] = [li for i, li in enumerate(listings) if i not in dropped]
    if kept_out is not None:
        kept_out["rows"] = [m for _, m in merged_rows]
        kept_out["keys"] = copy_keys
    return {"groups": len(plan.groups), "rows_dropped": before_n - len(listings),
            "addresses_restored": taken_n["street_address"],
            "first_seen_taken": taken_n["first_seen"],
            "groups_copy_owner_differs": owner_differs, "rows_after": len(listings),
            "reseen_repaired": len(plan.reseen), "reseen": reseen_stats,
            "digest": plan.digest()}
