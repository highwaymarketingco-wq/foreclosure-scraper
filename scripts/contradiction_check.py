#!/usr/bin/env python3
"""Contradiction check — does each record disagree with ITSELF?

Every enricher bug shipped on 2026-09-09 passed its own unit tests. They tested
that a rule FIRED, never that the answer was TRUE. The commercial reclassifier is
the clean example: it correctly matched "Groceries-Retail" and rewrote the parcel
to commercial, while the same record said 4 bedrooms / 1,130 sqft. The refuting
evidence was on the row being written.

So this asserts nothing about the world. It only asks whether a record contradicts
itself, which is checkable locally and catches exactly that class of error:

  commercial kind        vs  a bedroom count
  contamination flag     vs  a dwelling
  land kind              vs  living_sqft + bedrooms
  offer_target           vs  as_is_value  (ordering, and >50c breaks the buy rule)
  vision condition grade vs  no image to have graded it from
  street_address         vs  legal-notice prose parsed into the field
  tax year               vs  a year in the future or before 1990
  as-is offer            vs  SC assessed_value (a 4%/6% statutory ratio, not market)

Read-only. Never writes. Run it after any enricher change.

    python scripts/contradiction_check.py
    python scripts/contradiction_check.py --sample 5      # show examples
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
BOARD = REPO / "docs" / "listings.json.gz"
NOW_YEAR = 2026

_JUNK_ADDR = re.compile(
    r"notice|having qualified|substitute trustee|executor|administrat|"
    r"deed of trust|recorded in book|estate of|qualified as", re.I)


def _stream(path: Path):
    dec = json.JSONDecoder()
    buf, started = "", False
    with gzip.open(path, "rt", encoding="utf-8") as f:
        while True:
            chunk = f.read(1 << 20)
            if chunk:
                buf += chunk
            if not started:
                i = buf.find("[")
                if i == -1:
                    if not chunk:
                        return
                    continue
                buf, started = buf[i + 1:], True
            while True:
                j = 0
                while j < len(buf) and buf[j] in " \t\r\n,":
                    j += 1
                buf = buf[j:]
                if not buf:
                    break
                if buf[0] == "]":
                    return
                try:
                    obj, end = dec.raw_decode(buf)
                except ValueError:
                    break
                buf = buf[end:]
                yield obj
            if not chunk:
                return


def _kind(rec):
    k = rec.get("property_kind")
    return str(getattr(k, "value", k) or "").lower()


CHECKS = []


def check(name, severity):
    def deco(fn):
        CHECKS.append((name, severity, fn))
        return fn
    return deco


@check("commercial_kind_with_bedrooms", "critical")
def _c1(rec, raw):
    return _kind(rec) == "commercial" and bool(rec.get("bedrooms"))


@check("contamination_flag_on_a_dwelling", "critical")
def _c2(rec, raw):
    if not raw.get("environmental_risk"):
        return False
    sqft = rec.get("living_sqft")
    return bool(rec.get("bedrooms")) or (isinstance(sqft, (int, float)) and 0 < sqft < 5000)


@check("land_kind_but_has_a_house", "high")
def _c3(rec, raw):
    if _kind(rec) != "land":
        return False
    sqft = rec.get("living_sqft")
    return bool(rec.get("bedrooms")) and isinstance(sqft, (int, float)) and sqft > 400


@check("offer_target_exceeds_as_is_value", "critical")
def _c4(rec, raw):
    c = raw.get("calc") or {}
    a, o = c.get("as_is_value"), c.get("offer_target")
    return isinstance(a, (int, float)) and isinstance(o, (int, float)) and o > a


@check("offer_target_above_50c_breaks_buy_rule", "high")
def _c5(rec, raw):
    c = raw.get("calc") or {}
    a, o = c.get("as_is_value"), c.get("offer_target")
    return (isinstance(a, (int, float)) and a > 0
            and isinstance(o, (int, float)) and o > a * 0.5)


@check("vision_graded_with_no_image", "high")
def _c6(rec, raw):
    src = str(raw.get("condition_source") or "")
    if not src.lower().startswith("vision"):
        return False
    imgs = raw.get("images") or {}
    if not isinstance(imgs, dict):
        return True
    z = raw.get("zillow") or {}
    return not (imgs.get("real") or imgs.get("street") or imgs.get("aerial")
                or (isinstance(z, dict) and (z.get("photos") or z.get("photo"))))


@check("legal_prose_in_street_address", "high")
def _c7(rec, raw):
    a = rec.get("street_address")
    return isinstance(a, str) and bool(_JUNK_ADDR.search(a))


@check("tax_year_impossible", "high")
def _c8(rec, raw):
    to = raw.get("tax_owed") or {}
    if not isinstance(to, dict):
        return False
    for k in ("year", "tax_year", "first_cycle", "oldest_year"):
        v = to.get(k)
        m = re.search(r"(19|20)\d{2}", str(v)) if v is not None else None
        if m:
            y = int(m.group(0))
            if y > NOW_YEAR or y < 1990:
                return True
    return False


@check("sc_offer_priced_off_statutory_ratio", "critical")
def _c9(rec, raw):
    # SC assessed_value is a 4%/6% ratio of market value. If as_is_value equals
    # it, the whole offer band is several-fold too low.
    if str(rec.get("state") or "").upper() != "SC":
        return False
    c = raw.get("calc") or {}
    a = c.get("as_is_value")
    av = rec.get("assessed_value")
    return (isinstance(a, (int, float)) and isinstance(av, (int, float))
            and av > 0 and abs(a - av) < 1.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=3)
    args = ap.parse_args()

    hits = Counter()
    examples = defaultdict(list)
    n = 0
    for rec in _stream(BOARD):
        n += 1
        raw = rec.get("raw") or {}
        if not isinstance(raw, dict):
            raw = {}
        for name, sev, fn in CHECKS:
            try:
                bad = fn(rec, raw)
            except Exception:
                continue
            if bad:
                hits[name] += 1
                if len(examples[name]) < args.sample:
                    examples[name].append(
                        f"{str(rec.get('street_address'))[:34]:<36} "
                        f"{str(rec.get('county'))},{rec.get('state')} "
                        f"kind={_kind(rec)} beds={rec.get('bedrooms')} "
                        f"sqft={rec.get('living_sqft')} lu={str(rec.get('land_use'))[:22]!r}")

    print(f"board {n:,}\n")
    sev_of = {name: sev for name, sev, _ in CHECKS}
    bad = 0
    for name, _, _ in CHECKS:
        c = hits[name]
        bad += c
        flag = "OK " if c == 0 else "!! "
        print(f"  {flag}{sev_of[name]:<9} {name:<42} {c:>7,}")
        for e in examples[name]:
            print(f"        {e}")
    print(f"\n  total self-contradicting records: {bad:,}")
    return 1 if any(hits[n2] for n2, s, _ in CHECKS if s == "critical") else 0


if __name__ == "__main__":
    raise SystemExit(main())
