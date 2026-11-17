#!/usr/bin/env python3
"""Chesterfield County, SC parcel detail from the live chesterfieldsc.wthgis.com "tgis"
viewer -- closes 4 gap_matrix "no source known" cells in ONE pass: assessed_value,
lot_size (the board's `acreage` field), atty_deed_ref, atty_legal_description
(round-17-misc small-columns survey, 2026-11-17).

WHY THIS EXISTS. gap_matrix's 2026-11-16 gap list flags Chesterfield SC "no source
known" for all 4 of assessed_value (1,034 rows), lot_size (1,034), atty_deed_ref
(1,034) and atty_legal_description (1,034), each with source blank or "county GIS:
chesterfieldsc.wthgis.com". parcel_cache.py's own 2026-10-20 research note already
says this county's WTH "tgis" viewer has "no REST" in the ArcGIS FeatureServer
sense -- true, re-confirmed live tonight (/arcgis/rest/services and
/server/rest/services both 404). But exactly the same legacy ASP.NET escape hatch
scripts/ingest_williamsburg_wthgis_parcels.py already found and uses for
Williamsburg (a DIFFERENT county on the SAME WTH platform) is ALSO live on
Chesterfield's own subdomain, with its own dataset id (DSID=6796, read straight off
the viewer's own "Parcel Tools Menu" JS -- `fetchOverlay('tgis/custom.aspx?
DSID=6796&RequestType=CustomSearchForm&FormType=BasicParcels')`):

  tgis/custom.aspx?DSID=6796&RequestType=CustomSearchRequest&SearchType=Name
      &SearchCriteria=<lastname>|   -- substring owner-name search, one
      `showf(6796, <FeatureID>)...mainResultItem'>NNN NNN NNN NNN</div>` hit per
      matching parcel (same shape _parse_search in the Williamsburg script already
      parses, DSID is the only thing that differs).

  tgis/getftr.aspx?D=6796&F=<FeatureID>&Z=1 -- the single-parcel detail call. LIVE-
  CONFIRMED tonight (FeatureID 85, Map Number "001 000 000 068", owner "Smith Kim
  Blakeney Etal"): MarketValueTotalValue=102800.00, MarketValueLandValue=6000.00,
  MarketValueBuildingsValue=96800.00, TaxValueTotalValue=83300.00, Deed&nbsp;Book=
  514, Deed&nbsp;Page=1124, Legal&nbsp;Description="1.00 Acre Lot" -- i.e. this one
  county's detail page carries the EXACT Williamsburg schema (MarketValueTotalValue/
  MarketValueAcres/TaxValueTotalValue -- the three `_field()` already knows how to
  read) PLUS a clean Deed Book/Page pair and a Legal Description string neither
  Williamsburg's own deployment exposes. MarketValueAcres read 0.00 on this same
  sample despite a real "1.00 Acre Lot" legal description -- that field is NOT
  reliably populated here, so lot_size fill-only-skips zero exactly like every
  other 0/None value this codebase already treats as "no new data" (no special
  case needed, see build_patches()).

Chesterfield's board parcel_id IS the bare WTH Map Number already (qpaybill-sourced,
space-separated 4-group form, e.g. "176 000 000 011") -- confirmed live against
727 of this county's 1,034 real board rows tonight (iter_board_rows, never
load_board()). A sub-account suffix appears as a 5th space-separated group on 'bout
15% of rows ("102 000 000 071 001") the same way Williamsburg's qpaybill ids carry
a dotted suffix the GIS Map Number never has -- _base_mapno() below strips it the
same way.

MARION SC WAS ALSO LIVE-TESTED tonight (DSID=1064, its own getftr.aspx confirmed
real Land&nbsp;Value/Building&nbsp;Value/Total&nbsp;cres [sic -- the label itself
reads "cres", not "Acres", a genuine typo baked into that county's own template]
fields) but is NOT attempted here: 0 of its 280 board rows carry a parcel_id at
all (iter_board_rows, confirmed live), so a WTH hit could only be bound to a board
row by owner name alone -- multiple real people share a surname, and a wrong bind
would write a stranger's deed/value onto this row, which is worse than leaving the
cell empty. Left as a found-but-not-safely-bindable lead, not built.

BOARD I/O: one streaming read-only pass (board_stream.iter_board_rows()) to build
the Chesterfield candidate set and its existing values; board_lock() wraps ONLY the
final patch_existing_rows() write (same discipline backfill_fl_co_deed_ref.py and
backfill_orangeburg_assessed_value.py already use) -- never load_board().

POLITENESS: no login/CAPTCHA on this legacy per-county ASP.NET box (open HTTP,
live-confirmed), but it is a small county-run server, not a CDN -- CONCURRENCY=4,
20s timeout, 3 retries, matching the Williamsburg script's own already-proven pace.

    .venv/bin/python3 -I scripts/ingest_chesterfield_wthgis.py --limit 50   # canary
    .venv/bin/python3 -I scripts/ingest_chesterfield_wthgis.py              # dry run, full county
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python3 -I scripts/ingest_chesterfield_wthgis.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
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
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, board_lock, board_patch_size_state, patch_existing_rows,
)

STATE, COUNTY = "SC", "Chesterfield"
BASE = "https://chesterfieldsc.wthgis.com/tgis/"
DSID = 6796
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) HighWayResearch/1.0 (+parcel-cache build)"
CONCURRENCY = 4
TIMEOUT_S = 20.0
RETRIES = 3

#: parcel_cache._COLS field -> this county's getftr.aspx label (same shape the
#: Williamsburg script's WILLIAMSBURG_MAP already uses; _map_val() is a pure
#: function, no PARCEL_LAYERS registration needed to reuse it).
CHESTERFIELD_MAP = {
    "owner": "Owner&nbsp;Name",
    "address": "Property&nbsp;Address1",
    "owner_mailing": ["Mailing&nbsp;Address1", "Mailing&nbsp;Address2", "Mailing&nbsp;City",
                       "Mailing&nbsp;State", "Mailing&nbsp;ZipCode"],
    "market_value": "MarketValueTotalValue",
    "tax_value": "TaxValueTotalValue",
    "acreage": "MarketValueAcres",
    "improvement_value": "MarketValueBuildingsValue",
}
_DEED_BOOK, _DEED_PAGE, _LEGAL = "Deed&nbsp;Book", "Deed&nbsp;Page", "Legal&nbsp;Description"

_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                  "case_number", "source_url", "listing_type", "source",
                  "owner_name", "defendant", "raw", "assessed_value", "acreage",
                  "legal_description")

_FIELD_RE_CACHE: dict[str, re.Pattern] = {}


def _field(txt: str, name: str) -> str:
    pat = _FIELD_RE_CACHE.get(name)
    if pat is None:
        pat = _FIELD_RE_CACHE[name] = re.compile(re.escape(name) + r"</th><td[^>]*>([^<]*)</td>")
    m = pat.search(txt)
    return m.group(1).strip() if m else ""


#: Chesterfield's bare Map Number is 4 space-separated 3-digit groups; a qpaybill
#: sub-account rides as an extra 5th group the WTH search index never has.
_BASE_MAPNO_RE = re.compile(r"^(\d{3} \d{3} \d{3} \d{3})(?:\s+\S+)?$")


def _base_mapno(pid: str) -> str:
    m = _BASE_MAPNO_RE.match((pid or "").strip())
    return m.group(1) if m else (pid or "").strip()


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


def _parse_detail(txt: str) -> Optional[dict]:
    mapno = _field(txt, "Map&nbsp;Number")
    if not mapno:
        return None
    rec = {"MapNumber": mapno, "Owner&nbsp;Name": _field(txt, "Owner&nbsp;Name"),
           "Owner&nbsp;Name2": _field(txt, "Owner&nbsp;Name2")}
    for f in ("Mailing&nbsp;Address1", "Mailing&nbsp;Address2", "Mailing&nbsp;City",
              "Mailing&nbsp;State", "Mailing&nbsp;ZipCode", "Property&nbsp;Address1",
              "MarketValueTotalValue", "MarketValueAcres", "TaxValueTotalValue",
              "MarketValueBuildingsValue", _DEED_BOOK, _DEED_PAGE, _LEGAL):
        rec[f] = _field(txt, f)
    return rec


def _board_rows() -> list[dict]:
    out = []
    for rec in iter_board_rows(REPO / "docs" / "listings.json.gz"):
        if (rec.get("county") or "").strip().lower() == COUNTY.lower() and \
           (rec.get("state") or "").strip().upper() == STATE:
            out.append(rec)
    return out


def _book_page_ok(book: str, page: str) -> bool:
    return bool(book) and bool(page) and book not in ("0", "0.00") and page not in ("0", "0.00")


async def _run(limit: Optional[int]) -> dict:
    rows = _board_rows()
    if limit:
        rows = rows[:limit]
    print(f"board rows ({COUNTY}, {STATE}): {len(rows):,}")

    surnames = sorted({_surname(r.get("defendant") or "") for r in rows} - {""})
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
            fid = mapid_to_fid.get(pid) or mapid_to_fid.get(_base_mapno(pid))
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

    pid_to_rec: dict[str, dict] = {}
    for fid, pids in needed_fids.items():
        rec = fid_to_rec.get(fid)
        if rec:
            for pid in pids:
                pid_to_rec[pid] = rec

    return {"board_rows": len(rows), "rows": rows, "pid_to_rec": pid_to_rec,
            "records": [(fid_to_rec[fid], pids) for fid, pids in needed_fids.items()
                        if fid in fid_to_rec]}


def _write_cache(records: list[tuple[dict, list[str]]]) -> Path:
    parcel_cache.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    db_path = parcel_cache._db_path(COUNTY, STATE)  # noqa: SLF001
    tmp = db_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.execute(parcel_cache.PARCELS_DDL)
    rows_out = []
    for rec, board_pids in records:
        keys = set(parcel_cache._id_variants(rec["MapNumber"]))  # noqa: SLF001
        for pid in board_pids:
            keys |= parcel_cache._id_variants(pid)  # noqa: SLF001
        if not keys:
            continue
        vals = tuple(parcel_cache._map_val(rec, c, CHESTERFIELD_MAP.get(c))  # noqa: SLF001
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


def _num(s: str) -> Optional[float]:
    try:
        v = float(str(s).strip())
    except (TypeError, ValueError):
        return None
    return v if v != 0 else None


def build_patches(rows: list[dict], pid_to_rec: dict[str, dict]) -> tuple[dict[str, dict], dict]:
    """Fill-only patches: never overwrite a value the board already has."""
    patches: dict[str, dict] = {}
    stats = {"no_pid": 0, "no_match": 0, "no_key": 0, "no_new_data": 0}
    now_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    for r in rows:
        pid = (r.get("parcel_id") or "").strip()
        if not pid:
            stats["no_pid"] += 1
            continue
        rec = pid_to_rec.get(pid)
        if not rec:
            stats["no_match"] += 1
            continue
        try:
            li = Listing.model_construct(**{f: r.get(f) for f in _LIGHT_FIELDS})
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            stats["no_key"] += 1
            continue

        patch: dict = {}
        mv = _num(rec.get("MarketValueTotalValue"))
        if mv and not (r.get("assessed_value") or 0):
            patch["assessed_value"] = mv
        ac = _num(rec.get("MarketValueAcres"))
        if ac and not (r.get("acreage") or 0):
            patch["acreage"] = ac
        legal = (rec.get(_LEGAL) or "").strip()
        if legal and not (r.get("legal_description") or "").strip():
            patch["legal_description"] = legal
        book, page = (rec.get(_DEED_BOOK) or "").strip(), (rec.get(_DEED_PAGE) or "").strip()
        existing_cdr = (r.get("raw") or {}).get("county_deed_ref") if isinstance(r.get("raw"), dict) else None
        existing_book_page = isinstance(existing_cdr, dict) and existing_cdr.get("book") and existing_cdr.get("page")
        if _book_page_ok(book, page) and not existing_book_page:
            patch["raw"] = {"county_deed_ref": {
                "source": "chesterfield_wthgis", "parno": rec.get("MapNumber"),
                "book": book, "page": page, "date": None, "fetched_at": now_iso,
            }}
        if patch:
            patches[key] = patch
        else:
            stats["no_new_data"] += 1
    return patches, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap board rows (canary run)")
    ap.add_argument("--no-cache-write", action="store_true", help="skip the parcel_cache sqlite write")
    ap.add_argument("--apply", action="store_true", help="write patches via patch_existing_rows() (default: dry run)")
    args = ap.parse_args()

    result = asyncio.run(_run(args.limit))
    records, rows, pid_to_rec = result["records"], result["rows"], result["pid_to_rec"]

    if records and not args.no_cache_write:
        db_path = _write_cache(records)
        print(f"parcel_cache: wrote {len(records):,} records -> {db_path} "
              f"({db_path.stat().st_size/1e3:.0f} KB)")
    elif not records:
        print("no detail records fetched -- cache NOT written")

    patches, stats = build_patches(rows, pid_to_rec)
    print(f"\nboard patch candidates: {len(patches):,}  (stats: {stats})")

    if not patches:
        print("nothing to patch.")
        return 0
    if not args.apply:
        print("DRY RUN -- nothing written. Pass --apply to write for real.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, p)
        return 0

    docs_dir = REPO / "docs"
    size_state = board_patch_size_state(docs_dir)
    if not size_state["ok"] and os.environ.get("BOARD_PATCH_ALLOW_LARGE") != "1":
        print(f"REFUSING: {size_state['reason']}. Set BOARD_PATCH_ALLOW_LARGE=1 to override.")
        return 1

    try:
        with board_lock(REPO, owner="ingest_chesterfield_wthgis", wait=3600, poll=10):
            pstats = patch_existing_rows(
                patches, {"ingest_chesterfield_wthgis": len(patches)}, docs_dir=docs_dir)
    except BoardLockBusy as exc:
        print(f"{exc} -- refusing to write ({len(patches):,} patches lost; re-run to redo).")
        return 1
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
