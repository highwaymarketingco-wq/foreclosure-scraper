"""Vacant-land-use proxy — a FREE substitute for the paywalled USPS 90-day vacancy feed.

The county parcel layers we already bulk-download into the parcel cache carry a
land-class / land-use field (Rutherford `Land_Class`, Burke/Henderson `LAND_CLASS`,
Spartanburg `LandUse`). Where that field says the parcel is a VACANT / UNDEVELOPED lot,
we stamp a `vacant_lot` distress facet. This is an undeveloped-land signal (feeds the
LAND_WHOLESALE lane + stacks with absentee/tax), distinct from `vacant` (an unoccupied
HOUSE). Pure-local: reads the cache, no network. No-op for un-cached counties.
"""
from __future__ import annotations

import re
from typing import Iterable

import structlog

from .models import Listing
from . import parcel_cache

log = structlog.get_logger(__name__)

# land-class text that means "undeveloped / vacant lot" across the county schemas.
#
# 2026-10-16: the full word was not enough. Scanned every cached county's actual distinct
# land_use strings (288 containing "VAC" in some form) and found 169,077 rows across 99
# (county, land_use) pairs whose assessor abbreviates "vacant" instead of spelling it --
# Charleston alone: '905 - VAC-RES-LOT' 38,782 rows, '952 - VAC-COMM-LOT' 4,859 (the WHOLE
# reason Charleston/Horry/Oconee/Lexington -- fully cached, land_use 99%+ populated -- showed
# ZERO vacant_lot stamps on the board: every one of these rows was silently falling through).
# Other counties' own conventions: 'AG LAND VAC', 'CLASS: RESIDENTIAL - VAC', '7.90-Vacnt
# Ind-OP-SC', 'VACRES/LT-SMLTR/REAR'. \b(...)\b alone catches all of those (a hyphen, slash or
# space is a word boundary) WITHOUT also matching the two real false-positive risks the same
# scan turned up -- 'CRYOVAC BLVD (103.51 ACRES)' (a street name) and a mobile-home serial
# number ending '...S#VAC012120' -- because in both, the letters immediately next to "VAC" are
# ALSO word characters, so \b never fires there. VAC_CAMEL below is the second shape the scan
# found that \b cannot see at all: assessor codes that glue "Vac" straight onto the category
# with NO separator character ('ResVac', 'HOAVac', 'CommVac', 'AgVac', 'ManufVac', 'TCUVac',
# 'MHVac') -- matched by exact case (Title-case "Vac" only, never bare "VAC") specifically so it
# stays out of unrelated all-caps text that merely contains the three letters.
_VACANT_RE = re.compile(r"\b(VACANT|VACNT|UNDEVELOPED|VACRES|VAC)\b", re.I)
_VAC_CAMEL_RE = re.compile(r"[A-Za-z]Vac(?=[A-Z]|[^a-zA-Z]|$)")


def _is_vacant_land_use(lu: str) -> bool:
    return bool(_VACANT_RE.search(lu)) or bool(_VAC_CAMEL_RE.search(lu))


# 2026-10-20: Greenwood and Aiken SC. Both map a `land_use` field confirmed LIVE to carry
# no vacant/improved signal at all, even though -- unlike Horry/Barnwell's bare numeric DOR
# codes -- it is text: Greenwood's PropType is a coarse land-use CATEGORY (Residential/
# Commercial/Farm-Timber/Mobile Home/Multi-Family/Other; live-sampled, zero rows carry a
# "Vacant" bucket) and Aiken's PropertyClassType is the SC 4-6% owner-occupancy ratio class
# spelled out as text (OWNER OCCUPIED RESIDENTIAL/NON-OWNER OCCUPIED RESIDENTIAL/
# AGRICULTURAL/.../NON-QUALIFIED LAND) -- the same kind of field as Barnwell's digit-coded
# PT163_Class, just spelled out; a live full-table LIKE check found ZERO of 103,317 Aiken
# rows contain "VACANT"/"VAC"/"UNDEVELOPED"/"UNIMPROVED" anywhere in it, disproving the
# pasted-document claim that Aiken spells vacancy out in this field. Both counties DO map a
# real improvement-dollar-value field (parcel_cache.py's PARCEL_LAYERS), so they are let
# through the bare-digit gate below to reach that fallback -- scoped to just these two
# counties, not every text land_use, because a real land-use CATEGORY for most other
# counties (e.g. "SINGLE FAMILY RES") is already a complete and correct answer on its own
# and must not be silently reinterpreted (see the test for that invariant).
_TEXT_LANDUSE_SKIP_VACANT_GATE = frozenset({"Greenwood", "Aiken"})

# Greenwood's BuildingValue encodes "no structure" as a database NULL, never a literal 0
# (live-confirmed: `BuildingValue = 0` returns 0 of 39,555 rows; NULL on 17,114 of them).
# Every other improvement_value-mapped county (Horry, Barnwell, Aiken) uses a literal 0 for
# "no improvements" and a genuine NULL there means "no reading" -- which the code below
# correctly stays silent on. Only Greenwood gets NULL reinterpreted as the zero-value
# reading; live correlation check (1,800-row NULL-BuildingValue sample, ground truth
# SqFt>0 or YearBuilt set): 76.1% precision overall (1,108/1,455), but that varies a lot
# by PropType -- Farm/Timber 89.9% (268/298), Residential 86.0% (770/895), Other 75.3%
# (143/190) and Mobile Home 56.7% (174/307) are all well above the 38.1% base rate, but
# Commercial 19.4% (14/72) and Multi-Family 10.5% (4/38) are BELOW it -- worse than a coin
# flip, because a large commercial/multi-unit structure's value is evidently tracked
# somewhere this one field doesn't capture. Those two PropTypes are excluded below; the
# rest are wired in at the existing weak (weight-10, non-attribute) vacant_lot level
# rather than trusted as a hard fact.
_NULL_IMPROVEMENT_VALUE_MEANS_ZERO = frozenset({"Greenwood"})
_GREENWOOD_NULL_IMPROVEMENT_EXCLUDED_PROPTYPES = frozenset({"Commercial", "Multi-Family"})


def _has_cache(memo: dict, county: str, state: str | None) -> bool:
    """A parcel-cache file exists for the county. cached_counties() lists only the dedicated
    PARCEL_LAYERS counties; the other ~60 NC counties are cached off the statewide OneMap layer
    (nc_onemap_cfg) and were skipped here, so their rows never got a land use (Wake's cache holds
    1.74M parcels, all with a land-use value, and 0 board rows used it). State-aware for the
    dual-state names."""
    key = (county, (state or "").upper())
    if key not in memo:
        try:
            memo[key] = parcel_cache._db_path(county, state).exists()  # noqa: SLF001
        except Exception:  # noqa: BLE001 - a dual-state name with no state: nothing cached
            memo[key] = False
    return memo[key]


def enrich_vacant_landuse(listings: Iterable[Listing]) -> dict:
    memo: dict = {}
    stats = {"eligible": 0, "stamped": 0, "land_use_filled": 0, "stamped_by_improvement_value": 0}
    for li in listings:
        pid = (li.parcel_id or "").strip()
        county = (li.county or "").strip()
        if not pid or not county:
            continue
        if (li.state or "").upper() == "NC":
            county = parcel_cache._nc_name_ci(county.replace(" County", "").strip()) or county  # noqa: SLF001
        if not _has_cache(memo, county, li.state):
            continue
        rec = parcel_cache.lookup(county, pid, li.state)
        lu = (rec or {}).get("land_use")
        if not lu:
            continue
        stats["eligible"] += 1
        # The county's own class string is the row's land use. It was only ever stamped inside
        # raw.vacant_lot, so a row that is NOT a vacant lot carried no land use at all and the
        # cube counted vacant_lot as unchecked on it (top-80 2026-10-09: Mecklenburg 5 of 17,733
        # rows, Spartanburg 6,995 of 19,380). The comps pass runs earlier in the same run, so this
        # does not change this run's valuation; Listing.land_use is documented as GIS-backfilled.
        if not (getattr(li, "land_use", None) or "").strip():
            clean = str(lu).strip()
            if clean and not clean.isdigit():
                li.land_use = clean.title() if clean.isupper() else clean
                stats["land_use_filled"] = stats.get("land_use_filled", 0) + 1
        if _is_vacant_land_use(str(lu)):
            if not isinstance(li.raw, dict):
                li.raw = {}
            # idempotent — don't re-stamp on a re-run
            if not li.raw.get("vacant_lot"):
                li.raw["vacant_lot"] = {"land_use": str(lu).strip()[:60], "source": "parcel_cache_landuse"}
                stats["stamped"] += 1
            continue
        # 2026-10-19: a BARE NUMERIC land_use (Horry's DOR code, "101"/"300"/...) never
        # matches the text regex above and never has a published legend (checked live --
        # see parcel_cache.py's improvement_value comment). Fall back to the layer's own
        # improvement-dollar-value field when the cache maps one: zero/no improvement
        # value on a real parcel (acreage or market value present, so this is not a
        # blank/degenerate row) is the same "no structure built" signal this project
        # already uses elsewhere for vacant LAND (see the vacant/condemned investigation's
        # Lincoln/Buncombe note), just read from a dollar field instead of a text flag.
        # Only engages when land_use is ALL DIGITS -- a real text land_use that merely
        # didn't match the VACANT/VAC wordlist is left alone, not silently reinterpreted --
        # UNLESS this county is on the allowlist above (its text land_use is confirmed to
        # carry no vacant/improved signal of its own, live-verified per-county).
        if not str(lu).strip().isdigit() and county not in _TEXT_LANDUSE_SKIP_VACANT_GATE:
            continue
        imprv = (rec or {}).get("improvement_value")
        has_other_signal = (rec or {}).get("market_value") or (rec or {}).get("acreage")
        if (imprv is None and county in _NULL_IMPROVEMENT_VALUE_MEANS_ZERO
                and str(lu).strip() not in _GREENWOOD_NULL_IMPROVEMENT_EXCLUDED_PROPTYPES):
            imprv = 0.0
        if imprv is None or not has_other_signal:
            continue  # no determinate reading -- stay silent, don't guess
        if isinstance(li.raw, dict) and li.raw.get("vacant_lot"):
            continue
        if float(imprv) == 0.0:
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["vacant_lot"] = {"land_use": str(lu).strip()[:60],
                                     "improvement_value": 0,
                                     "source": "parcel_cache_improvement_value"}
            stats["stamped"] += 1
            stats["stamped_by_improvement_value"] += 1
        # improved (imprv > 0): genuinely not a vacant lot. Still record that this row
        # WAS checked (same "a healthy screen that found nothing is still a check"
        # convention gis_fill.py already uses elsewhere) so it reads correctly as
        # improved rather than unchecked.
        elif not (getattr(li, "land_use", None) or "").strip():
            li.land_use = "Improved"
            stats["land_use_filled"] = stats.get("land_use_filled", 0) + 1
    if stats["stamped"] or stats["land_use_filled"]:
        log.info("vacant_landuse.done", **stats)
    return stats
