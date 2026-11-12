#!/usr/bin/env python3
"""Undo name-to-property resolutions whose owner is provably a different person (middle-name conflict).

Audit 2026-09-21 A6: enrichment_resolve_name_to_property commits a unique surname + first-name hit in the
right county. Its middle-name rule (_drop_middle_name_conflicts / middle_conflict) arrived AFTER many
resolutions were already on the board, and the older code path only FLAGGED a conflict
(raw['resolved_from_name']['middle_conflict'] = True) while still committing the parcel. A committed wrong
parcel puts a stranger's address, value and mailing address on a lead, so outreach can mail the wrong person.

Every lead with raw['resolved_from_name'] whose confidence is a commit ('exact', 'strong', 'unique_match')
is re-judged from its own provenance: the name the resolver searched (query_name, else defendant, else
owner_name) against the GIS owner it matched (matched_owner). PROVEN CONFLICT = the same surname and first
name with a middle INITIAL on both sides that differs (name_normalize.owner_last_first_middle, the
convention-aware reader party_middle_verdict is built on), OR name_normalize.middle_conflict (a spelled-out
middle name on both sides that differs). No middle on either side proves nothing and is left alone.

WHAT --apply DOES to a proven conflict:
  * RESOLVER-OWNED lead (its primary source names a person, not a property, and so does every source in
    `also_seen_in`; the resolver only ever targets a lead with no street and no parcel): the fields the
    resolution and the parcel-keyed enrichers wrote are blanked, and their old values are kept in
    raw['resolver_conflict_undone']['removed'] and in backups/: parcel_id, street_address, market_value,
    tax_value, assessed_value, living_sqft, acreage, land_use, year_built, lot_size_sqft, owner_name (only
    when it equals the matched GIS owner), and the parcel-derived raw blocks gis, gis_attrs_full,
    owner_mailing, situs_address_source, parcel_from_geo. city, zip and coordinates are LEFT (they cannot be
    proven resolver-written and are still right at the county level).
  * MERGED lead (the primary or an also_seen_in source is a parcel-native source such as a tax roll: the
    parcel and street may be its own): NOTHING is blanked; it is only stamped, so the operator sees it.
  * Both: raw['resolved_from_name']['confidence'] becomes 'middle_conflict_undone' (the old value is kept in
    'confidence_before') so no later stage keys off a resolution that was withdrawn, and
    raw['resolver_conflict_undone'] = {action, query_name, matched_owner, verdict, removed}.

    python scripts/undo_resolver_middle_conflicts.py            # dry run: counts by verdict / source / action
    python scripts/undo_resolver_middle_conflicts.py --apply    # ONLY board process (about 3 GB)
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dq_common import iter_rows, print_counter  # noqa: E402

COMMIT = {"exact", "strong", "unique_match"}
UNDONE = "middle_conflict_undone"
NATIVE_RATE_MIN = 0.5           # a source with this share of address/parcel-bearing rows names PROPERTIES
BLANK_FIELDS = ("parcel_id", "street_address", "market_value", "tax_value", "assessed_value", "living_sqft",
                "acreage", "land_use", "year_built", "lot_size_sqft")
BLANK_RAW = ("gis", "gis_attrs_full", "owner_mailing", "situs_address_source", "parcel_from_geo")


def _names():
    from foreclosure_scraper import name_normalize as nn
    return nn


def initial_verdict(query, matched) -> str:
    """'conflict' | 'agrees' | 'unverified' | 'different_name' | 'unparsed' from middle INITIALS."""
    nn = _names()
    a, b = nn.owner_last_first_middle(query), nn.owner_last_first_middle(matched)
    if not a or not b:
        return "unparsed"
    if a[0] != b[0] or a[1] != b[1]:
        return "different_name"
    if not a[2] or not b[2]:
        return "unverified"
    return "agrees" if a[2] == b[2] else "conflict"


def judge(prov: dict, owner_name, defendant) -> tuple[str, str | None]:
    """(verdict, name_used). verdict is 'conflict' only when PROVEN. Tries the name the resolver
    searched first, then the lead's own defendant / owner_name."""
    nn = _names()
    matched = str((prov or {}).get("matched_owner") or "").strip()
    if not matched:
        return "no_matched_owner", None
    cands: list[str] = []
    for s in ((prov or {}).get("query_name"), defendant, owner_name):
        s = str(s or "").strip()
        if s and s not in cands:
            cands.append(s)
    best = "different_name"
    for q in cands:
        if nn.middle_conflict(q, matched):
            return "conflict", q
        v = initial_verdict(q, matched)
        if v == "conflict":
            return "conflict", q
        if v in ("agrees", "unverified"):
            best = v if best == "different_name" or v == "agrees" else best
        elif v == "unparsed" and best == "different_name":
            best = "unparsed"
    return best, None


def is_resolver_owned(source, also_seen, native_rate: dict) -> bool:
    """True when neither the primary source nor any also_seen_in source names a property."""
    srcs = [source] + [a.get("source") for a in (also_seen or []) if isinstance(a, dict)]
    return all(native_rate.get(str(s), 0.0) < NATIVE_RATE_MIN for s in srcs if s)


def owned_removal(li_like: dict, matched: str) -> dict:
    """The {field: old value} a resolver-owned undo would blank, from a dict-shaped row."""
    out = {}
    for f in BLANK_FIELDS:
        if li_like.get(f) not in (None, "", 0):
            out[f] = li_like[f]
    on = str(li_like.get("owner_name") or "").strip()
    if on and on.upper() == matched.upper():
        out["owner_name"] = on
    return out


# --------------------------------------------------------------------------------------- dry run
def _dry_run(rows_file=None, rates_file=None) -> int:
    native_tot: Counter = Counter()
    native_yes: Counter = Counter()
    committed = []
    n = 0
    for r in iter_rows(rows_file):
        n += 1
        raw = r.get("raw") or {}
        prov = raw.get("resolved_from_name")
        src = str(r.get("source") or "")
        resolved = isinstance(prov, dict) and prov.get("queried") and prov.get("confidence") in (COMMIT | {UNDONE})
        if not resolved:
            native_tot[src] += 1
            if (r.get("street_address") or "").strip() or (r.get("parcel_id") or "").strip():
                native_yes[src] += 1
        if isinstance(prov, dict) and prov.get("confidence") in COMMIT and prov.get("queried"):
            committed.append((src, prov, r.get("owner_name"), r.get("defendant"), raw.get("also_seen_in"),
                              {f: r.get(f) for f in BLANK_FIELDS + ("owner_name",)}))
    if rates_file:                       # dev replay: rates saved from a full-board pass
        import json
        rates = json.load(open(rates_file))
    else:
        rates = {s: native_yes[s] / native_tot[s] for s in native_tot if native_tot[s]}
    print(f"board rows scanned: {n:,}; committed name resolutions: {len(committed):,}")
    v_c: Counter = Counter()
    act: Counter = Counter()
    by_src: Counter = Counter()
    rem: Counter = Counter()
    flagged_already = 0
    sample = []
    for src, prov, oname, dname, also, fields in committed:
        verdict, used = judge(prov, oname, dname)
        v_c[verdict] += 1
        if verdict != "conflict":
            continue
        if prov.get("middle_conflict"):
            flagged_already += 1
        owned = is_resolver_owned(src, also, rates)
        act["blank (resolver-owned)" if owned else "flag only (merged with a parcel-native source)"] += 1
        by_src[src.split(".")[-1]] += 1
        if owned:
            for f, _v in owned_removal(fields, str(prov.get("matched_owner") or "")).items():
                rem[f] += 1
        if len(sample) < 4:
            sample.append((src.split(".")[-1], used, prov.get("matched_owner"), "owned" if owned else "merged"))
    print_counter(v_c, "\nVERDICT OF COMMITTED RESOLUTIONS")
    print(f"\nPROVEN CONFLICTS: {v_c['conflict']:,} (already flagged middle_conflict=True by the resolver: {flagged_already:,})")
    print_counter(act, "action")
    print_counter(by_src, "by primary source")
    print_counter(rem, "fields that would be blanked (resolver-owned leads)")
    print("samples (source, searched name, matched owner, kind):", sample)
    print("DRY RUN, nothing written. Re-run with --apply (as the only board process).")
    return 0


# ----------------------------------------------------------------------------------------- apply
REQUIRED_RAW_KEYS = ["resolver_conflict_undone", "resolved_from_name", *BLANK_RAW]
BACKUP_NAME = "undo_resolver_middle_conflicts_removed"


def native_rates(rows: list) -> dict:
    """{source: share of its NON-resolved rows that carry a street or a parcel}, from Listing objects."""
    tot: Counter = Counter()
    yes: Counter = Counter()
    for li in rows:
        prov = li.raw.get("resolved_from_name") if isinstance(li.raw, dict) else None
        resolved = isinstance(prov, dict) and prov.get("queried") and prov.get("confidence") in (COMMIT | {UNDONE})
        if not resolved:
            tot[str(li.source)] += 1
            if (li.street_address or "").strip() or (li.parcel_id or "").strip():
                yes[str(li.source)] += 1
    return {s: yes[s] / tot[s] for s in tot if tot[s]}


def apply_rows(rows: list, *, dry_run: bool = False) -> dict:
    """Undo proven middle-name-conflict resolutions on Listing objects, in place. What was removed is returned
    under '_backup' (and kept in raw['resolver_conflict_undone']). Never changes len(rows), never writes a file.
    Run it BEFORE the address fill and the parcel-cache join. dry_run=True mutates nothing."""
    from _dq_common import assert_raw_keep
    if not dry_run:
        assert_raw_keep(REQUIRED_RAW_KEYS)
    n = len(rows)
    rates = native_rates(rows)
    c: Counter = Counter()
    backup: dict = {}
    for i, li in enumerate(rows):
        if not isinstance(li.raw, dict):
            continue
        prov = li.raw.get("resolved_from_name")
        if not (isinstance(prov, dict) and prov.get("queried") and prov.get("confidence") in COMMIT):
            continue
        c["committed resolutions"] += 1
        verdict, used = judge(prov, li.owner_name, li.defendant)
        if verdict != "conflict":
            continue
        matched = str(prov.get("matched_owner") or "")
        owned = is_resolver_owned(li.source, li.raw.get("also_seen_in"), rates)
        c["proven conflicts"] += 1
        c["blanked (resolver-owned)" if owned else "flag only (merged with a parcel-native source)"] += 1
        if dry_run:
            continue
        removed: dict = {}
        if owned:
            as_dict = {f: getattr(li, f, None) for f in BLANK_FIELDS + ("owner_name",)}
            removed = owned_removal(as_dict, matched)
            for f in removed:
                setattr(li, f, None)
            for k in BLANK_RAW:
                if k in li.raw:
                    removed.setdefault("raw", {})[k] = li.raw.pop(k)
        prov["confidence_before"] = prov.get("confidence")
        prov["confidence"] = UNDONE
        li.raw["resolver_conflict_undone"] = {
            "action": "blanked" if owned else "flag_only", "query_name": used, "matched_owner": matched,
            "verdict": "middle_conflict", "removed": removed}
        backup[str(i)] = {"source": li.source, "source_url": li.source_url, "action": "blanked" if owned else "flag_only",
                          "query_name": used, "matched_owner": matched, "removed": removed}
    assert len(rows) == n, "an undo must never change the row count"
    out = {k: v for k, v in c.items() if v}
    if backup:
        out["_backup"] = backup
    return out


def _apply() -> int:
    from _dq_common import run_apply
    return run_apply("undo_resolver_middle_conflicts", apply_rows, REQUIRED_RAW_KEYS, BACKUP_NAME)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the board (ONLY board process)")
    ap.add_argument("--rows-file", help="dry run over a saved JSONL extract instead of the live board")
    ap.add_argument("--rates-file", help="with --rows-file: JSON {source: share of rows with a parcel/street}")
    args = ap.parse_args()
    if not args.apply:
        return _dry_run(args.rows_file, args.rates_file)
    if args.rows_file:
        raise SystemExit("--rows-file is dry-run only")
    return _apply()


if __name__ == "__main__":
    raise SystemExit(main())
