#!/usr/bin/env python3
"""Replace a parcel_id that sits at a DIFFERENT address than the lead's own street, when that street resolves uniquely
to another parcel, and withdraw it (with what was copied from it) when the street resolves to nothing unique. The repair
half of scripts/resolve_parcel_from_address.py (docs/parcel_from_address_2026-09-21.md section 5.5, 11 and 12).

WHY. About 4,000 liensnc leads carry a parcel that is a neighbour's ("4116 Balsam Drive" carries the parcel of
"4028 BALSAM DR"). The parcel was attached without the address, and every value, sqft, acreage and mailing the join
copied from it belongs to another house. resolve_parcel_from_address never replaces an existing parcel; this does, under
the same acceptance rule, and only when three things are all true.

  1. THE PARCEL IS NOT THE SOURCE'S OWN. A tax roll's parcel_id is what the bill is for; when its address disagrees, the
     address is the mailing or a lot description and the parcel is right. So only sources whose scraper never sets a
     parcel_id are repaired (REPAIRABLE_SOURCES: the parcel was attached later by an enricher, from coordinates). Every
     other source is left alone, and so are denied sources, overage claims, name-resolved parcels and streets that were
     copied from a parcel cache.
  2. THE EXISTING PARCEL CLEARLY DISAGREES. It is in the cache, its situs parses as a numbered street, and it fails
     every agreement test: not the same number and street name, not the resolver's full rule, not the older Burke test
     (same number and one shared word). A different house number on the same street, or another street, is a
     disagreement. A different suffix, a unit, a leading zero, missing or unparseable situs, or an id that is not in
     the cache is NOT: those leads are left as they are.
  3. THE ADDRESS RESOLVES UNIQUELY TO A DIFFERENT PARCEL under resolve_parcel_from_address's rule (full street name, suffix,
     direction, town, unit, ZIP, specific id, exactly one parcel). One more guard: if the existing parcel's owner agrees
     with the lead's owner and the new parcel's does not, the owner evidence favours the existing parcel (a mistyped
     address), so it stays.

WHAT IT DOES WHEN THERE IS NO REPLACEMENT (a lead in a repairable source whose existing parcel clearly disagrees and whose street resolves to no
unique parcel: no match, ambiguous, unit, ZIP conflict, placeholder id) is a WITHDRAWAL. The old parcel is still at another address, so what the
join copied from it is still wrong, and the next join would copy it again from the parcel_id. So the fields that provably came from the old parcel are
cleared exactly as for a replacement AND parcel_id is cleared; raw['parcel_from_address'] records {withdrawn_parcel, reason:
street_disagrees_no_unique_match, ...}. The street stays, so resolve_parcel_from_address can still resolve the lead on a later run if a cache gains
that street. Every guard applies to a withdrawal as to a replacement, and one more: a lead whose owner independently agrees with the old parcel keeps
it (the street is more likely the typo). `withdraw=False` (CLI --no-withdraw, dry run) switches it off.

WHAT A REPLACEMENT DOES. parcel_id becomes the new parcel (the board's own spelling for it when one is on the board);
raw['parcel_from_address'] is stamped as the resolver stamps it, plus replaced_parcel, replaced_situs and the fields
cleared. The old parcel_id and everything cleared goes to the returned '_backup' (backups/), for a withdrawal too. The join wrote no
provenance, so only what provably came from the OLD parcel is cleared, by value: market_value, tax_value, living_sqft,
acreage, land_use and owner_name equal to the old cache row's; raw.gis mailing, owner, values and last_sale equal to it; an
owner_mailing block whose mailing equals the old cache mailing and whose source is a parcel layer (never the lead's own
filing); a gis_attrs_full bag that names the old parcel. The next join step refills them from the new parcel.

    python scripts/repair_parcel_from_address.py               # dry run over the live board: ONE streaming pass, counts only
    python scripts/repair_parcel_from_address.py --rows-file X # dry run over a saved board-format extract
    python scripts/repair_parcel_from_address.py --apply       # ONLY board process

or as step `parcel_repair` of scripts/apply_board_fixes.py (right after `parcel`, before `address` and `join`).
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolve_parcel_from_address as R  # noqa: E402
from _dq_common import county_in_state, iter_rows  # noqa: E402

REQUIRED_RAW_KEYS = ["parcel_from_address"]
BACKUP_NAME = "repair_parcel_from_address_replaced"

#: Sources whose scraper NEVER sets a parcel_id, so a parcel on one of their rows was attached later by an enricher (from
#: coordinates or a search) and can be a neighbour's. Checked against the scraper source by
#: tests/test_dq_repair_parcel_from_address.py, so a scraper that starts setting parcel_id breaks the build instead of
#: having its native parcels overwritten. The street of each is the property or facility site.
REPAIRABLE_SOURCES = frozenset({
    "liensnc",                 # lien filings: the project site
    "sc_dew_lien_registry",    # SC DES lien registry: the facility site
    "nc_ust_incidents",        # NC UST incidents (scrapers/counties_generic/state_contamination.py)
    "nc_dam_safety",           # NC dam safety (same file)
    "sc_ust_registry",         # SC UST registry: the facility site
    "fannie_homepath",         # REO listings: the property
    "brock_scott",             # foreclosure notices: the property address
})
#: source tail -> scraper file (relative to src/foreclosure_scraper/scrapers), for the ones not named after their source
SCRAPER_FILE = {"nc_ust_incidents": "counties_generic/state_contamination.py",
                "nc_dam_safety": "counties_generic/state_contamination.py"}

#: owner_mailing.source values that mean "read from a parcel layer" (the lead's own filing is 'liensnc_filing')
PARCEL_MAILING_SOURCES = frozenset({None, "", "county_gis", "nc_onemap", "scdot_sc", "sc_assessor_roll",
                                    "county_tax_roll", "henderson_county_gis"})
#: A disagreeing parcel with no unique replacement is WITHDRAWN (its values blanked, parcel_id cleared) when the reason is one of these.
#: Not withdrawn: left_same_parcel, left_owner_favours_existing, left_cache_unreadable, and any lead whose owner agrees with the old parcel.
WITHDRAW_ON = frozenset({"left_no_match", "left_ambiguous", "left_no_specific_id", "left_zip_conflict", "left_unit_rejected"})
WITHDRAW_REASON = "street_disagrees_no_unique_match"
#: parcel_from_geo.source values that are not coordinates: a PIN swap and an earlier address match
NON_GEO_STAMPS = frozenset({"ptscloud_pts_to_pin", "burke_cache_situs_address"})


# ================================================================================== row adapters
class _DictRow:
    def __init__(self, d: dict):
        self.d = d

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v):
        self.d[k] = v

    @property
    def raw(self) -> dict:
        r = self.d.get("raw")
        return r if isinstance(r, dict) else {}


class _ObjRow:
    def __init__(self, li):
        self.li = li

    def get(self, k):
        return getattr(self.li, k, None)

    def set(self, k, v):
        setattr(self.li, k, v)

    @property
    def raw(self) -> dict:
        return self.li.raw if isinstance(self.li.raw, dict) else {}


# ================================================================================== the disagreement test
def situs_verdict(lead_street, cache_address, lead_city=()) -> str:
    """'agrees' | 'disagrees' | 'unknown' for a lead's street against a parcel cache's situs.

    Agreement is tested at every level (the resolver's full rule with the town ignored, same number and street name, the
    older Burke test), so only a CLEAR difference counts as disagreement. 'unknown' when either side is not one numbered
    street (missing, road-only, legal text, a range) or when any part of a multi-address situs is not."""
    from repair_burke_storm_damage_parcels import addresses_agree as burke
    a, _why = R.parse_street(lead_street)
    if a is None:
        return "unknown"
    parts = [p for p in str(cache_address or "").split(";") if p.strip()]
    if not parts:
        return "unknown"
    parsed = [R.parse_street(p)[0] for p in parts]
    city = lead_city or R._norm_city(a.trail)
    for text, st in zip(parts, parsed):
        if burke(lead_street, text) or R.name_level_agree(lead_street, text):
            return "agrees"
        if st is not None and R.street_agrees(a, st, city, "off"):
            return "agrees"
    if any(p is None for p in parsed):
        return "unknown"
    return "disagrees"


class Cand(NamedTuple):
    ref: int
    lead: R.Lead
    row: object               # the Listing or the board dict, kept for the clearing plan
    old_hit: dict
    old_tier: str


def existing_status(ld: R.Lead, raw: dict, *, policy: bool = True, lookup=None) -> tuple:
    """(status, old cache hit, tier) for a lead that already has a parcel. Only 'disagrees' proceeds to resolution.
    policy=False skips the source and provenance gates (the hold-out tests the algorithm, not the source policy)."""
    from foreclosure_scraper import parcel_cache as pc
    if not ld.parcel_id:
        return "skip_no_parcel", None, None
    if ld.listing_type == "tax_sale_overage":
        return "skip_tax_sale_overage", None, None
    tail = ld.source.split(".")[-1]
    if tail in R.DENY_SOURCES:
        return "skip_source_street_is_not_situs", None, None
    if policy and tail not in REPAIRABLE_SOURCES:
        return "skip_parcel_is_the_sources_own", None, None
    if not ld.street:
        return "skip_no_address", None, None
    if ld.addr_from_cache:
        return "skip_street_came_from_a_parcel_layer", None, None
    if policy:
        pfg = raw.get("parcel_from_geo")
        if raw.get("resolved_from_name") or (isinstance(pfg, dict) and pfg.get("source") in NON_GEO_STAMPS):
            return "skip_parcel_not_from_coordinates", None, None
        pfa = raw.get(R.RAW_KEY)
        if isinstance(pfa, dict) and not pfa.get("replaced_parcel"):
            return "skip_parcel_from_the_address_resolver", None, None          # it was matched on this very street
    if not ld.county:
        return "skip_no_county", None, None
    if not county_in_state(ld.county, ld.state):
        return "skip_county_not_in_state", None, None
    if not R._cache_exists(ld.county, ld.state):
        return "no_cache", None, None
    try:
        hit, tier = (lookup or pc.lookup_with_tier)(ld.county, ld.parcel_id, ld.state)
    except Exception:  # noqa: BLE001
        return "lookup_error", None, None
    if not tier:
        return "existing_id_not_in_cache", None, None
    hit = hit or {}
    if not hit.get("address"):
        return "existing_situs_missing", hit, tier
    v = situs_verdict(ld.street, hit["address"], R._city_words(ld.city))
    if v == "unknown":
        return "situs_not_comparable", hit, tier
    return ("agrees" if v == "agrees" else "disagrees"), hit, tier


# ================================================================================== clearing what the old parcel wrote
def _nz(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _same_num(a, b) -> bool:
    from foreclosure_scraper import parcel_cache as pc
    x, y = pc._num(a), pc._num(b)
    return x is not None and y is not None and x > 0 and math.isclose(x, y, rel_tol=1e-6, abs_tol=0.01)


_TOP_NUMERIC = ("market_value", "tax_value", "living_sqft", "acreage")
_GIS_NUMERIC = ("market_value", "tax_value", "living_sqft", "acreage", "assessed_value")
_ID_KEYS = ("PIN", "LEGACY_PIN", "REID", "TAXPIN", "PARCEL_ID", "PARCELID", "PID", "TMS", "PARCEL", "PARCEL_NUMBER",
            "PARNO", "ALTPARNO", "NPARNO")          # the last three: NC OneMap


def plan_clear(row, old_hit: dict, old_ids: set) -> list:
    """The fields that provably came from the OLD parcel, as [(kind, key, value)]. Nothing is guessed: a field is listed only
    when its value equals what the old parcel's cache row holds (or, for a parcel-layer block, when the block names the old
    parcel). The lead's own data (a filing's mailing and owner) never matches and is never listed."""
    from foreclosure_scraper import parcel_cache as pc
    ops: list = []
    for f in _TOP_NUMERIC:
        cur, old = row.get(f), old_hit.get(f)
        if cur and old and _same_num(cur, old):
            ops.append(("top", f, cur))
    if row.get("land_use") and old_hit.get("land_use") and _nz(row.get("land_use")) == _nz(old_hit["land_use"]):
        ops.append(("top", "land_use", row.get("land_use")))
    if row.get("owner_name") and old_hit.get("owner") and str(row.get("owner_name")).strip() == str(old_hit["owner"]).strip():
        ops.append(("top", "owner_name", row.get("owner_name")))       # verbatim: the join copies the cache string as it is
    raw = row.raw
    g = raw.get("gis")
    if isinstance(g, dict):
        if g.get("mailing") and old_hit.get("owner_mailing") and _nz(g["mailing"]) == _nz(old_hit["owner_mailing"]):
            ops.append(("gis", "mailing", g["mailing"]))
        if g.get("owner") and old_hit.get("owner") and _nz(g["owner"]) == _nz(old_hit["owner"]):
            ops.append(("gis", "owner", g["owner"]))
        for f in _GIS_NUMERIC:
            if g.get(f) and old_hit.get(f) and _same_num(g[f], old_hit[f]):
                ops.append(("gis", f, g[f]))
        if g.get("land_use") and old_hit.get("land_use") and _nz(g["land_use"]) == _nz(old_hit["land_use"]):
            ops.append(("gis", "land_use", g["land_use"]))
        ls = g.get("last_sale")
        amt = pc.sale_amount(old_hit.get("sale_price"))
        if isinstance(ls, dict) and amt and pc.sale_amount(ls.get("amount")) == amt:
            ops.append(("gis_last_sale", "last_sale", dict(ls)))
        for k in ("parcel_id", "pin", "parcel"):
            if g.get(k) and _nz(g[k]) in old_ids:
                ops.append(("gis", k, g[k]))
    om = raw.get("owner_mailing")
    if isinstance(om, dict) and om.get("source") in PARCEL_MAILING_SOURCES:
        same_mail = om.get("mailing") and old_hit.get("owner_mailing") and _nz(om["mailing"]) == _nz(old_hit["owner_mailing"])
        names_old = om.get("parcel_id") and pc._norm_id(om["parcel_id"]) in old_ids
        if same_mail or names_old:
            ops.append(("owner_mailing", "owner_mailing", dict(om)))
    bag = raw.get("gis_attrs_full")
    if isinstance(bag, dict):
        low = {str(k).lower(): v for k, v in bag.items()}
        vals = {pc._norm_id(v) for k, v in bag.items() if str(k).upper() in _ID_KEYS and isinstance(v, (str, int, float)) and v}
        # a bag with no usable id still belongs to the old parcel when its site address AND owner are the old cache row's
        same_site = (_nz(low.get("siteadd") or low.get("situs")) and old_hit.get("address")
                     and _nz(low.get("siteadd") or low.get("situs")) == _nz(old_hit["address"])
                     and _nz(low.get("ownname") or low.get("owner")) and old_hit.get("owner")
                     and _nz(low.get("ownname") or low.get("owner")) == _nz(old_hit["owner"]))
        if vals & old_ids or same_site:
            ops.append(("gis_attrs_full", "gis_attrs_full", dict(bag)))
    return ops


def apply_ops(row, ops: list) -> None:
    raw = row.raw
    for kind, key, _val in ops:
        if kind == "top":
            row.set(key, None)
        elif kind == "gis":
            g = raw.get("gis")
            if isinstance(g, dict):
                g.pop(key, None)
        elif kind == "gis_last_sale":
            g = raw.get("gis")
            if isinstance(g, dict):
                g.pop("last_sale", None)
        elif kind in ("owner_mailing", "gis_attrs_full"):
            raw.pop(key, None)
    g = raw.get("gis")
    if isinstance(g, dict) and not g:
        raw.pop("gis", None)


# ================================================================================== resolution
class Plan(NamedTuple):
    cand: Cand
    status: str            # replace | left_* | ...
    res: object = None
    new_pid: str = ""
    basis: str = ""
    new_agrees: object = None
    old_agrees: object = None
    ops: tuple = ()
    why: str = ""          # for a withdrawal: the resolution outcome that left no replacement (left_no_match, ...)


def owner_evidence(lead_owner, old_owner, new_owner) -> tuple:
    """(old parcel agrees with the lead's owner, new parcel agrees). A lead owner that is the OLD parcel's owner spelled exactly
    as the cache spells it was most likely copied from that parcel by the join (fill-only when the lead had none), so it is not
    independent evidence for either parcel: both verdicts are then None."""
    if lead_owner and old_owner and str(lead_owner).strip() == str(old_owner).strip():
        return None, None
    return R.owner_verdict(lead_owner, old_owner), R.owner_verdict(lead_owner, new_owner)


def _old_ids(pid) -> set:
    from foreclosure_scraper import parcel_cache as pc
    return {k for k, _t in pc._lookup_candidates(pid)}


def _view(c: Cand):
    return _DictRow(c.row) if isinstance(c.row, dict) else _ObjRow(c.row)


def _withdraw_or_leave(c: Cand, res, status: str, withdraw: bool) -> Plan:
    """No unique replacement. The old parcel is still at another address, so what was copied from it is still wrong: withdraw it, unless
    the lead's owner independently agrees with the old parcel (then the street is more likely the typo and everything stays)."""
    if not withdraw or status not in WITHDRAW_ON:
        return Plan(c, status, res)
    old_a, _n = owner_evidence(c.lead.owner, c.old_hit.get("owner"), None)
    if old_a is True:
        return Plan(c, "left_owner_agrees_with_existing", res, old_agrees=old_a)
    ops = tuple(plan_clear(_view(c), c.old_hit, _old_ids(c.lead.parcel_id)))
    return Plan(c, "withdraw", res, old_agrees=old_a, ops=ops, why=status)


def plan_candidates(cands: list, corpus: R.Corpus, *, index_factory=None, withdraw: bool = True) -> list:
    """One Plan per disagreeing lead: replace, withdraw (no unique replacement) or left. One county index per county, built from the
    disagreeing leads' streets only."""
    build = index_factory or R.CountyIndex.build
    by_county: dict = defaultdict(list)
    for c in cands:
        by_county[(c.lead.state, c.lead.county)].append(c)
    plans: list = []
    for (state, county), cs in sorted(by_county.items(), key=lambda kv: -len(kv[1])):
        parsed = [(c, R.parse_street(c.lead.street)[0]) for c in cs]
        keys = {(st.num, R.anchor_word(st)) for _c, st in parsed if st}
        idx = build(county, state, keys) if keys else None
        if idx is None:
            plans += [Plan(c, "left_cache_unreadable") for c in cs]
            continue
        bmap = R.board_id_map(corpus.board_pids.get((state, county), ()))
        hist = corpus.id_hist.get((state, county), Counter())
        try:
            for c, st in parsed:
                ld = c.lead
                res = idx.resolve(st, city=ld.city, zip_code=ld.zip_code)
                if res.status != "unique":
                    plans.append(_withdraw_or_leave(c, res, "left_" + res.status, withdraw))
                    continue
                old_ids = _old_ids(ld.parcel_id)
                if old_ids & set(res.group.ids):
                    plans.append(Plan(c, "left_same_parcel", res))
                    continue
                old_a, new_a = owner_evidence(ld.owner, c.old_hit.get("owner"), res.group.owner)
                if old_a is True and new_a is not True:
                    plans.append(Plan(c, "left_owner_favours_existing", res, old_agrees=old_a, new_agrees=new_a))
                    continue
                pid, basis = R.choose_id(res.ids, bmap, hist)
                ops = tuple(plan_clear(_view(c), c.old_hit, old_ids))
                plans.append(Plan(c, "replace", res, pid, basis, new_a, old_a, ops))
        finally:
            idx.close()
    return plans


# ================================================================================== apply_rows
def _collect(rows_iter, *, listings: bool, keep_holdout: bool = False) -> tuple:
    """(corpus, disagreeing candidates, status counts by source, overall status counts) over Listing objects or board dicts."""
    corpus = R.Corpus(keep_holdout=keep_holdout)
    cands: list = []
    by_source: dict = defaultdict(Counter)
    overall: Counter = Counter()
    for i, r in enumerate(rows_iter):
        ld = R.lead_from_listing(i, r) if listings else R.lead_from_dict(i, r)
        corpus.add(ld)
        if not ld.parcel_id:
            continue
        raw = r.raw if listings else r.get("raw")
        status, hit, tier = existing_status(ld, raw if isinstance(raw, dict) else {})
        overall[status] += 1
        tail = ld.source.split(".")[-1]
        if tail in REPAIRABLE_SOURCES:
            by_source[tail][status] += 1
        if status == "disagrees":
            cands.append(Cand(i, ld, r, hit, tier))
    return corpus, cands, by_source, overall


def _backup_entry(c: Cand, p: Plan) -> dict:
    ld = c.lead
    e = {"action": "withdrawn" if p.status == "withdraw" else "replaced", "source": ld.source,
         "source_url": getattr(c.row, "source_url", None) if not isinstance(c.row, dict) else c.row.get("source_url"),
         "county": ld.county, "state": ld.state, "street": ld.street, "old_parcel_id": ld.parcel_id,
         "old_situs": c.old_hit.get("address"), "old_owner": c.old_hit.get("owner"),
         "cleared": [{"kind": k, "key": key, "value": v} for k, key, v in p.ops]}
    if p.status == "replace":
        e.update({"new_parcel_id": p.new_pid, "new_situs": str(p.res.group.address or ""), "new_owner": p.res.group.owner})
    else:
        e.update({"new_parcel_id": None, "withdraw_reason": WITHDRAW_REASON, "match_status": p.why})
    return e


def _stamp_replacement(li, p: Plan) -> None:
    old = li.parcel_id
    R._stamp(li, p.res, p.new_pid, p.basis, p.new_agrees)
    blk = li.raw[R.RAW_KEY]
    blk["verified"] = "address_exact_unique_replaced_disagreeing_parcel"
    blk["replaced_parcel"] = old
    blk["replaced_situs"] = str(p.cand.old_hit.get("address") or "")[:120]
    blk["replaced_cache_owner"] = p.cand.old_hit.get("owner")
    blk["replaced_owner_agrees"] = p.old_agrees
    blk["cleared_from_old_parcel"] = sorted({f"{k}:{key}" if k in ("top", "gis") else key for k, key, _v in p.ops})


def _stamp_withdrawal(li, p: Plan) -> None:
    """Record the withdrawal, blank the parcel_id, so the join (which needs a parcel_id) cannot refill it from the old parcel."""
    old = li.parcel_id
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw[R.RAW_KEY] = {"source": "repair_parcel_from_address", "withdrawn_parcel": old, "reason": WITHDRAW_REASON,
                         "match_status": p.why, "county": R.norm_county(li.county), "state": li.state,
                         "withdrawn_situs": str(p.cand.old_hit.get("address") or "")[:120],
                         "withdrawn_cache_owner": p.cand.old_hit.get("owner"), "withdrawn_owner_agrees": p.old_agrees,
                         "cleared_from_old_parcel": sorted({f"{k}:{key}" if k in ("top", "gis") else key for k, key, _v in p.ops})}
    li.parcel_id = None


def apply_rows(rows: list, *, dry_run: bool = False, index_factory=None, withdraw: bool = True) -> dict:
    """Replace disagreeing parcels on Listing objects, in place; withdraw (blank the values copied from it and the parcel_id) those with
    no unique replacement. Never changes len(rows), never writes a file. Returns counters and, on a real run, '_backup' (old parcel ids
    and everything cleared, keyed by row index)."""
    from _dq_common import assert_raw_keep
    if not dry_run:
        assert_raw_keep(REQUIRED_RAW_KEYS)
    n = len(rows)
    corpus, cands, _by, overall = _collect(rows, listings=True)
    plans = plan_candidates(cands, corpus, index_factory=index_factory, withdraw=withdraw)
    c: Counter = Counter({k: v for k, v in overall.items() if k not in ("skip_parcel_is_the_sources_own", "disagrees")})
    backup: dict = {}
    for p in plans:
        if p.status == "withdraw":
            c["withdrawn"] += 1
            c[f"withdrawn: {p.why[5:]}"] += 1
            for kind, key, _v in p.ops:
                c[f"withdrawn, cleared {kind}.{key}" if kind in ("top", "gis") else f"withdrawn, cleared {kind}"] += 1
            if dry_run:
                continue
            li = rows[p.cand.ref]
            backup[str(p.cand.ref)] = _backup_entry(p.cand, p)
            apply_ops(_ObjRow(li), list(p.ops))
            _stamp_withdrawal(li, p)
            continue
        if p.status != "replace":
            c[p.status] += 1
            continue
        c["replaced"] += 1
        c[f"replaced: new owner agrees {p.new_agrees}"] += 1
        for kind, key, _v in p.ops:
            c[f"cleared {kind}.{key}" if kind in ("top", "gis") else f"cleared {kind}"] += 1
        if dry_run:
            continue
        li = rows[p.cand.ref]
        backup[str(p.cand.ref)] = _backup_entry(p.cand, p)
        apply_ops(_ObjRow(li), list(p.ops))
        _stamp_replacement(li, p)
    assert len(rows) == n, "a repair must never change the row count"
    out = {k: v for k, v in c.items() if v}
    if backup:
        out["_backup"] = backup
    return out


repair_rows = apply_rows


# ================================================================================== hold-out: corrupt, then repair
def evaluate_repair_holdout(corpus: R.Corpus, *, per_county_cap: int = 1500, index_factory=None) -> dict:
    """(1) How the disagreement test classes the hold-out leads. (2) CORRUPT AND REPAIR: give each of those leads a WRONG parcel, either a neighbour (same street
    name, other number) or a parcel on another street, from the same county, then run the production path (disagreement test,
    unique resolution, owner guard) and see whether the true parcel comes back. precision = restored / (restored + wrong)."""
    from foreclosure_scraper import parcel_cache as pc
    build = index_factory or R.CountyIndex.build
    by_county: dict = defaultdict(list)
    seen: set = set()
    for ld in corpus.holdout:
        if ld.source.split(".")[-1] in R.DENY_SOURCES:
            continue
        k = (ld.state, ld.county, pc._norm_id(ld.parcel_id), ld.street.upper())
        if k in seen:
            continue
        seen.add(k)
        if len(by_county[(ld.state, ld.county)]) < per_county_cap:
            by_county[(ld.state, ld.county)].append(ld)
    out = {"agree": Counter(), "neighbour": Counter(), "other_street": Counter(), "per_county": defaultdict(Counter), "wrong_samples": []}
    # (1) counts how the disagreement test classes the hold-out; (2) is the corrupt-and-repair run below
    for (state, county), leads in sorted(by_county.items(), key=lambda kv: -len(kv[1])):
        if not (True if index_factory else R._cache_exists(county, state)):
            continue
        ver = []                                              # (lead, parsed street, true hit)
        for ld in leads:
            status, hit, _t = existing_status(ld, {}, policy=False)
            out["agree"]["checked"] += 1
            out["agree"][status] += 1
            if status == "agrees" and R.name_level_agree(ld.street, hit.get("address")):
                st, _w = R.parse_street(ld.street)
                if st is not None:
                    ver.append((ld, st, hit))
        if len(ver) < 2:
            continue
        keys = {(st.num, R.anchor_word(st)) for _l, st, _h in ver}
        idx = build(county, state, keys)
        if idx is None:
            continue
        by_name: dict = defaultdict(list)
        for j, (ld, st, hit) in enumerate(ver):
            by_name[st.name].append(j)
        try:
            for j, (ld, st, hit) in enumerate(ver):
                decoys = []
                same = [x for x in by_name[st.name] if x != j and ver[x][1].num != st.num]
                if same:
                    decoys.append(("neighbour", min(same, key=lambda x: abs(ver[x][1].num - st.num))))
                other = [x for x in range(len(ver)) if ver[x][1].name != st.name]
                if other:
                    decoys.append(("other_street", other[(j * 7919 + 13) % len(other)]))
                for kind, x in decoys:
                    dec_ld, _dst, dec_hit = ver[x]
                    fake = ld._replace(parcel_id=dec_ld.parcel_id)
                    status, hit2, _t = existing_status(fake, {}, policy=False)
                    c = out[kind]
                    if status != "disagrees":
                        c["decoy_not_a_clear_disagreement"] += 1
                        continue
                    c["corrupted"] += 1
                    res = idx.resolve(st, city=ld.city, zip_code=ld.zip_code)
                    if res.status != "unique":
                        if "left_" + res.status in WITHDRAW_ON:
                            # production withdraws it (the decoy is blanked) unless the lead's owner independently agrees with the decoy
                            old_a, _n = owner_evidence(ld.owner, hit2.get("owner"), None)
                            c["kept_owner_agrees_with_decoy" if old_a is True else "withdrawn"] += 1
                        else:
                            c["left_" + res.status] += 1
                        continue
                    old_a, new_a = owner_evidence(ld.owner, hit2.get("owner"), res.group.owner)
                    if old_a is True and new_a is not True:
                        c["left_owner_favours_existing"] += 1
                        continue
                    if _old_ids(dec_ld.parcel_id) & set(res.group.ids):
                        c["left_same_parcel"] += 1
                        continue
                    truth = _old_ids(ld.parcel_id)
                    ok = bool(truth & set(res.group.ids))
                    c["restored" if ok else "WRONG"] += 1
                    out["per_county"][(state, county)][kind + (":restored" if ok else ":wrong")] += 1
                    if not ok and len(out["wrong_samples"]) < 15:
                        out["wrong_samples"].append((state, county, kind, ld.street, res.group.address, hit.get("address"),
                                                     dec_hit.get("address")))
        finally:
            idx.close()
    return out


# ================================================================================== reporting and CLI
def _kind_key(kind: str, key: str) -> str:
    return f"{kind}.{key}" if kind in ("top", "gis") else kind


def _table_by_county(plans: list, sel: list, out, label: str) -> None:
    by_cty = Counter((p.cand.lead.state, p.cand.lead.county) for p in sel)
    dis = Counter((p.cand.lead.state, p.cand.lead.county) for p in plans)
    out(f"{label} BY COUNTY (all {len(by_cty)}; of the disagreeing leads in the county):")
    for (s, co), v in by_cty.most_common():
        out(f"  {s} {co:16}{v:>7,} of {dis[(s, co)]:,}")


def _has_coordinates(c: Cand) -> bool:
    v = _view(c)
    return bool(v.get("latitude") and v.get("longitude"))


def print_report(by_source: dict, plans: list, hold: dict | None, n_rows: int, out=print) -> None:
    from repair_burke_storm_damage_parcels import addresses_agree
    out(f"board rows scanned: {n_rows:,}")
    out("\nREPAIRABLE SOURCES (the scraper never sets a parcel_id): rows with a parcel and a street, and how they classed")
    out(f"  {'source':30}{'checked':>8}{'agrees':>8}{'disagrees':>10}{'not comparable':>15}{'id not in cache':>16}{'other skips':>12}")
    for src, c in sorted(by_source.items(), key=lambda kv: -sum(kv[1].values())):
        skips = sum(v for k, v in c.items() if k.startswith("skip_") or k in ("no_cache", "lookup_error"))
        cmp_ = c["situs_not_comparable"] + c["existing_situs_missing"]
        chk = c["agrees"] + c["disagrees"] + cmp_ + c["existing_id_not_in_cache"]
        out(f"  {src:30}{chk:>8,}{c['agrees']:>8,}{c['disagrees']:>10,}{cmp_:>15,}{c['existing_id_not_in_cache']:>16,}{skips:>12,}")
    out("  (every other source keeps its parcel: its parcel_id is the source's own, so a differing address is not evidence against it)")
    st = Counter(p.status for p in plans)
    out(f"\nDISAGREEING PARCELS: {len(plans):,}   REPLACED {st['replace']:,}   WITHDRAWN {st['withdraw']:,}   left: " + (", ".join(
        f"{k[5:]} {v:,}" for k, v in st.most_common() if k not in ("replace", "withdraw")) or "none"))

    # ------------------------------------------------------------------------------------------- replaced
    rep = [p for p in plans if p.status == "replace"]
    out("\nREPLACED BY SOURCE: " + ", ".join(f"{k} {v:,}" for k, v in Counter(p.cand.lead.source.split(".")[-1] for p in rep).most_common()))
    out("REPLACED BY STATE: " + ", ".join(f"{k} {v:,}" for k, v in Counter(p.cand.lead.state for p in rep).most_common()))
    _table_by_county(plans, rep, out, "REPLACED")
    a = Counter((p.old_agrees, p.new_agrees) for p in rep)
    out("\nOWNER EVIDENCE on the replaced (existing parcel agrees with lead owner, new parcel agrees): " + ", ".join(
        f"({o}, {n}) {v:,}" for (o, n), v in a.most_common()))
    cl = Counter(_kind_key(k, key) for p in rep for k, key, _v in p.ops)
    out("CLEARED on the replaced (value provably from the old parcel; refilled by the next join): " + (", ".join(
        f"{k} {v:,}" for k, v in cl.most_common()) or "nothing"))
    out(f"  replaced leads with at least one field cleared: {sum(1 for p in rep if p.ops):,} of {len(rep):,}")
    left: Counter = Counter()
    for p in rep:
        row = _view(p.cand)
        gone = {key for kind, key, _v in p.ops if kind == "gis"} | ({"last_sale"} if any(k == "gis_last_sale" for k, _a, _b in p.ops) else set())
        g = row.raw.get("gis")
        for k in (g if isinstance(g, dict) else {}):
            if k not in gone:
                left[f"gis.{k}"] += 1
        for k in ("gis_attrs_full", "parcel_from_geo", "calc", "distress_stack"):
            if k in row.raw and not any(kind == k for kind, _a, _b in p.ops):
                left[k] += 1
    out("LEFT ON THE REPLACED LEADS (not provably from the old parcel, or derived; recompute_valuation and the scorer refresh the derived ones): "
        + (", ".join(f"{k} {v:,}" for k, v in left.most_common(14)) or "nothing"))
    chg = []
    for p in rep:
        old_v = next((v for kind, key, v in p.ops if kind == "top" and key == "market_value"), None)
        new_v = dict(zip(R._COLS[1:], p.res.group.cols)).get("market_value")
        if old_v and new_v:
            chg.append((float(old_v), float(new_v)))
    if chg:
        import statistics
        big = sum(1 for o, n in chg if abs(n - o) > 0.2 * o)
        out(f"MARKET VALUE, {len(chg):,} replaced leads that had the old parcel's: median old {statistics.median(o for o, _ in chg):,.0f}, "
            f"median new {statistics.median(n for _, n in chg):,.0f}; the new value differs from the old by more than 20% on {big:,} ({100 * big / len(chg):.0f}%)")

    # ------------------------------------------------------------------------------------------ withdrawn
    wd = [p for p in plans if p.status == "withdraw"]
    out(f"\nWITHDRAWN {len(wd):,}: a parcel at another address and no unique replacement, so the values copied from it are blanked and the parcel_id cleared")
    out("  by why there is no replacement: " + ", ".join(f"{k[5:]} {v:,}" for k, v in Counter(p.why for p in wd).most_common()))
    out("  by source: " + ", ".join(f"{k} {v:,}" for k, v in Counter(p.cand.lead.source.split(".")[-1] for p in wd).most_common()))
    out("  by state: " + ", ".join(f"{k} {v:,}" for k, v in Counter(p.cand.lead.state for p in wd).most_common()))
    same_street = 0
    for p in wd:
        a0, _w = R.parse_street(p.cand.lead.street)
        names = {b0.name for b0 in (R.parse_street(x)[0] for x in str(p.cand.old_hit.get("address") or "").split(";")) if b0}
        same_street += bool(a0 and a0.name in names)
    out(f"  the old parcel sits on the SAME street (another house number): {same_street:,}; on another street: {len(wd) - same_street:,}")
    out("  the lead's owner against the old parcel's (agrees True is never withdrawn): " + ", ".join(
        f"{k} {v:,}" for k, v in Counter(p.old_agrees for p in wd).most_common()))
    wcl = Counter(_kind_key(k, key) for p in wd for k, key, _v in p.ops)
    out("  CLEARED (value equals the old cache row's): " + (", ".join(f"{k} {v:,}" for k, v in wcl.most_common()) or "nothing"))
    out(f"  withdrawn leads with at least one field cleared: {sum(1 for p in wd if p.ops):,} of {len(wd):,}; with no copied value to clear: {sum(1 for p in wd if not p.ops):,} (parcel_id still cleared)")
    out(f"  withdrawn leads that carry coordinates: {sum(1 for p in wd if _has_coordinates(p.cand)):,} (enrichment_parcel_from_geo would re-attach a parcel from them on a full pipeline run)")
    wviol = sum(1 for p in wd if addresses_agree(p.cand.lead.street, p.cand.old_hit.get("address"))
                or R.name_level_agree(p.cand.lead.street, p.cand.old_hit.get("address")))
    _table_by_county(plans, wd, out, "WITHDRAWN")
    kept = Counter(p.status for p in plans if p.status not in ("replace", "withdraw"))
    out("\nLEFT AS THEY ARE (a guard applies): " + (", ".join(f"{k[5:]} {v:,}" for k, v in kept.most_common()) or "none")
        + "  (owner agrees: the street is more likely the typo; same parcel; cache unreadable)")
    violations = 0
    for p in rep:
        if addresses_agree(p.cand.lead.street, p.cand.old_hit.get("address")) or R.name_level_agree(p.cand.lead.street, p.cand.old_hit.get("address")):
            violations += 1
    out(f"GUARD CHECK: replaced or withdrawn leads whose existing parcel agrees with the street by the Burke or name test: {violations + wviol} (must be 0)")
    if hold is not None:
        ag = hold["agree"]
        out(f"\nHOLD-OUT 1, what the disagreement test does to {ag['checked']:,} hold-out leads (any source with a parcel and a street): "
            f"agrees {ag['agrees']:,} (never touched: neither replaced nor withdrawn), disagrees {ag['disagrees']:,} (the only ones that go on to resolution), "
            f"not comparable {ag['situs_not_comparable'] + ag['existing_situs_missing']:,}, id not in cache {ag['existing_id_not_in_cache']:,}")
        out("HOLD-OUT 2, corrupt and repair (give a verified lead a wrong parcel, run the production path: the true parcel comes back, or the wrong one is withdrawn)")
        for kind, label in (("neighbour", "wrong parcel on the SAME street (other number)"), ("other_street", "wrong parcel on ANOTHER street")):
            c = hold[kind]
            done = c["restored"] + c["WRONG"]
            prec = 100 * c["restored"] / done if done else 0.0
            rec = 100 * c["restored"] / c["corrupted"] if c["corrupted"] else 0.0
            out(f"  {label:48} corrupted {c['corrupted']:6,}  restored {c['restored']:6,}  wrong {c['WRONG']:4,}  "
                f"precision {prec:6.2f}%  recall {rec:5.1f}%   withdrawn (wrong parcel blanked) {c['withdrawn']:,}; kept, owner agrees with the wrong parcel "
                f"{c['kept_owner_agrees_with_decoy']:,}; left: " + ", ".join(f"{k[5:]} {v:,}" for k, v in c.most_common() if k.startswith("left_")))
        for s in hold["wrong_samples"][:8]:
            out("    WRONG " + " | ".join(str(x) for x in s))


def _dry_run(rows_file, holdout: bool, withdraw: bool = True) -> int:
    n = 0

    def rows():
        nonlocal n
        for d in iter_rows(rows_file):
            n += 1
            yield d
    corpus, cands, by_source, overall = _collect(rows(), listings=False, keep_holdout=holdout)
    plans = plan_candidates(cands, corpus, withdraw=withdraw)
    hold = evaluate_repair_holdout(corpus) if holdout else None
    print_report(by_source, plans, hold, n)
    print("\nOVERALL, rows with a parcel: " + ", ".join(f"{k} {v:,}" for k, v in overall.most_common()))
    print("\nDRY RUN, nothing written, no network. Re-run with --apply (as the only board process).")
    return 0


def _apply() -> int:
    from _dq_common import run_apply
    return run_apply("repair_parcel_from_address", apply_rows, REQUIRED_RAW_KEYS, BACKUP_NAME)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the board (board_lock + load_board + write_artifact)")
    ap.add_argument("--dry-run", action="store_true", help="accepted; a dry run is the default")
    ap.add_argument("--rows-file", help="dry run over a saved board-format JSONL extract instead of the live board")
    ap.add_argument("--no-holdout", action="store_true", help="skip the corrupt-and-repair hold-out")
    ap.add_argument("--no-withdraw", action="store_true", help="dry run only: replace, but do not withdraw the leads with no unique replacement")
    args = ap.parse_args()
    if args.apply and not args.dry_run:
        if args.rows_file:
            raise SystemExit("--rows-file is dry-run only")
        return _apply()
    return _dry_run(args.rows_file, not args.no_holdout, not args.no_withdraw)


if __name__ == "__main__":
    raise SystemExit(main())
