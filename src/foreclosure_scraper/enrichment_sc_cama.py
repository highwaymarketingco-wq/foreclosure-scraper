"""Backfill SC leads with clean CAMA value + specs + condition from the county
Assessor CSV table (sc_assessor_cama). Closes SC valuation parity for counties
whose live GIS value is missing/corrupt (Spartanburg's SCDOT numerics are bad).

Sets market_value (-> ARV tier + assessed-value anchor), year_built/beds/baths
(spec backfill), and raw['cama'] condition (-> distress/property scoring). Only
fills fields that are missing, so it never overwrites better data.
"""
from __future__ import annotations

import structlog

from .models import Listing
from . import sc_assessor_cama as cama

log = structlog.get_logger()


def enrich_sc_cama(listings: list[Listing]) -> dict:
    counties = {(s, c) for (s, c) in cama.SC_CAMA if cama.has_data(s, c)}
    if not counties:
        return {"matched": 0}
    matched = filled_val = 0
    for li in listings:
        if (li.state, li.county) not in counties:
            continue
        rec = cama.lookup(li.state, li.county, parcel_id=li.parcel_id,
                          street_address=li.street_address)
        if not rec:
            continue
        matched += 1
        if not li.market_value and rec.get("market_value"):
            li.market_value = rec["market_value"]
            filled_val += 1
        if not li.year_built and rec.get("year_built"):
            li.year_built = rec["year_built"]
        if li.bedrooms is None and rec.get("beds"):
            li.bedrooms = rec["beds"]
        if li.bathrooms is None and rec.get("baths"):
            li.bathrooms = rec["baths"]
        # Backfill parcel_id from the assessor MAP number when the lead has none,
        # so the on-demand qPublic card enricher (keyed on parcel_id) can resolve
        # address-only Spartanburg leads. map_digits is the dashed-map source.
        if not li.parcel_id and (rec.get("map_digits") or rec.get("tms")):
            li.parcel_id = rec.get("map_digits") or rec.get("tms")
        raw = li.raw if isinstance(li.raw, dict) else {}
        cama_blk = dict(raw.get("cama") or {})
        cama_blk.update({
            "appraised_value": rec.get("market_value"),
            "condition_code": rec.get("condition_code"),
            "condition_distressed": bool(rec.get("condition_distressed")),
            "grade": rec.get("grade"), "building_type": rec.get("building_type"),
            "story_height": rec.get("story_height"),
            "last_sale_date": rec.get("sale_date"), "source": "sc_assessor_csv",
        })
        raw["cama"] = cama_blk
        if rec.get("condition_distressed"):
            raw["distressed"] = True
        li.raw = raw
    log.info("sc_cama.enriched", matched=matched, filled_value=filled_val)
    return {"matched": matched, "filled_value": filled_val}
