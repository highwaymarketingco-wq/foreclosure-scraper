#!/usr/bin/env python3
"""ARV accuracy where truth exists: the parcel's own recorded sale (audit 2026-10-09, valuation).

Truth: the most recent sale of the row's OWN parcel recorded within TRUTH_MONTHS of the board date
(raw.gis.last_sale, raw.cama.last_sale_*, raw.assessor_card.sales), at least MIN_SALE dollars, not
marked unqualified on the assessor card, at least MIN_SALE_SHARE of the county's own value, and
not a deed whose (amount, date) sits on 2+ distinct parcels of the board (one deed, several
parcels: its amount is not this parcel's price).

The engine prices a row WITH its own sale in hand (the ARV floor raises a low ARV to a recent
sale), so comparing the published ARV to that sale is circular. Each truth row is therefore
re-priced by valuation.calc / grading as of this code with the truth sale (and every later sale)
removed from the row ("leave-sale-out"), once with the outlier guard off (`before`) and once on
(`after`). The published figure is reported beside them, labelled circular.

Reported per variant: rows priced, signed median error, median and p90 absolute percentage error,
by state, by property kind, by ARV method, and for rows with tight comps (+sqft +beds).
Sales within 18 months need no index adjustment beyond a few percent; ARV is AFTER-repair and the
sale is the parcel as it stood, so a positive median is expected (the 2026-06-30 backtest: +1.7%).

  uv run python scripts/valuation_accuracy.py --checkpoint DIR [--json OUT]
  uv run python scripts/valuation_accuracy.py --board docs [--json OUT]

Two streaming passes (the deed index, then the measurement); memory is the deed index (amount,
date -> up to 2 parcel ids) plus counters. Writes nothing but --json.
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (REPO / "src", REPO / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

TRUTH_MONTHS = 18
MIN_SALE = 20_000
MIN_SALE_SHARE = 0.25
UNQUALIFIED = ("not qualified", "unqualified", "non-qualified", "family", "quit", "gift",
               "foreclos", "related", "partial", "multi")


def _date(s) -> date | None:
    s = str(s or "").strip()
    if len(s) >= 8 and s[:8].isdigit():
        s = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def own_sales(raw: dict) -> list[tuple[date, float, str]]:
    """Every dated, priced sale of the row's own parcel in its raw blocks."""
    out = []
    gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}
    ls = gis.get("last_sale") if isinstance(gis.get("last_sale"), dict) else {}
    d, a = _date(ls.get("date")), _f(ls.get("amount"))
    if d and a:
        out.append((d, a, "gis"))
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    d, a = _date(cama.get("last_sale_date")), _f(cama.get("last_sale_amount"))
    if d and a:
        out.append((d, a, "cama"))
    card = raw.get("assessor_card") if isinstance(raw.get("assessor_card"), dict) else {}
    for s in card.get("sales") or []:
        if not isinstance(s, dict):
            continue
        reason = str(s.get("reason") or "").lower()
        if any(w in reason for w in UNQUALIFIED):
            continue
        d, a = _date(s.get("sale_date")), _f(s.get("price"))
        if d and a:
            out.append((d, a, "card"))
    return out


def county_values(row: dict) -> list[float]:
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    return [v for v in (_f(row.get("market_value")), _f(cama.get("appraised_value")),
                        _f(row.get("tax_value"))) if v and v > 1000]


def truth_sale(row: dict, as_of: date, multi_parcel: set) -> tuple[date, float, str] | None:
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    lo = as_of - timedelta(days=int(TRUTH_MONTHS * 30.44))
    cv = county_values(row)
    best = None
    for d, a, src in own_sales(raw):
        if not (lo <= d <= as_of) or a < MIN_SALE:
            continue
        if cv and a < MIN_SALE_SHARE * max(cv):
            continue
        if (round(a), d.isoformat()) in multi_parcel:
            continue
        if best is None or d > best[0]:
            best = (d, a, src)
    return best


def strip_sales(raw: dict, since: date) -> dict:
    """The row's raw with the truth sale and every later sale removed (leave-sale-out)."""
    r = copy.deepcopy(raw)
    gis = r.get("gis")
    if isinstance(gis, dict) and isinstance(gis.get("last_sale"), dict):
        d = _date(gis["last_sale"].get("date"))
        if d is None or d >= since:
            gis.pop("last_sale", None)
    cama = r.get("cama")
    if isinstance(cama, dict):
        d = _date(cama.get("last_sale_date"))
        if d is None or d >= since:
            cama.pop("last_sale_amount", None)
            cama.pop("last_sale_date", None)
    card = r.get("assessor_card")
    if isinstance(card, dict) and isinstance(card.get("sales"), list):
        card["sales"] = [s for s in card["sales"] if isinstance(s, dict)
                         and (_date(s.get("sale_date")) or date.min) < since]
    fh = r.get("fhfa_value")
    if isinstance(fh, dict):
        r.pop("fhfa_value", None)       # an HPI rescale of the same sale
    return r


def method_of(notes) -> str:
    s = " ".join(notes or [])
    for key, label in (("RECORDED arms-length sales within", "recorded_ppsf"),
                       ("zip-matched sold comps", "listing_comps"),
                       ("RECORDED nearby sales priced against county", "sale_to_assessed"),
                       ("Zillow Zestimate", "zestimate"), ("ARV from county market value", "county_market"),
                       ("FHFA-HPI", "fhfa"), ("tax-assessed × 1.25", "tax_x1.25"),
                       ("proxy from bid", "bid_proxy"), ("Land ARV", "land_county"),
                       ("land comps", "land_comps")):
        if key in s:
            return label
    return "other"


class Acc:
    def __init__(self):
        self.err: dict = defaultdict(list)
        self.n: dict = defaultdict(int)

    def add(self, keys, truth: float, arv: float | None) -> None:
        for k in keys:
            self.n[k] += 1
            if arv:
                self.err[k].append((arv - truth) / truth)

    def table(self) -> dict:
        out = {}
        for k in sorted(self.n, key=lambda k: (k.split(":")[0], -self.n[k])):
            e = self.err.get(k, [])
            a = sorted(abs(x) for x in e)
            out[k] = {"truth_rows": self.n[k], "priced": len(e),
                      "median_signed_pct": round(100 * statistics.median(e), 1) if e else None,
                      "median_ape_pct": round(100 * statistics.median(a), 1) if a else None,
                      "p90_ape_pct": round(100 * a[int(0.9 * (len(a) - 1))], 1) if a else None,
                      "within_20pct": round(100 * sum(x <= 0.2 for x in a) / len(a), 1) if a else None}
        return out


def rows_of(args):
    if args.checkpoint:
        # the full Listing dumps (not the published trim): calc reads raw blocks the trim drops
        from foreclosure_scraper.board_parts import iter_gz_rows
        return iter_gz_rows(Path(args.checkpoint) / "board.json.gz")
    from foreclosure_scraper.board_stream import iter_board_rows_with_detail
    return iter_board_rows_with_detail(Path(args.board) / "listings.json.gz", keys=("comps", "cama"))


def board_date(args) -> date:
    try:
        if args.checkpoint:
            m = json.loads((Path(args.checkpoint) / "manifest.json").read_text())
            return datetime.fromisoformat(m["saved_at"]).date()
        m = json.loads((Path(args.board) / "run_meta.json").read_text())
        return datetime.fromisoformat(m["run_time"].replace("Z", "")).date()
    except (OSError, ValueError, KeyError):
        return date.today()


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--checkpoint")
    g.add_argument("--board")
    ap.add_argument("--json")
    args = ap.parse_args()

    from foreclosure_scraper.models import Listing
    from foreclosure_scraper.valuation import calc as vcalc

    as_of = board_date(args)
    # pass 1: which (amount, date) deeds sit on 2+ distinct parcels
    seen: dict = {}
    multi: set = set()
    for row in rows_of(args):
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        pid = str(row.get("parcel_id") or row.get("street_address") or "")
        for d, a, _src in own_sales(raw):
            k = (round(a), d.isoformat())
            prev = seen.get(k)
            if prev is None:
                seen[k] = pid
            elif prev != pid:
                multi.add(k)
    del seen

    real_guard = vcalc._outlier_unexplained
    accs = {"published (circular)": Acc(), "before (leave-sale-out, no outlier guard)": Acc(),
            "after (leave-sale-out, outlier guard)": Acc()}
    excluded = defaultdict(int)
    total = 0
    for row in rows_of(args):
        total += 1
        t = truth_sale(row, as_of, multi)
        if not t:
            continue
        d, amount, src = t
        calc = (row.get("raw") or {}).get("calc") or {}
        kind = str(row.get("property_kind") or "unknown")
        st = str(row.get("state") or "?")
        tight = any(isinstance(c, dict) and "sqft" in str(c.get("match_quality") or "")
                    and "beds" in str(c.get("match_quality") or "")
                    for c in ((row.get("raw") or {}).get("comps") or []))
        improved = kind not in ("land", "unknown")
        base = ["all", f"state:{st}", f"kind:{kind}", f"state_kind:{st}:{kind}",
                f"truth_source:{src}", "improved" if improved else "land_or_unknown"]
        if tight:
            base.append("comps_tight")
        accs["published (circular)"].add(base + [f"method:{method_of(calc.get('notes'))}"],
                                         amount, _f(calc.get("arv_expected")))
        try:
            li = Listing.model_validate({**row, "raw": strip_sales(row.get("raw") or {}, d)})
        except Exception:  # noqa: BLE001
            excluded["did_not_validate"] += 1
            continue
        for label, guard in (("before (leave-sale-out, no outlier guard)", lambda *a, **k: False),
                             ("after (leave-sale-out, outlier guard)", real_guard)):
            vcalc._outlier_unexplained = guard
            try:
                c = vcalc.compute(li)
            finally:
                vcalc._outlier_unexplained = real_guard
            accs[label].add(base + [f"method:{method_of(c.notes)}"], amount, c.arv_expected)
    out = {"as_of": as_of.isoformat(), "rows": total, "multi_parcel_deeds": len(multi),
           "excluded": dict(excluded), "truth_rule": {
               "months": TRUTH_MONTHS, "min_sale": MIN_SALE, "min_share_of_county_value": MIN_SALE_SHARE},
           "variants": {k: v.table() for k, v in accs.items()}}
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1))
    for k, v in out["variants"].items():
        print(f"\n== {k}")
        print(f"{'slice':34} {'truth':>6} {'priced':>6} {'signed':>7} {'medAPE':>7} {'p90APE':>7} {'<=20%':>6}")
        for s, r in v.items():
            print(f"{s:34} {r['truth_rows']:>6} {r['priced']:>6} {str(r['median_signed_pct']):>7} "
                  f"{str(r['median_ape_pct']):>7} {str(r['p90_ape_pct']):>7} {str(r['within_20pct']):>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
