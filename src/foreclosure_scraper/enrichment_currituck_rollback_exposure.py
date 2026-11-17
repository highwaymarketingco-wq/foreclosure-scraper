"""Currituck County NC's own real, public, downloadable NC-DOR "AA502" certified-parcel
listing (a standard NC DOR export format) -> raw['rollback_exposure'] from its own USE_VALUE_
field.

WHY THIS EXISTS (round 19 of the tax-cluster gap_matrix sweep, 2026-11-17). Round 18 found this
source but did not have time to parse or build it (see project_tax_cluster_round18_2026-11-17.md
's own Currituck section): no live ArcGIS REST directory for Currituck exposes a CAMA/tax field
at all (`Currituck/iasWorldBase` and `iasWorldBase2026` MapServer's own "Parcels" layer carries
only geometry/parcel-ID fields -- confirmed again this round), but the county's own tax-data
page (https://currituckcountync.gov/tax/tax-data/) links a direct XLSX download, refreshed
periodically (the live file read 2026-11-17 was dated "Updated, September 16, 2026"):
    https://www.currituckcountync.gov/wp-content/uploads/aa502nccur-updated-parcel.xlsx
26,988 real data rows, 52 columns, header-confirmed (`C_PARID`, `TOTAL_VALU`, `USE_VALUE_`
[present-use value], `GLOBAL_PIN`, `TAX_YEAR`, ...). Live-sampled 2026-11-17: 1,015 rows carry
a real present-use deferral (`0 < USE_VALUE_ < TOTAL_VALU`), e.g. C_PARID "126A0000076000Q",
owner "GRUBB, DANIEL S JR TRUSTEE", USE_VALUE_ $0 total_valu $643,800 (TAX_YEAR 2027, the
upcoming/current cycle -- genuinely fresh, not stale).

PARCEL JOIN -- THE missing piece round 18 left open, resolved this round. The board's own
Currituck parcel_id (e.g. "993591506800000", 15 digits) is NEITHER this file's `C_PARID`
(alphanumeric map/lot-based, e.g. "126A0000076000Q") NOR a direct NC OneMap statewide `parno`/
`altparno` match (both checked live, 0 hits) -- it is the county's own live GIS `PIN_1` field
(`maps.currituckcountync.gov/.../iasWorldBase2026/MapServer/0`, dashed "9935-91-5068") with the
dashes stripped and zero-padded to 15 chars. This file's own `GLOBAL_PIN` column carries that
SAME PIN, already dashed exactly like the live GIS's PIN_1 -- live-confirmed on 2 independent
real parcels (owner GRUBB/772 Mariner Dr -> GLOBAL_PIN "9935-91-5068" == board parcel_id
"993591506800000"[:10]; owner LOTUS RIDGE LLC -> GLOBAL_PIN "8021-62-7129" == board parcel_id
"802162712900000"[:10], confirmed via the live `iasWorldBase2026` MapServer's own PARCEL_ID/
PARCEL/C_PARID/PIN_1 fields for the first parcel). So the join key is `GLOBAL_PIN` with its
dashes stripped (10 digits), matched against the board's own parcel_id's first 10 characters
(the trailing 5 characters are this board's own zero-padding, not part of the real PIN).

BULK, not per-row: the whole file is downloaded ONCE per run (~6MB, no login, no CAPTCHA/WAF)
and parsed with the stdlib `zipfile`+`xml.etree.ElementTree` (this project's venv has no
`openpyxl` -- confirmed again this round, same as round 18's own note), filtered in Python to
real deferrals, then joined locally against every Currituck NC board row with a parcel_id.

WHAT THIS DOES NOT COVER. This file carries no balance-due/tax-year-arrears history field (only
CAMA value fields + one ownership/sale snapshot), so multi_year_delinquent_tax/
two_year_delinquent/tax_aging_surfaced have no source here -- a genuinely separate research
question, not touched by this module. atty_tax_verified_confirmed is verdict-driven (needs its
own Currituck tax_lien verifier, not a producer) and is also not touched here.

Gate off entirely with FORECLOSURE_CURRITUCK_ROLLBACK=0.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from typing import Any, Iterable, Optional

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

SLUG = "enrichment_currituck_rollback_exposure"
STATE, COUNTY = "NC", "Currituck"
AA502_URL = "https://www.currituckcountync.gov/wp-content/uploads/aa502nccur-updated-parcel.xlsx"
#: NC G.S. 105-277.4(c) -- see enrichment_rollback_deferral.py's own module docstring.
ROLLBACK_YEARS_NC = 4

ENABLED = os.environ.get("FORECLOSURE_CURRITUCK_ROLLBACK") != "0"
_FETCH_TIMEOUT = float(os.getenv("CURRITUCK_ROLLBACK_TIMEOUT", "60.0"))

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
_NON_DIGIT = re.compile(r"[^0-9]")
_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# 0-indexed column positions in the AA502 parcel sheet's own header row (live-confirmed
# 2026-11-17; see the module docstring above).
_COL_C_PARID = 0
_COL_TOTAL_VALU = 4
_COL_USE_VALUE = 5
_COL_GLOBAL_PIN = 49
_COL_TAX_YEAR = 50


def _compact_pin(value: Any) -> str:
    """Digits-only form of a dashed GIS PIN ('9935-91-5068' -> '9935915068'), or of a board
    parcel_id truncated to its real 10-digit PIN (see the module docstring's join-key note)."""
    return _NON_DIGIT.sub("", str(value or ""))


def _board_pin10(parcel_id: Any) -> str:
    """The board's own Currituck parcel_id is the real 10-digit PIN zero-padded to 15 chars
    (live-confirmed on 2 independent real parcels -- see the module docstring). Strip to digits
    first (defensive -- a dashed board spelling would also work), then take the first 10."""
    digits = _compact_pin(parcel_id)
    return digits[:10] if len(digits) >= 10 else ""


def _col_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def _load_shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        data = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(data)
    out = []
    for si in root.findall(f"{_XLSX_NS}si"):
        texts = si.findall(f".//{_XLSX_NS}t")
        out.append("".join(t.text or "" for t in texts))
    return out


def _iter_rows(z: zipfile.ZipFile, shared: list[str]) -> Iterable[dict[int, Optional[str]]]:
    """Stdlib-only XLSX row reader (no openpyxl in this project's venv -- see the module
    docstring). Streams via iterparse so a 6MB sheet doesn't hold a parsed tree in memory."""
    with z.open("xl/worksheets/sheet1.xml") as f:
        for event, elem in ET.iterparse(f, events=("end",)):
            if elem.tag != f"{_XLSX_NS}row":
                continue
            cells: dict[int, Optional[str]] = {}
            for c in elem.findall(f"{_XLSX_NS}c"):
                ref = c.get("r") or ""
                idx = _col_index(ref) if ref else len(cells)
                t = c.get("t")
                v_elem = c.find(f"{_XLSX_NS}v")
                val = v_elem.text if v_elem is not None else None
                if t == "s" and val is not None:
                    val = shared[int(val)]
                cells[idx] = val
            yield cells
            elem.clear()


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_deferrals(xlsx_bytes: bytes) -> dict[str, dict]:
    """{pin10 (digits-only): {"use_value", "total_value", "c_parid", "tax_year"}} for every row
    with a real present-use deferral (0 < USE_VALUE_ < TOTAL_VALU). Pure (no network)."""
    by_pin: dict[str, dict] = {}
    with zipfile.ZipFile(BytesIO(xlsx_bytes)) as z:
        shared = _load_shared_strings(z)
        first = True
        for cells in _iter_rows(z, shared):
            if first:
                first = False
                continue  # header row
            use_val = _to_float(cells.get(_COL_USE_VALUE))
            total_val = _to_float(cells.get(_COL_TOTAL_VALU))
            if not use_val or use_val <= 0 or not total_val or use_val >= total_val:
                continue
            pin10 = _compact_pin(cells.get(_COL_GLOBAL_PIN))
            if len(pin10) != 10:
                continue
            by_pin[pin10] = {"use_value": use_val, "total_value": total_val,
                              "c_parid": cells.get(_COL_C_PARID),
                              "tax_year": cells.get(_COL_TAX_YEAR)}
    return by_pin


async def fetch_deferrals(c: httpx.AsyncClient) -> dict[str, dict]:
    r = await c.get(AA502_URL)
    r.raise_for_status()
    return parse_deferrals(r.content)


def build_rollback_block(rec: dict) -> Optional[dict]:
    use_value = rec.get("use_value")
    total_value = rec.get("total_value")
    if not use_value or use_value <= 0 or not total_value or use_value >= total_value:
        return None
    deferred = round(total_value - use_value, 2)
    out: dict[str, Any] = {"deferred_value": deferred, "basis": "present_use_deferral",
                           "county": COUNTY, "state": STATE,
                           "source": "currituckcountync.gov AA502 certified-parcel export "
                                      '("USE_VALUE_" vs "TOTAL_VALU")',
                           "source_key": SLUG, "rollback_years": ROLLBACK_YEARS_NC,
                           "estimate_is_floor": True, "match_method": "parcel_id"}
    out["land_value"] = round(total_value, 2)
    if rec.get("tax_year"):
        out["tax_year"] = rec["tax_year"]
    return out


def _is_currituck_nc(li: Listing) -> bool:
    return li.state == STATE and (li.county or "").strip().lower() == COUNTY.lower()


def _already_done(raw: Any) -> bool:
    """Only a REAL dollar deferred_value counts as done -- same convention as the Macon/
    Haywood siblings (a flag-only presentval=Y marker must not block this real-dollar join)."""
    rb = raw.get("rollback_exposure") if isinstance(raw, dict) else None
    return isinstance(rb, dict) and rb.get("deferred_value") is not None


async def enrich_currituck_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Fetch+parse the AA502 parcel file ONCE (bulk), then join locally against every
    Currituck NC board row by its parcel_id's own 10-digit PIN. Writes raw['rollback_exposure']
    only when a real deferral exists -- never invented."""
    if not ENABLED:
        return {"skipped": "disabled (FORECLOSURE_CURRITUCK_ROLLBACK=0)"}
    targets = [li for li in listings
              if _is_currituck_nc(li) and _board_pin10(li.parcel_id)
              and not _already_done(li.raw if isinstance(li.raw, dict) else {})]
    stats = {"eligible": len(targets), "deferred_pins": 0, "matched": 0, "errors": 0}
    if not targets:
        return stats

    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, headers={"User-Agent": _UA}) as c:
        try:
            by_pin = await fetch_deferrals(c)
        except Exception:  # noqa: BLE001 - a failed fetch must not crash the run
            stats["errors"] += 1
            log.warning("currituck_rollback.fetch_failed")
            return stats
    stats["deferred_pins"] = len(by_pin)

    for li in targets:
        hit = by_pin.get(_board_pin10(li.parcel_id))
        if hit is None:
            continue
        block = build_rollback_block(hit)
        if not block:
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["rollback_exposure"] = block
        stats["matched"] += 1

    log.info("currituck_rollback.done", **stats)
    return stats
