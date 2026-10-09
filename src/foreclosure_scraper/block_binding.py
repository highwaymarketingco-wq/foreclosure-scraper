"""Does a raw[...] block on a row describe THAT row's property, owner or case? Pure, no I/O.

tax_binding.py (2026-10-08) answered this for county property-tax blocks. This module asks the same
question of every OTHER block a scraper or enricher writes: the GIS record, the owner's mailing,
phone and skip trace, the deed chain, assessor card and CAMA facts, photos, court and lien filings,
person matches (jail, obituary, probate, state tax liens). Measured on the 10/7 board (350,013
rows, docs/audit_2026-10-09/block_binding.md) a block is ANOTHER property's record in six ways:

  foreign_county  the block names a county (or state) that is not the row's (Lincoln code cases on
                  Buncombe rows);
  other_parcel    the block names a parcel id of the row's numbering system that is not one of the
                  row's own ids (an owner mailing, skip trace or GIS record of the parcel next door);
  other_address   no comparable id, and the block's situs is a different house or street than the
                  row's (a LiensNC filing for '31 Reed Rd' fused into the '86 Reed Rd' row);
  other_person    a block matched on a PERSON (owner mailing, skip trace, jail booking, obituary,
                  probate, a state tax lien, an SOS entity) names someone who shares no name with
                  the row's owner, while the county roll on the row agrees with the row's owner (or
                  the block also disagrees with the roll);
  shared_copy     the identical block (canonical JSON, volatile timestamps ignored) sits on rows of
                  two or more different properties: kept only where it binds (its parcel is the
                  row's, its named owner is the row's owner, or it is the record of the one owner
                  most of those rows share: a multi-parcel deed, an HOA's lots);
  fallback_point  the row has no parcel id and no house-numbered address of its own and its point
                  is a shared geocoder fallback (a county seat or town centroid, a point 8+ rows
                  share): a block looked up BY THE POINT is the parcel at that centroid's.

scrub_unbound_blocks() removes those blocks (and what was derived from them) from rows in place,
the same contract as tax_binding.scrub_unbound_tax (idempotent, counts only, never raises on an odd
row). A block that is the row's OWN source's record is never removed (when it disagrees with the
row, the row's identity is what is wrong: reported by the audit check, not scrubbed). County
property-tax blocks are tax_binding's and are skipped here.

keep_fresh_blocks() is the merge-precedence half: board_persist.merge_prior_board() folds the prior
board into the fresh scrape with Listing.merge(), whose raw deep-merge lets the PRIOR row's leaves
win; for every block the fresh scrape itself carries, this puts the fresh record back.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any, Iterable, Optional

from .tax_binding import (
    block_from_source,
    count_properties,
    county_key,
    id_relation,
    is_property_tax_block,
    norm_id,
    property_keys,
    row_ids,
    same_county,
    usable_id,
)
from .verification.core import address_key, address_relation

# ---------------------------------------------------------------------------------------------
# What each block describes
# ---------------------------------------------------------------------------------------------

#: area-level blocks: a tract, ZIP, county or the surroundings of a point. Neighbouring rows
#: legitimately carry identical copies; they are not checked here.
AREA_BLOCKS = frozenset({
    "fema_disaster", "flood", "flood_zone", "eviction_market", "census_demographics", "census_rent",
    "hud_fmr", "market_velocity", "opportunity_zone", "foreclosure_sold_comp_summary",
    "recorded_comps", "recorded_sales", "recorded_ratio_comps", "county_sales", "rent_comps_extra",
    "rent_comps", "comps", "foreclosure_sold_comps", "fema_repetitive_loss", "cemetery_proximity",
    "staleness", "epa", "fallback_links", "competition", "storm_damage", "helene",
})

#: this pipeline's own outputs (scores, flags, links, markers), rebuilt from the row every run
DERIVED_BLOCKS = frozenset({
    "flags", "calc", "is_new", "grade", "data_quality", "corroboration", "signal_stack",
    "intent_score", "intent_band", "fullmer", "link_kind", "entity_type", "distress_stack",
    "qa_flags", "first_seen_run", "amount_owed", "condition_tier", "geo_imprecise",
    "property_category", "equity", "derived_signals", "stale_case", "pulled_sale", "tax_aging_high",
    "tax_aging_surfaced", "tax_big_old", "tax_not_yet_late", "tax_owed", "two_year_delinquent",
    "link_check", "strategy_fit", "crm", "owner_name_as_of", "red_flags", "derivation_flags",
    "carryover", "life_events", "life_event", "condition_source", "comps_geo_warning", "comps_note",
    "tax_sale_status", "sale_date_passed", "sale_date_passed_days", "estimated_monthly_rent",
    "estimated_monthly_rent_extra", "rent_median_ppsf", "rent_median_ppsf_extra",
    "comp_median_ppsf", "comp_median_ppsf_recorded", "comp_median_ppa_recorded", "refresh_misses",
    "last_refresh_seen", "link_may_be_stale", "verification", "search_url", "also_seen_in",
    "parcel_id_nulled", "geo_source", "landed_by", "geo_attribution", "situs_address_source",
    "owner_name_source", "document_url", "distressed", "absentee", "absentee_owner", "condemned",
    "multiple_owners", "land_distress", "onemap_resolved", "_resolved_deep_enriched",
    "address_is_approximate", "sold_confirmed", "sold_comp", "superseded_mailing_copies",
    "mailing_address_not_inherited", "exempt_claim_withdrawn", "tax_county_check", "tenure",
    "owner_name_signal", "relationship_signal", "mf_signal", "title_risk", "upset_bid",
    "vision_fetch_failed", "is_new_booking", "outreach", "near_beach_drive", "oceanfront",
    "lead_signals", "case", "item_number", "sale_type", "sale_date", "loan_amount",
    "actual_sold_price", "mtg_file", "zpid", "trulia_id", "reo_id", "vrm_id", "hud_property_id",
    "usda_property_id", "fc_listing_id", "xome_listing_id", "parcel_withdrawn_fallback_point",
    "fhfa_value", "land_ratio", "vacant_lot", "land_use_commercial_hint", "county_backfill",
    "address_was_owner_mailing", "county_was_name_derived", "geocoded_by_name", "geo_missing",
    "parcel_id_alias", "withdrawn_case_type_other", "resolver_conflict_undone",
    # identity.py's provenance (audit 2026-10-09, identity): written by the identity pass
    "merged_records", "twins_collapsed", "unfused", "owner_conflict",
})

#: person blocks: they describe the OWNER (a person or entity), so the same block on two parcels
#: of one owner is right; on parcels of two different owners it is a copy.
PERSON_BLOCKS = frozenset({
    "owner_mailing", "owner_phone", "owner_email", "skip_trace", "sos_agent", "owner_cluster",
    "builder_distress", "liensnc_related", "divorce", "jail_booking", "jail_booking_new",
    "incarceration", "incarceration_check", "bop_check", "bop_federal", "obituary", "probate",
    "sc_probate_notice", "sc_probate_net", "mcdowell_probate", "heir_estate", "heir_candidates",
    "bankruptcy", "courtlistener", "courtlistener_adversary", "bankruptcy_stay",
    "bankruptcy_tax_combo", "sc_state_tax_lien", "resolved_from_name", "rod", "marriage_license",
    "co_defendant_signal", "owner_mismatch", "name_resolution", "notice_contact",
})

#: blocks matched on a PERSON, and the fields that name that person. A block whose person shares
#: no name with the row's owner was attached to someone else's property.
PERSON_NAME_FIELDS: dict[str, tuple[str, ...]] = {
    "jail_booking": ("matched_name", "inmate_name"),
    "incarceration": ("matched_name",),
    "incarceration_check": ("name",),
    "bop_check": ("name",),
    "skip_trace": ("owner_name",),
    "obituary": ("decedent",),
    "probate": ("decedent",),
    "mcdowell_probate": ("ownname", "deceased_owner"),
    "heir_estate": ("owner_of_record",),
    "sos_agent": ("resolved_for_entity",),
    "sc_state_tax_lien": ("owner",),
    "owner_mailing": ("owner", "name"),
    "owner_phone": ("matched_name", "county_owner"),
}

#: field names (lower case) a block states the PROPERTY's county in. A person's mailing county, a
#: newspaper's county or a court's name are not the property's.
COUNTY_FIELDS = ("county", "sitecounty", "county_name", "queried_county", "tenant", "cntyname")
#: field names (lower case) a block states the PROPERTY's state in
STATE_FIELDS = ("state",)
#: field names (lower case) a block names the property's parcel in
ID_FIELDS = ("parcel_id", "pin", "parcel", "pid", "parcelid", "gispin", "pin15", "tms",
             "map_number", "mapnumber", "parcel_number", "parcelnumb", "taxpin", "parcel_raw",
             "county_id", "parcel_key", "pts_number", "parcel_from_map_number", "parno")
#: field names (lower case) a block names the property's situs in
ADDR_FIELDS = ("situs", "situs_text", "property_address", "site_address", "property_location",
               "propertyaddress", "physicaladdr", "matched_situs", "situs_address",
               "matched_address", "siteaddr", "siteadd")
#: field names (lower case) a block names the property's current owner in
OWNER_FIELDS = ("owner", "owner_name", "ownname", "owner_of_record", "cache_owner", "name1",
                "owner1", "county_owner", "owner_text")

#: per block: fields NOT to read although their name is generic (a mailing state is the owner's,
#: a court's or jail's county is where the person was sued or held), and extra fields to read.
BLOCK_SPECS: dict[str, dict] = {
    "owner_mailing": {"skip": ("state", "county", "mail_state"), "owners": ("name",)},
    "skip_trace": {"skip": ("state", "mail_state")},
    "sos_agent": {"skip": ("state", "county")},
    "liensnc_related": {"skip": ("state", "county")},
    "lrcpwa": {"skip": ("state",)},
    "obituary": {"skip": ("county", "state", "home_address")},
    "jail_booking": {"skip": ("county", "state")},
    "jail_booking_new": {"skip": ("county", "state")},
    "incarceration": {"skip": ("state",)},
    "bankruptcy": {"skip": ("state", "county")},
    "courtlistener": {"skip": ("state", "county")},
    "parcel_from_address": {"ids": ("cache_ids",)},
    "liensnc": {"addr": ("address",)},
    "nod": {"addr": ("property_address",)},
    "public_notice": {"skip": ("county", "publication_county", "filtered_county")},
    "column": {"skip": ("county",)},
    "owner_cluster": {"skip": ("county", "state")},
    "heir_estate": {"skip": ("mailing",)},
    # these layers' STATE / CITY / ADDRESS columns are the owner's MAILING address
    "lincoln_vacant": {"skip": ("state",)},
    "gis_attrs_full": {"skip": ("state",)},
    "arcgis_distress": {"skip": ("state",)},
    "state_contamination": {"skip": ("state",), "addr": ("address",)},
    "sc_ust_registry": {"skip": ("state",)},
    "gaston_gis": {"skip": ("state",)},
    "transylvania_vacant": {"skip": ("state",)},
    "mcdowell_probate": {"skip": ("state",)},
}

#: blocks a stage looks up BY THE ROW'S POINT, or derives from one that was (enrichment_gis_attrs
#: point query, enrichment_images tiles, enrichment_vision on those tiles, the footprint at the
#: point, the reverse geocode, the assessor card and CAMA of a point-resolved parcel, the deed chain,
#: last sale and value of that parcel; the agent audit of 2026-10-08 lists the writers).
POINT_BLOCKS = frozenset({
    "gis_attrs_full", "gis", "deed_chain", "last_sale", "cama", "cama_specs", "condition_cama",
    "images", "zillow", "vision", "footprint", "situs_road_only", "parcel_resolution",
    "parcel_from_geo", "assessor_card", "lrcpwa", "assessor_photo", "fhfa_value", "tenure",
    "land_ratio",
})
#: identical copies of these are expected on different properties (neighbouring rows share an aerial
#: tile; an owner cluster is the owner's by construction; one builder's lien-agent filings name the
#: same contact on every lot): the shared test skips them (the fallback-point test still applies)
_SHARED_EXEMPT = frozenset({"images", "zillow", "vision", "owner_cluster", "builder_distress",
                            "liensnc_related", "footprint"})
#: block sources that come from the row's own LiensNC filing (they bind with the 'liensnc' block)
_FILING_SOURCES = ("liensnc_filing",)

#: verdicts under which a block is another property's record
UNBOUND = ("foreign_county", "other_parcel", "other_address", "other_person", "shared_copy",
           "fallback_point")

#: raw['geo_imprecise'] tags that describe a real resolved address (enrichment_geocode)
_PRECISE_GEO_TAGS = ("census_geocode",)
#: a point this many rows share is a geocoder fallback (enrichment_board_quality's own test)
FALLBACK_POINT_MIN_ROWS = 8

_VOLATILE = re.compile(
    r"(_at$|^as_of$|^as_of_|fetched|checked|timestamp|^ts$|days_remaining|_days$|_years$|"
    r"months_since|^in_window$|surfaced|extracted|^first_detected|^last_confirmed|_detected$|"
    r"^confidence_before$)", re.I)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T].*)?$|^\d{1,2}/\d{1,2}/\d{2,4}$|^(19|20)\d{2}$|^(19|20)\d{6}$|^1\d{12}$")
_DIGITS4 = re.compile(r"\d{4,}")
#: keys whose values are area codes or labels, not one property's identifiers
_AREA_KEYS = re.compile(r"(msa|cbsa|zcta|geoid|tract|fips|zip|postal|_code$|^code$|layer|source|"
                        r"provider|basis|method|kind|type|status|class|tier|category|note|reason)", re.I)


def block_kind(name: str) -> str:
    """'area' | 'derived' | 'person' | 'property' (anything else names one property)."""
    if name in AREA_BLOCKS:
        return "area"
    if name in DERIVED_BLOCKS:
        return "derived"
    if name in PERSON_BLOCKS:
        return "person"
    return "property"


def checked(name: str, blk: Any) -> bool:
    """The block is one this module judges: a property or person record, not area, derived or a
    county property-tax block (tax_binding's)."""
    return (isinstance(blk, (dict, list)) and bool(blk) and block_kind(name) in ("property", "person")
            and not is_property_tax_block(name, blk))


def _strip_volatile(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _strip_volatile(x) for k, x in v.items() if not _VOLATILE.search(str(k))}
    if isinstance(v, list):
        return [_strip_volatile(x) for x in v]
    return v


def canonical(blk: Any) -> str:
    """The block's content as one string, keys sorted, volatile timestamps and day counts left out."""
    try:
        return json.dumps(_strip_volatile(blk), sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(blk)


def fingerprint(name: str, blk: Any) -> int:
    """A 63-bit hash of name + canonical(blk): equal content, equal fingerprint."""
    h = hashlib.blake2b((name + "|" + canonical(blk)).encode("utf-8", "replace"), digest_size=8)
    return int.from_bytes(h.digest(), "big") >> 1


def _specific_values(v: Any, depth: int = 0) -> bool:
    """The block holds an identifier of one thing: a string with a run of 4+ digits that is not a
    date or an area code (a parcel id, a bill or instrument number, a phone, a house number, a
    photo tile). Category words, flags, amounts and empty results are not identifiers."""
    if depth > 4:
        return False
    if isinstance(v, dict):
        return any(_specific_values(x, depth + 1) for k, x in v.items()
                   if not _VOLATILE.search(str(k)) and not _AREA_KEYS.search(str(k)))
    if isinstance(v, list):
        return any(_specific_values(x, depth + 1) for x in v[:20])
    if isinstance(v, str):
        s = v.strip()
        if not s or _DATE.match(s):
            return False
        return bool(_DIGITS4.search(s))
    return False


#: fields that describe the PERSON (where they get mail, their phone): one person or one property
#: manager legitimately shares them across many parcels and owners
_PERSON_LEVEL_KEYS = re.compile(r"(mail|phone|email|owner|name|care_of|agent|contact|carrier|line_type|"
                                r"tcpa|consent|dnc|absentee|out_of_state|^street|^city|^state|^zip|"
                                r"corroborated|alternates|alt_phones|additional)", re.I)


def parcel_specific(name: str, blk: Any) -> bool:
    """The block names something that belongs to ONE property (a parcel id, a situs, a deed or
    instrument reference, a bill or account number, a photo), not only a person's mailing address,
    phone or email (which many parcels of one owner, or of one property manager, share)."""
    if not isinstance(blk, (dict, list)) or not blk:
        return False
    if isinstance(blk, dict):
        p = probe(name, blk)
        if p["ids"] or p["addrs"]:
            return True
        rest = {k: v for k, v in blk.items() if not _PERSON_LEVEL_KEYS.search(str(k))}
        return _specific_values(rest)
    return _specific_values(blk)


def is_specific(name: str, blk: Any) -> bool:
    """A block that names one property, person or case (an identifier, an owner or a situs), not
    an empty result, a category or a flag: only such a block is too specific to sit, identical,
    on two different properties by coincidence."""
    if not isinstance(blk, (dict, list)) or not blk:
        return False
    if isinstance(blk, dict):
        p = probe(name, blk)
        if p["ids"] or p["addrs"] or any(name_tokens(o) for o in p["owners"] + p["person"]):
            return True
    return _specific_values(blk)


def writer(blk: Any) -> str:
    """Who wrote the block, as the block itself says (source / provider / layer / match)."""
    if not isinstance(blk, dict):
        return "-"
    for k in ("source", "provider", "source_key", "layer", "registry", "backend", "strategy", "match"):
        v = blk.get(k)
        if isinstance(v, str) and v.strip():
            return f"{k}={v.strip()[:48]}"
    return "-"


# ---------------------------------------------------------------------------------------------
# What a block states
# ---------------------------------------------------------------------------------------------

_PHOTO_PATH = re.compile(r"parcel_photos/([a-z]+)_([0-9A-Za-z.\-]+?)\.(?:jpe?g|png|webp)", re.I)
_SPATIALEST = re.compile(r"prc-([a-z]+)\.spatialest\.com/#/property/([0-9A-Za-z]+)", re.I)


def _fields(blk: dict, names: Iterable[str], skip: Iterable[str]) -> list:
    want = set(names) - {s.lower() for s in skip}
    return [v for k, v in blk.items() if str(k).lower() in want]


def _strs(vals: Iterable[Any]) -> list[str]:
    out = []
    for v in vals:
        if isinstance(v, (list, tuple)):
            out += [str(x).strip() for x in v if isinstance(x, (str, int)) and not isinstance(x, bool)
                    and str(x).strip()]
        elif isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip():
            out.append(str(v).strip())
    return out


def probe(name: str, blk: Any) -> dict:
    """What the block states about the property it describes:
    {'county': [..], 'state': [..], 'ids': [..], 'addrs': [..], 'owners': [..], 'person': [..]}.
    Only top-level fields are read (a list of comps or instruments names other properties)."""
    out = {"county": [], "state": [], "ids": [], "addrs": [], "owners": [], "person": []}
    if not isinstance(blk, dict):
        return out
    spec = BLOCK_SPECS.get(name, {})
    skip = spec.get("skip", ())
    out["county"] = [c for c in _strs(_fields(blk, COUNTY_FIELDS, skip)) if county_key(c)]
    out["state"] = [s.upper() for s in _strs(_fields(blk, STATE_FIELDS, skip))
                    if len(s.strip()) == 2 and s.isalpha()]
    ids = _strs(_fields(blk, ID_FIELDS + tuple(spec.get("ids", ())), skip))
    out["ids"] = [i for i in ids if usable_id(norm_id(i))]
    out["addrs"] = [a for a in _strs(_fields(blk, ADDR_FIELDS + tuple(spec.get("addr", ())), skip))
                    if any(ch.isdigit() for ch in a)]
    out["owners"] = _strs(_fields(blk, OWNER_FIELDS + tuple(spec.get("owners", ())), skip))
    out["person"] = _strs(blk.get(f) for f in PERSON_NAME_FIELDS.get(name, ()))
    # a photo or assessor card names the county and parcel in its URL
    for v in (blk.get("photo"), blk.get("primary"), blk.get("source_url"), blk.get("file")):
        if not isinstance(v, str):
            continue
        m = _PHOTO_PATH.search(v) or _SPATIALEST.search(v)
        if m:
            out["county"].append(m.group(1))
            if usable_id(norm_id(m.group(2))):
                out["ids"].append(m.group(2))
    return out


# ---------------------------------------------------------------------------------------------
# Owner names
# ---------------------------------------------------------------------------------------------

_NAME_NOISE = frozenset({
    "JR", "SR", "II", "III", "IV", "LE", "ETUX", "ETAL", "ET", "UX", "AL", "THE", "AND", "HEIRS",
    "HEIR", "OF", "DECEASED", "DECD", "ESTATE", "ESTATES", "TRUSTEE", "TRUSTEES", "TRUST", "AKA",
    "FKA", "NKA", "DBA", "MRS", "LIFE", "REVOCABLE", "IRREVOCABLE", "LIVING", "FAMILY", "TEN",
    "WROS", "HUSBAND", "WIFE", "SURVIVOR", "SURVIVORSHIP", "ENTIRETY", "TENANTS", "COMMON",
    "UNKNOWN", "OWNER", "OWNERS", "CURRENT", "OCCUPANT", "NONE", "TBD", "SAME", "LLC", "INC",
    "CORP", "COMPANY", "MR", "ATTN", "CARE", "LTD", "PLLC",
})
_NAME_PLACEHOLDER = re.compile(r"^\s*(unknown|unknown owner|owner|current owner|occupant|n/?a|none|"
                               r"tbd|not available|no owner|see deed)\s*$", re.I)


def name_tokens(name: Any) -> frozenset:
    """Identity-bearing tokens of a person or entity name (3+ letters, no suffix or role words)."""
    s = str(name or "").upper()
    if not s.strip() or _NAME_PLACEHOLDER.match(s):
        return frozenset()
    return frozenset(t for t in re.split(r"[^A-Z0-9]+", s)
                     if len(t) >= 3 and t not in _NAME_NOISE and not t.isdigit())


def names_disagree(a: Any, b: Any) -> bool:
    """Two names with identity tokens on both sides and none in common."""
    ta, tb = name_tokens(a), name_tokens(b)
    return bool(ta and tb and not (ta & tb))


#: blocks whose owner IS the county roll's (the strongest owner source on a row)
ROLL_OWNER_BLOCKS = ("gis", "gis_attrs_full", "lrcpwa", "qpaybill_roll", "lincoln_vacant",
                     "gaston_gis", "transylvania_vacant", "greenville_distress")


def _get(row: Any, name: str):
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _raw(row: Any) -> dict:
    raw = _get(row, "raw")
    return raw if isinstance(raw, dict) else {}


#: owner_mailing writers that read the county's own parcel roll or layer (its owner is the roll's)
ROLL_MAILING_SOURCES = frozenset({"county_gis", "nc_onemap", "scdot_sc", "sc_assessor_roll",
                                  "county_tax_roll", "lincoln_county_gis", "transylvania_county_gis",
                                  "greenville_tax_parcel_layer", "pickens_delinquent_roll"})


def roll_owners(row: Any) -> list[str]:
    raw = _raw(row)
    out = []
    for b in ROLL_OWNER_BLOCKS:
        blk = raw.get(b)
        if isinstance(blk, dict):
            out += probe(b, blk)["owners"]
    om = raw.get("owner_mailing")
    if isinstance(om, dict) and str(om.get("source") or "") in ROLL_MAILING_SOURCES:
        out += probe("owner_mailing", om)["owners"]
    return out


def row_owner_strength(row: Any) -> str:
    """'roll' when the row's owner agrees with a county-roll block on the row, 'contradicted' when
    every roll owner disagrees with it, 'unbacked' with no roll owner, 'none' with no row owner."""
    own = _get(row, "owner_name")
    if not name_tokens(own):
        return "none"
    rolls = [o for o in roll_owners(row) if name_tokens(o)]
    if not rolls:
        return "unbacked"
    if any(not names_disagree(own, o) for o in rolls):
        return "roll"
    return "contradicted"


# ---------------------------------------------------------------------------------------------
# Relations between a block and its row
# ---------------------------------------------------------------------------------------------

def county_relation(row: Any, name: str, p: dict) -> str:
    """'other_county' | 'other_state' | 'same' | 'unknown' for what the block states."""
    rc, rs = _get(row, "county"), str(_get(row, "state") or "").upper()
    if p["state"] and rs and not any(s == rs for s in p["state"]):
        return "other_state"
    if p["county"] and rc:
        if any(same_county(c, rc) for c in p["county"]):
            return "same"
        return "other_county"
    return "unknown"


def parcel_relation(row: Any, p: dict) -> str:
    """'other_parcel' | 'other_address' | 'same' | 'unknown' (tax_binding's id and address rules)."""
    rel = id_relation(p["ids"], row_ids(row)) if p["ids"] else "no_key"
    if rel == "same":
        return "same"
    if rel == "different":
        return "other_parcel"
    addr = _get(row, "street_address")
    rels = [address_relation(addr, a) for a in p["addrs"]]
    if "match" in rels:
        return "same"
    if "conflict" in rels:
        return "other_address"
    return "unknown"


def owner_relation(row: Any, name: str, p: dict) -> str:
    """'other_owner' | 'same' | 'unknown' between the owner/person the block names and the row's
    owner_name (the matched person for person blocks, the stated owner for property blocks)."""
    own = _get(row, "owner_name")
    names = [n for n in p["person"] + p["owners"] if name_tokens(n)]
    if not names or not name_tokens(own):
        return "unknown"
    if any(not names_disagree(own, n) for n in names):
        return "same"
    return "other_owner"


def own_source_block(row: Any, name: str, blk: Any) -> bool:
    """The block is the record of the row's own (primary) source, or of the row's own LiensNC filing
    for the person blocks built from it."""
    src = _get(row, "source")
    if block_from_source(name, src):
        return True
    if isinstance(blk, dict) and str(blk.get("source") or "") in _FILING_SOURCES:
        return "liensnc" in str(src or "")
    return False


def _point(row: Any) -> Optional[tuple]:
    lat, lng = _get(row, "latitude"), _get(row, "longitude")
    try:
        return (round(float(lat), 5), round(float(lng), 5))
    except (TypeError, ValueError):
        return None


def imprecise_point(row: Any, shared_points: Optional[set] = None) -> bool:
    """The row's coordinate is a geocoder fallback, not its own location: flagged imprecise
    (enrichment_geocode.imprecise_point_flag), a county-seat centroid, or one of `shared_points`
    (a point FALLBACK_POINT_MIN_ROWS or more rows share)."""
    from .enrichment_geocode import imprecise_point_flag, is_county_seat_point
    raw = _raw(row)
    if imprecise_point_flag(raw):
        return True
    pt = _point(row)
    if pt is None:
        return False
    return is_county_seat_point(pt[0], pt[1]) or bool(shared_points and pt in shared_points)


def own_location(row: Any) -> bool:
    """The row has a parcel id or a house-numbered address of its own (not one a parcel record
    found at its point wrote: raw['situs_address_source'] 'gis_parcel_situs')."""
    if row_ids(row):
        return True
    num, street, _ = address_key(_get(row, "street_address"))
    if not (num and street):
        return False
    return str(_raw(row).get("situs_address_source") or "") != "gis_parcel_situs"


def shared_points(rows: Iterable[Any], min_rows: int = FALLBACK_POINT_MIN_ROWS) -> set:
    n = Counter(p for p in (_point(r) for r in rows) if p is not None)
    return {p for p, c in n.items() if c >= min_rows}


#: contact blocks a LiensNC filing writes with no name of their own (liensnc_handoff: the filing's
#: "Owner" section); the person they belong to is the one that section names
FILING_CONTACT_BLOCKS = ("owner_phone", "owner_email")


def filing_persons(row: Any, name: str, blk: Any) -> list[str]:
    """The owner a LiensNC filing names (first line of raw['liensnc']['owner_text']) for a contact
    block built from that filing, else []. WHY (audit 2026-10-09, phones_lost): a lien-agent
    appointment's "Owner" section is often the BUILDER or contractor who filed it; their phone was
    judged only by the filing's address, so it stayed on the homeowner's row (one builder's phone on
    100+ rows) or, once the address matched, would have been restored there."""
    if name not in FILING_CONTACT_BLOCKS or not isinstance(blk, dict) \
            or str(blk.get("source") or "") not in _FILING_SOURCES:
        return []
    lien = _raw(row).get("liensnc")
    if not isinstance(lien, dict):
        return []
    first = str(lien.get("owner_text") or "").strip().split("\n")[0].strip()
    return [first] if name_tokens(first) else []


def filing_contact_value(name: str, blk: Any) -> Optional[str]:
    """The phone (10 digits) or e-mail (lower case) of a contact block a LiensNC filing wrote, else
    None. WHY (audit 2026-10-09, phones_lost): a builder or pool company puts its own number in the
    "Owner" section of every lien-agent appointment it files; on 34 rows of 6 different owners the
    'self-filed' phone was the contractor's. The shared test now reads these by value."""
    if name not in FILING_CONTACT_BLOCKS or not isinstance(blk, dict) \
            or str(blk.get("source") or "") not in _FILING_SOURCES:
        return None
    if name == "owner_phone":
        d = re.sub(r"\D", "", str(blk.get("phone") or ""))[-10:]
        return d if len(d) == 10 else None
    e = str(blk.get("email") or "").strip().lower()
    return e or None


#: a filing phone is the filer's line only when the filings carrying it name this many different
#: owners (two are often one owner and their LLC)
FILER_LINE_MIN_OWNERS = 3


def filing_line_rows(members: list[tuple[int, frozenset]]) -> set:
    """The filer's-line test for ONE filing phone or e-mail value. `members`: (row index, tokens of
    the owner the row's filing names, filing_persons) of every row carrying the value.
      * one owner named on at least half of those filings (2+ of them: a builder on its own lots,
        an owner on their own filings) keeps it, except on the rows whose filing names someone else;
      * else, filings naming FILER_LINE_MIN_OWNERS or more different owners: the value is the
        filer's (a pool company, a permit service) on everybody's appointment and leaves every row;
      * else (two names: often one owner and their company) it stays.
    Returns the row indexes it is removed from."""
    named = [(i, t) for i, t in members if t]
    if len(named) < 2:
        return set()
    group: set = set()
    for _i, t in named[:50]:
        g = {j for j, u in named if u & t}
        if len(g) > len(group):
            group = g
    if len(group) >= 2 and 2 * len(group) >= len(named):
        return {i for i, _t in named if i not in group}
    clusters: list[set] = []
    for _i, t in named:
        hit = next((c for c in clusters if c & t), None)
        if hit is None:
            clusters.append(set(t))
        else:
            hit |= t
        if len(clusters) >= FILER_LINE_MIN_OWNERS:
            return {i for i, _t in members}
    return set()


def _judges_person(name: str, blk: Any) -> bool:
    return name in PERSON_NAME_FIELDS or (name in FILING_CONTACT_BLOCKS and isinstance(blk, dict)
                                          and str(blk.get("source") or "") in _FILING_SOURCES)


def _person_disagrees(row: Any, name: str, blk: Any, strength: Optional[str],
                      roll_only: bool = False) -> bool:
    """The person a person-matched block names shares no name with the row's owner, and (when the
    row's owner disagrees with the county roll) none with the roll's owner either. `roll_only`:
    only when the row's owner is the county roll's (a filing's own contact on a row with no roll
    owner is the best owner information the row has)."""
    if not isinstance(blk, dict):
        return False
    persons = [n for n in _strs(blk.get(f) for f in PERSON_NAME_FIELDS.get(name, ())) if name_tokens(n)]
    if not persons:
        persons = filing_persons(row, name, blk)
    own = _get(row, "owner_name")
    if not persons or not name_tokens(own) or not all(names_disagree(own, n) for n in persons):
        return False
    st = strength or row_owner_strength(row)
    if roll_only and st != "roll":
        return False
    rolls = [o for o in roll_owners(row) if name_tokens(o)] if st == "contradicted" else []
    return not any(not names_disagree(r, n) for r in rolls for n in persons)


def block_verdict(row: Any, name: str, blk: Any, *, strength: Optional[str] = None,
                  fallback: Optional[bool] = None) -> tuple[str, dict]:
    """(verdict, probe) for one block on its row, without the cross-row shared test: one of UNBOUND
    (except 'shared_copy'), or 'own_source' (the row's own record: never removed), 'bound' (a
    parcel, address or owner ties it to the row) or 'unknown' (nothing contradicts it)."""
    p = probe(name, blk) if isinstance(blk, dict) else {"county": [], "state": [], "ids": [],
                                                        "addrs": [], "owners": [], "person": []}
    if own_source_block(row, name, blk):
        # the row's own record stays, except a contact built from its LiensNC filing that names a
        # filer (a builder, a contractor) the county roll on the row says is not the owner
        filing = isinstance(blk, dict) and str(blk.get("source") or "") in _FILING_SOURCES
        if not (filing and _judges_person(name, blk) and _person_disagrees(row, name, blk, strength, roll_only=True)):
            return "own_source", p
        return "other_person", p
    cr = county_relation(row, name, p)
    if cr in ("other_county", "other_state"):
        return "foreign_county", p
    pr = parcel_relation(row, p)
    if pr == "other_parcel":
        return "other_parcel", p
    if pr == "other_address":
        return "other_address", p
    if _judges_person(name, blk) and _person_disagrees(row, name, blk, strength):
        return "other_person", p
    if pr == "same":
        return "bound", p
    if fallback is None:
        fallback = imprecise_point(row) and not own_location(row)
    if fallback and name in POINT_BLOCKS:
        return "fallback_point", p
    if owner_relation(row, name, p) == "same":
        return "bound", p
    return "unknown", p


# ---------------------------------------------------------------------------------------------
# The scrub
# ---------------------------------------------------------------------------------------------

def _dependents(raw: dict, removed: dict) -> list[str]:
    """Blocks derived from a removed block that go with it: the deed chain, value estimate and
    tenure of a removed GIS last sale; the contact blocks of a removed LiensNC filing or of a
    removed bulk-document OCR."""
    out = []
    ls_amounts = set()
    for n in ("gis", "last_sale"):
        b = removed.get(n)
        if isinstance(b, dict):
            ls = b.get("last_sale") if n == "gis" else b
            if isinstance(ls, dict) and isinstance(ls.get("amount"), (int, float)):
                ls_amounts.add(round(float(ls["amount"]), 2))
    dc = raw.get("deed_chain")
    if "gis" in removed and isinstance(dc, dict):
        tr = dc.get("transfers")
        if isinstance(tr, list) and tr and all(isinstance(t, dict) and t.get("source") == "gis.last_sale"
                                                for t in tr):
            out.append("deed_chain")
    fv = raw.get("fhfa_value")
    if isinstance(fv, dict) and isinstance(fv.get("sale_price"), (int, float)) and \
            (round(float(fv["sale_price"]), 2) in ls_amounts or "last_sale" in removed):
        out.append("fhfa_value")
    if ("last_sale" in removed or "gis" in removed) and "tenure" in raw and "deed_chain" in out:
        out.append("tenure")
    if "liensnc" in removed:
        for n in ("owner_mailing", "owner_phone", "skip_trace", "owner_email"):
            b = raw.get(n)
            if isinstance(b, dict) and str(b.get("source") or "") in _FILING_SOURCES:
                out.append(n)
        for n in ("liensnc_related", "builder_distress"):
            if n in raw:
                out.append(n)
    if "ocr_extraction" in removed:
        for n in ("owner_phone", "owner_email"):
            b = raw.get(n)
            if isinstance(b, dict) and str(b.get("source") or "").startswith("ocr_"):
                out.append(n)
    return [n for n in out if n in raw and n not in removed]


def _dominant_owner(members: list[tuple[int, frozenset]]) -> set:
    """Of (row index, owner tokens) pairs: the rows whose owner is the one owner most of them share
    (a multi-parcel deed, an HOA's lots): at least 2 rows and at least half of them; else empty."""
    toks = [(i, t) for i, t in members if t]
    best: set = set()
    for _, t in toks[:50]:
        grp = {i for i, u in toks if u & t}
        if len(grp) > len(best):
            best = grp
    if len(best) >= 2 and 2 * len(best) >= len(members):
        return best
    return set()


def row_verdicts(row: Any, points: Optional[set] = None) -> list[tuple[str, str, Optional[int], bool]]:
    """[(block name, verdict, fingerprint or None, block names an owner)] for every block this module
    judges on `row` (checked()). The fingerprint is set for a specific block the shared test reads.
    A LiensNC filing's phone / e-mail has none: scrub_unbound_blocks reads those by value
    (filing_line_rows)."""
    raw = _raw(row)
    out: list[tuple[str, str, Optional[int], bool]] = []
    if not raw:
        return out
    try:
        strength = row_owner_strength(row)
        fb = imprecise_point(row, points) and not own_location(row)
    except Exception:  # noqa: BLE001
        strength, fb = None, False
    for name, blk in list(raw.items()):
        try:
            if not checked(name, blk):
                continue
            v, p = block_verdict(row, name, blk, strength=strength, fallback=fb)
            fp = None
            named = any(name_tokens(n) for n in p["owners"] + p["person"])
            if name not in _SHARED_EXEMPT and (named or parcel_specific(name, blk)) \
                    and not (isinstance(blk, dict) and str(blk.get("source") or "") in _FILING_SOURCES):
                fp = fingerprint(name, blk)
            out.append((name, v, fp, named))
        except Exception:  # noqa: BLE001 - an unreadable block is not evidence either way
            continue
    return out


def shared_unbound(members: list[tuple[int, str, frozenset, frozenset]], named: bool) -> set:
    """The shared test for ONE fingerprint. `members`: (row index, verdict, property keys, owner
    tokens) of every row carrying the identical block. When they are 2+ different properties
    (tax_binding.count_properties), the block stays only where it binds: its parcel or situs is the
    row's, the owner it names is the row's owner ('bound'), the row's own source wrote it, or (a
    block naming nobody) the row is one of the one owner most of the copies share. Returns the
    row indexes it is removed from."""
    if len(members) < 2 or count_properties([m[2] for m in members]) < 2:
        return set()
    dominant = set() if named else _dominant_owner([(m[0], m[3]) for m in members])
    return {i for i, v, _k, _t in members if v not in ("bound", "own_source") and i not in dominant}


def removal_reason(verdict: str, in_shared_unbound: bool) -> Optional[str]:
    if verdict in UNBOUND:
        return verdict
    return "shared_copy" if in_shared_unbound else None


def _clear_footprint_sqft(row: Any, fp_blk: Any) -> bool:
    """A removed building footprint's estimated living area also leaves the row (the footprint
    enricher fills living_sqft only when the row had none, and flags it estimated)."""
    if not isinstance(fp_blk, dict):
        return False
    est = fp_blk.get("est_living_sqft")
    if est is None or not _get(row, "living_sqft_estimated"):
        return False
    try:
        same = abs(float(_get(row, "living_sqft") or 0) - float(est)) < 1
    except (TypeError, ValueError):
        return False
    if not same:
        return False
    for f, v in (("living_sqft", None), ("living_sqft_estimated", False)):
        if isinstance(row, dict):
            row[f] = v
        else:
            try:
                setattr(row, f, v)
            except Exception:  # noqa: BLE001 - a model that refuses None keeps its value
                return False
    return True


def remove_blocks(row: Any, reasons: dict[str, str], stats: Optional[dict] = None,
                  record: Optional[list] = None, idx: Optional[int] = None) -> int:
    """Remove `reasons` ({block name: reason}) and the blocks derived from them from `row`."""
    raw = _raw(row)
    removed: dict = {}
    for name, reason in reasons.items():
        if name not in raw:
            continue
        removed[name] = raw.pop(name)
        if name == "footprint" and _clear_footprint_sqft(row, removed[name]) and stats is not None:
            stats["by_reason"]["footprint_sqft_cleared"] += 1
        if stats is not None:
            stats["by_reason"][reason] += 1
            stats["by_block"][f"{name}:{reason}"] += 1
        if record is not None:
            record.append((idx, name, reason))
    if not removed:
        return 0
    for dep in _dependents(raw, removed):
        removed[dep] = raw.pop(dep)
        if stats is not None:
            stats["by_reason"]["derived_from_removed"] += 1
            stats["by_block"][f"{dep}:derived_from_removed"] += 1
        if record is not None:
            record.append((idx, dep, "derived_from_removed"))
    if stats is not None:
        stats["blocks_removed"] += len(removed)
    return len(removed)


#: per-row rounds: removing one block can change what the rest bind to (the row's owner strength)
MAX_ROUNDS = 4


def scrub_row(row: Any, verdicts: list, stats: Optional[dict], record: Optional[list],
              idx: int, *, unbound: set, points: Optional[set]) -> int:
    """Remove from `row` the blocks its verdicts (and the shared test's `unbound` {(row index,
    fingerprint)}) mark, then re-judge the row alone until nothing more goes (MAX_ROUNDS)."""
    n = 0
    vs = verdicts
    for rnd in range(MAX_ROUNDS):
        reasons = {}
        for name, v, fp, _named in vs:
            r = removal_reason(v, rnd == 0 and fp is not None and (idx, fp) in unbound)
            if r:
                reasons[name] = r
        if not reasons:
            break
        if rnd < MAX_ROUNDS - 1 and "other_person" in reasons.values() \
                and any(r != "other_person" for r in reasons.values()):
            # a person verdict leans on the row's owner strength, which a block leaving in this same
            # round may have set (a roll owner read from another parcel's record): remove the other
            # blocks first and judge the people again (audit 2026-10-09, phones_lost: the roll
            # owner's own phone left a row because an unbound block made the row's owner look rolled)
            reasons = {k: r for k, r in reasons.items() if r != "other_person"}
        n += remove_blocks(row, reasons, stats, record, idx)
        vs = row_verdicts(row, points)
    if n and stats is not None:
        stats["rows_scrubbed"] += 1
        stats["by_county"][f"{_get(row, 'state') or ''}:{county_key(_get(row, 'county'))}"] += 1
    return n


def scrub_unbound_blocks(listings: Iterable[Any], record: Optional[list] = None,
                         points: Optional[set] = None) -> dict:
    """Remove from every row the property and person blocks that are another property's record
    (block_verdict, plus the shared-copy test across `listings`) and what was derived from them.
    In place; idempotent; never raises on an odd row. Returns counts (no names, no addresses):
      rows_scrubbed, blocks_removed, by_reason, by_block (block:reason), by_county.
    `record`, when given, receives one (row index, block name, reason) per removal."""
    rows = list(listings)
    if points is None:
        try:
            points = shared_points(rows)
        except Exception:  # noqa: BLE001 - no shared points is the lenient side
            points = set()
    stats: dict = {"rows_scrubbed": 0, "blocks_removed": 0, "by_reason": Counter(),
                   "by_block": Counter(), "by_county": Counter()}
    verdicts = [row_verdicts(row, points) for row in rows]
    holders: dict[int, list[int]] = defaultdict(list)
    named_fp: dict[int, bool] = {}
    for i, vs in enumerate(verdicts):
        for _name, _v, fp, named in vs:
            if fp is not None:
                holders[fp].append(i)
                named_fp[fp] = named
    unbound: set[tuple[int, int]] = set()
    for fp, members in holders.items():
        uniq = sorted(set(members))
        if len(uniq) < 2:
            continue
        info = []
        for i in uniq:
            v = next((v for _n, v, f, _x in verdicts[i] if f == fp), "unknown")
            try:
                keys = property_keys(rows[i], i)
            except Exception:  # noqa: BLE001
                keys = frozenset({("r", i)})
            info.append((i, v, keys, name_tokens(_get(rows[i], "owner_name"))))
        unbound |= {(i, fp) for i in shared_unbound(info, named_fp.get(fp, False))}
    # a LiensNC filing's phone / e-mail by value (filing_line_rows; audit 2026-10-09 phones_lost)
    lines: dict[tuple[str, str], list] = defaultdict(list)
    for i, row in enumerate(rows):
        raw = _raw(row)
        for name in FILING_CONTACT_BLOCKS:
            try:
                v = filing_contact_value(name, raw.get(name))
                if v:
                    fo = filing_persons(row, name, raw.get(name))
                    lines[(name, v)].append((i, name_tokens(fo[0]) if fo else frozenset()))
            except Exception:  # noqa: BLE001
                continue
    filer_lines: dict[int, dict[str, str]] = defaultdict(dict)
    for (name, _v), members in lines.items():
        if len(members) >= 2:
            for i in filing_line_rows(members):
                filer_lines[i][name] = "shared_copy"
    for i, row in enumerate(rows):
        try:
            k = remove_blocks(row, filer_lines[i], stats, record, i) if i in filer_lines else 0
            if not scrub_row(row, verdicts[i], stats, record, i, unbound=unbound, points=points) and k:
                stats["rows_scrubbed"] += 1
                stats["by_county"][f"{_get(row, 'state') or ''}:{county_key(_get(row, 'county'))}"] += 1
        except Exception:  # noqa: BLE001
            continue
    stats["by_reason"] = dict(stats["by_reason"])
    stats["by_block"] = dict(stats["by_block"].most_common(40))
    stats["by_county"] = dict(stats["by_county"].most_common(25))
    return stats


# ---------------------------------------------------------------------------------------------
# Merge precedence (board_persist.merge_prior_board)
# ---------------------------------------------------------------------------------------------

#: raw keys where the PRIOR copy is the one to keep or merge_prior_board handles them itself
PRIOR_WINS = frozenset({"also_seen_in", "carryover", "first_seen_run", "pulled_sale", "stale_case",
                        "verification", "is_new"})


def _deep_fresh(prior: Any, fresh: Any) -> Any:
    """Deep merge where FRESH leaves win and the prior only fills keys the fresh block lacks."""
    if isinstance(prior, dict) and isinstance(fresh, dict):
        out = dict(prior)
        for k, v in fresh.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = _deep_fresh(out[k], v)
            elif v is not None or k not in out:
                out[k] = copy.deepcopy(v)
        return out
    return copy.deepcopy(fresh) if fresh is not None else prior


def blocks_conflict(row: Any, name: str, a: Any, b: Any) -> bool:
    """Two versions of one block describe different records: different parcels of one numbering
    system, different counties, or different house-numbered addresses."""
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return False
    pa, pb = probe(name, a), probe(name, b)
    if pa["ids"] and pb["ids"] and id_relation(pa["ids"], pb["ids"]) == "different":
        return True
    if pa["county"] and pb["county"] and not any(same_county(x, y) for x in pa["county"] for y in pb["county"]):
        return True
    rels = [address_relation(x, y) for x in pa["addrs"] for y in pb["addrs"]]
    return bool(rels) and "match" not in rels and "conflict" in rels


def keep_fresh_blocks(fresh: Any, merged: Any) -> dict:
    """After `merged = fresh.merge(prior)` (board_persist): Listing.merge() deep-merges raw with
    the PRIOR row's leaves winning, so a re-scraped record (a new balance, a new status, a moved
    upset bid, a corrected owner) lost to last run's copy, and a prior copy of ANOTHER record was
    blended into the fresh one. For every raw key the fresh scrape carries (merge_prior_board runs
    before any enricher, so these are the scrapers' own records): the fresh version wins; a prior
    version of the same record only fills keys the fresh one lacks, and a prior version of a
    different record (blocks_conflict) is dropped. In place on `merged`. Returns counts."""
    fr = _raw(fresh)
    mr = _raw(merged)
    out = {"fresh_block_kept": 0, "fresh_block_whole": 0}
    if not fr or not isinstance(mr, dict):
        return out
    for k, fv in fr.items():
        if k in PRIOR_WINS or fv is None:
            continue
        mv = mr.get(k)
        if mv == fv:
            continue
        if isinstance(fv, dict) and isinstance(mv, dict):
            if blocks_conflict(fresh, k, fv, mv):
                mr[k] = copy.deepcopy(fv)
                out["fresh_block_whole"] += 1
            else:
                new = _deep_fresh(mv, fv)
                if new == mv:
                    continue
                mr[k] = new
        else:
            mr[k] = copy.deepcopy(fv)
        out["fresh_block_kept"] += 1
    return out
