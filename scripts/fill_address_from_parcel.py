#!/usr/bin/env python3
"""Fill the property street address (and city / zip where provable) from the local parcel data.

WHY. 34,010 leads have no street address and about 16,000 of them already carry a parcel_id
(audit 2026-09-21 section 16). scripts/join_parcel_cache_to_board.py fills `street_address` from
`data/parcel_cache/*.sqlite` when a lookup hits, but two things stop it working:

  1. MOST OF THE MISSES ARE NOT FORMAT PROBLEMS. Measured on the live board: 12 of the 20 biggest
     address-gap counties have NO cache at all (Greenville, Florence, Williamsburg, Berkeley,
     Allendale, Marlboro, Cherokee SC, Jasper, Clarendon, Georgetown, McCormick, Kershaw ...), and
     the caches that exist often hold no address (Horry, Oconee: 0%) or hold a LEGAL DESCRIPTION
     in the address column ("SPLIT FROM 116-00-01-048", "OFF SR 1151 EXT", "COMMON AREA-WHITEWATER
     COVE", "S-6-65", "PINEWOOD ACRES  3101 CAMDEN DR", McDowell "1163"). Transylvania's whole
     address column is LEGAL_ADDR, so its "street" is a subdivision and lot, and vacant land has
     no house number at all.
  2. The join script copies `hit["address"]` into street_address WITHOUT looking at it. Some of
     that text passes web_artifact._is_valid_street_address ("COMMON AREA-WHITEWATER COVE" ends in
     a road word), so it would be published as the property's address.

WHAT THIS DOES (state-qualified, never guesses across counties, fill-only):
  * looks the parcel up with parcel_cache.lookup_with_tier (which now also resolves a delimited
    all-zero sub-parcel suffix and zero-padding differences; see parcel_cache._lookup_candidates),
  * classifies the cache text: numbered street address | road only | legal description or junk,
  * fills street_address ONLY from a numbered address, and stashes a road-only name under
    raw['situs_road_only'] (the convention enrichment_situs_address already uses),
  * fills city and zip ONLY when the owner's mailing address starts with the same street (the
    owner mails to the property, so the mailing city and zip are the property's), or when an
    address-point overlay (data/address_points/<county>.sqlite) supplies them,
  * upgrades a street-NAME-ONLY address to the numbered situs when the parcel's numbered address
    names the same street (Transylvania item; the cache has almost none, the overlay has all),
  * skips tax_sale_overage (the cache owner is not the claimant) and any (county, state) pair that
    is not a real county of that state.

    python scripts/fill_address_from_parcel.py                 # dry run: per-county table, no writes
    python scripts/fill_address_from_parcel.py --apply         # ONLY board process (about 3 GB)

Optional overlay: scripts/build_transylvania_address_points.py writes
data/address_points/transylvania.sqlite from the county's own E911 address layer (numbered
address + postal city + zip, keyed by parcel number). Not built by default.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dq_common import (REPO, county_in_state, iter_rows, lt_str, norm_county,  # noqa: E402
                        print_counter)

OVERLAY_DIR = REPO / "data" / "address_points"

_WS = re.compile(r"[\s ]+")
_HOUSE = re.compile(r"^(?P<num>\d+)(?P<suf>[A-Za-z]?)(?:\s*[-/&]\s*\d+[A-Za-z]?)?\s+(?P<rest>\S.*)$")
_LEGAL_HEAD = re.compile(r"^(ACRES?|AC|LOTS?|LT|TRACT|TR|PART|PT|PARCEL|BLK|BLOCK|SEC|SECTION)\b", re.I)
_STOP = {"ST", "STREET", "RD", "ROAD", "DR", "DRIVE", "LN", "LANE", "AVE", "AVENUE", "CT", "COURT",
         "CIR", "CIRCLE", "HWY", "HIGHWAY", "BLVD", "WAY", "PL", "PLACE", "TRL", "TRAIL", "TR", "TER",
         "TERRACE", "PKWY", "PARKWAY", "LOOP", "PIKE", "N", "S", "E", "W", "NE", "NW", "SE", "SW",
         "NORTH", "SOUTH", "EAST", "WEST", "NC", "SC", "US"}
_ACREAGE_TAIL = re.compile(r"\s+\d*\.\d+$")
_CITY_ZIP = re.compile(r"^(?P<city>[A-Za-z][A-Za-z .'\-]*?)[ ,]+(?P<st>[A-Z]{2})"
                       r"(?:[ ,]+(?P<zip>\d{5})\d{0,4})?$")


# --------------------------------------------------------------------------------------- classify
def _clean(s) -> str:
    return _WS.sub(" ", str(s or "")).strip()


def classify_situs(addr) -> dict:
    """Judge one situs string from a parcel cache.

    kind is one of:
      'numbered'  a real house number then a street ("3101 CAMDEN DR", "000141 LEVI DR" -> "141 LEVI DR")
      'road_only' a street with no house number ("MEADOW RD", or a "0 CALHOUN TRL" / "99999 X" sentinel)
      'legal'     a legal description, subdivision, "OFF SR 1151 EXT", a bare lot number, a plat
      'junk'      empty, "NO ADDRESS", C/O, PO box
    Returns {'kind', 'address' (numbered only), 'road' (road_only only), 'reason'}.
    """
    from foreclosure_scraper.enrichment_situs_address import _is_junk_address
    from foreclosure_scraper.web_artifact import _is_valid_street_address

    s = _clean(addr)
    if not s or _is_junk_address(s):
        return {"kind": "junk", "reason": "empty_or_placeholder"}
    s = _ACREAGE_TAIL.sub("", s)          # "12C TOXAWAY FALLS DR .86": the county appends the acreage
    m = _HOUSE.match(s)
    if m:
        num, suf, rest = m.group("num"), m.group("suf"), m.group("rest")
        digits = num.lstrip("0")
        words = [w for w in re.findall(r"[A-Za-z]+", rest) if len(w) >= 2]
        # a street name: one word of 3+ letters ("OAK ST"), or two of 2+ ("OX RD", "3RD ST")
        alpha_words = words if (any(len(w) >= 3 for w in words) or len(words) >= 2) else []
        if not digits or (set(num) == {"9"} and len(num) >= 4):
            # no-house-number sentinel: NC layers publish "0 X" and "99999 X"
            # The layer itself put a road after the sentinel ("0 QUEENS GAP", "99999 DUCKERS VW"), so it
            # is a road name whether or not its suffix is one this repo recognizes.
            if alpha_words:
                return {"kind": "road_only", "road": rest, "reason": f"sentinel_house_number:{num}"}
            return {"kind": "legal", "reason": "sentinel_no_street"}
        if alpha_words and not _LEGAL_HEAD.match(rest):
            return {"kind": "numbered", "address": f"{digits}{suf.upper()} {rest}"}
        return {"kind": "legal", "reason": "number_then_no_street_word"}
    if _is_valid_street_address(s) and not re.search(r"\d", s):
        return {"kind": "road_only", "road": s, "reason": "no_house_number"}
    return {"kind": "legal", "reason": "not_a_street"}


def street_words(s) -> frozenset:
    """Street-name words with the number, suffix and direction removed, for name agreement."""
    toks = re.findall(r"[A-Z0-9]+", str(s or "").upper())
    return frozenset(t for t in toks if not t.isdigit() and t not in _STOP and len(t) > 1)


_DIRS = {"N": "N", "NORTH": "N", "S": "S", "SOUTH": "S", "E": "E", "EAST": "E", "W": "W", "WEST": "W",
         "NE": "NE", "NW": "NW", "SE": "SE", "SW": "SW"}


def street_dirs(s) -> frozenset:
    """Directional tokens ("N", "SOUTH") of a street, normalized. "S CHESTER ST" and "N CHESTER ST" are
    different roads even though their names are the same word."""
    return frozenset(_DIRS[t] for t in re.findall(r"[A-Z]+", str(s or "").upper()) if t in _DIRS)


def has_house_number(street) -> bool:
    return bool(_HOUSE.match(_clean(street)))


def city_zip_from_mailing(situs: str, mailing, lead_state) -> tuple[str | None, str | None]:
    """(city, zip) when the owner's mailing address BEGINS with the property's own street. An
    owner who mails to the property is at the property, so its city and zip are the lead's.
    Requires the mailing state to equal the lead state; the zip is optional."""
    if not situs or not mailing or not lead_state:
        return None, None

    def n(x):
        return _WS.sub(" ", re.sub(r"[.,#]", " ", str(x).upper())).strip()

    ms, ss = n(mailing), n(situs)
    if not ms.startswith(ss + " "):
        return None, None
    m = _CITY_ZIP.match(ms[len(ss):].strip())
    if not m or m.group("st") != str(lead_state).upper():
        return None, None
    city = m.group("city").strip().title()
    return (city if len(city) >= 3 else None), m.group("zip")


# ---------------------------------------------------------------------------------------- overlay
def overlay_lookup(county: str, state: str, parcel_id: str) -> dict | None:
    """Address-point overlay: data/address_points/<county>[_<st>].sqlite, table pts(id, address, city,
    zip), keyed by the same normalized id parcel_cache uses. None when there is no overlay."""
    from foreclosure_scraper import parcel_cache as pc
    stem = pc._db_path(county, state).stem if county in pc.DUAL_STATE_COUNTIES else county.lower().replace(" ", "_")
    p = OVERLAY_DIR / f"{stem}.sqlite"
    if not p.exists():
        return None
    con = _OVERLAY.get(p)
    if con is None:
        con = _OVERLAY[p] = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    for k, _tier in pc._lookup_candidates(parcel_id):
        row = con.execute("SELECT address, city, zip FROM pts WHERE id=? LIMIT 1", (k,)).fetchone()
        if row and row[0]:
            return {"address": row[0], "city": row[1], "zip": row[2]}
    return None


_OVERLAY: dict = {}


# ------------------------------------------------------------------------------------------- plan
def plan_fill(*, state, county, listing_type, parcel_id, street, city, zip_code, mailing,
              hit, tier, cache_exists=True, overlay=None) -> dict:
    """Pure decision for one lead. Returns
       {'pop': 'gap'|'name_only'|None, 'status': str, 'set': {...}, 'road_only': {...}|None,
        'replaced_street': str|None, 'kind': str|None}
    pop is the population the lead belongs to (no street / street name only); None means the lead
    already has a numbered address or has nothing to join on, and nothing is done to it."""
    street = _clean(street)
    if not street:
        pop = "gap"
    elif not has_house_number(street):
        pop = "name_only"
    else:
        return {"pop": None, "status": "has_numbered_address", "set": {}, "road_only": None,
                "replaced_street": None, "kind": None}

    def out(status, kind=None, set_=None, road=None, replaced=None):
        return {"pop": pop, "status": status, "set": set_ or {}, "road_only": road,
                "replaced_street": replaced, "kind": kind}

    if lt_str(listing_type) == "tax_sale_overage":
        return out("skip_tax_sale_overage")      # the cache owner is not the claimant
    if not str(parcel_id or "").strip():
        return out("skip_no_parcel")
    if not county_in_state(county, state):
        return out("skip_county_not_in_state")
    if overlay is None and hit is None:
        return out("no_cache" if not cache_exists else "miss")

    # Candidate situs: the address-point overlay first (numbered by construction), then the cache.
    cand_addr, cand_city, cand_zip, src = None, None, None, None
    if overlay and overlay.get("address"):
        c = classify_situs(overlay["address"])
        if c["kind"] == "numbered":
            cand_addr, cand_city, cand_zip, src = c["address"], overlay.get("city"), overlay.get("zip"), "address_points"
    cache_kind = None
    if cand_addr is None and hit:
        raw_addr = hit.get("address")
        if not raw_addr:
            return out("hit_no_address")
        c = classify_situs(raw_addr)
        cache_kind = c["kind"]
        if c["kind"] == "numbered":
            cand_addr, src = c["address"], f"parcel_cache:{tier}"
        elif c["kind"] == "road_only":
            road = {"road": c["road"], "reason": c["reason"],
                    "note": "road centroid only, not a building, never mail or Street View this"}
            return out("road_only", "road_only", road=road)
        else:
            return out("hit_legal_or_junk", c["kind"])
    if cand_addr is None:
        return out("hit_no_address")

    set_ = {}
    if pop == "gap":
        set_["street_address"] = cand_addr
        status = "filled"
    else:
        # street NAME only -> numbered: only when both name the same street
        d1, d2 = street_dirs(street), street_dirs(cand_addr)
        if not (street_words(street) and street_words(street) == street_words(cand_addr)) or (d1 and d2 and d1 != d2):
            return out("name_only_street_disagrees", "numbered")
        set_["street_address"] = cand_addr
        status = "upgraded"
    if not _clean(city):
        cc = cand_city if src == "address_points" else city_zip_from_mailing(
            cand_addr, (hit or {}).get("owner_mailing") or mailing, state)[0]
        if cc:
            set_["city"] = cc
    if not _clean(zip_code):
        zz = cand_zip if src == "address_points" else city_zip_from_mailing(
            cand_addr, (hit or {}).get("owner_mailing") or mailing, state)[1]
        if zz:
            set_["zip_code"] = zz
    set_["_source"] = src
    return out(status, "numbered", set_=set_, replaced=street if pop == "name_only" else None)


def _mailing_of(raw) -> str | None:
    if not isinstance(raw, dict):
        return None
    om = raw.get("owner_mailing")
    if isinstance(om, dict) and om.get("mailing"):
        return om["mailing"]
    if isinstance(om, str) and om.strip():
        return om
    g = raw.get("gis")
    if isinstance(g, dict) and g.get("mailing"):
        return g["mailing"]
    return None


def _lookup(county, state, parcel_id):
    """(cache_exists, hit, tier, overlay) for one lead."""
    from foreclosure_scraper import parcel_cache as pc
    c = norm_county(county)
    try:
        exists = pc._db_path(c, state).exists()
    except ValueError:
        exists = False
    hit, tier = (None, None)
    if exists:
        try:
            hit, tier = pc.lookup_with_tier(c, parcel_id, state)
        except Exception:  # noqa: BLE001
            hit, tier = None, None
    ov = None
    try:
        ov = overlay_lookup(c, state, parcel_id)
    except Exception:  # noqa: BLE001
        ov = None
    if hit is None and tier:
        hit = {}                      # the cache HAS the parcel but holds no fields for it (Horry, Spartanburg)
    return exists, hit, tier, ov


def plan_row(row: dict) -> dict:
    """plan_fill for a board dict row (dry run) with the live lookups."""
    state = str(row.get("state") or "").upper()
    county = norm_county(row.get("county"))
    street = _clean(row.get("street_address"))
    if street and has_house_number(street):
        return plan_fill(state=state, county=county, listing_type=row.get("listing_type"),
                         parcel_id=row.get("parcel_id"), street=street, city=row.get("city"),
                         zip_code=row.get("zip_code"), mailing=None, hit=None, tier=None)
    exists, hit, tier, ov = (True, None, None, None)
    pid = str(row.get("parcel_id") or "").strip()
    if pid and county_in_state(county, state) and lt_str(row.get("listing_type")) != "tax_sale_overage":
        exists, hit, tier, ov = _lookup(county, state, pid)
    p = plan_fill(state=state, county=county, listing_type=row.get("listing_type"), parcel_id=pid,
                  street=street, city=row.get("city"), zip_code=row.get("zip_code"),
                  mailing=_mailing_of(row.get("raw")), hit=hit, tier=tier, cache_exists=exists,
                  overlay=ov)
    p["tier"] = tier
    p["cache_address"] = (hit or {}).get("address")
    return p


# --------------------------------------------------------------------------------------- dry run
_SUBPARCEL_TAIL = re.compile(r"[.\-\s]\w{1,4}$")


def _parent_probe(row) -> bool:
    """INFORMATION ONLY, never applied: would the PARENT parcel (last delimited segment dropped) have a
    numbered address? A sub-parcel's parent can be a different lot with a different owner and situs, so
    lookup() does not do this by default."""
    from foreclosure_scraper import parcel_cache as pc
    pid = str(row.get("parcel_id") or "").strip()
    parent = _SUBPARCEL_TAIL.sub("", pid)
    if parent == pid or len(pc._norm_id(parent)) < 9:
        return False
    try:
        hit = pc.lookup(norm_county(row.get("county")), parent, str(row.get("state") or "").upper())
    except Exception:  # noqa: BLE001
        return False
    return bool(hit and classify_situs(hit.get("address"))["kind"] == "numbered")


def _dry_run(rows_file=None) -> int:
    from foreclosure_scraper import parcel_cache as pc
    per: dict = defaultdict(Counter)
    by_source: dict = defaultdict(Counter)
    total = Counter()
    samples: dict = defaultdict(list)
    junk_join = Counter()          # what the un-gated join script would have written
    n = 0
    for r in iter_rows(rows_file):
        n += 1
        p = plan_row(r)
        if p["pop"] is None:
            continue
        key = (str(r.get("state") or ""), norm_county(r.get("county")) or "(none)")
        st, pop = p["status"], p["pop"]
        total[(pop, st)] += 1
        if pop == "gap" and st == "skip_no_parcel":
            by_source[str(r.get("source") or "").split(".")[-1]][st] += 1
            continue                  # nothing to join on: reported in OUTCOME, not in the per-county table
        if pop == "gap":
            c = per[key]
            c["gap_rows"] += 1
            if st == "no_cache":
                c["no_cache"] += 1
            if st not in ("no_cache", "skip_no_parcel", "skip_county_not_in_state", "skip_tax_sale_overage"):
                c["cache"] += 1
            if p.get("tier") == "exact":
                c["hit_now"] += 1
            if p.get("tier"):
                c["hit_after"] += 1
            if st == "filled":
                c["filled"] += 1
                if "city" in p["set"]:
                    c["city"] += 1
                if "zip_code" in p["set"]:
                    c["zip"] += 1
            elif st == "road_only":
                c["road_only"] += 1
            elif st == "hit_legal_or_junk":
                c["legal_junk"] += 1
            elif st == "hit_no_address":
                c["hit_no_addr"] += 1
            elif st == "miss":
                c["miss"] += 1
                probe = _parent_probe(r)
                if probe:
                    c["parent_probe"] += 1
            by_source[str(r.get("source") or "").split(".")[-1]][st] += 1
            if st == "filled" and len(samples[key]) < 2:
                samples[key].append((r.get("parcel_id"), p["set"].get("street_address"), p["set"].get("_source")))
        # what the join script's blind copy would have written for this lead
        if pop == "gap" and p.get("cache_address") and p["status"] in ("hit_legal_or_junk", "road_only"):
            from foreclosure_scraper.web_artifact import _is_valid_street_address
            if _is_valid_street_address(p["cache_address"]):
                junk_join["cache text the ungated join would publish as a street address (passes _is_valid_street_address)"] += 1
    print(f"board rows scanned: {n:,}")
    hdr = f"{'state':5}{'county':16}{'gap':>7}{'nocache':>8}{'hit_now':>8}{'hit_new':>8}{'fill':>7}{'city':>6}{'zip':>6}{'road':>6}{'legal':>7}{'noaddr':>7}{'miss':>6}"
    print("\nPER COUNTY: leads with a parcel_id and no street address (hit_now = exact id form, hit_new = after the tolerance)")
    print(hdr)
    tot = Counter()
    for (st, co), c in sorted(per.items(), key=lambda kv: -kv[1]["gap_rows"]):
        if c["gap_rows"] < 1:
            continue
        print(f"{st:5}{co[:15]:16}{c['gap_rows']:>7,}{c['no_cache']:>8,}{c['hit_now']:>8,}{c['hit_after']:>8,}"
              f"{c['filled']:>7,}{c['city']:>6,}{c['zip']:>6,}{c['road_only']:>6,}{c['legal_junk']:>7,}"
              f"{c['hit_no_addr']:>7,}{c['miss']:>6,}")
        tot.update(c)
    print(f"{'':5}{'TOTAL':16}{tot['gap_rows']:>7,}{tot['no_cache']:>8,}{tot['hit_now']:>8,}{tot['hit_after']:>8,}"
          f"{tot['filled']:>7,}{tot['city']:>6,}{tot['zip']:>6,}{tot['road_only']:>6,}{tot['legal_junk']:>7,}"
          f"{tot['hit_no_addr']:>7,}{tot['miss']:>6,}")
    print(f"\nINFORMATION ONLY (not applied): {tot['parent_probe']:,} of the {tot['miss']:,} cache misses are sub-parcels "
          f"whose PARENT parcel has a numbered address")
    print_counter(Counter({f"{a}:{b}": v for (a, b), v in total.items()}), "\nOUTCOME BY POPULATION")
    print("\nBY SOURCE (gap population)")
    for src, c in sorted(by_source.items(), key=lambda kv: -sum(kv[1].values()))[:14]:
        print(f"  {src[:34]:34} " + ", ".join(f"{k}={v:,}" for k, v in c.most_common()))
    print_counter(junk_join, "\nJOIN-SCRIPT HAZARD")
    print("\nSAMPLES (parcel, address, source)")
    for k, v in list(samples.items())[:12]:
        print("  ", k, v)
    print("\nDRY RUN, nothing written. Re-run with --apply (as the only board process).")
    return 0


# ----------------------------------------------------------------------------------------- apply
REQUIRED_RAW_KEYS = ["situs_address_source", "situs_road_only"]
BACKUP_NAME = "fill_address_from_parcel_replaced_street"


def apply_rows(rows: list, *, dry_run: bool = False) -> dict:
    """Fill / upgrade street_address (and city, zip) on Listing objects, in place. Never changes len(rows),
    never writes a file. With dry_run=True nothing is mutated and the same counts are returned.
    The result is a counter dict; when a street-name-only address is replaced its old value is returned under
    '_backup' for the caller to write (run_apply / apply_board_fixes pop it before printing)."""
    from _dq_common import assert_raw_keep
    if not dry_run:
        assert_raw_keep(REQUIRED_RAW_KEYS)
    n = len(rows)
    c: Counter = Counter()
    backup: dict = {}
    for i, li in enumerate(rows):
        state = str(li.state or "").upper()
        county = norm_county(li.county)
        street = _clean(li.street_address)
        if street and has_house_number(street):
            continue
        pid = str(li.parcel_id or "").strip()
        exists, hit, tier, ov = (True, None, None, None)
        if pid and county_in_state(county, state) and lt_str(li.listing_type) != "tax_sale_overage":
            exists, hit, tier, ov = _lookup(county, state, pid)
        p = plan_fill(state=state, county=county, listing_type=li.listing_type, parcel_id=pid,
                      street=street, city=li.city, zip_code=li.zip_code,
                      mailing=_mailing_of(li.raw), hit=hit, tier=tier, cache_exists=exists, overlay=ov)
        c[p["status"]] += 1
        s = p["set"]
        if p["status"] in ("filled", "upgraded"):
            c["city filled"] += "city" in s
            c["zip filled"] += "zip_code" in s
        if dry_run:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        if p["road_only"] and not li.raw.get("situs_road_only"):
            li.raw["situs_road_only"] = p["road_only"]
        if p["status"] not in ("filled", "upgraded"):
            continue
        if p["status"] == "upgraded":
            backup[str(i)] = {"source": li.source, "source_url": li.source_url, "parcel_id": pid,
                              "street_address": li.street_address}
            # keep the replaced street-name-only text as road context, not lost
            li.raw.setdefault("situs_road_only", {"road": p["replaced_street"], "reason": "replaced_by_numbered_situs",
                                                  "note": "street name from the original source; the numbered situs replaced it"})
        li.street_address = s["street_address"]
        if s.get("city") and not _clean(li.city):
            li.city = s["city"]
        if s.get("zip_code") and not _clean(li.zip_code):
            li.zip_code = s["zip_code"]
        li.raw["situs_address_source"] = s["_source"]
    assert len(rows) == n, "a fill must never change the row count"
    out = {k: v for k, v in c.items() if v}
    if backup:
        out["_backup"] = backup
    return out


def _apply() -> int:
    from _dq_common import run_apply
    return run_apply("fill_address_from_parcel", apply_rows, REQUIRED_RAW_KEYS, BACKUP_NAME)


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
