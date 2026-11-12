#!/usr/bin/env python3
"""Staleness sweep — flag leads that are no longer actionable or have gone quiet.

The board persists leads across runs and re-enriches them; the daily run bumps
``last_seen`` on every lead a source re-lists. Two things go stale:

  1. AUCTION PASSED — the sale/upset window is over. NC upset bids restart the
     10-day clock on each successful upset, so a PAST sale_date does NOT mean
     dead; the authoritative signal is ``upset_bid_deadline``. Rule:
       - upset_bid_deadline present and < today            -> "upset_closed"
       - else sale_date present and < today-GRACE          -> "sale_passed"
  2. GONE QUIET — not re-seen by any source in STALE_UNSEEN_DAYS. The listing
     likely resolved/withdrew/sold. Rule: last_seen < today - STALE_UNSEEN_DAYS.

Modes:
  --report  (default, READ-ONLY): writes docs/staleness_report.json + prints a
            breakdown. Safe to run anytime, including while a scrape run holds
            the board lock.
  --annotate (LOCK-GUARDED): stamps raw["staleness"] = {state, days_since_seen,
            reason} on each lead and re-writes the board via write_artifact so
            the dashboard can gray/filter them. Refuses to run while a scrape
            run holds the lock.
  --slim    read docs/listings_slim.json (no last_seen -> auction-passed only;
            light, for a quick pass without loading the 282MB board).
"""
from __future__ import annotations

import argparse
import collections
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

DOCS = Path("docs")
STALE_UNSEEN_DAYS = 21          # not re-listed in 3 weeks -> gone quiet
SALE_PASSED_GRACE_DAYS = 14     # NC upset window assumption when no explicit deadline


def _parse_dt(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).strip()
    for fmt in (None,):  # try fromisoformat first
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt)+4], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _classify(rec: dict, now: datetime) -> tuple[str, dict]:
    """Return (state, detail). state in fresh|upset_closed|sale_passed|gone_quiet."""
    get = (rec.get if isinstance(rec, dict) else lambda k: getattr(rec, k, None))
    deadline = _parse_dt(get("upset_bid_deadline"))
    sale = _parse_dt(get("sale_date"))
    last_seen = _parse_dt(get("last_seen"))
    detail = {}

    if deadline and deadline < now:
        return "upset_closed", {"deadline": deadline.date().isoformat()}
    if not deadline and sale and sale < now - timedelta(days=SALE_PASSED_GRACE_DAYS):
        return "sale_passed", {"sale_date": sale.date().isoformat()}
    if last_seen:
        days = (now - last_seen).days
        detail["days_since_seen"] = days
        if days >= STALE_UNSEEN_DAYS:
            return "gone_quiet", detail
    return "fresh", detail


def _load(slim: bool):
    if slim:
        d = json.load(open(DOCS / "listings_slim.json"))
        return d if isinstance(d, list) else d.get("listings", d)
    from foreclosure_scraper.web_artifact import load_board
    return load_board(str(DOCS))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotate", action="store_true", help="stamp raw + rewrite board (lock-guarded)")
    ap.add_argument("--slim", action="store_true", help="use slim file (auction-passed only)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    recs = _load(args.slim)
    n = len(recs)
    buckets = collections.Counter()
    by_source_stale = collections.Counter()
    examples = collections.defaultdict(list)
    stamped = []
    for r in recs:
        state, detail = _classify(r, now)
        buckets[state] += 1
        if state != "fresh":
            src = (r.get("source") if isinstance(r, dict) else getattr(r, "source", None)) or "?"
            by_source_stale[src] += 1
            addr = (r.get("street_address") if isinstance(r, dict) else getattr(r, "street_address", None)) or "?"
            if len(examples[state]) < 5:
                examples[state].append(f"{addr} [{src}] {detail}")
        stamped.append((r, state, detail))

    print(f"BOARD: {n} leads  |  {'SLIM (auction-only)' if args.slim else 'FULL (with last_seen)'}")
    print("=== staleness breakdown ===")
    for k in ("fresh", "upset_closed", "sale_passed", "gone_quiet"):
        c = buckets[k]
        print(f"  {k:14} {c:6d}  {100*c/n:5.1f}%")
    actionable_stale = buckets["upset_closed"] + buckets["sale_passed"] + buckets["gone_quiet"]
    print(f"  {'STALE TOTAL':14} {actionable_stale:6d}  {100*actionable_stale/n:5.1f}%")
    print("\n=== top sources carrying stale leads ===")
    for s, c in by_source_stale.most_common(12):
        print(f"  {c:5d}  {s}")
    print("\n=== examples ===")
    for k in ("upset_closed", "sale_passed", "gone_quiet"):
        for ex in examples[k]:
            print(f"  [{k}] {ex}")

    report = {
        "ts": now.isoformat(),
        "total": n,
        "mode": "slim" if args.slim else "full",
        "buckets": dict(buckets),
        "stale_total": actionable_stale,
        "by_source_stale": dict(by_source_stale.most_common(40)),
        "thresholds": {"stale_unseen_days": STALE_UNSEEN_DAYS,
                       "sale_passed_grace_days": SALE_PASSED_GRACE_DAYS},
    }
    (DOCS / "staleness_report.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote docs/staleness_report.json")

    if args.annotate:
        if args.slim:
            print("--annotate requires the full board (drop --slim)."); return 2
        from foreclosure_scraper.web_artifact import write_artifact, board_lock
        from foreclosure_scraper.dedupe import dedupe
        with board_lock(owner="staleness_sweep"):
            for li, state, detail in stamped:
                if not isinstance(getattr(li, "raw", None), dict):
                    li.raw = {}
                li.raw["staleness"] = {"state": state, **detail,
                                       "swept": now.isoformat()}
            # Dedupe as the LAST board-writer: earlier sequential writers (e.g.
            # resolve_addresses filling a divergent situs vs geocoded address on
            # two rows of the same parcel) can leave same-parcel dupes that
            # board_selfcheck's identity invariant flags. dedupe() collapses them.
            board = dedupe([li for li, _, _ in stamped])
            # Re-grade after dedupe: merging can pair one row's CONTRADICTED arv_flag
            # with the other's max_bid/equity, which board_selfcheck flags as "money
            # on a disputed ARV". Recomputing calc/grade + equity restores consistency
            # (the same dedupe -> regrade -> equity tail the full ingest pipeline runs).
            from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade
            from foreclosure_scraper.enrichment_equity import enrich_equity
            for li in board:
                try:
                    c = vcalc.compute(li)
                    g = vgrade.grade(li, c)
                    if not isinstance(li.raw, dict):
                        li.raw = {}
                    li.raw["calc"] = vcalc.to_dict(c)
                    li.raw["grade"] = vgrade.to_dict(g)
                except Exception:  # noqa: BLE001
                    pass
            try:
                enrich_equity(board)
            except Exception:  # noqa: BLE001
                pass
            summary = {"notes": "staleness annotation sweep + dedupe + regrade",
                       "by_source": dict(collections.Counter(
                           li.source for li in board if getattr(li, "source", None)))}
            lp, mp = write_artifact(board, summary, docs_dir=str(DOCS))
            print(f"annotated + deduped + wrote {lp.name}: "
                  f"{len(stamped)} -> {len(board)} leads ({actionable_stale} stale flagged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
