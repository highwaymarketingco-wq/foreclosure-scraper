#!/usr/bin/env python3
"""Replace account-number / PIN style parcel_ids with the county's own parcel key, where the ROW ITSELF
carries the crosswalk. Two rules, both offline, both proven against the live board on 2026-09-21.

RULE L, Laurens SC qpaybill (393 rows). The treasurer roll's `identification_no` is a 6-digit ACCOUNT
number ("000789", "944994"), not a TMS, so the Laurens parcel cache cannot match it. The same raw block
carries the parcel: raw['qpaybill_roll']['detail']['map_number'] = "094-00-00-036.002". parcel_id becomes
that TMS. The account number stays in raw['qpaybill_roll']['identification_no'] and in backups/. A
sub-parcel suffix (".002" = the mobile home / item on that map parcel) is kept as written; the cache
holds only the parent parcel, so a cache lookup of a suffixed TMS still misses until the parent-parcel
fallback (which is deliberately not the default: the parent's owner can differ) is chosen.

RULE R, Rutherford NC (PIN-keyed rows, 338 rows). Rutherford's parcel cache is keyed by the 6-7 digit
Parcel_Number (REID); rows written with the 10-digit PIN ("1549378423", or dashed "1563-89-1446") never
match. Rutherford's own GIS bag, raw['gis_attrs_full'] = {PIN, LEGACY_PIN, REID, TAXPIN, PARCEL_PK}, is
the crosswalk, but ONLY when the bag is the row's own parcel: its PIN / LEGACY_PIN / REID equals the row's
parcel_id. For 295 of 367 Rutherford misses the attached bag is a DIFFERENT parcel (point-in-polygon on
approximate coordinates), so it is never trusted on its own. parcel_id becomes the REID.
What is missing for the other ~330 rows is not in the board: the cached layer
(gis.rutherfordcountync.gov TaxParcels/MapServer/0, verified 2026-09-21) DOES publish `PIN`, but
parcel_cache.PARCEL_LAYERS['Rutherford']['id_fields'] lists only Parcel_Number, so the cache indexes no PIN.
Add "PIN" to that list and refresh the cache (one network pull of about 57k parcels); see the doc.

Replaced ids are backed up under backups/ and kept in raw provenance. Fill-only elsewhere; the row
count is asserted unchanged.

    python scripts/map_account_ids_to_parcels.py            # dry run
    python scripts/map_account_ids_to_parcels.py --apply    # ONLY board process (about 3 GB)
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dq_common import iter_rows, norm_county, print_counter  # noqa: E402

TMS_RE = re.compile(r"^\d{3}-\d{2}-\d{2}-\d{3}(?:\.\d{3})?$")
ACCOUNT_RE = re.compile(r"^\d{6}$")


def _norm(x) -> str:
    return re.sub(r"[^0-9a-z]", "", str(x or "").lower())


def laurens_rule(state, county, parcel_id, raw) -> str | None:
    """New TMS for a Laurens SC row whose parcel_id is a 6-digit account number, else None."""
    if str(state or "").upper() != "SC" or norm_county(county) != "Laurens":
        return None
    if not ACCOUNT_RE.match(str(parcel_id or "").strip()):
        return None
    q = (raw or {}).get("qpaybill_roll")
    if not isinstance(q, dict):
        return None
    mn = str((q.get("detail") or {}).get("map_number") or "").strip()
    return mn if TMS_RE.match(mn) else None


def rutherford_rule(state, county, parcel_id, raw, cache_lookup) -> tuple[str | None, str]:
    """(REID, status) for a Rutherford NC row keyed by PIN whose own GIS bag names the REID."""
    if str(state or "").upper() != "NC" or norm_county(county) != "Rutherford":
        return None, "n/a"
    pid = str(parcel_id or "").strip()
    if not pid or cache_lookup(pid):
        return None, "already_resolves"
    g = (raw or {}).get("gis_attrs_full")
    if not isinstance(g, dict):
        return None, "no_gis_bag"
    keys = {_norm(g.get(k)) for k in ("PIN", "LEGACY_PIN", "REID", "TAXPIN")} - {"", "0", "none"}
    if not (_norm(pid) in keys):
        return None, "bag_is_a_different_parcel"
    reid = str(g.get("REID") or "").strip()
    if not re.fullmatch(r"\d{5,7}", reid) or reid == pid:
        return None, "bag_has_no_reid"
    if not cache_lookup(reid):
        return None, "reid_not_in_cache"
    return reid, "resolved"


def _cache_fn():
    from foreclosure_scraper import parcel_cache as pc

    def f(pid):
        return pc.lookup("Rutherford", pid, "NC")
    return f


# --------------------------------------------------------------------------------------- dry run
def _dry_run(rows_file=None) -> int:
    look = _cache_fn()
    c = Counter()
    n = 0
    for r in iter_rows(rows_file):
        n += 1
        raw = r.get("raw") or {}
        st, co, pid = r.get("state"), r.get("county"), r.get("parcel_id")
        if str(st or "").upper() == "SC" and norm_county(co) == "Laurens" and ACCOUNT_RE.match(str(pid or "").strip()):
            c["Laurens 6-digit account-number rows"] += 1
            tms = laurens_rule(st, co, pid, raw)
            c["  crosswalk map_number present -> parcel_id becomes the TMS" if tms else "  no usable map_number"] += 1
        if str(st or "").upper() == "NC" and norm_county(co) == "Rutherford" and str(pid or "").strip():
            reid, status = rutherford_rule(st, co, pid, raw, look)
            if status != "already_resolves":
                c["Rutherford rows whose parcel_id misses the cache"] += 1
                c[f"  {status}"] += 1
    print(f"board rows scanned: {n:,}")
    print_counter(c)
    print("DRY RUN, nothing written. Re-run with --apply (as the only board process).")
    return 0


# ----------------------------------------------------------------------------------------- apply
REQUIRED_RAW_KEYS = ["qpaybill_roll", "parcel_from_geo", "gis_attrs_full"]
BACKUP_NAME = "map_account_ids_to_parcels_replaced_ids"


def apply_rows(rows: list, *, dry_run: bool = False, cache_lookup=None) -> dict:
    """Swap account-number / PIN parcel_ids for the county's own key on Listing objects, in place. The replaced
    ids are returned under '_backup'. Never changes len(rows), never writes a file (reads the Rutherford
    parcel cache). dry_run=True mutates nothing."""
    from _dq_common import assert_raw_keep
    if not dry_run:
        assert_raw_keep(REQUIRED_RAW_KEYS)
    look = cache_lookup or _cache_fn()
    n = len(rows)
    c: Counter = Counter()
    backup: dict = {}
    for i, li in enumerate(rows):
        if not isinstance(li.raw, dict):
            continue
        new = laurens_rule(li.state, li.county, li.parcel_id, li.raw)
        if new:
            c["Laurens account number -> TMS"] += 1
            if not dry_run:
                backup[str(i)] = {"rule": "laurens_map_number", "source": li.source, "source_url": li.source_url,
                                  "old_parcel_id": li.parcel_id, "new_parcel_id": new}
                q = li.raw["qpaybill_roll"]
                q["is_account_id_not_parcel"] = True
                q["parcel_from_map_number"] = True
                q.setdefault("identification_no", li.parcel_id)
                li.parcel_id = new
            continue
        reid, _status = rutherford_rule(li.state, li.county, li.parcel_id, li.raw, look)
        if reid:
            c["Rutherford PIN -> REID"] += 1
            if not dry_run:
                backup[str(i)] = {"rule": "rutherford_gis_bag_reid", "source": li.source, "source_url": li.source_url,
                                  "old_parcel_id": li.parcel_id, "new_parcel_id": reid}
                li.raw["parcel_from_geo"] = {"source": "rutherford_gis_attrs_crosswalk",
                                            "verified": "bag_pin_equals_row_id", "pin": li.parcel_id}
                li.parcel_id = reid
    assert len(rows) == n, "a parcel-id mapping must never change the row count"
    out = {k: v for k, v in c.items() if v}
    if backup:
        out["_backup"] = backup
    return out


def _apply() -> int:
    from _dq_common import run_apply
    return run_apply("map_account_ids_to_parcels", apply_rows, REQUIRED_RAW_KEYS, BACKUP_NAME)


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
