#!/usr/bin/env python3
"""Marlboro County, SC parcel detail from the live marlborosc.wthgis.com "tgis"
viewer -- closes gap_matrix's atty_deed_ref gap for Marlboro (round 31's own
finding, picked up round 32, 2026-11-18) and, as a bonus from the SAME HTTP
fetch, fills assessed_value/lot_size/legal_description wherever the board lacks
them -- same 4-column shape scripts/ingest_chesterfield_wthgis.py already shipped
for Chesterfield (round 17) on the identical WTH platform.

WHY THIS EXISTS (round 31's own gap_matrix comment, scripts/gap_matrix.py
"atty_deed_ref" Spec(), 2026-11-18): "Marlboro's bind_chain() can never return
'book_page'/'sale_date' -- only 'name_only' -- because this county has no
parcel_cache.py entry at all, so county_deed_ref() never has a parcel-side sale
date/book-page to match against ... Marlboro's bound-hit ceiling is a SEPARATE,
larger gap -- parcel_cache coverage -- out of this round's scope; flagged for a
future round, not declined, since it is not a dead end." Confirmed live
2026-11-18: of 1,488 Marlboro SC board rows, 294 already carry raw['gis'] ==
{"queried": true} (enrichment_gis_attrs.py's own no-op stamp -- it tried a
parcel_cache lookup, found nothing, and gave up) and ZERO carry raw['gis']
['last_sale'] or raw['county_deed_ref'] -- lawyer_lane.county_deed_ref() really
does return {date: None, book: None, page: None} for every single row today.

THE FIX IS NOT "add a PARCEL_LAYERS[...] entry", though. parcel_cache.py's
generic schema (_COLS) has no deed_book/deed_page columns at all -- every
existing ArcGIS-sourced county's "map" only ever feeds owner/address/value/
acreage/sale_price/sale_date into raw["gis"], never book/page (confirmed by
reading the schema and every "map" dict in parcel_cache.py; Williamsburg's own
WTH entry is the same). Deed Book/Page only ever reaches deed_ref_present() via
raw['county_deed_ref'] (a book+page the parcel record itself cites) or
raw['deed_latest'] (a register-chain deed BOUND to the parcel by bind_chain()).
Chesterfield's own fix (round 17, scripts/ingest_chesterfield_wthgis.py) proves
the right shape: fetch the WTH getftr.aspx detail page per parcel and write
Deed Book/Page straight into raw['county_deed_ref'] directly -- no
PARCEL_LAYERS registration, no parcel_cache.py schema change, and (as a direct
consequence) this ALSO gives lawyer_lane.county_deed_ref() a real date/book/page
to hand bind_chain(), unblocking the ALREADY-BUILT scripts/
backfill_marlboro_rod_chain.py's "name_only"-only ceiling the gap_matrix comment
above describes -- that script needs no changes at all; it already reads
exactly these fields through county_deed_ref()/bind_chain(), just never had
anything to bind against before this.

DSID DISCOVERY. Read straight off marlborosc.wthgis.com's own homepage (the
"Parcel Tools Menu" menu item's own fetchOverlay call, same place Chesterfield's/
Dillon's/McCormick's DSIDs were each found): `addMenuItem("tgis/btnParcels.png",
"Parcel Tools Menu","fetchOverlay('tgis/custom.aspx?DSID=2558&RequestType=
CustomSearchForm&FormType=BasicParcels')")`. Subdomain confirmed from this
project's own 2026-09-21 sc_parcel_viewers.json ArcGIS feature-service snapshot
("https://marlborosc.wthgis.com/", county_name "Marlboro") and live-reconfirmed
tonight (HTTP 200, "Marlboro Co, SC Map" title, same tgisServer2.js app shell
chesterfieldsc.wthgis.com/williamsburgsc.wthgis.com/dillonsc.wthgis.com serve).

LIVE-VERIFIED tonight, 20-row spread sample of real board owner surnames (Eddie,
Nancy, Velma, Leslie, AAC, Cain, Damon, Gaddy -- the board's own first 8 distinct
defendant surnames): every getftr.aspx detail page carries Map&nbsp;Number
(matches the board's own `parcel_id` format BYTE FOR BYTE -- "NNN-NN-NN-NNN",
confirmed on 1,226 of 1,234 Marlboro rows that carry a parcel_id at all; the
other 8 are non-TMS ids -- mobile-home/other account numbers -- that will
simply not match here, same as any county's unmatched bucket), Deed&nbsp;Book +
Deed&nbsp;Page (13/20 = 65% of a later ESTATE/HEIR-token sample; some parcels
genuinely have none recorded), Sale&nbsp;Date + Sale&nbsp;Price (19/20 = 95%),
Total&nbsp;Market&nbsp;Appraisal + Total&nbsp;Acreage (19/20 each). Marlboro's
OWN label schema does NOT match the Chesterfield/Williamsburg "MarketValueXxx"
camelCase shape at all -- it has no MarketValueTotalValue/TaxValueTotalValue/
MarketValueAcres fields, and no Owner&nbsp;Name2 (single-owner schema) or
Property&nbsp;Address1 (it is Physical&nbsp;Address instead); mailing city/state
are not split out as their own cells (combined into Mailing&nbsp;Address3, e.g.
"WALLACE SC") the way Chesterfield's Mailing&nbsp;City/Mailing&nbsp;State are.
MARLBORO_MAP below reflects the REAL labels, not the Chesterfield ones.

BOARD I/O: one streaming read-only pass (board_stream.iter_board_rows()) to
build the Marlboro candidate set and its existing values; board_lock() wraps
ONLY the final patch_existing_rows() write (same discipline
backfill_fl_co_deed_ref.py, backfill_orangeburg_assessed_value.py and
ingest_chesterfield_wthgis.py already use) -- never load_board().

POLITENESS: no login/CAPTCHA on this legacy per-county ASP.NET box (open HTTP,
live-confirmed), but it is a small county-run server, not a CDN -- CONCURRENCY=4,
20s timeout, 3 retries, matching Williamsburg's/Chesterfield's own already-proven
pace.

    .venv/bin/python3 -I scripts/backfill_marlboro_wthgis_deed_ref.py --limit 50   # canary
    .venv/bin/python3 -I scripts/backfill_marlboro_wthgis_deed_ref.py              # dry run, full county
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python3 -I scripts/backfill_marlboro_wthgis_deed_ref.py --apply
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

STATE, COUNTY = "SC", "Marlboro"
BASE = "https://marlborosc.wthgis.com/tgis/"
DSID = 2558
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) HighWayResearch/1.0 (+parcel-cache build)"
CONCURRENCY = 4
TIMEOUT_S = 20.0
RETRIES = 3

#: parcel_cache._COLS field -> this county's OWN getftr.aspx label (live-verified
#: 2026-11-18; deliberately NOT the Chesterfield/Williamsburg camelCase labels --
#: Marlboro's own template uses a different, plain-English scheme throughout).
MARLBORO_MAP = {
    "owner": "Owner&nbsp;Name",
    "address": "Physical&nbsp;Address",
    "owner_mailing": ["Mailing&nbsp;Address1", "Mailing&nbsp;Address2",
                       "Mailing&nbsp;Address3", "Mailing&nbsp;ZipCode"],
    "market_value": "Total&nbsp;Market&nbsp;Appraisal",
    "acreage": "Total&nbsp;Acreage",
    "sale_price": "Sale&nbsp;Price",
    "sale_date": "_sale_date_iso",  # pre-normalized key _write_cache() adds to its own copy
    "improvement_value": "Building&nbsp;Market&nbsp;Appraisal",
    # no tax_value / living_sqft / land_use field exists on this county's template
    # at all (live-checked). Total&nbsp;Number&nbsp;Buldings (building COUNT; the
    # live page really does spell it "Buldings", not a comment typo) is fetched
    # in _parse_detail() below for corroboration only -- parcel_cache._COLS has no
    # building-count column, same as every other county on this platform.
}
_DEED_BOOK, _DEED_PAGE = "Deed&nbsp;Book", "Deed&nbsp;Page"
_SALE_DATE, _SALE_PRICE = "Sale&nbsp;Date", "Sale&nbsp;Price"
_LEGAL1, _LEGAL2 = "Legal&nbsp;Description1", "Legal&nbsp;Description2"

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
    rec = {"MapNumber": mapno, "Owner&nbsp;Name": _field(txt, "Owner&nbsp;Name")}
    for f in ("Mailing&nbsp;Address1", "Mailing&nbsp;Address2", "Mailing&nbsp;Address3",
              "Mailing&nbsp;ZipCode", "Physical&nbsp;Address",
              "Total&nbsp;Market&nbsp;Appraisal", "Total&nbsp;Acreage",
              "Building&nbsp;Market&nbsp;Appraisal", "Total&nbsp;Number&nbsp;Buldings",
              _DEED_BOOK, _DEED_PAGE, _SALE_DATE, _SALE_PRICE, _LEGAL1, _LEGAL2):
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


def _iso_sale_date(s: str) -> Optional[str]:
    """Marlboro's own Sale&nbsp;Date cell reads 'YYYY/MM/DD' -- ISO-ify it, and
    drop the platform's own null-date convention ('1900/01/01', seen live) same
    as a 0 sale price is already dropped elsewhere in this codebase."""
    s = (s or "").strip()
    m = re.match(r"^(\d{4})/(\d{2})/(\d{2})$", s)
    if not m or s == "1900/01/01":
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


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

    return {"board_rows": len(rows), "rows": rows, "pid_to_rec": pid_to_rec,
            "records": [(fid_to_rec[fid], pids) for fid, pids in needed_fids.items()
                        if fid in fid_to_rec]}


def _write_cache(records: list[tuple[dict, list[str]]]) -> Path:
    """Bonus, same shape ingest_chesterfield_wthgis.py already uses: a
    parcel_cache SQLite file keyed the generic way (owner/address/mailing/
    market_value/acreage/sale_price/sale_date), so enrich_gis_attrs()'s own
    normal local-cache-join pass picks this county up on every future board
    run too -- no PARCEL_LAYERS registration needed, lookup() only checks file
    existence (parcel_cache.py, confirmed by reading it). Deed Book/Page are
    NOT part of this generic schema (parcel_cache._COLS has no such column,
    true of every county in the file) -- they only ever reach the board via
    the direct raw['county_deed_ref'] patch build_patches() writes below."""
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
        mapped = dict(rec)
        mapped["_sale_date_iso"] = _iso_sale_date(rec.get(_SALE_DATE) or "")
        vals = tuple(parcel_cache._map_val(mapped, c, MARLBORO_MAP.get(c))  # noqa: SLF001
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
        v = float(str(s).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if v != 0 else None


def build_patches(rows: list[dict], pid_to_rec: dict[str, dict]) -> tuple[dict[str, dict], dict]:
    """Fill-only patches: never overwrite a value the board already has."""
    patches: dict[str, dict] = {}
    stats = {"no_pid": 0, "no_match": 0, "no_key": 0, "no_new_data": 0, "deed_ref_gained": 0}
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
        mv = _num(rec.get("Total&nbsp;Market&nbsp;Appraisal"))
        if mv and not (r.get("assessed_value") or 0):
            patch["assessed_value"] = mv
        ac = _num(rec.get("Total&nbsp;Acreage"))
        if ac and not (r.get("acreage") or 0):
            patch["acreage"] = ac
        legal = " ".join(p for p in (rec.get(_LEGAL1) or "", rec.get(_LEGAL2) or "") if p).strip()
        if legal and not (r.get("legal_description") or "").strip():
            patch["legal_description"] = legal

        book, page = (rec.get(_DEED_BOOK) or "").strip(), (rec.get(_DEED_PAGE) or "").strip()
        sale_date = _iso_sale_date(rec.get(_SALE_DATE) or "")
        existing_cdr = (r.get("raw") or {}).get("county_deed_ref") if isinstance(r.get("raw"), dict) else None
        existing_book_page = isinstance(existing_cdr, dict) and existing_cdr.get("book") and existing_cdr.get("page")
        if _book_page_ok(book, page) and not existing_book_page:
            patch["raw"] = {"county_deed_ref": {
                "source": "marlboro_wthgis", "parno": rec.get("MapNumber"),
                "book": book, "page": page, "date": sale_date, "fetched_at": now_iso,
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
        with board_lock(REPO, owner="backfill_marlboro_wthgis_deed_ref", wait=3600, poll=10):
            pstats = patch_existing_rows(
                patches, {"backfill_marlboro_wthgis_deed_ref": len(patches)}, docs_dir=docs_dir)
    except BoardLockBusy as exc:
        print(f"{exc} -- refusing to write ({len(patches):,} patches lost; re-run to redo).")
        return 1
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
