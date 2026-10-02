"""Normalize per-source delinquent-tax amounts into one raw['tax_owed'] field and
cross-reference it onto matching parcels.

The tax-distress scrapers each capture the owed amount under their own raw key —
Buncombe `principal_tax_due`, SC state liens `balance`, Oconee FLC `fll_bid` — and
nothing on the board reads a unified figure. The assessor/GIS feed only ever gives
assessed/market VALUE, never the delinquent BALANCE, so this is the only place a
real taxes-OWED number lands.

Two passes, both free + pure-Python + idempotent:
  1. Normalize: each tax lead's own amount -> raw['tax_owed'] =
     {balance, kind, source, year, basis:'own_record', years_delinquent?} —
     years_delinquent is promoted from a sibling source block when that source
     already states a multi-year count (raw['multi_year_delinquent_tax'],
     raw['qpaybill_roll']), never invented.
  2. Cross-reference: build a (state, county, parcel) -> tax_owed index from those,
     then stamp it onto ANY lead (court/probate/foreclosure) resolved to the same
     parcel that doesn't already carry one (basis:'parcel_cross_ref'). A court lead
     the resolver just pinned to a parcel that is ALSO on a delinquent-tax list
     inherits the owed balance — a strong, free motivated-seller signal.

Gate off with FORECLOSURE_TAX_OWED=0.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, Optional

import structlog

from .models import Listing

log = structlog.get_logger()

# source-substring -> (raw subkey, amount field, kind)
_SOURCES = {
    "buncombe_delinquent_tax": ("buncombe_delinquent_tax", "principal_tax_due", "delinquent_tax"),
    "sc_state_tax_lien": ("sc_state_tax_lien", "balance", "state_tax_lien"),
    "oconee_forfeited_land": ("oconee_forfeited_land", "fll_bid", "flc_opening_bid"),
    "nc_ptscloud_delinquent_tax": ("nc_ptscloud_delinquent_tax", "principal_tax_due", "delinquent_tax"),
    "nc_county_pdf_delinquent_tax": ("nc_county_pdf_delinquent_tax", "total_due", "delinquent_tax"),
    "nc_county_csv_delinquent_tax": ("nc_county_csv_delinquent_tax", "total_due", "delinquent_tax"),
    "rutherford_wildfire": ("rutherford_wildfire", "taxes_owed", "delinquent_tax"),
    "multi_year_delinquent_tax": ("multi_year_delinquent_tax", "total_due", "delinquent_tax"),
    "spartanburg_delinquent_tax": ("spartanburg_delinquent_tax", "balance", "delinquent_tax"),
    "chesterfield_delinquent_tax": ("chesterfield_delinquent_tax", "total_due", "delinquent_tax"),
    "york_delinquent_tax": ("york_delinquent_tax", "total_due", "delinquent_tax"),
    "florence_delinquent_tax": ("florence_delinquent_tax", "total_due", "delinquent_tax"),
    "sumter_delinquent_tax": ("sumter_delinquent_tax", "total_due", "delinquent_tax"),
    # Georgetown's FLC (Forfeited-Land-Commission) rows carry a real, county-published
    # over-the-counter opening-bid price (same convention as oconee_forfeited_land's
    # fll_bid, above). The block key is shared by all three Georgetown CivicEngage docs
    # (FLC/Tax-Sale/MIE) but only FLC rows set "opening_bid", so this entry is a no-op
    # for the other two -- the Tax-Sale list genuinely carries no dollar figure at all
    # (confirmed 2026-09-29, see georgetown_civicengage.py's docstring) and MIE rows use
    # a different raw shape. Added 2026-09-29 auditing the 355-row "no tax amount" gap.
    "georgetown_civicengage": ("georgetown_civicengage", "opening_bid", "flc_opening_bid"),
}

# generic amount keys scanned for any other tax/FLC/lien source subdict
# `balance_owed` (added 2026-09-20) is the real delinquent balance carried by
# raw['qpaybill_roll'] (19 SC counties) and raw['transylvania_tax']. Every one of
# their ~40,000 rows has it, yet only a few hundred reached raw['tax_owed'], so
# Spartanburg showed 288 of 4,280 rows with a known debt. It goes last so it
# never outranks a more specific key on a block that carries both.
_GENERIC_KEYS = (
    "principal_tax_due", "tax_due", "taxes_owed", "amount_owed", "total_due",
    "balance", "lien_amount", "fll_bid", "flc_bid", "opening_bid", "balance_owed",
)
_TAXISH = ("tax", "flc", "forfeited", "delinquent", "lien")


def _money(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = re.sub(r"[^\d.]", "", str(v))
    if not s or s == ".":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f > 0 else None


def _pkey(pid: Optional[str]) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", pid or "").upper()


def _county_county_key(li: Listing) -> tuple:
    return (li.state, (li.county or "").replace(" County", "").strip().title(),
            _pkey(li.parcel_id))


_YEAR_KEYS = ("year", "tax_year", "taxyear", "bill_year", "bill_years",
              "year_span", "latest_cycle", "first_cycle")

# Depth audit 2026-10-02 (per-signal completeness check, not the 2026-09-21 per-
# source extraction audit): raw['tax_owed'] normalizes a balance + a single year
# but drops the multi-year delinquency history that several source blocks sitting
# right next to it already carry -- raw['multi_year_delinquent_tax']['years_delinquent']
# (Buncombe-area multi-year engine) and raw['qpaybill_roll']['years_delinquent']
# (19 SC counties via qPayBill) are both already on the board, just never promoted.
# Measured: 46,037 of 88,927 raw['tax_owed'] rows are sourced from one of these
# multi-year-capable blocks; none of them exposed years_delinquent before this.
# A plain int count, when the source states one directly; _YEARS_LIST_KEYS is the
# fallback (count the years a source lists, e.g. qpaybill_roll['years_unpaid']).
_YEARS_DELINQUENT_KEYS = ("years_delinquent", "matured_years_delinquent")
_YEARS_LIST_KEYS = ("years_unpaid", "years")


def _coerce_year(val) -> Optional[int]:
    """Extract a 4-digit year from int, str, list, or None."""
    if val is None:
        return None
    if isinstance(val, (list, tuple)):
        # bill_years is a list like ['2023', '2024', '2025'] — take the oldest
        for v in sorted(val):
            y = _coerce_year(v)
            if y:
                return y
        return None
    try:
        s = str(val).strip()
        # year_span like "2023-2025" — take the first year
        if "-" in s:
            s = s.split("-")[0].strip()
        y = int(s[:4])
        return y if 1990 <= y <= 2030 else None
    except (ValueError, TypeError):
        return None


def _extract(li: Listing) -> tuple[Optional[float], Optional[str], object]:
    """(balance, kind, year) from a lead's OWN source record, else (None, None, None)."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    src = li.source or ""

    # --- Pass A: explicit source mapping ---
    for sub, (key, fld, kind) in _SOURCES.items():
        if sub in src:
            blk = raw.get(key) or {}
            bal = _money(blk.get(fld))
            if bal:
                year = None
                for yk in _YEAR_KEYS:
                    year = _coerce_year(blk.get(yk))
                    if year:
                        break
                return bal, kind, year

    # --- Pass B: generic scan for any other tax-ish source ---
    # Gate per-BLOCK, not once on the lead's own `src`: a tax-ish raw sub-block
    # can arrive on a lead whose PRIMARY source isn't tax-named at all, when
    # dedupe() merges a tax-delinquent record into a foreclosure/court lead
    # for the same parcel (merge() keeps the bucket-holder's source/source_url,
    # per its own docstring). Found 2026-09-14: a Greenville parcel merged from
    # greenville_mie_adverts (a foreclosure lead) + greenville_delinquent_tax
    # carried a real raw["greenville_delinquent_tax"]["total_due"] that this
    # function silently never saw, because the old gate checked only
    # `li.source` ("greenville_mie_adverts" -- no "tax"/"delinquent"
    # substring) before ever looking at block names. Checking each block's own
    # name is a strict superset of the old behavior: every row that used to
    # match (tax-ish `src`) still does, and non-tax merged-in blocks on an
    # unrelated lead still don't spuriously match on _GENERIC_KEYS alone.
    src_is_taxish = any(k in src for k in _TAXISH)
    for blk_name, blk in raw.items():
        if blk_name == "tax_owed":  # skip pre-existing tax_owed from prior runs
            continue
        if not (src_is_taxish or any(k in blk_name for k in _TAXISH)):
            continue
        if isinstance(blk, dict):
            for gk in _GENERIC_KEYS:
                bal = _money(blk.get(gk))
                if bal:
                    year = None
                    for yk in _YEAR_KEYS:
                        year = _coerce_year(blk.get(yk))
                        if year:
                            break
                    return bal, "delinquent_tax", year

    # --- Pass C: fallback — pre-existing tax_owed balance with year=None ---
    # On board re-runs, source sub-dicts may be stripped but tax_owed survived.
    # Try to find a year in ANY remaining raw sub-dict (lrcpwa, gis, cama, etc.).
    to = raw.get("tax_owed")
    if isinstance(to, dict) and to.get("balance"):
        bal = _money(to["balance"])
        if bal:
            year = None
            # Check lrcpwa (has tax_year from PTS roll)
            for blk_name, blk in raw.items():
                if blk_name == "tax_owed":
                    continue
                if isinstance(blk, dict):
                    for yk in _YEAR_KEYS:
                        year = _coerce_year(blk.get(yk))
                        if year:
                            break
                    if year:
                        break
            return bal, to.get("kind", "delinquent_tax"), year

    return None, None, None


def _find_years_delinquent(raw: dict) -> Optional[int]:
    """How many years delinquent, read from whichever sibling source block already
    carries it (same "don't trust a single block name, scan them all" shape as the
    year search above) -- never computed/invented, only promoted from what a source
    already states. An explicit count key wins; a years-list key's length is the
    fallback (qpaybill_roll['years_unpaid'] is a list of year strings, not a count)."""
    if not isinstance(raw, dict):
        return None
    for blk_name, blk in raw.items():
        if blk_name == "tax_owed" or not isinstance(blk, dict):
            continue
        for k in _YEARS_DELINQUENT_KEYS:
            v = blk.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return int(v)
        for k in _YEARS_LIST_KEYS:
            v = blk.get(k)
            if isinstance(v, list) and v:
                return len(v)
    return None


def enrich_tax_owed(listings: Iterable[Listing]) -> dict:
    if os.environ.get("FORECLOSURE_TAX_OWED", "1") == "0":
        return {"stamped": 0, "skipped": "disabled"}

    listings = list(listings)
    stamped = 0
    index: dict[tuple, dict] = {}

    # Pass 1 — normalize each tax lead's own amount.
    for li in listings:
        bal, kind, year = _extract(li)
        if bal is None:
            continue
        # Preserve existing year if _extract couldn't find one (source sub-dict stripped on re-run)
        if year is None and isinstance(li.raw, dict):
            prev = li.raw.get("tax_owed")
            if isinstance(prev, dict) and prev.get("year"):
                year = prev["year"]
        if not isinstance(li.raw, dict):
            li.raw = {}
        years_delinquent = _find_years_delinquent(li.raw)
        if years_delinquent is None:
            prev = li.raw.get("tax_owed")
            if isinstance(prev, dict) and prev.get("years_delinquent"):
                years_delinquent = prev["years_delinquent"]
        li.raw["tax_owed"] = {
            "balance": bal, "kind": kind, "source": li.source,
            "year": year, "basis": "own_record",
        }
        if years_delinquent is not None:
            li.raw["tax_owed"]["years_delinquent"] = years_delinquent
        stamped += 1
        if (li.parcel_id or "").strip():
            entry = {"balance": bal, "kind": kind, "source": li.source, "year": year}
            if years_delinquent is not None:
                entry["years_delinquent"] = years_delinquent
            index.setdefault(_county_county_key(li), entry)

    # Pass 2 — cross-reference onto same-parcel leads from other sources.
    xref = 0
    for li in listings:
        if not isinstance(li.raw, dict) or li.raw.get("tax_owed"):
            continue
        if not (li.parcel_id or "").strip():
            continue
        hit = index.get(_county_county_key(li))
        if hit:
            li.raw["tax_owed"] = {**hit, "basis": "parcel_cross_ref"}
            xref += 1

    log.info("tax_owed.done", stamped=stamped, cross_referenced=xref,
             parcels_indexed=len(index))
    return {"stamped": stamped, "cross_referenced": xref, "parcels_indexed": len(index)}
