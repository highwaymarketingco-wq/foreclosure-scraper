#!/usr/bin/env python3
"""What a county parcel cache would add to the board, measured in counts only. READ-ONLY.

One streaming pass of foreclosure_scraper.board_stream.iter_board_rows() (about 300 MB, no
load_board, nothing written to the board). For each county named with --counties it reports:

  * baseline   rows, parcel id, owner mailing, county value, living sqft, last sale;
  * id join    what scripts/join_parcel_cache_to_board.py would fill on rows that carry a
               parcel id (same lookup, same fill-only rules, overage claims skipped), and how
               often the cache owner agrees with the row's owner name;
  * address    what scripts/resolve_parcel_from_address.py would resolve on rows with a street
               and no parcel id (its own rules: unique parcel, full street name, town/ZIP
               checks), and what the join would then fill; a mailing is counted only when the
               resolver's owner check is not False (the join withholds it otherwise);
  * after      mailing / value / sqft / sale coverage with both added.

It also counts, for EVERY county, rows that have a parcel id and no owner mailing while their
county's cache already holds a mailing for that parcel: data on disk that the join has not
applied yet.

    python scripts/measure_parcel_cache_lift.py --counties SC:Jasper,SC:Beaufort
    python scripts/measure_parcel_cache_lift.py --counties SC:Jasper --json /tmp/lift.json

Prints counts and rates only: no owner names, addresses or parcel ids.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from foreclosure_scraper import parcel_cache as pc  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def has_mailing(raw: dict) -> bool:
    """The coverage audits' owner-mailing union (docs/completeness_audit_2026-09-29-evening.md)."""
    om = raw.get("owner_mailing")
    om_ok = bool(om.get("mailing")) if isinstance(om, dict) else bool(isinstance(om, str) and om.strip())
    return bool(_d(raw.get("skip_trace")).get("owner_mailing_address")
                or _d(raw.get("outreach")).get("mailing_address")
                or _d(_d(raw.get("liensnc_related")).get("owner_contact")).get("mailing")
                or om_ok or _d(raw.get("gis")).get("mailing"))


def _pos(v) -> bool:
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def has_value(r: dict, raw: dict) -> bool:
    cama = _d(raw.get("cama"))
    return any(_pos(v) for v in (r.get("market_value"), cama.get("appraised_value"),
                                 cama.get("total_value"), r.get("tax_value")))


def has_sale(raw: dict) -> bool:
    return bool(raw.get("last_sale") or _d(raw.get("gis")).get("last_sale"))


def norm_key(county, state) -> tuple[str, str]:
    return (str(county or "").replace(" County", "").strip().lower(), str(state or "").strip().upper())


def _fills(hit: dict, base: dict, mail_ok: bool = True) -> dict:
    return {"mail": bool(mail_ok and hit.get("owner_mailing") and not base["mail"]),
            "value": bool(hit.get("market_value") and not base["value"]),
            "sqft": bool(hit.get("living_sqft") and not base["sqft"]),
            "sale": bool(pc.sale_amount(hit.get("sale_price")) and not base["sale"])}


def measure(rows, targets: set[tuple[str, str]]) -> dict:
    import resolve_parcel_from_address as rpa
    out: dict = defaultdict(Counter)
    keep: list[dict] = []
    base_of: dict[int, dict] = {}
    unapplied: Counter = Counter()
    for i, r in enumerate(rows):
        raw = _d(r.get("raw"))
        county = str(r.get("county") or "").replace(" County", "").strip()
        state = str(r.get("state") or "").strip().upper()
        k = norm_key(county, state)
        pid = str(r.get("parcel_id") or "").strip()
        mail = has_mailing(raw)
        overage = rpa.lt_str(r.get("listing_type")) == "tax_sale_overage"
        if pid and not mail and county and state and not overage:
            hit = pc.lookup(county, pid, state)
            if hit and hit.get("owner_mailing"):
                unapplied[f"{state}:{county}"] += 1
        if k not in targets:
            continue
        c = out[f"{k[1]}:{county}"]
        base = {"mail": mail, "value": has_value(r, raw), "sqft": _pos(r.get("living_sqft")),
                "sale": has_sale(raw)}
        c["rows"] += 1
        c["has_parcel_id"] += bool(pid)
        for f, v in base.items():
            c[f"base_{f}"] += v
        add = {"mail": False, "value": False, "sqft": False, "sale": False}
        if pid and not overage:
            hit = pc.lookup(county, pid, state)
            c["id_join_hit"] += bool(hit)
            if hit:
                agree = rpa.owner_verdict(str(r.get("owner_name") or ""), hit.get("owner"))
                c[f"id_join_owner_agrees_{agree}"] += 1
                add = _fills(hit, base)
                for f, v in add.items():
                    c[f"id_join_adds_{f}"] += v
        elif not pid:
            keep.append({"source": r.get("source"), "listing_type": r.get("listing_type"),
                         "state": state, "county": county, "parcel_id": "",
                         "street_address": r.get("street_address"), "city": r.get("city"),
                         "zip_code": r.get("zip_code"), "owner_name": r.get("owner_name"),
                         "market_value": r.get("market_value"), "tax_value": r.get("tax_value"),
                         "living_sqft": r.get("living_sqft"), "acreage": r.get("acreage"),
                         "raw": {k2: raw[k2] for k2 in ("owner_mailing", "gis", "situs_address_source",
                                                        "parcel_from_geo", "resolved_from_name")
                                 if k2 in raw}})
            base_of[len(keep) - 1] = base
        for f, v in add.items():
            c[f"after_{f}"] += bool(base[f] or v)
    # situs-address resolver on the target counties' rows without a parcel id
    if keep:
        corpus = rpa.collect_dicts(keep, keep_holdout=False)
        results, _per = rpa.resolve_targets(corpus)
        for ld, res, pid, _basis, agrees in results:
            c = out[f"{ld.state}:{keep[ld.ref]['county']}"]
            c[f"addr_{res.status}"] += 1
            base = base_of[ld.ref]
            if res.status != "unique" or not pid:
                continue
            hit = pc.lookup(keep[ld.ref]["county"], pid, ld.state) or {}
            c[f"addr_owner_agrees_{agrees}"] += 1
            add = _fills(hit, base, mail_ok=agrees is not False)
            for f, v in add.items():
                c[f"addr_adds_{f}"] += v
                if v:
                    c[f"after_{f}"] += 1      # base was False, so this row moves to covered
    return {"targets": {k: dict(v) for k, v in out.items()},
            "unapplied_cached_mailing_top": unapplied.most_common(25),
            "unapplied_cached_mailing_total": sum(unapplied.values())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--counties", required=True, help="comma list of ST:County, e.g. SC:Jasper,SC:Beaufort")
    ap.add_argument("--board", default="docs/listings.json.gz")
    ap.add_argument("--json", help="also write the counts here")
    a = ap.parse_args()
    targets = set()
    for item in a.counties.split(","):
        st, _, name = item.partition(":")
        targets.add(norm_key(name, st))
    res = measure(iter_board_rows(a.board), targets)
    for name, c in sorted(res["targets"].items()):
        n = c.get("rows", 0) or 1
        print(f"== {name}: {c.get('rows', 0):,} rows, parcel id {c.get('has_parcel_id', 0):,}")
        for f in ("mail", "value", "sqft", "sale"):
            b, af = c.get(f"base_{f}", 0), c.get(f"after_{f}", 0)
            print(f"   {f:<6} {b:>6,} ({100 * b / n:5.1f}%) -> {af:>6,} ({100 * af / n:5.1f}%)  "
                  f"+{af - b:,} [id join {c.get(f'id_join_adds_{f}', 0):,}, address {c.get(f'addr_adds_{f}', 0):,}]")
        rest = {k: v for k, v in c.items() if k.startswith(("id_join_hit", "id_join_owner", "addr_"))
                and not k.startswith("addr_adds")}
        print(f"   detail {rest}")
    print(f"== rows with a parcel id and no mailing whose county cache already holds one: "
          f"{res['unapplied_cached_mailing_total']:,}")
    for k, v in res["unapplied_cached_mailing_top"]:
        print(f"   {k:<22}{v:>7,}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
