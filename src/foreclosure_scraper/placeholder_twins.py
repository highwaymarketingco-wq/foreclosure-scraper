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

The merge itself is always Listing.merge() with the re-scraped (fresh) row as the base, so fresh
wins on conflicting fields and the old row backfills missing ones; fold() then keeps the old
row's numbered situs over the fresh row's sentinel string, which is the address the board was
already publishing.
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
from .web_artifact import _PLACEHOLDER_HOUSE_NUM_RE

#: validation.py nulls a parcel id under 7 characters as too short to be unique; same floor.
MIN_PARCEL_LEN = 7

#: Largest group (live row + its old copies) the cleanup will collapse. Same number as
#: board_selfcheck.FUSION_THRESHOLD / dedupe.suspicious_parcel_keys: 4+ rows under one parcel is
#: the shape of a fused or placeholder id, not of one property landed twice.
MAX_GROUP_ROWS = 4

#: raw keys that mark a parcel id a resolver attached, rather than one the source published.
RESOLVER_PARCEL_KEYS = ("parcel_from_geo", "parcel_from_address")


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
    except that a base whose situs is a no-number sentinel takes ``other``'s numbered situs.
    Listing.merge() would keep the sentinel (it is non-null), and the sentinel is exactly what
    _to_dict nulls on publish, so without this the address the board was showing would vanish."""
    merged = base.merge(other)
    if is_sentinel_address(base.street_address) and real_house_no(other.street_address):
        merged.street_address = other.street_address
    return merged


def clear_reappeared(li: Listing, *, keep_stale_case: bool = False) -> None:
    """The live row absorbed an aging copy: drop the copy's pulled_sale miss counter, its
    presumed_withdrawn tag and its raw['stale_case'] flag (Listing.merge() backfills all three
    onto the live row); dedupe.drop_withdrawn_tags(), the rule dedupe() applies too."""
    drop_withdrawn_tags(li, keep_stale_case=keep_stale_case)


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

    def ident(self) -> list:
        return [self.source, self.street_address, self.first_seen, self.last_seen]

    def sample(self) -> dict:
        return {"row": self.ident(), "parcel_id": self.parcel_id, "aged_copy_source":
                self.aged_source, "also_seen_in": list(self.also_seen_in), "status": self.status,
                "hot_demoted": self.hot_demoted}


def _reseen_view(idx: int, row: Any) -> _Reseen:
    d = _view_fields(row)
    raw = _raw(row)
    ps = raw.get("pulled_sale")
    return _Reseen(idx=idx, source=str(d.get("source") or ""), street_address=d.get("street_address"),
                   first_seen=_stamp(d.get("first_seen")), last_seen=_stamp(d.get("last_seen")),
                   parcel_id=_get(row, "parcel_id"), status=_get(row, "auction_status"),
                   aged_source=ps.get("last_seen_source") if isinstance(ps, dict) else None,
                   hot_demoted=_hot_demoted_by_tag(raw),
                   also_seen_in=tuple(sorted(sources_of(None, raw))))


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
        drop_withdrawn_tags(li)
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
            order = lambda v: (v.source, v.last_seen, v.idx)  # noqa: E731
            out["reseen"] = {
                "seen_since": self.seen_since,
                "rows_repaired": len(self.reseen),
                "by_source": dict(Counter(v.source for v in self.reseen).most_common()),
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

    RESEEN ROWS (only when ``seen_since``, the run's start, is given): a row carrying
    raw['pulled_sale'] whose last_seen is at or after ``seen_since`` absorbed a row created
    this run (see the block comment above parse_stamp()) and is planned for repair_reseen().
    A repaired row counts as live for the twin rule too.

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
    carry_below = 0
    n = 0
    for n, row in enumerate(rows(), start=1):
        raw = _raw(row)
        if raw.get("pulled_sale"):
            if cut is None:
                continue
            ls = parse_stamp(_get(row, "last_seen"))
            if ls is None or ls < cut:
                if ls is not None and (below is None or ls > below):
                    below = ls
                carry_below += bool(raw.get("carryover"))
                continue
            if above is None or ls < above:
                above = ls
            plan.reseen.append(_reseen_view(n - 1, row))
            revived.add(n - 1)
        addr = _get(row, "street_address")
        if real_house_no(addr) or has_unit(addr):
            continue
        k = parcel_key(_get(row, "state"), _get(row, "county"), _get(row, "parcel_id"))
        if k is None or resolver_parcel(raw):
            continue
        seeds[k] = seeds.get(k, 0) + 1
    plan.rows_scanned = n
    if cut is not None:
        plan.evidence = {
            "newest_tagged_last_seen_before_cutoff": below.isoformat() if below else None,
            "oldest_tagged_last_seen_at_or_after_cutoff": above.isoformat() if above else None,
            "tagged_carryover_rows_before_cutoff_not_judged": carry_below,
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


#: A twin group's live row keeps ITS OWN scored outputs from this run. Listing.merge() lets the
#: absorbed copy win raw leaf collisions, and each aging copy was scored (and down-ranked for its
#: tag) as a row of its own in the tail; nothing re-scores at publish.
_KEEP_SCORED_RAW_KEYS = ("distress_stack", "signal_stack", "intent_score", "intent_band")


def apply_collapse(listings: list[Listing], plan: CollapsePlan,
                   today: Optional[date] = None) -> dict:
    """Apply ``plan`` to ``listings`` IN PLACE. Every planned row is re-checked against the
    plan's view of it first (CollapsePlanMismatch, nothing changed, if any differs). Then the
    reseen rows are repaired (repair_reseen()), and each twin group's live row absorbs its aging
    copies via fold() (newest copy first), loses the copies' withdrawn tags, keeps its own
    scored outputs, and the copies are removed."""
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
        if (now.ident() != v.ident() or not _raw(li).get("pulled_sale")
                or ls is None or cut is None or ls < cut):
            raise CollapsePlanMismatch(f"row {v.idx}: planned reseen {v.ident()} found {now.ident()}")

    reseen_stats = repair_reseen([listings[v.idx] for v in plan.reseen], today=today)

    dropped: set[int] = set()
    restored = 0
    for g in plan.groups:
        keep_idx = g["keep"].idx
        merged = listings[keep_idx]
        own = merged.raw if isinstance(merged.raw, dict) else {}
        keep_stale = bool(own.get("stale_case"))
        scored = {k: copy.deepcopy(own[k]) for k in _KEEP_SCORED_RAW_KEYS if k in own}
        for v in g["drop"]:
            before = merged.street_address
            merged = fold(merged, listings[v.idx])
            if merged.street_address != before:
                restored += 1
            dropped.add(v.idx)
        clear_reappeared(merged, keep_stale_case=keep_stale)
        merged.raw.update(scored)
        listings[keep_idx] = merged
    before_n = len(listings)
    listings[:] = [li for i, li in enumerate(listings) if i not in dropped]
    return {"groups": len(plan.groups), "rows_dropped": before_n - len(listings),
            "addresses_restored": restored, "rows_after": len(listings),
            "reseen_repaired": len(plan.reseen), "reseen": reseen_stats,
            "digest": plan.digest()}
