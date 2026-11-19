#!/usr/bin/env python3
"""McCormick County, SC parcel detail from the live mccormicksc.wthgis.com "tgis"
viewer -- closes gap_matrix's vacant_lot "no source known" bucket for McCormick
(round 58, 2026-11-19), same shape as scripts/backfill_dillon_wthgis_vacant_lot.py
(round 54) one round later on the same WTH platform family.

WHY THIS EXISTS. McCormick carries NO parcel_cache entry of any kind before this
script (confirmed: grep of parcel_cache.py's PARCEL_LAYERS, no "McCormick" key; no
data/parcel_cache/mccormick.sqlite file on disk before this script). Without a
cache entry, enrichment_vacant_landuse.py's improvement-value fallback (the same
mechanism already wired for Williamsburg/Chesterfield/Sumter/Barnwell/Dillon --
"zero improvement_value + real market_value = vacant lot", no land_use field
required) can never fire for McCormick because there is nothing in parcel_cache to
read. The fix is a cache-population script, same shape as backfill_dillon_wthgis_
vacant_lot.py: fetch per-parcel via the DSID endpoint, write to a generic
parcel_cache SQLite file -- NOT a custom_html/PARCEL_LAYERS entry, NOT a direct
board patch -- so the ALREADY-EXISTING enrich_gis_attrs() local-cache-join pass
(next scheduled run) and enrichment_vacant_landuse.py (next scheduled run) do the
actual board fill + vacant_lot stamp automatically, same as they already do for
every other WTH-sourced county. This script's own job ends at a correct, verified
cache file.

DSID. McCormick's DSID=46 is NOT newly discovered this round -- it was already
live-verified and in production use by src/foreclosure_scraper/scrapers/
counties_sc/sc_wthgis_heir_estate.py since round 19 (2026-11-17), read straight off
mccormicksc.wthgis.com's own root-page JS (addMenuItem/g_hoverDss, same two-method
cross-check Dillon's own docstring describes). RE-CONFIRMED LIVE tonight
(2026-11-19) by a direct probe of mccormicksc.wthgis.com/tgis/ with DSID=46: every
sample detail page's Mailing City/State reads "Mc Cormick, SC" (zip 29835) --
genuinely this county's own data, not another county's borrowed dsid (the
established platform-wide pitfall: a WTH dsid is NOT tenant-scoped at the HTTP
layer, so this is checked fresh per county rather than assumed).

LIVE-VERIFIED 2026-11-19 (read-only GETs, same UA/politeness as every sibling WTH
script). McCormick's getftr.aspx schema is FIELD-FOR-FIELD IDENTICAL to Dillon's
(both match the Chesterfield-family camelCase MarketValue*/TaxValue* convention,
including the same Buildings/Land/Lots split Dillon's own docstring found richer
than sc_wthgis_heir_estate.py's shared _DEFAULT_FIELDS needed) -- confirmed by a
live side-by-side field-name diff against a real McCormick detail page (FeatureID
159, Map Number 025-00-00-011.): Map Number, Owner Name/2, Mailing Address1/2/City/
State/ZipCode, Property Address1/2/City/State/ZipCode, Legal Description, Deed
Book/Page, Plat Book/Page, District, Fire Code, and the full MarketValue*/
TaxValue* family (Acres/Buildings/BuildingsAssessed/BuildingsValue/LandAssessed/
LandValue/Lots/TotalAssessed/TotalValue). The two fields this project's vacant_lot
detection needs are present and REAL (not placeholder zeros), same mapping as
Dillon:
  - market_value       -> MarketValueTotalValue
  - improvement_value  -> MarketValueBuildingsValue
A 2-row SMITH-surname sample found MarketValueBuildingsValue genuinely VARIES in
exactly the needed shape: FeatureID 159 (map 025-00-00-011.) = 5400.00 (improved,
MarketValueTotalValue 8400.00) vs. FeatureID 160 (map 025-00-00-010., the adjacent
parcel, same owner) = 0.00 (MarketValueBuildingsValue) while MarketValueTotalValue
still reads a real 2500.00 -- the identical "zero improvement, real market value"
shape already proven and board-wired for Williamsburg/Chesterfield/Sumter/Barnwell/
Dillon on this exact same enrichment path. NO land_use/property-class/land-class
field of any kind exists on this county's template (confirmed: the full field dump
has nothing matching that shape) -- same structural absence as Dillon/Williamsburg/
Sumter/Chesterfield, which the existing enrichment_vacant_landuse.py fallback
already handles as a flat, county-wide improvement-value-only rule.

BOARD OPPORTUNITY (live-measured 2026-11-19, board_stream read-only scan): 527
McCormick, SC board rows total, 416 (79%) already carry a parcel_id (mostly
tax_sale/estate_lead/distressed rows whose own parcel_id already reads in the
SAME "NNN-NN-NN-NNN." dashed TMS format as McCormick's own Map Number field --
sample board parcel_id "112-08-02-011." vs. this source's own "025-00-00-011.",
same shape byte-for-byte) -- a genuinely strong target, unlike Marion SC (same
round's other candidate, same platform, but only 7/287 board rows carry ANY
parcel_id at all, and all 7 of those already came from the one producer that
populates them -- see this round's handoff notes; not attempted here, no adapter
built, a real yield ceiling rather than a platform wall).

Deed Book/Page and Legal Description are ALSO present on this template (same free
fetch, Dillon's own "bonus" note applies here too) but deliberately NOT patched
into the board by this script -- scoped to vacant_lot's two required fields only,
same as Dillon.

BOARD I/O: one streaming read-only pass (board_stream.iter_board_rows()) to build
the McCormick candidate set and its existing values -- never load_board(). This
script writes ONLY a new, standalone parcel_cache SQLite file
(data/parcel_cache/mccormick.sqlite); it does NOT touch docs/listings.json.gz at
all, so board_lock()/patch_existing_rows() are not used here.

MATCH METHOD (same as Dillon/Marlboro): WTH's name index is a plain substring
match, not prefix-only. Search by every distinct board-row surname, collect Map
Number -> FeatureID from the results, then keep ONLY the FeatureIDs whose Map
Number exactly equals a McCormick board row's own parcel_id (both confirmed to
share the "NNN-NN-NN-NNN[.NN]" dashed TMS format). A by-surname crawl, not a
full-county enumeration -- same known, accepted limitation as Dillon/Marlboro.

POLITENESS: same as every sibling WTH script -- a small county-run legacy ASP.NET
box, not a CDN. CONCURRENCY=4, 20s timeout, 3 retries.

    .venv/bin/python3 -I scripts/backfill_mccormick_wthgis_vacant_lot.py --limit 50   # canary
    .venv/bin/python3 -I scripts/backfill_mccormick_wthgis_vacant_lot.py              # dry run, full county
    .venv/bin/python3 -I scripts/backfill_mccormick_wthgis_vacant_lot.py --apply      # write the cache file for real
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import httpx  # noqa: E402

from foreclosure_scraper import parcel_cache  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402

STATE, COUNTY = "SC", "McCormick"
BASE = "https://mccormicksc.wthgis.com/tgis/"
DSID = 46
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) HighWayResearch/1.0 (+parcel-cache build)"
CONCURRENCY = 4
TIMEOUT_S = 20.0
RETRIES = 3

#: parcel_cache._COLS field -> this county's own getftr.aspx label (live-verified
#: 2026-11-19 against a direct full-field dump -- field-for-field identical to
#: Dillon's own DILLON_MAP, same platform family, independently confirmed rather
#: than assumed). No land_use field exists on this template.
MCCORMICK_MAP = {
    "owner": ["Owner&nbsp;Name", "Owner&nbsp;Name2"],
    "address": "Property&nbsp;Address1",
    "owner_mailing": ["Mailing&nbsp;Address1", "Mailing&nbsp;Address2",
                       "Mailing&nbsp;City", "Mailing&nbsp;State", "Mailing&nbsp;ZipCode"],
    "market_value": "MarketValueTotalValue",
    "tax_value": "TaxValueTotalValue",
    "acreage": "MarketValueAcres",
    "improvement_value": "MarketValueBuildingsValue",
    # land_use: no field on this template (confirmed live) -- left unmapped (None).
}

_FIELD_RE_CACHE: dict[str, re.Pattern] = {}


def _field(txt: str, name: str) -> str:
    pat = _FIELD_RE_CACHE.get(name)
    if pat is None:
        pat = _FIELD_RE_CACHE[name] = re.compile(re.escape(name) + r"</th><td[^>]*>([^<]*)</td>")
    m = pat.search(txt)
    return m.group(1).strip() if m else ""


def _surname(defendant: str) -> str:
    s = (defendant or "").strip()
    if not s:
        return ""
    tok = re.split(r"\s+", s)[0]
    return re.sub(r"[^A-Za-z'-]", "", tok).strip()


async def _get(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> Optional[str]:
    async with sem:
        for attempt in range(RETRIES):
            try:
                r = await client.get(url, timeout=TIMEOUT_S)
                if r.status_code == 200:
                    return r.text
            except (httpx.TimeoutException, httpx.TransportError):
                pass
            if attempt < RETRIES - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
        return None


def _parse_search(txt: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in re.finditer(r"showf\(\s*\d+\s*,\s*(\d+)\s*\).*?mainResultItem'>([^<]+)<", txt, re.S):
        fid, mapno = m.group(1), m.group(2).strip()
        if mapno:
            out[mapno] = int(fid)
    return out


#: Every field this script pulls off a detail page -- the MCCORMICK_MAP targets
#: plus Legal Description/Deed Book/Page (fetched for free, NOT patched to the
#: board this round -- see module docstring).
_DETAIL_FIELDS = (
    "Map&nbsp;Number", "Owner&nbsp;Name", "Owner&nbsp;Name2",
    "Mailing&nbsp;Address1", "Mailing&nbsp;Address2", "Mailing&nbsp;City",
    "Mailing&nbsp;State", "Mailing&nbsp;ZipCode", "Property&nbsp;Address1",
    "MarketValueTotalValue", "TaxValueTotalValue", "MarketValueAcres",
    "MarketValueBuildingsValue", "MarketValueLandValue",
    "Legal&nbsp;Description", "Deed&nbsp;Book", "Deed&nbsp;Page",
)


def _parse_detail(txt: str) -> Optional[dict]:
    mapno = _field(txt, "Map&nbsp;Number")
    if not mapno:
        return None
    return {f: _field(txt, f) for f in _DETAIL_FIELDS}


def _board_rows() -> list[dict]:
    out = []
    for rec in iter_board_rows(REPO / "docs" / "listings.json.gz"):
        if (rec.get("county") or "").strip().lower() == COUNTY.lower() and \
           (rec.get("state") or "").strip().upper() == STATE:
            out.append(rec)
    return out


def _num(s: str) -> Optional[float]:
    try:
        v = float(str(s).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if v != 0 else None


async def _run(limit: Optional[int]) -> dict:
    rows = _board_rows()
    if limit:
        rows = rows[:limit]
    print(f"board rows ({COUNTY}, {STATE}): {len(rows):,}")

    surnames = sorted({_surname(r.get("defendant") or r.get("owner_name") or "") for r in rows} - {""})
    print(f"distinct surnames to search: {len(surnames):,}")

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(headers={"User-Agent": UA}) as client:
        t0 = time.time()
        search_urls = [
            BASE + "custom.aspx?DSID=%d&RequestType=CustomSearchRequest&SearchType=Name"
                   "&SearchCriteria=%s%%7C" % (DSID, urllib.parse.quote(s))
            for s in surnames
        ]
        texts = await asyncio.gather(*(_get(client, u, sem) for u in search_urls))
        mapid_to_fid: dict[str, int] = {}
        for txt in texts:
            if txt:
                mapid_to_fid.update(_parse_search(txt))
        print(f"search phase: {len(mapid_to_fid):,} distinct Map Numbers surfaced "
              f"in {time.time()-t0:.0f}s")

        needed_fids: dict[int, list[str]] = {}
        unmatched = no_pid = 0
        for r in rows:
            pid = (r.get("parcel_id") or "").strip()
            if not pid:
                no_pid += 1
                continue
            fid = mapid_to_fid.get(pid)
            if fid is None:
                unmatched += 1
                continue
            needed_fids.setdefault(fid, []).append(pid)
        print(f"board parcel_id -> FeatureID resolved: {len(needed_fids):,} "
              f"(no parcel_id: {no_pid:,}, unmatched: {unmatched:,})")

        t1 = time.time()
        fids = list(needed_fids)
        detail_urls = [BASE + f"getftr.aspx?D={DSID}&F={fid}&Z=1" for fid in fids]
        detail_texts = await asyncio.gather(*(_get(client, u, sem) for u in detail_urls))
        fid_to_rec: dict[int, dict] = {}
        for fid, txt in zip(fids, detail_texts):
            if not txt:
                continue
            rec = _parse_detail(txt)
            if rec:
                fid_to_rec[fid] = rec
        print(f"detail phase: {len(fid_to_rec):,}/{len(needed_fids):,} parcels fetched "
              f"in {time.time()-t1:.0f}s")

    records = [(fid_to_rec[fid], pids) for fid, pids in needed_fids.items() if fid in fid_to_rec]

    # Dry-run-only vacant_lot simulation: what enrichment_vacant_landuse.py's existing
    # improvement-value fallback WOULD stamp once this cache feeds a real
    # enrich_gis_attrs() pass -- "zero improvement, real market value" (same gate
    # already proven for Williamsburg/Chesterfield/Sumter/Barnwell/Dillon). Computed
    # here read-only, for reporting only; this script never stamps vacant_lot itself.
    vacant_sim = improved_sim = no_value_sim = 0
    for rec, _pids in records:
        mv = _num(rec.get("MarketValueTotalValue"))
        iv = _num(rec.get("MarketValueBuildingsValue"))
        bv_field_present = rec.get("MarketValueBuildingsValue") is not None and \
            rec.get("MarketValueBuildingsValue") != ""
        if mv and bv_field_present and iv is None:
            vacant_sim += 1          # real market value, buildings value reads 0
        elif mv and iv:
            improved_sim += 1
        else:
            no_value_sim += 1
    print(f"\nvacant_lot SIMULATION ONLY (not applied; this is what the existing "
          f"enrichment_vacant_landuse.py gate would see once the cache is in place):")
    print(f"  zero-improvement + real market value (would stamp vacant_lot): {vacant_sim:,}")
    print(f"  nonzero improvement (improved, no stamp):                      {improved_sim:,}")
    print(f"  no usable value pair:                                         {no_value_sim:,}")

    return {"board_rows": len(rows), "records": records}


def _write_cache(records: list[tuple[dict, list[str]]]) -> Path:
    """Same shape as backfill_dillon_wthgis_vacant_lot.py's own _write_cache() --
    a generic parcel_cache SQLite keyed the normal way, so enrich_gis_attrs()'s
    already-existing local-cache-join pass picks McCormick up on every future board
    run. No PARCEL_LAYERS registration (this is not an ArcGIS layer)."""
    parcel_cache.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    db_path = parcel_cache._db_path(COUNTY, STATE)  # noqa: SLF001
    tmp = db_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.execute(parcel_cache.PARCELS_DDL)
    rows_out = []
    for rec, board_pids in records:
        keys = set(parcel_cache._id_variants(rec["Map&nbsp;Number"]))  # noqa: SLF001
        for pid in board_pids:
            keys |= parcel_cache._id_variants(pid)  # noqa: SLF001
        if not keys:
            continue
        vals = tuple(parcel_cache._map_val(rec, c, MCCORMICK_MAP.get(c))  # noqa: SLF001
                      for c in parcel_cache._COLS)  # noqa: SLF001
        rows_out.extend((k, *vals) for k in keys)
    con.executemany(
        "INSERT INTO parcels VALUES(" + ",".join("?" * (1 + len(parcel_cache._COLS))) + ")",
        rows_out)
    con.execute("CREATE INDEX idx_id ON parcels(id)")
    con.commit()
    con.close()
    tmp.replace(db_path)
    return db_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap board rows (canary run)")
    ap.add_argument("--apply", action="store_true",
                     help="write the parcel_cache sqlite for real (default: dry run, no file written)")
    args = ap.parse_args()

    result = asyncio.run(_run(args.limit))
    records = result["records"]
    print(f"\nparcel_cache candidate records: {len(records):,}")

    if not records:
        print("nothing to write.")
        return 0
    if not args.apply:
        print("DRY RUN -- no cache file written. Pass --apply to write for real.")
        for rec, pids in records[:5]:
            print("  ", pids, {k: rec.get(k) for k in
                                 ("Map&nbsp;Number", "Owner&nbsp;Name",
                                  "MarketValueTotalValue", "MarketValueBuildingsValue")})
        return 0

    db_path = _write_cache(records)
    print(f"parcel_cache: wrote {len(records):,} records -> {db_path} "
          f"({db_path.stat().st_size/1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
