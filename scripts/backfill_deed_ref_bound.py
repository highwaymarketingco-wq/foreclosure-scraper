#!/usr/bin/env python3
"""One-time repair for top80-fill-deed-ref-bound (audit 2026-10-18 gap-sweep continuation).

Two mechanisms published ~978 rows (1,453 violations) whose raw['county_deed_ref'] /
raw['county_legal'] names a DIFFERENT parcel than the row's own identity, both already fixed in
gis_fill.py / enrichment_court_owner_verify.py for FUTURE writes (commits e34f72cb, 6ebfaf1b,
both 2026-10-17 -- a day after this board's run_time of 2026-10-16T20:24:46Z) but unable to
retroactively heal what is already published:

  1. "wrong parno echoed" -- row.parcel_id is still set. gis_fill.fetch_nc()/fetch_nc_like()
     used to unconditionally echo a feature's `parno` field as provenance even when the row's
     own pin actually matched the feature's `altparno` -- a feature can carry BOTH ids for the
     SAME parcel. The deed/legal CONTENT was always correct; only the written 'parno' id was a
     foreign-looking value. Fix: re-run the CURRENT (already-fixed) fetch_nc() / fetch_nc_like()
     against the row's own parcel_id, confirm the re-fetched book/page (deed) or text (legal)
     is IDENTICAL to what's already published (proving this is purely the parno-echo bug and not
     some other data problem), and only then correct the block's 'parno' field in place.
     Anything that doesn't re-confirm this way (layer no longer has the parcel, content
     disagrees) is left alone and reported, never guessed at.

  2. "stale block after a court-verify strip" -- row.parcel_id is already null (correctly
     cleared by enrichment_court_owner_verify._strip_property). PROPERTY_SIGNAL_BLOCKS used to
     omit county_deed_ref / county_legal / gis_fill, so a strip that ran before the 2026-10-17
     fix left those three blocks behind, still naming the old (wrong) parcel. Fix: move exactly
     those three keys (whichever are present) into raw['unbound_property_blocks'], byte-for-byte
     what _strip_property(blocks=True) does today -- no network, no guessing, a pure data move.

Usage:
    python scripts/backfill_deed_ref_bound.py --dry-run
    python scripts/backfill_deed_ref_bound.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import gis_fill as G  # noqa: E402
from foreclosure_scraper.enrichment_court_owner_verify import PROPERTY_SIGNAL_BLOCKS  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

#: the three keys this backfill moves for a stale-strip row -- exactly the gis_fill-owned subset
#: of PROPERTY_SIGNAL_BLOCKS (the task at hand; the other PROPERTY_SIGNAL_BLOCKS keys are not
#: this check's business and a different sweep already covers lincoln_bulk et al.).
_GIS_FILL_KEYS = ("county_deed_ref", "county_legal", "gis_fill")
assert set(_GIS_FILL_KEYS) <= set(PROPERTY_SIGNAL_BLOCKS), "PROPERTY_SIGNAL_BLOCKS no longer covers these keys"

#: fetch_nc / fetch_nc_like batch size, same constant gis_fill.py's own pipeline uses
BATCH = G.BATCH


def _raw(li: Any) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


def _aliases(pin: Any) -> set[str]:
    return set(G.pin_aliases(pin))


def _other_parcel(block: Any, own_pin: Any) -> bool:
    """True when `block` is a county_deed_ref / county_legal dict naming a parno that is not an
    alias of `own_pin` -- the exact condition scripts/audit_checks/top80_fill.py's Bound check
    flags (source restricted to nc_onemap / *_parcel_layer, same as that check)."""
    if not isinstance(block, dict) or not block.get("parno"):
        return False
    src = str(block.get("source") or "")
    if src != "nc_onemap" and not src.endswith("_parcel_layer"):
        return False
    return not (_aliases(block["parno"]) & _aliases(own_pin))


def classify(li: Any) -> Optional[str]:
    """'wrong_parno' | 'stale_strip' | None (not a violation this script repairs)."""
    raw = _raw(li)
    hit = any(_other_parcel(raw.get(k), li.parcel_id) for k in ("county_deed_ref", "county_legal"))
    if not hit:
        return None
    return "stale_strip" if not li.parcel_id else "wrong_parno"


def _nc_county(li: Any) -> str:
    co = G.county_name(li)
    if str(li.state).upper() == "NC":
        from foreclosure_scraper.quiet_title.adapters.nc_onemap import canonical_county
        co = canonical_county(co) or co
    return co


def _fetch_live(county: str, pins: list[str]) -> dict[str, dict]:
    """{pin: matched} for every pin found by the current fetch_nc(), falling back to
    fetch_nc_like() (the real pipeline's second pass) for the pins the exact pass misses.
    Pins the layer never answers for at all (down, closed, truly not found) are left out."""
    found: dict[str, dict] = {}
    todo = list(pins)
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        got = G.fetch_nc(county, chunk)
        if got is None:
            continue
        for p in chunk:
            m = got.get(p)
            if m is not None:
                found[p] = m
    missing = [p for p in todo if p not in found]
    for i in range(0, len(missing), G.LIKE_BATCH):
        chunk = missing[i:i + G.LIKE_BATCH]
        got = G.fetch_nc_like(county, chunk)
        if got is None:
            continue
        for p in chunk:
            m = got.get(p)
            if m is not None:
                found[p] = m
    return found


def corrected_parno(block: Any, matched: Optional[dict], own_pin: Any) -> Optional[str]:
    """The live-refetched parno to replace `block['parno']` with, or None when the re-fetch does
    not clearly confirm the parno-echo mechanism for THIS block (no match, content disagrees, or
    the new parno still doesn't alias own_pin) -- caller must then leave the row untouched."""
    if not isinstance(block, dict) or matched is None:
        return None
    new_parno = matched.get("parno")
    if not (_aliases(new_parno) & _aliases(own_pin)):
        return None
    if "book" in block or "page" in block:  # county_deed_ref shape
        d = matched.get("deed")
        if not isinstance(d, dict) or d.get("book") != block.get("book") or d.get("page") != block.get("page"):
            return None
    else:  # county_legal shape
        if matched.get("legal") != block.get("text"):
            return None
    return new_parno


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="deed_ref_bound_backfill")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows: {before:,}")

        wrong_parno: list = []
        stale_strip: list = []
        for li in rows:
            kind = classify(li)
            if kind == "wrong_parno":
                wrong_parno.append(li)
            elif kind == "stale_strip":
                stale_strip.append(li)
        print(f"wrong_parno candidates: {len(wrong_parno):,}   stale_strip candidates: {len(stale_strip):,}")

        c = Counter()

        # --- mechanism 1: re-derive the correct parno live, only touch confirmed matches -------
        by_county: dict[str, list] = {}
        for li in wrong_parno:
            if str(li.state).upper() != "NC":
                c["wrong_parno_skip_non_nc_state"] += 1
                continue
            raw = _raw(li)
            if any(str((raw.get(k) or {}).get("source") or "") not in ("nc_onemap",)
                   for k in ("county_deed_ref", "county_legal") if _other_parcel(raw.get(k), li.parcel_id)):
                c["wrong_parno_skip_non_nc_onemap_source"] += 1
                continue
            by_county.setdefault(_nc_county(li), []).append(li)

        for county, lis in sorted(by_county.items()):
            pins = sorted({str(li.parcel_id).strip() for li in lis})
            matched_by_pin = _fetch_live(county, pins)
            for li in lis:
                pin = str(li.parcel_id).strip()
                matched = matched_by_pin.get(pin)
                raw = dict(_raw(li))
                changed = False
                for key in ("county_deed_ref", "county_legal"):
                    block = raw.get(key)
                    if not _other_parcel(block, li.parcel_id):
                        continue
                    new_parno = corrected_parno(block, matched, li.parcel_id)
                    if new_parno is None:
                        c[f"wrong_parno_skip_unconfirmed_{key}"] += 1
                        continue
                    if not args.dry_run:
                        raw[key] = {**block, "parno": new_parno}
                    changed = True
                    c[f"wrong_parno_fixed_{key}"] += 1
                    c[f"wrong_parno_fixed_county:{county}"] += 1
                if changed and not args.dry_run:
                    li.raw = raw

        # --- mechanism 2: move the three stale blocks aside, exactly like _strip_property -----
        for li in stale_strip:
            raw = dict(_raw(li))
            moved = {k: raw.pop(k) for k in _GIS_FILL_KEYS if k in raw}
            if not moved:
                continue
            c["stale_strip_fixed"] += 1
            c[f"stale_strip_fixed_county:{li.county}"] += 1
            if not args.dry_run:
                raw.setdefault("unbound_property_blocks", {}).update(moved)
                li.raw = raw

        print("\nby kind:")
        for k, v in sorted(c.items()):
            if ":" not in k:
                print(f"    {k:40} {v:,}")
        print("\nby county (fixed only):")
        for k, v in sorted(c.items()):
            if ":" in k:
                print(f"    {k:40} {v:,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0
        if not (c["wrong_parno_fixed_county_deed_ref"] or c["wrong_parno_fixed_county_legal"]
                or c["stale_strip_fixed"]):
            print("\nnothing to do.")
            return 0
        assert len(rows) == before, "row count changed -- refusing to write"
        write_artifact(rows, dict(c), docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged, repairs above applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
