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
from foreclosure_scraper.enrichment_sc_phone import usable_owner_phone  # noqa: E402

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.config import NC_COUNTIES, SC_COUNTIES  # noqa: E402
from foreclosure_scraper.distress_score import _divorce_signal  # noqa: E402

# family -> (source-name fragments, distress_stack signal names). A lead counts
# toward a family if ANY of them matches.
#
# The signal-name half must be a signal that ONLY ever fires from a source that
# genuinely belongs to the family -- not a generic cross-cutting stamp that many
# unrelated sources can set. `distressed_condition` used to sit on code_vacancy:
# it looks family-specific ("a distressed structure") but distress_score.py
# actually sets it from raw['distressed'], which is stamped by bulk CAMA
# assessor-condition enrichment (enrichment_cama_condition.py /
# enrichment_sc_cama.py / enrichment_owner_mailing.py's condition-column scan)
# on ANY row in ANY county with a "Poor"/"Unsound" appraiser condition code,
# regardless of which scraper produced that row. A tax-delinquent lead in a
# county with a bulk condition layer (e.g. Buncombe) got counted as
# "code_vacancy" evidence even though no code-enforcement/vacancy scraper ever
# touched it -- the same false-positive class the 2026-09-29 completeness audit
# separately flagged for `recorded_debt` under "liens" (a real-debt signal any
# tax/foreclosure source can set, not a lien-registry-specific one; still open,
# see docs/completeness_audit_2026-09-29-evening.md). `vacant_structure` is the
# one genuinely code_vacancy-scoped derived signal: it only fires from
# raw['vacancy']/raw['vacant'] being a dict with vacant/boarded_up True, which
# only hendersonville_vacant_structures.py ever writes.
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
    # "zombie" dropped from the fragments (audit false-positive #2): zombie_properties.py
    # is a DERIVED stalled-foreclosure signal (a stale lis pendens that never progressed
    # to sale) -- it is not a code-enforcement/vacancy source and has no physical-condition
    # evidence at all. Only the 6 real dedicated scrapers match now: gaston_vacant,
    # henderson_code_violations, hendersonville_vacant_structures, lincoln_code_violations,
    # lincoln_vacant, transylvania_vacant (NC) + spartanburg_vacant, spartanburg_condemned,
    # spartanburg_city_condemned (SC) + city_websites.asheville_min_housing (Buncombe).
    "code_vacancy": (("code_violation", "condemn", "vacant", "min_housing", "demoli",
                      "nuisance", "code_enforcement"),
                     ("code_enforcement", "vacant_structure")),
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


def family_hits(source: str | None, raw: dict) -> set[str]:
    """Which FAMILIES keys one row counts as evidence for.

    A hit requires the row's own source/scraper identity to match a family's
    name fragments, OR a distress_stack signal that only that family's sources
    ever set. It deliberately does NOT match on a generic flag (like
    raw['distressed']) directly -- see the FAMILIES comment for the
    code_vacancy / liens false positives that pattern caused.
    """
    low = (source or "").lower()
    ds = raw.get("distress_stack") if isinstance(raw.get("distress_stack"), dict) else {}
    sigs = set(ds.get("signals") or [])
    hits: set[str] = set()
    for fam, (frags, snames) in FAMILIES.items():
        hit = any(f in low for f in frags) or any(s in sigs for s in snames)
        if fam == "divorce":
            dv = raw.get("divorce")
            hit = hit or (isinstance(dv, dict) and bool(dv.get("case_count")))
        if fam == "incarceration":
            hit = hit or bool(raw.get("incarceration"))
        if hit:
            hits.add(fam)
    return hits


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
        # usable_owner_phone drops do-not-dial xref matches, agent/attorney lines and people-search phones
        if usable_owner_phone(raw) or out_.get("phones") or oc.get("phone"):
            c["phone"] += 1
        # ACTUAL debt only: raw['tax_owed'].balance is a real delinquent balance;
        # raw['amount_owed'] is often an estimate (is_actual_debt False).
        to = raw.get("tax_owed") if isinstance(raw.get("tax_owed"), dict) else {}
        ao = raw.get("amount_owed") if isinstance(raw.get("amount_owed"), dict) else {}
        if _pos(to.get("balance")) or (_pos(ao.get("value")) and ao.get("is_actual_debt") is True):
            c["debt_actual"] += 1

        dv = raw.get("divorce")
        if isinstance(dv, dict) and _divorce_signal(raw):
            c["divorce_scored"] += 1              # recent enough to reach the score
        for fam in family_hits(r.get("source"), raw):
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
