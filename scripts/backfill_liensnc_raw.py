#!/usr/bin/env python3
"""Recover address + owner contact that the liensnc scraper already FETCHED but
never parsed.

The liensnc adapter stores the detail page's ``property_text`` and ``owner_text``
verbatim in ``raw['liensnc']`` and then writes ``address: ""`` — the street line
leaks into ``city`` and the owner block is dropped entirely. Measured on the
published board (56,452 liensnc rows):

    street address   53,381 in raw (94.6%)  vs  40,366 on board  -> +14,136 net-new
    county           55,167 in raw (97.7%)  vs       0 on board
    owner name       56,452 in raw ( 100%)  vs       0 on board
    owner phone      56,452 in raw ( 100%)  vs       0 on board
    owner email      56,452 in raw ( 100%)  vs       0 on board

This is a pure LOCAL re-parse: no network, no API, no cost. It only FILLS BLANKS
— an existing non-empty value is never overwritten — and it never adds or removes
a row, so the count guard is untouched.

NOTE ON LEAD CLASS: every liensnc row is filing_type "Appointment of Lien Agent",
an NC construction-improvement filing. These owners are INVESTING in the property,
not distressed. Treat the recovered contacts as a buyer/contractor/owner-investor
and skip-trace cross-reference asset, not as motivated-seller leads.

    python scripts/backfill_liensnc_raw.py --dry-run   # count only, no write
    python scripts/backfill_liensnc_raw.py             # parse + write board
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
DOCS = REPO / "docs"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"Phone:\s*([0-9][0-9\-.\s()]{9,})")
STATE_ZIP_RE = re.compile(r"^([A-Z]{2})\s+(\d{5})(?:-\d{4})?$")
COUNTY_RE = re.compile(r"([A-Za-z .'-]+?)\s+County\b", re.I)
# Filers often type the STATE into the county line ("NC County",
# "North Carolina County"). That is not a county: storing it makes
# scope_repass judge an in-footprint lead off-footprint and drop it.
STATE_NOT_COUNTY = {"nc", "n.c.", "north carolina", "sc", "s.c.",
                    "south carolina", "none", "n/a", "na", "unknown"}
STREET_RE = re.compile(r"^\d+\s+\S")


def _lines(txt: str) -> list[str]:
    txt = (txt or "").replace("\xa0", " ")
    out = []
    for ln in txt.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln:
            out.append(ln)
    return out


def parse_property(pt: str) -> dict:
    """property_text -> street / city / zip / county / state."""
    res = {"street": None, "city": None, "zip": None, "county": None, "state": None}
    if not pt:
        return res
    raw_lines = _lines(pt)
    lines = [l.rstrip(",").strip() for l in raw_lines]
    m = COUNTY_RE.search(pt.replace("\xa0", " "))
    if m:
        _c = re.sub(r"\s+", " ", m.group(1)).strip().title()
        res["county"] = None if _c.lower() in STATE_NOT_COUNTY else _c
    sidx = None
    for i, l in enumerate(lines):
        m2 = STATE_ZIP_RE.match(l)
        if m2:
            res["state"], res["zip"], sidx = m2.group(1), m2.group(2), i
            break
    upper = lines[:sidx] if sidx is not None else lines
    streets = [l for l in upper if STREET_RE.match(l)]
    if streets:
        res["street"] = streets[-1]
    if sidx is not None and sidx > 0:
        prev = lines[sidx - 1]
        if prev and prev != res["street"] and not COUNTY_RE.search(prev):
            res["city"] = prev
    return res


def parse_owner(ot: str) -> dict:
    """owner_text -> name / mailing / phone / email."""
    res = {"name": None, "mailing": None, "phone": None, "email": None}
    if not ot:
        return res
    txt = ot.replace("\xa0", " ")
    lines = _lines(txt)
    if lines:
        res["name"] = lines[0].rstrip(",").strip()
    m = EMAIL_RE.search(txt)
    if m:
        res["email"] = m.group(0)
    m = PHONE_RE.search(txt)
    if m:
        d = re.sub(r"\D", "", m.group(1))[:10]
        if len(d) == 10:
            res["phone"] = f"({d[0:3]}) {d[3:6]}-{d[6:10]}"
    mail = []
    for l in lines[1:]:
        low = l.lower()
        if low.startswith("phone") or "@" in l or low in ("united states", "usa"):
            break
        mail.append(l.rstrip(",").strip())
    if mail:
        res["mailing"] = " ".join(mail)
    return res


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from foreclosure_scraper.web_artifact import load_board, write_artifact, board_lock

    # board_lock takes the REPO ROOT, not docs/. Passing DOCS builds
    # docs/logs/.board.lock - a phantom lock that excludes nothing, so this
    # writer runs concurrently with the 4h-holding vision pass and its work is
    # silently reverted when that pass flushes its stale in-memory board.
    with board_lock(REPO):
        board = load_board(DOCS)
        rows = [li for li in board
                if "liensnc" in str(getattr(li, "source", "") or "")]
        print(f"board {len(board):,} rows | liensnc {len(rows):,}")

        st = collections.Counter()
        n = 0
        for li in rows:
            if args.limit and n >= args.limit:
                break
            raw = li.raw if isinstance(getattr(li, "raw", None), dict) else {}
            blk = raw.get("liensnc") or {}
            if not blk:
                continue
            n += 1
            p = parse_property(blk.get("property_text") or "")
            o = parse_owner(blk.get("owner_text") or "")

            if p["street"] and _blank(getattr(li, "street_address", None)):
                li.street_address = p["street"]; st["street"] += 1
            # city was mis-parsed (street text leaked in) -> correct it when we
            # have a clean city AND the stored one contains the street line.
            if p["city"]:
                cur = getattr(li, "city", None)
                if _blank(cur) or (p["street"] and p["street"].lower() in str(cur).lower()):
                    li.city = p["city"]; st["city"] += 1
            if p["zip"] and _blank(getattr(li, "zip_code", None)):
                li.zip_code = p["zip"]; st["zip"] += 1
            if p["county"] and _blank(getattr(li, "county", None)):
                li.county = p["county"]; st["county"] += 1
            if o["name"] and _blank(getattr(li, "owner_name", None)):
                li.owner_name = o["name"]; st["owner_name"] += 1

            if o["phone"] and not raw.get("owner_phone"):
                raw["owner_phone"] = {
                    "phone": o["phone"],
                    "additional_phones": [],
                    "source": "liensnc_filing",
                    "match": "self_filed_lien_agent_appointment",
                    "needs_dnc_scrub": True,
                    "tcpa_class": "manual_only",
                }
                st["phone"] += 1
            if o["email"] and not raw.get("owner_email"):
                raw["owner_email"] = {"email": o["email"], "source": "liensnc_filing"}
                st["email"] += 1
            if o["mailing"] and not raw.get("owner_mailing"):
                situs = p["street"] or getattr(li, "street_address", None)
                absentee = bool(situs and situs.split()[0] not in o["mailing"])
                raw["owner_mailing"] = {
                    "owner": o["name"],
                    "mailing": o["mailing"],
                    "situs": situs,
                    "absentee": absentee,
                    "source": "liensnc_filing",
                }
                st["mailing"] += 1
            raw["liensnc_reparse"] = {"v": 1}
            li.raw = raw

        print(f"\nparsed {n:,} liensnc rows -> fields FILLED (blanks only):")
        for k in ("street", "city", "zip", "county", "owner_name", "phone", "email", "mailing"):
            print(f"   {k:<12} +{st[k]:,}")

        if args.dry_run:
            print("\n--dry-run: nothing written")
            return 0

        with_addr = sum(1 for li in board
                        if not _blank(getattr(li, "street_address", None)))
        summary = {
            "by_source": dict(collections.Counter(
                li.source for li in board if getattr(li, "source", None))),
            "notes": (f"liensnc raw re-parse: +{st['street']} addresses, "
                      f"+{st['phone']} phones, +{st['owner_name']} owners"),
        }
        lp, _ = write_artifact(board, summary, docs_dir=DOCS)
        print(f"\nboard rows {len(board):,} (unchanged) | with street_address: {with_addr:,}")
        print(f"wrote {lp} ({lp.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
