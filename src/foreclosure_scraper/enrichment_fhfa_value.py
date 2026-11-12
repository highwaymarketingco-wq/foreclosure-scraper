"""FHFA House-Price-Index AVM — a COARSE, free fallback current-value estimate.

When comps are thin (no recorded/scraped sales within radius, no Zestimate), but
we DO know what the owner paid and when (a last arms-length sale price + date now
surfaced by the SCDOT / qPublic-card / county-GIS enrichers), we can still put a
number on today's value by trend-scaling that purchase against the FHFA House
Price Index for the property's metro:

    current_value = last_sale_price * HPI_now / HPI_then

This is NOT a parcel- or comp-level appraisal — it's a market-trend rescale, so
it carries NO size/condition/lot adjustment and is labelled a low-confidence
FALLBACK. valuation/calc.py should only reach for it when every real comp tier
is empty. It exists so a lead with a known purchase but no live comps still gets
*an* ARV input (which the equity engine then needs to compute any equity at all)
instead of falling through to nothing.

Data: two free, no-auth, quarterly (1975Q1–present) FHFA CSVs, cached locally:
  * hpi_at_metro.csv  — "place, TX",CBSA,year,quarter,index_NSA,(stderr)
  * hpi_at_state.csv  — STATE,year,quarter,index            (no header)
Both encode missing early-year indices as a literal "-", which we guard against.

Footprint counties map to their MSA's CBSA when one covers them; rural / non-MSA
footprint counties fall back to the NC or SC statewide series. Pure index math —
the only I/O is the one-time CSV download (via http_client.get_bytes), cached on
disk so a normal run does no network at all.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path
from typing import Optional

import structlog

from .models import Listing
from .valuation.amortize import _as_date

log = structlog.get_logger()

# --- source CSVs + on-disk cache --------------------------------------------
_METRO_URL = "https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_metro.csv"
_STATE_URL = "https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_state.csv"

# Repo-root data dir, same convention as parcel_inventory.py / sc_*_footprints.py.
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fhfa"
_METRO_CACHE = _DATA_DIR / "hpi_at_metro.csv"
_STATE_CACHE = _DATA_DIR / "hpi_at_state.csv"

# --- footprint county -> CBSA (MSA) map -------------------------------------
# Only counties that sit inside one of these MSAs map to a CBSA; every other
# footprint county (rural / non-MSA, plus most coastal counties) falls back to
# the state series via _STATE_BY_COUNTY below. Keys are Title-cased county names.
_CBSA_BY_COUNTY: dict[tuple[str, str], int] = {
    # Asheville MSA
    ("NC", "Buncombe"): 11700,
    ("NC", "Henderson"): 11700,
    # Hickory-Lenoir-Morganton MSA
    ("NC", "Burke"): 25860,
    ("NC", "McDowell"): 25860,   # added to the Hickory MSA in the 2023 OMB delineation
    # Charlotte-Concord-Gastonia MSA
    ("NC", "Gaston"): 16740,
    ("NC", "Lincoln"): 16740,
    # Wilmington MSA
    ("NC", "New Hanover"): 48900,
    ("NC", "Pender"): 48900,
    # Greenville-Anderson-Greer MSA
    ("SC", "Anderson"): 24860,
    ("SC", "Laurens"): 24860,
    ("SC", "Pickens"): 24860,
    # Spartanburg MSA
    ("SC", "Spartanburg"): 43900,
    ("SC", "Cherokee"): 43900,   # added to the Spartanburg MSA in the 2023 OMB delineation
    # Myrtle Beach-Conway-North Myrtle Beach MSA
    ("SC", "Horry"): 34820,
    # Charleston-North Charleston MSA
    ("SC", "Charleston"): 16700,
    ("SC", "Berkeley"): 16700,
    ("SC", "Dorchester"): 16700,
}

# Everything else in the footprint -> the property's STATE series. Listed
# explicitly (rather than "anything NC/SC") so a typo'd county is never silently
# valued off the wrong series; an unmapped county simply gets no FHFA estimate.
_STATE_ONLY_COUNTIES: dict[str, frozenset[str]] = {
    "NC": frozenset({
        "Cleveland", "Mitchell", "Polk", "Rutherford", "Transylvania",
        "Brunswick", "Onslow", "Carteret", "Dare",
    }),
    "SC": frozenset({
        "Oconee", "Union",
        "Beaufort", "Georgetown", "Colleton",
    }),
}

# How recent the index reading must be before we trust the rescale: a purchase
# decades ago compounds index error, but we still allow it (labelled low conf).
_MIN_PLAUSIBLE_PRICE = 10_000.0     # ignore $1 / nominal family-transfer "sales"


# --- index table ------------------------------------------------------------
class _HPITable:
    """In-memory FHFA HPI lookup: (key) -> {(year, quarter): index_float}.

    Metro keys are the integer CBSA code; state keys are the 2-letter code.
    Built once per process from the cached CSVs. `latest(key)` returns the most
    recent non-blank quarter; `at(key, dt)` returns the index for the quarter
    containing a date (falling back to the nearest earlier quarter we have).
    """

    def __init__(self) -> None:
        self._metro: dict[int, dict[tuple[int, int], float]] = {}
        self._state: dict[str, dict[tuple[int, int], float]] = {}

    @staticmethod
    def _to_float(raw: str) -> Optional[float]:
        # FHFA encodes a missing index as a literal "-" (early years before a
        # metro had enough sales). Guard so "-" never becomes 0.0 or raises.
        s = (raw or "").strip()
        if not s or s == "-":
            return None
        try:
            v = float(s)
        except ValueError:
            return None
        return v if v > 0 else None

    def load_metro(self, text: str) -> None:
        # "place, ST",CBSA,year,quarter,index_NSA,(stderr) — quoted place may
        # contain a comma, so parse with csv, not str.split.
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 5:
                continue
            try:
                cbsa, yr, q = int(row[1]), int(row[2]), int(row[3])
            except (ValueError, IndexError):
                continue  # header / malformed line
            idx = self._to_float(row[4])
            if idx is None:
                continue
            self._metro.setdefault(cbsa, {})[(yr, q)] = idx

    def load_state(self, text: str) -> None:
        # STATE,year,quarter,index — no header, no quoting.
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 4:
                continue
            st = (row[0] or "").strip().upper()
            try:
                yr, q = int(row[1]), int(row[2])
            except (ValueError, IndexError):
                continue
            idx = self._to_float(row[3])
            if idx is None or len(st) != 2:
                continue
            self._state.setdefault(st, {})[(yr, q)] = idx

    def _series(self, *, cbsa: int | None, state: str | None) -> dict[tuple[int, int], float] | None:
        if cbsa is not None:
            s = self._metro.get(cbsa)
            if s:
                return s
        if state:
            return self._state.get(state.upper())
        return None

    def latest(self, *, cbsa: int | None = None, state: str | None = None
               ) -> Optional[tuple[tuple[int, int], float]]:
        s = self._series(cbsa=cbsa, state=state)
        if not s:
            return None
        key = max(s)               # latest (year, quarter)
        return key, s[key]

    def at(self, dt: date, *, cbsa: int | None = None, state: str | None = None
           ) -> Optional[tuple[tuple[int, int], float]]:
        """Index for the quarter containing `dt`; else the nearest earlier
        quarter we have (a purchase between releases / a stale series tail)."""
        s = self._series(cbsa=cbsa, state=state)
        if not s:
            return None
        want = (dt.year, (dt.month - 1) // 3 + 1)
        if want in s:
            return want, s[want]
        earlier = [k for k in s if k <= want]
        if not earlier:
            return None
        key = max(earlier)
        return key, s[key]


_TABLE: _HPITable | None = None


async def _ensure_csvs() -> bool:
    """Download both CSVs to the local cache once. Returns False if unavailable."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _METRO_CACHE.exists() and _STATE_CACHE.exists():
        return True
    from .http_client import get_bytes
    ok = True
    for url, dest in ((_METRO_URL, _METRO_CACHE), (_STATE_URL, _STATE_CACHE)):
        if dest.exists():
            continue
        try:
            data = await get_bytes(url, timeout=90.0)
            if not data or len(data) < 1000:   # a real CSV is hundreds of KB
                raise ValueError(f"suspiciously small download ({len(data)}B)")
            dest.write_bytes(data)
            log.info("fhfa.cached", url=url, bytes=len(data))
        except Exception as exc:  # noqa: BLE001
            log.warning("fhfa.download_failed", url=url, error=str(exc)[:160])
            ok = False
    return ok and _METRO_CACHE.exists() and _STATE_CACHE.exists()


async def _table() -> _HPITable | None:
    """Lazily build (and cache for the process) the in-memory HPI lookup."""
    global _TABLE
    if _TABLE is not None:
        return _TABLE
    if not await _ensure_csvs():
        return None
    t = _HPITable()
    try:
        t.load_metro(_METRO_CACHE.read_text(encoding="utf-8", errors="replace"))
        t.load_state(_STATE_CACHE.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        log.warning("fhfa.parse_failed", error=str(exc)[:160])
        return None
    if not t._metro and not t._state:
        return None
    _TABLE = t
    return _TABLE


# --- listing field extraction -----------------------------------------------
def _county(li: Listing) -> str:
    return (li.county or "").strip().title()


def _series_for(li: Listing) -> tuple[Optional[int], Optional[str]]:
    """(cbsa, state) the listing's value should be trended against.

    CBSA when the county sits in a mapped MSA; otherwise the state series for any
    footprint county explicitly listed as non-MSA. Returns (None, None) for
    out-of-footprint / unrecognized counties so they get no FHFA estimate."""
    state = (li.state or "").strip().upper()
    county = _county(li)
    if not state or not county:
        return None, None
    cbsa = _CBSA_BY_COUNTY.get((state, county))
    if cbsa is not None:
        return cbsa, state
    if county in _STATE_ONLY_COUNTIES.get(state, frozenset()):
        return None, state
    return None, None


def _last_sale(li: Listing) -> tuple[Optional[float], Optional[date]]:
    """Best known last arms-length sale (price, date) from any upstream enricher.

    Checks, in order: the GIS last_sale block (ArcGIS), flat GIS fields, and the
    assessor/qPublic card. Never uses li.sale_date — that's the FORECLOSURE
    auction date, not the prior purchase. Returns (None, None) if nothing usable
    or the price is below the nominal-transfer floor."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    gis = raw.get("gis") if isinstance(raw.get("gis"), dict) else {}

    candidates: list[tuple[object, object]] = []
    ls = gis.get("last_sale") if isinstance(gis.get("last_sale"), dict) else {}
    if ls:
        candidates.append((ls.get("amount"), ls.get("date")))
    candidates.append((gis.get("last_sale_amount"), gis.get("last_sale_date")))

    card = raw.get("assessor_card") if isinstance(raw.get("assessor_card"), dict) else {}
    if card:
        sales = card.get("sales") if isinstance(card.get("sales"), list) else []
        first = sales[0] if sales and isinstance(sales[0], dict) else {}
        # card sales are newest-first; pair the headline price with that date
        candidates.append((card.get("sale_price"), first.get("sale_date")))
        candidates.append((first.get("price"), first.get("sale_date")))

    # Top-level raw["last_sale"] — the recorded-sales / deed enricher's block, and
    # the MOST populated last-sale source on the board (~34%). It was the missing
    # source: FHFA read gis.last_sale + card.sales only, so the stale-sale
    # appreciation fired on ~0% (verified 2026-08-13). Key names vary by producer
    # (price/amount, date/sale_date/sale_date_iso), so try each pairing.
    top = raw.get("last_sale") if isinstance(raw.get("last_sale"), dict) else {}
    if top:
        amt = top.get("price") if top.get("price") is not None else top.get("amount")
        dt = top.get("date") or top.get("sale_date") or top.get("sale_date_iso")
        candidates.append((amt, dt))

    for amt_raw, date_raw in candidates:
        try:
            amt = float(amt_raw) if amt_raw not in (None, "") else None
        except (ValueError, TypeError):
            amt = None
        dt = _as_date(date_raw)
        if amt and amt >= _MIN_PLAUSIBLE_PRICE and dt:
            return amt, dt
    return None, None


# --- public API -------------------------------------------------------------
async def enrich_fhfa_value(listings: list[Listing]) -> dict:
    """Attach raw['fhfa_value'] = {est_value, msa_or_state, hpi_then, hpi_now,
    as_of, ...} for any listing with a known last_sale_price + sale_date.

    COARSE trend-rescale fallback (see module docstring) — labelled low
    confidence. Pure index math after a one-time CSV cache; safe to call every
    run. Returns a small stats dict for the run report."""
    targets = [li for li in listings if _series_for(li) != (None, None)]
    if not targets:
        log.info("fhfa.skip_no_footprint_targets", total=len(listings))
        return {"computed": 0, "candidates": 0}

    table = await _table()
    if table is None:
        log.warning("fhfa.no_table")
        return {"computed": 0, "candidates": len(targets), "error": "hpi_unavailable"}

    computed = 0
    candidates = 0
    for li in targets:
        cbsa, state = _series_for(li)
        sale_price, sale_dt = _last_sale(li)
        if not sale_price or not sale_dt:
            continue
        candidates += 1

        then = table.at(sale_dt, cbsa=cbsa, state=state)
        now = table.latest(cbsa=cbsa, state=state)
        # Metro series can have gaps in a thin quarter — fall back to the state
        # series so a real purchase still gets *an* estimate rather than none.
        if (then is None or now is None) and cbsa is not None and state:
            then = then or table.at(sale_dt, state=state)
            now = now or table.latest(state=state)
            cbsa = None  # the numbers we used are state-level; label them so
        if then is None or now is None:
            continue
        (then_yq, hpi_then) = then
        (now_yq, hpi_now) = now
        if hpi_then <= 0 or hpi_now <= 0:
            continue

        est_value = round(sale_price * hpi_now / hpi_then, -2)
        label = f"CBSA:{cbsa}" if cbsa is not None else f"{(state or '').upper()} (state)"
        raw = li.raw if isinstance(li.raw, dict) else {}
        raw["fhfa_value"] = {
            "est_value": est_value,
            "msa_or_state": label,
            "hpi_then": round(hpi_then, 2),
            "hpi_now": round(hpi_now, 2),
            "sale_price": round(sale_price, 2),
            "sale_quarter": f"{then_yq[0]}Q{then_yq[1]}",
            "as_of": f"{now_yq[0]}Q{now_yq[1]}",
            "confidence": "low",
            "method": "fhfa_hpi_trend_rescale",
            "is_fallback": True,
        }
        li.raw = raw
        computed += 1

    log.info("fhfa.done", computed=computed, candidates=candidates, targets=len(targets))
    return {"computed": computed, "candidates": candidates, "targets": len(targets)}
