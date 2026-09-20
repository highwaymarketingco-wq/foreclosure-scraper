#!/usr/bin/env python3
"""Per-county x per-signal coverage ledger for the 18-county footprint.

`county_coverage_matrix.py` counts a signal family as "present" from source
NAMES, so it misses signals that live as stamps on leads (court-verified divorce,
incarceration, obituaries) and says nothing about how many leads carry a family.
This ledger streams the board once (constant memory, safe next to another board
process) and reports, for each footprint county:

  * LAYERS  rows, identity (parcel+situs), value, owner name, mail, phone, actual debt
  * SIGNALS a lead count per family, from the union of (a) the source name,
            (b) distress_stack.signals, and (c) raw stamps (divorce, incarceration)
  * the weakest layer and every family with ZERO leads

A family with 0 leads is either a build target or a documented wall; the walls
live in docs/MASTER_GAPS_WALLS_AND_MANUAL_LANES.md and are overlaid by hand in
the ledger doc, not guessed here.

    python scripts/coverage_100_ledger.py            # prints markdown to stdout
    python scripts/coverage_100_ledger.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.config import NC_COUNTIES, SC_COUNTIES  # noqa: E402
from foreclosure_scraper.distress_score import _divorce_signal  # noqa: E402

# family -> (source-name fragments, distress_stack signal names). A lead counts
# toward a family if ANY of them matches.
FAMILIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "tax_delinquent": (("delinquent_tax", "tax_delinquent", "ptscloud", "pdf_delinquent",
                        "csv_delinquent", "multi_year", "qpaybill", "flc"), ("tax_lien",)),
    "tax_sale": (("tax_sale", "tax_foreclos", "kania", "zacchaeus"), ("tax_sale",)),
    "mortgage_foreclosure": (("hutchens", "brock_scott", "shapiro", "substitute_trustee",
                              "foreclosure_sale", "sheriff", "trustee", "upset"),
                             ("foreclosure_sale", "upset_bid", "sheriff_sale", "auction")),
    "lis_pendens": (("lis_pendens", "public_index"), ("lis_pendens",)),
    "probate_estate": (("probate", "estate", "obitu", "funeral", "deceased"),
                       ("probate", "probate_notice", "probate_deed")),
    "code_vacancy": (("code_violation", "condemn", "vacant", "min_housing", "demoli",
                      "zombie", "nuisance", "code_enforcement"),
                     ("code_enforcement", "distressed_condition")),
    "bankruptcy": (("bankruptcy", "courtlistener"), ("bankruptcy",)),
    "divorce": (("divorce",), ()),               # + raw['divorce'] stamp, below
    "liens": (("lien", "judgment", "ucc"), ("recorded_debt",)),
    "incarceration": ((), ("incarceration",)),   # + raw['incarceration'] stamp
}


def _pos(v) -> bool:
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def _cd(d: dict, k: tuple[str, str]) -> dict:
    return d.setdefault(k, defaultdict(int))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="also write the raw numbers here")
    args = ap.parse_args()

    footprint = [(c.name, c.state) for c in list(NC_COUNTIES) + list(SC_COUNTIES)]
    want = {(n.lower(), s) for n, s in footprint}
    cnt: dict = {}

    for r in iter_board_rows():
        cty = (r.get("county") or "").replace(" County", "").strip().lower()
        st = (r.get("state") or "").strip().upper()
        k = (cty, st)
        if k not in want:
            continue
        c = _cd(cnt, k)
        raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
        c["rows"] += 1
        if (r.get("parcel_id") or "").strip() and (r.get("street_address") or "").strip():
            c["identity"] += 1
        cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
        if any(_pos(v) for v in (r.get("market_value"), cama.get("appraised_value"),
                                 cama.get("total_value"), r.get("tax_value"))):
            c["value"] += 1
        has_name = bool((r.get("owner_name") or "").strip())
        if has_name:
            c["owner_name"] += 1
        st_ = raw.get("skip_trace") if isinstance(raw.get("skip_trace"), dict) else {}
        out_ = raw.get("outreach") if isinstance(raw.get("outreach"), dict) else {}
        op = raw.get("owner_phone") if isinstance(raw.get("owner_phone"), dict) else {}
        rel = raw.get("liensnc_related") if isinstance(raw.get("liensnc_related"), dict) else {}
        oc = rel.get("owner_contact") if isinstance(rel.get("owner_contact"), dict) else {}
        om = raw.get("owner_mailing") if isinstance(raw.get("owner_mailing"), dict) else {}
        if has_name and (st_.get("owner_mailing_address") or out_.get("mailing_address")
                         or oc.get("mailing") or om.get("mailing")):
            c["mail"] += 1
        if op.get("phone") or out_.get("phones") or oc.get("phone"):
            c["phone"] += 1
        # ACTUAL debt only: raw['tax_owed'].balance is a real delinquent balance;
        # raw['amount_owed'] is often an estimate (is_actual_debt False).
        to = raw.get("tax_owed") if isinstance(raw.get("tax_owed"), dict) else {}
        ao = raw.get("amount_owed") if isinstance(raw.get("amount_owed"), dict) else {}
        if _pos(to.get("balance")) or (_pos(ao.get("value")) and ao.get("is_actual_debt") is True):
            c["debt_actual"] += 1

        low = (r.get("source") or "").lower()
        ds = raw.get("distress_stack") if isinstance(raw.get("distress_stack"), dict) else {}
        sigs = set(ds.get("signals") or [])
        for fam, (frags, snames) in FAMILIES.items():
            hit = any(f in low for f in frags) or any(s in sigs for s in snames)
            if fam == "divorce":
                dv = raw.get("divorce")
                hit = hit or (isinstance(dv, dict) and bool(dv.get("case_count")))
                if isinstance(dv, dict) and _divorce_signal(raw):
                    c["divorce_scored"] += 1          # recent enough to reach the score
            if fam == "incarceration":
                hit = hit or bool(raw.get("incarceration"))
            if hit:
                c["fam:" + fam] += 1

    fams = list(FAMILIES)
    pct = lambda n, d: f"{100 * n / d:.0f}%" if d else "-"
    lines = ["| county | rows | ident | value | name | mail | phone | debt$ | weakest |",
             "|---|--:|--:|--:|--:|--:|--:|--:|---|"]
    weak_of = {}
    for name, state in footprint:
        c = cnt.get((name.lower(), state), {})
        n = c.get("rows", 0)
        layers = {k: (c.get(k, 0) / n if n else 0) for k in ("identity", "value", "owner_name", "mail", "phone")}
        worst = min(layers, key=layers.get) if n else "NO ROWS"
        weak_of[(name, state)] = worst
        lines.append(f"| {name} {state} | {n:,} | {pct(c.get('identity', 0), n)} | {pct(c.get('value', 0), n)} | "
                     f"{pct(c.get('owner_name', 0), n)} | {pct(c.get('mail', 0), n)} | {pct(c.get('phone', 0), n)} | "
                     f"{pct(c.get('debt_actual', 0), n)} | {worst} {pct(int(layers.get(worst, 0) * n), n) if n else ''} |")
    print("## Layers (share of the county's leads)\n")
    print("\n".join(lines))

    hdr = "| county | " + " | ".join(f[:9] for f in fams) + " |"
    print("\n## Signals (lead count; `0` = no lead carries that family)\n")
    print(hdr)
    print("|---|" + "--:|" * len(fams))
    zero_cells = []
    for name, state in footprint:
        c = cnt.get((name.lower(), state), {})
        row = []
        for f in fams:
            v = c.get("fam:" + f, 0)
            row.append(f"**0**" if v == 0 else f"{v:,}")
            if v == 0:
                zero_cells.append((f"{name} {state}", f))
        print(f"| {name} {state} | " + " | ".join(row) + " |")

    print(f"\n## Zero cells: {len(zero_cells)} of {len(footprint) * len(fams)}\n")
    by_fam = defaultdict(list)
    for cty, f in zero_cells:
        by_fam[f].append(cty)
    for f in fams:
        if by_fam[f]:
            print(f"- **{f}** missing in {len(by_fam[f])}/{len(footprint)}: {', '.join(by_fam[f])}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {f"{n} {s}": dict(cnt.get((n.lower(), s), {})) for n, s in footprint}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
