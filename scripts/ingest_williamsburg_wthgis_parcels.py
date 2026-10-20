#!/usr/bin/env python3
"""Build a parcel_cache SQLite file for Williamsburg County, SC from the live
williamsburgsc.wthgis.com "tgis" viewer -- the gap_matrix's vacant_lot / heir_estate
"sourced-not-built" entries for Williamsburg (2026-10-20).

BACKGROUND. parcel_cache.py already carries a note (2026-09-21) that Marion /
Williamsburg / Clarendon / Marlboro were investigated and NOT added because the "WTH
'tgis' viewer" exposes "no REST" -- true in the ArcGIS FeatureServer sense (confirmed
again live tonight: /arcgis/rest/services, /server/rest/services, /gis/rest/services,
/rest/services all 404 on this host). But the viewer's own legacy ASP.NET endpoints
ARE live, scriptable and open (no login, no CAPTCHA, verified live 2026-10-20):

  tgis/custom.aspx?DSID=56&RequestType=CustomSearchRequest&SearchType=Name
      &SearchCriteria=<lastname>|<firstname>
      -- substring search across EVERY Williamsburg parcel's owner-name text in one
      request. Returns an ordered HTML result list: Map Number (TMS, "45-279-255"
      style -- matches this project's board parcel_id for Williamsburg exactly) +
      owner name + the record's internal numeric FeatureID (the `showf(56, N)`
      onclick on each result row).

  tgis/getftr.aspx?D=56&F=<FeatureID>&Z=1
      -- the single-parcel detail "identify" call: owner name(s), full mailing
      address, property address, legal description, deed/plat book-page, District,
      and -- the field this gap needed -- BOTH a building COUNT
      (MarketValueBuildings) and a building DOLLAR value (MarketValueBuildingsValue)
      for the Assessment year. No land_use/property-type text field exists anywhere
      in the record (only 3 tabs: General / Assessment / History) -- confirmed by
      reading the full CDATA block, not just scanning for an expected field name.

  Sequential FeatureID enumeration (D=56, F=1..~29,413) DOES return a full record for
  every F in range -- i.e. a true county-wide dump is technically possible -- but
  Williamsburg's ~29,400 total parcels is ~10x more than the 2,921 the board actually
  carries (100% sourced from qpaybill_delinquent_roll, live-confirmed against
  board_stream.iter_board_rows()). Canary-tested the full-dump path at concurrency=10:
  7/60 (12%) requests timed out at 15s -- this is a small legacy per-county ASP.NET
  box, not a CDN-backed ArcGIS service, and does not take high concurrency well.
  Rather than datamine ~26,500 county parcels this project will never use at a pace
  gentle enough not to lean on that server for hours, this script takes the TARGETED
  path: search by each board row's own defendant surname (already on the board, zero
  extra guessing), harvest the Map Number -> FeatureID map from those search results,
  then fetch getftr detail ONLY for the FeatureIDs the board's own 2,921 Williamsburg
  parcel_ids actually resolve to. Same end schema, ~5-6x fewer requests, ~10-20x less
  load on the county's server than a full dump, and the number this gap actually
  needed (county-wide coverage was never the question Williamsburg posed).

VACANT-LOT SIGNAL. MarketValueBuildings (count) and MarketValueBuildingsValue
(dollars) were 0 together and nonzero together on every one of 9 live samples pulled
while scoping this (zero correlation break). Only the dollar value is stored (the
existing _COLS schema has no building-count column), matching the exact
"_VALUE_ONLY_NO_LANDUSE" shape already shipped for Sumter SC (parcel_cache.py,
2026-10-20 commit 151c6599) -- improvement_value == 0 means vacant, no land_use text
to cross-check against because the county genuinely never published one. 8 live
satellite spot-checks (4 improvement_value==0, 4 >0; World Imagery, cropped to each
parcel's own identify-call label point): 6/6 clean on small-to-medium acreage
(<2 acres: 2 improved with real rooftops, 2 vacant with bare canopy/field); the other
2 improved-side checks sat on 30-93 acre tracts where a single label point cannot
rule a structure in or out anywhere on the parcel -- inconclusive, not contradicted,
and the field being checked is the county assessor's own building count/value, not a
derived heuristic. No large-acreage exclusion is applied: nothing in the sample
contradicted the signal, the inconclusive cases are a visual-verification limit, not
a sign the field is wrong, and the identical acreage-caveat already stands
undisclaimed on Sumter's shipped version of this same rule.

    .venv/bin/python3 -I scripts/ingest_williamsburg_wthgis_parcels.py
    .venv/bin/python3 -I scripts/ingest_williamsburg_wthgis_parcels.py --limit 50  # canary
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

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import httpx  # noqa: E402

from foreclosure_scraper import parcel_cache  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402

BASE = "https://williamsburgsc.wthgis.com/tgis/"
DSID = 56
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) HighWayResearch/1.0 (+parcel-cache build)"
CONCURRENCY = 5
TIMEOUT_S = 20.0
RETRIES = 3

#: The "map" spec lives on PARCEL_LAYERS["Williamsburg"] itself (single source of
#: truth for lookup()/sc_heir_estate_parcel_cache.py and this script alike), applied
#: with parcel_cache._map_val so formatting (squash, _tidy_mailing, numeric coercion)
#: is byte-identical to every ArcGIS-sourced county's cache.
WILLIAMSBURG_MAP = parcel_cache.PARCEL_LAYERS["Williamsburg"]["map"]

_FIELD_RE_CACHE: dict[str, re.Pattern] = {}


def _field(txt: str, name: str) -> str:
    pat = _FIELD_RE_CACHE.get(name)
    if pat is None:
        pat = _FIELD_RE_CACHE[name] = re.compile(
            re.escape(name) + r"</th><td[^>]*>([^<]*)</td>")
    m = pat.search(txt)
    return m.group(1).strip() if m else ""


_BASE_MAPNO_RE = re.compile(r"^(\d{2}-\d{3}-\d{3})(?:[.\-\s].*)?$")


def _base_mapno(pid: str) -> str:
    """Williamsburg's qpaybill-sourced board parcel_id carries a sub-account suffix
    on 45% of rows ("45-120-068.A", ".01", ...) that the GIS's own Map Number field
    never has -- live-confirmed (45-120-068.A and 45-120-069.A on the board are two
    DIFFERENT real GIS records "45-120-068"/"45-120-069", not one record split two
    ways: the suffix is the tax roll's own sub-account marker, not a GIS sub-parcel).
    Strips it back to the bare "NN-NNN-NNN" the search index actually keys on."""
    m = _BASE_MAPNO_RE.match(pid)
    return m.group(1) if m else pid


def _surname(defendant: str) -> str:
    """First whitespace token of the board's defendant string, stripped of the
    trailing commas/ampersands these rolls carry ("ANDERSON CORA ETAL" -> "ANDERSON";
    "ALTMAN BOBBY E JR" -> "ALTMAN"). Good enough as a SEARCH seed -- the real match
    is confirmed afterward by exact Map Number, never by name alone."""
    s = (defendant or "").strip()
    if not s:
        return ""
    tok = re.split(r"\s+", s)[0]
    return re.sub(r"[^A-Za-z'-]", "", tok).strip()


async def _get(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> str | None:
    async with sem:
        for attempt in range(RETRIES):
            try:
                r = await client.get(url, timeout=TIMEOUT_S)
                if r.status_code == 200 and len(r.text) > 60:
                    return r.text
                if r.status_code == 200:
                    return r.text  # short-but-200 (e.g. empty result) is still valid
            except (httpx.TimeoutException, httpx.TransportError):
                pass
            if attempt < RETRIES - 1:
                await asyncio.sleep(0.5 * (attempt + 1))
        return None


def _parse_search(txt: str) -> dict[str, int]:
    """Map Number -> FeatureID for every hit in one owner-name search response."""
    out: dict[str, int] = {}
    for m in re.finditer(r"showf\(\s*\d+\s*,\s*(\d+)\s*\).*?mainResultItem'>([^<]+)<",
                          txt, re.S):
        fid, mapno = m.group(1), m.group(2).strip()
        if mapno:
            out[mapno] = int(fid)
    return out


def _parse_detail(txt: str) -> dict | None:
    mapno = _field(txt, "Map&nbsp;Number")
    if not mapno:
        return None
    rec = {
        "MapNumber": mapno,
        "OwnerName": _field(txt, "Owner&nbsp;Name"),
        "OwnerName2": _field(txt, "Owner&nbsp;Name2"),
        "MailingAddress1": _field(txt, "Mailing&nbsp;Address1"),
        "MailingAddress2": _field(txt, "Mailing&nbsp;Address2"),
        "MailingCity": _field(txt, "Mailing&nbsp;City"),
        "MailingState": _field(txt, "Mailing&nbsp;State"),
        "MailingZipCode": _field(txt, "Mailing&nbsp;ZipCode"),
        "PropertyAddress1": _field(txt, "Property&nbsp;Address1"),
        "PropertyAddress2": _field(txt, "Property&nbsp;Address2"),
        "MarketValueAcres": _field(txt, "MarketValueAcres"),
        "MarketValueBuildingsValue": _field(txt, "MarketValueBuildingsValue"),
        "MarketValueTotalValue": _field(txt, "MarketValueTotalValue"),
        "TaxValueTotalValue": _field(txt, "TaxValueTotalValue"),
    }
    # Most recent sale: first row of the History tab's Sale Date / Sale Price table.
    hist = re.search(
        r"Sale Date.*?Sale Price.*?Grantor.*?Grantee.*?Book.*?Page.*?\|\s*\|\s*"
        r"([\d/]+)\s*\|\s*\|\s*\$?([\d,]+\.\d{2})",
        txt.replace("&nbsp;", " "))
    if not hist:
        hist = re.search(r"<td[^>]*>(\d{2}/\d{2}/\d{4})</td>\s*<td[^>]*>\$?([\d,.]+)</td>",
                          txt)
    if hist:
        rec["SaleDate"] = hist.group(1)
        rec["SalePrice"] = hist.group(2).replace(",", "")
    return rec


def _board_williamsburg_rows() -> list[dict]:
    out = []
    for r in iter_board_rows(REPO / "docs" / "listings.json.gz"):
        if (r.get("county") or "").strip().lower() == "williamsburg" and \
           (r.get("state") or "").strip().upper() == "SC":
            out.append(r)
    return out


async def _run(limit: int | None) -> dict:
    board_rows = _board_williamsburg_rows()
    if limit:
        board_rows = board_rows[:limit]
    print(f"board rows (Williamsburg, SC): {len(board_rows):,}")

    surnames = sorted({_surname(r.get("defendant") or "") for r in board_rows} - {""})
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

        # Resolve each board parcel_id to a FeatureID (exact Map Number match only).
        needed_fids: dict[int, list[str]] = {}
        unmatched = 0
        for r in board_rows:
            pid = (r.get("parcel_id") or "").strip()
            if not pid:
                unmatched += 1
                continue
            fid = mapid_to_fid.get(pid)
            if fid is None:
                fid = mapid_to_fid.get(_base_mapno(pid))
            if fid is None:
                unmatched += 1
                continue
            needed_fids.setdefault(fid, []).append(pid)
        print(f"board parcel_id -> FeatureID resolved: {len(needed_fids):,} "
              f"(unmatched: {unmatched:,})")

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

    # One entry per (record, every board parcel_id string that resolved to it) so the
    # cache can be indexed under the board's OWN parcel_id spelling (which may carry a
    # qpaybill sub-account suffix the GIS Map Number never has -- see _base_mapno).
    records = [(fid_to_rec[fid], pids) for fid, pids in needed_fids.items() if fid in fid_to_rec]

    return {"board_rows": len(board_rows), "surnames": len(surnames),
            "search_hits": len(mapid_to_fid), "unmatched": unmatched,
            "records": records}


def _write_cache(records: list[tuple[dict, list[str]]]) -> Path:
    parcel_cache.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    db_path = parcel_cache._db_path("Williamsburg", "SC")  # noqa: SLF001
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
        vals = tuple(parcel_cache._map_val(rec, c, WILLIAMSBURG_MAP.get(c))  # noqa: SLF001
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
    ap.add_argument("--limit", type=int, default=None,
                     help="only process the first N board rows (canary run)")
    ap.add_argument("--no-write", action="store_true",
                     help="fetch + report only, skip the SQLite write")
    args = ap.parse_args()

    result = asyncio.run(_run(args.limit))
    records = result["records"]
    if not records:
        print("no records fetched -- cache NOT written")
        return 1

    if args.no_write:
        print(f"[--no-write] would cache {len(records):,} parcel records")
        return 0

    db_path = _write_cache(records)
    print(f"wrote {len(records):,} parcel records -> {db_path} "
          f"({db_path.stat().st_size/1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
