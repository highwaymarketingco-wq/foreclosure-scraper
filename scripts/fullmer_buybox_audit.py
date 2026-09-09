#!/usr/bin/env python3
"""Measure the published board against the buy box Fullmer actually states.

Every threshold here is a quote, not an inference. The book and the two most
recent podcast episodes give hard numbers that the engine had never been scored
against:

  * "choose properties that are worth 200 grand or above -- but on the CAD
    value" (ep 021). CAD = county appraisal district = our `_anchor_value`.
  * "I don't look at deals ... fair market value of 30, 40,000. I don't even
    look at that anymore. Even if you give it to me for free, it's not worth it"
    (ep 019). So there is a hard FLOOR, not just a preference.
  * "I want them to be two to three years behind" (book ch. 20). One year is
    explicitly too early.
  * "we just went ahead and focused on owners that were in a tax lawsuit at some
    level" (ep 021) -- the served notice is what makes a seller problem-aware.
  * "leads that have a pretty high delinquent tax base to them ... this one only
    had 8K in delinquent taxes" (ep 022) -- the delinquent DOLLAR amount is a
    ranking column, and we do not carry it as a field at all.
  * "Heirship ... this is where 70% of our deals live" (book glossary).
  * "I don't like to deal in itsy bitsy tiny crummy markets ... no liquidity"
    (ep 019) -- market liquidity is a gate, not a nice-to-have.
  * "margins need to be no lower than 50 grand" (ep 021).

The point of this script is to report which of those the board can even answer.
A threshold we cannot measure is a worse finding than a threshold we fail.
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

BOARD_GZ = REPO / "docs" / "listings.json.gz"

# "worth 200 grand or above -- but on the CAD value" (ep 021)
CAD_A_TIER = 200_000.0
# "fair market value of 30, 40,000 ... even if you give it to me for free, it's
# not worth it" (ep 019). 50K is the first value above the range he names.
CAD_FLOOR = 50_000.0
# "margins need to be no lower than 50 grand" (ep 021)
MARGIN_FLOOR = 50_000.0

# "I don't like to deal in itsy bitsy tiny crummy markets in the middle of
# nowhere ... you got no liquidity" (ep 019). Tiering by the MSA the county sits
# in, not by county population, because the exit is the MSA's buyer pool.
MSA_TIER = {
    # Charlotte-Concord-Gastonia MSA (~2.8M) and Asheville MSA (~475K)
    ("gaston", "NC"): "major", ("lincoln", "NC"): "major",
    ("cleveland", "NC"): "major", ("mecklenburg", "NC"): "major",
    ("buncombe", "NC"): "mid", ("henderson", "NC"): "mid",
    ("madison", "NC"): "mid", ("haywood", "NC"): "mid",
    # Greenville-Anderson-Greer MSA (~950K) + Spartanburg MSA (~330K)
    ("greenville", "SC"): "major", ("spartanburg", "SC"): "mid",
    ("anderson", "SC"): "mid", ("pickens", "SC"): "mid",
    ("laurens", "SC"): "thin", ("greenwood", "SC"): "thin",
    ("cherokee", "SC"): "thin", ("union", "SC"): "thin",
    ("oconee", "SC"): "thin", ("abbeville", "SC"): "thin",
    # Rural WNC -- he would decline these on liquidity alone
    ("rutherford", "NC"): "thin", ("polk", "NC"): "thin",
    ("mcdowell", "NC"): "thin", ("transylvania", "NC"): "thin",
    ("burke", "NC"): "thin", ("yancey", "NC"): "thin",
    ("mitchell", "NC"): "thin", ("avery", "NC"): "thin",
    ("swain", "NC"): "thin", ("jackson", "NC"): "thin",
    ("macon", "NC"): "thin", ("clay", "NC"): "thin",
    ("cherokee", "NC"): "thin", ("graham", "NC"): "thin",
    # Coastal (user authorised for foreclosure + all distressed)
    ("brunswick", "NC"): "mid", ("new hanover", "NC"): "major",
    ("charleston", "SC"): "major", ("horry", "SC"): "major",
    ("beaufort", "SC"): "mid", ("georgetown", "SC"): "thin",
    ("colleton", "SC"): "thin", ("berkeley", "SC"): "major",
    ("dorchester", "SC"): "major",
}


def stream_board(path: Path):
    """Yield board records one at a time.

    The board is a 600MB JSON array and this runs on an 8GB machine, so it is
    decoded incrementally with raw_decode over gzip chunks rather than loaded.
    """
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


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _first_num(*vals):
    for v in vals:
        n = _num(v)
        if n is not None:
            return n
    return None


def cad_value(rec: dict) -> float | None:
    """County 100%-basis appraisal, mirroring valuation.calc._anchor_value.

    `assessed_value` is deliberately excluded: SC assesses at a 4%/6% statutory
    ratio, so it is a unit error rather than a value.
    """
    raw = rec.get("raw") or {}
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    return _first_num(
        rec.get("market_value"),
        cama.get("appraised_value"),
        cama.get("total_value"),
        rec.get("tax_value"),
    )


def _walk_keys(obj, out, depth=0):
    """Collect every key name anywhere in a nested record (bounded depth)."""
    if depth > 4:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            out[k] += 1
            _walk_keys(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:6]:
            _walk_keys(v, out, depth + 1)


def main() -> int:
    total = 0
    key_census: Counter[str] = Counter()

    have_cad = 0
    cad_a_tier = 0
    cad_below_floor = 0
    cad_missing = 0

    tax_delinq_any = 0
    tax_2yr_plus = 0
    tax_owed_dollars = 0          # a county actually STATED the arrears
    tax_owed_estimated = 0        # we only have our own estimate
    owed_real: list[float] = []
    chain_break = 0
    in_tax_lawsuit = 0            # named defendant in a tax suit
    multi_owner_signal = 0
    probate_heir_signal = 0
    lien_judgment_signal = 0
    absentee = 0
    margin_ok = 0

    liq = Counter()
    a_tier_by_county: Counter[str] = Counter()
    # the actual Fullmer A-lead: CAD>=200k AND 2yr+ delinquent AND liquid market
    a_leads = []

    for rec in stream_board(BOARD_GZ):
        total += 1
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if total <= 400:
            _walk_keys(rec, key_census)

        cad = cad_value(rec)
        if cad is None:
            cad_missing += 1
        else:
            have_cad += 1
            if cad >= CAD_A_TIER:
                cad_a_tier += 1
            if cad < CAD_FLOOR:
                cad_below_floor += 1

        blob = json.dumps(rec, default=str).lower()

        # --- delinquency ---
        # PATHS VERIFIED against the live board, not guessed. `raw.amount_owed` is
        # a dict, not a number, and it is usually SYNTHETIC: source
        # `estimated_tax_2yr` with `is_actual_debt: False` is the board's own
        # estimate (value x rate x 2yr), not a balance any county stated. Only
        # `is_actual_debt: True` is a real arrears figure, and that is the column
        # ep 022 actually cherry-picks on.
        tad = raw.get("two_year_delinquent") if isinstance(raw.get("two_year_delinquent"), dict) else {}
        surf = raw.get("tax_aging_surfaced") if isinstance(raw.get("tax_aging_surfaced"), dict) else {}
        yrs = _num(surf.get("years_delinquent"))
        two_plus = bool(tad.get("is_two_year_plus"))
        tax_year = tad.get("tax_year") or surf.get("tax_year")

        if two_plus or tax_year or yrs:
            tax_delinq_any += 1
        if two_plus or (yrs and yrs >= 2):
            tax_2yr_plus += 1

        ao = raw.get("amount_owed") if isinstance(raw.get("amount_owed"), dict) else {}
        owed = _num(ao.get("value"))
        if owed:
            tax_owed_estimated += 1
            if ao.get("is_actual_debt"):
                tax_owed_dollars += 1
                owed_real.append(owed)
            else:
                owed = None   # an estimate must not be ranked as if it were arrears

        # --- named in a tax lawsuit (the problem-aware trigger) ---
        lt = (rec.get("listing_type") or "").lower()
        src = (rec.get("source") or "").lower()
        if ("tax_foreclosure" in lt or "tax_foreclosure" in src
                or "tax_suit" in blob or "tax lawsuit" in blob
                or ("in rem" in blob and "tax" in blob)):
            in_tax_lawsuit += 1

        # --- the mess: multi-owner / heirs / probate / liens ---
        owner = (rec.get("owner_name") or "") + " " + (rec.get("defendant") or "")
        ol = owner.lower()
        if (" et al" in ol or "et al." in ol or " and " in ol or "," in ol.strip(",")
                or "heirs" in ol or "&" in ol):
            multi_owner_signal += 1
        if "probate" in blob or "estate of" in ol or "heirs" in blob or "decedent" in blob:
            probate_heir_signal += 1
        # A substring test for "lien" matched 100% of the board -- the word lives
        # in schema labels and source names, so it measured nothing. Structured
        # signals only.
        dc = raw.get("deed_chain") if isinstance(raw.get("deed_chain"), dict) else {}
        summ = dc.get("summary") if isinstance(dc.get("summary"), dict) else {}
        if _num(summ.get("chain_breaks")):
            chain_break += 1
        if _num(rec.get("judgment_amount")):
            lien_judgment_signal += 1
        ds = raw.get("distress_stack") if isinstance(raw.get("distress_stack"), dict) else {}
        if ds.get("absentee") or raw.get("absentee") or raw.get("owner_absentee"):
            absentee += 1

        margin = _num((raw.get("calc") or {}).get("est_gross_margin")) if isinstance(raw.get("calc"), dict) else None
        if margin is None:
            margin = _num(raw.get("est_gross_margin"))
        if margin and margin >= MARGIN_FLOOR:
            margin_ok += 1

        cty = (rec.get("county") or "").strip().lower()
        st = (rec.get("state") or "").strip().upper()
        tier = MSA_TIER.get((cty, st), "unmapped")
        liq[tier] += 1

        if cad and cad >= CAD_A_TIER:
            a_tier_by_county[f"{rec.get('county')},{st}"] += 1
            if yrs and yrs >= 2 and tier in ("major", "mid"):
                a_leads.append((cad, yrs, owed, rec.get("street_address"),
                                f"{rec.get('county')},{st}", rec.get("source")))

    p = lambda n: f"{n:>8,}  {n/total*100:5.1f}%"
    print(f"board rows: {total:,}\n")
    print("=== CAD VALUE GATE  (ep 021: 'worth 200 grand or above, on the CAD value') ===")
    print(f"  have a CAD value at all      {p(have_cad)}")
    print(f"  MISSING CAD value            {p(cad_missing)}   <- cannot be underwritten at all")
    print(f"  CAD >= $200k  (A-tier)       {p(cad_a_tier)}")
    print(f"  CAD <  $50k   (he declines)  {p(cad_below_floor)}")
    print()
    print("=== DELINQUENCY GATE  (book ch.20: 'two to three years behind') ===")
    print(f"  any delinquency signal       {p(tax_delinq_any)}")
    print(f"  2+ years delinquent (known)  {p(tax_2yr_plus)}")
    print(f"  arrears ESTIMATED by us      {p(tax_owed_estimated)}   (synthetic: value x rate x 2yr)")
    print(f"  arrears STATED by a county   {p(tax_owed_dollars)}   <- ep 022's primary cherry-pick column")
    if owed_real:
        owed_real.sort()
        print(f"      real arrears: median ${owed_real[len(owed_real)//2]:,.0f}  "
              f"p90 ${owed_real[int(len(owed_real)*0.9)]:,.0f}  max ${owed_real[-1]:,.0f}")
    print(f"  named in a tax lawsuit       {p(in_tax_lawsuit)}   <- ep 021's actual lead source")
    print()
    print("=== THE MESS  (book: 'the margin lives in the mess'; 70% heirship) ===")
    print(f"  multi-owner name signal      {p(multi_owner_signal)}")
    print(f"  probate / heirs / estate     {p(probate_heir_signal)}")
    print(f"  judgment_amount present      {p(lien_judgment_signal)}")
    print(f"  deed-chain break             {p(chain_break)}")
    print(f"  absentee owner               {p(absentee)}")
    print()
    print("=== EXIT LIQUIDITY  (ep 019: 'no liquidity ... does not matter') ===")
    for t in ("major", "mid", "thin", "unmapped"):
        print(f"  {t:<9} {p(liq[t])}")
    print()
    print(f"=== MARGIN  (ep 021: 'no lower than 50 grand') ===")
    print(f"  est_gross_margin >= $50k     {p(margin_ok)}")
    print()
    print("=== THE ACTUAL FULLMER A-LEAD (CAD>=200k AND 2yr+ delinquent AND liquid) ===")
    print(f"  count: {len(a_leads):,}")
    for cad, yrs, owed, addr, cty, src in sorted(a_leads, reverse=True)[:15]:
        o = f"${owed:,.0f}" if owed else "owed=?"
        print(f"    ${cad:>11,.0f}  {yrs:.0f}yr  {o:>10}  {str(addr)[:38]:<38} {cty:<18} {src}")
    print()
    print("=== keys seen in first 400 records that could carry delinquent DOLLARS ===")
    for k, n in sorted(key_census.items()):
        if any(t in k.lower() for t in ("owed", "due", "delinq", "balance", "arrear", "unpaid")):
            print(f"    {k}  x{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
