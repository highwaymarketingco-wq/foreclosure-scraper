"""Hurricane Helene structural-damage enrichment (TIME-SENSITIVE).

Stamps ``raw['storm_damage'] = {damage_level, estimated_loss, occupancy,
source, ...}`` on any lead whose parcel_id or street address matches a
public county/FEMA post-Helene damage-assessment layer. A destroyed /
major-damage structure on a distressed parcel is one of the strongest
motivated-seller signals we can attach, but these public layers are being
actively curated and will decay — pull them while they're live.

Compliant sources only (open ArcGIS REST FeatureServers, no auth / no
CAPTCHA / no ToS-scrape wall). Live-verified 2026-07-02:

  * Spartanburg SC — Property_Damage_Assessments/25 (1531, Palmetto+Red Cross)
    and Palmetto_Property_Damage/2 (696). Both carry Parcel_ID + full Address +
    Building_Damage + Estimated_Loss; Palmetto also carries Occupancy_type.
  * Henderson NC — HC_DamageAssessments2024_PublicView/24 (19,571; 16,923
    parcel-keyed). Carries PARCELID + TYPDAMAGE (Affected/Minor/Major/Destroyed)
    + STRLOSS (structure-loss $) + HOMETYPE. No street-address column, so this
    one joins by parcel only.
  * Buncombe NC — NC_BuncombeCnty_PPDR_Dashboard_Helene_RT2024/0 (1461). A
    Private-Property-Debris-Removal parcel join: pin + Address + the
    residential/commercial flag + service requested + ROE status.
  * Buncombe NC — HeleneCombinedDamageAssessmentResults_Clipped/0 (10,973;
    10,532 pin-keyed). THE AUTHORITATIVE PLACARD SOURCE: the countywide
    combined ATC-45 posting roll — red 1,542 / yellow 5,728 / green 3,693,
    plus a substantial_damage_determination (734 "yes") that is the FEMA
    50%-rule trigger, use/entry restrictions, and detailed-eval flags. Keyed
    on pinnum + structure_address. Live-verified 2026-08-03.
  * Buncombe NC — Accela/MapServer/7 (10,723 rows; 7,643 with a pin). The
    permit-system view of the same event: DamageType = DESTROYED (758 w/ pin)
    / MAJOR DAMAGE / INUNDATED / LANDSLIDE / MINOR DAMAGE-AFFECTED. Parcel
    join only (no address column). objectIdField is null on this layer, so
    pagination REQUIRES orderByFields (see ``order_by`` below) — without it
    the service 400s on any resultOffset request.

The two Buncombe layers ADD to (never replace) the PPDR layer: measured
against the live board, repointing off PPDR onto the placards would have
dropped 76 already-matched leads while gaining 306, so all three run and the
worst-damage-wins collision rule picks the strongest signal per parcel.

PRIVACY: the placard layer also carries ``building_contact_info`` (owner /
occupant phone + email). That column is deliberately NOT requested — the
outFields list is enumerated explicitly and never ``*``.

Each source is a single ArcGIS FeatureServer layer we page through ONCE into
memory (a few thousand rows), build parcel + address indexes, then match each
listing locally. Two shared-host services -> a couple of paginated GETs total,
so this is cheap and polite (the http_client per-host throttle still applies).

Rutherford / McDowell / Polk: their live Helene layers (the statewide SARCOP
"Helen Work Map" InundatedBuildings layers + the county recovery dashboards)
are FLOOD-INUNDATION footprints — "parcels with flooding" polygons keyed by an
address-number, with HAZUS coded building attributes but NO per-structure
damage rating and NO estimated-loss field. That is a different (weaker) signal
than the structural damage-assessment schema this enricher stamps, so those
counties are intentionally NOT wired here; a flood-footprint enricher is a
separate future build (slips to GATHER).
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx
import structlog

from .http_client import client
from .models import Listing, _normalize_addr, _normalize_parcel

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_HELENE_DAMAGE_OFF"

# ---- Source registry -------------------------------------------------------
#
# Each entry is one ArcGIS FeatureServer layer + a field map onto the common
# storm_damage schema. ``join`` says which keys we can match on for that layer
# ("parcel", "address", or both). Field names are the LIVE attribute names
# verified against each layer's ?f=json schema on 2026-07-02.

SOURCES: list[dict[str, Any]] = [
    {
        "key": "spartanburg_palmetto",
        "label": "Spartanburg County Palmetto Property Damage (Helene 2024)",
        "url": (
            "https://services6.arcgis.com/YJV3IFNXuNHJDIvn/ArcGIS/rest/services/"
            "Palmetto_Property_Damage/FeatureServer/2/query"
        ),
        "parcel_field": "Parcel_ID",
        "addr_field": "Address",
        "damage_field": "Building_Damage",
        "loss_field": "Estimated_Loss",
        "occupancy_field": "Occupancy_type",
        "structure_field": "Structure_Type",
        "zip_field": "Zip_Code",
        "join": ("parcel", "address"),
        "county": "Spartanburg",
        "state": "SC",
    },
    {
        "key": "spartanburg_assessments",
        "label": "Spartanburg County Property Damage Assessments (Palmetto + Red Cross, Helene 2024)",
        "url": (
            "https://services6.arcgis.com/YJV3IFNXuNHJDIvn/ArcGIS/rest/services/"
            "Property_Damage_Assessments/FeatureServer/25/query"
        ),
        "parcel_field": "Parcel_ID",
        "addr_field": "Address",
        "damage_field": "Building_Damage",
        "loss_field": "Estimated_Loss",
        "occupancy_field": None,          # not on this layer
        "structure_field": "Structure_Type",
        "zip_field": "Zip_Code",
        "join": ("parcel", "address"),
        "county": "Spartanburg",
        "state": "SC",
    },
    {
        "key": "henderson_damage_2024",
        "label": "Henderson County Damage Assessments 2024 (Helene)",
        "url": (
            "https://services.arcgis.com/apTfC6SUmnNfnxuF/arcgis/rest/services/"
            "HC_DamageAssessments2024_PublicView/FeatureServer/24/query"
        ),
        "parcel_field": "PARCELID",
        "addr_field": None,               # no street-address column on this layer
        "damage_field": "TYPDAMAGE",
        "loss_field": "STRLOSS",
        "occupancy_field": "HOMETYPE",
        "structure_field": "HOMETYPE",
        "zip_field": None,
        "join": ("parcel",),
        "county": "Henderson",
        "state": "NC",
        # Only rows that are actually a structure damage rating are useful; the
        # layer also holds roadway/utility inspection rows with TYPDAMAGE like
        # "Inaccessible" and no parcel.
        "where": "PARCELID IS NOT NULL",
    },
    {
        "key": "buncombe_ppdr",
        "label": "Buncombe County PPDR Helene Right-of-Entry Parcels",
        "url": (
            "https://services.arcgis.com/HdtZMT2FmI4wPzTM/arcgis/rest/services/"
            "NC_BuncombeCnty_PPDR_Dashboard_Helene_RT2024/FeatureServer/0/query"
        ),
        "parcel_field": "pin",
        "addr_field": "Address",
        # No single damage-severity column; the presence of a debris/demo PPDR
        # request IS the damage signal. We derive a level from the requested
        # service + residential flag in _derive_buncombe_level().
        "damage_field": None,
        "loss_field": None,
        "occupancy_field": "Was_this_Property_Residential_o",
        "structure_field": "Was_this_Property_Residential_o",
        "zip_field": "Zipcode",
        "join": ("parcel", "address"),
        "county": "Buncombe",
        "state": "NC",
        "where": "pin IS NOT NULL",
        "extra_fields": ("What_Service_are_you_Requesting", "Status",
                         "Was_this_Property_Residential_o"),
    },
    {
        "key": "buncombe_placards",
        "label": "Buncombe County Combined Helene Damage Assessment (ATC-45 placards)",
        "url": (
            "https://services6.arcgis.com/VLA0ImJ33zhtGEaP/arcgis/rest/services/"
            "HeleneCombinedDamageAssessmentResults_Clipped/FeatureServer/0/query"
        ),
        "parcel_field": "pinnum",
        "addr_field": "structure_address",
        # red / yellow / green ATC-45 posting, ranked in _DAMAGE_RANK below.
        "damage_field": "posting",
        "loss_field": None,               # no dollar loss on this layer
        "occupancy_field": "primary_occupancy_type",
        "structure_field": "structure_type",
        "zip_field": None,
        "join": ("parcel", "address"),
        "county": "Buncombe",
        "state": "NC",
        # NOTE: building_contact_info (owner/occupant phone+email) is
        # intentionally omitted — we never pull personal contact data off a
        # damage-assessment layer.
        "extra_fields": ("use_and_entry_restrictions_as_w",
                         "detailed_evals_recommended_for",
                         "substantial_damage_determinatio",
                         "Source"),
    },
    {
        "key": "buncombe_accela_damage",
        "label": "Buncombe County Accela Helene Damage Parcels (permit system)",
        "url": "https://gis.buncombenc.gov/arcgis/rest/services/Accela/MapServer/7/query",
        "parcel_field": "pin",
        "addr_field": None,               # layer carries pin + DamageType only
        "damage_field": "DamageType",
        "loss_field": None,
        "occupancy_field": None,
        "structure_field": None,
        "zip_field": None,
        "join": ("parcel",),
        "county": "Buncombe",
        "state": "NC",
        "where": "pin IS NOT NULL AND pin<>''",
        # objectIdField is null on this MapServer layer: any resultOffset
        # request 400s ("Pagination request requires either orderBy field or
        # the layer/table needs to have OID Field") unless orderByFields is set.
        "order_by": "pin",
        "page_size": 1000,
    },
]

# Normalize the many damage-severity spellings across layers onto one ladder so
# downstream scoring can rank them. Higher = worse.
_DAMAGE_RANK = {
    "destroyed": 5,
    "major damage": 4,
    "major": 4,
    "minor damage": 2,
    "minor": 2,
    "affected": 1,
    "inaccessible": 1,
    "unaffected": 0,
    # Buncombe Accela DamageType spellings.
    "natural disaster - destroyed": 5,
    "natural disaster - major damage": 4,
    "natural disaster - inundated": 3,
    "natural disaster - landslide": 3,
    "natural disaster - minor damage/affected": 2,
    # Buncombe ATC-45 placard postings. Red = unsafe (do not enter), yellow =
    # restricted use, green = inspected & usable. Slotted between the county
    # damage words so a red placard outranks a "minor damage" row but not an
    # outright "destroyed" determination.
    "red": 4,
    "yellow": 3,
    "green": 1,
}

# ATC-45 placard postings we treat as a real structure posting. The layer also
# holds a handful of road/access rows ("access point - open" / "- cloes") that
# are not building assessments and carry no seller signal.
_PLACARD_POSTINGS = {"red", "yellow", "green"}


def _rank(level: Optional[str]) -> int:
    if not level:
        return -1
    return _DAMAGE_RANK.get(str(level).strip().lower(), 0)


def _rec_rank(rec: Optional[dict[str, Any]]) -> int:
    """Severity of a built record, used to pick a winner on key collisions.

    A FEMA substantial-damage determination outranks every plain severity
    word, so a yellow-placard structure that was nonetheless found >=50%
    damaged beats a bare red placard from another layer.
    """
    if not rec:
        return -1
    r = _rank(rec.get("damage_level"))
    if rec.get("substantial_damage") is True:
        r += 10
    return r


def _clean(v: Any) -> Optional[str]:
    if v in (None, "", "<Null>"):
        return None
    s = str(v).strip()
    return s or None


def _to_float(v: Any) -> Optional[float]:
    if v in (None, "", "<Null>"):
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None
    # Guard against sentinel junk (e.g. HAZUS -8888 no-data) and negatives.
    if f <= 0 or f > 5e8:
        return None
    return f


def _derive_buncombe_level(attrs: dict[str, Any]) -> Optional[str]:
    """Buncombe PPDR has no severity column. A right-of-entry for debris/demo
    removal is itself the storm-damage signal; a demolition request is the
    strongest tier we can infer, debris the next."""
    svc = (_clean(attrs.get("What_Service_are_you_Requesting")) or "").lower()
    if "demo" in svc:
        return "Demolition Requested"
    if "debris" in svc:
        return "Debris Removal Requested"
    # A recorded ROE with no service string still means an inspected damaged
    # property entered the PPDR program.
    return "PPDR Enrolled"


async def _fetch_layer(c: httpx.AsyncClient, src: dict[str, Any]) -> list[dict[str, Any]]:
    """Page an ArcGIS FeatureServer layer fully into memory (attributes only)."""
    out: list[dict[str, Any]] = []
    out_fields = [f for f in (
        src.get("parcel_field"), src.get("addr_field"), src.get("damage_field"),
        src.get("loss_field"), src.get("occupancy_field"), src.get("structure_field"),
        src.get("zip_field"),
    ) if f]
    out_fields.extend(src.get("extra_fields", ()))
    # NEVER "*": some of these layers carry personal contact columns
    # (the placard layer's building_contact_info), so a source with no
    # enumerated fields is a config bug, not a reason to widen the request.
    fields_param = ",".join(dict.fromkeys(out_fields))
    if not fields_param:
        log.warning("helene.no_out_fields", key=src["key"])
        return out
    where = src.get("where", "1=1")
    offset = 0
    page = int(src.get("page_size", 2000))
    while True:
        params = {
            "where": where,
            "outFields": fields_param,
            "returnGeometry": "false",
            "resultOffset": offset,
            "resultRecordCount": page,
            "f": "json",
        }
        # Layers whose objectIdField is null reject any paged request unless an
        # explicit sort is supplied.
        if src.get("order_by"):
            params["orderByFields"] = src["order_by"]
        try:
            r = await c.get(src["url"], params=params, timeout=40.0)
            if r.status_code != 200:
                log.warning("helene.fetch_status", key=src["key"], code=r.status_code)
                break
            data = r.json()
            if "error" in data:
                log.warning("helene.fetch_error", key=src["key"],
                            error=str(data.get("error"))[:200])
                break
            feats = data.get("features", [])
            out.extend(f.get("attributes", {}) or {} for f in feats)
            if len(feats) < page or not data.get("exceededTransferLimit"):
                break
            offset += page
            if offset >= 60000:  # safety cap
                break
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("helene.fetch_fail", key=src["key"], error=str(exc)[:200])
            break
    return out


def _index_source(src: dict[str, Any], rows: list[dict[str, Any]]
                  ) -> tuple[dict[str, dict], dict[str, dict]]:
    """Build normalized parcel + address indexes for one source's rows.

    On a key collision keep the WORST damage (highest rank) so the strongest
    signal wins — the same parcel can appear in both Spartanburg layers.
    """
    by_parcel: dict[str, dict] = {}
    by_addr: dict[str, dict] = {}
    can_parcel = "parcel" in src["join"] and src.get("parcel_field")
    can_addr = "address" in src["join"] and src.get("addr_field")

    for attrs in rows:
        rec = _build_record(src, attrs)
        if rec is None:
            continue
        rank = _rec_rank(rec)
        if can_parcel:
            pk = _normalize_parcel(attrs.get(src["parcel_field"]))
            if pk:
                cur = by_parcel.get(pk)
                if cur is None or rank > _rec_rank(cur):
                    by_parcel[pk] = rec
        if can_addr:
            ak = _normalize_addr(_clean(attrs.get(src["addr_field"])))
            if ak:
                cur = by_addr.get(ak)
                if cur is None or rank > _rec_rank(cur):
                    by_addr[ak] = rec
    return by_parcel, by_addr


def _build_record(src: dict[str, Any], attrs: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Map one raw ArcGIS row onto the storm_damage schema."""
    if src["key"] == "buncombe_ppdr":
        level = _derive_buncombe_level(attrs)
    else:
        level = _clean(attrs.get(src["damage_field"])) if src.get("damage_field") else None

    if src["key"] == "buncombe_placards":
        # Drop the road/access-point rows — not a structure posting.
        if (level or "").lower() not in _PLACARD_POSTINGS:
            return None

    loss = _to_float(attrs.get(src["loss_field"])) if src.get("loss_field") else None
    occ = _clean(attrs.get(src["occupancy_field"])) if src.get("occupancy_field") else None
    structure = _clean(attrs.get(src["structure_field"])) if src.get("structure_field") else None

    # A row with no severity AND no loss AND no occupancy carries no signal.
    if not level and loss is None and not occ:
        return None

    rec = {
        "damage_level": level,
        "estimated_loss": loss,
        "occupancy": occ,
        "source": src["label"],
        "source_key": src["key"],
        "structure_type": structure,
        "county": src["county"],
        "state": src["state"],
    }
    if src.get("addr_field"):
        rec["matched_address"] = _clean(attrs.get(src["addr_field"]))

    if src["key"] == "buncombe_placards":
        rec["placard"] = (level or "").lower()
        # substantial_damage_determination == yes is the FEMA/NFIP 50%-rule
        # finding: repair cost >= 50% of market value, which forces the owner
        # to bring the whole structure to current code (or demolish) before it
        # can be reoccupied. That is the single hardest sell-instead-of-repair
        # trigger this layer carries.
        sub = (_clean(attrs.get("substantial_damage_determinatio")) or "").lower()
        if sub in ("yes", "no"):
            rec["substantial_damage"] = sub == "yes"
        rec["entry_restrictions"] = _clean(attrs.get("use_and_entry_restrictions_as_w"))
        rec["detailed_eval_recommended"] = _clean(attrs.get("detailed_evals_recommended_for"))
        rec["assessment_program"] = _clean(attrs.get("Source"))
    return rec


def _county_match(li: Listing, src: dict[str, Any]) -> bool:
    """Only match a listing against a source in the same county+state, to keep
    parcel/address collisions across counties from cross-contaminating."""
    if li.state and src.get("state") and li.state.upper() != src["state"].upper():
        return False
    lc = (li.county or "").replace(" County", "").strip().lower()
    if not lc:
        # No county on the lead — allow the match (state already agreed) so we
        # don't drop a legit hit just because county wasn't populated upstream.
        return True
    return lc == src["county"].lower()


async def enrich_with_helene_damage(listings: list[Listing]) -> dict[str, int]:
    """Stamp raw['storm_damage'] on listings that match a Helene damage layer.

    Returns a small stats dict for the per-run health artifact.
    """
    stats = {"targets": 0, "matched_parcel": 0, "matched_address": 0, "matched": 0}
    if os.environ.get(ENV_OFF):
        return stats
    if not listings:
        return stats

    # Which counties are even present in this batch? Skip fetching a source
    # whose county has zero leads (e.g. an all-coastal run never touches
    # Henderson/Buncombe).
    present = set()
    for li in listings:
        c = (li.county or "").replace(" County", "").strip().lower()
        st = (li.state or "").upper()
        if c:
            present.add((c, st))
    active = [
        s for s in SOURCES
        if not present or (s["county"].lower(), s["state"].upper()) in present
    ]
    if not active:
        log.info("helene.no_relevant_counties")
        return stats

    # Load every active source once, build indexes.
    parcel_idx: dict[str, list[tuple[dict, dict]]] = {}  # key -> [(src, rec)]
    addr_idx: dict[str, list[tuple[dict, dict]]] = {}
    async with client(timeout=40.0) as c:
        for src in active:
            rows = await _fetch_layer(c, src)
            log.info("helene.source_loaded", key=src["key"], rows=len(rows))
            by_parcel, by_addr = _index_source(src, rows)
            for k, rec in by_parcel.items():
                parcel_idx.setdefault(k, []).append((src, rec))
            for k, rec in by_addr.items():
                addr_idx.setdefault(k, []).append((src, rec))

    if not parcel_idx and not addr_idx:
        log.info("helene.no_index")
        return stats

    for li in listings:
        # Only consider leads in a county we actually loaded a source for.
        candidate_srcs = [s for s in active if _county_match(li, s)]
        if not candidate_srcs:
            continue
        stats["targets"] += 1
        allowed_keys = {s["key"] for s in candidate_srcs}

        best: Optional[dict] = None
        best_via = None

        # 1) Parcel join (strongest — no false positives from fuzzy street match)
        pk = _normalize_parcel(li.parcel_id)
        if pk:
            for src, rec in parcel_idx.get(pk, ()):
                if src["key"] in allowed_keys and (
                    best is None or _rec_rank(rec) > _rec_rank(best)
                ):
                    best, best_via = rec, "parcel"

        # 2) Address join (only if parcel didn't hit)
        if best is None and li.street_address:
            ak = _normalize_addr(li.street_address)
            if ak:
                for src, rec in addr_idx.get(ak, ()):
                    if src["key"] in allowed_keys and (
                        best is None or _rec_rank(rec) > _rec_rank(best)
                    ):
                        best, best_via = rec, "address"

        if best is None:
            continue

        if not isinstance(li.raw, dict):
            li.raw = {}
        payload = dict(best)
        payload["match_method"] = best_via
        li.raw["storm_damage"] = payload
        stats["matched"] += 1
        if best_via == "parcel":
            stats["matched_parcel"] += 1
        else:
            stats["matched_address"] += 1

    log.info("helene.done", **stats)
    return stats
