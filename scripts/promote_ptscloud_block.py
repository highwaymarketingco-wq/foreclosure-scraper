#!/usr/bin/env python3
"""Promote the fields the Henderson (PTS cloud) delinquent-tax block already carries, and swap a junk
PTS number for the real PIN when the row itself proves which parcel it is.

Audit 2026-09-21 section 9: Henderson `nc_ptscloud_delinquent_tax` rows carry a PTS bill number in
`parcel_id` ("9941506", "113183"), not a 10-digit PIN, so the parcel-cache join cannot match them
(10 hits of 385) and every downstream parcel enricher skips them because they "have" a parcel_id.
The same rows carry `raw['nc_ptscloud_delinquent_tax']` = {parcel (the PTS number), owner, mailing{addr1,
addr2, ...}, assessed_value, prop_size, legal_description, tax_year, principal_tax_due}.

MEASURED on the live board (dry run): every one of the PTS-number rows already has owner_name and a
value, and most already have an owner mailing, because point-in-polygon on the row's coordinates
attached a county_gis / nc_onemap parcel and its owner_mailing (with that parcel's real PIN inside it).
So a pure "fill what is missing" promotion has little to fill. The real prize is that PIN, and the real
risk is that the coordinates are approximate: for a fifth of these rows the attached parcel belongs to
a stranger.

WHAT --apply DOES, per PTS-number row (fill-only unless stated):
  1. owner_name, assessed_value, acreage (from prop_size), legal_description: from the block, only when
     blank. Placeholder owners ("UNKNOWN OWNER") are never promoted.
  2. raw['owner_mailing']: built from the block's own mailing address (the taxpayer's bill address) only
     when the row has none. absentee is derived only when the row has a street address.
  3. parcel_id: the PTS number is REPLACED by the PIN found in raw['owner_mailing']['parcel_id'] only
     when that PIN is a 10-digit Henderson PIN present in the Henderson parcel cache AND the cache's owner
     shares a surname/name token with the delinquent taxpayer. The replaced PTS number stays in the block
     (`parcel`) and in backups/, and raw['parcel_from_geo'] records the basis.
  4. raw['owner_mismatch'] (flag only, nothing removed) when the parcel the coordinates resolved to has an
     owner that does NOT match the taxpayer: its owner, mailing and street are then a stranger's.

    python scripts/promote_ptscloud_block.py            # dry run
    python scripts/promote_ptscloud_block.py --apply    # ONLY board process (about 3 GB)
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dq_common import iter_rows, norm_county, print_counter  # noqa: E402

SRC_KEY = "nc_ptscloud_delinquent_tax"
_PIN10 = re.compile(r"^\d{10}$")
_STOPW = {"THE", "AND", "TRUSTEE", "TRUSTEES", "TRUST", "LLC", "INC", "ETAL", "ETUX", "ETVIR", "HEIRS", "HEIR",
          "ESTATE", "OF", "FOR", "LIVING", "REVOCABLE", "JR", "SR", "III", "II", "CO", "LP", "LTD", "CORP",
          "UNKNOWN", "OWNER", "NAME", "DECEASED", "ET", "AL", "UX", "VIR", "TR"}
_PLACEHOLDER = {"UNKNOWN OWNER", "UNKNOWN", "OWNER UNKNOWN", "NAME UNKNOWN", ""}


def name_tokens(s) -> set[str]:
    return {t for t in re.findall(r"[A-Z]{2,}", str(s or "").upper()) if t not in _STOPW}


def owners_agree(a, b) -> bool:
    """True when two owner strings share enough real name tokens to be the same party: two when both names
    have two or more ("DALTON, DWIGHT" against "DALTON, DWIGHT E. TRUSTEE"), one when a side is a single token.
    A shared surname alone (a neighbour called SMITH) is not agreement. Placeholders never agree."""
    if is_placeholder_owner(a) or is_placeholder_owner(b):
        return False
    ta, tb = name_tokens(a), name_tokens(b)
    if not (ta and tb):
        return False
    return len(ta & tb) >= min(2, len(ta), len(tb))


_PLACEHOLDER_PAT = re.compile(r"\b(UNKNOWN|UNIDENTIFIED|MAPPING\s+WORK|WORK\s+IN\s+PROGRESS|NOT\s+AVAILABLE|TBD|NO\s+OWNER)\b")


def is_placeholder_owner(s) -> bool:
    u = " ".join(str(s or "").upper().split())
    return u in _PLACEHOLDER or bool(_PLACEHOLDER_PAT.search(u))


def is_pts_row(source, parcel_id, block) -> bool:
    """A ptscloud row whose parcel_id is the block's own PTS number rather than a 10-digit PIN."""
    if SRC_KEY not in str(source or "") or not isinstance(block, dict):
        return False
    pid = str(parcel_id or "").strip()
    return bool(pid) and pid == str(block.get("parcel") or "").strip() and not _PIN10.match(pid)


def block_mailing(block) -> str | None:
    m = block.get("mailing")
    if not isinstance(m, dict):
        return None
    parts = [str(m.get(k) or "").strip() for k in ("addr1", "addr2", "addr3")]
    s = " ".join(p for p in parts if p) or str(m.get("addr") or "").strip()
    return re.sub(r"\s+", " ", s).strip(" ,") or None


def acres_from(prop_size) -> float | None:
    m = re.match(r"\s*([\d.]+)\s*AC", str(prop_size or ""), re.I)
    try:
        v = float(m.group(1)) if m else 0.0
    except ValueError:
        return None
    return v if v > 0 else None


def plan(*, source, county="Henderson", parcel_id, owner_name, assessed_value, acreage, legal_description, street,
         raw, cache_lookup) -> dict:
    """Pure decision for one row. `cache_lookup(pin)` returns the Henderson cache hit dict or None. Only Henderson
    rows are handled: the 10-digit PIN shape and the cache are Henderson's (the four Hyde PTS rows on the board
    are reported as status 'other_county' and left alone).
    Returns {'is_pts': bool, 'fill': {...}, 'owner_mailing': dict|None, 'new_parcel': str|None,
             'mismatch': dict|None, 'status': str}."""
    raw = raw if isinstance(raw, dict) else {}
    block = raw.get(SRC_KEY)
    out = {"is_pts": False, "fill": {}, "owner_mailing": None, "new_parcel": None, "mismatch": None, "status": "skip"}
    if not is_pts_row(source, parcel_id, block):
        return out
    if norm_county(county) != "Henderson":
        out["status"] = "other_county"
        return out
    out["is_pts"] = True
    taxpayer = str(block.get("owner") or "").strip()
    fill = out["fill"]
    if not str(owner_name or "").strip() and taxpayer and not is_placeholder_owner(taxpayer):
        fill["owner_name"] = taxpayer
    if not assessed_value and block.get("assessed_value"):
        fill["assessed_value"] = block["assessed_value"]
    if not acreage and acres_from(block.get("prop_size")):
        fill["acreage"] = acres_from(block.get("prop_size"))
    if not str(legal_description or "").strip() and str(block.get("legal_description") or "").strip():
        fill["legal_description"] = str(block["legal_description"]).strip()

    om = raw.get("owner_mailing")
    bm = block_mailing(block)
    if not (isinstance(om, dict) and om.get("mailing")) and not isinstance(om, str) and bm:
        d = {"owner": taxpayer or None, "mailing": bm, "source": "ptscloud_block"}
        m = re.search(r"\b([A-Z]{2})\b[\s,]*(?:\d{5}(?:[\s-]+\d{4})?)?\s*$", bm.upper())
        if m:
            d["mail_state"] = m.group(1)
        out["owner_mailing"] = d

    om = om if isinstance(om, dict) else {}
    pin = str(om.get("parcel_id") or "").strip()
    if _PIN10.match(pin) and taxpayer and not is_placeholder_owner(taxpayer):
        hit = cache_lookup(pin)
        if not hit:
            out["status"] = "pin_not_in_cache"
        elif owners_agree(taxpayer, hit.get("owner")):
            out["new_parcel"] = pin
            out["status"] = "promote_pin"
        else:
            out["status"] = "resolved_parcel_owner_differs"
            surname = re.findall(r"[A-Za-z]{2,}", taxpayer)
            out["mismatch"] = {"defendant_surname": (surname[0] if surname else taxpayer)[:40],
                               "snapped_owner": str(hit.get("owner") or "")[:80], "source": SRC_KEY}
    else:
        out["status"] = "no_pin_to_promote"
    return out


def _lookup_fn():
    from foreclosure_scraper import parcel_cache as pc

    def f(pin):
        return pc.lookup("Henderson", pin, "NC")
    return f


# --------------------------------------------------------------------------------------- dry run
def _dry_run(rows_file=None) -> int:
    look = _lookup_fn()
    c = Counter()
    sample = []
    n = 0
    for r in iter_rows(rows_file):
        n += 1
        raw = r.get("raw") or {}
        p = plan(source=r.get("source"), county=r.get("county"), parcel_id=r.get("parcel_id"), owner_name=r.get("owner_name"),
                 assessed_value=r.get("assessed_value"), acreage=r.get("acreage"),
                 legal_description=r.get("legal_description"), street=r.get("street_address"),
                 raw=raw, cache_lookup=look)
        if p["status"] == "other_county":
            c[f"PTS-number rows in {norm_county(r.get('county')) or '(none)'} (not handled)"] += 1
            continue
        if not p["is_pts"]:
            continue
        c["PTS-number rows (Henderson)"] += 1
        for k in p["fill"]:
            c[f"fill {k}"] += 1
        if p["owner_mailing"]:
            c["fill owner_mailing from block"] += 1
        c[f"pin: {p['status']}"] += 1
        if p["new_parcel"]:
            c["parcel_id PTS -> PIN"] += 1
            if len(sample) < 3:
                sample.append((r.get("parcel_id"), p["new_parcel"], (raw.get(SRC_KEY) or {}).get("owner")))
        if p["mismatch"]:
            c["owner_mismatch flag"] += 1
    print(f"board rows scanned: {n:,}")
    print_counter(c)
    print("sample (PTS number, PIN, taxpayer):", sample)
    print("DRY RUN, nothing written. Re-run with --apply (as the only board process).")
    return 0


# ----------------------------------------------------------------------------------------- apply
REQUIRED_RAW_KEYS = ["owner_mailing", "parcel_from_geo", "owner_mismatch", SRC_KEY]
BACKUP_NAME = "promote_ptscloud_block_replaced_parcel_ids"


def apply_rows(rows: list, *, dry_run: bool = False, cache_lookup=None) -> dict:
    """Promote the ptscloud block on Listing objects, in place (fill-only, except the PTS number -> PIN swap
    whose old value is returned under '_backup'). Never changes len(rows), never writes a file (reads the
    Henderson parcel cache). dry_run=True mutates nothing."""
    from _dq_common import assert_raw_keep
    if not dry_run:
        assert_raw_keep(REQUIRED_RAW_KEYS)
    from foreclosure_scraper.enrichment_owner_mailing import _is_absentee
    look = cache_lookup or _lookup_fn()
    n = len(rows)
    c: Counter = Counter()
    backup: dict = {}
    for i, li in enumerate(rows):
        if not isinstance(li.raw, dict):
            continue
        p = plan(source=li.source, county=li.county, parcel_id=li.parcel_id, owner_name=li.owner_name,
                 assessed_value=li.assessed_value, acreage=li.acreage,
                 legal_description=li.legal_description, street=li.street_address, raw=li.raw,
                 cache_lookup=look)
        if not p["is_pts"]:
            continue
        c["PTS-number rows (Henderson)"] += 1
        for k in p["fill"]:
            c[f"filled {k}"] += 1
        if p["owner_mailing"]:
            c["filled owner_mailing"] += 1
        if p["new_parcel"]:
            c["parcel_id PTS -> PIN"] += 1
        if p["mismatch"] and not li.raw.get("owner_mismatch"):
            c["owner_mismatch flagged"] += 1
        if dry_run:
            continue
        for k, v in p["fill"].items():
            setattr(li, k, v)
        if p["owner_mailing"]:
            d = p["owner_mailing"]
            if (li.street_address or "").strip():
                d["situs"] = li.street_address
                d["absentee"] = _is_absentee(li.street_address, d["mailing"])
            li.raw["owner_mailing"] = d
        if p["new_parcel"]:
            backup[str(i)] = {"source": li.source, "source_url": li.source_url, "old_parcel_id": li.parcel_id,
                              "new_parcel_id": p["new_parcel"]}
            li.raw["parcel_from_geo"] = {"source": "ptscloud_pts_to_pin", "verified": "owner_name_agrees",
                                         "pts_number": li.parcel_id}
            li.parcel_id = p["new_parcel"]
        if p["mismatch"] and not li.raw.get("owner_mismatch"):
            li.raw["owner_mismatch"] = p["mismatch"]
    assert len(rows) == n, "a promotion must never change the row count"
    out = {k: v for k, v in c.items() if v}
    if backup:
        out["_backup"] = backup
    return out


def _apply() -> int:
    from _dq_common import run_apply
    return run_apply("promote_ptscloud_block", apply_rows, REQUIRED_RAW_KEYS, BACKUP_NAME)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the board (ONLY board process)")
    ap.add_argument("--rows-file", help="dry run over a saved JSONL extract instead of the live board")
    args = ap.parse_args()
    if not args.apply:
        return _dry_run(args.rows_file)
    if args.rows_file:
        raise SystemExit("--rows-file is dry-run only")
    return _apply()


if __name__ == "__main__":
    raise SystemExit(main())
