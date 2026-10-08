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


# Public alias — the orchestrator runs a final county-normalization pass with
# this right before the post-enrichment dedupe, so late enrichments that assign
# li.county (reverse-geo, parcel-pin, aggressive-address) can't reintroduce the
# 'Mcdowell' vs 'McDowell' split that validate() fixed earlier in the pipeline.
def normalize_county(raw: str) -> str:
    return _normalize_county(raw)


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


#: Counties whose OWN parcel numbers are shorter than the 7-character floor below, by the shapes
#: measured to be that county's parcel number (audit 2026-10-09, drops_lineage). The 2026-10-08
#: run nulled 20,030 short ids; every nulled id on its dot_ocr checkpoint (21,248 rows carrying
#: raw['parcel_id_nulled']) was looked up in the county's parcel cache (NC OneMap parno / altparno /
#: nparno, data/parcel_cache) and the cache's situs house number compared with the row's:
#:   Cleveland 4-5 digits   648 rows, 100% in the county layer, 544 same house / 27 another
#:   Onslow 6 digits and map-block forms ('312-96', '43E-34', '28-9.1')  752 rows, 99.3% in the
#:                          layer, 646 same house / 8 another
#:   Nash 6 digits          237 rows, 100%, 235 same house / 1 another
#:   Rowan 6 digits          67 rows, 100%, 67 same house
#: 1,704 rows in all (LiensNC 662, nc_its_public_tax 355, Rocky Mount survey 229, NC UST 167, ...).
#: These ids ARE the parcel: nulling them published the row with no parcel id. NOT here, measured:
#: Catawba (the county list's tax ACCOUNT number, 0 of 5,376 in the layer), Guilford / Beaufort /
#: Madison PTS Cloud ids (0% in the layer), Buncombe STR permit ids and Burke storm-layer ids (0%);
#: Pitt and Hyde PTS ids (Pitt 5-digit 95% in the layer but 4-digit 0%, Hyde 64-94%; the rows carry
#: no house number to confirm, and the 13 Pitt rows that do all disagree); Polk map forms (97% in the
#: layer, 11% another house);
#: Durham 6 digits (86%); Lincoln and Rutherford, where the owner chose the 10-digit PIN with the
#: short id kept as an alias (parcel_alias.py, 2026-10-07).
COUNTY_NATIVE_SHORT_PARCEL = {
    ("NC", "Cleveland"): re.compile(r"^\d{4,5}$"),
    ("NC", "Onslow"): re.compile(r"^(?:\d{6}|\d{1,4}[A-Z]?-\d{1,3}(?:\.[0-9A-Z]{1,2})?)$", re.I),
    ("NC", "Nash"): re.compile(r"^\d{6}$"),
    ("NC", "Rowan"): re.compile(r"^\d{6}$"),
}


def county_native_short_parcel(state: Optional[str], county: Optional[str], pid: Optional[str]) -> bool:
    """True when `pid`, shorter than 7 characters, has the shape of the county's own parcel number
    (COUNTY_NATIVE_SHORT_PARCEL), so it must be kept rather than nulled as too short. Pure."""
    pat = COUNTY_NATIVE_SHORT_PARCEL.get(((state or "").strip().upper(), _normalize_county(county or "")))
    p = (pid or "").strip()
    return bool(pat and p and pat.match(p))


def _record_nulled_parcel(li: Listing, pid: str, reason: str) -> None:
    """Keep the id the source gave in raw['parcel_id_nulled'] when it is nulled here. It is
    still that source's identifier for the row (Catawba's tax account '65771'), and the next
    run's re-scrape carries it as parcel_id again: board_persist.merge_prior_board() rebuilds the
    published row's key from it, or it never matches its own re-scrape (2026-10-06)."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["parcel_id_nulled"] = {"value": pid, "reason": reason}


def _normalize_parcel_text(v) -> str:
    return re.sub(r"[^0-9a-z]", "", str(v or "").lower())


def _nulled_record(li: Listing) -> Optional[dict]:
    n = li.raw.get("parcel_id_nulled") if isinstance(li.raw, dict) else None
    return n if isinstance(n, dict) else None


def _validate_parcel_id(li: Listing, stats: dict) -> None:
    pid = (li.parcel_id or "").strip()
    nulled = _nulled_record(li)
    if not pid:
        # A county-native id an earlier run nulled (a carried row the re-scrape did not refresh):
        # put it back, the row has no other parcel id (audit 2026-10-09).
        val = str((nulled or {}).get("value") or "").strip()
        if (nulled and nulled.get("reason") == "too_short"
                and county_native_short_parcel(li.state, li.county, val)):
            li.parcel_id = val
            li.raw.pop("parcel_id_nulled", None)
            stats["parcel_restored_county_native"] += 1
        return
    if len(pid) < 7 and county_native_short_parcel(li.state, li.county, pid):
        stats["parcel_kept_county_native"] += 1
        # a merged-in prior copy's record of nulling this same id is stale now
        if nulled and _normalize_parcel_text(nulled.get("value")) == _normalize_parcel_text(pid):
            li.raw.pop("parcel_id_nulled", None)
        return
    if len(pid) < 7:
        stats["parcel_nulled_too_short"] += 1
        log.warning("validation.parcel_too_short", source=li.source, pid=pid)
        _record_nulled_parcel(li, pid, "too_short")
        li.parcel_id = None
        return
    for pat in _PARCEL_BAD_PATTERNS:
        if pat.match(pid):
            stats["parcel_nulled_bad_pattern"] += 1
            log.warning("validation.parcel_bad_pattern", source=li.source, pid=pid)
            _record_nulled_parcel(li, pid, "bad_pattern")
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
    for the run summary.

    Per-listing isolation: each listing is validated inside try/except.
    A malformed record can't poison validation for the rest of the batch
    (the original implementation would short-circuit the loop on the first
    bad listing; downstream calc/grade then ran on un-validated data).
    """
    stats = {
        "county_normalized": 0,
        "county_nulled_cross_state": 0,
        "parcel_nulled_too_short": 0,
        "parcel_nulled_bad_pattern": 0,
        "parcel_kept_county_native": 0,
        "parcel_restored_county_native": 0,
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
        "validation_exceptions": 0,
    }
    for li in listings:
        try:
            _validate_state_county(li, stats)
            _validate_parcel_id(li, stats)
            _validate_numeric_bounds(li, stats)
            _validate_comps(li, stats)
        except Exception as exc:  # noqa: BLE001
            stats["validation_exceptions"] += 1
            log.warning(
                "validation.per_listing_failed",
                source=getattr(li, "source", None),
                source_url=getattr(li, "source_url", None),
                error=str(exc),
            )
    log.info("validation.done", **stats)
    return stats
