#!/usr/bin/env python3
"""What is missing, per county, per state — the actual definition of "100%".

A lead is only workable when FIVE layers are all present. This measures each
layer for every footprint county so "what's left to do" is a table, not a feeling.

  1. SIGNAL    a distress event in public records (delinquent tax 2-3yr, tax
               foreclosure suit, probate/estate, lis pendens, code violation,
               vacancy, divorce, bankruptcy, lien)
  2. IDENTITY  resolved to a real property: parcel id AND a situs address
  3. VALUE     the county's own 100%-basis appraisal (Fullmer's CAD baseline)
  4. CONTACT   an owner name plus a phone or a mailing address
  5. RANKED    survived scoring and carries a fullmer rank

A county with 4,000 signals and no contacts is not covered. A county with perfect
contacts and no value cannot be underwritten. The weakest layer is the county's
real coverage, so that is what gets reported.
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.config import NC_COUNTIES, SC_COUNTIES  # noqa: E402

BOARD = REPO / "docs" / "listings.json.gz"

# The distress families that matter for the buy box. A county missing a whole
# family is a build target, not a data-quality problem.
SIGNAL_FAMILIES = {
    "tax_delinquent": ("delinquent_tax", "tax_delinquent", "ptscloud", "pdf_delinquent",
                       "csv_delinquent", "multi_year", "qpaybill", "flc", "tax_sale"),
    "tax_foreclosure": ("tax_foreclos", "kania", "zacchaeus", "upset"),
    "mortgage_foreclosure": ("hutchens", "brock_scott", "shapiro", "substitute_trustee",
                             "foreclosure_sale", "sheriff", "trustee"),
    # NB: no bare "ecourts" here. `_family` is first-match-wins, and NC eCourts
    # serves several distinct dockets: nc_ecourts_divorce, nc_ecourts_estates,
    # nc_ecourts_judgments, nc_ecourts_lis_pendens. A bare "ecourts" pattern in this
    # (earlier-checked) family swallowed all of them, which is how the first run of
    # this script reported "divorce present in 0/18 counties" while 75 divorce rows
    # sat on the board, 53 of them in-footprint. Each docket matches on its own noun.
    "lis_pendens": ("lis_pendens", "public_index"),
    "probate_estate": ("probate", "estate", "obitu", "funeral", "deceased"),
    "code_vacancy": ("code_violation", "condemn", "vacant", "min_housing", "demoli",
                     "zombie", "nuisance"),
    "bankruptcy": ("bankruptcy", "courtlistener"),
    "divorce": ("divorce", "marriage", "separation"),
    "liens": ("lien", "judgment", "ucc", "ecourts_judgment"),
}


def stream(path: Path):
    dec = json.JSONDecoder()
    buf = ""
    started = False
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            buf += chunk
            if not started:
                i = buf.find("[")
                if i < 0:
                    continue
                buf = buf[i + 1:]
                started = True
            while True:
                s = buf.lstrip()
                if s[:1] == ",":
                    s = s[1:].lstrip()
                if not s or s[0] == "]":
                    buf = s
                    break
                try:
                    obj, end = dec.raw_decode(s)
                except ValueError:
                    buf = s
                    break
                buf = s[end:]
                yield obj


def _family(source: str) -> str | None:
    low = (source or "").lower()
    for fam, pats in SIGNAL_FAMILIES.items():
        if any(p in low for p in pats):
            return fam
    return None


def main() -> int:
    want = [(c.name, c.state) for c in list(NC_COUNTIES) + list(SC_COUNTIES)]
    key = {(n.lower(), s) for n, s in want}

    rows = defaultdict(int)
    ident = defaultdict(int)
    value = defaultdict(int)
    contact = defaultdict(int)
    ranked = defaultdict(int)
    mail_only = defaultdict(int)
    phone_any = defaultdict(int)
    fams = defaultdict(set)
    other = defaultdict(int)

    for r in stream(BOARD):
        cty = (r.get("county") or "").replace(" County", "").strip()
        st = (r.get("state") or "").strip().upper()
        k = (cty.lower(), st)
        if k not in key:
            if cty:
                other[f"{cty},{st}"] += 1
            continue
        raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
        rows[k] += 1

        if (r.get("parcel_id") or "").strip() and (r.get("street_address") or "").strip():
            ident[k] += 1

        cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
        if any(_pos(v) for v in (r.get("market_value"), cama.get("appraised_value"),
                                 cama.get("total_value"), r.get("tax_value"))):
            value[k] += 1

        # FIELD NAMES VERIFIED against the live board, not guessed. An earlier pass
        # of this script reported SC contact at 0% because it looked for
        # skip_trace["mailing"], outreach["mailing"] and gis["mailing"] -- none of
        # which exist. The real keys are skip_trace["owner_mailing_address"] and
        # outreach["mailing_address"], and gis["mailing"] genuinely is ~0 (4 rows).
        has_name = bool((r.get("owner_name") or "").strip())
        rel = raw.get("liensnc_related") if isinstance(raw.get("liensnc_related"), dict) else {}
        oc = rel.get("owner_contact") if isinstance(rel.get("owner_contact"), dict) else {}
        st_ = raw.get("skip_trace") if isinstance(raw.get("skip_trace"), dict) else {}
        out_ = raw.get("outreach") if isinstance(raw.get("outreach"), dict) else {}
        op = raw.get("owner_phone") if isinstance(raw.get("owner_phone"), dict) else {}
        mailing = (st_.get("owner_mailing_address") or out_.get("mailing_address")
                   or oc.get("mailing"))
        # skip_trace["phone_numbers"] is empty on all 21,400 rows that carry it --
        # its provider is 100% "tax_records_only", so it is a MAIL source, never a
        # phone source. Only owner_phone / outreach.phones / the LiensNC report
        # actually yield a number.
        phone = op.get("phone") or (out_.get("phones") or None) or oc.get("phone")
        if has_name and (mailing or phone):
            contact[k] += 1
        if has_name and mailing:
            mail_only[k] += 1
        if phone:
            phone_any[k] += 1

        if isinstance(raw.get("fullmer"), dict):
            ranked[k] += 1

        fam = _family(r.get("source") or "")
        if fam:
            fams[k].add(fam)

    total_fams = len(SIGNAL_FAMILIES)
    print(f"{'county':<20}{'rows':>8}{'ident':>8}{'value':>8}{'mail':>7}"
          f"{'phone':>7}{'ranked':>8}   signal families present")
    print("-" * 108)
    gaps: list[tuple[str, str]] = []
    for name, state in want:
        k = (name.lower(), state)
        n = rows[k]
        pct = lambda c: f"{(c / n * 100):.0f}%" if n else "-"
        have = sorted(fams[k])
        missing = [f for f in SIGNAL_FAMILIES if f not in fams[k]]
        print(f"{name + ',' + state:<20}{n:>8,}{pct(ident[k]):>8}{pct(value[k]):>8}"
              f"{pct(mail_only[k]):>7}{pct(phone_any[k]):>7}{pct(ranked[k]):>8}   "
              f"{len(have)}/{total_fams} {','.join(f[:4] for f in have)}")
        if n == 0:
            gaps.append((f"{name},{state}", "NO ROWS AT ALL"))
        else:
            weak = []
            if ident[k] / n < 0.5:
                weak.append(f"identity {ident[k]/n*100:.0f}%")
            if value[k] / n < 0.5:
                weak.append(f"value {value[k]/n*100:.0f}%")
            if mail_only[k] / n < 0.5:
                weak.append(f"mail {mail_only[k]/n*100:.0f}%")
            if phone_any[k] / n < 0.3:
                weak.append(f"phone {phone_any[k]/n*100:.0f}%")
            if len(missing) > 4:
                weak.append(f"missing {len(missing)} signal families")
            if weak:
                gaps.append((f"{name},{state}", "; ".join(weak)))

    print()
    print("=== WEAKEST LAYER PER COUNTY (this is the work queue) ===")
    for c, why in gaps:
        print(f"  {c:<20} {why}")

    print()
    print("=== signal families with the WORST county coverage ===")
    fam_counts = {f: sum(1 for k in key if f in fams[k]) for f in SIGNAL_FAMILIES}
    for f, c in sorted(fam_counts.items(), key=lambda x: x[1]):
        print(f"  {f:<22} present in {c:>2}/{len(key)} counties")

    print()
    print(f"=== rows in counties OUTSIDE the {len(key)}-county footprint: "
          f"{sum(other.values()):,} ===")
    for c, n in sorted(other.items(), key=lambda x: -x[1])[:10]:
        print(f"  {n:>7,}  {c}")
    return 0


def _pos(v):
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
