"""Greenville County SC parcel-CAMA ``ROLLBK`` field -> the shared raw['rollback_exposure']
contract enrichment_rollback_deferral.py established and gap_matrix.py's own
checked_columns()/positive_columns() already read.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-20.csv, read before writing a line here).
    rollback_exposure shows sourced-not-built for Greenville (5,510 applicable), source
    "tax/property card: www.greenvillecounty.org", built=no. The next_action column guesses a
    new per-parcel reader is needed. One already exists for a DIFFERENT purpose:
    parcel_cache.py's PARCEL_LAYERS["Greenville"] already bulk-pulls the county's own GCGIS
    parcel layer (arcgis3/.../GreenvilleNJ/QueryLayers/MapServer/0, 244,338 parcels, refreshed
    weekly) for owner/address/value/acreage/sqft. That layer ALSO carries a field named
    ``ROLLBK`` this project's map never read before this change (parcel_cache.py's Greenville
    ``map`` dict had no "rollback_tax" key until this session added one).

    LIVE-VERIFIED 2026-10-20 (county-wide query against the real layer, read-only, no board
    touched): ROLLBK is nonzero on 8,447/244,338 parcels, 1,854/1,902 (97.5%) of every
    PROPTYPE='AGRICULTURAL' parcel among them -- and every nonzero-ROLLBK parcel checked,
    including several whose PROPTYPE reads something other than AGRICULTURAL (e.g. a
    $121,680-taxed parcel billed only $66.46 TOTTAX), carries the exact signature of land taxed
    on a present-use/current-use value rather than its full assessed value. The gate this
    module uses is ``rollback_tax > 0`` itself, never PROPTYPE -- PROPTYPE is the parcel's
    zoning/category label, not a flag for whether the LAND sits under an ag/forestry
    current-use covenant, and several nonzero rows prove the two are not the same thing.

    INDEPENDENTLY CONFIRMED the same day against the county's own per-parcel bill page
    (appsas400/RealProperty/Details.aspx, the SAME page assessor_cards/greenville_sc.py
    already fetches for Greenville leads under ASSESSOR_CARD_ON -- but only for a
    distress-ranked, capped subset of leads per run, which is why THIS module reads the bulk
    parcel_cache instead of that on-demand path): live PIN 0132000100300's VALUE section
    prints three separate labelled lines -- "Fair Market Value:", "Taxable Market Value:" and
    "Total Rollback:". The county's OWN name for this figure is literally "Rollback", not a
    difference between two generically-named value columns this module had to interpret. This
    is the same caliber of evidence Wake's "Total Deferred Value" label and Transylvania's
    "Deferred Value :" line gave this module's siblings -- not the NC PTS Cloud trap (an
    inferred gap between two value columns with no label saying which deferral mechanism
    produced it) enrichment_rollback_deferral.py's own docstring correctly declined to build.

NOT BUILT, investigated the same session, for the other four tax-card/qpaybill counties this
    task named (reported here rather than in four near-duplicate files):
      Spartanburg, Horry (qPayBill) -- RE-VERIFIED LIVE 2026-10-20 (a real search + detail-page
          fetch against both tenants, prefix "A"): the detail page's full label set (26 and 28
          labels respectively) carries "Total Appraisal:" / "Total Assessed:" / "Residential
          Exemption:" / "Homestead Exemption:" / "Other Exemptions:" and NO separate
          present-use/market-value field at all. Confirms enrichment_qpaybill_multiyear_tax.py's
          2026-10-18 finding for this same vendor family (parse_detail() is one function shared
          verbatim by all 29 qpaybill counties); not re-attempted.
      Brunswick NC -- its tax-bill roll (scrapers/counties_nc/nc_its_public_tax.py, the ITSNet
          vendor at tax.brunsco.net, wired 2026-10-08) carries owner/amount/description only, no
          appraised or use-value field of any kind. Its parcel layer (the generic NC OneMap
          NC1Map_Parcels FeatureServer that Wake's own rollback source already reads) returns
          ZERO parusecode IN ('AGR','FOR','HOR') parcels for Brunswick (live count, 2026-10-20),
          and its parusedesc roster (a live 2,000-row sample) is entirely coastal/residential
          land-use codes (SFR OCEAN, TH BEACH, MARSH ACRE, ...) with no agricultural/forestry
          category present at all -- a genuinely coastal county with no real present-use
          farmland inventory to surface, not a missed source.
      Pickens -- its only bulk parcel layer this project reads (parcel_cache.py's
          Pickens_Open_data FeatureServer/6) carries NO value field of any kind (live field
          roster pulled 2026-10-20: owner/address/acres/IMPVAC/zoning/sale price only;
          parcel_cache.py's own existing comment already documents "the layer publishes no
          appraised value, so the honest mapping is None") -- there is no value to compute a
          deferral FROM, a more basic gap than Spartanburg/Horry's. Its delinquent-tax ArcGIS
          layers (scrapers/counties_sc/pickens_delinquent_parcels.py) carry the same shape:
          owner/mailing/situs/amount-due only, never an appraisal.

GATE. Only a positive ``rollback_tax`` from the Greenville parcel cache qualifies --
    ``build_block()`` never invents one, matching every sibling in this family.

Pure, no network: ``parcel_cache.lookup()`` is a local SQLite read against the already
weekly-refreshed cache; the bulk GIS pull that populates it is parcel_cache.py's own existing
refresh job (``scripts/refresh_parcel_cache.py Greenville``), not a new live fetch owned by
this module. Idempotent: a row that already carries raw['rollback_exposure'] is left untouched.
Gate off entirely with FORECLOSURE_GREENVILLE_ROLLBACK=0.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Optional

import structlog

from . import parcel_cache
from .models import Listing

log = structlog.get_logger()

RAW_KEY = "rollback_exposure"
SOURCE_KEY = "greenville_parcel_cama"
#: SC Code 12-43-220(d)(4) -- see enrichment_rollback_deferral.py's module docstring.
ROLLBACK_YEARS_SC = 3

ENABLED = os.environ.get("FORECLOSURE_GREENVILLE_ROLLBACK") != "0"


def _already_done(raw: dict) -> bool:
    return isinstance(raw.get(RAW_KEY), dict)


def _county_of(li: Listing) -> str:
    return (li.county or "").replace(" County", "").strip().lower()


def _positive(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def build_block(cached: dict) -> Optional[dict]:
    """Pure: the raw['rollback_exposure'] record from one parcel_cache row's own
    rollback_tax, or None when it is blank/zero -- never invented."""
    rollback = _positive(cached.get("rollback_tax"))
    if rollback is None:
        return None

    rec: dict[str, Any] = {
        "estimated_rollback": round(rollback, 2),
        "basis": "present_use_deferral",
        "county": "Greenville",
        "state": "SC",
        "source": 'Greenville County GIS parcel layer ("ROLLBK"), confirmed against the '
                  'county\'s own per-parcel bill page ("Total Rollback:")',
        "source_key": SOURCE_KEY,
        "rollback_years": ROLLBACK_YEARS_SC,
        "estimate_is_floor": False,  # the county's own stated figure, not a rate-derived guess
        "match_method": "parcel",
    }
    market = _positive(cached.get("market_value"))
    taxed = _positive(cached.get("tax_value"))
    if market is not None and taxed is not None and market > taxed:
        rec["deferred_value"] = round(market - taxed, 2)
    return rec


def enrich_greenville_rollback_exposure(listings: Iterable[Listing]) -> dict[str, Any]:
    """Walk every Greenville SC board row and look up parcel_cache's own ROLLBK restatement.
    Pure, no network -- the lookup is a local SQLite read against the already-refreshed
    weekly cache."""
    stats = {"targets": 0, "matched": 0, "no_rollback": 0, "no_parcel": 0, "cache_miss": 0}
    if not ENABLED:
        return stats
    for li in listings:
        if _county_of(li) != "greenville" or (li.state or "").upper() != "SC":
            continue
        raw = li.raw
        if not isinstance(raw, dict):
            raw = li.raw = {}
        if _already_done(raw):
            continue
        pid = (li.parcel_id or "").strip()
        if not pid:
            stats["no_parcel"] += 1
            continue
        stats["targets"] += 1
        cached = parcel_cache.lookup("Greenville", pid, "SC")
        if not cached:
            stats["cache_miss"] += 1
            continue
        rec = build_block(cached)
        if rec is None:
            stats["no_rollback"] += 1
            continue
        raw[RAW_KEY] = rec
        stats["matched"] += 1
    log.info("greenville_rollback.done", **stats)
    return stats
