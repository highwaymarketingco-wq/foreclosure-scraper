"""Pre-write data validation gates.

Run BEFORE listings are persisted to docs/listings.json / Sheet / email.
Catches the audit's recurring data-quality bugs at a single chokepoint:

  * State <-> county mismatch (13 NC counties had wrong-state hits each
    week; 16 still have casing errors — "Mcdowell" vs "McDowell")
  * Numeric out-of-range values (opening_bid=0, tax_value < 5k for
    non-land, sqft > 20k, etc.)
  * Invalid parcel_id formats (deed-book references, < 7 chars)

Strategy: SOFT validation — log warnings, normalize where safe, null
out fields that are demonstrably wrong (rather than dropping the whole
listing — losing leads is worse than presenting flagged data).
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

from .models import Listing, PropertyKind

log = structlog.get_logger()


# ---- canonical NC + SC county sets ------------------------------------------

NC_COUNTIES = frozenset({
    "Alamance","Alexander","Alleghany","Anson","Ashe","Avery","Beaufort","Bertie",
    "Bladen","Brunswick","Buncombe","Burke","Cabarrus","Caldwell","Camden",
    "Carteret","Caswell","Catawba","Chatham","Cherokee","Chowan","Clay",
    "Cleveland","Columbus","Craven","Cumberland","Currituck","Dare","Davidson",
    "Davie","Duplin","Durham","Edgecombe","Forsyth","Franklin","Gaston","Gates",
    "Graham","Granville","Greene","Guilford","Halifax","Harnett","Haywood",
    "Henderson","Hertford","Hoke","Hyde","Iredell","Jackson","Johnston","Jones",
    "Lee","Lenoir","Lincoln","Macon","Madison","Martin","McDowell","Mecklenburg",
    "Mitchell","Montgomery","Moore","Nash","New Hanover","Northampton","Onslow",
    "Orange","Pamlico","Pasquotank","Pender","Perquimans","Person","Pitt","Polk",
    "Randolph","Richmond","Robeson","Rockingham","Rowan","Rutherford","Sampson",
    "Scotland","Stanly","Stokes","Surry","Swain","Transylvania","Tyrrell","Union",
    "Vance","Wake","Warren","Washington","Watauga","Wayne","Wilkes","Wilson",
    "Yadkin","Yancey",
})
SC_COUNTIES = frozenset({
    "Abbeville","Aiken","Allendale","Anderson","Bamberg","Barnwell","Beaufort",
    "Berkeley","Calhoun","Charleston","Cherokee","Chester","Chesterfield",
    "Clarendon","Colleton","Darlington","Dillon","Dorchester","Edgefield",
    "Fairfield","Florence","Georgetown","Greenville","Greenwood","Hampton",
    "Horry","Jasper","Kershaw","Lancaster","Laurens","Lee","Lexington","Marion",
    "Marlboro","McCormick","Newberry","Oconee","Orangeburg","Pickens","Richland",
    "Saluda","Spartanburg","Sumter","Union","Williamsburg","York",
})


def _county_set_for(state: str) -> frozenset[str] | None:
    if state == "NC":
        return NC_COUNTIES
    if state == "SC":
        return SC_COUNTIES
    return None


def _normalize_county(raw: str) -> str:
    """Return the canonical Title-cased county name, stripping suffixes
    and fixing common casing artifacts.

    NC GIS feeds variously return 'MCDOWELL', 'mcdowell', 'Mcdowell' for
    the same county; the canonical form is 'McDowell'. Same for
    'New Hanover' (some sources strip the space)."""
    if not raw:
        return raw
    s = raw.replace(" County", "").strip()
    # Handle compound names (drop trailing comma + state if present)
    s = re.sub(r",\s*[A-Z]{2}\s*$", "", s)
    # Title-case — Python's .title() is wrong for "McDowell" (gives "Mcdowell")
    titled = " ".join(w.capitalize() for w in s.split())
    # Special-cases where simple capitalize() loses information
    fixes = {
        "Mcdowell": "McDowell",
        "Mccormick": "McCormick",
        "Newhanover": "New Hanover",
        "Newhanover County": "New Hanover",
    }
    return fixes.get(titled, titled)


def _validate_state_county(li: Listing, stats: dict) -> None:
    if not li.state or not li.county:
        return
    canonical = _normalize_county(li.county)
    if canonical != li.county:
        # Casing fix — apply silently (no warn).
        li.county = canonical
        stats["county_normalized"] += 1

    counties = _county_set_for(li.state)
    if counties is None:
        return  # state is something we don't track (e.g. test data)
    if li.county not in counties:
        # Cross-state mismatch — null out the bogus county. We KEEP the
        # listing (the address might be valid), just remove the wrong tag
        # so downstream enrichments don't query the wrong-state GIS.
        log.warning(
            "validation.cross_state_county",
            source=li.source, state=li.state,
            county=li.county, case=li.case_number,
        )
        li.county = None
        stats["county_nulled_cross_state"] += 1


# ---- parcel_id ---------------------------------------------------------------

# Patterns that look like parcel IDs but aren't:
#   * < 7 chars: too short to be unique
#   * pure all-zero: GIS placeholder
#   * "BookNNNN-PageNNNN" or just "Book/Page" → recorded-document reference
#     mistakenly captured as parcel
_PARCEL_BAD_PATTERNS = (
    re.compile(r"^0+$"),
    re.compile(r"^\d{1,3}$"),          # 1-3 digit numbers
    re.compile(r"^B\d+P\d+$", re.I),   # B123P456
    re.compile(r"^Book\s*\d+", re.I),
    re.compile(r"^DB\s*\d", re.I),
)


def _validate_parcel_id(li: Listing, stats: dict) -> None:
    pid = (li.parcel_id or "").strip()
    if not pid:
        return
    if len(pid) < 7:
        stats["parcel_nulled_too_short"] += 1
        log.warning("validation.parcel_too_short", source=li.source, pid=pid)
        li.parcel_id = None
        return
    for pat in _PARCEL_BAD_PATTERNS:
        if pat.match(pid):
            stats["parcel_nulled_bad_pattern"] += 1
            log.warning("validation.parcel_bad_pattern", source=li.source, pid=pid)
            li.parcel_id = None
            return


# ---- numeric bounds ----------------------------------------------------------

def _validate_numeric_bounds(li: Listing, stats: dict) -> None:
    # opening_bid: must be > 0 to be meaningful. 0 means "auction not
    # priced yet" or scraper failure; either way it shouldn't drive math.
    if li.opening_bid is not None and li.opening_bid <= 0:
        stats["opening_bid_zeroed"] += 1
        li.opening_bid = None

    # opening_bid > $50M — implausibly large for a foreclosure / lis
    # pendens; almost always a units / formatting error from the scraper.
    if li.opening_bid is not None and li.opening_bid > 50_000_000:
        stats["opening_bid_too_large"] += 1
        log.warning("validation.bid_too_large",
                    source=li.source, bid=li.opening_bid)
        li.opening_bid = None

    # tax_value: < $5k for non-land is suspect (just $300 in one case).
    # Land can legitimately have low tax_value (raw acreage in rural counties).
    if (li.tax_value is not None and li.tax_value > 0
            and li.tax_value < 5_000
            and li.property_kind != PropertyKind.LAND):
        stats["tax_value_too_low"] += 1
        log.warning("validation.tax_value_too_low",
                    source=li.source, tax_value=li.tax_value, kind=li.property_kind)
        li.tax_value = None

    # tax_value > $50M — overflow / units problem.
    if li.tax_value is not None and li.tax_value > 50_000_000:
        stats["tax_value_too_large"] += 1
        li.tax_value = None

    # living_sqft outside (50, 25_000) is suspect. Skip multi-family
    # since some scrapers report aggregate sqft for whole complexes.
    if (li.living_sqft is not None
            and li.property_kind != PropertyKind.MULTI_FAMILY):
        if li.living_sqft <= 0 or li.living_sqft > 25_000:
            stats["sqft_out_of_range"] += 1
            li.living_sqft = None

    # year_built sanity: 1700-2030
    if li.year_built is not None and (li.year_built < 1700 or li.year_built > 2030):
        stats["year_built_out_of_range"] += 1
        li.year_built = None

    # bedrooms / bathrooms
    if li.bedrooms is not None and (li.bedrooms < 0 or li.bedrooms > 30):
        stats["bedrooms_out_of_range"] += 1
        li.bedrooms = None
    if li.bathrooms is not None and (li.bathrooms < 0 or li.bathrooms > 30):
        stats["bathrooms_out_of_range"] += 1
        li.bathrooms = None


# ---- comp validation ---------------------------------------------------------

# Comp `kind` strings vary across feeds (HomeHarvest "sfr", Realtor
# "single_family", county "manufactured" vs PropertyKind "mobile", …).
# Map equivalent labels to a canonical category so legitimate comps
# aren't dropped just because the labels disagree.
_KIND_EQUIVALENT = {
    "sfr": "single_family",
    "single family": "single_family",
    "single-family": "single_family",
    "single_family_residence": "single_family",
    "single family residence": "single_family",
    "house": "single_family",
    "detached": "single_family",
    "single_family": "single_family",
    "multi": "multi_family",
    "multifamily": "multi_family",
    "multi-family": "multi_family",
    "multi_family": "multi_family",
    "duplex": "multi_family",
    "triplex": "multi_family",
    "fourplex": "multi_family",
    "manufactured": "mobile",
    "mobile_home": "mobile",
    "manufactured_home": "mobile",
    "trailer": "mobile",
    "mobile": "mobile",
    "townhome": "townhouse",
    "town_house": "townhouse",
    "townhouse": "townhouse",
    "condominium": "condo",
    "condo": "condo",
    "land": "land",
    "vacant": "land",
    "lot": "land",
}


def _canonical_kind(s: str) -> str:
    s = (s or "").lower().strip()
    return _KIND_EQUIVALENT.get(s, s)


def _validate_comps(li: Listing, stats: dict) -> None:
    if not isinstance(li.raw, dict):
        return
    comps = li.raw.get("comps")
    if not isinstance(comps, list):
        return
    keep = []
    subj_kind = _canonical_kind(
        li.property_kind.value if hasattr(li.property_kind, "value")
        else str(li.property_kind or "")
    )
    for c in comps:
        if not isinstance(c, dict):
            continue
        sp = c.get("sold_price")
        if not isinstance(sp, (int, float)) or sp <= 0 or sp > 5_000_000:
            stats["comps_dropped_price"] += 1
            continue
        ck = _canonical_kind(c.get("kind"))
        # Drop only when both kinds are known AND clearly different
        # categories (improved vs land, stick-built vs mobile, condo vs
        # SFR). Townhouse is allowed against SFR — they trade similarly
        # in the foreclosure-flip context.
        if ck and subj_kind and subj_kind not in ("unknown", "")\
                and ck != subj_kind:
            # Allow townhouse <-> single_family (both are improved
            # detached/semi-detached residential and trade in similar
            # comp pools for flip economics).
            allowed = {
                ("single_family", "townhouse"),
                ("townhouse", "single_family"),
            }
            if (subj_kind, ck) not in allowed:
                stats["comps_dropped_kind_mismatch"] += 1
                continue
        keep.append(c)
    if len(keep) != len(comps):
        li.raw["comps"] = keep
        # Recompute median ppsf from the kept comps so the calculator's
        # ARV path uses validated data.
        ppsfs = [c["price_per_sqft"] for c in keep
                 if isinstance(c.get("price_per_sqft"), (int, float))]
        if ppsfs:
            ppsfs.sort()
            li.raw["comp_median_ppsf"] = ppsfs[len(ppsfs) // 2]
        else:
            li.raw.pop("comp_median_ppsf", None)


# ---- public entry point ------------------------------------------------------

def validate(listings: list[Listing]) -> dict:
    """Apply all validation gates in-place. Returns a stats dict suitable
    for the run summary."""
    stats = {
        "county_normalized": 0,
        "county_nulled_cross_state": 0,
        "parcel_nulled_too_short": 0,
        "parcel_nulled_bad_pattern": 0,
        "opening_bid_zeroed": 0,
        "opening_bid_too_large": 0,
        "tax_value_too_low": 0,
        "tax_value_too_large": 0,
        "sqft_out_of_range": 0,
        "year_built_out_of_range": 0,
        "bedrooms_out_of_range": 0,
        "bathrooms_out_of_range": 0,
        "comps_dropped_price": 0,
        "comps_dropped_kind_mismatch": 0,
    }
    for li in listings:
        _validate_state_county(li, stats)
        _validate_parcel_id(li, stats)
        _validate_numeric_bounds(li, stats)
        _validate_comps(li, stats)
    log.info("validation.done", **stats)
    return stats
