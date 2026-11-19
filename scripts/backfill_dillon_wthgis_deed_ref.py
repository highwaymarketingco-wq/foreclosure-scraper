#!/usr/bin/env python3
"""Dillon County, SC Deed Book/Page from the live dillonsc.wthgis.com "tgis" viewer --
closes gap_matrix's atty_deed_ref gap for Dillon (round 56, 2026-11-19), the SAME
getftr.aspx fetch scripts/backfill_dillon_wthgis_vacant_lot.py (round 54) already proved
live for this county, extended to also lift Deed Book/Page into raw['county_deed_ref'] --
exactly the follow-up that script's own docstring flagged and declined to do itself
("a future round can lift Deed Book/Page into raw['county_deed_ref'] the same way
backfill_marlboro_wthgis_deed_ref.py already does, once this cache is in place").

WHY A SEPARATE SCRIPT, NOT AN EDIT TO THE VACANT_LOT ONE. parcel_cache._COLS (the
generic schema both scripts' sqlite cache uses) has no deed_book/deed_page column at
all -- confirmed by reading _COLS, same fact backfill_marlboro_wthgis_deed_ref.py's own
docstring already established for this WTH platform family. Deed Book/Page can only
ever reach the board via a DIRECT raw['county_deed_ref'] patch (Marlboro's proven
shape), never through the cache-join path enrich_gis_attrs() already runs for
vacant_lot's market_value/improvement_value. The underlying HTTP data (Map Number ->
FeatureID search, then getftr.aspx detail) is identical to the vacant_lot script's own
first two phases; this script re-fetches it (the detail dict was never persisted --
DILLON_MAP has no deed_book/deed_page key, so nothing to read back from dillon.sqlite)
and does the Marlboro-style direct board patch instead of (additionally to) a cache
write. It does NOT touch data/parcel_cache/dillon.sqlite at all.

LIVE-CONFIRMED FIELDS (backfill_dillon_wthgis_vacant_lot.py's own 2026-11-19 full-field
dump, re-used here, not re-verified independently): Deed&nbsp;Book, Deed&nbsp;Page and a
SINGLE Legal&nbsp;Description field (Dillon's template does NOT split it into 1/2 the
way Marlboro's does) are present. UNLIKE Marlboro, this template carries no Sale&nbsp;
Date/Sale&nbsp;Price field at all (confirmed: Dillon's full-field dump lists none, and
DILLON_MAP maps no sale_price/sale_date target either) -- so the deed_ref patch below
always writes date=None; lawyer_lane.county_deed_ref() tolerates a missing date fine
(book+page is what deed_ref_present() checks), it only loses bind_chain()'s date-match
signal, same gap Marlboro's docstring describes as a separate, unblocked-by-this-script
concern.

SCOPE. This round's gap_matrix (2026-11-19) shows SC/Dillon atty_deed_ref at 1/1,536 =
0.07% (built-but-low-yield, est_rows_affected 1,535) -- the live index
(dillonsc.avenuinsights.com, a JS-rendered Register-of-Deeds SPA) is separately DECLINED
for this county's liens/atty_rod_lien_checked columns, but deed_ref comes from the
PARCEL record (getftr.aspx) via the assessor's own GIS viewer, an entirely different,
unblocked source -- not affected by that decline. assessed_value/acreage are LEFT ALONE
here (DILLON_MAP already maps them into dillon.sqlite; the next enrich_gis_attrs()
cache-join pass fills them with no further action needed) -- this script patches ONLY
raw['county_deed_ref'], the one out-of-schema field the cache mechanism structurally
cannot carry. (Dillon's own Legal&nbsp;Description field was checked too, live, during
this round's canary -- its values read like bare street locations, not metes-and-bounds
text, e.g. "601 S Macarthur Avenue", "S Side Coreys Court Lot # 28" -- and gap_matrix
tracks no legal_description column for SC at all, so it is deliberately left out of
this patch rather than carried as an unverified, uncounted bonus.)

BOARD I/O: one streaming read-only pass (board_stream.iter_board_rows()) to build the
Dillon candidate set; board_lock() wraps ONLY the final patch_existing_rows() write.
Never load_board().

POLITENESS: same small county-run ASP.NET box, same proven pace -- CONCURRENCY=4, 20s
timeout, 3 retries.

    .venv/bin/python3 -I scripts/backfill_dillon_wthgis_deed_ref.py --limit 50   # canary
    .venv/bin/python3 -I scripts/backfill_dillon_wthgis_deed_ref.py              # dry run, full county
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python3 -I scripts/backfill_dillon_wthgis_deed_ref.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import httpx  # noqa: E402

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, board_lock, board_patch_size_state, patch_existing_rows,
)

STATE, COUNTY = "SC", "Dillon"
BASE = "https://dillonsc.wthgis.com/tgis/"
DSID = 1042
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) HighWayResearch/1.0 (+parcel-cache build)"
CONCURRENCY = 4
TIMEOUT_S = 20.0
RETRIES = 3

_DEED_BOOK, _DEED_PAGE = "Deed&nbsp;Book", "Deed&nbsp;Page"

_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                  "case_number", "source_url", "listing_type", "source",
                  "owner_name", "defendant", "raw")

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


def _parse_detail(txt: str) -> Optional[dict]:
    mapno = _field(txt, "Map&nbsp;Number")
    if not mapno:
        return None
    return {
        "MapNumber": mapno,
        _DEED_BOOK: _field(txt, _DEED_BOOK),
        _DEED_PAGE: _field(txt, _DEED_PAGE),
    }


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

    pid_to_rec: dict[str, dict] = {}
    for fid, pids in needed_fids.items():
        rec = fid_to_rec.get(fid)
        if rec:
            for pid in pids:
                pid_to_rec[pid] = rec

    return {"board_rows": len(rows), "rows": rows, "pid_to_rec": pid_to_rec}


def build_patches(rows: list[dict], pid_to_rec: dict[str, dict]) -> tuple[dict[str, dict], dict]:
    """Fill-only patches: never overwrite a value the board already has."""
    patches: dict[str, dict] = {}
    stats = {"no_pid": 0, "no_match": 0, "no_key": 0, "no_new_data": 0, "deed_ref_gained": 0}
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
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
        book, page = (rec.get(_DEED_BOOK) or "").strip(), (rec.get(_DEED_PAGE) or "").strip()
        existing_cdr = (r.get("raw") or {}).get("county_deed_ref") if isinstance(r.get("raw"), dict) else None
        existing_book_page = isinstance(existing_cdr, dict) and existing_cdr.get("book") and existing_cdr.get("page")
        if _book_page_ok(book, page) and not existing_book_page:
            patch["raw"] = {"county_deed_ref": {
                "source": "dillon_wthgis", "parno": rec.get("MapNumber"),
                "book": book, "page": page, "date": None, "fetched_at": now_iso,
            }}
            stats["deed_ref_gained"] += 1
        if patch:
            patches[key] = patch
        else:
            stats["no_new_data"] += 1
    return patches, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap board rows (canary run)")
    ap.add_argument("--apply", action="store_true", help="write patches via patch_existing_rows() (default: dry run)")
    args = ap.parse_args()

    result = asyncio.run(_run(args.limit))
    rows, pid_to_rec = result["rows"], result["pid_to_rec"]

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
        with board_lock(REPO, owner="backfill_dillon_wthgis_deed_ref", wait=3600, poll=10):
            pstats = patch_existing_rows(
                patches, {"backfill_dillon_wthgis_deed_ref": len(patches)}, docs_dir=docs_dir)
    except BoardLockBusy as exc:
        print(f"{exc} -- refusing to write ({len(patches):,} patches lost; re-run to redo).")
        return 1
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
