#!/usr/bin/env python3
"""Grade the board against the one it replaced, and fail loudly when it should.

WHY THIS EXISTS
    Every real defect this system has produced was found by a human noticing, or
    by an audit someone thought to ask for. Not one was caught by the system.

    On 2026-08-11 alone: a manufactured home published a $780,300 ARV built from
    a warehouse's assessor row; one county appraisal was stamped on 1,433 leads
    and drove $320,145,300 of max bids; a noon job's 1,064 resolved addresses
    were silently reverted by a concurrent writer; 6,426 cards showed a satellite
    photo of a place 1-2 miles from the property. Every one of those published
    successfully. Nothing errored. The tests were green.

    That is the actual gap — not coverage, not sources. A board that cannot tell
    when it has gone wrong is a board you have to audit by hand forever.

WHAT IT DOES
    Compares the just-written board against the previously PUBLISHED one (the
    committed .gz in git), and reports two different things:

      INVARIANTS  — statements that must be true of any board we publish.
                    A breach exits non-zero. These are not thresholds or
                    heuristics; each one means a specific known defect is back.

      MOVEMENT    — how much changed since the last publish, per field. This
                    does not fail. It is the signal a human reads to notice
                    "why did 4,000 ARVs move when I only edited the CSS?".
                    Silent, unexplained movement is how all of the above got in.

WHY MOVEMENT IS REPORTED AND NOT ENFORCED
    A legitimate run moves a lot: a fresh scrape adds leads, a vision pass
    scores 12,000 of them, a valuation fix withdraws $72M of max bid on purpose.
    Thresholding that would either fire constantly (and be ignored, which is
    worse than nothing) or be set so loose it never fires. So movement is
    printed, loudly and comparably, for a human to sanity-check against what
    they believe they changed.

USAGE
    uv run python scripts/board_selfcheck.py            # vs the last commit
    uv run python scripts/board_selfcheck.py --json     # machine-readable
    uv run python scripts/board_selfcheck.py --against <git-ref>

    Exit 0 = every invariant held. Exit 1 = at least one breached.
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
SLIM = "docs/listings_slim.json.gz"

#: Flags that mean the valuation itself is disputed. A lead carrying one of
#: these must not publish money derived from the ARV. Kept in sync with
#: valuation.grading.ARV_FLAGS_CONTRADICTED — imported rather than restated so a
#: rename cannot make this check silently vacuous, which is the exact failure
#: mode (a reader and a writer disagreeing) that produced five separate silent
#: defects in one day.
try:
    sys.path.insert(0, str(REPO / "src"))
    from foreclosure_scraper.valuation.grading import ARV_FLAGS_CONTRADICTED
    CONTRADICTED = frozenset(ARV_FLAGS_CONTRADICTED)
except Exception:  # noqa: BLE001 - the check must still run from a bare checkout
    CONTRADICTED = frozenset({
        "anchor_shared_across_parcels", "bid_proxy_arv", "arv_above_anchor",
        "arv_above_list_price", "arv_land_sqft_mismatch", "arv_proxy_above_ceiling",
        "arv_above_plausible_max", "arv_implies_implausible_roi",
    })

MONEY_FIELDS = ("max_bid_70", "roi_pct", "estimated_profit", "wholesale_mao")


def _load_gz(raw: bytes) -> list:
    return json.loads(gzip.decompress(raw).decode("utf-8"))


def _current() -> list:
    p = DOCS / "listings_slim.json.gz"
    if not p.exists():
        raise SystemExit("no docs/listings_slim.json.gz — nothing to check")
    return _load_gz(p.read_bytes())


def _previous(ref: str) -> list | None:
    r = subprocess.run(["git", "show", f"{ref}:{SLIM}"],
                       cwd=REPO, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        return _load_gz(r.stdout)
    except Exception:  # noqa: BLE001
        return None


def _calc(rec) -> dict:
    return ((rec or {}).get("raw") or {}).get("calc") or {}


def _identifier(rec) -> str | None:
    """A value that genuinely distinguishes ONE property, or None.

    Returns None deliberately and often. The first version of this used
    address+case+county+state+source with empty-string fallbacks, and reported
    8,241 duplicates on a board that has almost none:

      7,901 of them were leads where BOTH address and case_number are empty, so
            every address-less lead in a county collapsed onto one key;
        644 were parcels sharing a road name with no house number — "SR 1135",
            "HWY 226", "OFF PARKER PADGETT RD" in McDowell — which are distinct
            properties that simply have no street number to tell them apart.

    Neither is a duplicate. A guard that fires on 8,241 good leads is worse than
    no guard, because the next person deletes it and takes the real check with
    it.

    Two further identifiers were tried and rejected on the evidence:

      source_url — identifies the SOURCE DOCUMENT, not the property. 80 leads
        share one Lincoln County delinquent-tax PDF; 8 share one Asheville
        permits endpoint. Every one is a different house.
      case_number — one foreclosure case routinely covers several parcels, so a
        shared case is normal, not a collision.

    What is left is what actually names a property: the county's own parcel id,
    or a street address carrying a house number. When a lead has neither, this
    returns None and the lead is excluded from the duplicate count rather than
    guessed at.
    """
    r = rec or {}
    pid = str(r.get("parcel_id") or "").strip()
    if pid:
        return f"parcel:{(r.get('county') or '').lower()}:{pid.lower()}"
    addr = str(r.get("street_address") or "").strip()
    parts = addr.split()
    if parts and any(ch.isdigit() for ch in parts[0]):
        return f"addr:{(r.get('county') or '').lower()}:{addr.lower()}"
    return None


def _key(rec) -> str:
    """Stable identity for MATCHING a lead across two publishes.

    Falls back to a composite so every lead gets compared; unlike _identifier
    this is allowed to be imprecise, because a wrong match here only mislabels a
    lead as changed rather than asserting a defect.
    """
    return _identifier(rec) or "|".join(
        str((rec or {}).get(f) or "") for f in
        ("street_address", "case_number", "county", "state", "source"))


def invariants(board: list) -> list[dict]:
    """Each entry is a statement that must be true. Breach = a known defect is back."""
    out = []

    contra = [r for r in board if any(f in (_calc(r).get("arv_flags") or [])
                                      for f in CONTRADICTED)]
    for field in MONEY_FIELDS:
        bad = [r for r in contra if _calc(r).get(field)]
        out.append({
            "name": f"no {field} on a contradicted ARV",
            "count": len(bad), "must_be": 0, "ok": not bad,
            "why": "the valuation disputes its own number; money derived from it "
                   "is a bid instruction built on a figure we refused to stand behind",
        })

    bad = [r for r in contra if _calc(r).get("deal_status")]
    out.append({"name": "no deal verdict on a contradicted ARV", "count": len(bad),
                "must_be": 0, "ok": not bad,
                "why": "a green GREAT beside a red do-not-bid warning is how this "
                       "shipped before"})

    bad = [r for r in contra if (((r.get("raw") or {}).get("equity") or {}).get("value"))]
    out.append({"name": "no equity on a contradicted ARV", "count": len(bad),
                "must_be": 0, "ok": not bad,
                "why": "equity is ARV minus payoff; on a disputed ARV it is the same "
                       "disputed number wearing a different label, and it feeds the "
                       "HOT/WARM ranking"})

    big = [r for r in board if (_calc(r).get("arv_expected") or 0) > 2_000_000]
    bad = [r for r in big if _calc(r).get("max_bid_70")]
    out.append({"name": "no max bid on an ARV over $2M", "count": len(bad),
                "must_be": 0, "ok": not bad,
                "why": "no comparable property in these counties has fetched that; "
                       "the grader already refuses to letter-grade them"})
    bad = [r for r in big if not _calc(r).get("arv_flags")]
    out.append({"name": "every ARV over $2M carries a flag", "count": len(bad),
                "must_be": 0, "ok": not bad,
                "why": "an unflagged $2M+ ARV is indistinguishable from a real one"})

    ids = [i for i in (_identifier(r) for r in board) if i]
    dupes = len(ids) - len(set(ids))
    unidentifiable = len(board) - len(ids)
    out.append({"name": "no duplicate identifiable properties", "count": dupes,
                "must_be": 0, "ok": dupes == 0,
                "why": "two rows for one property double-count it in every total "
                       f"and split its enrichment ({unidentifiable:,} leads carry no "
                       "parcel/case/url/numbered-address and are excluded — they "
                       "cannot be judged either way)"})
    return out


def movement(cur: list, prev: list) -> dict:
    """What changed since the last publish. Reported, never enforced."""
    pi = {_key(r): r for r in prev}
    matched = gained = lost = 0
    moved: dict[str, int] = {f: 0 for f in ("arv_expected",) + MONEY_FIELDS}
    big_moves = []
    for r in cur:
        p = pi.get(_key(r))
        if p is None:
            gained += 1
            continue
        matched += 1
        c, pc = _calc(r), _calc(p)
        for f in moved:
            a, b = c.get(f), pc.get(f)
            if a != b:
                moved[f] += 1
                if f == "arv_expected" and a and b:
                    try:
                        if abs(a - b) / max(b, 1) >= 1.0:
                            big_moves.append((abs(a - b), r.get("street_address"), b, a))
                    except Exception:  # noqa: BLE001
                        pass
    ck = {_key(r) for r in cur}
    lost = sum(1 for r in prev if _key(r) not in ck)
    # Sort on the delta ONLY. A bare reverse=True falls through to comparing the
    # next tuple element when deltas tie, and street_address is None on hundreds
    # of leads, which raises str < NoneType and takes down the whole check.
    big_moves.sort(key=lambda t: t[0], reverse=True)
    return {
        "prev_count": len(prev), "curr_count": len(cur),
        "matched": matched, "new": gained, "dropped": lost,
        "changed": moved,
        "largest_arv_moves": [
            {"address": a, "from": b, "to": c2} for _, a, b, c2 in big_moves[:10]
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--against", default="HEAD",
                    help="git ref holding the board to compare against (default HEAD)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cur = _current()
    inv = invariants(cur)
    prev = _previous(args.against)
    mv = movement(cur, prev) if prev else None
    breached = [i for i in inv if not i["ok"]]

    if args.json:
        print(json.dumps({"invariants": inv, "movement": mv,
                          "breached": len(breached)}, indent=1, default=str))
        return 1 if breached else 0

    print(f"BOARD SELF-CHECK — {len(cur):,} leads\n")
    print("INVARIANTS (a breach means a known defect is back)")
    for i in inv:
        mark = "ok " if i["ok"] else "FAIL"
        print(f"  [{mark}] {i['name']:44} {i['count']:>6,} (must be {i['must_be']})")
        if not i["ok"]:
            print(f"         why it matters: {i['why']}")

    if mv is None:
        print(f"\nMOVEMENT: no previous board at {args.against} — nothing to compare.")
    else:
        print(f"\nMOVEMENT vs {args.against}")
        print(f"  leads      {mv['prev_count']:,} -> {mv['curr_count']:,}"
              f"   (+{mv['new']:,} new / -{mv['dropped']:,} dropped / {mv['matched']:,} matched)")
        for f, n in mv["changed"].items():
            pct = (n / mv["matched"] * 100) if mv["matched"] else 0
            print(f"  {f:20} changed on {n:>6,} matched leads  ({pct:4.1f}%)")
        if mv["largest_arv_moves"]:
            print("\n  largest ARV moves (>=2x) — check these against what you changed:")
            for m in mv["largest_arv_moves"][:6]:
                print(f"    {str(m['address'])[:34]:36} "
                      f"{(m['from'] or 0):>12,.0f} -> {(m['to'] or 0):>12,.0f}")
        print("\n  Movement never fails this check. A real run moves a lot: a scrape adds")
        print("  leads, a vision pass scores thousands, a valuation fix withdraws money on")
        print("  purpose. It is printed so a human can ask 'why did that move when I only")
        print("  changed the CSS?' — which is the question nothing was asking before.")

    if breached:
        print(f"\n{len(breached)} INVARIANT(S) BREACHED — do not publish this board.")
        return 1
    print("\nAll invariants held.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
